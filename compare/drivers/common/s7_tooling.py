"""Shared S7 scenario steps (`delivery.tooling`): the Linux service tool `deploy/aibox/zeus_aibox_service.py` and the
offline data-transfer CLI `scripts/aibox_data` (DESIGN-s7 §0 "Delivery tooling", §2 row `delivery.tooling`, §3 step 7),
recorded from SOURCE BEFORE the verbatim deploy move.

Layer: harness (never shipped). Never imports `codex_harness`.

Two case groups, each case labelled in the result (`{group: {case: {...}}}`); a case's `mirrors` names the M7 test(s)
it copies (a case without `mirrors` is characterized directly):
- `service` (M7 `tests/test_aibox_service_templates.py`, 33 tests): `render` (hashes, every refusal, the account database
  through a LABELLED `pwd` double), `parse_unit`/`values_of`/`unit_findings` over every rendered unit and each weakened
  fleet unit, `verify` (static policy; `systemd-analyze` through LABELLED `run` doubles), `launch_plan` per role over a
  LABELLED fixture control dir, release tree and machine-id file, `check_activation`, `fleet_owner`, `pinned_release`,
  `bootstrap_inactive` (a LABELLED systemctl double), `journal_entry`/`append_journal`, `inspect`/`compare_network`
  over a LABELLED proc root, cgroup tree and runner double, `parser()`, `main` for every subcommand, and `launch`
  up to `os.execve`.
- `data_cli` (M7 `tests/test_aibox_data_manifest.py`, 40 tests): every subcommand of `aibox_data.cli.parser()` through
  `data_main` (`aibox_data.cli.main`) over fixture trees, manifests, exports and evidence documents, with its stdout,
  stderr and exit code. Where M7 reaches a library function with no CLI path (`mapping.validate_allowlist`,
  `contracts.validate_redis`, `contracts.stream_entries_sha256`, `contracts.validate_pg`) the case calls the function of
  the SAME loaded module (`sys.modules["aibox_data.<name>"]`) and says so (`via: library`).

**Doubles (all LABELLED; no real systemd, systemd-analyze, docker, ip, /proc, exec, PostgreSQL or Redis is touched).**
- `run` of `verify`/`launch_plan`/`inspect` and the `subprocess.run` that `network` calls are recording doubles that
  answer the fixed command forms and raise on any other.
- `/proc` and the cgroup tree are fixture directories (`proc=`/`sys_cgroup=` arguments, or the `inspect` keyword defaults
  while `main` runs).
- `launch` ends in `os.execve`: the api hook `install_execve(fn)` puts a recording sentinel there; it records the argv,
  the env KEYS and the cwd and raises `Exec`. It is never a real exec. `launch` does `os.chdir` into the fixture control
  dir first: the working directory is restored after each case.
- The machine id is a fixture file; the launcher's own default `/etc/machine-id` (and `run=subprocess.run`) are replaced
  for a case by assigning the function's `__defaults__`/`__kwdefaults__`, and `emit`'s default stream is replaced the
  same way while `main` runs, so its stdout is captured. All are restored.
- `pwd.getpwnam` is replaced by a double for the account-database cases and restored.
- The clock is substituted per run on both sides: `utcnow` of the launcher is `2026-01-01T00:00:00Z` and `utcnow` of
  `aibox_data.inventory` is `2026-01-01T00:00:00+00:00` (module-attribute substitutions, restored afterwards). Fixture
  paths that reach a rendered unit are literal (`/srv/zeus/...`) so their hashes are literal.
- Fixture files are created with explicit modes where a mode is recorded (the process umask is never read). The
  big file is deterministic (a sha256 counter stream), never `os.urandom`.

**Normalization is explicit, done here and identical on both sides:** this case's temporary root → `<root>`; every `uid`
int → `<uid>`; `mtime_ns` → `<mtime_ns>`; a manifest `digest`/`manifest_digest` (it covers the temporary `source_label`) → `<manifest-digest>`
(the digest's properties - stable, tamper-detecting, valid - are recorded as booleans). Nothing else is masked.

`api` supplies `launcher` (the loaded `zeus_aibox_service` module), `data_main` (`aibox_data.cli.main`) and
`install_execve(fn)`.

**Unreachable here (named, with the reason; never faked):** `test_systemd_analyze_verify_accepts_rendered_units_offline`
(needs the real `systemd-analyze` binary against a real account), `test_journal_matches_the_relocation_runner_state_contract`
(the reader `runner_state` is product code: the `delivery.fleet_recovery_collectors` family; this family records the journal
lines it reads), `test_artifact_store_accepts_real_file_artifacts_output` (the writer `FileArtifacts` is product code; the hand-built
store of the same format is recorded), and the process-level behaviour of a real exec, real `systemctl`/`docker`/`ip` and the
host's `/proc`.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

A = None  # the api of this run
CLOCK_Z = "2026-01-01T00:00:00Z"
CLOCK_ISO = "2026-01-01T00:00:00+00:00"
REVISION = "a" * 40
TOOL_PATH = "/srv/zeus/deploy/aibox/zeus_aibox_service.py"
CONFIG_ENV = "/srv/zeus/config/zeus-aibox.env"
SECRET_ENV = "/srv/zeus/secrets/zeus-aibox.env"
FLEET_CG = "/system.slice/zeus-aibox-fleet.service"
DOCKER_CG = "/system.slice/docker-" + "c" * 64 + ".scope"
RUNNER_ARGV = ["/srv/zeus/releases/x/.venv/bin/python", "-m", "zeus", "fleet", "run"]
CONTAINER = {"ID": "c" * 64, "Names": "zeus-run-1", "State": "running",
             "Labels": "zeus.isolated.role=worker,zeus.isolated.run=run-1"}

SERVICE_TESTS = [
    "test_render_resolves_every_placeholder_and_records_hashes", "test_rendered_units_pass_static_policy",
    "test_render_refuses_live_systemd_directories", "test_render_refuses_non_explicit_values_without_partial_output",
    "test_render_checks_the_account_database_unless_fixture", "test_fleet_unit_is_single_bounded_control_group_owner",
    "test_secrets_only_come_from_environment_files", "test_static_policy_rejects_each_weakened_unit",
    "test_loopback_literals_are_allowed", "test_only_the_target_and_timer_install_into_boot_targets",
    "test_systemd_analyze_verify_accepts_rendered_units_offline", "test_systemd_analyze_unavailable_is_not_a_pass",
    "test_fleet_launch_binds_pinned_release_and_never_resumes", "test_monitor_roles_need_no_activation_and_stay_loopback",
    "test_fence_refuses_every_role_even_when_unreadable", "test_fleet_refuses_without_matching_activation_receipt",
    "test_unpinned_release_pointer_is_refused", "test_launch_requires_explicit_linux_environment",
    "test_launch_cli_refusal_exits_78_without_executing", "test_journal_pairs_start_and_exit_by_invocation",
    "test_journal_matches_the_relocation_runner_state_contract", "test_journal_refuses_outside_systemd",
    "test_inspect_healthy_single_owner_with_container_outside_cgroup", "test_inspect_reports_runner_outside_the_owner_unit",
    "test_inspect_reports_duplicate_runner_inside_the_unit", "test_inspect_reports_docker_residue_after_owner_stop",
    "test_inspect_docker_unavailable_is_unknown_not_empty",
    "test_inspect_flags_active_owner_on_fenced_host_and_loose_secret_mode",
    "test_inspect_flags_lan_ip_and_windows_paths_in_installed_config", "test_inspect_network_excludes_loopback",
    "test_network_comparison_reports_ip_change_only",
    "test_templates_hold_no_lan_address_so_ip_change_needs_no_rerender", "test_cli_usage_error_is_exit_2",
]
DATA_TESTS = [
    "test_manifest_records_bytes_hashes_and_links_without_following", "test_manifest_digest_is_stable_and_detects_tampering",
    "test_case_collisions_and_windows_names_are_reported", "test_artifact_store_verification_matches_file_artifacts_rules",
    "test_artifact_store_accepts_real_file_artifacts_output", "test_path_references_are_reported_not_rewritten",
    "test_stage_copies_verifies_and_is_idempotent", "test_interrupted_copy_resumes_from_verified_partial",
    "test_diverged_partial_and_conflicting_staged_file_are_refused", "test_source_change_after_seal_is_refused",
    "test_same_migration_id_with_different_digest_is_refused",
    "test_external_symlink_is_not_created_and_blocks_verification",
    "test_symlinked_staging_ancestor_is_refused_before_any_write",
    "test_symlinked_nested_ancestor_created_after_first_level_is_refused",
    "test_symlinked_staging_root_work_dir_partial_and_journal_are_refused",
    "test_work_dir_must_be_migration_owned_and_separate", "test_unsafe_manifest_paths_are_refused_even_with_a_valid_digest",
    "test_unreadable_source_subtree_blocks_stage_and_verification", "test_truly_empty_root_stages_and_verifies",
    "test_source_files_named_part_stage_and_verify_under_real_names",
    "test_leftover_staged_part_named_file_is_extra_not_hidden", "test_binding_plan_maps_only_allowlisted_fields_with_receipt",
    "test_binding_plan_refuses_unmapped_and_parent_escape", "test_allowlist_rejects_mapping_an_immutable_bucket",
    "test_pg_comparison_accepts_identity_and_receipted_delta",
    "test_pg_comparison_rejects_missing_rows_public_and_version_skew", "test_source_public_control_schema_is_supported",
    "test_public_stays_forbidden_as_target_schema_and_map_destination",
    "test_cli_pg_inventory_requires_role_and_accepts_source_public", "test_pg_export_rejects_duplicate_rows",
    "test_redis_comparison_preserves_groups_pel_and_absolute_expiry",
    "test_redis_comparison_rejects_dropped_pel_and_extended_ttl",
    "test_redis_key_expired_during_downtime_is_classified_not_missing",
    "test_redis_validation_rejects_out_of_allowlist_keys_and_impossible_pel",
    "test_stream_entries_digest_depends_on_ids_and_fields_not_field_order", "test_pending_entries_must_map_to_pg_owner",
    "test_r0_requires_untouched_source_and_silent_target", "test_r1_refuses_old_snapshot_reuse_and_unreconciled_effects",
    "test_retirement_gate_c_requires_a_b_backup_and_exact_items", "test_cli_inventory_stage_verify_roundtrip",
]
UNREACHABLE = {
    "test_systemd_analyze_verify_accepts_rendered_units_offline":
        "needs the real systemd-analyze binary and a real service account; the verify() contract is recorded through LABELLED run doubles",
    "test_journal_matches_the_relocation_runner_state_contract":
        "the reader runner_state is product code (adapters/fleet_recovery): the delivery.fleet_recovery_collectors family; the journal lines it reads are recorded here",
    "test_artifact_store_accepts_real_file_artifacts_output":
        "the writer FileArtifacts is product code (adapters/artifacts): another family; the hand-built store of the same format is recorded",
}


# ============================== workspace, normalization, doubles =================================================

class Ws:
    """One case's temporary root and normalizer."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s7tool-")).resolve()

    def n(self, value):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key == "uid" and type(item) is int:
                    out[key] = "<uid>"
                elif key == "mtime_ns" and type(item) is int:
                    out[key] = "<mtime_ns>"
                elif key in ("digest", "manifest_digest") and isinstance(item, str) and item.startswith("sha256:"):
                    out[key] = "<manifest-digest>"
                else:
                    out[self.n(key)] = self.n(item)
            return out
        if isinstance(value, (list, tuple)):
            return [self.n(item) for item in value]
        if isinstance(value, Path):
            return self.n(str(value))
        if isinstance(value, str):
            return value.replace(str(self.root), "<root>")
        return value

    def close(self):
        for directory, _, files in os.walk(self.root):
            with contextlib.suppress(OSError):
                os.chmod(directory, 0o700)
            for name in files:
                path = os.path.join(directory, name)
                if not os.path.islink(path):
                    with contextlib.suppress(OSError):
                        os.chmod(path, 0o600)
        shutil.rmtree(self.root, ignore_errors=True)


def attempt(ws, call):
    """What one call returned, or the exception type with its reason fields."""
    try:
        return {"returned": ws.n(call())}
    except SystemExit as exc:
        return {"exit": exc.code}
    except Exception as exc:  # the refusal is the characterized result
        view = {"type": type(exc).__name__, "message": ws.n(str(exc))}
        if getattr(exc, "reason", None) is not None:
            view["reason"] = exc.reason
        for name in ("facts", "path"):
            if getattr(exc, name, None):
                view[name] = ws.n(getattr(exc, name))
        return {"raised": view}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parsed(ws, text: str):
    """A captured stream: its JSON document, else its text; empty is None."""
    if not text:
        return None
    try:
        return ws.n(json.loads(text))
    except ValueError:
        return {"text": ws.n(text)}


@contextlib.contextmanager
def pinned_clock():
    """The per-run clock substitution (both sides): the launcher's and the inventory's `utcnow`."""
    launcher, inventory = A.launcher, sys.modules["aibox_data.inventory"]
    saved = launcher.utcnow, inventory.utcnow
    launcher.utcnow, inventory.utcnow = (lambda: CLOCK_Z), (lambda: CLOCK_ISO)
    try:
        yield
    finally:
        launcher.utcnow, inventory.utcnow = saved


@contextlib.contextmanager
def environment(values):
    """`os.environ` as the launcher reads it (a dict), restored afterwards."""
    saved = A.launcher.os.environ
    A.launcher.os.environ = dict(values)
    try:
        yield
    finally:
        A.launcher.os.environ = saved


@contextlib.contextmanager
def host_defaults(machine: Path, run):
    """The launcher's own defaults replaced for one case: `/etc/machine-id` and `run=subprocess.run`."""
    launcher = A.launcher
    saved = launcher.host_id.__defaults__, launcher.launch_plan.__kwdefaults__
    launcher.host_id.__defaults__ = (Path(machine),)
    launcher.launch_plan.__kwdefaults__ = {**launcher.launch_plan.__kwdefaults__, "machine_id_path": Path(machine),
                                           "run": run}
    try:
        yield
    finally:
        launcher.host_id.__defaults__, launcher.launch_plan.__kwdefaults__ = saved


@contextlib.contextmanager
def inspect_defaults(**values):
    """`inspect`'s keyword defaults (`run`, `proc`, `sys_cgroup`, `unit_dir`) replaced while `main` runs."""
    saved = A.launcher.inspect.__kwdefaults__
    A.launcher.inspect.__kwdefaults__ = {**saved, **values}
    try:
        yield
    finally:
        A.launcher.inspect.__kwdefaults__ = saved


@contextlib.contextmanager
def subprocess_run(double):
    """`subprocess.run` as `network` reads it at call time, restored afterwards."""
    saved = subprocess.run
    subprocess.run = double
    try:
        yield
    finally:
        subprocess.run = saved


@contextlib.contextmanager
def getpwnam(double):
    saved = A.launcher.pwd.getpwnam
    A.launcher.pwd.getpwnam = double
    try:
        yield
    finally:
        A.launcher.pwd.getpwnam = saved


@contextlib.contextmanager
def keep_cwd():
    saved = os.getcwd()
    try:
        yield
    finally:
        os.chdir(saved)


class Exec(Exception):
    """Raised by the recording `execve` double: the exec is never performed."""


