"""Host-side proof for the two owner operations of storage-recovery-001 (INV-FLEET-001).

The policy lives in `domain.fleet_recovery`; everything impure lives here. Nothing in this module
writes to the lane store, to Docker, to the machine call ledger or to any copied artifact: it reads
what the host can actually show and answers with one observation document, or it refuses with a
fixed reason code. A value never reaches the message; the field name does.

`collect_recovery_proof` binds an interrupted fleet job to dead external effects: the lane
`operations` row that owns the exact `operation:<id>` correlation (the existing
`operation_finalization.owner` rule), the cancelled task at its advanced generation with no live
lease, the task's recorded worktree, the one retained isolation run record for that worktree with
its exact container name and id, that container's Docker state, the closed invocation reservation
and the settled machine call slot, which is bound to that same operation by the ledger's own
`purpose` or the operation row's own recorded calls rather than by the caller's assertion. A
container name with no recorded task/run binding is refused, a call slot with no recorded binding
is refused, unknown usage stays unknown, and an unreadable or ambiguous read is a refusal, never an
absence.

`collect_relocation_proof` establishes that the fleet is idle for a cutover and that the copied
targets are usable: the service lifecycle journal (`adapters/service_entry`) must show the last
Fleet CLI run finished, every retained isolation run in a moving lane must have a container Docker
proves is not running, each target must be a real independent checkout of the same repository
identity carrying every queued job's pinned base commit and goal bytes, each target runtime must be
writable, and every entry of the owner's copy manifest must be a file below a path this request
moves that reads back to the declared digest and length. The owner's own idle claim is never read
as a fact, and neither is a source that could not be enumerated; where the platform cannot
establish one, the answer is a bounded refusal instead of an assumption.

Copy ownership is physical, not lexical: a normalized absolute name proves nothing about where it
leads. `normalize_path`'s casefolded comparison form belongs to scheduling identity and is not a
filesystem rule - on a case-sensitive filesystem it reads two distinct sibling directories as one -
so containment here is decided by concrete, platform-native `Path` operations on strictly resolved
roots and files, with the relative components the request actually spelled. Every declared component
below each move root is inspected with `lstat` and a symlink, junction or other reparse point is
refused as such, on the source side as well and whether or not it happens to lead outside the root:
a redirected child is not the file this request moves, wherever it points.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePath

from codex_harness.adapters.call_budget import CallBudget
from codex_harness.adapters.isolated_worker import LIMITS, RESOLVED, _docker, run_records
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.application.operation_finalization import _lease_live as lease_live
from codex_harness.application.operation_finalization import owner as operation_owner
from codex_harness.domain.fleet import (
    FleetRefused,
    absolute_resolved,
    normalize_path,
    repository_identity,
)
from codex_harness.domain.fleet_recovery import (
    CLOSED_INVOCATIONS,
    COPY_MANIFEST_SCHEMA,
    COPY_OWNERSHIP,
    HEX64,
    HOST_MIGRATION_PROOF_SCHEMA,
    MOVABLE,
    PROOF_SCHEMA,
    RELOCATION_PROOF_SCHEMA,
    STOPPED_STATES,
)
from codex_harness.domain.model import digest, utcnow

# Where `bootstrap.isolated_worker` puts the retained run records of one runtime root.
RUN_ROOT = ("isolated-worker", "runs")
COPY_ENTRY_FIELDS = {"source", "destination", "sha256", "bytes"}
READ_BYTES = 1 << 20
# The largest single copied file this verification will read back. A manifest may not ask for an
# unbounded read, and a declared length beyond this is refused instead of attempted.
MAX_COPY_BYTES = 1 << 36
# One journal line per lifecycle step; a service journal far longer than this is not read further
# back, so an unbounded file cannot be walked here.
JOURNAL_LINES = 20000


def _hash_file(path: Path) -> str | None:
    """The sha256 of a file's bytes, or None when it cannot be read as one."""
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            while chunk := stream.read(READ_BYTES):
                sha.update(chunk)
    except OSError:
        return None
    return sha.hexdigest()


def _hash_bounded(path: Path, limit: int) -> dict | None:
    """The sha256 and length of a file, reading at most one byte past the declared length.

    A file that cannot be opened or read answers None, which is never a match for anything; a file
    longer than it was declared to be stops the read and reports the longer length, so a manifest
    entry can never make this command walk an unbounded file.
    """
    sha, size = hashlib.sha256(), 0
    try:
        with open(path, "rb") as stream:
            while size <= limit and (chunk := stream.read(min(READ_BYTES, limit + 1 - size))):
                sha.update(chunk)
                size += len(chunk)
    except OSError:
        return None
    return {"sha256": sha.hexdigest(), "bytes": size}


