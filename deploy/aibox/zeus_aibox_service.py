#!/usr/bin/python3
"""Linux service templates and lifecycle inspection for the Zeus aibox host.

Standard library only, so the system interpreter can run it before any release venv exists.
It owns no Zeus policy: admission, pause, fence semantics, relocation and recovery stay in the
harness (`zeus fleet ...`, HostDelivery). This file only

* `render`   - fills the unit templates with EXPLICIT values into a staging directory; it refuses
               to write into a live systemd directory, so rendering never installs anything;
* `verify`   - static policy checks of rendered units, plus `systemd-analyze verify` on request;
* `launch`   - the unit's ExecStart: refuses fail-closed (exit 78) when the host is fenced, the
               release pointer is not a pinned revision or the Fleet has no activation receipt for
               this host and revision, then execs the release interpreter. It never resumes
               admission. Exactly ONE Fleet owner runs: once the owner records the managed Fleet as
               the host's Fleet owner (`fleet-owner.json`), the bootstrap `fleet` role refuses and the
               `managed-fleet` role starts only while the bootstrap unit is observed inactive
               (aibox SPEC s14 G3);
* `journal`  - the start/exit lifecycle journal the Fleet relocation proof reads (runner_state);
* `inspect`  - read-only: unit state, control-group processes, Fleet runners outside the unit,
               labelled Docker containers (which are NOT in the unit cgroup), fence/activation
               files, secret-file mode, addresses and LAN-IP/Windows-path references;
* `network`  - compares current addresses with a recorded baseline (the IP-change maintenance);
* `host-id`  - the host identity an activation receipt must name (a digest, never the raw id).

Exit codes: 0 ok, 1 findings or refused, 2 usage error, 78 launch refused (EX_CONFIG; the units
set RestartPreventExitStatus=78 so a refusal is never restarted into a loop).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
import pwd
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 78

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "systemd"
UNITS = ("zeus-aibox-fleet.service", "zeus-aibox-monitor-collect.service",
         "zeus-aibox-monitor-web.service", "zeus-aibox-inspect.service",
         "zeus-aibox-inspect.timer", "zeus-aibox.target",
         "zeus-aibox-managed-fleet.service", "zeus-aibox-owner-actions.service")
SERVICES = UNITS[:3]
FLEET_UNIT = "zeus-aibox-fleet.service"
# The owner-fixed unit of the managed Fleet target (domain.host_delivery.MANAGED_SYSTEMD_UNIT) and the
# server-owned pending-action coordinator (INV-OWNER-ACTIONS-001), aibox SPEC s14.
MANAGED_FLEET_UNIT = "zeus-aibox-managed-fleet.service"
OWNER_ACTIONS_UNIT = "zeus-aibox-owner-actions.service"
OWNER_SERVICES = (MANAGED_FLEET_UNIT, OWNER_ACTIONS_UNIT)
ROLES = {"fleet": FLEET_UNIT, "monitor-collect": "zeus-aibox-monitor-collect.service",
         "monitor-web": "zeus-aibox-monitor-web.service", "managed-fleet": MANAGED_FLEET_UNIT,
         "owner-actions": OWNER_ACTIONS_UNIT}
# The owner's record that the managed Fleet target (not the bootstrap unit) is this host's Fleet owner.
FLEET_OWNER_FILE = "fleet-owner.json"
FLEET_OWNER_SCHEMA = "urn:zeus:aibox-fleet-owner:1"
MANAGED_STATE = ("runtime", "managed-fleet")
POLKIT = HERE / "polkit" / "50-zeus-aibox-managed-fleet.rules.in"
POLICY_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

# The isolated worker's run label (adapters/isolated_worker.py LABEL); read, never changed here.
RUN_LABEL = "zeus.isolated.run"
FENCE_FILE = "host-fence.json"
ACTIVATION_FILE = "host-activation.json"
ACTIVATION_SCHEMA = "urn:zeus:aibox-host-activation:1"
# Coordinator states in which this host may run the Fleet owner (SPEC s6 state machine).
ACTIVE_STATES = ("restored_paused", "limited_active", "qualified")
REVISION = re.compile(r"[0-9a-f]{40}")
PLACEHOLDER = re.compile(r"@[A-Z_]+@")
# Directories systemd loads units from; rendering into them would be an installation.
LIVE_UNIT_DIRS = ("/etc/systemd", "/run/systemd", "/lib/systemd", "/usr/lib/systemd",
                  "/usr/local/lib/systemd", "/etc/polkit-1", "/usr/share/polkit-1")
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
WINDOWS_PATH = re.compile(r"(?i)(/mnt/[a-z]/|\b[a-z]:[\\/]|\\\\)")
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
SECRET_NAME = re.compile(r"(?i)(TOKEN|PASSWORD|SECRET|API_KEY|PRIVATE|DATABASE_URL|REDIS_URL)")
SHOW_PROPERTIES = ("LoadState", "ActiveState", "SubState", "UnitFileState", "MainPID",
                   "ControlGroup", "NRestarts", "Result", "ExecMainStatus", "InvocationID",
                   "User", "WorkingDirectory", "KillMode", "TimeoutStopUSec")


class Refused(Exception):
    def __init__(self, reason: str, **facts):
        super().__init__(reason)
        self.reason, self.facts = reason, facts


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def emit(document: dict, stream=sys.stdout) -> None:
    stream.write(json.dumps(document, sort_keys=True, indent=2) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----- render -----------------------------------------------------------------------------------
def render_values(args) -> dict:
    """The explicit substitution map. Every value is checked before anything is written."""
    root = args.root.rstrip("/") or "/"
    values = {
        "ZEUS_ROOT": root, "SERVICE_USER": args.user, "SERVICE_GROUP": args.group or args.user,
        "SERVICE_HOME": args.home, "SERVICE_PATH": args.path, "PYTHON": args.python,
        "TOOL": args.tool or f"{root}/deploy/aibox/zeus_aibox_service.py",
        "CONFIG_ENV": args.config_env or f"{root}/config/zeus-aibox.env",
        "SECRET_ENV": args.secret_env or f"{root}/secrets/zeus-aibox.env",
        "WEB_PORT": str(args.web_port),
    }
    for key in ("ZEUS_ROOT", "SERVICE_HOME", "PYTHON", "TOOL", "CONFIG_ENV", "SECRET_ENV"):
        if not values[key].startswith("/"):
            raise Refused("path_not_absolute", field=key)
    for key, value in values.items():
        # Whitespace would split an ExecStart word; '%' is a systemd specifier; '$' an expansion.
        if not value or re.search(r"[\s%$\\\"'`;]", value):
            raise Refused("value_not_literal", field=key)
    for entry in values["SERVICE_PATH"].split(":"):
        if not entry.startswith("/") or WINDOWS_PATH.search(entry + "/"):
            raise Refused("path_entry_not_absolute_linux", field="SERVICE_PATH")
    if not 1024 <= args.web_port <= 65535:
        raise Refused("web_port_out_of_range", field="WEB_PORT")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", values["SERVICE_USER"]):
        raise Refused("service_user_invalid", field="SERVICE_USER")
    if args.uid is None or args.uid == 0:
        raise Refused("explicit_non_root_uid_required", field="uid")
    if not args.skip_account_check:
        try:
            account = pwd.getpwnam(values["SERVICE_USER"])
        except KeyError:
            raise Refused("service_user_unknown", field="SERVICE_USER") from None
        if account.pw_uid != args.uid:
            raise Refused("service_uid_mismatch", field="uid", expected=args.uid,
                          observed=account.pw_uid)
        if account.pw_dir != values["SERVICE_HOME"]:
            raise Refused("service_home_mismatch", field="SERVICE_HOME")
    return values


def render_text(template: str, values: dict) -> str:
    text = template
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    left = sorted(set(PLACEHOLDER.findall(text)))
    if left:
        raise Refused("placeholder_unresolved", placeholders=left)
    return text


def render(args) -> dict:
    output = Path(args.output).resolve()
    if any(str(output) == d or str(output).startswith(d + "/") for d in LIVE_UNIT_DIRS):
        raise Refused("output_is_live_systemd_directory", output=str(output))
    values = render_values(args)
    # Every unit is rendered in memory first, so a refusal leaves no partial output behind.
    sources = {unit: TEMPLATES / (unit + ".in") for unit in UNITS}
    sources[POLKIT.name[:-3]] = POLKIT
    rendered = {name: render_text(path.read_text("utf-8"), values) for name, path in sources.items()}
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for unit, text in rendered.items():
        (output / unit).write_text(text, "utf-8")
        files[unit] = {"sha256": hashlib.sha256(text.encode()).hexdigest(),
                       "template_sha256": sha256_file(sources[unit])}
    manifest = {"schema": "urn:zeus:aibox-service-render:1", "rendered_at": utcnow(),
                "uid": args.uid, "values": values, "files": files,
                "tool_sha256": sha256_file(Path(__file__).resolve()), "installed": False}
    (output / "render-manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2)
                                                 + "\n", "utf-8")
    return manifest


# ----- verify -----------------------------------------------------------------------------------
def parse_unit(text: str) -> dict:
    """Section -> list of (key, value); repeated keys are kept in order."""
    sections, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], [])
        elif current is not None and "=" in line:
            key, _, value = line.partition("=")
            current.append((key.strip(), value.strip()))
    return sections


def values_of(sections: dict, section: str, key: str) -> list:
    return [value for name, value in sections.get(section, []) if name == key]


def unit_findings(name: str, text: str) -> list:
    """The policy every rendered service must satisfy (SPEC-retirement-update s9)."""
    findings = []

    def need(condition, code):
        if not condition:
            findings.append({"unit": name, "code": code})

    left = PLACEHOLDER.findall(text)
    need(not left, "placeholder_unresolved")
    need(not WINDOWS_PATH.search(text), "windows_path_reference")
    for address in IPV4.findall(text):
        need(_loopback(address), "lan_ip_literal")
    sections = parse_unit(text)
    if not name.endswith(".service"):
        return findings
    service = dict(sections.get("Service", []))
    need(service.get("User") not in (None, "", "root", "0"), "explicit_non_root_user_missing")
    need(service.get("Group") not in (None, ""), "explicit_group_missing")
    workdir = service.get("WorkingDirectory", "")
    need(workdir.startswith("/"), "working_directory_not_absolute")
    for key in ("ExecStartPre", "ExecStart", "ExecStopPost"):
        for command in values_of(sections, "Service", key):
            need(command.lstrip("-@:+!").startswith("/"), "exec_not_absolute")
    environment = values_of(sections, "Service", "Environment")
    paths = [value.split("=", 1)[1] for value in environment if value.startswith("PATH=")]
    need(len(paths) == 1 and all(p.startswith("/") for p in paths[0].split(":")) if paths
         else False, "explicit_path_missing")
    for value in environment:
        need(not SECRET_NAME.search(value.split("=", 1)[0]), "secret_in_environment_line")
    # Paused bootstrap: no directive may resume admission; the owner resumes through the harness.
    directives = [value for entries in sections.values() for _, value in entries]
    need(not any(re.search(r"\bresume\b", value) for value in directives), "resume_reference")
    if service.get("Type") == "oneshot":
        return findings
    need(service.get("KillMode") == "control-group", "kill_mode_not_control_group")
    need(service.get("SendSIGKILL", "yes") == "yes", "final_sigkill_disabled")
    stop = service.get("TimeoutStopSec", "")
    need(stop.isdigit() and 0 < int(stop) <= 900, "stop_timeout_unbounded")
    need(service.get("Restart") in ("on-failure", "no"), "restart_policy_unbounded")
    unit = dict(sections.get("Unit", []))
    need(unit.get("StartLimitBurst", "").isdigit() and unit.get("StartLimitIntervalSec", "")
         .isdigit(), "start_limit_missing")
    need("78" in service.get("RestartPreventExitStatus", "").split(),
         "refusal_restart_not_prevented")
    need(any(v.startswith("ZEUS_AIBOX_ROOT=/") for v in environment), "root_not_explicit")
    return findings


def _loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return True  # not an address (a version string): not a LAN reference


def verify(args, run=subprocess.run) -> dict:
    directory = Path(args.directory)
    findings, checked = [], []
    for unit in UNITS:
        path = directory / unit
        if not path.is_file():
            findings.append({"unit": unit, "code": "unit_missing"})
            continue
        checked.append(unit)
        findings += unit_findings(unit, path.read_text("utf-8"))
    analyze = {"status": "not_run"}
    if args.systemd_analyze and checked:
        # Offline: it reads the given files; nothing is installed, enabled or started.
        files = [str(directory / unit) for unit in checked]
        try:
            result = run(["systemd-analyze", "verify", "--man=no", *files],
                         capture_output=True, text=True, timeout=60)
            lines = [line for line in (result.stderr + result.stdout).splitlines() if line]
            # systemd-analyze also loads the host's installed units; their warnings are kept apart
            # and do not decide the verdict about these files.
            ours = [line for line in lines if str(directory) in line
                    or any(unit in line for unit in UNITS)]
            analyze = {"status": "passed" if result.returncode == 0 and not ours else "failed",
                       "exit_code": result.returncode, "diagnostics": ours[:40],
                       "unrelated_host_diagnostics": len(lines) - len(ours)}
        except (OSError, subprocess.TimeoutExpired) as exc:
            analyze = {"status": "unavailable", "error_type": type(exc).__name__}
    if analyze["status"] == "failed":
        findings.append({"unit": None, "code": "systemd_analyze_failed"})
    return {"checked": checked, "findings": findings, "systemd_analyze": analyze}


# ----- launch -----------------------------------------------------------------------------------
def host_id(machine_id_path: Path = Path("/etc/machine-id")) -> str:
    raw = machine_id_path.read_text("ascii").strip()
    return "machine-id-sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def pinned_release(root: Path) -> Path:
    """`current` resolved ONCE to an immutable revision directory, or a refusal."""
    pointer = root / "releases" / "current"
    try:
        release = pointer.resolve(strict=True)
    except OSError:
        raise Refused("release_pointer_missing") from None
    if release.parent != (root / "releases").resolve() or not REVISION.fullmatch(release.name):
        raise Refused("release_not_pinned_revision")
    if not os.access(release / ".venv" / "bin" / "python", os.X_OK):
        raise Refused("release_interpreter_missing")
    if not (release / "src" / "codex_harness" / "__init__.py").is_file():
        raise Refused("release_package_missing")
    return release


def check_activation(control: Path, release: Path, identity: str) -> dict:
    path = control / ACTIVATION_FILE
    try:
        receipt = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        raise Refused("activation_receipt_missing") from None
    except (OSError, ValueError):
        raise Refused("activation_receipt_unreadable") from None
    if not isinstance(receipt, dict) or receipt.get("schema") != ACTIVATION_SCHEMA:
        raise Refused("activation_receipt_schema")
    if receipt.get("host_id") != identity:
        raise Refused("activation_receipt_other_host")
    if receipt.get("state") not in ACTIVE_STATES:
        raise Refused("activation_receipt_state", state=receipt.get("state"))
    if receipt.get("release_revision") != release.name:
        raise Refused("activation_receipt_revision_mismatch")
    if not isinstance(receipt.get("migration_id"), str) or not receipt["migration_id"]:
        raise Refused("activation_receipt_migration_missing")
    return receipt


def fleet_owner(control: Path) -> str | None:
    """`managed-fleet` when the owner recorded the managed target as this host's Fleet owner; an
    unreadable or malformed record is a refusal, never a silent bootstrap owner."""
    path = control / FLEET_OWNER_FILE
    if not os.path.lexists(path):
        return None
    try:
        record = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        raise Refused("fleet_owner_unreadable") from None
    if not (isinstance(record, dict) and record.get("schema") == FLEET_OWNER_SCHEMA
            and record.get("owner") == "managed-fleet" and record.get("unit") == MANAGED_FLEET_UNIT):
        raise Refused("fleet_owner_invalid")
    return "managed-fleet"


def bootstrap_inactive(run) -> None:
    """The bootstrap Fleet unit must be observed stopped; an unknown state refuses."""
    try:
        result = run(["systemctl", "show", FLEET_UNIT, "-p", "ActiveState"], capture_output=True, text=True,
                     timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused("bootstrap_fleet_state_unknown") from None
    state = dict(line.split("=", 1) for line in (result.stdout or "").splitlines() if "=" in line).get("ActiveState")
    if result.returncode or state not in ("inactive", "failed", "active", "activating", "deactivating", "reloading"):
        raise Refused("bootstrap_fleet_state_unknown")
    if state not in ("inactive", "failed"):
        raise Refused("bootstrap_fleet_active")


def launch_plan(role: str, environ: dict, *, machine_id_path: Path = Path("/etc/machine-id"),
                run=subprocess.run) -> dict:
    """Everything the launch decides, without executing; the unit's ExecStart execs the result."""
    if role not in ROLES:
        raise Refused("role_unknown")
    root_value = environ.get("ZEUS_AIBOX_ROOT", "")
    if not root_value.startswith("/"):
        raise Refused("root_not_explicit")
    path_value = environ.get("PATH", "")
    if not path_value or any(not entry.startswith("/") or WINDOWS_PATH.search(entry + "/")
                             for entry in path_value.split(":")):
        raise Refused("path_not_explicit_linux")
    root = Path(root_value)
    control = root / "runtime" / "control"
    # A fence exists => this host must not own anything, whatever the file says (fail closed).
    if os.path.lexists(control / FENCE_FILE):
        raise Refused("host_fenced")
    release = pinned_release(root)
    activation = None
    if role in ("fleet", "managed-fleet", "owner-actions"):
        activation = check_activation(control, release, host_id(machine_id_path))
    python = str(release / ".venv" / "bin" / "python")
    owner = fleet_owner(control) if role in ("fleet", "managed-fleet") else None
    if role == "fleet" and owner == "managed-fleet":
        # The bootstrap owner is retired: only the managed target's unit runs the Fleet now.
        raise Refused("fleet_owner_managed")
    if role == "fleet":
        argv = [python, "-m", "zeus", "fleet", "run"]
    elif role == "managed-fleet":
        if owner != "managed-fleet":
            raise Refused("fleet_owner_not_managed")
        bootstrap_inactive(run)
        # The fixed state directory of the registered managed target; `supervise` re-validates the
        # persisted launch request, target, descriptor, sealed runtime and Fleet debt before starting.
        argv = [python, "-m", "codex_harness.adapters.managed_runtime", "supervise", "--state-dir",
                str(root.joinpath(*MANAGED_STATE))]
    elif role == "owner-actions":
        policy = environ.get("ZEUS_OWNER_ACTIONS_POLICY", "")
        if not POLICY_TOKEN.fullmatch(policy):
            raise Refused("owner_actions_policy_unset")
        argv = [python, "-m", "zeus", "owner-actions", "run", "--policy", policy]
    elif role == "monitor-collect":
        argv = [python, "-m", "codex_harness.monitor", "collect", "--repository", str(release)]
    else:
        port = environ.get("ZEUS_AIBOX_WEB_PORT", "8787")
        if not port.isdigit():
            raise Refused("web_port_invalid")
        argv = [python, "-m", "codex_harness.monitor", "web", "--repository", str(release),
                "--port", port]
    env = dict(environ)
    env.update(ZEUS_REPOSITORY=str(release), HARNESS_REPOSITORY=str(release),
               VIRTUAL_ENV=str(release / ".venv"), ZEUS_AIBOX_RELEASE=str(release),
               ZEUS_AIBOX_ROLE=role, PATH=str(release / ".venv" / "bin") + ":" + path_value)
    env.pop("PYTHONHOME", None)
    return {"argv": argv, "env": env, "cwd": str(control), "release": str(release),
            "revision": release.name,
            "migration_id": activation.get("migration_id") if activation else None}


