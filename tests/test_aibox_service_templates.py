"""aibox Linux service templates and lifecycle tooling (deploy/aibox, SPEC-retirement-update s9).

Every test here uses isolated fixtures: templates are rendered into tmp_path, launch plans are
computed with --dry-run semantics (no exec), `/proc`, the cgroup tree, `systemctl` and `docker`
are fake directories and fake runners. No unit is installed, enabled, started or stopped, and no
live Docker container or Fleet store is read. The one real-host check is `systemd-analyze verify`
on rendered files in tmp_path, which is skipped (and says so) where that binary is absent.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "deploy" / "aibox" / "zeus_aibox_service.py"
REVISION = "a" * 40


def load_tool():
    spec = importlib.util.spec_from_file_location("zeus_aibox_service", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


svc = load_tool()


def render_args(tmp_path: Path, **overrides) -> SimpleNamespace:
    (tmp_path / "cfg.env").write_text("")
    (tmp_path / "sec.env").write_text("")
    values = dict(output=str(tmp_path / "units"), root="/srv/zeus", user="zeus", group=None,
                  uid=1500, home="/home/zeus", path=svc.DEFAULT_PATH, python="/usr/bin/python3",
                  tool=str(TOOL), config_env=str(tmp_path / "cfg.env"),
                  secret_env=str(tmp_path / "sec.env"), web_port=8787, skip_account_check=True)
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def rendered(tmp_path):
    manifest = svc.render(render_args(tmp_path))
    return tmp_path / "units", manifest


# ----- render ----------------------------------------------------------------------------------
def test_render_resolves_every_placeholder_and_records_hashes(rendered):
    directory, manifest = rendered
    for unit in svc.UNITS:
        text = (directory / unit).read_text()
        assert not svc.PLACEHOLDER.search(text)  # no placeholder survives
        assert manifest["files"][unit]["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert manifest["installed"] is False
    assert json.loads((directory / "render-manifest.json").read_text())["uid"] == 1500


def test_rendered_units_pass_static_policy(rendered):
    directory, _ = rendered
    result = svc.verify(SimpleNamespace(directory=str(directory), systemd_analyze=False))
    assert result["findings"] == []
    assert result["systemd_analyze"] == {"status": "not_run"}


@pytest.mark.parametrize("target", ["/etc/systemd/system", "/run/systemd/system",
                                    "/usr/lib/systemd/system"])
def test_render_refuses_live_systemd_directories(tmp_path, target):
    with pytest.raises(svc.Refused) as refused:
        svc.render(render_args(tmp_path, output=target))
    assert refused.value.reason == "output_is_live_systemd_directory"


@pytest.mark.parametrize("override,reason", [
    ({"root": "srv/zeus"}, "path_not_absolute"),
    ({"root": "/srv/ze us"}, "value_not_literal"),
    ({"root": "/srv/%h"}, "value_not_literal"),
    ({"path": "/usr/bin:bin"}, "path_entry_not_absolute_linux"),
    ({"path": "/usr/bin:/mnt/c/Windows"}, "path_entry_not_absolute_linux"),
    ({"uid": 0}, "explicit_non_root_uid_required"),
    ({"uid": None}, "explicit_non_root_uid_required"),
    ({"web_port": 80}, "web_port_out_of_range"),
])
def test_render_refuses_non_explicit_values_without_partial_output(tmp_path, override, reason):
    with pytest.raises(svc.Refused) as refused:
        svc.render(render_args(tmp_path, **override))
    assert refused.value.reason == reason
    assert not (tmp_path / "units").exists()


def test_render_checks_the_account_database_unless_fixture(tmp_path, monkeypatch):
    account = SimpleNamespace(pw_uid=1000, pw_dir="/home/zeus")
    monkeypatch.setattr(svc.pwd, "getpwnam", lambda name: account)
    with pytest.raises(svc.Refused) as refused:
        svc.render(render_args(tmp_path, skip_account_check=False, uid=1500))
    assert refused.value.reason == "service_uid_mismatch"
    svc.render(render_args(tmp_path, skip_account_check=False, uid=1000))


# ----- unit semantics --------------------------------------------------------------------------
def fleet_unit(directory):
    return svc.parse_unit((directory / svc.FLEET_UNIT).read_text())


def test_fleet_unit_is_single_bounded_control_group_owner(rendered):
    directory, _ = rendered
    sections = fleet_unit(directory)
    service = dict(sections["Service"])
    unit = dict(sections["Unit"])
    # A non-template unit name: systemd refuses a second concurrent instance itself.
    assert "@" not in svc.FLEET_UNIT
    assert (service["User"], service["Group"]) == ("zeus", "zeus")
    assert service["WorkingDirectory"] == "/srv/zeus/runtime/control"
    assert service["KillMode"] == "control-group" and service["SendSIGKILL"] == "yes"
    assert service["KillSignal"] == "SIGTERM" and int(service["TimeoutStopSec"]) <= 900
    assert service["Restart"] == "on-failure" and service["RestartPreventExitStatus"] == "78"
    assert int(unit["StartLimitBurst"]) == 3 and int(unit["StartLimitIntervalSec"]) == 600
    environment = svc.values_of(sections, "Service", "Environment")
    assert f"PATH={svc.DEFAULT_PATH}" in environment and "HOME=/home/zeus" in environment
    starts = svc.values_of(sections, "Service", "ExecStart")
    assert starts == [f"/usr/bin/python3 {TOOL} launch --role fleet"]
    assert any("journal start" in v for v in svc.values_of(sections, "Service", "ExecStartPre"))
    assert any("journal exit" in v for v in svc.values_of(sections, "Service", "ExecStopPost"))


def test_secrets_only_come_from_environment_files(rendered, tmp_path):
    directory, _ = rendered
    for unit in svc.SERVICES:
        sections = svc.parse_unit((directory / unit).read_text())
        files = svc.values_of(sections, "Service", "EnvironmentFile")
        assert files == [str(tmp_path / "cfg.env"), str(tmp_path / "sec.env")]
        for value in svc.values_of(sections, "Service", "Environment"):
            assert not svc.SECRET_NAME.search(value.split("=", 1)[0])


@pytest.mark.parametrize("mutation,code", [
    (("KillMode=control-group", "KillMode=process"), "kill_mode_not_control_group"),
    (("TimeoutStopSec=180", "TimeoutStopSec=infinity"), "stop_timeout_unbounded"),
    (("Restart=on-failure", "Restart=always"), "restart_policy_unbounded"),
    (("RestartPreventExitStatus=78", "RestartPreventExitStatus=1"), "refusal_restart_not_prevented"),
    (("User=zeus", "User=root"), "explicit_non_root_user_missing"),
    (("StartLimitBurst=3", "#"), "start_limit_missing"),
    (("Environment=LANG=C.UTF-8", "Environment=CLAUDE_CODE_OAUTH_TOKEN=x"),
     "secret_in_environment_line"),
    (("launch --role fleet", "launch --role fleet --resume"), "resume_reference"),
    (("WorkingDirectory=/srv/zeus/runtime/control", "WorkingDirectory=~"),
     "working_directory_not_absolute"),
    (("Environment=HOME=/home/zeus", "Environment=HOME=/mnt/d/workspaces"),
     "windows_path_reference"),
    (("Environment=LANG=C.UTF-8", "Environment=ZEUS_DB_HOST=192.168.0.10"), "lan_ip_literal"),
])
def test_static_policy_rejects_each_weakened_unit(rendered, mutation, code):
    directory, _ = rendered
    text = (directory / svc.FLEET_UNIT).read_text().replace(*mutation, 1)
    assert code in {f["code"] for f in svc.unit_findings(svc.FLEET_UNIT, text)}


def test_loopback_literals_are_allowed(rendered):
    directory, _ = rendered
    text = (directory / svc.FLEET_UNIT).read_text().replace(
        "Environment=LANG=C.UTF-8", "Environment=ZEUS_DB_HOST=127.0.0.1", 1)
    assert svc.unit_findings(svc.FLEET_UNIT, text) == []


def test_only_the_target_and_timer_install_into_boot_targets(rendered):
    directory, _ = rendered
    for unit in svc.SERVICES:
        sections = svc.parse_unit((directory / unit).read_text())
        assert svc.values_of(sections, "Install", "WantedBy") == ["zeus-aibox.target"]
    target = svc.parse_unit((directory / "zeus-aibox.target").read_text())
    assert svc.values_of(target, "Install", "WantedBy") == ["multi-user.target"]


# ----- systemd-analyze (real binary, rendered files only) --------------------------------------
@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze not installed")
def test_systemd_analyze_verify_accepts_rendered_units_offline(tmp_path):
    # User must exist for systemd-analyze; the current account is used for this offline check.
    import getpass
    import os
    import pwd

    account = pwd.getpwuid(os.getuid())
    if account.pw_uid == 0:
        pytest.skip("root account: the template requires a non-root service user")
    args = render_args(tmp_path, user=getpass.getuser(), uid=account.pw_uid, home=account.pw_dir,
                       root=str(tmp_path / "srv"), skip_account_check=False)
    svc.render(args)
    good = svc.verify(SimpleNamespace(directory=args.output, systemd_analyze=True))
    assert good["systemd_analyze"]["status"] == "passed", good
    unit = Path(args.output) / svc.FLEET_UNIT
    unit.write_text(unit.read_text().replace("KillMode=control-group", "KillMode=bogus"))
    bad = svc.verify(SimpleNamespace(directory=args.output, systemd_analyze=True))
    assert bad["systemd_analyze"]["status"] == "failed"
    assert any("kill mode" in line.lower() for line in bad["systemd_analyze"]["diagnostics"])


def test_systemd_analyze_unavailable_is_not_a_pass(rendered):
    directory, _ = rendered

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("systemd-analyze")

    result = svc.verify(SimpleNamespace(directory=str(directory), systemd_analyze=True),
                        run=missing)
    assert result["systemd_analyze"]["status"] == "unavailable"


# ----- launch (plan only; nothing is executed) -------------------------------------------------
@pytest.fixture
def host(tmp_path):
    root = tmp_path / "srv"
    release = root / "releases" / REVISION
    (release / ".venv" / "bin").mkdir(parents=True)
    python = release / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    (release / "src" / "codex_harness").mkdir(parents=True)
    (release / "src" / "codex_harness" / "__init__.py").write_text("")
    (root / "releases" / "current").symlink_to(release)
    control = root / "runtime" / "control"
    control.mkdir(parents=True)
    machine = tmp_path / "machine-id"
    machine.write_text("0123456789abcdef0123456789abcdef\n")
    environ = {"ZEUS_AIBOX_ROOT": str(root), "PATH": svc.DEFAULT_PATH}
    return SimpleNamespace(root=root, release=release, control=control, machine=machine,
                           environ=environ, host_id=svc.host_id(machine))


def activate(host, **overrides):
    receipt = {"schema": svc.ACTIVATION_SCHEMA, "host_id": host.host_id,
               "state": "restored_paused", "release_revision": REVISION,
               "migration_id": "aibox-migration-001"}
    receipt.update(overrides)
    (host.control / svc.ACTIVATION_FILE).write_text(json.dumps(receipt))


def plan(host, role="fleet", **environ):
    return svc.launch_plan(role, {**host.environ, **environ}, machine_id_path=host.machine)


def test_fleet_launch_binds_pinned_release_and_never_resumes(host):
    activate(host)
    result = plan(host)
    python = str(host.release / ".venv" / "bin" / "python")
    assert result["argv"] == [python, "-m", "zeus", "fleet", "run"]
    assert result["cwd"] == str(host.control) and result["revision"] == REVISION
    assert result["env"]["ZEUS_REPOSITORY"] == str(host.release)
    assert result["env"]["PATH"].startswith(str(host.release / ".venv" / "bin") + ":")
    assert result["migration_id"] == "aibox-migration-001"
    assert "resume" not in result["argv"]


def test_monitor_roles_need_no_activation_and_stay_loopback(host):
    collect = plan(host, "monitor-collect")
    assert collect["argv"][2:4] == ["codex_harness.monitor", "collect"]
    web = plan(host, "monitor-web", ZEUS_AIBOX_WEB_PORT="8790")
    assert web["argv"][-2:] == ["--port", "8790"]
    assert not any(svc.IPV4.search(word) for word in web["argv"])


def test_fence_refuses_every_role_even_when_unreadable(host):
    activate(host)
    (host.control / svc.FENCE_FILE).write_text("not json")
    for role in svc.ROLES:
        with pytest.raises(svc.Refused) as refused:
            plan(host, role)
        assert refused.value.reason == "host_fenced"


@pytest.mark.parametrize("overrides,reason", [
    (None, "activation_receipt_missing"),
    ({"host_id": "machine-id-sha256:" + "0" * 64}, "activation_receipt_other_host"),
    ({"state": "staged"}, "activation_receipt_state"),
    ({"state": "rollback_required"}, "activation_receipt_state"),
    ({"release_revision": "b" * 40}, "activation_receipt_revision_mismatch"),
    ({"schema": "urn:other:1"}, "activation_receipt_schema"),
    ({"migration_id": ""}, "activation_receipt_migration_missing"),
])
def test_fleet_refuses_without_matching_activation_receipt(host, overrides, reason):
    if overrides is not None:
        activate(host, **overrides)
    with pytest.raises(svc.Refused) as refused:
        plan(host)
    assert refused.value.reason == reason


def test_unpinned_release_pointer_is_refused(host, tmp_path):
    activate(host)
    current = host.root / "releases" / "current"
    current.unlink()
    with pytest.raises(svc.Refused) as refused:
        plan(host)
    assert refused.value.reason == "release_pointer_missing"
    moving = host.root / "releases" / "main"
    moving.mkdir()
    current.symlink_to(moving)
    with pytest.raises(svc.Refused) as refused:
        plan(host)
    assert refused.value.reason == "release_not_pinned_revision"


@pytest.mark.parametrize("environ,reason", [
    ({"ZEUS_AIBOX_ROOT": ""}, "root_not_explicit"),
    ({"PATH": ""}, "path_not_explicit_linux"),
    ({"PATH": "/usr/bin:."}, "path_not_explicit_linux"),
    ({"PATH": "/usr/bin:/mnt/c/Windows/System32"}, "path_not_explicit_linux"),
])
def test_launch_requires_explicit_linux_environment(host, environ, reason):
    activate(host)
    with pytest.raises(svc.Refused) as refused:
        plan(host, **environ)
    assert refused.value.reason == reason


def test_launch_cli_refusal_exits_78_without_executing(host, monkeypatch, capsys):
    monkeypatch.setattr(svc.os, "environ", dict(host.environ))
    monkeypatch.setattr(svc.os, "execve", lambda *a: pytest.fail("must not exec"))
    assert svc.main(["launch", "--role", "fleet"]) == svc.EXIT_REFUSED
    assert json.loads(capsys.readouterr().err)["reason"] == "activation_receipt_missing"


# ----- journal ---------------------------------------------------------------------------------
def test_journal_pairs_start_and_exit_by_invocation(tmp_path, monkeypatch):
    path = tmp_path / "fleet-service-journal.jsonl"
    run_id = "f" * 32
    monkeypatch.setattr(svc.os, "environ", {"INVOCATION_ID": run_id})
    assert svc.main(["journal", "start", "--role", "fleet", "--journal", str(path)]) == 0
    monkeypatch.setattr(svc.os, "environ", {"INVOCATION_ID": run_id, "SERVICE_RESULT": "success",
                                            "EXIT_CODE": "exited", "EXIT_STATUS": "0"})
    assert svc.main(["journal", "exit", "--role", "fleet", "--journal", str(path)]) == 0
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(e["event"], e["run_id"]) for e in lines] == [("start", run_id), ("exit", run_id)]
    assert lines[1]["service_result"] == "success"


def test_journal_matches_the_relocation_runner_state_contract(tmp_path):
    """The journal format is read by the harness's own runner_state (fleet_recovery)."""
    from codex_harness.adapters.fleet_recovery import runner_state

    path = tmp_path / "journal.jsonl"
    svc.append_journal(path, svc.journal_entry("start", "fleet", {"INVOCATION_ID": "1" * 32}))
    assert runner_state(path)["state"] == "running"
    svc.append_journal(path, svc.journal_entry("exit", "fleet", {"INVOCATION_ID": "1" * 32}))
    assert runner_state(path)["state"] == "stopped"
    svc.append_journal(path, svc.journal_entry("start", "fleet", {"INVOCATION_ID": "2" * 32}))
    assert runner_state(path) | {"journal_sha256": None} == {
        "state": "running", "run_id": "2" * 32, "journal_sha256": None, "reason": None}