def _resolved_directory(value: str, field: str) -> Path:
    """An existing directory whose own spelling is its resolution: a symlink or junction that
    points somewhere else is refused here rather than followed."""
    path = Path(value)
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise FleetRefused("path_unresolved", field) from exc
    if resolved != path or not path.is_dir():
        raise FleetRefused("path_unresolved", field)
    return path


def run_root(runtime: str) -> Path:
    return Path(runtime).joinpath(*RUN_ROOT)


def docker_state(container_id: str, docker: str = "docker") -> dict | None:
    """The exact container's state by id, or None when Docker could not answer about it."""
    shown = _docker(docker, ["inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", container_id],
                    timeout=LIMITS["docker_command_seconds"])
    parts = shown.stdout.split()
    if shown.returncode != 0 or len(parts) != 2:
        return None
    return {"status": parts[0], "exit_code": int(parts[1]) if parts[1].lstrip("-").isdigit() else None}


class LaneReader:
    """Read-only document reads from one lane schema. It opens, reads and closes; never writes.

    The schema the connection actually selected is verified on every reader, so a DSN that fell
    back to `public` reads nothing here.
    """

    def __init__(self, dsn: str, schema: str, connect=None):
        if connect is None:  # imported lazily so a store-free unit test needs no driver
            import psycopg

            connect = psycopg.connect
        self.dsn, self.schema, self.connect = dsn, schema, connect

    def _read(self, statement: str, parameters: tuple) -> list:
        try:
            with self.connect(self.dsn, connect_timeout=5) as conn:
                current = conn.execute("SELECT current_schema()").fetchone()[0]
                if current != self.schema:
                    raise FleetRefused("lane_schema_mismatch")
                return conn.execute(statement, parameters).fetchall()
        except FleetRefused:
            raise
        except Exception as exc:
            # An unreadable lane is uncertainty, never an empty result.
            raise FleetRefused("lane_unreadable") from exc

    def get(self, bucket: str, key: str):
        rows = self._read("SELECT body FROM documents WHERE bucket=%s AND id=%s", (bucket, key))
        return rows[0][0] if rows else None

    def scan(self, bucket: str) -> list:
        return [row[0] for row in self._read("SELECT body FROM documents WHERE bucket=%s ORDER BY id", (bucket,))]


# ----- reconcile ---------------------------------------------------------------------------
def _run_record(runtime: str, worktree: str, evidence: dict) -> dict:
    """The one retained isolation run of this task's recorded worktree, bound to the named container."""
    records = [row for row in run_records(run_root(runtime)) if row.get("workspace") == worktree]
    if not records:
        raise FleetRefused("container_binding_missing", "container.run_id")
    if len(records) > 1:
        raise FleetRefused("container_ambiguous", "container.run_id")
    record = records[0]
    if record.get("state") == "unreadable":
        raise FleetRefused("run_record_unreadable", "container.run_id")
    if record.get("run_id") != evidence["container"]["run_id"] \
            or record.get("container_name") != evidence["container"]["name"]:
        raise FleetRefused("container_binding_mismatch", "container.name")
    if record.get("container") != evidence["container"]["id"]:
        raise FleetRefused("container_binding_mismatch", "container.id")
    return record


