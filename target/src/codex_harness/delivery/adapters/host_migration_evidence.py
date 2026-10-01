"""The managed `limited_active` evidence producer: the read-only host reads, the capture and its recheck, the PH4-13 comparison and the typed output (INV-HOST-MIGRATION-001).

Layer: adapters
Context: delivery
Owns: `HostReader`, `bounded_run`, `Ports`, `Capture`, `observe`, `validate_request` and the capture/recheck helpers (M7 `adapters/host_migration_evidence.py`)
Does not own: the operator CLI (`cli_ports`, `observe_command`, `_archive`, `_named_env`, `_schema`, `_lane_dsn`: S10, they need fleet_runtime, monitoring and application.fleet), the `/proc` facts (`host_os.adapters.host_facts`, injected as `facts`), process creation (the host_os chokepoint, injected as `processes`), the evidence policy (`delivery.domain.host_migration_evidence`)
Entry points: observe, HostReader, bounded_run, Ports, validate_request
Contracts: INV-HOST-MIGRATION-001, INV-HOST-DELIVERY-VERIFY-001

S7 named transcription of M7 `adapters/host_migration_evidence.py` (SOURCE e38aa722) through the declared rules (DESIGN-s7 adapters-move §8/§9, A/evidence/rebuild/s7/migration-evidence-adapter/transcribe.py): the S10 CLI excluded, `facts` and `processes` required (V6), and the import homes; every body is otherwise M7's. M7 docstring follows.

Read-only receipt producer of a managed `limited_active` transition (INV-HOST-MIGRATION-001).

@invariant INV-HOST-MIGRATION-001

`python -m codex_harness.adapters.host_migration observe-limited-active ...` runs `observe` once. It
prints `{observation, result_sha256, projections, evidence, transition_draft, diagnostic}` and the
operator archives it in a new evidence directory. There is no apply mode. With `--expect <archived
output>` it re-reads every source and prints `{observation, result_sha256, projections, diagnostic,
comparison}` instead: no draft and no receipt. Run before submitting the archived draft, it refuses any
changed tuple. With `--post-transition` as well, it is the post-check after the recorded managed
transition (PH4-13). The policy lives in `domain.host_migration_evidence`; this module only reads:

* The coordinator record, the owner-action canary row, the Fleet registry (lane routing only) and the
  delivery rows are read through `LaneSnapshotStore`. Each read is one `REPEATABLE READ READ ONLY`
  transaction on a connection whose only search path is the stated, verified schema. The writers'
  advisory lock is never taken, no `PostgresStore` is constructed, and nothing is migrated or created.
* Host files, all read-only: `host-activation.json`, `host-fence.json` (presence only),
  `releases/current`, the managed state directory's descriptor, startup receipt and plan-scoped owner
  canary request and receipt, and the host configuration file (hashed only).
* `/usr/bin/systemctl show` of the one owner-fixed managed unit, and `/usr/bin/journalctl -o json` of
  exactly that unit's current invocation, boot and main pid, restricted to the fields it reads. These
  are the only commands. They run by absolute path with a fixed minimal environment (no inherited
  connection string), and their output is read up to a byte cap; more is an unknown.
* `/proc` through the accepted `HostFacts` (pid, start ticks, boot id, cgroup) plus the pid's parent
  and the sha256 of its cmdline: a raw argv is never kept, so a reused pid's arguments never reach the
  output. The boottime-monotonic clock offset is measured once, so `/proc` start times compare with
  systemd's and journald's monotonic timestamps across a suspend. The supervisor's own journal line
  for this invocation is read from the managed state directory, and the sealed runtime through
  `Materializer.verify`.

Nothing is written, locked, registered, ticked, started, stopped or submitted. No artifact is stored.
No model, provider or network endpoint other than the stated store is contacted. Connection strings
are read in this process from the NAMED environment variables the accepted loader sets. They never
reach argv or the result. A read that fails is `activation_observation_unavailable` naming only its
step, and no exception text, path or value is kept. Every source reaches the result only through
`Capture.record`, as its typed allowlist projection (`domain.host_migration_evidence.project`): a
document that failed its check keeps its raw digest, fixed shape and typed identifiers, never itself.

Files are opened `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` and must be regular files by `fstat`, like
`monitoring.ArtifactReader`.

The capture is bounded, not atomic across the filesystem and the stores. It reads every source once,
then rereads every identity tuple (effective head, activation file and `current`, configuration,
descriptor and startup and canary bytes, delivery rows, canary record, unit invocation, boot and both
processes). A difference, including a source that is gone, is `activation_observation_changed`. The
observation is then obsolete and must be recollected, never rewritten.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from codex_harness.delivery.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    canary_receipt_file,
    canary_request_file,
    owner_qualified_canary,
    systemd_control_dir,
)
from codex_harness.delivery.adapters.host_migration import ACTIVATION_FILE, FENCE_FILE, current_revision
from codex_harness.delivery.adapters.managed_runtime import SUPERVISOR_JOURNAL, Materializer
from codex_harness.delivery.application.host_delivery.state import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    BUCKET_TARGETS,
)
from codex_harness.delivery.application.host_migration import BUCKET as MIGRATIONS
from codex_harness.delivery.domain import host_migration_evidence as policy
from codex_harness.delivery.domain.host_delivery import TOKEN as DELIVERY_TOKEN
from codex_harness.delivery.domain.host_delivery import DeliveryRefused
from codex_harness.delivery.domain.host_migration import HEX64, TOKEN, MigrationRefused
from codex_harness.delivery.domain.managed_runtime import EnvironmentUnqualified
from codex_harness.delivery.domain.managed_runtime import manifest_digest as runtime_manifest_digest
from codex_harness.kernel.ids import digest

# The owner-action rows (INV-OWNER-ACTIONS-001); the constant of `application.owner_actions`.
OWNER_ACTIONS = "owner_actions"
MANAGED_STATE = ("runtime", "managed-fleet")
CONFIG_FILE = ("config", "zeus-aibox.env")
MAX_FILE_BYTES = 1024 * 1024
MAX_CMDLINE_BYTES = 1024 * 1024
MAX_JOURNAL_ENTRIES = 100_000
# stdout of one host command; stderr is capped far lower and is itself an unknown for `journalctl`.
MAX_COMMAND_BYTES = 4 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
COMMAND_TIMEOUT = 30
# The only two commands, by absolute path, with nothing inherited: no connection string or credential
# variable of this process reaches them, and no PATH lookup chooses the binary.
SYSTEMCTL = "/usr/bin/systemctl"
JOURNALCTL = "/usr/bin/journalctl"
COMMAND_ENV = {"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"}
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


class Unreadable(Exception):
    """A host fact that exists but cannot be observed; `_read` turns it into the step's unknown."""


