"""Read-only receipt producer of a managed `limited_active` transition (INV-HOST-MIGRATION-001).

@invariant INV-HOST-MIGRATION-001

`python -m codex_harness.adapters.host_migration observe-limited-active ...` runs `observe` once. It
prints `{observation, result_sha256, projections, evidence, transition_draft, diagnostic}` and the
operator archives it in a new evidence directory. There is no apply mode. The policy lives in
`domain.host_migration_evidence`; this module only reads:

* The coordinator record, the owner-action canary row, the Fleet registry (lane routing only) and the
  delivery rows are read through `LaneSnapshotStore`. Each read is one `REPEATABLE READ READ ONLY`
  transaction on a connection whose only search path is the stated, verified schema. The writers'
  advisory lock is never taken, no `PostgresStore` is constructed, and nothing is migrated or created.
* Host files, all read-only: `host-activation.json`, `host-fence.json` (presence only),
  `releases/current`, the managed state directory's descriptor, startup receipt and plan-scoped owner
  canary request and receipt, and the host configuration file (hashed only).
* `systemctl show` of the one owner-fixed managed unit, and `journalctl -o json` of exactly that
  unit's current invocation on the current boot. These are the only commands run.
* `/proc` through the accepted `HostFacts` (pid, start ticks, boot id, cgroup) plus the pid's cmdline
  and parent. The supervisor's own journal line for this invocation is read from the managed state
  directory, and the sealed runtime through `Materializer.verify`.

Nothing is written, locked, registered, ticked, started, stopped or submitted. No artifact is stored.
No model, provider or network endpoint other than the stated store is contacted. Connection strings
are read in this process from the NAMED environment variables the accepted loader sets. They never
reach argv or the result. A read that fails is `activation_observation_unavailable` naming only its
step, and no exception text, path or value is kept.

The capture is bounded, not atomic across the filesystem and the stores. It reads every source once,
then rereads every identity tuple (effective head, activation file and `current`, descriptor and
startup and canary bytes, delivery rows, canary record, unit invocation, boot and both processes). A
difference is `activation_observation_changed`. The observation is then obsolete and must be
recollected, never rewritten.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    canary_receipt_file,
    canary_request_file,
    owner_qualified_canary,
    systemd_control_dir,
)
from codex_harness.adapters.host_migration import ACTIVATION_FILE, FENCE_FILE, current_revision
from codex_harness.adapters.managed_runtime import SUPERVISOR_JOURNAL, Materializer
from codex_harness.application.host_delivery import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    BUCKET_TARGETS,
)
from codex_harness.application.host_migration import BUCKET as MIGRATIONS
from codex_harness.domain import host_migration_evidence as policy
from codex_harness.domain.host_delivery import TOKEN as DELIVERY_TOKEN
from codex_harness.domain.host_delivery import DeliveryRefused
from codex_harness.domain.host_migration import HEX64, IDENT, TOKEN, MigrationRefused
from codex_harness.domain.managed_runtime import EnvironmentUnqualified
from codex_harness.domain.managed_runtime import manifest_digest as runtime_manifest_digest
from codex_harness.domain.model import digest

# The owner-action rows (INV-OWNER-ACTIONS-001); the constant of `application.owner_actions`.
OWNER_ACTIONS = "owner_actions"
MANAGED_STATE = ("runtime", "managed-fleet")
CONFIG_FILE = ("config", "zeus-aibox.env")
MAX_FILE_BYTES = 1024 * 1024
MAX_JOURNAL_ENTRIES = 100_000
COMMAND_TIMEOUT = 30
HEX32 = re.compile(r"^[0-9a-f]{32}$")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


class Unreadable(Exception):
    """A host fact that exists but cannot be observed; `_read` turns it into the step's unknown."""


def _read(step: str, function, *args):
    """One read. A failure is an unknown and never a pass. It becomes `activation_observation_unavailable`
    naming the step, with no exception text: a driver message can quote a DSN."""
    try:
        return function(*args)
    except MigrationRefused:
        raise
    except Exception:  # noqa: BLE001 - every other failure to read is the same unknown
        pass
    raise MigrationRefused(policy.UNAVAILABLE, step)