def collect_recovery_proof(evidence: dict, lane: dict, *, reader, budget=None, state=docker_state,
                           clock=utcnow) -> dict:
    """Observe, in the lane store, on the Docker daemon and in the machine ledger, that the work
    this evidence names is dead. Raises `FleetRefused` with a fixed reason for anything missing,
    unreadable or ambiguous; it never decides what happens to the job."""
    operation = operation_owner(reader, evidence["lane_operation"]["correlation_id"])
    if operation is None or operation.get("id") != evidence["lane_operation"]["id"]:
        raise FleetRefused("lane_operation_unbound", "lane_operation.correlation_id")
    task = reader.get("tasks", evidence["lane_operation"]["task_id"])
    if not isinstance(task, dict) or task.get("id") != evidence["lane_operation"]["task_id"]:
        raise FleetRefused("task_unknown", "lane_operation.task_id")
    message = task.get("message") if isinstance(task.get("message"), dict) else {}
    if message.get("correlation_id") != evidence["lane_operation"]["correlation_id"]:
        raise FleetRefused("task_not_bound", "lane_operation.task_id")
    if task.get("status") != "cancelled":
        raise FleetRefused("task_not_cancelled", "task.status")
    if task.get("generation") != evidence["lane_operation"]["generation"]:
        # The fence advanced when the task was cancelled; another generation is other work.
        raise FleetRefused("task_generation_mismatch", "lane_operation.generation")
    now = datetime.fromisoformat(clock())
    now = now if now.utcoffset() is not None else now.replace(tzinfo=timezone.utc)
    live = lease_live(task, now)  # the existing rule: unparsable is unknown, never "not live"
    if live is None:
        raise FleetRefused("task_lease_unknown", "task.lease_until")
    if live:
        raise FleetRefused("task_lease_live", "task.lease_until")
    progress = reader.get("execution_progress", evidence["lane_operation"]["task_id"])
    worktree = progress.get("worktree") if isinstance(progress, dict) else None
    if not isinstance(worktree, str) or not worktree:
        # Without the task's own recorded worktree there is no task/run binding to check a
        # container name against, and a name alone is not proof of ownership.
        raise FleetRefused("container_binding_missing", "execution_progress.worktree")
    record = _run_record(lane["runtime"], worktree, evidence)
    observed = state(evidence["container"]["id"])
    if not isinstance(observed, dict) or observed.get("status") not in STOPPED_STATES:
        raise FleetRefused("docker_unavailable" if observed is None else "container_not_stopped", "container.id")
    reservation = reader.get("invocation_reservations", evidence["invocation"]["reservation_id"])
    if not isinstance(reservation, dict) or reservation.get("task_id") != evidence["lane_operation"]["task_id"]:
        raise FleetRefused("invocation_unknown", "invocation.reservation_id")
    if reservation.get("status") not in CLOSED_INVOCATIONS:
        raise FleetRefused("invocation_open", "invocation.status")
    if any(row.get("status") == "reserved" and row.get("task_id") == evidence["lane_operation"]["task_id"]
           for row in reader.scan("invocation_reservations")):
        raise FleetRefused("invocation_open", "invocation.reservation_id")
    slot = _machine_slot(evidence, budget, operation)
    usage = reservation.get("usage") if isinstance(reservation.get("usage"), dict) else {}
    return {"schema": PROOF_SCHEMA,
            "lane_operation": {"id": operation["id"], "correlation_id": operation["correlation_id"],
                               "status": operation.get("status")},
            "task": {"id": task["id"], "status": task.get("status"), "generation": task.get("generation"),
                     "lease_live": live},
            "container": {"run_id": record["run_id"], "name": record["container_name"],
                          "id": record["container"], "state": observed["status"],
                          "exit_code": observed.get("exit_code"), "bound_worktree": True,
                          "record_state": record.get("state")},
            "invocation": {"reservation_id": reservation["id"], "status": reservation["status"],
                           # Preserved exactly as recorded: an interrupted call's usage is unknown,
                           # and nothing here back-fills it to zero.
                           "usage_source": usage.get("source"), "total_tokens": usage.get("total_tokens")},
            "machine_slot": slot, "worktree_digest": digest(worktree), "observed_at": clock()}


def _recorded_slots(operation: dict) -> dict:
    """The call slots the lane `operations` row itself recorded, by id.

    `application.operation` writes `calls.slots[]` when the operation FINISHES, so an interrupted
    operation usually has none; this is the binding when the row does carry them, not a substitute
    for the ledger's own.
    """
    calls = operation.get("calls") if isinstance(operation.get("calls"), dict) else {}
    recorded = calls.get("slots") if isinstance(calls.get("slots"), list) else []
    return {row["id"]: row for row in recorded if isinstance(row, dict) and type(row.get("id")) is str}