def test_journal_refuses_outside_systemd(tmp_path, monkeypatch):
    monkeypatch.setattr(svc.os, "environ", {})
    path = tmp_path / "j.jsonl"
    assert svc.main(["journal", "start", "--role", "fleet", "--journal", str(path)]) == 1
    assert not path.exists()


# ----- inspect (fake /proc, cgroup tree, systemctl and docker) ---------------------------------
FLEET_CG = "/system.slice/zeus-aibox-fleet.service"
DOCKER_CG = "/system.slice/docker-" + "c" * 64 + ".scope"


def fake_proc(tmp_path, processes):
    proc = tmp_path / "proc"
    for pid, (argv, cgroup) in processes.items():
        entry = proc / str(pid)
        entry.mkdir(parents=True)
        entry.joinpath("cmdline").write_bytes(b"\0".join(w.encode() for w in argv) + b"\0")
        entry.joinpath("cgroup").write_text(f"0::{cgroup}\n")
        entry.joinpath("comm").write_text(Path(argv[0]).name[:15] + "\n")
    return proc


def fake_cgroups(tmp_path, groups):
    root = tmp_path / "cgroup"
    for group, pids in groups.items():
        directory = root / group.lstrip("/")
        directory.mkdir(parents=True)
        directory.joinpath("cgroup.procs").write_text("".join(f"{p}\n" for p in pids))
    return root


