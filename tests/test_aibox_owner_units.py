"""aibox SPEC s14 G1-G3 host units: the managed Fleet unit, the owner-action coordinator unit, the one
Fleet owner rule and the start-only polkit grant (deploy/aibox).

Isolated fixtures only, as in `test_aibox_service_templates`: templates rendered into tmp_path, launch
plans computed without executing, and `systemctl` a fake runner. No unit or polkit rule is installed,
enabled, started or stopped. Linux-only tooling: the module is skipped before import elsewhere.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

if os.name != "posix":
    pytest.skip("aibox service tooling is Linux-only; not supported on this platform", allow_module_level=True)

from test_aibox_service_templates import REVISION, TOOL, activate, render_args, svc  # noqa: E402


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
    from types import SimpleNamespace
    return SimpleNamespace(root=root, release=release, control=control, machine=machine,
                           environ={"ZEUS_AIBOX_ROOT": str(root), "PATH": svc.DEFAULT_PATH},
                           host_id=svc.host_id(machine))


def unit_state(state="inactive", code=0):
    calls = []

    def run(argv, **_):
        calls.append(argv)
        assert argv[:3] == ["systemctl", "show", svc.FLEET_UNIT], argv
        return subprocess.CompletedProcess(argv, code, f"ActiveState={state}\n", "")

    run.calls = calls
    return run


def owner_record(host, **overrides):
    record = {"schema": svc.FLEET_OWNER_SCHEMA, "owner": "managed-fleet", "unit": svc.MANAGED_FLEET_UNIT,
              **overrides}
    (host.control / svc.FLEET_OWNER_FILE).write_text(json.dumps(record))


def plan(host, role, run=None, **environ):
    return svc.launch_plan(role, {**host.environ, **environ}, machine_id_path=host.machine,
                           run=run or unit_state())


# ----- exactly one Fleet owner --------------------------------------------------------------------
def test_the_managed_fleet_role_runs_the_supervisor_of_the_fixed_state_directory(host):
    activate(host)
    owner_record(host)
    run = unit_state("inactive")
    result = plan(host, "managed-fleet", run)
    python = str(host.release / ".venv" / "bin" / "python")
    assert result["argv"] == [python, "-m", "codex_harness.adapters.managed_runtime", "supervise", "--state-dir",
                              str(host.root / "runtime" / "managed-fleet")]
    assert result["env"]["ZEUS_REPOSITORY"] == str(host.release) and result["revision"] == REVISION
    # The stable controller code is `current`; the candidate runtime is only what supervise launches.
    assert run.calls == [["systemctl", "show", svc.FLEET_UNIT, "-p", "ActiveState"]]


@pytest.mark.parametrize("setup, run, reason", [
    ("no_activation", unit_state(), "activation_receipt_missing"),
    ("no_owner", unit_state(), "fleet_owner_not_managed"),
    ("bad_owner", unit_state(), "fleet_owner_invalid"),
    ("owner", unit_state("active"), "bootstrap_fleet_active"),
    ("owner", unit_state("activating"), "bootstrap_fleet_active"),
    ("owner", unit_state("inactive", code=1), "bootstrap_fleet_state_unknown"),
    ("owner", unit_state("maintenance"), "bootstrap_fleet_state_unknown"),
])
def test_the_managed_fleet_role_refuses_without_activation_owner_record_or_a_stopped_bootstrap(host, setup, run,
                                                                                               reason):
    if setup != "no_activation":
        activate(host)
    if setup in ("owner", "no_activation"):
        owner_record(host)
    if setup == "bad_owner":
        owner_record(host, unit="zeus-aibox-fleet.service")
    with pytest.raises(svc.Refused) as refused:
        plan(host, "managed-fleet", run)
    assert refused.value.reason == reason


def test_once_the_managed_target_owns_the_fleet_the_bootstrap_role_refuses(host):
    activate(host)
    assert plan(host, "fleet")["argv"][-2:] == ["fleet", "run"]      # unchanged without the owner record
    owner_record(host)
    with pytest.raises(svc.Refused) as refused:
        plan(host, "fleet")
    assert refused.value.reason == "fleet_owner_managed"
    (host.control / svc.FLEET_OWNER_FILE).write_text("not json")
    with pytest.raises(svc.Refused) as unreadable:
        plan(host, "fleet")
    assert unreadable.value.reason == "fleet_owner_unreadable"


def test_the_owner_actions_role_needs_activation_and_a_named_policy(host):
    with pytest.raises(svc.Refused) as refused:
        plan(host, "owner-actions", ZEUS_OWNER_ACTIONS_POLICY="owners-1")
    assert refused.value.reason == "activation_receipt_missing"
    activate(host)
    for value in ("", "../x", "a b"):
        with pytest.raises(svc.Refused) as unset:
            plan(host, "owner-actions", ZEUS_OWNER_ACTIONS_POLICY=value)
        assert unset.value.reason == "owner_actions_policy_unset"
    result = plan(host, "owner-actions", ZEUS_OWNER_ACTIONS_POLICY="owners-1")
    assert result["argv"][1:] == ["-m", "zeus", "owner-actions", "run", "--policy", "owners-1"]


def test_the_owner_actions_role_ticks_a_policy_list_in_one_process(host):
    """Whole-goal adjudication C2: one owner process, several disjoint policies, each named once."""
    activate(host)
    result = plan(host, "owner-actions", ZEUS_OWNER_ACTIONS_POLICY="aibox-owner-actions-002,aibox-owner-actions-i1")
    assert result["argv"][1:] == ["-m", "zeus", "owner-actions", "run", "--policy", "aibox-owner-actions-002",
                                  "--policy", "aibox-owner-actions-i1"]
    for value in ("a,", ",a", "a,,b", "a, b", "a,../x"):
        with pytest.raises(svc.Refused) as unset:
            plan(host, "owner-actions", ZEUS_OWNER_ACTIONS_POLICY=value)
        assert unset.value.reason == "owner_actions_policy_unset", value
    with pytest.raises(svc.Refused) as duplicate:
        plan(host, "owner-actions", ZEUS_OWNER_ACTIONS_POLICY="a,b,a")
    assert duplicate.value.reason == "owner_actions_policy_duplicate"


def test_a_fence_refuses_the_new_roles_too(host):
    activate(host)
    owner_record(host)
    (host.control / svc.FENCE_FILE).write_text("{}")
    for role in ("managed-fleet", "owner-actions"):
        with pytest.raises(svc.Refused) as refused:
            plan(host, role, ZEUS_OWNER_ACTIONS_POLICY="owners-1")
        assert refused.value.reason == "host_fenced"


# ----- rendered unit and polkit policy ----------------------------------------------------------------------
@pytest.fixture
def rendered(tmp_path):
    manifest = svc.render(render_args(tmp_path))
    return tmp_path / "units", manifest


def test_the_managed_unit_owns_its_own_control_group_with_bounded_non_looping_restarts(rendered):
    directory, manifest = rendered
    sections = svc.parse_unit((directory / svc.MANAGED_FLEET_UNIT).read_text())
    service, unit = dict(sections["Service"]), dict(sections["Unit"])
    assert "@" not in svc.MANAGED_FLEET_UNIT and svc.MANAGED_FLEET_UNIT == "zeus-aibox-managed-fleet.service"
    assert service["KillMode"] == "control-group" and service["SendSIGKILL"] == "yes"
    assert service["Restart"] == "on-failure" and service["RestartPreventExitStatus"].split() == ["78", "2"]
    assert int(unit["StartLimitBurst"]) == 3 and (service["User"], service["Group"]) == ("zeus", "zeus")
    assert svc.values_of(sections, "Service", "ExecStart") == [f"/usr/bin/python3 {TOOL} launch --role managed-fleet"]
    assert svc.unit_findings(svc.MANAGED_FLEET_UNIT, (directory / svc.MANAGED_FLEET_UNIT).read_text()) == []
    weakened = (directory / svc.MANAGED_FLEET_UNIT).read_text().replace("KillMode=control-group", "KillMode=process")
    assert "kill_mode_not_control_group" in {f["code"] for f in svc.unit_findings(svc.MANAGED_FLEET_UNIT, weakened)}
    owner = svc.parse_unit((directory / svc.OWNER_ACTIONS_UNIT).read_text())
    assert svc.values_of(owner, "Service", "ExecStart") == [f"/usr/bin/python3 {TOOL} launch --role owner-actions"]
    assert svc.unit_findings(svc.OWNER_ACTIONS_UNIT, (directory / svc.OWNER_ACTIONS_UNIT).read_text()) == []
    for name in svc.OWNER_SERVICES:
        assert manifest["files"][name]["sha256"] and manifest["installed"] is False


def test_the_polkit_rule_grants_only_start_of_the_managed_unit_to_the_service_user(rendered):
    directory, manifest = rendered
    text = (directory / "50-zeus-aibox-managed-fleet.rules").read_text()
    assert not svc.PLACEHOLDER.search(text) and 'subject.user == "zeus"' in text
    assert 'action.lookup("unit") == "zeus-aibox-managed-fleet.service"' in text
    assert 'action.lookup("verb") == "start"' in text
    for forbidden in ('"stop"', '"restart"', '"kill"', "zeus-aibox-fleet.service", "zeus-aibox-*", "indexOf"):
        assert forbidden not in text
    assert manifest["files"]["50-zeus-aibox-managed-fleet.rules"]["sha256"]


def test_rendering_refuses_a_live_polkit_directory(tmp_path):
    with pytest.raises(svc.Refused) as refused:
        svc.render(render_args(tmp_path, output="/etc/polkit-1/rules.d"))
    assert refused.value.reason == "output_is_live_systemd_directory"