def _machine_slot(evidence: dict, budget, operation: dict) -> dict:
    """The named machine call slot, bound to THIS operation by the host's own records.

    The slot id in the evidence document is a caller assertion, and an unrelated settled slot has
    exactly the same shape as the right one. Two records the host wrote for its own reasons decide
    instead: the ledger slot's `purpose`, which `application.operation.BudgetedExecutor` writes as
    `operation:<id>:<kind>` at the moment the slot is taken, and the lane `operations` row's
    recorded `calls.slots[]`. Where both exist they must agree, including the provider. A slot that
    carries neither (an older ledger row without a purpose, an operation row that never recorded
    its calls) is incomplete evidence and refuses; nothing here infers the binding from the id.
    """
    ledger = CallBudget() if budget is None else budget
    rows = [row for row in ledger.slots() if row.get("id") == evidence["machine_slot"]["id"]]
    if len(rows) != 1:
        raise FleetRefused("machine_slot_unknown", "machine_slot.id")
    row = rows[0]
    if row.get("unreadable"):
        raise FleetRefused("machine_slot_unreadable", "machine_slot.id")
    correlation = evidence["lane_operation"]["correlation_id"]
    purpose = row.get("purpose")
    by_purpose = type(purpose) is str and purpose.startswith(correlation + ":") and len(purpose) > len(correlation) + 1
    recorded = _recorded_slots(operation).get(row["id"])
    if type(purpose) is str and not by_purpose:
        # A purpose that names other work is a mismatch, never a missing binding.
        raise FleetRefused("machine_slot_foreign", "machine_slot.id")
    if recorded is not None and by_purpose and recorded.get("provider") not in (None, row.get("provider")):
        raise FleetRefused("machine_slot_binding_mismatch", "machine_slot.id")
    if not by_purpose and recorded is None:
        raise FleetRefused("machine_slot_unbound", "machine_slot.id")
    return {"id": row["id"], "status": row.get("status"), "outcome": row.get("outcome"),
            "bound_by": "ledger_purpose" if by_purpose else "operation_calls",
            "bound_operation": evidence["lane_operation"]["id"],
            "provider": row.get("provider") if by_purpose else recorded.get("provider"),
            "model": row.get("model"), "kind": purpose.rpartition(":")[2] if by_purpose else recorded.get("kind")}


# ----- relocate ----------------------------------------------------------------------------
def runner_state(journal) -> dict:
    """What the service lifecycle journal says about the last Fleet CLI run on this host.

    `stopped` only when the newest `start` entry has its own `exit` entry; a journal that is
    missing, unreadable or still open at its last start answers `unknown` or `running`, and the
    caller refuses rather than assuming an idle host.
    """
    path = Path(journal) if journal is not None else None
    if path is None or not path.is_file():
        return {"state": "unknown", "run_id": None, "journal_sha256": None, "reason": "journal_missing"}
    sha = _hash_file(path)
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()[-JOURNAL_LINES:]
    except (OSError, UnicodeDecodeError):
        return {"state": "unknown", "run_id": None, "journal_sha256": sha, "reason": "journal_unreadable"}
    started, exited = None, set()
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or type(entry.get("run_id")) is not str:
            continue
        if entry.get("event") == "start":
            started = entry["run_id"]
        elif entry.get("event") == "exit":
            exited.add(entry["run_id"])
    if started is None:
        return {"state": "unknown", "run_id": None, "journal_sha256": sha, "reason": "no_recorded_run"}
    state = "stopped" if started in exited else "running"
    return {"state": state, "run_id": started, "journal_sha256": sha, "reason": None}


def listed_runs(runtime: str, field: str) -> list:
    """The retained isolation run records of one runtime root, or a refusal.

    `run_records` answers an empty list for a root that is missing, that is not a directory and
    that could not be enumerated, all of which would read as "this lane has no runs" - the exact
    absence this command must never assume. The source of the answer is checked first: the runtime
    root and its `isolated-worker/runs` root must exist and enumerate, and a run directory without
    a readable record is uncertainty too. An initialized root that genuinely holds nothing answers
    an empty list, which is a fact about a source that was read. Nothing is created here.
    """
    if not Path(runtime).is_dir():
        raise FleetRefused("lane_runtime_unavailable", field)
    runs = run_root(runtime)
    if not runs.is_dir():
        raise FleetRefused("lane_runs_unavailable", field)
    try:
        with os.scandir(runs) as entries:
            listed = [entry.name for entry in entries if entry.is_dir()]
    except OSError as exc:
        raise FleetRefused("lane_runs_unreadable", field) from exc
    records = run_records(runs)
    if len(records) != len(listed):
        # A retained run directory that holds no record at all: its container is unaccounted for.
        raise FleetRefused("lane_runs_unreadable", field)
    return records


def _active_runs(runtime: str, lane_id: str, state) -> int:
    """Retained isolation runs of this lane whose container is not proven stopped or absent."""
    active = 0
    for row in listed_runs(runtime, "lanes[]." + lane_id):
        if row.get("state") in RESOLVED:
            continue
        if row.get("state") == "unreadable":
            raise FleetRefused("lane_run_unknown", "lanes[]." + lane_id)
        container = row.get("container")
        if not isinstance(container, str) or not container:
            raise FleetRefused("lane_run_unknown", "lanes[]." + lane_id)
        observed = state(container)
        if observed is None:
            raise FleetRefused("lane_run_unknown", "lanes[]." + lane_id)
        if observed.get("status") not in STOPPED_STATES:
            active += 1
    return active