def execve_double(calls):
    def execve(path, argv, env):
        calls.append({"path": path, "argv": list(argv), "env_keys": sorted(env), "cwd": os.getcwd(),
                      "ZEUS_AIBOX_ROLE": env.get("ZEUS_AIBOX_ROLE")})
        raise Exec("execve")
    return execve


def run_main(ws, argv, environ=None, execves=None):
    """`launcher.main(argv)` in process: the exit code, the document `emit` wrote to stdout, and stderr."""
    launcher = A.launcher
    out, err = io.StringIO(), io.StringIO()
    saved_stream = launcher.emit.__defaults__
    launcher.emit.__defaults__ = (out,)
    result = {}
    try:
        with contextlib.redirect_stderr(err):
            with environment(environ if environ is not None else {}):
                if execves is None:
                    result["exit"] = launcher.main(list(argv))
                else:
                    with A.install_execve(execve_double(execves)):
                        try:
                            result["exit"] = launcher.main(list(argv))
                        except Exec:
                            result["exit"] = "exec_reached"
    finally:
        launcher.emit.__defaults__ = saved_stream
    result["stdout"], result["stderr"] = parsed(ws, out.getvalue()), parsed(ws, err.getvalue())
    return result


# ============================== service fixtures ==================================================================

def render_args(ws, **overrides):
    values = dict(output=str(ws.root / "units"), root="/srv/zeus", user="zeus", group=None, uid=1500,
                  home="/home/zeus", path=A.launcher.DEFAULT_PATH, python="/usr/bin/python3", tool=TOOL_PATH,
                  config_env=CONFIG_ENV, secret_env=SECRET_ENV, web_port=8787, skip_account_check=True)
    values.update(overrides)
    return SimpleNamespace(**values)


def rendered(ws, **overrides):
    manifest = A.launcher.render(render_args(ws, **overrides))
    return ws.root / "units", manifest


def unit_texts(directory: Path) -> dict:
    return {unit: (directory / unit).read_text() for unit in A.launcher.UNITS}


class Host:
    def __init__(self, ws):
        launcher = A.launcher
        self.root = ws.root / "srv"
        self.release = self.root / "releases" / REVISION
        (self.release / ".venv" / "bin").mkdir(parents=True)
        python = self.release / ".venv" / "bin" / "python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)
        (self.release / "src" / "codex_harness").mkdir(parents=True)
        (self.release / "src" / "codex_harness" / "__init__.py").write_text("")
        (self.root / "releases" / "current").symlink_to(self.release)
        self.control = self.root / "runtime" / "control"
        self.control.mkdir(parents=True)
        self.machine = ws.root / "machine-id"
        self.machine.write_text("0123456789abcdef0123456789abcdef\n")
        self.environ = {"ZEUS_AIBOX_ROOT": str(self.root), "PATH": launcher.DEFAULT_PATH}
        self.host_id = launcher.host_id(self.machine)


def no_systemctl(argv, **_kwargs):
    raise AssertionError(f"unexpected command {argv}")


def activate(host, **overrides):
    receipt = {"schema": A.launcher.ACTIVATION_SCHEMA, "host_id": host.host_id, "state": "restored_paused",
               "release_revision": REVISION, "migration_id": "aibox-migration-001"}
    receipt.update(overrides)
    (host.control / A.launcher.ACTIVATION_FILE).write_text(json.dumps(receipt))


def plan(host, role="fleet", run=no_systemctl, **environ):
    return A.launcher.launch_plan(role, {**host.environ, **environ}, machine_id_path=host.machine, run=run)


def plan_view(ws, result):
    keys = ("ZEUS_REPOSITORY", "HARNESS_REPOSITORY", "VIRTUAL_ENV", "ZEUS_AIBOX_RELEASE", "ZEUS_AIBOX_ROLE", "PATH")
    return ws.n({"argv": result["argv"], "cwd": result["cwd"], "release": result["release"],
                 "revision": result["revision"], "migration_id": result["migration_id"],
                 "env_keys": sorted(result["env"]), "env_set": {k: result["env"][k] for k in keys},
                 "pythonhome_absent": "PYTHONHOME" not in result["env"]})


def rec(ws, call, mirrors=None, **extra):
    out = {"result": attempt(ws, call)}
    if mirrors:
        out["mirrors"] = mirrors
    out.update(ws.n(extra))
    return out


def completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def fake_proc(ws, processes):
    proc = ws.root / "proc"
    proc.mkdir(exist_ok=True)
    os.chmod(proc, 0o700)  # explicit: `file_facts_present` records this mode; never the process umask (CI 0022)
    for pid, (argv, cgroup) in processes.items():
        entry = proc / str(pid)
        entry.mkdir(parents=True, exist_ok=True)
        entry.joinpath("cmdline").write_bytes(b"\0".join(w.encode() for w in argv) + b"\0")
        entry.joinpath("cgroup").write_text(f"0::{cgroup}\n")
        entry.joinpath("comm").write_text(Path(argv[0]).name[:15] + "\n")
    return proc


def fake_cgroups(ws, groups):
    root = ws.root / "cgroup"
    root.mkdir(exist_ok=True)
    for group, pids in groups.items():
        directory = root / group.lstrip("/")
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("cgroup.procs").write_text("".join(f"{p}\n" for p in pids))
    return root


def fake_runner(*, fleet_active=True, containers=(), docker_ok=True, ip_ok=True):
    """M7's `fake_runner`: answers the fixed systemctl/docker/ip forms, raises on any other (LABELLED double)."""
    calls = []

    def run(argv, **_kwargs):
        calls.append(list(argv))
        launcher = A.launcher
        if argv[0] == "systemctl":
            unit = argv[2]
            active = unit != launcher.FLEET_UNIT or fleet_active
            group = f"/system.slice/{unit}" if active else ""
            out = (f"ActiveState={'active' if active else 'inactive'}\nControlGroup={group}\n"
                   f"MainPID={100 if active else 0}\nNRestarts=0\nKillMode=control-group\n")
            return completed(argv, 0, out)
        if argv[:2] == ["docker", "ps"]:
            if not docker_ok:
                return completed(argv, 1, "", "Cannot connect")
            return completed(argv, 0, "".join(json.dumps(c) + "\n" for c in containers))
        if argv[:2] == ["docker", "inspect"]:
            return completed(argv, 0, "300\n")
        if argv[0] == "ip":
            if not ip_ok:
                return completed(argv, 1, "", "no ip")
            if "route" in argv:
                return completed(argv, 0, json.dumps([{"dev": "enp5s0", "gateway": "192.168.0.1"}]))
            return completed(argv, 0, json.dumps([
                {"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
                {"ifname": "enp5s0", "addr_info": [{"family": "inet", "local": "192.168.0.10", "prefixlen": 24}]}]))
        raise AssertionError(f"unexpected command {argv}")

    run.calls = calls
    return run


def run_inspect(ws, processes, *, runner, groups=None):
    proc = fake_proc(ws, processes)
    cgroups = fake_cgroups(ws, groups or {FLEET_CG: [p for p, (_, g) in processes.items() if g == FLEET_CG]})
    return A.launcher.inspect(ws.root / "srv", run=runner, proc=proc, sys_cgroup=cgroups, unit_dir=ws.root / "units")


# ============================== service: render, verify, unit semantics ===========================================

def svc_constants(ws):
    L = A.launcher
    return {"EXIT": [L.EXIT_OK, L.EXIT_FINDINGS, L.EXIT_USAGE, L.EXIT_REFUSED], "UNITS": list(L.UNITS),
            "SERVICES": list(L.SERVICES), "ROLES": dict(L.ROLES), "OWNER_SERVICES": list(L.OWNER_SERVICES),
            "MANAGED_STATE": list(L.MANAGED_STATE), "ACTIVE_STATES": list(L.ACTIVE_STATES),
            "schemas": [L.ACTIVATION_SCHEMA, L.FLEET_OWNER_SCHEMA], "files": [L.FENCE_FILE, L.ACTIVATION_FILE,
                                                                               L.FLEET_OWNER_FILE],
            "DEFAULT_PATH": L.DEFAULT_PATH, "LIVE_UNIT_DIRS": list(L.LIVE_UNIT_DIRS), "SHOW_PROPERTIES": list(L.SHOW_PROPERTIES),
            "RUN_LABEL": L.RUN_LABEL, "templates_dir": L.TEMPLATES.name, "polkit": L.POLKIT.name,
            "template_files": sorted(p.name for p in L.TEMPLATES.iterdir()),
            "template_sha256": {p.name: sha(p.read_bytes()) for p in sorted(L.TEMPLATES.iterdir())},
            "polkit_sha256": sha(L.POLKIT.read_bytes()),
            "tool_sha256": sha(Path(L.__file__).read_bytes()),
            "utcnow_is_substituted": L.utcnow() == CLOCK_Z}


def svc_render(ws):
    L = A.launcher
    directory, manifest = rendered(ws)
    texts = unit_texts(directory)
    return {"mirrors": "test_render_resolves_every_placeholder_and_records_hashes", "manifest": ws.n(manifest),
            "files_on_disk": sorted(p.name for p in directory.iterdir()),
            "disk_sha256": {name: sha(p.read_bytes()) for name, p in sorted((p.name, p) for p in directory.iterdir())},
            "no_placeholder_survives": {u: not L.PLACEHOLDER.search(t) for u, t in texts.items()},
            "recorded_hash_matches_disk": {u: manifest["files"][u]["sha256"] == sha(t.encode()) for u, t in texts.items()},
            "manifest_file_equals_returned": json.loads((directory / "render-manifest.json").read_text()) == manifest,
            "manifest_file_uid": json.loads((directory / "render-manifest.json").read_text())["uid"],
            "fleet_unit": texts[L.FLEET_UNIT],
            "group_defaults_to_user": manifest["values"]["SERVICE_GROUP"]}


def svc_render_defaults(ws):
    """`render_values` defaults: tool/config/secret derived from `--root`, a trailing slash, an explicit group."""
    L = A.launcher
    args = render_args(ws, root="/srv/zeus/", tool=None, config_env=None, secret_env=None, group="ops")
    return {"values": attempt(ws, lambda: L.render_values(args)),
            "root_slash": attempt(ws, lambda: L.render_values(render_args(ws, root="/", tool=None, config_env=None,
                                                                           secret_env=None)))}


def svc_render_text(ws):
    L = A.launcher
    return {"all_resolved": attempt(ws, lambda: L.render_text("a=@X@ b=@Y@", {"X": "1", "Y": "2"})),
            "unresolved": attempt(ws, lambda: L.render_text("a=@X@ @B_C@ @B_C@ @Z@", {"X": "1"})),
            "no_placeholders": attempt(ws, lambda: L.render_text("plain", {"X": "1"}))}


def svc_static_policy(ws):
    directory, _ = rendered(ws)
    result = A.launcher.verify(SimpleNamespace(directory=str(directory), systemd_analyze=False))
    return {"mirrors": "test_rendered_units_pass_static_policy", "result": ws.n(result),
            "findings_per_unit": {u: A.launcher.unit_findings(u, t) for u, t in unit_texts(directory).items()}}


def svc_verify_missing(ws):
    (ws.root / "empty").mkdir()
    partial = ws.root / "partial"
    partial.mkdir()
    (partial / "zeus-aibox-fleet.service").write_text("[Service]\nUser=zeus\n")
    return {"empty_directory": attempt(ws, lambda: A.launcher.verify(
                SimpleNamespace(directory=str(ws.root / "empty"), systemd_analyze=True), run=no_systemctl)),
            "one_incomplete_unit": attempt(ws, lambda: A.launcher.verify(
                SimpleNamespace(directory=str(partial), systemd_analyze=False)))}


def svc_render_live_dirs(ws):
    out = {}
    for target in ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system", "/etc/polkit-1/rules.d",
                   "/usr/share/polkit-1"):
        out[target] = rec(ws, lambda target=target: A.launcher.render(render_args(ws, output=target)),
                          "test_render_refuses_live_systemd_directories")
    return out


RENDER_REFUSALS = [
    ("root_relative", {"root": "srv/zeus"}), ("root_space", {"root": "/srv/ze us"}), ("root_percent", {"root": "/srv/%h"}),
    ("path_relative_entry", {"path": "/usr/bin:bin"}), ("path_windows_entry", {"path": "/usr/bin:/mnt/c/Windows"}),
    ("uid_root", {"uid": 0}), ("uid_none", {"uid": None}), ("web_port_privileged", {"web_port": 80}),
    # characterized directly (no M7 test): the remaining refusals of `render_values`
    ("web_port_too_high", {"web_port": 65536}), ("home_relative", {"home": "home/zeus"}),
    ("python_relative", {"python": "python3"}), ("tool_relative", {"tool": "zeus_aibox_service.py"}),
    ("dollar", {"home": "/home/$USER"}), ("quote", {"python": "/usr/bin/py'thon"}),
    ("backslash", {"tool": "/srv/zeus\\tool"}), ("semicolon", {"config_env": "/srv/a;b"}),
    ("empty_secret_env", {"secret_env": ""}), ("user_uppercase", {"user": "Zeus"}),
    ("user_leading_digit", {"user": "1zeus"}), ("user_too_long", {"user": "z" * 33}),
]


def svc_render_refusals(ws):
    out = {}
    for label, override in RENDER_REFUSALS:
        out[label] = rec(ws, lambda override=override: A.launcher.render(render_args(ws, **override)),
                         "test_render_refuses_non_explicit_values_without_partial_output",
                         units_exist=(ws.root / "units").exists())
    return out


def svc_account_database(ws):
    L = A.launcher
    account = SimpleNamespace(pw_uid=1000, pw_dir="/home/zeus")

    def unknown(name):
        raise KeyError(name)

    out = {}
    with getpwnam(lambda name: account):
        out["uid_mismatch"] = attempt(ws, lambda: L.render(render_args(ws, skip_account_check=False, uid=1500)))
        out["match"] = attempt(ws, lambda: sorted(L.render(render_args(ws, skip_account_check=False, uid=1000))))
        out["home_mismatch"] = attempt(ws, lambda: L.render(render_args(ws, skip_account_check=False, uid=1000,
                                                                       home="/home/other")))
    with getpwnam(unknown):
        out["user_unknown"] = attempt(ws, lambda: L.render(render_args(ws, skip_account_check=False, uid=1000)))
    out["mirrors"] = "test_render_checks_the_account_database_unless_fixture"
    return out


def svc_unit_semantics(ws):
    L = A.launcher
    directory, _ = rendered(ws)
    texts = unit_texts(directory)
    sections = {unit: L.parse_unit(text) for unit, text in texts.items()}
    fleet = sections[L.FLEET_UNIT]
    return {"mirrors": "test_fleet_unit_is_single_bounded_control_group_owner",
            "parsed": {u: {s: [list(p) for p in pairs] for s, pairs in secs.items()} for u, secs in sections.items()},
            "fleet_is_not_a_template": "@" not in L.FLEET_UNIT,
            "fleet_service": dict(fleet["Service"]), "fleet_unit_section": dict(fleet["Unit"]),
            "fleet_environment": L.values_of(fleet, "Service", "Environment"),
            "fleet_execstart": L.values_of(fleet, "Service", "ExecStart"),
            "fleet_execstartpre": L.values_of(fleet, "Service", "ExecStartPre"),
            "fleet_execstoppost": L.values_of(fleet, "Service", "ExecStopPost"),
            "values_of_absent": [L.values_of(fleet, "Nope", "x"), L.values_of(fleet, "Service", "Nope")]}


