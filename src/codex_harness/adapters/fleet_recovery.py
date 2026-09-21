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
and the settled machine call slot. A container name with no recorded task/run binding is refused,
unknown usage stays unknown, and an unreadable or ambiguous read is a refusal, never an absence.

`collect_relocation_proof` establishes that the fleet is idle for a cutover and that the copied
targets are usable: the service lifecycle journal (`adapters/service_entry`) must show the last
Fleet CLI run finished, every retained isolation run in a moving lane must have a container Docker
proves is not running, each target must be a real independent checkout of the same repository
identity carrying every queued job's pinned base commit and goal bytes, each target runtime must be
writable, and every entry of the owner's copy manifest must hash to what was copied. The owner's
own idle claim is never read as a fact; where the platform cannot establish one, the answer is a
bounded refusal instead of an assumption.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.adapters.call_budget import CallBudget
from codex_harness.adapters.isolated_worker import LIMITS, RESOLVED, _docker, run_records
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.application.operation_finalization import _lease_live as lease_live
from codex_harness.application.operation_finalization import owner as operation_owner
from codex_harness.domain.fleet import FleetRefused, repository_identity
from codex_harness.domain.fleet_recovery import (
    CLOSED_INVOCATIONS,
    COPY_MANIFEST_SCHEMA,
    PROOF_SCHEMA,
    RELOCATION_PROOF_SCHEMA,
    STOPPED_STATES,
)
from codex_harness.domain.model import digest, utcnow

# Where `bootstrap.isolated_worker` puts the retained run records of one runtime root.
RUN_ROOT = ("isolated-worker", "runs")
COPY_ENTRY_FIELDS = {"source", "destination", "sha256", "bytes"}
READ_BYTES = 1 << 20
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
    slot = _machine_slot(evidence, budget)
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


def _machine_slot(evidence: dict, budget) -> dict:
    ledger = CallBudget() if budget is None else budget
    rows = [row for row in ledger.slots() if row.get("id") == evidence["machine_slot"]["id"]]
    if len(rows) != 1:
        raise FleetRefused("machine_slot_unknown", "machine_slot.id")
    row = rows[0]
    if row.get("unreadable"):
        raise FleetRefused("machine_slot_unreadable", "machine_slot.id")
    return {"id": row["id"], "status": row.get("status"), "outcome": row.get("outcome")}


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


def _active_runs(runtime: str, lane_id: str, state) -> int:
    """Retained isolation runs of this lane whose container is not proven stopped or absent."""
    active = 0
    for row in run_records(run_root(runtime)):
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


def verify_copy_manifest(request: dict) -> dict:
    """Re-hash the owner's copy manifest and every destination file it claims.

    The manifest document itself must hash to the digest the request states, so the request is
    bound to the exact evidence the owner verified; every destination file is then read and
    compared. Nothing is copied, moved or deleted here.
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
    verified = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != COPY_ENTRY_FIELDS:
            raise FleetRefused("copy_manifest_invalid", "copy_manifest.entries")
        if _hash_file(Path(entry["destination"])) == entry["sha256"]:
            verified += 1
    if verified != len(entries):
        raise FleetRefused("copy_corrupt", "copy_manifest.entries")
    return {"sha256": observed, "entries": len(entries), "verified": verified}


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
            row["runtime"] = {"writable": _writable(target),
                              "existing_runs": len(run_records(run_root(str(target))))}
        observed.append(row)
    return {"schema": RELOCATION_PROOF_SCHEMA, "runner": runner, "lanes": observed,
            "copy_manifest": verify_copy_manifest(request), "observed_at": clock()}


__all__ = ["LaneReader", "checkout_identity", "collect_recovery_proof", "collect_relocation_proof",
           "docker_state", "run_root", "runner_state", "verify_copy_manifest"]