def checkout_identity(path: str, source=None) -> str:
    """One repository, whatever checkout shows it: the digest of its root commits.

    A copy, a clone and the original share their root commits; another repository does not. The
    path is never part of the identity, so a relocated checkout is recognizably the same history.
    """
    git = GitSource(path) if source is None else source
    listed = git._run("rev-list", "--max-parents=0", "--all")
    commits = sorted(listed.stdout.decode("ascii", "replace").split())
    if listed.returncode != 0 or not commits:
        raise FleetRefused("repository_identity_unknown", "repository")
    return digest(["git-roots-v1", commits])


def _independent(path: Path) -> bool:
    """A real checkout of its own: its Git directory is inside it and it borrows no objects."""
    git = GitSource(str(path))
    shown = git._run("rev-parse", "--path-format=absolute", "--git-common-dir")
    if shown.returncode != 0:
        return False
    common = Path(shown.stdout.decode("utf-8", "replace").strip())
    try:
        inside = common.resolve() == (path / ".git").resolve() or common.resolve().is_relative_to(path.resolve())
    except OSError:
        return False
    return inside and not (common / "objects" / "info" / "alternates").exists()


def _writable(path: Path) -> bool:
    probe = path / (".zeus-relocation-probe-" + digest(str(path))[:16])
    try:
        probe.write_text("", encoding="utf-8")
    except OSError:
        return False
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass
    return True


def _queued_bindings(target: str, jobs: list) -> list:
    """Each queued job's pinned base commit and goal bytes, read from the TARGET checkout."""
    git = GitSource(target)
    bindings = []
    for job in sorted(jobs, key=lambda row: row["id"]):
        goal = job["goal"]
        present = git.commit_exists(goal["base_revision"])
        mode, data = git.blob(goal["base_revision"], goal["path"]) if present else (None, b"")
        matches = mode == "100644" and hashlib.sha256(data).hexdigest() == goal["sha256"]
        bindings.append({"job_id": job["id"], "base_present": present, "goal_matches": bool(matches)})
    return bindings


def _relative(inner: str, outer: str) -> str | None:
    """`inner`'s path below `outer`, in comparison form, or None when it is not below it."""
    low, high = normalize_path(inner), normalize_path(outer)
    if low == high or not low.startswith(high.rstrip("/") + "/"):
        return None
    return low[len(high.rstrip("/")) + 1:]


def _move_roots(request: dict) -> list:
    """Every `from` -> `to` pair this request actually moves, as `(lane, key, from, to)`."""
    return [(move["lane"], key, move[key]["from"], move[key]["to"])
            for move in request["moves"] for key in MOVABLE if move[key] is not None]


def _bind_entry(entry: dict, roots: list, name: str) -> tuple:
    """The one move this copied file belongs to, by containment AND relative correspondence.

    A manifest of files copied somewhere else says nothing about the paths this request moves, so
    an entry that is not below a stated target - or that is below it at a different relative path
    than its source is below the stated source - is refused rather than counted. This is the
    entry's NAME against the request's names, in the conservative casefolded comparison form the
    scheduler uses everywhere, so it selects the move an entry claims to belong to. It is not an
    ownership rule: `_owned_copy` decides, with the request's actual path components and this
    platform's own path semantics, where those names lead on this filesystem.
    """
    for lane, key, source_root, target_root in roots:
        below = _relative(entry["destination"], target_root)
        if below is None:
            continue
        if below != _relative(entry["source"], source_root):
            raise FleetRefused("copy_entry_unbound", name)
        return lane, key, source_root, target_root
    raise FleetRefused("copy_entry_unbound", name)


def _link_entry(info) -> bool:
    """Whether one `lstat` result is a symlink, a Windows junction or any other reparse point."""
    reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse)


def _linked(path: Path) -> bool:
    """A symlink, a Windows junction or any other reparse point, by the rule `isolated_worker`
    already applies to its own roots: the name's own entry is inspected, never followed."""
    try:
        info = path.lstat()
    except OSError:
        return False  # unresolvable; `_actual` refuses it with the precise reason
    return _link_entry(info)