def launch(args) -> int:
    try:
        plan = launch_plan(args.role, dict(os.environ))
    except Refused as refusal:
        emit({"event": "launch_refused", "role": args.role, "reason": refusal.reason,
              **{k: v for k, v in refusal.facts.items() if k == "state"}}, sys.stderr)
        return EXIT_REFUSED
    emit({"event": "launch", "role": args.role, "revision": plan["revision"],
          "migration_id": plan["migration_id"]}, sys.stderr)
    if args.dry_run:
        return EXIT_OK
    os.chdir(plan["cwd"])
    os.execve(plan["argv"][0], plan["argv"], plan["env"])
    return EXIT_USAGE  # pragma: no cover - execve does not return


# ----- journal ----------------------------------------------------------------------------------
def journal_entry(event: str, role: str, environ: dict) -> dict:
    run_id = environ.get("INVOCATION_ID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        # Outside systemd there is no invocation to account for; refuse rather than invent one.
        raise Refused("invocation_id_missing")
    entry = {"event": event, "run_id": run_id, "role": role, "at": utcnow(),
             "unit": ROLES.get(role)}
    if event == "exit":
        entry.update(service_result=environ.get("SERVICE_RESULT"),
                     exit_code=environ.get("EXIT_CODE"), exit_status=environ.get("EXIT_STATUS"))
    return entry


def append_journal(path: Path, entry: dict) -> None:
    """One JSON line, appended under an exclusive lock and fsynced before returning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.write(descriptor, (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def journal(args) -> int:
    try:
        append_journal(Path(args.journal), journal_entry(args.event, args.role, dict(os.environ)))
    except Refused as refusal:
        emit({"event": "journal_refused", "reason": refusal.reason}, sys.stderr)
        return EXIT_FINDINGS
    return EXIT_OK


# ----- inspect ----------------------------------------------------------------------------------
def _run(run, argv, timeout=20):
    try:
        result = run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, type(exc).__name__
    if result.returncode:
        return None, f"exit_{result.returncode}"
    return result.stdout, None


def unit_state(unit: str, run) -> dict:
    out, error = _run(run, ["systemctl", "show", unit, "--property=" + ",".join(SHOW_PROPERTIES)])
    if out is None:
        return {"status": "unavailable", "error": error}
    facts = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return {"status": "ok", **facts}


def cgroup_of(pid: int, proc: Path) -> str | None:
    try:
        for line in (proc / str(pid) / "cgroup").read_text().splitlines():
            if line.startswith("0::"):
                return line[3:]
    except OSError:
        return None
    return None


def cgroup_processes(control_group: str, sys_cgroup: Path, proc: Path) -> dict:
    if not control_group:
        return {"status": "empty", "processes": []}
    try:
        text = (sys_cgroup / control_group.lstrip("/") / "cgroup.procs").read_text()
    except OSError as exc:
        return {"status": "unavailable", "error": type(exc).__name__, "processes": []}
    processes = []
    for pid in (int(value) for value in text.split()):
        try:
            comm = (proc / str(pid) / "comm").read_text().strip()
        except OSError:
            comm = None
        processes.append({"pid": pid, "comm": comm})
    return {"status": "ok", "processes": processes}


def fleet_runners(proc: Path) -> list:
    """Every process whose argv is a Fleet runner (`... zeus fleet run`), wherever it lives."""
    found = []
    pids = sorted(int(e.name) for e in proc.iterdir() if e.name.isdigit()) if proc.is_dir() else []
    for entry in (proc / str(pid) for pid in pids):
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        words = [word.decode("utf-8", "replace") for word in argv if word]
        for index in range(len(words) - 1):
            if words[index] == "fleet" and words[index + 1] == "run" and any(
                    w in ("zeus", "harness") or w.endswith(("/zeus", "/harness"))
                    for w in words[:index]):
                found.append({"pid": int(entry.name), "cgroup": cgroup_of(int(entry.name), proc),
                              "once": "--once" in words})
                break
    return found


def labelled_containers(run, proc: Path) -> dict:
    out, error = _run(run, ["docker", "ps", "--all", "--no-trunc", "--filter",
                            f"label={RUN_LABEL}", "--format", "{{json .}}"])
    if out is None:
        # Unknown is not zero: an unreadable daemon never reads as "no residue".
        return {"status": "unavailable", "error": error, "containers": []}
    containers = []
    for line in out.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        item = {"id": row.get("ID"), "name": row.get("Names"), "state": row.get("State"),
                "run_id": _label(row.get("Labels", ""), RUN_LABEL), "cgroup": None}
        if item["state"] == "running" and item["id"]:
            pid_text, _ = _run(run, ["docker", "inspect", "--format", "{{.State.Pid}}", item["id"]])
            if pid_text and pid_text.strip().isdigit():
                item["cgroup"] = cgroup_of(int(pid_text.strip()), proc)
        containers.append(item)
    return {"status": "ok", "containers": containers}


def _label(labels: str, name: str):
    for pair in labels.split(","):
        key, _, value = pair.partition("=")
        if key == name:
            return value
    return None


def file_facts(path: Path) -> dict:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"present": False}
    except OSError as exc:
        return {"present": None, "error": type(exc).__name__}
    return {"present": True, "mode": oct(stat.st_mode & 0o777), "uid": stat.st_uid}


def addresses(run) -> dict:
    out, error = _run(run, ["ip", "-j", "-4", "addr", "show"])
    route, route_error = _run(run, ["ip", "-j", "-4", "route", "show", "default"])
    result = {"status": "ok" if out is not None else "unavailable", "error": error,
              "ipv4": [], "default_routes": []}
    try:
        for link in json.loads(out or "[]"):
            for info in link.get("addr_info", []):
                if info.get("family") == "inet" and not _loopback(info.get("local", "")):
                    result["ipv4"].append({"ifname": link.get("ifname"),
                                           "address": f"{info.get('local')}/{info.get('prefixlen')}"})
        result["default_routes"] = [{"dev": r.get("dev"), "gateway": r.get("gateway")}
                                    for r in json.loads(route or "[]")]
    except (ValueError, AttributeError):
        result["status"] = "unavailable"
    if route is None:
        result["route_error"] = route_error
    return result


def reference_scan(paths: list) -> list:
    """LAN IPv4 literals and Windows paths in the host's Zeus unit/config files (names only)."""
    findings = []
    for path in paths:
        try:
            text = Path(path).read_text("utf-8")
        except OSError:
            continue
        if WINDOWS_PATH.search(text):
            findings.append({"code": "windows_path_reference", "file": str(path)})
        if any(not _loopback(address) for address in IPV4.findall(text)):
            findings.append({"code": "lan_ip_literal", "file": str(path)})
    return findings


def inspect(root: Path, *, run=subprocess.run, proc: Path = Path("/proc"),
            sys_cgroup: Path = Path("/sys/fs/cgroup"),
            unit_dir: Path = Path("/etc/systemd/system")) -> dict:
    """A read-only picture of the owner, its cgroup and what lies outside it. Nothing is changed."""
    units = {unit: unit_state(unit, run) for unit in SERVICES}
    for unit, state in units.items():
        if state.get("status") == "ok":
            state["cgroup_processes"] = cgroup_processes(state.get("ControlGroup", ""),
                                                         sys_cgroup, proc)
    fleet = units[FLEET_UNIT]
    fleet_cgroup = fleet.get("ControlGroup") or None
    fleet_active = fleet.get("ActiveState") in ("active", "activating", "deactivating", "reloading")
    runners = fleet_runners(proc)
    docker = labelled_containers(run, proc)
    control = root / "runtime" / "control"
    findings = []
    outside = [r for r in runners if not fleet_cgroup or r["cgroup"] != fleet_cgroup]
    inside = [r for r in runners if fleet_cgroup and r["cgroup"] == fleet_cgroup]
    if outside:
        findings.append({"code": "fleet_runner_outside_unit", "pids": [r["pid"] for r in outside]})
    if len(inside) > 1:
        findings.append({"code": "multiple_fleet_runners_in_unit", "pids": [r["pid"] for r in inside]})
    if fleet.get("status") != "ok":
        findings.append({"code": "fleet_unit_state_unavailable"})
    if docker["status"] != "ok":
        findings.append({"code": "docker_state_unavailable"})
    running = [c for c in docker["containers"] if c["state"] == "running"]
    if running and not fleet_active:
        # SPEC s9: dockerd owns these, not the unit cgroup. Reconcile by run label; never auto-stop.
        findings.append({"code": "labelled_containers_without_active_owner",
                         "run_ids": sorted({c["run_id"] or "" for c in running})})
    if fleet_active and os.path.lexists(control / FENCE_FILE):
        findings.append({"code": "fleet_active_while_fenced"})
    secret = file_facts(root / "secrets" / "zeus-aibox.env")
    if secret.get("present") and secret.get("mode") != "0o600":
        findings.append({"code": "secret_file_mode_not_0600"})
    scanned = [unit_dir / unit for unit in UNITS] + [root / "config" / "zeus-aibox.env"]
    findings += reference_scan(scanned)
    return {"schema": "urn:zeus:aibox-lifecycle-inspection:1", "observed_at": utcnow(),
            "read_only": True, "root": str(root), "units": units,
            "fleet_runners": runners, "docker": docker,
            "docker_cgroup_note": "containers are children of dockerd; unit cgroup stop does not end them",
            "fence": file_facts(control / FENCE_FILE),
            "activation": file_facts(control / ACTIVATION_FILE),
            "secret_env": secret, "network": addresses(run), "findings": findings,
            "windows_observer": "not_observable_from_aibox"}


# ----- network ----------------------------------------------------------------------------------
def compare_network(baseline: dict, current: dict) -> dict:
    before = {a["address"] for a in baseline.get("ipv4", [])}
    after = {a["address"] for a in current.get("ipv4", [])}
    return {"changed": before != after or baseline.get("default_routes") != current.get(
        "default_routes"), "removed": sorted(before - after), "added": sorted(after - before),
        "baseline_routes": baseline.get("default_routes"),
        "current_routes": current.get("default_routes")}


# ----- CLI --------------------------------------------------------------------------------------
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zeus_aibox_service.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("render", help="Render unit templates into a staging directory")
    r.add_argument("--output", required=True)
    r.add_argument("--root", default="/srv/zeus")
    r.add_argument("--user", required=True)
    r.add_argument("--group")
    r.add_argument("--uid", type=int, required=True)
    r.add_argument("--home", required=True)
    r.add_argument("--path", default=DEFAULT_PATH)
    r.add_argument("--python", default="/usr/bin/python3")
    r.add_argument("--tool")
    r.add_argument("--config-env", dest="config_env")
    r.add_argument("--secret-env", dest="secret_env")
    r.add_argument("--web-port", dest="web_port", type=int, default=8787)
    r.add_argument("--skip-account-check", action="store_true",
                   help="Fixture rendering only: do not compare the user with the account database")
    v = sub.add_parser("verify", help="Static checks of rendered units; optional systemd-analyze")
    v.add_argument("directory")
    v.add_argument("--systemd-analyze", dest="systemd_analyze", action="store_true")
    la = sub.add_parser("launch", help="ExecStart: fail-closed checks, then exec the release")
    la.add_argument("--role", required=True, choices=sorted(ROLES))
    la.add_argument("--dry-run", action="store_true")
    j = sub.add_parser("journal", help="Append a start/exit lifecycle journal line")
    j.add_argument("event", choices=["start", "exit"])
    j.add_argument("--role", required=True, choices=sorted(ROLES))
    j.add_argument("--journal", required=True)
    i = sub.add_parser("inspect", help="Read-only lifecycle inspection")
    i.add_argument("--root", default="/srv/zeus")
    i.add_argument("--output")
    n = sub.add_parser("network", help="Compare current addresses with a baseline")
    n.add_argument("--baseline")
    n.add_argument("--record")
    sub.add_parser("host-id", help="The host identity an activation receipt must name")
    return p


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK
    try:
        if args.command == "render":
            emit(render(args))
            return EXIT_OK
        if args.command == "verify":
            result = verify(args)
            emit(result)
            return EXIT_FINDINGS if result["findings"] else EXIT_OK
        if args.command == "launch":
            return launch(args)
        if args.command == "journal":
            return journal(args)
        if args.command == "inspect":
            result = inspect(Path(args.root))
            if args.output:
                target = Path(args.output)
                temporary = target.with_name(target.name + ".tmp")
                temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", "utf-8")
                os.replace(temporary, target)
            emit(result)
            return EXIT_FINDINGS if result["findings"] else EXIT_OK
        if args.command == "network":
            current = addresses(subprocess.run)
            result = {"current": current}
            if args.baseline:
                result["comparison"] = compare_network(
                    json.loads(Path(args.baseline).read_text("utf-8")), current)
            if args.record:
                Path(args.record).write_text(json.dumps(current, sort_keys=True, indent=2) + "\n",
                                             "utf-8")
            emit(result)
            return EXIT_OK
        if args.command == "host-id":
            emit({"host_id": host_id()})
            return EXIT_OK
    except Refused as refusal:
        emit({"refused": refusal.reason, **refusal.facts})
        return EXIT_FINDINGS
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