def fake_runner(*, fleet_active=True, containers=(), docker_ok=True):
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        if argv[0] == "systemctl":
            unit = argv[2]
            active = unit != svc.FLEET_UNIT or fleet_active
            group = f"/system.slice/{unit}" if active else ""
            out = (f"ActiveState={'active' if active else 'inactive'}\nControlGroup={group}\n"
                   f"MainPID={100 if active else 0}\nNRestarts=0\nKillMode=control-group\n")
            return subprocess.CompletedProcess(argv, 0, out, "")
        if argv[:2] == ["docker", "ps"]:
            if not docker_ok:
                return subprocess.CompletedProcess(argv, 1, "", "Cannot connect")
            out = "".join(json.dumps(c) + "\n" for c in containers)
            return subprocess.CompletedProcess(argv, 0, out, "")
        if argv[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, "300\n", "")
        if argv[0] == "ip":
            if "route" in argv:
                return subprocess.CompletedProcess(argv, 0, json.dumps(
                    [{"dev": "enp5s0", "gateway": "192.168.0.1"}]), "")
            return subprocess.CompletedProcess(argv, 0, json.dumps([
                {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1",
                                                "prefixlen": 8}]},
                {"ifname": "enp5s0", "addr_info": [{"family": "inet", "local": "192.168.0.10",
                                                    "prefixlen": 24}]}]), "")
        raise AssertionError(f"unexpected command {argv}")

    run.calls = calls
    return run