def _actual(path: Path, field: str) -> Path:
    """Where this name actually leads on this filesystem.

    `pathlib` distinguishes pure path computation from concrete resolution; only the concrete one
    answers here, and a name that is missing, unreadable or looping is refused instead of being
    assumed to live where it is spelled.
    """
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise FleetRefused("copy_entry_unresolved", field) from exc


def _actual_root(root: str, field: str) -> Path:
    """The move root as an existing directory of its own, resolved. A root that is itself a link
    would lend its whole subtree to unrelated storage, so it is refused rather than followed."""
    if _linked(Path(root)):
        raise FleetRefused("copy_entry_link_refused", field)
    actual = _actual(Path(root), field)
    if not actual.is_dir():
        raise FleetRefused("copy_entry_unresolved", field)
    return actual


def _declared_parts(value: str, root: str, field: str) -> tuple:
    """The components this entry states below its own move root, spelled as the request spells them.

    `PurePath.relative_to` is this platform's own path rule - case sensitive on POSIX, case
    insensitive on Windows - and nothing is casefolded here. `normalize_path`/`_relative` exist for
    scheduling identity and would read a case-distinct sibling directory (`new/RT` beside `new/rt`)
    as the same directory on a case-sensitive filesystem, which is the escape the owner reproduced;
    a name that is not natively below the root it claims is refused instead.
    """
    try:
        parts = Path(value).relative_to(Path(root)).parts
    except ValueError as exc:
        raise FleetRefused("copy_entry_escaped", field) from exc
    if not parts:  # the root itself is not a copied file below it
        raise FleetRefused("copy_entry_escaped", field)
    return parts


def _own_chain(root: str, parts: tuple, field: str, *, leaf_absent: bool) -> None:
    """Every stated component below this move root must be the root's own real directory entry.

    Each name is inspected with `lstat` and never followed, so a symlink, junction or other reparse
    point ANYWHERE below the root - intermediate directory or leaf, source side or destination side
    - is refused as a redirection rather than resolved for ownership credit. That holds even when it
    leads back inside the same root and even when it points at a contained file: a redirected child
    is not the file this request moves, wherever it happens to point, which is the no-child-
    redirection rule this command already states. A component that cannot be inspected at all is a
    refusal; only a destination's own leaf may be absent, and the bounded read then reports it
    unreadable.
    """
    path = Path(root)
    for index, part in enumerate(parts):
        path = path / part
        try:
            info = path.lstat()
        except OSError as exc:
            if leaf_absent and index == len(parts) - 1:
                return
            raise FleetRefused("copy_entry_unresolved", field) from exc
        if _link_entry(info):
            raise FleetRefused("copy_entry_link_refused", field)


def _owned_copy(entry: dict, source_root: str, target_root: str, name: str, resolved: dict) -> None:
    """Both ends of one manifest row must PHYSICALLY be their own root's own file at one relative path.

    Normalized absolute names do not establish containment, and the casefolded comparison form is
    not a filesystem rule at all, so the lexical binding of `_bind_entry` is not ownership evidence
    by itself. Three concrete, platform-native checks decide instead, for the source side as well as
    the destination side, because a link on either substitutes unrelated storage:

    * the stated components below the root are taken with the platform's own path rule, never
      casefolded, so a case-distinct sibling on POSIX is outside the root it claims;
    * the stated path resolves strictly - missing, unreadable or looping is a refusal, never an
      assumption that a name lives where it is spelled - and every stated component below the root
      is `lstat`-inspected, so any reparse redirection under the root is refused as one;
    * the resolved path sits below the strictly resolved root at exactly those components, and the
      two sides state the same components, so a row cannot certify a file this request never moves.

    A destination name that leads nowhere keeps its own reason (the bounded read below reports it
    unreadable), but its directory chain must still be this target's own.

    This is what the filesystem shows at the moment it is read; it does not exclude an OS-level
    concurrent mutation between this check and the read that follows.
    """
    stated: dict = {}
    for side, root in (("source", source_root), ("destination", target_root)):
        field = name + "." + side
        if root not in resolved:
            resolved[root] = _actual_root(root, field)
        parts = _declared_parts(entry[side], root, field)
        declared = Path(entry[side])
        absent = side == "destination" and not _linked(declared) and not declared.exists()
        actual = _actual(declared.parent, field) / declared.name if absent else _actual(declared, field)
        _own_chain(root, parts, field, leaf_absent=absent)
        if not actual.is_relative_to(resolved[root]) \
                or PurePath(*actual.relative_to(resolved[root]).parts) != PurePath(*parts):
            raise FleetRefused("copy_entry_escaped", field)
        stated[side] = parts
    if PurePath(*stated["source"]) != PurePath(*stated["destination"]):
        # The actual components, not their lowercased form: on a case-sensitive filesystem
        # `Artifacts/x` and `artifacts/x` are different files, so one is not the other's copy.
        raise FleetRefused("copy_entry_unbound", name + ".destination")