def svc_parse_unit_edges(ws):
    L = A.launcher
    text = "# c\n; c\nstray=1\n[A]\nk = v\nk=w\n\n[B]\nnoequals\nx=a=b\n"
    return {"parsed": {s: [list(p) for p in pairs] for s, pairs in L.parse_unit(text).items()}}


def svc_secrets(ws):
    L = A.launcher
    directory, _ = rendered(ws)
    out = {"mirrors": "test_secrets_only_come_from_environment_files", "units": {}}
    for unit in L.SERVICES:
        sections = L.parse_unit((directory / unit).read_text())
        out["units"][unit] = {"EnvironmentFile": L.values_of(sections, "Service", "EnvironmentFile"),
                              "secret_named_environment": [v for v in L.values_of(sections, "Service", "Environment")
                                                           if L.SECRET_NAME.search(v.split("=", 1)[0])]}
    return out


MUTATIONS = [
    (("KillMode=control-group", "KillMode=process"), "kill_mode_not_control_group"),
    (("TimeoutStopSec=180", "TimeoutStopSec=infinity"), "stop_timeout_unbounded"),
    (("Restart=on-failure", "Restart=always"), "restart_policy_unbounded"),
    (("RestartPreventExitStatus=78", "RestartPreventExitStatus=1"), "refusal_restart_not_prevented"),
    (("User=zeus", "User=root"), "explicit_non_root_user_missing"),
    (("StartLimitBurst=3", "#"), "start_limit_missing"),
    (("Environment=LANG=C.UTF-8", "Environment=CLAUDE_CODE_OAUTH_TOKEN=x"), "secret_in_environment_line"),
    (("launch --role fleet", "launch --role fleet --resume"), "resume_reference"),
    (("WorkingDirectory=/srv/zeus/runtime/control", "WorkingDirectory=~"), "working_directory_not_absolute"),
    (("Environment=HOME=/home/zeus", "Environment=HOME=/mnt/d/workspaces"), "windows_path_reference"),
    (("Environment=LANG=C.UTF-8", "Environment=ZEUS_DB_HOST=192.168.0.10"), "lan_ip_literal"),
    # characterized directly: the remaining policy checks
    (("Group=zeus", "Group="), "explicit_group_missing"),
    (("ExecStart=/usr/bin/python3", "ExecStart=python3"), "exec_not_absolute"),
    (("SendSIGKILL=yes", "SendSIGKILL=no"), "final_sigkill_disabled"),
    (("TimeoutStopSec=180", "TimeoutStopSec=0"), "stop_timeout_unbounded"),
    (("Environment=ZEUS_AIBOX_ROOT=/srv/zeus", "Environment=ZEUS_AIBOX_ROOT=srv"), "root_not_explicit"),
    (("User=zeus", "User=0"), "explicit_non_root_user_missing"),
]


def svc_weakened_units(ws):
    L = A.launcher
    directory, _ = rendered(ws)
    text = (directory / L.FLEET_UNIT).read_text()
    out = {}
    for index, ((old, new), code) in enumerate(MUTATIONS):
        mutated = text.replace(old, new, 1)
        out[f"{index:02d}_{code}"] = {"mirrors": "test_static_policy_rejects_each_weakened_unit" if index < 11 else None,
                                     "changed": mutated != text, "findings": L.unit_findings(L.FLEET_UNIT, mutated),
                                     "expected_code_present": code in {f["code"] for f in
                                                                       L.unit_findings(L.FLEET_UNIT, mutated)}}
        if out[f"{index:02d}_{code}"]["mirrors"] is None:
            del out[f"{index:02d}_{code}"]["mirrors"]
    other = text.replace("Type=simple", "Type=oneshot", 1)
    out["oneshot_skips_long_running_checks"] = {"changed": other != text,
                                                "findings": L.unit_findings(L.FLEET_UNIT, text.replace(
                                                    "KillMode=control-group", "KillMode=process").replace(
                                                    "[Service]", "[Service]\nType=oneshot", 1))}
    out["target_is_not_a_service"] = {"findings": L.unit_findings("zeus-aibox.target", "[Unit]\nDescription=x@Y@\n")}
    out["placeholder_left"] = {"findings": L.unit_findings("zeus-aibox.target", "[Unit]\nDescription=@LEFT@\n")}
    out["no_path"] = {"findings": L.unit_findings(L.FLEET_UNIT, text.replace("Environment=PATH=", "Environment=NOPATH=", 1))}
    out["relative_path_entry"] = {"findings": L.unit_findings(L.FLEET_UNIT, text.replace(
        "Environment=PATH=" + L.DEFAULT_PATH, "Environment=PATH=/usr/bin:bin", 1))}
    return out


def svc_loopback(ws):
    L = A.launcher
    directory, _ = rendered(ws)
    text = (directory / L.FLEET_UNIT).read_text().replace("Environment=LANG=C.UTF-8",
                                                          "Environment=ZEUS_DB_HOST=127.0.0.1", 1)
    return {"mirrors": "test_loopback_literals_are_allowed", "findings": L.unit_findings(L.FLEET_UNIT, text),
            "_loopback": {value: L._loopback(value) for value in ("127.0.0.1", "127.8.9.1", "192.168.0.10", "10.0.0.1",
                                                                   "999.1.1.1", "1.2.3", "not-an-address")}}


def svc_install_targets(ws):
    L = A.launcher
    directory, _ = rendered(ws)
    wanted = {unit: L.values_of(L.parse_unit((directory / unit).read_text()), "Install", "WantedBy") for unit in L.UNITS}
    return {"mirrors": "test_only_the_target_and_timer_install_into_boot_targets", "WantedBy": wanted}


def svc_systemd_analyze(ws):
    """`verify(systemd_analyze=True)` through LABELLED run doubles (the real binary is unreachable here)."""
    L = A.launcher
    directory, _ = rendered(ws)
    args = SimpleNamespace(directory=str(directory), systemd_analyze=True)

    def double(result=None, raises=None):
        calls = []

        def run(argv, **kwargs):
            calls.append({"argv": list(argv), "kwargs": sorted(kwargs.items(), key=lambda item: item[0])})
            if raises is not None:
                raise raises
            return result
        run.calls = calls
        return run

    def case(run, mirrors=None):
        out = {"result": attempt(ws, lambda: L.verify(args, run=run)), "calls": ws.n(run.calls)}
        if mirrors:
            out["mirrors"] = mirrors
        return out

    unit_line = f"{directory}/zeus-aibox-fleet.service:3: Unknown key name 'Bogus'"
    out = {
        "missing_binary": case(double(raises=FileNotFoundError("systemd-analyze")),
                               "test_systemd_analyze_unavailable_is_not_a_pass"),
        "timeout": case(double(raises=subprocess.TimeoutExpired(["systemd-analyze"], 60))),
        "passed": case(double(completed(["x"], 0, "", ""))),
        "failed_by_exit": case(double(completed(["x"], 1, "", ""))),
        "failed_by_our_diagnostic": case(double(completed(["x"], 0, "", unit_line + "\n"))),
        "unit_name_in_line": case(double(completed(["x"], 0, "zeus-aibox.target: bad\n", ""))),
        "unrelated_host_diagnostics": case(double(completed(["x"], 1, "other.service: warn\n", "elsewhere: warn\n"))),
        "diagnostics_capped": case(double(completed(["x"], 1, "", "".join(f"{unit_line} {i}\n" for i in range(45))))),
        "not_requested": {"result": attempt(ws, lambda: L.verify(SimpleNamespace(directory=str(directory),
                                                                                  systemd_analyze=False), run=no_systemctl))},
        "real_binary": {"mirrors_unreachable": "test_systemd_analyze_verify_accepts_rendered_units_offline",
                        "unreachable": UNREACHABLE["test_systemd_analyze_verify_accepts_rendered_units_offline"]},
    }
    return out


# ============================== service: launch ===================================================================

def svc_fleet_launch(ws):
    L = A.launcher
    h = Host(ws)
    activate(h)
    result = plan(h)
    return {"mirrors": "test_fleet_launch_binds_pinned_release_and_never_resumes", "plan": plan_view(ws, result),
            "argv_has_resume": "resume" in result["argv"], "env_path_starts_with_venv_bin":
                result["env"]["PATH"].startswith(str(h.release / ".venv" / "bin") + ":"),
            "passthrough_environ_kept": {k: result["env"][k] for k in h.environ if k != "PATH"} == {
                k: v for k, v in h.environ.items() if k != "PATH"},
            "host_id_shape": L.host_id(h.machine) == h.host_id and h.host_id.startswith("machine-id-sha256:"),
            "host_id": h.host_id}


def svc_pythonhome(ws):
    h = Host(ws)
    activate(h)
    result = plan(h, PYTHONHOME="/somewhere", EXTRA="kept")
    return {"plan": plan_view(ws, result), "extra_kept": result["env"].get("EXTRA"),
            "caller_environ_untouched": "PYTHONHOME" in {**h.environ, "PYTHONHOME": 1}}


def svc_monitor_roles(ws):
    L = A.launcher
    h = Host(ws)
    collect = plan(h, "monitor-collect")
    web = plan(h, "monitor-web", ZEUS_AIBOX_WEB_PORT="8790")
    default_web = plan(h, "monitor-web")
    return {"mirrors": "test_monitor_roles_need_no_activation_and_stay_loopback",
            "collect": plan_view(ws, collect), "web": plan_view(ws, web), "web_default_port": plan_view(ws, default_web),
            "web_has_ipv4_literal": any(L.IPV4.search(word) for word in web["argv"]),
            "port_not_digits": attempt(ws, lambda: plan(h, "monitor-web", ZEUS_AIBOX_WEB_PORT="80a")),
            "port_empty": attempt(ws, lambda: plan(h, "monitor-web", ZEUS_AIBOX_WEB_PORT=""))}


def svc_fence(ws):
    L = A.launcher
    h = Host(ws)
    activate(h)
    fence = h.control / L.FENCE_FILE
    fence.write_text("not json")
    out = {"mirrors": "test_fence_refuses_every_role_even_when_unreadable", "roles": {}}
    for role in L.ROLES:
        out["roles"][role] = attempt(ws, lambda role=role: plan(h, role, run=no_systemctl))
    fence.unlink()
    os.symlink("/nonexistent-fence-target", fence)
    out["dangling_symlink_still_fences"] = attempt(ws, lambda: plan(h, "fleet"))
    return out


RECEIPT_CASES = [
    ("missing", None), ("other_host", {"host_id": "machine-id-sha256:" + "0" * 64}), ("state_staged", {"state": "staged"}),
    ("state_rollback_required", {"state": "rollback_required"}), ("revision_mismatch", {"release_revision": "b" * 40}),
    ("schema", {"schema": "urn:other:1"}), ("migration_empty", {"migration_id": ""}),
    # characterized directly
    ("migration_not_str", {"migration_id": 7}), ("state_limited_active", {"state": "limited_active"}),
    ("state_qualified", {"state": "qualified"}),
]


def svc_activation_receipt(ws):
    out = {}
    for label, overrides in RECEIPT_CASES:
        local = Ws()
        try:
            h = Host(local)
            if overrides is not None:
                activate(h, **overrides)
            out[label] = {"mirrors": "test_fleet_refuses_without_matching_activation_receipt" if label in (
                "missing", "other_host", "state_staged", "state_rollback_required", "revision_mismatch", "schema",
                "migration_empty") else None, "result": attempt(local, lambda: plan(h))}
            if out[label]["mirrors"] is None:
                del out[label]["mirrors"]
        finally:
            local.close()
    ws2 = Ws()
    try:
        h = Host(ws2)
        (h.control / A.launcher.ACTIVATION_FILE).write_text("not json")
        out["unreadable_json"] = {"result": attempt(ws2, lambda: plan(h))}
        (h.control / A.launcher.ACTIVATION_FILE).write_text("[1, 2]")
        out["not_an_object"] = {"result": attempt(ws2, lambda: plan(h))}
        (h.control / A.launcher.ACTIVATION_FILE).unlink()
        (h.control / A.launcher.ACTIVATION_FILE).mkdir()
        out["is_a_directory"] = {"result": attempt(ws2, lambda: plan(h))}
    finally:
        ws2.close()
    return out


def svc_check_activation(ws):
    L = A.launcher
    h = Host(ws)
    activate(h)
    return {"valid": attempt(ws, lambda: L.check_activation(h.control, h.release, h.host_id)),
            "revision_name_is_the_release_directory": h.release.name == REVISION}


def svc_pinned_release(ws):
    L = A.launcher
    h = Host(ws)
    activate(h)
    current = h.root / "releases" / "current"
    out = {"pinned": attempt(ws, lambda: L.pinned_release(h.root))}
    current.unlink()
    out["mirrors"] = "test_unpinned_release_pointer_is_refused"
    out["pointer_missing"] = attempt(ws, lambda: plan(h))
    moving = h.root / "releases" / "main"
    moving.mkdir()
    current.symlink_to(moving)
    out["moving_name"] = attempt(ws, lambda: plan(h))
    current.unlink()
    outside = ws.root / "elsewhere" / REVISION
    outside.mkdir(parents=True)
    current.symlink_to(outside)
    out["revision_name_outside_releases"] = attempt(ws, lambda: L.pinned_release(h.root))
    current.unlink()
    current.symlink_to(h.release)
    python = h.release / ".venv" / "bin" / "python"
    python.chmod(0o644)
    out["interpreter_not_executable"] = attempt(ws, lambda: L.pinned_release(h.root))
    python.chmod(0o755)
    package = h.release / "src" / "codex_harness" / "__init__.py"
    package.unlink()
    out["package_missing"] = attempt(ws, lambda: L.pinned_release(h.root))
    return out


ENVIRONMENT_CASES = [("root_empty", {"ZEUS_AIBOX_ROOT": ""}), ("path_empty", {"PATH": ""}), ("path_dot", {"PATH": "/usr/bin:."}),
                     ("path_windows", {"PATH": "/usr/bin:/mnt/c/Windows/System32"}),
                     ("root_relative", {"ZEUS_AIBOX_ROOT": "srv/zeus"}), ("path_relative", {"PATH": "usr/bin"})]


def svc_launch_environment(ws):
    h = Host(ws)
    activate(h)
    out = {}
    for label, environ in ENVIRONMENT_CASES:
        out[label] = {"mirrors": "test_launch_requires_explicit_linux_environment" if label in (
            "root_empty", "path_empty", "path_dot", "path_windows") else None,
            "result": attempt(ws, lambda environ=environ: plan(h, **environ))}
        if out[label]["mirrors"] is None:
            del out[label]["mirrors"]
    out["role_unknown"] = {"result": attempt(ws, lambda: plan(h, "nonsense"))}
    out["root_missing_key"] = {"result": attempt(ws, lambda: A.launcher.launch_plan(
        "fleet", {"PATH": A.launcher.DEFAULT_PATH}, machine_id_path=h.machine, run=no_systemctl))}
    return out