# ----- the host ---------------------------------------------------------------------------------------
class HostReader:
    """Every host read of one observation. The only commands are `systemctl show` and `journalctl`,
    and nothing is opened for writing. `facts` is the accepted `/proc` reader of
    INV-HOST-DELIVERY-VERIFY-001, with its rule that an unobservable fact is unknown, never absent."""

    def __init__(self, *, runner=None, facts=None, clk_tck: int | None = None, timeout: int = COMMAND_TIMEOUT):
        if facts is None:
            from codex_harness.adapters.release_verifier import HostFacts

            facts = HostFacts()
        self.runner, self.facts, self.timeout = runner, facts, timeout
        self.clk_tck = clk_tck or os.sysconf("SC_CLK_TCK")

    def _run(self, argv: list):
        return (self.runner or run_process)(argv, timeout=self.timeout)

    @staticmethod
    def file(path) -> bytes | None:
        """The bytes of one regular file, or None when nothing exists there. A link, another kind of
        entry or an oversized file is unknown."""
        path = Path(path)
        if not os.path.lexists(path):
            return None
        if path.is_symlink() or not path.is_file():
            raise Unreadable("file_kind")
        with open(path, "rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise Unreadable("file_size")
        return data

    @staticmethod
    def exists(path) -> bool:
        return os.path.lexists(path)

    @staticmethod
    def current(releases) -> str | None:
        return current_revision(releases)

    @staticmethod
    def release_present(releases, revision: str) -> bool:
        release = Path(releases) / revision
        return release.is_dir() and not release.is_symlink()

    def unit(self, unit: str) -> dict:
        argv = ["systemctl", "show", unit]
        for name in policy.UNIT_PROPERTIES:
            argv += ["-p", name]
        result = self._run(argv)
        if result.returncode:
            raise Unreadable("unit")
        return policy.unit_facts(result.stdout)

    def journal(self, unit: str, invocation_id: str, boot_id: str) -> list:
        """The journal entries of exactly this unit invocation on this boot, in journal order."""
        if not (HEX32.fullmatch(invocation_id) and HEX32.fullmatch(boot_id)):
            raise Unreadable("journal")
        result = self._run(["journalctl", "--no-pager", "-o", "json", "_SYSTEMD_UNIT=" + unit,
                            "_SYSTEMD_INVOCATION_ID=" + invocation_id, "_BOOT_ID=" + boot_id])
        if result.returncode:
            raise Unreadable("journal")
        lines = [line for line in str(result.stdout or "").splitlines() if line.strip()]
        if len(lines) > MAX_JOURNAL_ENTRIES:
            raise Unreadable("journal_size")
        return [json.loads(line) for line in lines]

    def boot_id(self) -> str:
        """The current boot id in the journal's spelling (32 hex, no dashes)."""
        value = (self.facts.boot_id() or "").replace("-", "")
        if not HEX32.fullmatch(value):
            raise Unreadable("boot")
        return value

    def process(self, pid) -> dict:
        """One process identity: start ticks, parent, cgroup and argv. The identity is read again after
        the reads, so a pid that changed hands meanwhile is `replaced`, never merged."""
        if type(pid) is not int or pid <= 0:
            return {"pid": pid, "state": "absent"}
        state, ticks = self.facts.process(pid)
        if state == "absent":
            return {"pid": pid, "state": "absent"}
        if state != "present":
            raise Unreadable("process")
        root = Path(self.facts.proc) / str(pid)
        argv = [word.decode("utf-8", "replace") for word in (root / "cmdline").read_bytes().split(b"\0") if word]
        stat = (root / "stat").read_text("utf-8", errors="replace")
        fields = stat[stat.rindex(")") + 1:].split()
        if len(fields) < 2 or not fields[1].isdigit():
            raise Unreadable("process")
        cgroup = self.facts.cgroup(pid)
        if self.facts.process(pid) != (state, ticks):
            return {"pid": pid, "state": "replaced"}
        return {"pid": pid, "state": "present", "start_ticks": ticks, "start_usec": ticks * 1_000_000 // self.clk_tck,
                "tick_usec": 1_000_000 // self.clk_tck, "ppid": int(fields[1]), "cgroup": cgroup, "argv": argv}

    @staticmethod
    def sealed(target: dict, descriptor: dict) -> dict:
        """The sealed runtime the descriptor names, verified read-only against its own seal."""
        manifest = Materializer(target).verify(descriptor)
        return {"revision": manifest["revision"], "tree": manifest["tree"], "files": manifest["files"],
                "environment_lock": manifest["environment_lock"],
                "manifest_sha256": runtime_manifest_digest(manifest)}


@dataclass
class Ports:
    """Read-only stores and the host. `delivery(control)` is the store holding the delivery rows: the
    control store itself, or the one registered lane, resolved read-only."""

    coordinator: object
    control: object
    delivery: Callable
    host: HostReader
    clock: Callable = _utcnow


@dataclass
class Capture:
    clock: Callable
    checks: dict = field(default_factory=lambda: {name: False for name in policy.CHECKS})
    sources: dict = field(default_factory=dict)
    projections: dict = field(default_factory=dict)
    identity: dict = field(default_factory=dict)
    manifest_sha256: str | None = None
    activation: dict | None = None
    lineage: dict | None = None
    host: str | None = None
    config_sha256: str | None = None

    def record(self, name: str, projection) -> None:
        self.projections[name] = projection
        self.sources[name] = policy.source(projection, self.clock())


# ----- request --------------------------------------------------------------------------------------------
def validate_request(request) -> dict:
    """The operator's inputs, refused before any store or host read. The deployment path binding is
    `ZEUS_AIBOX_ROOT`, checked exactly as the systemd target checks it."""
    if not isinstance(request, dict):
        raise MigrationRefused("request_invalid", "request")
    for key, pattern in (("migration_id", TOKEN), ("expected_id", HEX64), ("target_id", DELIVERY_TOKEN),
                         ("plan_id", DELIVERY_TOKEN), ("actor", TOKEN)):
        if not (type(request.get(key)) is str and pattern.fullmatch(request[key])):
            raise MigrationRefused("request_invalid", key)
    root = request.get("root")
    if not (type(root) is str and systemd_control_dir({"ZEUS_AIBOX_ROOT": root})["control_dir"]):
        raise MigrationRefused("request_invalid", "root")
    config = request.get("config_file") or str(Path(root).joinpath(*CONFIG_FILE))
    if not (type(config) is str and Path(config).is_absolute()):
        raise MigrationRefused("request_invalid", "config_file")
    return {"migration_id": request["migration_id"], "expected_id": request["expected_id"],
            "target_id": request["target_id"], "plan_id": request["plan_id"], "actor": request["actor"],
            "root": Path(root), "config_file": Path(config)}


# ----- reads shared by the capture and the recheck ---------------------------------------------------
def _migration_row(ports: Ports, migration_id: str):
    with ports.coordinator.transaction() as tx:
        return tx.get(MIGRATIONS, migration_id)


def _delivery_rows(ports: Ports, q: dict) -> tuple:
    store = ports.delivery(ports.control)
    with store.transaction() as tx:
        return (tx.get(BUCKET_TARGETS, q["target_id"]), tx.get(BUCKET_PLANS, q["plan_id"]),
                tx.get(BUCKET_INTENTS, q["plan_id"]), tx.get(BUCKET_DESCRIPTORS, q["target_id"]),
                tx.scan(BUCKET_INTENTS))


def _action_row(ports: Ports, action_id: str):
    with ports.control.transaction() as tx:
        return tx.get(OWNER_ACTIONS, action_id)


def _activation_file(host: HostReader, q: dict, revision: str) -> dict:
    control, releases = q["root"] / "runtime" / "control", q["root"] / "releases"
    raw = host.file(control / ACTIVATION_FILE)
    if raw is None:
        raise MigrationRefused(policy.UNAVAILABLE, "activation_file")
    return {"document": json.loads(raw), "raw_sha256": _sha256(raw), "fence": host.exists(control / FENCE_FILE),
            "current": host.current(releases), "release_present": host.release_present(releases, revision)}


def _canary_files(host: HostReader, q: dict) -> dict:
    state = q["root"].joinpath(*MANAGED_STATE)
    receipt = host.file(state / canary_receipt_file(q["plan_id"]))
    request = host.file(state / canary_request_file(q["plan_id"]))
    return {"receipt": None if receipt is None else json.loads(receipt), "receipt_sha256": _sha256(receipt),
            "request": None if request is None else json.loads(request), "request_sha256": _sha256(request)}


def _supervisor_launches(host: HostReader, state_dir: Path, invocation_id: str) -> list:
    raw = host.file(state_dir / SUPERVISOR_JOURNAL)
    if raw is None:
        raise Unreadable("supervisor_journal")
    return policy.supervisor_launches(raw.decode("utf-8"), invocation_id)


def _migration_identity(view: dict) -> tuple:
    return (view["state"], view["manifest_sha256"], (view["effective"] or {}).get("id"), view["history_sha256"])


def _file_identity(view: dict) -> tuple:
    return (view["raw_sha256"], view["fence"], view["current"], view["release_present"])


def _unit_identity(unit: dict) -> tuple:
    return tuple(unit[key] for key in sorted(unit))


def _process_identity(process: dict) -> tuple:
    return (process.get("pid"), process.get("state"), process.get("start_ticks"))


def _supervisor_argv(root: Path, revision: str) -> list:
    """What the launcher execs for the `managed-fleet` role (deploy/aibox/zeus_aibox_service.py
    `launch_plan`): the pinned release's interpreter, then `supervise` of the fixed state directory."""
    release = (root / "releases" / revision).resolve()
    return [str(release / ".venv" / "bin" / "python"), "-m", policy.MANAGED_MODULE, "supervise", "--state-dir",
            str(root.joinpath(*MANAGED_STATE))]


def _entry_argv(target: dict, state_dir: Path) -> list:
    """What the managed `launch` starts inside the unit: the target's REGISTERED interpreter (not the
    launcher revision), the entry of the fixed state directory, the real Fleet workload."""
    return [target["python"], "-m", policy.MANAGED_MODULE, "entry", "--state-dir", str(state_dir), "--workload",
            policy.ENTRY_WORKLOAD]


def _sealed(host: HostReader, consumed: dict) -> dict:
    """The sealed runtime/module provenance: a refused seal is a refused consumption, an unreadable one
    an unknown."""
    try:
        return host.sealed(consumed["target"], consumed["descriptor"])
    except DeliveryRefused as exc:
        failure = (policy.CONSUMPTION, policy.diagnostic(exc.reason_code))
    except EnvironmentUnqualified:
        failure = (policy.CONSUMPTION, "environment_unqualified")
    except Exception:  # noqa: BLE001 - an unreadable seal is unknown, never verified
        failure = (policy.UNAVAILABLE, "sealed_runtime")
    raise MigrationRefused(*failure)


# ----- one capture -------------------------------------------------------------------------------------
def _capture(q: dict, ports: Ports, run: Capture) -> dict:
    """Every source once, in order. Each group sets its check only after it holds. The first refusal
    stops the capture with its fixed code; the sources already read stay recorded."""
    host, state_dir = ports.host, q["root"].joinpath(*MANAGED_STATE)
    # 1. The coordinator: restored_paused, exact manifest, exactly the expected effective head.
    row = _read("migration", _migration_row, ports, q["migration_id"])
    if not isinstance(row, dict):
        raise MigrationRefused(policy.UNAVAILABLE, "migration")
    view = _read("migration", policy.migration_view, row)
    run.record("migration", view)
    run.identity["migration"] = _migration_identity(view)
    activation = policy.require_head(view, q["migration_id"], q["expected_id"])
    run.manifest_sha256, run.activation, run.host = view["manifest_sha256"], activation, view["target_host_id"]
    # 2. The launcher's receipt equals the derived document as an object; no fence; `current` is it.
    files = _read("activation_file", _activation_file, host, q, activation["release_revision"])
    run.record("activation_file", files)
    run.identity["activation_file"] = _file_identity(files)
    policy.require_activation_file(files, view)
    run.checks["activation_equal"] = True
    policy.require_current(files, view)
    run.checks["current_equal"] = True
    config = _read("config", host.file, q["config_file"])
    if config is None:
        raise MigrationRefused(policy.UNAVAILABLE, "config")
    run.config_sha256 = run.identity["config"] = _sha256(config)
    # 3. The unit's main process is the exec'd supervisor, and its own pre-exec launch event names
    #    this activation.
    unit = _read("unit", host.unit, policy.MANAGED_UNIT)
    boot = _read("boot", host.boot_id)
    supervisor = _read("supervisor", host.process, unit["main_pid"])
    launches = _read("supervisor_journal", _supervisor_launches, host, state_dir, unit["invocation_id"])
    run.record("supervisor", {**supervisor, "role": "supervisor", "boot_id": boot,
                              "invocation_id": unit["invocation_id"], "unit": unit, "launches": launches})
    run.identity.update(unit=_unit_identity(unit), boot=boot, supervisor=_process_identity(supervisor),
                        supervisor_journal=digest(launches))
    policy.require_supervisor(unit, supervisor, argv=_supervisor_argv(q["root"], activation["release_revision"]))
    entries = _read("journal", host.journal, policy.MANAGED_UNIT, unit["invocation_id"], boot)
    launch = policy.launch_record(entries, unit=policy.MANAGED_UNIT, invocation_id=unit["invocation_id"],
                                  boot_id=boot, main_pid=unit["main_pid"])
    run.record("launch", launch)
    policy.require_launch(launch, unit, supervisor, migration_id=q["migration_id"],
                          revision=activation["release_revision"])
    run.checks["launch_bound"] = True
    # 4. The consumed managed payload: registered target, this plan's active delivery, the descriptor
    #    on the host, the EXISTING consumption verdict, and the sealed runtime it names.
    delivery = policy.delivery_view(*_read("delivery", _delivery_rows, ports, q), target_id=q["target_id"],
                                    plan_id=q["plan_id"])
    run.record("delivery", delivery)
    run.identity["delivery"] = digest(delivery)
    raw_descriptor = _read("descriptor", host.file, state_dir / DESCRIPTOR_FILE)
    raw_startup = _read("startup", host.file, state_dir / RECEIPT_FILE)
    if raw_descriptor is None or raw_startup is None:
        raise MigrationRefused(policy.UNAVAILABLE, "descriptor" if raw_descriptor is None else "startup")
    descriptor = _read("descriptor", json.loads, raw_descriptor)
    startup = _read("startup", json.loads, raw_startup)
    run.identity.update(descriptor=_sha256(raw_descriptor), startup=_sha256(raw_startup))
    run.record("startup", {"document": startup, "raw_sha256": _sha256(raw_startup)})
    described = {"document": descriptor, "raw_sha256": _sha256(raw_descriptor), "runtime": None}
    try:
        consumed = policy.require_consumption(delivery, descriptor, startup, activation, target_id=q["target_id"],
                                              plan_id=q["plan_id"], state_dir=str(state_dir))
        described["runtime"] = _sealed(host, consumed)
    finally:
        run.record("descriptor", described)
    run.lineage = consumed["lineage"]
    run.checks["consumption"] = True
    # 5. The live entry is the process that wrote the consumed receipt, in this unit, under this supervisor.
    entry = _read("entry", host.process, startup["pid"])
    run.record("entry", {**entry, "role": "entry", "boot_id": boot, "invocation_id": unit["invocation_id"]})
    run.identity["entry"] = _process_identity(entry)
    policy.require_supervisor_launch(launches, descriptor_sha256=consumed["descriptor_sha256"])
    policy.require_entry(entry, supervisor, unit, launch, argv=_entry_argv(consumed["target"], state_dir),
                         started_at=startup["started_at"])
    run.checks["process_bound"] = True
    # 6. A passed owner canary of this plan, descriptor and instance, agreeing with its accepted record.
    canary = _read("canary_receipt", _canary_files, host, q)
    run.record("canary_receipt", canary)
    run.identity["canary_receipt"] = (canary["receipt_sha256"], canary["request_sha256"])
    incumbent = _read("canary_receipt", lambda: owner_qualified_canary(
        consumed["target"], consumed["descriptor"], {"instance_id": consumed["instance_id"]}, plan=consumed["plan"]))
    receipt = canary["receipt"]
    action_id = (receipt.get("evidence") or {}).get("action_id") if isinstance(receipt, dict) \
        and isinstance(receipt.get("evidence"), dict) else None
    record = None
    if type(action_id) is str and HEX64.fullmatch(action_id):
        record = _read("canary_record", _action_row, ports, action_id)
        if isinstance(record, dict):
            run.record("canary_record", policy.record_view(record))
    run.identity["canary_record"] = digest(policy.record_view(record))
    policy.require_canary(consumed, incumbent, receipt, canary["request"], record, intent=delivery["intent"],
                          started_at=startup["started_at"])
    run.checks["canary_bound"] = True
    return {"supervisor_pid": unit["main_pid"], "entry_pid": startup["pid"], "action_id": action_id,
            "revision": activation["release_revision"]}


def _recheck(q: dict, ports: Ports, context: dict) -> dict:
    """The end-of-capture reread of every identity tuple, through the same reads as the capture. The
    unit is read first."""
    host, state_dir = ports.host, q["root"].joinpath(*MANAGED_STATE)
    unit = host.unit(policy.MANAGED_UNIT)
    fresh = {"unit": _unit_identity(unit), "boot": host.boot_id(),
             "supervisor_journal": digest(_supervisor_launches(host, state_dir, unit["invocation_id"])),
             "supervisor": _process_identity(host.process(context["supervisor_pid"])),
             "entry": _process_identity(host.process(context["entry_pid"])),
             "migration": _migration_identity(policy.migration_view(_migration_row(ports, q["migration_id"]))),
             "activation_file": _file_identity(_activation_file(host, q, context["revision"]))}
    fresh["config"] = _sha256(host.file(q["config_file"]))
    fresh["delivery"] = digest(policy.delivery_view(*_delivery_rows(ports, q), target_id=q["target_id"],
                                                    plan_id=q["plan_id"]))
    fresh["descriptor"] = _sha256(host.file(state_dir / DESCRIPTOR_FILE))
    fresh["startup"] = _sha256(host.file(state_dir / RECEIPT_FILE))
    canary = _canary_files(host, q)
    fresh["canary_receipt"] = (canary["receipt_sha256"], canary["request_sha256"])
    fresh["canary_record"] = digest(policy.record_view(_action_row(ports, context["action_id"])))
    return fresh


def observe(request, ports: Ports) -> dict:
    """One bounded read-only capture. Returns the observation, its digest, the archived source
    projections, the three receipts and, only on complete success, the transition draft."""
    q = validate_request(request)
    run = Capture(ports.clock)
    observed_from = ports.clock()
    reason = detail = None
    try:
        context = _capture(q, ports, run)
        fresh = _read("recheck", _recheck, q, ports, context)
        # The first changed tuple in capture order names the change (a restart is `unit`, not its effects).
        changed = [key for key in run.identity if fresh.get(key) != run.identity[key]]
        if changed:
            raise MigrationRefused(policy.CHANGED, changed[0])
        run.checks["stable_capture"] = True
    except MigrationRefused as exc:
        reason, detail = exc.reason_code, policy.diagnostic(exc.field)
        if reason not in policy.REFUSALS:
            reason, detail = policy.UNAVAILABLE, policy.diagnostic(exc.reason_code)
    observation = policy.validate_observation({
        "schema": policy.OBSERVATION_SCHEMA, "migration_id": q["migration_id"],
        "manifest_sha256": run.manifest_sha256, "observed_from": observed_from, "observed_to": ports.clock(),
        "activation": run.activation, "lineage": run.lineage, "checks": dict(run.checks),
        "sources": {name: run.sources.get(name) for name in policy.SOURCES}, "ok": reason is None,
        "reason_code": reason})
    result_sha256 = policy.observation_digest(observation)
    receipts = policy.observation_receipts(observation, result_sha256, q["expected_id"])
    draft = policy.transition_draft(observation, receipts, host=run.host, actor=q["actor"],
                                    config_sha256=run.config_sha256) if observation["ok"] else None
    return {"observation": observation, "result_sha256": result_sha256,
            "projections": {name: run.projections.get(name) for name in policy.SOURCES},
            "evidence": receipts, "transition_draft": draft,
            "diagnostic": None if reason is None else {"reason_code": reason, "detail": detail}}


# ----- CLI --------------------------------------------------------------------------------------------
def _named_env(name, argument: str) -> str:
    """The value of a NAMED environment variable. A refusal names the argument, never what was given:
    a credential typed where a name belongs is never echoed."""
    if not (type(name) is str and ENV_NAME.fullmatch(name)):
        raise MigrationRefused("environment_name_invalid", argument)
    value = os.environ.get(name)
    if not value:
        raise MigrationRefused("environment_missing", argument)
    return value


def _schema(value, field_name: str) -> str:
    if not (type(value) is str and IDENT.fullmatch(value)) or value == "public":
        raise MigrationRefused("schema_invalid", field_name)
    return value


def cli_ports(args) -> Ports:
    """Read-only snapshot stores over the stated schemas and the real host. Nothing connects here."""
    from codex_harness.adapters.fleet_runtime import lane_dsn
    from codex_harness.adapters.monitoring import LaneSnapshotStore

    schema, control_schema = _schema(args.schema, "schema"), _schema(args.control_schema, "control_schema")
    migration_dsn = _named_env(args.dsn_env, "dsn_env")
    control_dsn = _named_env(args.control_dsn_env, "control_dsn_env")
    lane_id = args.lane

    def delivery(control):
        if lane_id is None:
            return control
        from codex_harness.application.fleet import Fleet

        lanes = [lane for lane in Fleet(control).registered()["config"].get("lanes") or []
                 if lane.get("id") == lane_id]
        if len(lanes) != 1 or not (type(lanes[0].get("schema")) is str and IDENT.fullmatch(lanes[0]["schema"])):
            raise MigrationRefused(policy.UNAVAILABLE, "lane")
        return LaneSnapshotStore(lane_dsn(control_dsn, lanes[0]["schema"]), lanes[0]["schema"])

    return Ports(coordinator=LaneSnapshotStore(lane_dsn(migration_dsn, schema), schema),
                 control=LaneSnapshotStore(lane_dsn(control_dsn, control_schema), control_schema),
                 delivery=delivery, host=HostReader())


def observe_command(args, *, ports: Ports | None = None) -> tuple[dict, bool]:
    """`observe-limited-active`: the inputs are refused before anything is read; the exit follows `ok`."""
    request = {"migration_id": args.migration_id, "expected_id": args.expected_id, "target_id": args.target_id,
               "plan_id": args.plan_id, "actor": args.actor, "root": args.root, "config_file": args.config_file}
    validate_request(request)
    result = observe(request, ports or cli_ports(args))
    return result, result["observation"]["ok"]


__all__ = ["HostReader", "Ports", "cli_ports", "observe", "observe_command", "validate_request"]