RUNNER_ARGV = ["/srv/zeus/releases/x/.venv/bin/python", "-m", "zeus", "fleet", "run"]
CONTAINER = {"ID": "c" * 64, "Names": "zeus-run-1", "State": "running",
             "Labels": "zeus.isolated.role=worker,zeus.isolated.run=run-1"}


def run_inspect(tmp_path, processes, *, runner, groups=None):
    proc = fake_proc(tmp_path, processes)
    cgroups = fake_cgroups(tmp_path, groups or {FLEET_CG: [p for p, (_, g) in processes.items()
                                                           if g == FLEET_CG]})
    return svc.inspect(tmp_path / "srv", run=runner, proc=proc, sys_cgroup=cgroups,
                       unit_dir=tmp_path / "units")


def test_inspect_healthy_single_owner_with_container_outside_cgroup(tmp_path):
    runner = fake_runner(containers=[CONTAINER])
    result = run_inspect(tmp_path, {100: (RUNNER_ARGV, FLEET_CG),
                                     300: (["/bin/sleep", "1"], DOCKER_CG)}, runner=runner)
    assert result["findings"] == []
    fleet = result["units"][svc.FLEET_UNIT]
    assert [p["pid"] for p in fleet["cgroup_processes"]["processes"]] == [100]
    container = result["docker"]["containers"][0]
    # The documented caveat, observed: the worker container is NOT in the owner's cgroup.
    assert container["run_id"] == "run-1" and container["cgroup"] == DOCKER_CG
    assert container["cgroup"] != fleet["ControlGroup"]
    assert result["read_only"] is True
    mutating = {"start", "stop", "restart", "kill", "rm", "enable", "disable", "resume"}
    assert not any(set(argv) & mutating for argv in runner.calls)