def svc_fleet_owner(ws):
    L = A.launcher
    h = Host(ws)
    owner = h.control / L.FLEET_OWNER_FILE
    good = {"schema": L.FLEET_OWNER_SCHEMA, "owner": "managed-fleet", "unit": L.MANAGED_FLEET_UNIT}
    out = {"absent": attempt(ws, lambda: L.fleet_owner(h.control))}
    owner.write_text(json.dumps(good))
    out["valid"] = attempt(ws, lambda: L.fleet_owner(h.control))
    for label, document in (("schema", {**good, "schema": "urn:other:1"}), ("owner", {**good, "owner": "bootstrap"}),
                            ("unit", {**good, "unit": "zeus-aibox-fleet.service"}), ("list", [good])):
        owner.write_text(json.dumps(document))
        out["invalid_" + label] = attempt(ws, lambda: L.fleet_owner(h.control))
    owner.write_text("not json")
    out["unreadable_json"] = attempt(ws, lambda: L.fleet_owner(h.control))
    owner.unlink()
    os.symlink("/nonexistent-owner-target", owner)
    out["dangling_symlink_is_unreadable_never_absent"] = attempt(ws, lambda: L.fleet_owner(h.control))
    return out


def systemctl_double(output=None, returncode=0, raises=None):
    calls = []

    def run(argv, **kwargs):
        calls.append({"argv": list(argv), "timeout": kwargs.get("timeout")})
        if raises is not None:
            raise raises
        return completed(argv, returncode, output)
    run.calls = calls
    return run


def svc_managed_roles(ws):
    """The managed-fleet and owner-actions roles, and `bootstrap_inactive` (characterized directly)."""
    L = A.launcher
    h = Host(ws)
    activate(h)
    (h.control / L.FLEET_OWNER_FILE).write_text(json.dumps(
        {"schema": L.FLEET_OWNER_SCHEMA, "owner": "managed-fleet", "unit": L.MANAGED_FLEET_UNIT}))
    out = {}
    states = {"inactive": ("ActiveState=inactive\n", 0), "failed": ("ActiveState=failed\n", 0),
              "active": ("ActiveState=active\n", 0), "activating": ("ActiveState=activating\n", 0),
              "deactivating": ("ActiveState=deactivating\n", 0), "reloading": ("ActiveState=reloading\n", 0),
              "unknown_word": ("ActiveState=maintenance\n", 0), "no_state_line": ("MainPID=3\n", 0),
              "nonzero_exit": ("ActiveState=inactive\n", 1), "empty_output": ("", 0)}
    out["managed_fleet_by_bootstrap_state"] = {}
    for label, (text, code) in states.items():
        run = systemctl_double(text, code)
        out["managed_fleet_by_bootstrap_state"][label] = {"result": attempt(ws, lambda run=run: plan(h, "managed-fleet", run=run)),
                                                          "calls": run.calls}
    for label, raises in (("os_error", OSError("no systemctl")), ("timeout", subprocess.TimeoutExpired(["systemctl"], 20))):
        run = systemctl_double(raises=raises)
        out["managed_fleet_by_bootstrap_state"][label] = {"result": attempt(ws, lambda run=run: plan(h, "managed-fleet", run=run)),
                                                          "calls": run.calls}
    out["managed_fleet_plan"] = plan_view(ws, plan(h, "managed-fleet", run=systemctl_double("ActiveState=inactive\n")))
    out["bootstrap_fleet_retired"] = attempt(ws, lambda: plan(h, "fleet"))
    (h.control / L.FLEET_OWNER_FILE).unlink()
    out["managed_fleet_without_owner_record"] = attempt(ws, lambda: plan(h, "managed-fleet",
                                                                          run=systemctl_double("ActiveState=inactive\n")))
    out["fleet_without_owner_record_is_bootstrap"] = plan_view(ws, plan(h, "fleet"))
    policies = {}
    for label, value in (("unset", None), ("empty", ""), ("one", "alpha"), ("two", "alpha,beta"), ("duplicate", "alpha,alpha"),
                         ("bad_token", "alpha,-beta"), ("trailing_comma", "alpha,"), ("space", "alpha, beta"),
                         ("long_token", "p" * 64), ("too_long_token", "p" * 65)):
        environ = {} if value is None else {"ZEUS_OWNER_ACTIONS_POLICY": value}
        policies[label] = attempt(ws, lambda environ=environ: plan(h, "owner-actions", **environ)["argv"][2:])
    out["owner_actions_policy"] = policies
    out["owner_actions_without_receipt"] = {}
    (h.control / L.ACTIVATION_FILE).unlink()
    out["owner_actions_without_receipt"] = attempt(ws, lambda: plan(h, "owner-actions", ZEUS_OWNER_ACTIONS_POLICY="a"))
    return out


def svc_launch_main(ws):
    """`launch`/`main launch`: refusals exit 78, `--dry-run` execs nothing, and the exec is reached only through the hook."""
    L = A.launcher
    h = Host(ws)
    out = {}
    with host_defaults(h.machine, no_systemctl), keep_cwd():
        out["refusal_missing_receipt"] = {
            "mirrors": "test_launch_cli_refusal_exits_78_without_executing",
            "result": run_main(ws, ["launch", "--role", "fleet"], h.environ, execves=[]),
            }
        activate(h)
        calls = []
        out["dry_run"] = {"result": run_main(ws, ["launch", "--role", "fleet", "--dry-run"], h.environ, execves=calls),
                          "execve_calls": calls}
        calls = []
        before = os.getcwd()
        out["exec_reached"] = {"result": run_main(ws, ["launch", "--role", "fleet"], h.environ, execves=calls),
                               "execve_calls": ws.n(calls), "cwd_changed_to_control": calls[0]["cwd"] == str(h.control),
                               "cwd_before_was_not_control": before != str(h.control)}
        os.chdir(before)
        calls = []
        out["exec_reached_monitor_web"] = {"result": run_main(ws, ["launch", "--role", "monitor-web"],
                                                              {**h.environ, "ZEUS_AIBOX_WEB_PORT": "8801"}, execves=calls),
                                           "execve_calls": ws.n(calls)}
        os.chdir(before)
        (h.control / L.FENCE_FILE).write_text("{}")
        calls = []
        out["refusal_fenced"] = {"result": run_main(ws, ["launch", "--role", "fleet"], h.environ, execves=calls),
                                 "execve_calls": calls}
        (h.control / L.FENCE_FILE).unlink()
        activate(h, state="staged")
        out["refusal_state_fact_is_reported"] = run_main(ws, ["launch", "--role", "fleet"], h.environ, execves=[])
    out["usage_error"] = {"mirrors": "test_cli_usage_error_is_exit_2",
                          "exit": run_main(ws, ["launch", "--role", "nonsense"])["exit"],
                          "no_role": run_main(ws, ["launch"])["exit"], "no_command": run_main(ws, [])["exit"],
                          "unknown_command": run_main(ws, ["frobnicate"])["exit"],
                          "help_is_exit_0": run_main(ws, ["--help"])["exit"],
                          "subcommand_help_is_exit_0": run_main(ws, ["verify", "-h"])["exit"]}
    return out


# ============================== service: journal ==================================================================

def svc_journal(ws):
    path = ws.root / "fleet-service-journal.jsonl"
    run_id = "f" * 32
    start = run_main(ws, ["journal", "start", "--role", "fleet", "--journal", str(path)], {"INVOCATION_ID": run_id})
    stop = run_main(ws, ["journal", "exit", "--role", "fleet", "--journal", str(path)],
                    {"INVOCATION_ID": run_id, "SERVICE_RESULT": "success", "EXIT_CODE": "exited", "EXIT_STATUS": "0"})
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return {"mirrors": "test_journal_pairs_start_and_exit_by_invocation", "start": start, "exit": stop, "lines": lines,
            "pairs": [(e["event"], e["run_id"]) for e in lines],
            "raw_bytes_sha256": sha(path.read_bytes()), "every_line_sorted_keys_and_newline": path.read_bytes().endswith(b"\n")}


def svc_journal_lines(ws):
    """The journal bytes the relocation `runner_state` reads (that reader is the delivery.fleet_recovery_collectors family)."""
    L = A.launcher
    path = ws.root / "journal.jsonl"
    L.append_journal(path, L.journal_entry("start", "fleet", {"INVOCATION_ID": "1" * 32}))
    after_start = path.read_text()
    L.append_journal(path, L.journal_entry("exit", "fleet", {"INVOCATION_ID": "1" * 32}))
    L.append_journal(path, L.journal_entry("start", "fleet", {"INVOCATION_ID": "2" * 32}))
    nested = ws.root / "a" / "b" / "journal.jsonl"
    L.append_journal(nested, {"k": 1})
    return {"mirrors_unreachable": "test_journal_matches_the_relocation_runner_state_contract",
            "after_start": after_start, "all": path.read_text(), "nested_parent_created": nested.read_text(),
            "exit_entry_fields": L.journal_entry("exit", "fleet", {"INVOCATION_ID": "3" * 32, "SERVICE_RESULT": "exit-code",
                                                                    "EXIT_CODE": "exited", "EXIT_STATUS": "1"}),
            "start_entry_has_no_exit_fields": sorted(L.journal_entry("start", "managed-fleet", {"INVOCATION_ID": "3" * 32})),
            "owner_actions_unit": L.journal_entry("start", "owner-actions", {"INVOCATION_ID": "3" * 32})["unit"]}


def svc_journal_refusals(ws):
    L = A.launcher
    path = ws.root / "j.jsonl"
    out = {"outside_systemd": {"mirrors": "test_journal_refuses_outside_systemd",
                               "result": run_main(ws, ["journal", "start", "--role", "fleet", "--journal", str(path)], {}),
                               "journal_written": path.exists()}}
    for label, invocation in (("short_id", "abc"), ("uppercase_id", "F" * 32), ("long_id", "f" * 33), ("empty_id", "")):
        out[label] = attempt(ws, lambda invocation=invocation: L.journal_entry("start", "fleet", {"INVOCATION_ID": invocation}))
    out["bad_event_is_usage"] = run_main(ws, ["journal", "pause", "--role", "fleet", "--journal", str(path)],
                                         {"INVOCATION_ID": "f" * 32})["exit"]
    out["bad_role_is_usage"] = run_main(ws, ["journal", "start", "--role", "nope", "--journal", str(path)],
                                        {"INVOCATION_ID": "f" * 32})["exit"]
    return out


# ============================== service: inspect, network, templates, parser, main ================================

def view_inspect(ws, result):
    return ws.n(result)


def svc_inspect_healthy(ws):
    L = A.launcher
    runner = fake_runner(containers=[CONTAINER])
    result = run_inspect(ws, {100: (RUNNER_ARGV, FLEET_CG), 300: (["/bin/sleep", "1"], DOCKER_CG)}, runner=runner)
    fleet = result["units"][L.FLEET_UNIT]
    container = result["docker"]["containers"][0]
    mutating = {"start", "stop", "restart", "kill", "rm", "enable", "disable", "resume"}
    return {"mirrors": "test_inspect_healthy_single_owner_with_container_outside_cgroup", "result": view_inspect(ws, result),
            "fleet_cgroup_pids": [p["pid"] for p in fleet["cgroup_processes"]["processes"]],
            "container_outside_the_unit_cgroup": container["cgroup"] != fleet["ControlGroup"],
            "runner_calls": runner.calls, "any_mutating_word": any(set(argv) & mutating for argv in runner.calls)}


def svc_inspect_findings(ws):
    out = {}
    for label, mirrors, processes, kwargs in (
        ("runner_outside_unit", "test_inspect_reports_runner_outside_the_owner_unit",
         {100: (RUNNER_ARGV, FLEET_CG),
          200: (["/usr/bin/uv", "run", "zeus", "fleet", "run", "--once"], "/user.slice/session-4.scope")}, {}),
        ("duplicate_runner_inside_unit", "test_inspect_reports_duplicate_runner_inside_the_unit",
         {100: (RUNNER_ARGV, FLEET_CG), 101: (RUNNER_ARGV, FLEET_CG)}, {}),
        ("docker_residue_after_owner_stop", "test_inspect_reports_docker_residue_after_owner_stop",
         {300: (["/bin/sleep", "1"], DOCKER_CG)}, {"fleet_active": False, "containers": [CONTAINER], "groups": {FLEET_CG: []}}),
        ("docker_unavailable", "test_inspect_docker_unavailable_is_unknown_not_empty",
         {100: (RUNNER_ARGV, FLEET_CG)}, {"docker_ok": False}),
        ("ip_unavailable", None, {100: (RUNNER_ARGV, FLEET_CG)}, {"ip_ok": False}),
        ("harness_named_runner_and_relative_words", None,
         {100: (["harness", "fleet", "run"], FLEET_CG), 101: (["/bin/echo", "fleet", "run"], FLEET_CG),
          102: (["/opt/harness", "fleet"], FLEET_CG), 103: (["/x/zeus", "fleet", "run", "--once"], "/user.slice/a.scope")}, {}),
    ):
        local = Ws()
        try:
            groups = kwargs.pop("groups", None)
            runner = fake_runner(**kwargs)
            result = run_inspect(local, processes, runner=runner, groups=groups)
            out[label] = {"findings": local.n(result["findings"]), "docker": local.n(result["docker"]),
                          "fleet_runners": local.n(result["fleet_runners"]), "network": local.n(result["network"]),
                          "units": local.n({u: {k: v for k, v in state.items() if k != "cgroup_processes"}
                                            for u, state in result["units"].items()})}
            if mirrors:
                out[label]["mirrors"] = mirrors
        finally:
            local.close()
    return out


def svc_inspect_fenced_secret(ws):
    L = A.launcher
    control = ws.root / "srv" / "runtime" / "control"
    control.mkdir(parents=True)
    (control / L.FENCE_FILE).write_text("{}")
    (control / L.FENCE_FILE).chmod(0o640)
    secrets = ws.root / "srv" / "secrets"
    secrets.mkdir()
    (secrets / "zeus-aibox.env").write_text("X=1\n")
    (secrets / "zeus-aibox.env").chmod(0o644)
    result = run_inspect(ws, {100: (RUNNER_ARGV, FLEET_CG)}, runner=fake_runner())
    codes = sorted({f["code"] for f in result["findings"]})
    (secrets / "zeus-aibox.env").chmod(0o600)
    tight = run_inspect(ws, {100: (RUNNER_ARGV, FLEET_CG)}, runner=fake_runner())
    return {"mirrors": "test_inspect_flags_active_owner_on_fenced_host_and_loose_secret_mode",
            "codes": codes, "findings": ws.n(result["findings"]), "fence": ws.n(result["fence"]),
            "activation": ws.n(result["activation"]), "secret_env": ws.n(result["secret_env"]),
            "secret_body_not_in_result": "X=1" not in json.dumps(result),
            "tight_secret": ws.n(tight["secret_env"]),
            "tight_findings": ws.n(tight["findings"])}


def svc_inspect_references(ws):
    L = A.launcher
    units = ws.root / "units"
    units.mkdir()
    (units / L.FLEET_UNIT).write_text("[Service]\nEnvironment=X=192.168.0.10\n")
    config = ws.root / "srv" / "config"
    config.mkdir(parents=True)
    (config / "zeus-aibox.env").write_text("ZEUS_ARTIFACTS=D:\\workspaces\\zeus\n")
    result = run_inspect(ws, {100: (RUNNER_ARGV, FLEET_CG)}, runner=fake_runner())
    codes = sorted({(f["code"], Path(f["file"]).name) for f in result["findings"] if "file" in f})
    scan = L.reference_scan([units / L.FLEET_UNIT, config / "zeus-aibox.env", ws.root / "absent"])
    (units / "ok.service").write_text("[Service]\nEnvironment=X=127.0.0.1 /mnt/data\n")
    (units / "mnt.service").write_text("path=/mnt/c/Windows\nversion 1.2.3\n")
    return {"mirrors": "test_inspect_flags_lan_ip_and_windows_paths_in_installed_config", "codes": codes,
            "scan": ws.n(scan),
            "scan_more": ws.n(L.reference_scan([units / "ok.service", units / "mnt.service"]))}