def verify_copy_manifest(request: dict) -> dict:
    """Re-hash the owner's copy manifest and every destination file it claims.

    The manifest document itself must hash to the digest the request states, so the request is
    bound to the exact evidence the owner verified. Every entry is then checked as a copy of a file
    this request moves: typed fields, a real non-null sha256 and byte length, an absolute resolved
    source and destination, the destination below a stated target at the same relative path its
    source is below the stated source, no destination or source named twice, both ends physically
    being their own root's own entry at exactly the components the request spelled - no reparse
    redirection anywhere below either root, and no casefolded comparison standing in for the
    platform's own path rule - and a destination that is actually read back to that digest and that
    length. A missing
    destination file reads as nothing here; it never matches a null digest, and it is a refusal.
    Every moving runtime target must be covered by at least one entry, so an unrelated manifest
    cannot certify this cutover. Nothing is copied, moved or deleted here.
    """
    declared = request["copy_manifest"]
    path = Path(declared["path"])
    observed = _hash_file(path)
    if observed is None:
        raise FleetRefused("copy_manifest_unreadable", "copy_manifest.path")
    if observed != declared["sha256"]:
        raise FleetRefused("copy_manifest_mismatch", "copy_manifest.sha256")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FleetRefused("copy_manifest_unreadable", "copy_manifest.path") from exc
    entries = document.get("entries") if isinstance(document, dict) else None
    if not (isinstance(document, dict) and document.get("schema") == COPY_MANIFEST_SCHEMA
            and isinstance(entries, list) and len(entries) == declared["entries"]):
        raise FleetRefused("copy_manifest_invalid", "copy_manifest.entries")
    roots, covered, seen, verified = _move_roots(request), set(), set(), 0
    resolved: dict = {}  # one concrete resolution per move root, reused by every entry below it
    for index, entry in enumerate(entries):
        name = "copy_manifest.entries[" + str(index) + "]"
        if not isinstance(entry, dict) or set(entry) != COPY_ENTRY_FIELDS:
            raise FleetRefused("copy_manifest_invalid", name)
        if not (type(entry["sha256"]) is str and HEX64.fullmatch(entry["sha256"])):
            raise FleetRefused("copy_manifest_invalid", name + ".sha256")
        if type(entry["bytes"]) is not int or type(entry["bytes"]) is bool \
                or not 0 <= entry["bytes"] <= MAX_COPY_BYTES:
            raise FleetRefused("copy_manifest_invalid", name + ".bytes")
        for side in ("source", "destination"):
            if not absolute_resolved(entry[side]):
                raise FleetRefused("copy_manifest_invalid", name + "." + side)
        lane, key, source_root, target_root = _bind_entry(entry, roots, name)
        for side in ("source", "destination"):
            if normalize_path(entry[side]) in seen:
                raise FleetRefused("copy_entry_duplicate", name + "." + side)
            seen.add(normalize_path(entry[side]))
        # Physical ownership before any byte is counted: a redirected name reads back the SOURCE's
        # bytes and would otherwise be credited as a verified copy.
        _owned_copy(entry, source_root, target_root, name, resolved)
        read = _hash_bounded(Path(entry["destination"]), entry["bytes"])
        if read is None:
            raise FleetRefused("copy_unreadable", name + ".destination")
        if read != {"sha256": entry["sha256"], "bytes": entry["bytes"]}:
            raise FleetRefused("copy_corrupt", name + ".destination")
        covered.add((lane, key))
        verified += 1
    missing = [(lane, key) for lane, key, _, _ in roots if key == "runtime" and (lane, key) not in covered]
    if missing:
        raise FleetRefused("copy_manifest_incomplete", "lanes[]." + missing[0][0] + ".runtime")
    return {"sha256": observed, "entries": len(entries), "verified": verified, "bound": True,
            "ownership": COPY_OWNERSHIP,
            "covered": sorted(lane + "." + key for lane, key in covered)}