def test_inspect_reports_runner_outside_the_owner_unit(tmp_path):
    result = run_inspect(tmp_path, {100: (RUNNER_ARGV, FLEET_CG),
                                    200: (["/usr/bin/uv", "run", "zeus", "fleet", "run", "--once"],
                                          "/user.slice/session-4.scope")},
                         runner=fake_runner())
    assert {"code": "fleet_runner_outside_unit", "pids": [200]} in result["findings"]


def test_inspect_reports_duplicate_runner_inside_the_unit(tmp_path):
    result = run_inspect(tmp_path, {100: (RUNNER_ARGV, FLEET_CG), 101: (RUNNER_ARGV, FLEET_CG)},
                         runner=fake_runner())
    assert {"code": "multiple_fleet_runners_in_unit", "pids": [100, 101]} in result["findings"]


def test_inspect_reports_docker_residue_after_owner_stop(tmp_path):
    result = run_inspect(tmp_path, {300: (["/bin/sleep", "1"], DOCKER_CG)},
                         runner=fake_runner(fleet_active=False, containers=[CONTAINER]),
                         groups={FLEET_CG: []})
    assert {"code": "labelled_containers_without_active_owner", "run_ids": ["run-1"]} \
        in result["findings"]


def test_inspect_docker_unavailable_is_unknown_not_empty(tmp_path):
    result = run_inspect(tmp_path, {100: (RUNNER_ARGV, FLEET_CG)},
                         runner=fake_runner(docker_ok=False))
    assert result["docker"]["status"] == "unavailable"
    assert {"code": "docker_state_unavailable"} in result["findings"]