def svc_inspect_network(ws):
    result = run_inspect(ws, {100: (RUNNER_ARGV, FLEET_CG)}, runner=fake_runner())
    return {"mirrors": "test_inspect_network_excludes_loopback", "ipv4": result["network"]["ipv4"],
            "network": result["network"], "windows_observer": result["windows_observer"],
            "schema": result["schema"], "read_only": result["read_only"], "observed_at": result["observed_at"],
            "docker_cgroup_note": result["docker_cgroup_note"]}


def svc_inspect_parts(ws):
    """The helpers of `inspect` over a fixture: `unit_state`, `cgroup_of`, `cgroup_processes`, `fleet_runners`,
    `labelled_containers`, `file_facts`, `addresses` (characterized directly)."""
    L = A.launcher
    proc = fake_proc(ws, {100: (RUNNER_ARGV, FLEET_CG), 7: (["/bin/sleep", "1"], "/user.slice/a.scope")})
    (proc / "notapid").mkdir()
    (proc / "9").mkdir()  # a process whose files vanished
    (proc / "8").mkdir()
    (proc / "8" / "cgroup").write_text("1:name=systemd:/x\n0::/system.slice/y\n")
    cgroups = fake_cgroups(ws, {FLEET_CG: [100, 555]})
    runner = fake_runner(containers=[CONTAINER, {**CONTAINER, "ID": "d" * 64, "State": "exited"},
                                     {**CONTAINER, "ID": "e" * 64, "Labels": "other=1"}])
    out = {"unit_state_ok": attempt(ws, lambda: L.unit_state(L.FLEET_UNIT, runner)),
           "unit_state_unavailable": attempt(ws, lambda: L.unit_state(L.FLEET_UNIT, lambda argv, **k: completed(argv, 3))),
           "unit_state_oserror": attempt(ws, lambda: L.unit_state(L.FLEET_UNIT, systemctl_double(raises=OSError("x")))),
           "unit_state_timeout": attempt(ws, lambda: L.unit_state(
               L.FLEET_UNIT, systemctl_double(raises=subprocess.TimeoutExpired(["x"], 20)))),
           "cgroup_of": {pid: L.cgroup_of(pid, proc) for pid in (100, 7, 8, 9, 4242)},
           "cgroup_processes": {"ok": attempt(ws, lambda: L.cgroup_processes(FLEET_CG, cgroups, proc)),
                                "empty_name": attempt(ws, lambda: L.cgroup_processes("", cgroups, proc)),
                                "unreadable": attempt(ws, lambda: L.cgroup_processes("/nope", cgroups, proc))},
           "fleet_runners": attempt(ws, lambda: L.fleet_runners(proc)),
           "fleet_runners_no_proc": attempt(ws, lambda: L.fleet_runners(ws.root / "no-proc")),
           "labelled_containers": attempt(ws, lambda: L.labelled_containers(runner, proc)),
           "label_parse": [L._label("a=b,zeus.isolated.run=r1,c", L.RUN_LABEL), L._label("", L.RUN_LABEL),
                           L._label("zeus.isolated.run", L.RUN_LABEL)],
           "file_facts_absent": L.file_facts(ws.root / "absent"),
           "file_facts_present": ws.n(L.file_facts(ws.root / "proc")),
           "addresses": attempt(ws, lambda: L.addresses(runner)),
           "addresses_bad_json": attempt(ws, lambda: L.addresses(lambda argv, **k: completed(argv, 0, "not json")))}
    bad_lines = fake_runner(containers=[])
    out["labelled_containers_ignores_non_json_lines"] = attempt(ws, lambda: L.labelled_containers(
        lambda argv, **k: completed(argv, 0, "garbage\n" + json.dumps(CONTAINER) + "\n") if argv[:2] == ["docker", "ps"]
        else bad_lines(argv), proc))
    return out


def svc_network_comparison(ws):
    L = A.launcher
    before = {"ipv4": [{"ifname": "enp5s0", "address": "192.168.0.10/24"}],
              "default_routes": [{"dev": "enp5s0", "gateway": "192.168.0.1"}]}
    same = L.compare_network(before, json.loads(json.dumps(before)))
    after = {"ipv4": [{"ifname": "enp5s0", "address": "172.30.1.20/24"}],
             "default_routes": [{"dev": "enp5s0", "gateway": "172.30.1.254"}]}
    routes_only = {"ipv4": before["ipv4"], "default_routes": [{"dev": "enp5s0", "gateway": "192.168.0.254"}]}
    return {"mirrors": "test_network_comparison_reports_ip_change_only", "same": same,
            "changed": L.compare_network(before, after), "routes_only": L.compare_network(before, routes_only),
            "empty_both": L.compare_network({}, {})}


def svc_templates(ws):
    L = A.launcher
    out = {"mirrors": "test_templates_hold_no_lan_address_so_ip_change_needs_no_rerender", "templates": {}}
    for template in sorted(L.TEMPLATES.glob("*.in")):
        text = template.read_text()
        out["templates"][template.name] = {"only_loopback_literals": all(L._loopback(a) for a in L.IPV4.findall(text)),
                                           "no_windows_path": not L.WINDOWS_PATH.search(text),
                                           "placeholders": sorted(set(L.PLACEHOLDER.findall(text))),
                                           "sha256": sha(template.read_bytes())}
    polkit = L.POLKIT.read_text()
    out["polkit"] = {"placeholders": sorted(set(L.PLACEHOLDER.findall(polkit))), "sha256": sha(L.POLKIT.read_bytes())}
    return out


def option_view(action):
    return {"options": list(action.option_strings), "dest": action.dest, "required": action.required,
            "default": action.default if isinstance(action.default, (str, int, bool, type(None))) else repr(action.default),
            "choices": list(action.choices) if action.choices and not isinstance(action.choices, dict) else None,
            "nargs": action.nargs, "type": getattr(action.type, "__name__", None), "help": action.help,
            "kind": type(action).__name__}


def parser_view(parser):
    sub = next(a for a in parser._actions if type(a).__name__ == "_SubParsersAction")
    return {"prog": parser.prog, "description": parser.description, "required_subcommand": sub.required, "dest": sub.dest,
            "commands": {name: {"help": next((c.help for c in sub._choices_actions if c.dest == name), None),
                                "actions": [option_view(a) for a in child._actions if type(a).__name__ != "_HelpAction"]}
                         for name, child in sub.choices.items()}}


def svc_parser(ws):
    return {"parser": parser_view(A.launcher.parser())}


def svc_main_commands(ws):
    """`main` for render, verify, inspect, network and host-id over the doubles (characterized directly)."""
    L = A.launcher
    out = {}
    out_dir = ws.root / "main-units"
    base = ["render", "--output", str(out_dir), "--user", "zeus", "--uid", "1500", "--home", "/home/zeus",
            "--skip-account-check", "--tool", TOOL_PATH, "--config-env", CONFIG_ENV, "--secret-env", SECRET_ENV]
    out["render"] = run_main(ws, base)
    out["render_files"] = sorted(p.name for p in out_dir.iterdir())
    out["render_refused"] = run_main(ws, ["render", "--output", "/etc/systemd/system", "--user", "zeus", "--uid", "1500",
                                          "--home", "/home/zeus", "--skip-account-check"])
    out["render_missing_required"] = run_main(ws, ["render", "--output", str(out_dir)])["exit"]
    out["verify_clean"] = run_main(ws, ["verify", str(out_dir)])
    (out_dir / L.FLEET_UNIT).write_text((out_dir / L.FLEET_UNIT).read_text().replace("KillMode=control-group", "KillMode=process"))
    out["verify_findings"] = run_main(ws, ["verify", str(out_dir)])
    h = Host(ws)
    runner = fake_runner(containers=[CONTAINER])
    proc = fake_proc(ws, {100: (RUNNER_ARGV, FLEET_CG)})
    cgroups = fake_cgroups(ws, {FLEET_CG: [100]})
    snapshot = ws.root / "inspect.json"
    with inspect_defaults(run=runner, proc=proc, sys_cgroup=cgroups, unit_dir=ws.root / "units"):
        out["inspect"] = run_main(ws, ["inspect", "--root", str(h.root), "--output", str(snapshot)])
        out["inspect_no_output"] = run_main(ws, ["inspect", "--root", str(h.root)])["exit"]
    out["inspect_output_file_equals_stdout"] = json.loads(snapshot.read_text()) == json.loads(
        json.dumps(out["inspect"]["stdout"]).replace("<root>", str(ws.root)))
    out["inspect_tmp_left_behind"] = sorted(p.name for p in ws.root.glob("inspect.json*"))
    baseline = ws.root / "baseline.json"
    recorded = ws.root / "recorded.json"
    ip = fake_runner()
    with subprocess_run(ip):
        out["network_plain"] = run_main(ws, ["network"])
        out["network_record"] = run_main(ws, ["network", "--record", str(recorded)])
    baseline.write_text(json.dumps({"ipv4": [{"ifname": "enp5s0", "address": "10.0.0.2/24"}], "default_routes": []}))
    with subprocess_run(ip):
        out["network_baseline"] = run_main(ws, ["network", "--baseline", str(baseline)])
    out["recorded_equals_current"] = json.loads(recorded.read_text()) == out["network_plain"]["stdout"]["current"]
    out["network_calls"] = ip.calls
    with host_defaults(h.machine, no_systemctl):
        out["host_id"] = run_main(ws, ["host-id"])
    return out


# ============================== data CLI ==========================================================================

def lib(name):
    """The loaded module the CLI itself uses (a library call is labelled `via: library`)."""
    return sys.modules["aibox_data." + name]