def collect_relocation_proof(request: dict, config: dict, jobs: list, *, journal, state=docker_state,
                             clock=utcnow) -> dict:
    """Observe that this host is idle for a cutover and that every stated target is usable."""
    runner = runner_state(journal)
    if runner["state"] != "stopped":
        raise FleetRefused("runner_state_unknown" if runner["state"] == "unknown" else "runner_not_stopped", "runner")
    lanes = {lane["id"]: lane for lane in config["lanes"]}
    observed = []
    for move in request["moves"]:
        lane = lanes.get(move["lane"])
        if lane is None:
            raise FleetRefused("lane_unknown", "moves[]." + move["lane"])
        active = _active_runs(lane["runtime"], lane["id"], state)
        if active:
            # The cutover needs the lane quiet: a container still running owns the paths we move.
            raise FleetRefused("lane_run_active", "lanes[]." + lane["id"])
        row = {"id": lane["id"], "active_runs": active, "repository": None, "runtime": None,
               "queued_bindings": []}
        queued = [job for job in jobs if job["lane"] == lane["id"] and job["status"] == "queued"]
        repository = lane["repository"]
        if move["repository"] is not None:
            target = _resolved_directory(move["repository"]["to"], "moves[]." + lane["id"] + ".repository.to")
            repository = str(target)
            row["repository"] = {"source_identity": checkout_identity(move["repository"]["from"]),
                                 "target_identity": checkout_identity(repository),
                                 "independent": _independent(target),
                                 "prior_path_identity": repository_identity(move["repository"]["from"]),
                                 "path_identity": repository_identity(repository)}
        # Always read from the repository this lane will USE after the move: a queued job whose
        # pinned base or goal bytes are not in that checkout is never left behind by a relocation.
        row["queued_bindings"] = _queued_bindings(repository, queued)
        if move["runtime"] is not None:
            target = _resolved_directory(move["runtime"]["to"], "moves[]." + lane["id"] + ".runtime.to")
            runs = run_root(str(target))
            # A target that has never hosted an isolated run has no run root; that is reported as
            # an unknown count, never as a proven zero.
            row["runtime"] = {"writable": _writable(target), "run_root": runs.is_dir(),
                              "existing_runs": len(run_records(runs)) if runs.is_dir() else None}
        observed.append(row)
    return {"schema": RELOCATION_PROOF_SCHEMA, "runner": runner, "lanes": observed,
            "copy_manifest": verify_copy_manifest(request), "observed_at": clock()}


def _schema_provisioned(host_dsn: str, schema: str, verify=None) -> bool:
    """The lane search-path rule on the TARGET database: exactly `schema`, holding `documents`."""
    from codex_harness.adapters.fleet_runtime import lane_dsn, verify_lane_schema

    try:
        (verify or verify_lane_schema)(lane_dsn(host_dsn, schema), schema)
    except FleetRefused:
        return False
    return True


def collect_host_migration_proof(request: dict, jobs: list, *, journal, host_dsn: str,
                                 state=docker_state, verify_schema=None, clock=utcnow) -> dict:
    """Observe on the TARGET host that a whole-fleet host migration may bind these lanes.

    Nothing on the source host is read: the source repository is identified by the request's
    root-commit identity, and every check runs against the stated targets.
    """
    runner = runner_state(journal)
    if runner["state"] != "stopped":
        raise FleetRefused("runner_state_unknown" if runner["state"] == "unknown" else "runner_not_stopped", "runner")
    observed = []
    for move in request["lanes"]:
        name = "lanes[]." + move["lane"]
        repository = _resolved_directory(move["repository"]["to"], name + ".repository.to")
        runtime = _resolved_directory(move["runtime"]["to"], name + ".runtime.to")
        queued = [job for job in jobs if job["lane"] == move["lane"] and job["status"] == "queued"]
        observed.append({
            "id": move["lane"],
            "active_runs": _active_runs(str(runtime), move["lane"], state),
            "repository": {"target_identity": checkout_identity(str(repository)),
                           "independent": _independent(repository),
                           "path_identity": repository_identity(str(repository))},
            "runtime": {"writable": _writable(runtime)},
            "schema": {"name": move["schema"]["to"],
                       "provisioned": _schema_provisioned(host_dsn, move["schema"]["to"], verify_schema)},
            "queued_bindings": _queued_bindings(str(repository), queued)})
    return {"schema": HOST_MIGRATION_PROOF_SCHEMA, "runner": runner, "lanes": observed, "observed_at": clock()}


__all__ = ["LaneReader", "checkout_identity", "collect_host_migration_proof", "collect_recovery_proof", "collect_relocation_proof",
           "docker_state", "listed_runs", "run_root", "runner_state", "verify_copy_manifest"]