def test_inspect_flags_active_owner_on_fenced_host_and_loose_secret_mode(tmp_path):
    control = tmp_path / "srv" / "runtime" / "control"
    control.mkdir(parents=True)
    (control / svc.FENCE_FILE).write_text("{}")
    secrets = tmp_path / "srv" / "secrets"
    secrets.mkdir()
    (secrets / "zeus-aibox.env").write_text("X=1\n")
    (secrets / "zeus-aibox.env").chmod(0o644)
    result = run_inspect(tmp_path, {100: (RUNNER_ARGV, FLEET_CG)}, runner=fake_runner())
    codes = {f["code"] for f in result["findings"]}
    assert {"fleet_active_while_fenced", "secret_file_mode_not_0600"} <= codes
    assert "X=1" not in json.dumps(result)  # the secret file is stat()ed, never read


def test_inspect_flags_lan_ip_and_windows_paths_in_installed_config(tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    (units / svc.FLEET_UNIT).write_text("[Service]\nEnvironment=X=192.168.0.10\n")
    config = tmp_path / "srv" / "config"
    config.mkdir(parents=True)
    (config / "zeus-aibox.env").write_text("ZEUS_ARTIFACTS=D:\\workspaces\\zeus\n")
    result = run_inspect(tmp_path, {100: (RUNNER_ARGV, FLEET_CG)}, runner=fake_runner())
    codes = {(f["code"], Path(f["file"]).name) for f in result["findings"] if "file" in f}
    assert codes == {("lan_ip_literal", svc.FLEET_UNIT), ("windows_path_reference",
                                                          "zeus-aibox.env")}


def test_inspect_network_excludes_loopback(tmp_path):
    result = run_inspect(tmp_path, {100: (RUNNER_ARGV, FLEET_CG)}, runner=fake_runner())
    assert result["network"]["ipv4"] == [{"ifname": "enp5s0", "address": "192.168.0.10/24"}]
    assert result["windows_observer"] == "not_observable_from_aibox"


# ----- network change --------------------------------------------------------------------------
def test_network_comparison_reports_ip_change_only():
    before = {"ipv4": [{"ifname": "enp5s0", "address": "192.168.0.10/24"}],
              "default_routes": [{"dev": "enp5s0", "gateway": "192.168.0.1"}]}
    same = svc.compare_network(before, json.loads(json.dumps(before)))
    assert same["changed"] is False
    after = {"ipv4": [{"ifname": "enp5s0", "address": "172.30.1.20/24"}],
             "default_routes": [{"dev": "enp5s0", "gateway": "172.30.1.254"}]}
    changed = svc.compare_network(before, after)
    assert changed["changed"] is True
    assert changed["removed"] == ["192.168.0.10/24"] and changed["added"] == ["172.30.1.20/24"]


def test_templates_hold_no_lan_address_so_ip_change_needs_no_rerender():
    for template in (ROOT / "deploy" / "aibox" / "systemd").glob("*.in"):
        text = template.read_text()
        assert all(svc._loopback(a) for a in svc.IPV4.findall(text)), template.name
        assert not svc.WINDOWS_PATH.search(text), template.name


def test_cli_usage_error_is_exit_2():
    assert svc.main(["launch", "--role", "nonsense"]) == svc.EXIT_USAGE