def stream(count: int) -> bytes:
    """A deterministic byte stream (never os.urandom): a sha256 counter."""
    return b"".join(hashlib.sha256(index.to_bytes(4, "big")).digest() * 32 for index in range((count // 1024) + 1))[:count]


BIG = stream(3 * 1024 * 1024 + 17)


def cli(ws, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = A.data_main([str(a) for a in argv])
    return {"exit": code, "stdout": parsed(ws, out.getvalue()), "stderr": parsed(ws, err.getvalue())}


def make_tree(ws, name="source", links=True):
    source = ws.root / name
    (source / "logs").mkdir(parents=True)
    (source / "logs" / "run.log").write_bytes(b"line\n" * 1000)
    (source / "big.bin").write_bytes(BIG)
    (source / "empty.txt").write_bytes(b"")
    if links:
        os.symlink("logs/run.log", source / "latest")
    return source


def seal(ws, tree, name="manifest.json", migration="mig-1", root="art"):
    """`inventory --out`: the CLI result and the manifest it wrote."""
    path = ws.root / name
    result = cli(ws, "inventory", "--migration-id", migration, "--root", f"{root}={tree}", "--host", "fixture", "--out", path)
    return path, result, (json.loads(path.read_text()) if path.exists() else None)


def stage_args(manifest, tree, staging, work, root="art", limit=None):
    argv = ["stage", "--manifest", manifest, "--root-id", root, "--source", tree, "--staging", staging, "--work", work]
    return argv + (["--limit-bytes", limit] if limit is not None else [])


def verify_args(manifest, staging, work=None, root="art"):
    return ["verify-staged", "--manifest", manifest, "--root-id", root, "--staging", staging] + (
        ["--work", work] if work is not None else [])


def partial_of(work: Path, root_id: str, relative: str) -> Path:
    return work / "partials" / (hashlib.sha256(f"{root_id}\0{relative}".encode()).hexdigest() + ".part")


def tree_listing(ws, root: Path) -> list:
    return sorted(ws.n(str(p.relative_to(root))) + ("@" + os.readlink(p) if p.is_symlink() else "")
                  for p in root.rglob("*")) if root.exists() else None


def manifest_view(ws, manifest):
    """A manifest without its volatile or path-derived members: entries (mtime masked), findings, totals."""
    return ws.n({"schema": manifest["schema"], "migration_id": manifest["migration_id"], "host": manifest["host"],
                 "scanned_at": manifest["scanned_at"], "roots": manifest["roots"], "digest": manifest["digest"]})


def data_inventory_links(ws):
    tree = make_tree(ws)
    os.symlink("/outside-zeus-fixture/dir", tree / "outside")
    path, result, manifest = seal(ws, tree)
    entries = {e["path"]: e for e in manifest["roots"]["art"]["entries"]}
    return {"mirrors": "test_manifest_records_bytes_hashes_and_links_without_following", "cli": result,
            "manifest": manifest_view(ws, manifest),
            "big_sha_matches_file": entries["big.bin"]["sha256"] == hashlib.sha256(BIG).hexdigest(),
            "big_bytes_match_file": entries["big.bin"]["bytes"] == len(BIG),
            "latest_entry": entries["latest"], "outside_escapes_root": entries["outside"]["escapes_root"],
            "external_symlinks": manifest["roots"]["art"]["findings"]["external_symlinks"],
            "digest_valid_per_cli": cli(ws, "verify-manifest", path)}


def data_inventory_clean(ws):
    tree = make_tree(ws)
    path, result, manifest = seal(ws, tree)
    stdout = cli(ws, "inventory", "--migration-id", "mig-1", "--root", f"art={tree}", "--host", "fixture")
    return {"written": result, "manifest": manifest_view(ws, manifest),
            "to_stdout": {"exit": stdout["exit"], "stderr": stdout["stderr"],
                          "same_entries_as_written": [{k: v for k, v in e.items() if k != "mtime_ns"} for e in
                                                      stdout["stdout"]["roots"]["art"]["entries"]] == [
                              {k: v for k, v in e.items() if k != "mtime_ns"} for e in
                              ws.n(manifest["roots"]["art"]["entries"])]}}


def data_inventory_refusals(ws):
    tree = make_tree(ws)
    other = ws.root / "other"
    other.mkdir()
    out = {"bad_migration_id": cli(ws, "inventory", "--migration-id", "bad id", "--root", f"art={tree}", "--host", "h"),
           "root_not_a_directory": cli(ws, "inventory", "--migration-id", "m", "--root", f"art={tree / 'big.bin'}", "--host", "h"),
           "root_missing": cli(ws, "inventory", "--migration-id", "m", "--root", f"art={ws.root / 'nope'}", "--host", "h"),
           "root_without_name": cli(ws, "inventory", "--migration-id", "m", "--root", str(tree), "--host", "h"),
           "root_duplicate": cli(ws, "inventory", "--migration-id", "m", "--root", f"a={tree}", "--root", f"a={other}", "--host", "h"),
           "no_root": cli(ws, "inventory", "--migration-id", "m")["exit"],
           "two_roots": cli(ws, "inventory", "--migration-id", "m", "--root", f"a={tree}", "--root", f"b={other}", "--host", "h")}
    out["two_roots"] = {"exit": out["two_roots"]["exit"], "roots": sorted(out["two_roots"]["stdout"]["roots"])}
    return out


def data_manifest_digest(ws):
    tree = make_tree(ws)
    inv = lib("inventory")
    path, _, first = seal(ws, tree)
    os.utime(tree / "empty.txt", (1, 1))  # mtime is descriptive, not identity
    _, _, second = seal(ws, tree, "second.json")
    tampered = json.loads(path.read_text())
    tampered["roots"]["art"]["entries"][0]["bytes"] += 1
    bad = ws.root / "tampered.json"
    bad.write_text(json.dumps(tampered))
    wrong_schema = ws.root / "schema.json"
    wrong_schema.write_text(json.dumps({**first, "schema": "other"}))
    (ws.root / "garbage.json").write_text("{")
    return {"mirrors": "test_manifest_digest_is_stable_and_detects_tampering",
            "digest_stable_across_an_mtime_change": first["digest"] == second["digest"],
            "mtime_differs_between_scans": first["roots"]["art"]["entries"][1].get("mtime_ns") is not None,
            "verify_untouched": cli(ws, "verify-manifest", path), "verify_tampered": cli(ws, "verify-manifest", bad),
            "verify_wrong_schema": cli(ws, "verify-manifest", wrong_schema),
            "verify_missing_file": cli(ws, "verify-manifest", ws.root / "absent.json"),
            "verify_not_json": cli(ws, "verify-manifest", ws.root / "garbage.json"),
            "via_library_digest_is_a_sha256_ref": first["digest"].startswith("sha256:") and len(first["digest"]) == 71,
            "via_library_recomputed_equal": inv.manifest_digest(first) == first["digest"]}


def data_windows_names(ws):
    tree = ws.root / "names"
    tree.mkdir()
    for name, body in (("Report.json", "a"), ("report.JSON", "b"), ("con.txt", "c"), ("bad:name", "d"), ("trail.", "e"),
                       ("LPT1", "f"), ("ok.txt", "g")):
        (tree / name).write_text(body)
    path, result, manifest = seal(ws, tree)
    found = manifest["roots"]["art"]["findings"]
    return {"mirrors": "test_case_collisions_and_windows_names_are_reported", "cli": result,
            "case_collisions": found["case_collisions"],
            "windows_incompatible": {item["path"]: item["problems"] for item in found["windows_incompatible"]},
            "findings": found}


def data_artifact_store(ws):
    def put(root, body, meta=None):
        key = hashlib.sha256(body).hexdigest()
        (root / f"{key}.txt").write_bytes(body)
        (root / f"{key}.json").write_text(json.dumps(meta or {"ref": "sha256:" + key, "bytes": len(body),
                                                              "source": "fixture", "at": "t"}))
        return key

    store = ws.root / "store"
    store.mkdir()
    good = put(store, b"hello")
    clean = cli(ws, "verify-artifacts", store)
    bad_bytes = put(store, b"world", {"ref": "sha256:" + hashlib.sha256(b"world").hexdigest(), "bytes": 99})
    modified = put(store, b"original")
    (store / f"{modified}.txt").write_bytes(b"tampered")
    orphan = "b" * 64
    (store / f"{orphan}.json").write_text("{}")
    missing_meta = put(store, b"nometa")
    (store / f"{missing_meta}.json").unlink()
    bad_json = put(store, b"badjson")
    (store / f"{bad_json}.json").write_text("{")
    wrong_ref = put(store, b"wrongref", {"ref": "sha256:" + "0" * 64, "bytes": 8})
    string_bytes = put(store, b"strbytes", {"ref": "", "bytes": "8"})
    (store / "notes.txt").write_text("x")
    (store / "sub").mkdir()
    result = cli(ws, "verify-artifacts", store)
    keys = {"good": good, "bad_bytes": bad_bytes, "modified": modified, "orphan": orphan, "missing_meta": missing_meta,
            "bad_json": bad_json, "wrong_ref": wrong_ref, "string_bytes": string_bytes}
    return {"mirrors": "test_artifact_store_verification_matches_file_artifacts_rules", "clean_store": clean,
            "result": result, "keys": keys,
            "good_not_a_problem": good not in {p["key"] for p in result["stdout"]["problems"]},
            "store_missing": cli(ws, "verify-artifacts", ws.root / "no-store")}


def data_artifact_store_real(ws):
    return {"mirrors_unreachable": "test_artifact_store_accepts_real_file_artifacts_output",
            "unreachable": UNREACHABLE["test_artifact_store_accepts_real_file_artifacts_output"]}


def data_path_references(ws):
    root = ws.root / "refs"
    root.mkdir()
    log = root / "old.log"
    log.write_text('run at D:\\workspaces\\zeus\\artifacts\\x and "C:/Users/rudtn/zeus/y"\n')
    (root / "clean.txt").write_text("nothing here\n")
    (root / "words.txt").write_text("abc:/not-a-drive and x:\\ one and E:\\\\double\\\\slash\n")
    before = log.read_bytes()
    report = cli(ws, "scan-paths", root)
    out_file = ws.root / "scan.json"
    to_file = cli(ws, "scan-paths", root, "--out", out_file)
    return {"mirrors": "test_path_references_are_reported_not_rewritten", "report": report,
            "count_for_old_log": report["stdout"]["files_with_windows_paths"][0]["count"],
            "file_unchanged": log.read_bytes() == before, "to_file": to_file,
            "file_equals_report": json.loads(out_file.read_text()) == json.loads(json.dumps(report["stdout"]).replace(
                "<root>", str(ws.root))), "root_missing": cli(ws, "scan-paths", ws.root / "nope")}


def data_stage_roundtrip(ws):
    tree = make_tree(ws)
    manifest, _, _ = seal(ws, tree)
    staging, work = ws.root / "staging", ws.root / "work"
    first = cli(ws, *stage_args(manifest, tree, staging, work))
    verified = cli(ws, *verify_args(manifest, staging, work))
    second = cli(ws, *stage_args(manifest, tree, staging, work))
    return {"mirrors": "test_stage_copies_verifies_and_is_idempotent", "stage": first, "verify": verified,
            "latest_link": os.readlink(staging / "latest"), "work_listing": sorted(os.listdir(work)),
            "staging_listing": tree_listing(ws, staging),
            "staged_bytes_equal_source": all((staging / p).read_bytes() == (tree / p).read_bytes() for p in
                                             ("big.bin", "empty.txt", "logs/run.log")),
            "second_actions": sorted({e["action"] for e in second["stdout"]["events"]}), "second_exit": second["exit"],
            "journal_document": ws.n(json.loads((work / "journal.json").read_text()))}


def data_stage_resume(ws):
    tree = make_tree(ws)
    manifest, _, _ = seal(ws, tree)
    staging, work = ws.root / "staging", ws.root / "work"
    stopped = cli(ws, *stage_args(manifest, tree, staging, work, limit=1024 * 1024))
    part = partial_of(work, "art", "big.bin")
    interrupted = cli(ws, *verify_args(manifest, staging, work))
    partial_size = part.stat().st_size
    resumed = cli(ws, *stage_args(manifest, tree, staging, work))
    big = next(e for e in resumed["stdout"]["events"] if e["path"] == "big.bin")
    return {"mirrors": "test_interrupted_copy_resumes_from_verified_partial", "stopped": stopped,
            "partial_is_between_zero_and_full": 0 < partial_size < len(BIG), "partial_size": partial_size,
            "big_not_staged_yet": not os.path.lexists(staging / "big.bin"), "verify_interrupted": interrupted,
            "partial_name_is_in_verify": interrupted["stdout"]["partials"] == [part.name], "resumed": resumed,
            "resumed_from_bytes": big["resumed_from_bytes"], "final_bytes_equal": (staging / "big.bin").read_bytes() == BIG,
            "final_verify": cli(ws, *verify_args(manifest, staging, work))}


def data_stage_refusals(ws):
    tree = make_tree(ws)
    manifest, _, _ = seal(ws, tree)
    staging, work = ws.root / "staging", ws.root / "work"
    first = cli(ws, *stage_args(manifest, tree, staging, work, limit=1024))
    partial_of(work, "art", "big.bin").write_bytes(b"not the source prefix")
    diverged = cli(ws, *stage_args(manifest, tree, staging, work))
    staging.mkdir(exist_ok=True)
    (staging / "empty.txt").write_bytes(b"different")
    conflict = cli(ws, *stage_args(manifest, tree, staging, ws.root / "work2"))
    return {"mirrors": "test_diverged_partial_and_conflicting_staged_file_are_refused", "first": first,
            "partial_diverged": diverged, "staged_conflict": conflict,
            "conflicting_file_never_overwritten": (staging / "empty.txt").read_bytes() == b"different"}


def data_stage_source_changes(ws):
    tree = make_tree(ws)
    manifest, _, first = seal(ws, tree)
    (tree / "logs" / "run.log").write_bytes(b"changed after seal")
    changed = cli(ws, *stage_args(manifest, tree, ws.root / "staging", ws.root / "work"))
    out = {"mirrors": "test_source_change_after_seal_is_refused", "refused": changed,
           "nothing_staged": not (ws.root / "staging" / "logs" / "run.log").exists()}
    other = Ws()
    try:
        tree = make_tree(other)
        manifest, _, _ = seal(other, tree)
        work = other.root / "work"
        cli(other, *stage_args(manifest, tree, other.root / "staging", work))
        (tree / "new.txt").write_text("new")
        changed_manifest, _, _ = seal(other, tree, "changed.json")
        out["same_migration_id_other_digest"] = {
            "mirrors": "test_same_migration_id_with_different_digest_is_refused",
            "result": cli(other, *stage_args(changed_manifest, tree, other.root / "staging", work))}
    finally:
        other.close()
    return out


def data_stage_external_symlink(ws):
    tree = make_tree(ws)
    os.symlink("/etc/hostname", tree / "outside")
    manifest, sealed, _ = seal(ws, tree)
    staged = cli(ws, *stage_args(manifest, tree, ws.root / "staging", ws.root / "work"))
    verified = cli(ws, "verify-staged", "--manifest", manifest, "--root-id", "art", "--staging", ws.root / "staging")
    return {"mirrors": "test_external_symlink_is_not_created_and_blocks_verification", "inventory": sealed, "stage": staged,
            "outside_not_created": not os.path.lexists(ws.root / "staging" / "outside"), "verify": verified}


def data_stage_symlinked_ancestors(ws):
    out = {}
    source, staging, outside = ws.root / "source", ws.root / "staging", ws.root / "outside"
    (source / "sub").mkdir(parents=True)
    (source / "sub" / "evidence").write_bytes(b"proof")
    staging.mkdir()
    outside.mkdir()
    os.symlink(outside, staging / "sub")
    manifest, _, _ = seal(ws, source)
    out["ancestor"] = {"mirrors": "test_symlinked_staging_ancestor_is_refused_before_any_write",
                       "result": cli(ws, *stage_args(manifest, source, staging, ws.root / "work")),
                       "outside_empty": os.listdir(outside) == [],
                       "partials_empty": os.listdir(ws.root / "work" / "partials") == [],
                       "verify": cli(ws, *verify_args(manifest, staging))}
    nested = Ws()
    try:
        source, staging, outside = nested.root / "source", nested.root / "staging", nested.root / "outside"
        (source / "a" / "b").mkdir(parents=True)
        (source / "a" / "b" / "f").write_bytes(b"x")
        (staging / "a").mkdir(parents=True)
        outside.mkdir()
        os.symlink(outside, staging / "a" / "b")
        manifest, _, _ = seal(nested, source)
        out["nested_ancestor"] = {"mirrors": "test_symlinked_nested_ancestor_created_after_first_level_is_refused",
                                  "result": cli(nested, *stage_args(manifest, source, staging, nested.root / "work")),
                                  "outside_empty": os.listdir(outside) == []}
    finally:
        nested.close()
    return out


def data_stage_symlinked_roots(ws):
    tree = make_tree(ws)
    manifest, _, _ = seal(ws, tree)
    outside = ws.root / "outside"
    outside.mkdir()
    os.symlink(outside, ws.root / "staging-link")
    out = {"mirrors": "test_symlinked_staging_root_work_dir_partial_and_journal_are_refused",
           "staging_root": cli(ws, *stage_args(manifest, tree, ws.root / "staging-link", ws.root / "w1"))}
    os.symlink(outside, ws.root / "work-link")
    out["work_dir"] = cli(ws, *stage_args(manifest, tree, ws.root / "s2", ws.root / "work-link"))
    victim = outside / "victim"
    victim.write_bytes(b"keep")
    work = ws.root / "w3"
    cli(ws, *stage_args(manifest, tree, ws.root / "s3", work, limit=1024))
    partial_of(work, "art", "big.bin").unlink()
    os.symlink(victim, partial_of(work, "art", "big.bin"))
    out["partial"] = cli(ws, *stage_args(manifest, tree, ws.root / "s3", work))
    work4 = ws.root / "w4"
    work4.mkdir()
    os.symlink(victim, work4 / "journal.json")
    out["journal"] = cli(ws, *stage_args(manifest, tree, ws.root / "s4", work4))
    out["victim_untouched"] = victim.read_bytes() == b"keep" and os.listdir(outside) == ["victim"]
    return out


def data_work_dir_rules(ws):
    tree = make_tree(ws)
    manifest, _, _ = seal(ws, tree)
    foreign = ws.root / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("someone else's")
    return {"mirrors": "test_work_dir_must_be_migration_owned_and_separate",
            "foreign": cli(ws, *stage_args(manifest, tree, ws.root / "staging", foreign)),
            "inside_staging": cli(ws, *stage_args(manifest, tree, ws.root / "staging", ws.root / "staging" / "w")),
            "staging_in_source": cli(ws, *stage_args(manifest, tree, tree / "copy", ws.root / "work")),
            "unknown_root_id": cli(ws, *stage_args(manifest, tree, ws.root / "s9", ws.root / "w9", root="nope")),
            "missing_manifest": cli(ws, *stage_args(ws.root / "absent.json", tree, ws.root / "s9", ws.root / "w9"))}


def data_unsafe_manifest_path(ws):
    tree = make_tree(ws)
    path, _, manifest = seal(ws, tree)
    inv = lib("inventory")
    out = {"mirrors": "test_unsafe_manifest_paths_are_refused_even_with_a_valid_digest"}
    for label, value in (("parent_escape", "../escape"), ("absolute", "/abs"), ("dot_segment", "a/./b"),
                         ("empty_segment", "a//b")):
        changed = json.loads(path.read_text())
        changed["roots"]["art"]["entries"][0]["path"] = value
        changed["digest"] = inv.manifest_digest(changed)
        document = ws.root / f"{label}.json"
        document.write_text(json.dumps(changed))
        out[label] = {"digest_valid_per_cli": cli(ws, "verify-manifest", document)["exit"],
                      "stage": cli(ws, *stage_args(document, tree, ws.root / f"staging-{label}", ws.root / f"work-{label}")),
                      "escaped": (ws.root / "escape").exists()}
    return out


def data_unreadable_subtree(ws):
    if os.geteuid() == 0:
        return {"mirrors": "test_unreadable_source_subtree_blocks_stage_and_verification",
                "unreachable": "root ignores directory permissions: needs a non-root user"}
    source = ws.root / "source"
    (source / "denied").mkdir(parents=True)
    (source / "denied" / "proof.txt").write_bytes(b"hidden")
    os.chmod(source / "denied", 0)
    try:
        path, sealed, manifest = seal(ws, source)
    finally:
        os.chmod(source / "denied", 0o700)
    root = manifest["roots"]["art"]
    staged = cli(ws, *stage_args(path, source, ws.root / "staging", ws.root / "work"))
    verified = cli(ws, *verify_args(path, ws.root / "staging", ws.root / "work"))
    return {"mirrors": "test_unreadable_source_subtree_blocks_stage_and_verification", "inventory": sealed,
            "entries": root["entries"], "unreadable": root["unreadable"], "stage": staged, "verify": verified,
            "compare_roots_never_matches_unreadable": lib("inventory").compare_roots(root, root)["match"] is False,
            "via": "library (compare_roots)"}


def data_empty_root(ws):
    source = ws.root / "source"
    source.mkdir()
    manifest, sealed, _ = seal(ws, source)
    return {"mirrors": "test_truly_empty_root_stages_and_verifies", "inventory": sealed,
            "stage": cli(ws, *stage_args(manifest, source, ws.root / "staging", ws.root / "work")),
            "verify": cli(ws, *verify_args(manifest, ws.root / "staging", ws.root / "work"))}


def data_part_named_files(ws):
    source = ws.root / "source"
    source.mkdir()
    (source / "log").write_bytes(BIG[:2 * 1024 * 1024])
    (source / "log.part").write_bytes(b"a real file whose name ends in .part\n")
    (source / "big.bin.part").write_bytes(b"another")
    manifest, _, _ = seal(ws, source)
    staging, work = ws.root / "staging", ws.root / "work"
    stopped = cli(ws, *stage_args(manifest, source, staging, work, limit=1024 * 1024))
    resumed = cli(ws, *stage_args(manifest, source, staging, work))
    verified = cli(ws, *verify_args(manifest, staging, work))
    return {"mirrors": "test_source_files_named_part_stage_and_verify_under_real_names", "stopped": stopped,
            "event_paths_when_stopped": [e["path"] for e in stopped["stdout"]["events"]],
            "small_part_file_staged": (staging / "big.bin.part").read_bytes() == b"another",
            "log_not_staged_yet": not os.path.lexists(staging / "log"), "resumed": resumed,
            "resumed_from_bytes_of_log": next(e for e in resumed["stdout"]["events"] if e["path"] == "log")[
                "resumed_from_bytes"], "verify": verified,
            "all_equal": all((staging / n).read_bytes() == (source / n).read_bytes() for n in
                             ("log", "log.part", "big.bin.part"))}


def data_leftover_part(ws):
    tree = make_tree(ws)
    manifest, _, _ = seal(ws, tree)
    staging = ws.root / "staging"
    cli(ws, *stage_args(manifest, tree, staging, ws.root / "work"))
    (staging / "stray.part").write_bytes(b"not in the manifest")
    verified = cli(ws, *verify_args(manifest, staging, ws.root / "work"))
    return {"mirrors": "test_leftover_staged_part_named_file_is_extra_not_hidden", "verify": verified,
            "extra": verified["stdout"]["extra"]}


ALLOWLIST = {"schema": "", "fields": [{"bucket": "lanes", "path": ["runtime", "root"]}], "immutable_buckets": ["audit"],
             "prefix_rules": [{"source": "D:/workspaces/zeus/", "target": "/srv/zeus/"}]}


def write_json(path: Path, value) -> Path:
    path.write_text(json.dumps(value))
    return path


def write_rows(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def allowlist():
    return {**ALLOWLIST, "schema": lib("mapping").ALLOWLIST_SCHEMA}


def data_plan_bindings(ws):
    rows = [{"bucket": "lanes", "id": "l1", "body": {"runtime": {"root": "D:\\workspaces\\zeus\\runtime\\l1"},
                                                      "note": "D:\\workspaces\\zeus\\keep"}},
            {"bucket": "audit", "id": "a1", "body": {"runtime": {"root": "D:/workspaces/zeus/x"}}}]
    rows_path, allow = write_rows(ws.root / "rows.jsonl", rows), write_json(ws.root / "allow.json", allowlist())
    before = rows_path.read_bytes()
    planned = cli(ws, "plan-bindings", "--rows", rows_path, "--allowlist", allow)
    out_file = ws.root / "plan.json"
    to_file = cli(ws, "plan-bindings", "--rows", rows_path, "--allowlist", allow, "--out", out_file)
    out = {"mirrors": "test_binding_plan_maps_only_allowlisted_fields_with_receipt", "plan": planned, "to_file": to_file,
           "before_sha256_is_body_sha": planned["stdout"]["receipt"]["changes"][0]["before_sha256"] == lib("mapping").body_sha(
               rows[0]["body"]), "input_untouched": rows_path.read_bytes() == before,
           "file_equals_plan": json.loads(out_file.read_text()) == planned["stdout"]}
    refused_rows = write_rows(ws.root / "refused.jsonl", [
        {"bucket": "lanes", "id": "l1", "body": {"runtime": {"root": "C:/Users/rudtn/zeus"}}},
        {"bucket": "lanes", "id": "l2", "body": {"runtime": {"root": "D:/workspaces/zeus/../x"}}}])
    refused = cli(ws, "plan-bindings", "--rows", refused_rows, "--allowlist", allow)
    out["refused"] = {"mirrors": "test_binding_plan_refuses_unmapped_and_parent_escape", "result": refused,
                      "reasons": [r["reason"] for r in refused["stdout"]["refused"]]}
    out["rows_not_json"] = cli(ws, "plan-bindings", "--rows", ws.root / "rows.jsonl.absent", "--allowlist", allow)
    return out


def data_allowlist(ws):
    mapping = lib("mapping")
    bad = dict(allowlist(), fields=[{"bucket": "audit", "path": ["x"]}])
    return {"mirrors": "test_allowlist_rejects_mapping_an_immutable_bucket", "via": "library (mapping.validate_allowlist)",
            "immutable_bucket_mapped": mapping.validate_allowlist(bad),
            "valid_allowlist": mapping.validate_allowlist(allowlist()),
            "wrong_schema": mapping.validate_allowlist({**allowlist(), "schema": "other"}),
            "constants": {"ALLOWLIST_SCHEMA": mapping.ALLOWLIST_SCHEMA}}


def pg_meta(schemas, sequences=None, version=170004, extensions=None):
    return {"schema": lib("contracts").PG_SCHEMA, "server_version_num": version,
            "extensions": extensions or {"plpgsql": "1.0", "vector": "0.8.0"},
            "schemas": {name: {"tables": ["documents"], "sequences": sequences or {"s": 5}} for name in schemas}}


def pg_inventory(ws, tag, exports, role, sequences=None, version=170004):
    """`pg-inventory`: the CLI result and the inventory it wrote; `exports` maps schema -> rows."""
    meta = write_json(ws.root / f"{tag}-meta.json", pg_meta(list(exports), sequences, version))
    argv = ["pg-inventory", "--meta", meta, "--role", role, "--out", ws.root / f"{tag}.json"]
    for name, rows in exports.items():
        argv += ["--export", f"{name}={write_rows(ws.root / f'{tag}-{name}.jsonl', rows)}"]
    result = cli(ws, *argv)
    document = ws.root / f"{tag}.json"
    return document, result, (json.loads(document.read_text()) if document.exists() else None)


def data_pg_compare(ws):
    rows = [{"bucket": "lanes", "id": "l1", "body": {"runtime": {"root": "D:/workspaces/zeus/r"}}},
            {"bucket": "tasks", "id": "t1", "body": {"b": 1, "a": 2}}]
    source, source_result, _ = pg_inventory(ws, "source", {"zeus_control": rows}, "source")
    rows_path = write_rows(ws.root / "plan-rows.jsonl", rows)
    allow = write_json(ws.root / "allow.json", allowlist())
    plan_out = ws.root / "plan.json"
    cli(ws, "plan-bindings", "--rows", rows_path, "--allowlist", allow, "--out", plan_out)
    receipt = write_json(ws.root / "receipt.json", json.loads(plan_out.read_text())["receipt"])
    mapped = [rows[0] | {"body": {"runtime": {"root": "/srv/zeus/r"}}}, {"bucket": "tasks", "id": "t1", "body": {"a": 2, "b": 1}}]
    target, target_result, _ = pg_inventory(ws, "target", {"zeus_aibox_control": mapped}, "target")
    schema_map = write_json(ws.root / "map.json", {"zeus_control": "zeus_aibox_control"})
    accepted = cli(ws, "compare-pg", "--source", source, "--target", target, "--schema-map", schema_map, "--delta", receipt)
    unreceipted = cli(ws, "compare-pg", "--source", source, "--target", target, "--schema-map", schema_map)
    return {"mirrors": "test_pg_comparison_accepts_identity_and_receipted_delta", "source_inventory": source_result,
            "target_inventory": target_result, "accepted": accepted, "unreceipted": unreceipted,
            "unreceipted_problems": [r["problem"] for r in unreceipted["stdout"]["rows"]]}


def data_pg_rejections(ws):
    source, _, _ = pg_inventory(ws, "source", {"zeus_control": [{"bucket": "t", "id": "1", "body": {}},
                                                                  {"bucket": "t", "id": "2", "body": {}}]}, "source")
    target, _, _ = pg_inventory(ws, "target", {"zeus_aibox_control": [{"bucket": "t", "id": "1", "body": {}}]}, "target",
                                sequences={"s": 4}, version=180000)
    schema_map = write_json(ws.root / "map.json", {"zeus_control": "zeus_aibox_control"})
    result = cli(ws, "compare-pg", "--source", source, "--target", target, "--schema-map", schema_map)
    public, public_result, _ = pg_inventory(ws, "public-target", {"public": []}, "target")
    return {"mirrors": "test_pg_comparison_rejects_missing_rows_public_and_version_skew", "compare": result,
            "server_major_mismatch": "server_major_mismatch" in result["stdout"]["problems"],
            "sequence_behind": "sequence_behind:zeus_control.s" in result["stdout"]["problems"],
            "missing_row": result["stdout"]["rows"],
            "public_as_target_inventory": public_result, "via": "cli (pg-inventory --role target)"}


def data_pg_public_source(ws):
    rows = [{"bucket": "audit_progress_windows", "id": "w1", "body": {"n": 1}}]
    names_source, names_target = ["public", "zeus_asset_operation_001"], ["zeus_aibox_control", "zeus_aibox_asset_operation_001"]
    source, source_result, _ = pg_inventory(ws, "source", {n: rows for n in names_source}, "source")
    target, target_result, _ = pg_inventory(ws, "target", {n: rows for n in names_target}, "target")
    schema_map = write_json(ws.root / "map.json", {"public": "zeus_aibox_control",
                                                    "zeus_asset_operation_001": "zeus_aibox_asset_operation_001"})
    return {"mirrors": "test_source_public_control_schema_is_supported", "source": source_result, "target": target_result,
            "compare": cli(ws, "compare-pg", "--source", source, "--target", target, "--schema-map", schema_map),
            "validate_pg_source_via_library": lib("contracts").validate_pg(json.loads(source.read_text()), "source")}


def data_pg_public_forbidden(ws):
    rows = [{"bucket": "t", "id": "1", "body": {}}]
    contracts = lib("contracts")
    source, _, source_doc = pg_inventory(ws, "source", {"public": rows}, "source")
    target_public, target_result, _ = pg_inventory(ws, "tpub", {"public": rows}, "source")  # `source` role: only to build it
    ok_target, _, _ = pg_inventory(ws, "ok", {"zeus_aibox_control": rows}, "target")
    public_map = write_json(ws.root / "public-map.json", {"public": "public"})
    return {"mirrors": "test_public_stays_forbidden_as_target_schema_and_map_destination",
            "validate_target_via_library": contracts.validate_pg(json.loads(target_public.read_text()), "target"),
            "compare_public_to_public": cli(ws, "compare-pg", "--source", source, "--target", target_public,
                                            "--schema-map", public_map),
            "compare_mapped_to_public": cli(ws, "compare-pg", "--source", source, "--target", ok_target,
                                            "--schema-map", public_map),
            "unknown_role_via_library": attempt(ws, lambda: contracts.validate_pg(source_doc, "either")),
            "built_with_source_role": target_result["exit"]}


def data_pg_inventory_cli(ws):
    export = write_rows(ws.root / "public.jsonl", [{"bucket": "tasks", "id": "t1", "body": {"a": 1}}])
    meta = write_json(ws.root / "meta.json", {"schema": lib("contracts").PG_SCHEMA, "server_version_num": 170011,
                                              "extensions": {"plpgsql": "1.0", "vector": "0.8.6"},
                                              "schemas": {"public": {"tables": ["documents"], "sequences": {}}}})
    base = ["pg-inventory", "--meta", meta, "--export", f"public={export}"]
    source = cli(ws, *base, "--role", "source")
    return {"mirrors": "test_cli_pg_inventory_requires_role_and_accepts_source_public",
            "source": {"exit": source["exit"], "tasks_count": source["stdout"]["schemas"]["public"]["buckets"]["tasks"]["count"],
                       "result": source},
            "target": cli(ws, *base, "--role", "target"), "no_role": cli(ws, *base)["exit"],
            "bad_role": cli(ws, *base, "--role", "either")["exit"],
            "export_not_name_path": cli(ws, "pg-inventory", "--meta", meta, "--export", str(export), "--role", "source"),
            "export_missing_file": cli(ws, "pg-inventory", "--meta", meta, "--export", f"public={ws.root / 'nope.jsonl'}",
                                       "--role", "source"),
            "meta_missing": cli(ws, "pg-inventory", "--meta", ws.root / "nometa.json", "--export", f"public={export}",
                                "--role", "source")}


def data_pg_duplicates(ws):
    export = ws.root / "x.jsonl"
    export.write_text('{"bucket":"t","id":"1","body":{}}\n{"bucket":"t","id":"1","body":{}}\n')
    meta = write_json(ws.root / "meta.json", pg_meta(["public"]))
    blank = ws.root / "blank.jsonl"
    blank.write_text('\n{"bucket":"t","id":"1","body":{}}\n\n')
    return {"mirrors": "test_pg_export_rejects_duplicate_rows",
            "cli": cli(ws, "pg-inventory", "--meta", meta, "--export", f"public={export}", "--role", "source"),
            "blank_lines_skipped": cli(ws, "pg-inventory", "--meta", meta, "--export", f"public={blank}", "--role", "source",
                                       "--out", ws.root / "blank-out.json")}


def redis_inventory(pending=None, expire=None, captured=1000):
    pending = [{"id": "5-0", "consumer": "c1", "deliveries": 1}] if pending is None else pending
    return {"schema": lib("contracts").REDIS_SCHEMA, "captured_at_ms": captured, "namespace_prefixes": ["zeus"],
            "keys": {"zeus:agent:claude": {"type": "stream", "expire_at_ms": None},
                     "zeus:dedup:m1": {"type": "string", "expire_at_ms": expire, "dump_sha256": "c" * 64}},
            "streams": {"zeus:agent:claude": {
                "length": 3, "last_generated_id": "7-0", "entries_sha256": "d" * 64,
                "groups": {"workers": {"last_delivered_id": "6-0", "consumers": {"c1": len(pending)} if pending else {},
                                       "pending": pending}}}}}


def compare_redis(ws, tag, source, target, *extra):
    return cli(ws, "compare-redis", "--source", write_json(ws.root / f"{tag}-s.json", source),
               "--target", write_json(ws.root / f"{tag}-t.json", target), *extra)


def data_redis_preserved(ws):
    source = redis_inventory(expire=5000)
    return {"mirrors": "test_redis_comparison_preserves_groups_pel_and_absolute_expiry",
            "validate_via_library": lib("contracts").validate_redis(source),
            "compare": compare_redis(ws, "a", source, redis_inventory(expire=5000, captured=2000)),
            "tolerance_ms": compare_redis(ws, "b", source, redis_inventory(expire=5500, captured=2000), "--tolerance-ms", "600"),
            "no_tolerance": compare_redis(ws, "c", source, redis_inventory(expire=5500, captured=2000))}


def data_redis_rejections(ws):
    source = redis_inventory(expire=5000)
    result = compare_redis(ws, "a", source, redis_inventory(pending=[], expire=9000))
    return {"mirrors": "test_redis_comparison_rejects_dropped_pel_and_extended_ttl", "compare": result,
            "problems": sorted({d["problem"] for d in result["stdout"]["diffs"]})}


def data_redis_expiry(ws):
    source = redis_inventory(expire=1500)
    target = redis_inventory(expire=1500, captured=2000)
    del target["keys"]["zeus:dedup:m1"]
    early = redis_inventory(expire=1500, captured=1200)
    del early["keys"]["zeus:dedup:m1"]
    return {"mirrors": "test_redis_key_expired_during_downtime_is_classified_not_missing",
            "downtime": compare_redis(ws, "a", source, target), "too_early": compare_redis(ws, "b", source, early)}


def data_redis_validation(ws):
    document = redis_inventory(pending=[{"id": "9-0", "consumer": "c1", "deliveries": 1}])
    document["keys"]["other:app"] = {"type": "string", "expire_at_ms": None, "dump_sha256": "c" * 64}
    problems = lib("contracts").validate_redis(document)
    return {"mirrors": "test_redis_validation_rejects_out_of_allowlist_keys_and_impossible_pel",
            "via": "library (contracts.validate_redis)", "problems": problems,
            "outside_allowlist": "key_outside_allowlist:other:app" in problems,
            "impossible_pel": "pel_id:zeus:agent:claude/workers/9-0" in problems,
            "valid_document": lib("contracts").validate_redis(redis_inventory(expire=5000)),
            "schema_wrong": lib("contracts").validate_redis({**redis_inventory(), "schema": "other"})}


def data_stream_digest(ws):
    contracts = lib("contracts")
    first = contracts.stream_entries_sha256([("1-0", {"body": "a", "x": "1"})])
    return {"mirrors": "test_stream_entries_digest_depends_on_ids_and_fields_not_field_order",
            "via": "library (contracts.stream_entries_sha256)", "digest": first,
            "field_order_free": first == contracts.stream_entries_sha256([("1-0", {"x": "1", "body": "a"})]),
            "id_matters": first != contracts.stream_entries_sha256([("1-1", {"body": "a", "x": "1"})]),
            "empty": contracts.stream_entries_sha256([])}


def data_pel_owners(ws):
    document = write_json(ws.root / "redis.json", redis_inventory())
    none = write_json(ws.root / "owners-none.json", {})
    owned = write_json(ws.root / "owners.json", {"zeus:agent:claude/workers/5-0": {"bucket": "operations", "id": "op-1"}})
    return {"mirrors": "test_pending_entries_must_map_to_pg_owner",
            "unowned": cli(ws, "pel-owners", "--inventory", document, "--owners", none),
            "owned": cli(ws, "pel-owners", "--inventory", document, "--owners", owned)}


R0_OK = {"target_authoritative_writes": 0, "target_external_effects": 0, "target_fenced": True, "target_writer_count": 0,
         "source_sealed_digest": "sha256:" + "a" * 64, "source_current_digest": "sha256:" + "a" * 64,
         "source_runtime_pointer_unchanged": True, "source_single_owner_confirmed": True}
R1_OK = {"target_reachable": True, "target_admission_stopped": True, "target_fenced": True,
         "reverse_file_manifest_match": True, "reverse_pg_match": True, "reverse_redis_match": True,
         "reverse_mapping_roundtrip_verified": True, "windows_runtime_binding_receipt": True,
         "single_owner_resume_planned": True, "target_writer_count": 0, "unknown_external_effects": 0,
         "windows_incompatible_names": 0, "case_collisions": 0, "windows_restore_db_identity": "win-restore-2",
         "original_snapshot_identity": "win-snap-1", "external_effects": [{"id": "pr-201", "disposition": "reconciled_no_rerun"}]}
C_ITEM = {"absolute_path": "D:/workspaces/zeus/runtime", "owner": "zeus", "kind": "runtime", "prior_sha256": "sha256:" + "a" * 64,
          "dirty_ignored_checked": True, "server_copy_verified": True}
C_OK = {"completion_state": "autonomous_qualified", "a_accepted": True, "b_accepted": True, "backup_restore_verified": True,
        "server_references_resolved_without_windows": True, "windows_observer_disabled": True,
        "unresolved_windows_references": 0, "deletion_manifest": [C_ITEM]}


def gate(ws, name, label, evidence):
    return cli(ws, "gate", name, "--evidence", write_json(ws.root / f"{label}.json", evidence))


def data_gate_r0(ws):
    return {"mirrors": "test_r0_requires_untouched_source_and_silent_target", "ok": gate(ws, "r0", "a", R0_OK),
            "target_wrote": gate(ws, "r0", "b", R0_OK | {"target_authoritative_writes": 3}),
            "source_changed": gate(ws, "r0", "c", R0_OK | {"source_current_digest": "sha256:" + "b" * 64}),
            "fence_missing": gate(ws, "r0", "d", {k: v for k, v in R0_OK.items() if k != "target_fenced"}),
            "digest_malformed": gate(ws, "r0", "e", R0_OK | {"source_sealed_digest": "abc"}),
            "bool_for_count": gate(ws, "r0", "f", R0_OK | {"target_writer_count": False}),
            "empty_evidence": gate(ws, "r0", "g", {})}


def data_gate_r1(ws):
    return {"mirrors": "test_r1_refuses_old_snapshot_reuse_and_unreconciled_effects", "ok": gate(ws, "r1", "a", R1_OK),
            "snapshot_reuse": gate(ws, "r1", "b", R1_OK | {"windows_restore_db_identity": "win-snap-1"}),
            "effect_rerun": gate(ws, "r1", "c", R1_OK | {"external_effects": [{"id": "merge", "disposition": "rerun"}]}),
            "unreachable": gate(ws, "r1", "d", R1_OK | {"target_reachable": False}),
            "empty_evidence": gate(ws, "r1", "e", {})}


def data_gate_c(ws):
    protected = [C_ITEM | {"absolute_path": "C:/Users/rudtn/.claude"}, C_ITEM | {"absolute_path": "flexday-pg", "kind": "shared"},
                 C_ITEM | {"kind": "claude_harness_original"}, C_ITEM | {"dirty_ignored_checked": None}]
    blocked = gate(ws, "c", "c", C_OK | {"deletion_manifest": protected})
    return {"mirrors": "test_retirement_gate_c_requires_a_b_backup_and_exact_items", "ok": gate(ws, "c", "a", C_OK),
            "limited": gate(ws, "c", "b", C_OK | {"completion_state": "migrated_limited", "b_accepted": False}),
            "blocked": blocked,
            "blocked_problems": [item["problems"] for item in blocked["stdout"]["blocked_items"]],
            "empty_evidence": gate(ws, "c", "d", {}), "not_a_list": gate(ws, "c", "e", C_OK | {"deletion_manifest": "x"})}


def data_roundtrip(ws):
    tree = make_tree(ws)
    out = ws.root / "manifest.json"
    inventory = cli(ws, "inventory", "--migration-id", "mig-1", "--root", f"art={tree}", "--host", "fixture", "--out", out)
    staged = cli(ws, "stage", "--manifest", out, "--root-id", "art", "--source", tree, "--staging", ws.root / "s",
                 "--work", ws.root / "w")
    verified = cli(ws, "verify-staged", "--manifest", out, "--root-id", "art", "--staging", ws.root / "s", "--work", ws.root / "w")
    evidence = write_json(ws.root / "r0.json", R0_OK | {"target_fenced": False})
    return {"mirrors": "test_cli_inventory_stage_verify_roundtrip", "inventory": inventory, "stage": staged,
            "verify": verified, "match": verified["stdout"]["match"],
            "gate_r0_ineligible": cli(ws, "gate", "r0", "--evidence", evidence),
            "gate_unknown_name": cli(ws, "gate", "bogus", "--evidence", evidence)}


def data_usage(ws):
    return {"no_command": cli(ws)["exit"], "unknown_command": cli(ws, "frobnicate")["exit"],
            "help_is_exit_0": cli(ws, "--help")["exit"], "stage_missing_required": cli(ws, "stage")["exit"],
            "compare_redis_bad_tolerance": cli(ws, "compare-redis", "--source", "a", "--target", "b",
                                               "--tolerance-ms", "x")["exit"],
            "gate_without_evidence": cli(ws, "gate", "r0")["exit"],
            "verify_staged_without_work_is_allowed": cli(ws, "verify-staged", "--manifest", ws.root / "none.json",
                                                         "--root-id", "a", "--staging", ws.root / "s")}


def data_parser(ws):
    return {"parser": parser_view(sys.modules["aibox_data.cli"].parser()),
            "package_modules": sorted(name for name in sys.modules if name.startswith("aibox_data"))}


def data_pairs(ws):
    """`--root`/`--export` NAME=PATH parsing (`_pairs`): its SystemExit becomes exit 2 with a JSON error."""
    return {"via": "cli", "unnamed": cli(ws, "inventory", "--migration-id", "m", "--root", "=x", "--host", "h"),
            "no_equals": cli(ws, "inventory", "--migration-id", "m", "--root", "plain", "--host", "h"),
            "empty_path": cli(ws, "inventory", "--migration-id", "m", "--root", "a=", "--host", "h")}


# ============================== registry ==========================================================================

GROUPS = {
    "service": [
        ("constants", svc_constants), ("render", svc_render), ("render_defaults", svc_render_defaults),
        ("render_text", svc_render_text), ("render_live_directories", svc_render_live_dirs),
        ("render_refusals", svc_render_refusals), ("render_account_database", svc_account_database),
        ("static_policy_of_rendered_units", svc_static_policy), ("verify_missing_units", svc_verify_missing),
        ("unit_semantics", svc_unit_semantics), ("parse_unit_edges", svc_parse_unit_edges),
        ("secrets_only_from_environment_files", svc_secrets), ("weakened_units", svc_weakened_units),
        ("loopback_literals", svc_loopback), ("install_targets", svc_install_targets),
        ("systemd_analyze_doubles", svc_systemd_analyze),
        ("fleet_launch", svc_fleet_launch), ("launch_drops_pythonhome", svc_pythonhome),
        ("monitor_roles", svc_monitor_roles), ("fence_refuses_every_role", svc_fence),
        ("activation_receipt", svc_activation_receipt), ("check_activation", svc_check_activation),
        ("pinned_release", svc_pinned_release), ("launch_environment", svc_launch_environment),
        ("fleet_owner", svc_fleet_owner), ("managed_roles_and_bootstrap", svc_managed_roles),
        ("launch_main_and_exec_hook", svc_launch_main),
        ("journal_main", svc_journal), ("journal_lines", svc_journal_lines), ("journal_refusals", svc_journal_refusals),
        ("inspect_healthy", svc_inspect_healthy), ("inspect_findings", svc_inspect_findings),
        ("inspect_fenced_and_secret_mode", svc_inspect_fenced_secret), ("inspect_references", svc_inspect_references),
        ("inspect_network", svc_inspect_network), ("inspect_parts", svc_inspect_parts),
        ("network_comparison", svc_network_comparison), ("templates", svc_templates), ("parser", svc_parser),
        ("main_commands", svc_main_commands),
    ],
    "data_cli": [
        ("parser", data_parser), ("usage_errors", data_usage), ("name_path_pairs", data_pairs),
        ("inventory_links", data_inventory_links), ("inventory_clean", data_inventory_clean),
        ("inventory_refusals", data_inventory_refusals), ("manifest_digest", data_manifest_digest),
        ("windows_names_and_case_collisions", data_windows_names), ("artifact_store", data_artifact_store),
        ("artifact_store_real_writer", data_artifact_store_real), ("path_references", data_path_references),
        ("stage_roundtrip", data_stage_roundtrip), ("stage_resume", data_stage_resume),
        ("stage_refusals", data_stage_refusals), ("stage_source_changes", data_stage_source_changes),
        ("stage_external_symlink", data_stage_external_symlink), ("stage_symlinked_ancestors", data_stage_symlinked_ancestors),
        ("stage_symlinked_roots", data_stage_symlinked_roots), ("work_dir_rules", data_work_dir_rules),
        ("unsafe_manifest_paths", data_unsafe_manifest_path), ("unreadable_subtree", data_unreadable_subtree),
        ("empty_root", data_empty_root), ("part_named_files", data_part_named_files), ("leftover_part", data_leftover_part),
        ("plan_bindings", data_plan_bindings), ("allowlist", data_allowlist), ("pg_compare", data_pg_compare),
        ("pg_rejections", data_pg_rejections), ("pg_public_source", data_pg_public_source),
        ("pg_public_forbidden", data_pg_public_forbidden), ("pg_inventory_cli", data_pg_inventory_cli),
        ("pg_duplicate_rows", data_pg_duplicates), ("redis_preserved", data_redis_preserved),
        ("redis_rejections", data_redis_rejections), ("redis_expiry", data_redis_expiry),
        ("redis_validation", data_redis_validation), ("stream_digest", data_stream_digest), ("pel_owners", data_pel_owners),
        ("gate_r0", data_gate_r0), ("gate_r1", data_gate_r1), ("gate_c", data_gate_c), ("roundtrip", data_roundtrip),
    ],
}


def mirrored(value, found: set):
    """Every `mirrors` / `mirrors_unreachable` name in a result tree."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("mirrors", "mirrors_unreachable") and isinstance(item, str):
                found.add(item)
            else:
                mirrored(item, found)
    elif isinstance(value, list):
        for item in value:
            mirrored(item, found)


def run(api) -> dict:
    global A
    A = api
    out = {}
    with pinned_clock():
        for group, cases in GROUPS.items():
            out[group] = {}
            for name, fn in cases:
                ws = Ws()
                try:
                    try:
                        with keep_cwd():
                            result = fn(ws)
                    except Exception as exc:  # an unexpected failure of the characterized operation is itself compared
                        result = {"case_error": type(exc).__name__, "message": ws.n(str(exc))[:300]}
                finally:
                    ws.close()
                out[group][name] = result
    found: set = set()
    mirrored(out, found)
    tests = SERVICE_TESTS + DATA_TESTS
    out["coverage"] = {"service_tests": len(SERVICE_TESTS), "data_tests": len(DATA_TESTS),
                       "mirrored": sorted(found & set(tests)), "unreachable": UNREACHABLE,
                       "uncovered": sorted(set(tests) - found), "unknown_mirrors": sorted(found - set(tests))}
    return out