def bounded_run(argv: list, *, timeout: float, env: dict, limit: int,
                processes) -> subprocess.CompletedProcess:
    """One read-only host command: stdout (bytes) is read up to `limit` and stderr up to
    `MAX_STDERR_BYTES`, never buffered beyond. More of either, or the deadline, kills the child's
    session and is `Unreadable`. The child gets exactly `env` and no stdin."""
    process = processes.popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, close_fds=True, start_new_session=True)
    buffers = {process.stdout: bytearray(), process.stderr: bytearray()}
    caps = {process.stdout: limit, process.stderr: MAX_STDERR_BYTES}
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for stream in buffers:
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Unreadable("command_timeout")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffers[key.fileobj] += chunk
                    if len(buffers[key.fileobj]) > caps[key.fileobj]:
                        raise Unreadable("command_output")
        returncode = process.wait(max(0.0, deadline - time.monotonic()))
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
    return subprocess.CompletedProcess(argv, returncode, bytes(buffers[process.stdout]),
                                       bytes(buffers[process.stderr]))


def boottime_offset_usec() -> int:
    """CLOCK_BOOTTIME - CLOCK_MONOTONIC now, in microseconds: the time this host has been suspended
    since boot. `/proc/<pid>/stat` start ticks count boottime; systemd's `...Monotonic` and journald's
    `__MONOTONIC_TIMESTAMP` do not. The midpoint of two monotonic reads bounds the read jitter."""
    before = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    after = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    return max(0, (boot - (before + after) // 2) // 1000)


def _argv_sha256(argv: list) -> str:
    """The digest of an argv exactly as `/proc/<pid>/cmdline` spells it: each word NUL-terminated."""
    return hashlib.sha256(b"".join(word.encode("utf-8") + b"\0" for word in argv)).hexdigest()


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
    INV-HOST-DELIVERY-VERIFY-001, with its rule that an unobservable fact is unknown, never absent.
    `runner(argv, timeout=, env=, limit=)` returns bytes output (`bounded_run`, bound to `processes`, the
    host_os `ChildProcesses` of V6, when no runner is given); `boottime_offset()` measures the clock offset
    (`boottime_offset_usec`). `facts` and `processes` are required: composition passes
    `host_os.adapters.host_facts.HostFacts()` and the chokepoint."""

    def __init__(self, *, runner=None, facts, clk_tck: int | None = None, timeout: int = COMMAND_TIMEOUT,
                 boottime_offset=None, output_limit: int = MAX_COMMAND_BYTES, processes):
        self.runner = runner or functools.partial(bounded_run, processes=processes)
        self.facts, self.timeout = facts, timeout
        self.clk_tck = clk_tck or os.sysconf("SC_CLK_TCK")
        self.boottime_offset = boottime_offset or boottime_offset_usec
        self.output_limit = output_limit

    def _run(self, argv: list):
        result = self.runner(argv, timeout=self.timeout, env=dict(COMMAND_ENV), limit=self.output_limit)
        if not (isinstance(result.stdout, bytes) and isinstance(result.stderr, bytes)) \
                or len(result.stdout) > self.output_limit:
            raise Unreadable("command_output")
        return result

    @staticmethod
    def file(path, limit: int = MAX_FILE_BYTES) -> bytes | None:
        """The bytes of one regular file, or None when nothing exists there. It is opened without
        following a final link and without blocking, then `fstat` must say regular file (as
        `monitoring.ArtifactReader`): a link, a FIFO, another kind of entry or an oversized file is
        unknown."""
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except FileNotFoundError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise Unreadable("file_kind")
            chunks, size = [], 0
            while size <= limit:
                chunk = os.read(descriptor, min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        finally:
            os.close(descriptor)
        if size > limit:
            raise Unreadable("file_size")
        return b"".join(chunks)

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
        argv = [SYSTEMCTL, "show", "--no-pager", unit]
        for name in policy.UNIT_PROPERTIES:
            argv += ["-p", name]
        result = self._run(argv)
        if result.returncode:
            raise Unreadable("unit")
        return policy.unit_facts(result.stdout.decode("utf-8"))

    def journal(self, unit: str, invocation_id: str, boot_id: str, main_pid: int) -> list:
        """The journal entries of exactly this unit invocation, boot and main pid, in journal order,
        with only the fields `launch_record` reads.

        The unit has a current invocation here, and its main process wrote the launcher's event before
        its exec, so an empty answer is not "no launch": it is what an unprivileged reader sees. Any
        stderr (a permission hint included) or no entry at all is therefore unknown, never
        `launch_missing`."""
        if not (HEX32.fullmatch(invocation_id) and HEX32.fullmatch(boot_id) and type(main_pid) is int
                and main_pid > 0):
            raise Unreadable("journal")
        result = self._run([JOURNALCTL, "--no-pager", "-o", "json",
                            "--output-fields=" + ",".join(policy.JOURNAL_FIELDS), "_SYSTEMD_UNIT=" + unit,
                            "_SYSTEMD_INVOCATION_ID=" + invocation_id, "_BOOT_ID=" + boot_id,
                            "_PID=" + str(main_pid)])
        if result.returncode or result.stderr:
            raise Unreadable("journal")
        lines = [line for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
        if not lines:
            raise Unreadable("journal_empty")
        if len(lines) > MAX_JOURNAL_ENTRIES:
            raise Unreadable("journal_size")
        return [json.loads(line) for line in lines]

    def boot_id(self) -> str:
        """The current boot id in the journal's spelling (32 hex, no dashes)."""
        value = (self.facts.boot_id() or "").replace("-", "")
        if not HEX32.fullmatch(value):
            raise Unreadable("boot")
        return value

    def process(self, pid, offset_usec: int = 0) -> dict:
        """One process identity: start ticks, parent, cgroup and the sha256 of its cmdline (the raw
        argv is never kept). `start_usec` is CLOCK_MONOTONIC: the boottime ticks less `offset_usec`,
        the offset measured for this observation, rounded to the tick. The identity is read again
        after the reads, so a pid that changed hands meanwhile is `replaced`, never merged."""
        if type(pid) is not int or pid <= 0:
            return {"pid": pid, "state": "absent"}
        state, ticks = self.facts.process(pid)
        if state == "absent":
            return {"pid": pid, "state": "absent"}
        if state != "present":
            raise Unreadable("process")
        root = Path(self.facts.proc) / str(pid)
        cmdline = self.file(root / "cmdline", MAX_CMDLINE_BYTES)
        text = (root / "stat").read_text("utf-8", errors="replace")
        fields = text[text.rindex(")") + 1:].split()
        if len(fields) < 2 or not fields[1].isdigit():
            raise Unreadable("process")
        cgroup = self.facts.cgroup(pid)
        if cmdline is None or self.facts.process(pid) != (state, ticks):
            return {"pid": pid, "state": "replaced"}
        offset_ticks = round(offset_usec * self.clk_tck / 1_000_000)
        return {"pid": pid, "state": "present", "start_ticks": ticks, "boottime_offset_ticks": offset_ticks,
                "start_usec": (ticks - offset_ticks) * 1_000_000 // self.clk_tck,
                "tick_usec": 1_000_000 // self.clk_tck, "ppid": int(fields[1]), "cgroup": cgroup,
                "argv_sha256": _sha256(cmdline)}

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

    def record(self, name: str, facts, *, accepted: bool = False) -> None:
        """The one record path (PH4-12): what is returned, archived and hashed is the domain's typed
        projection of what was read (`policy.project`), never the read object itself. `accepted` says
        the source's own check accepted it."""
        projection = policy.project(name, facts, accepted=accepted)
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


def _activation_identity(host: HostReader, q: dict, revision: str) -> tuple:
    """The recheck's `_file_identity`: bytes, not parsed, so a file that is gone or rewritten is a change."""
    control, releases = q["root"] / "runtime" / "control", q["root"] / "releases"
    return (_sha256(host.file(control / ACTIVATION_FILE)), host.exists(control / FENCE_FILE),
            host.current(releases), host.release_present(releases, revision))


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


def _process_projection(process: dict, role: str, expected_sha256: str, **facts) -> dict:
    """The facts of one process source: identity, parent, cgroup, the argv digest and whether it matched.
    `validated` stays None until the process passes its check; then it holds only fixed facts. What is
    archived is their typed projection."""
    return {**process, **facts, "role": role, "argv_match": process.get("argv_sha256") == expected_sha256,
            "validated": None}


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
def _capture(q: dict, ports: Ports, run: Capture, *, post_transition: bool = False) -> dict:
    """Every source once, in order. Each group sets its check only after it holds. The first refusal
    stops the capture with its fixed code; the sources already read stay recorded."""
    host, state_dir = ports.host, q["root"].joinpath(*MANAGED_STATE)
    # 1. The coordinator: restored_paused (or, in a post-check, limited_active by the managed
    #    transition), exact manifest, exactly the expected effective head. The host configuration's
    #    digest is committed here, in the `migration` projection, because the draft's identity names it.
    row = _read("migration", _migration_row, ports, q["migration_id"])
    if not isinstance(row, dict):
        raise MigrationRefused(policy.UNAVAILABLE, "migration")
    view = _read("migration", policy.migration_view, row)
    config = _read("config", host.file, q["config_file"])
    run.record("migration", {**view, "config_sha256": _sha256(config)})
    run.identity["migration"] = _migration_identity(view)
    run.identity["config"] = _sha256(config)
    if config is None:
        raise MigrationRefused(policy.UNAVAILABLE, "config")
    activation = policy.require_head(view, q["migration_id"], q["expected_id"], post_transition=post_transition)
    run.manifest_sha256, run.activation, run.host = view["manifest_sha256"], activation, view["target_host_id"]
    # 2. The launcher's receipt equals the derived document as an object; no fence; `current` is it.
    files = _read("activation_file", _activation_file, host, q, activation["release_revision"])
    run.identity["activation_file"] = _file_identity(files)
    accepted = False
    try:
        policy.require_activation_file(files, view)
        accepted = True
    finally:
        run.record("activation_file", files, accepted=accepted)
    run.checks["activation_equal"] = True
    policy.require_current(files, view)
    run.checks["current_equal"] = True
    # 3. The unit's main process is the exec'd supervisor, and its own pre-exec launch event names
    #    this activation. Process start times are compared on CLOCK_MONOTONIC.
    unit = _read("unit", host.unit, policy.MANAGED_UNIT)
    boot = _read("boot", host.boot_id)
    offset = _read("clock", host.boottime_offset)
    if type(offset) is not int or offset < 0:
        raise MigrationRefused(policy.UNAVAILABLE, "clock")
    supervisor = _read("supervisor", host.process, unit["main_pid"], offset)
    launches = _read("supervisor_journal", _supervisor_launches, host, state_dir, unit["invocation_id"])
    run.identity.update(unit=_unit_identity(unit), boot=boot, supervisor=_process_identity(supervisor),
                        supervisor_journal=digest(launches))
    expected = _argv_sha256(_supervisor_argv(q["root"], activation["release_revision"]))
    projection = _process_projection(supervisor, "supervisor", expected, boot_id=boot,
                                     invocation_id=unit["invocation_id"], unit=unit, launches=launches)
    try:
        policy.require_supervisor(unit, supervisor, argv_sha256=expected)
        projection["validated"] = policy.supervisor_facts(activation["release_revision"])
    finally:
        run.record("supervisor", projection)
    entries = _read("journal", host.journal, policy.MANAGED_UNIT, unit["invocation_id"], boot, unit["main_pid"])
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
    described = {"document": descriptor, "raw_sha256": _sha256(raw_descriptor), "runtime": None}
    accepted = False
    try:
        consumed = policy.require_consumption(delivery, descriptor, startup, activation, target_id=q["target_id"],
                                              plan_id=q["plan_id"], state_dir=str(state_dir))
        accepted = True
        described["runtime"] = _sealed(host, consumed)
    finally:
        # Both documents were read as untrusted data: until the consumption check accepted them, only
        # their raw digests, typed identifiers and shape are archived.
        run.record("startup", {"document": startup, "raw_sha256": _sha256(raw_startup)}, accepted=accepted)
        run.record("descriptor", described, accepted=accepted)
    run.lineage = consumed["lineage"]
    run.checks["consumption"] = True
    # 5. The live entry is the process that wrote the consumed receipt, in this unit, under this supervisor.
    entry = _read("entry", host.process, startup["pid"], offset)
    run.identity["entry"] = _process_identity(entry)
    expected = _argv_sha256(_entry_argv(consumed["target"], state_dir))
    projection = _process_projection(entry, "entry", expected, boot_id=boot, invocation_id=unit["invocation_id"])
    try:
        policy.require_supervisor_launch(launches, descriptor_sha256=consumed["descriptor_sha256"])
        policy.require_entry(entry, supervisor, unit, launch, argv_sha256=expected, started_at=startup["started_at"])
        projection["validated"] = policy.entry_facts()
    finally:
        run.record("entry", projection)
    run.checks["process_bound"] = True
    # 6. A passed owner canary of this plan, descriptor and instance, agreeing with its accepted record.
    canary = _read("canary_receipt", _canary_files, host, q)
    run.identity["canary_receipt"] = (canary["receipt_sha256"], canary["request_sha256"])
    accepted = False
    try:
        incumbent = _read("canary_receipt", lambda: owner_qualified_canary(
            consumed["target"], consumed["descriptor"], {"instance_id": consumed["instance_id"]},
            plan=consumed["plan"]))
        receipt = canary["receipt"]
        action_id = (receipt.get("evidence") or {}).get("action_id") if isinstance(receipt, dict) \
            and isinstance(receipt.get("evidence"), dict) else None
        record = None
        if type(action_id) is str and HEX64.fullmatch(action_id):
            record = _read("canary_record", _action_row, ports, action_id)
            if isinstance(record, dict):
                run.record("canary_record", record)
        run.identity["canary_record"] = digest(policy.record_view(record))
        policy.require_canary(consumed, incumbent, receipt, canary["request"], record, intent=delivery["intent"],
                              started_at=startup["started_at"])
        accepted = True
    finally:
        run.record("canary_receipt", canary, accepted=accepted)
    run.checks["canary_bound"] = True
    return {"supervisor_pid": unit["main_pid"], "entry_pid": startup["pid"], "action_id": action_id,
            "revision": activation["release_revision"], "invocation_id": unit["invocation_id"], "offset": offset}


class _Gone(Exception):
    """A source the capture read no longer exists at the recheck: a change, never an unknown."""


GONE = "gone"


def _recheck_readers(q: dict, ports: Ports, context: dict) -> dict:
    """One reread per identity key, through the same reads as the capture. A source that is gone
    answers `GONE` (or a None digest); only a read that fails is unknown."""
    host, state_dir = ports.host, q["root"].joinpath(*MANAGED_STATE)

    def migration():
        row = _migration_row(ports, q["migration_id"])
        if not isinstance(row, dict):
            raise _Gone
        return _migration_identity(policy.migration_view(row))

    def unit():
        try:
            return _unit_identity(host.unit(policy.MANAGED_UNIT))  # a failed `systemctl` is unknown
        except MigrationRefused:
            # `systemctl` answered, but its facts no longer describe a current invocation: it stopped.
            raise _Gone from None

    def supervisor_journal():
        raw = host.file(state_dir / SUPERVISOR_JOURNAL)
        if raw is None:
            raise _Gone
        return digest(policy.supervisor_launches(raw.decode("utf-8"), context["invocation_id"]))

    def delivery():
        rows = _delivery_rows(ports, q)
        if not all(isinstance(row, dict) for row in rows[:4]):
            raise _Gone
        return digest(policy.delivery_view(*rows, target_id=q["target_id"], plan_id=q["plan_id"]))

    def canary_receipt():
        return (_sha256(host.file(state_dir / canary_receipt_file(q["plan_id"]))),
                _sha256(host.file(state_dir / canary_request_file(q["plan_id"]))))

    return {
        "migration": migration,
        "activation_file": lambda: _activation_identity(host, q, context["revision"]),
        "config": lambda: _sha256(host.file(q["config_file"])),
        "unit": unit,
        "boot": host.boot_id,
        "supervisor": lambda: _process_identity(host.process(context["supervisor_pid"], context["offset"])),
        "supervisor_journal": supervisor_journal,
        "delivery": delivery,
        "descriptor": lambda: _sha256(host.file(state_dir / DESCRIPTOR_FILE)),
        "startup": lambda: _sha256(host.file(state_dir / RECEIPT_FILE)),
        "entry": lambda: _process_identity(host.process(context["entry_pid"], context["offset"])),
        "canary_receipt": canary_receipt,
        "canary_record": lambda: digest(policy.record_view(_action_row(ports, context["action_id"]))),
    }


def _recheck(q: dict, ports: Ports, context: dict, identity: dict) -> None:
    """The end-of-capture reread of every identity tuple, the unit first. The first changed or gone
    tuple in capture order is `activation_observation_changed` (a restart is `unit`, not its effects);
    only when nothing readable changed does a reread that failed make the capture unknown."""
    readers, fresh, unreadable = _recheck_readers(q, ports, context), {}, []
    for key in sorted(identity, key=lambda name: name != "unit"):
        try:
            fresh[key] = readers[key]()
        except _Gone:
            fresh[key] = GONE
        except Exception:  # noqa: BLE001 - a reread that fails is the same unknown as a read that fails
            unreadable.append(key)
    changed = [key for key in identity if key not in unreadable and fresh[key] != identity[key]]
    if changed:
        raise MigrationRefused(policy.CHANGED, changed[0])
    if unreadable:
        raise MigrationRefused(policy.UNAVAILABLE, unreadable[0])


def observe(request, ports: Ports, *, expect=None, post_transition: bool = False) -> dict:
    """One bounded read-only capture. Returns the observation, its digest, the archived source
    projections, the three receipts and, only on complete success, the transition draft.

    With `expect` (an archived success output) it is a comparison instead (PH4-13): the archive is
    validated before anything is read, the same capture runs, and the output carries the fresh
    observation and `comparison`, never a draft or a receipt. `post_transition` requires `expect`."""
    q = validate_request(request)
    if post_transition and expect is None:
        raise MigrationRefused("request_invalid", "expect")
    archive = None if expect is None else policy.validate_archive(
        expect, migration_id=q["migration_id"], expected_id=q["expected_id"], target_id=q["target_id"],
        plan_id=q["plan_id"])
    run = Capture(ports.clock)
    observed_from = ports.clock()
    reason = detail = None
    try:
        context = _capture(q, ports, run, post_transition=post_transition)
        _recheck(q, ports, context, run.identity)
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
    projections = {name: run.projections.get(name) for name in policy.SOURCES}
    result = {"observation": observation, "result_sha256": result_sha256, "projections": projections,
              "diagnostic": None if reason is None else {"reason_code": reason, "detail": detail}}
    if archive is not None:
        result["comparison"] = policy.compare_observation(archive, observation, projections,
                                                          post_transition=post_transition, refusal=(reason, detail))
        return result
    receipts = policy.observation_receipts(observation, result_sha256, q["expected_id"])
    result["evidence"] = receipts
    result["transition_draft"] = policy.transition_draft(
        observation, receipts, host=run.host, actor=q["actor"],
        config_sha256=projections["migration"]["config_sha256"]) if observation["ok"] else None
    return result


__all__ = ["COMMAND_ENV", "HostReader", "Ports", "boottime_offset_usec", "bounded_run", "observe",
           "validate_request"]
