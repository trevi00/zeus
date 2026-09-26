"""The owned-attempt verification port of host delivery (INV-HOST-DELIVERY-VERIFY-001).

`HostDelivery._verify` drives the EXISTING incumbent evaluator (`ReleaseRunner.evaluate`) through
this port. The evaluation is an external effect - review workspaces, a compose stack, an image
build, two containers and host child processes - so every evaluation is one exactly owned attempt:

* its identity (`attempt_id`) and the resources derived from it are fixed before anything starts:
  compose project `zeus-verify-<id>`, containers `zeus-release-start-<id>` and
  `zeus-release-canary-<id>` with the `zeus.isolated.run=<id>` / `zeus.isolated.role=<role>` labels
  (`deployment.attempt_resources`, the names `OwnedContainer` computes), and the owner process
  `{pid, start_ticks, boot_id, cgroup}` read from `/proc`;
* the store records it first (the caller, in its owned transaction), then this port writes
  `<root>/attempts/<id>/run.json` through the existing atomic `_write_record`, and every host child
  the evaluation creates is appended to that record the moment it exists (`observe_spawns`);
* before ANY later evaluation, and before a verified delivery may leave `verifying`, every
  unresolved attempt is reconciled EXACTLY: an owner still alive blocks; each container is looked up
  by exact name AND label and only a successful listing with zero rows is absence (one row is
  stopped, removed and listed again; ambiguity or a Docker error is unknown); the compose project is
  taken down through its own directory and then listed by its exact project label; a host child
  group is killed only while its recorded leader is provably the same process (pid AND start time),
  a group whose leader is gone but which still has members is an unclassified survivor and stays
  debt, and a dead owner's recorded cgroup must be empty of everything but this process. Nothing
  is ever selected by a prefix, an age or another attempt's id, and `collect_stale` is not called.

Signal, lease and store semantics (A1.4): the first SIGTERM/SIGINT during an evaluation raises
`EvaluationCancelled` once in the main thread (`CancellationBoundary`), so the existing primitives
kill their owned process groups and exit their stacks; later signals only set the stop flag. The
fence between checks is the queue heartbeat observed within `FENCE_SECONDS` in a helper thread: a
lost lease is `FenceLost`, and an error OR an observation that did not complete in time is
`FenceUnobservable` - a blocked store call is never assumed to time out by itself. Cleanup never
needs the store. A SIGKILL, an OOM kill or a power loss leaves the durable records for the next
owner's reconcile; correctness never depends on finishing inside the unit's stop window.
"""
from __future__ import annotations

import json
import os
import signal
import threading
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.commands import _group_gone, observe_spawns
from codex_harness.adapters.deployment import ATTEMPT_ID, RETRY_OBSERVATION, attempt_resources
from codex_harness.adapters.isolated_worker import (
    CONTAINER_ID,
    LABEL,
    LIMITS,
    OwnedContainer,
    _docker,
    _write_record,
)
from codex_harness.adapters.verification import VerificationServices
from codex_harness.application.tickets import TicketSuperseded
from codex_harness.domain.model import ContractError, canonical, utcnow

# How long one fence observation (the queue heartbeat) may take before its completion is treated as
# unobserved. `PostgresStore` bounds connect (5 s) and lock waits (`lock_timeout` 10 s); this bound
# also covers a call that neither returns nor fails, which no store setting alone bounds.
FENCE_SECONDS = 30
ATTEMPTS_DIR = "attempts"
RECORD_FILE = "run.json"
COMPOSE_LABEL = "com.docker.compose.project"


class EvaluationCancelled(KeyboardInterrupt):
    """The owner asked this controller to stop while an evaluation was running (raised once)."""


class FenceLost(Exception):
    """The release fence refused this controller between checks: it records nothing."""


class FenceUnobservable(Exception):
    """The fence could not be observed within its bound: nothing is committed, cleanup still runs."""


class CancellationBoundary:
    """The one place a stop signal may interrupt an evaluation: active only around it, once."""

    def __init__(self):
        self.active = self.raised = self.requested = False

    def enter(self) -> None:
        self.active, self.raised = True, False
        if self.requested:
            # A stop that arrived before the evaluation began: it does not begin.
            self.raised = True
            raise EvaluationCancelled()

    def leave(self) -> None:
        self.active = False

    def reset(self) -> None:
        """A new run loop starts with no stop requested."""
        self.active = self.raised = self.requested = False

    def signal(self) -> None:
        """Called by the loop's handler after it sets its own flag; raises at most once."""
        self.requested = True
        if self.active and not self.raised and threading.current_thread() is threading.main_thread():
            self.raised = True
            raise EvaluationCancelled()


def bounded_fence(heartbeat, seconds: float = FENCE_SECONDS):
    """The evaluator's fence: `heartbeat` observed within `seconds`, or treated as unobserved."""
    def fence():
        box = {}

        def observe():
            try:
                heartbeat()
                box["done"] = True
            except BaseException as exc:  # handed to the evaluating thread below
                box["error"] = exc

        thread = threading.Thread(target=observe, name="zeus-verification-fence", daemon=True)
        thread.start()
        thread.join(seconds)
        if thread.is_alive():
            raise FenceUnobservable("fence observation did not complete within its bound")
        error = box.get("error")
        if isinstance(error, ContractError):
            raise FenceLost(type(error).__name__) from error
        if error is not None:
            raise FenceUnobservable(type(error).__name__) from error
    return fence


class HostFacts:
    """What `/proc` and the cgroup v2 tree say about processes; every unreadable fact is None."""

    def __init__(self, proc="/proc", cgroup_root="/sys/fs/cgroup"):
        self.proc, self.cgroup_root = Path(proc), Path(cgroup_root)

    def boot_id(self):
        try:
            return (self.proc / "sys" / "kernel" / "random" / "boot_id").read_text("ascii").strip() or None
        except OSError:
            return None

    def start_ticks(self, pid):
        """Field 22 of `/proc/<pid>/stat`: the start time that makes a pid a process identity."""
        try:
            text = (self.proc / str(pid) / "stat").read_text("utf-8", errors="replace")
            return int(text[text.rindex(")") + 1:].split()[19])
        except (OSError, ValueError, IndexError):
            return None

    def cgroup(self, pid="self"):
        try:
            lines = (self.proc / str(pid) / "cgroup").read_text("utf-8").splitlines()
        except OSError:
            return None
        paths = [line[3:] for line in lines if line.startswith("0::")]
        return paths[0] if len(paths) == 1 and paths[0].startswith("/") else None

    def members(self, cgroup):
        """The pids of one cgroup: [] when it no longer exists, None when it cannot be read."""
        if not (isinstance(cgroup, str) and cgroup.startswith("/") and ".." not in cgroup.split("/")):
            return None
        directory = self.cgroup_root / cgroup.lstrip("/")
        if not directory.exists():
            return []
        try:
            return [int(value) for value in (directory / "cgroup.procs").read_text("ascii").split()]
        except (OSError, ValueError):
            return None

    def owner(self):
        pid = os.getpid()
        owner = {"pid": pid, "start_ticks": self.start_ticks(pid), "boot_id": self.boot_id(),
                 "cgroup": self.cgroup()}
        return owner if owner["start_ticks"] is not None and owner["boot_id"] else None


class ReleaseVerifier:
    """The port `HostDelivery` drives; see the module docstring for the ownership rules.

    `runner` builds the existing `ReleaseRunner` around a given fence. `artifacts` is a factory, so
    no directory is created until an attempt actually runs.
    """

    def __init__(self, runner, *, root, artifacts, docker: str = "docker", facts=None,
                 fence_seconds: float = FENCE_SECONDS, boundary=None):
        self.runner, self.root, self._artifacts = runner, Path(root), artifacts
        self.docker, self.facts = docker, facts or HostFacts()
        self.fence_seconds, self.boundary = fence_seconds, boundary or CancellationBoundary()
        self._artifact_store = None
        self._lock = threading.Lock()

    # ----- identity -----------------------------------------------------------------------------
    @property
    def artifacts(self):
        if self._artifact_store is None:
            self._artifact_store = self._artifacts()
        return self._artifact_store

    def available(self) -> bool:
        """Only where an owned cancellation boundary and process identity exist (A1.4)."""
        return (os.name == "posix" and threading.current_thread() is threading.main_thread()
                and self.facts.owner() is not None)

    def new_attempt(self, *, plan_id: str, release_id: str, generation) -> dict:
        owner = self.facts.owner()
        if owner is None:
            raise FenceUnobservable("owner identity unavailable")
        return {"attempt_id": uuid4().hex, "plan_id": plan_id, "release_id": release_id,
                "generation": generation, "owner": owner, "started_at": utcnow()}

    def _path(self, attempt_id: str) -> Path:
        return self.root / ATTEMPTS_DIR / attempt_id / RECORD_FILE

    def prepare(self, attempt: dict) -> dict:
        """A1.2 step 2: the disk record, lifecycle `prepared`, before any effect."""
        path = self._path(attempt["attempt_id"])
        path.parent.mkdir(parents=True, exist_ok=False)
        record = {**{key: attempt[key] for key in ("attempt_id", "plan_id", "release_id", "generation",
                                                   "owner", "started_at")},
                  "resources": attempt_resources(attempt["attempt_id"]), "children": [],
                  "lifecycle": [], "state": None, "cleanup": None, "record": str(path)}
        self._step(record, "prepared")
        return record

    def _step(self, record: dict, state: str, **detail) -> dict:
        # The path is derived from the validated attempt id, never taken from a record's own
        # content, and every write of one record is serialized with the spawn recorder.
        with self._lock:
            record["lifecycle"].append({"state": state, "at": utcnow(), **detail})
            record["state"] = state
            return _write_record(self._path(record["attempt_id"]), record)

    def _load(self, attempt_id: str) -> dict:
        return json.loads(self._path(attempt_id).read_text("utf-8"))

    # ----- one owned evaluation --------------------------------------------------------------------
    def evaluate(self, release_id: str, attempt: dict, *, fence) -> dict:
        """Run the evaluator for this attempt; ALWAYS reconcile its own resources afterwards.

        Returns the outcome with the attempt's own cleanup (`confirmed` or `unconfirmed`); every
        exception of the evaluation is classified here, never propagated as a store write.
        """
        record = self._load(attempt["attempt_id"])
        outcome, state = {"verdict": "retry", "reason_code": RETRY_OBSERVATION}, "failed"
        try:
            with observe_spawns(lambda pid: self._spawned(record, pid)):
                self._step(record, "started")
                try:
                    try:
                        self.boundary.enter()
                        runner = self.runner(bounded_fence(fence, self.fence_seconds))
                        result = runner.evaluate(release_id, attempt=attempt["attempt_id"])
                    finally:
                        self.boundary.leave()
                    outcome, state = self._checked(result), "evaluated"
                except FenceLost:
                    outcome, state = {"verdict": "fence_lost"}, "interrupted"
                except FenceUnobservable:
                    outcome, state = {"verdict": "fence_unobservable"}, "interrupted"
                except TicketSuperseded as exc:
                    outcome, state = {"verdict": "superseded", "reason": str(exc)[:200]}, "evaluated"
                except ContractError as exc:
                    outcome, state = {"verdict": "refused", "error_type": type(exc).__name__}, "evaluated"
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    outcome = {"verdict": "retry", "reason_code": RETRY_OBSERVATION,
                               "error_type": type(exc).__name__}
        except KeyboardInterrupt:
            # EvaluationCancelled, or ProcessCancelled after a logged child was reclaimed.
            outcome, state = {"verdict": "interrupted", "reason_code": "verification_interrupted"}, "interrupted"
        finally:
            self.boundary.leave()
        evaluation = self._evaluation_receipt(record, outcome)
        try:
            self._step(record, state, verdict=outcome["verdict"], evaluation=evaluation)
        except OSError:
            pass  # the cleanup below still decides; an unwritable record stays unresolved
        cleanup = self._close(record, self_owned=True)
        return {**outcome, "state": state, "evaluation": evaluation, "cleanup": cleanup}

    @staticmethod
    def _checked(result: dict) -> dict:
        if result.get("verdict") == "retry":
            return {"verdict": "retry", "reason_code": result.get("reason_code") or RETRY_OBSERVATION,
                    "evidence": result.get("evidence")}
        return {"verdict": "checked", "passed": bool(result.get("passed")), "checks": result["checks"],
                "image": result.get("image"), "receipt": result.get("receipt")}

    def _evaluation_receipt(self, record: dict, outcome: dict):
        try:
            body = {"attempt_id": record["attempt_id"], "release_id": record["release_id"],
                    "verdict": outcome.get("verdict"), "reason_code": outcome.get("reason_code"),
                    "passed": outcome.get("passed"), "image": outcome.get("image"),
                    "checks": {name: {"passed": check.get("passed"), "evidence": check.get("evidence"),
                                      "skipped": bool(check.get("skipped"))}
                               for name, check in (outcome.get("checks") or {}).items()},
                    "receipt": outcome.get("receipt")}
            return self.artifacts.put(canonical(body), "verification-attempt")["ref"]
        except Exception:
            return None

    def _spawned(self, record: dict, pid: int) -> None:
        """Every host child of this attempt, durably, the moment it exists (final review C1)."""
        with self._lock:
            record["children"].append({"pid": pid, "pgid": pid, "start_ticks": self.facts.start_ticks(pid)})
            _write_record(self._path(record["attempt_id"]), record)

    # ----- reconciliation --------------------------------------------------------------------------
    def reconcile(self, open_attempts: list) -> dict:
        """A1.3 over EVERY unresolved attempt record under this root plus every store attempt
        without a resolving cleanup. Returns `clear`, `owner_alive` or `cleanup_unconfirmed` and the
        cleanups that close store attempts."""
        wanted = {row["attempt_id"]: row for row in open_attempts if isinstance(row.get("attempt_id"), str)}
        resolved, states, seen = {}, [], set()
        directory = self.root / ATTEMPTS_DIR
        for path in sorted(directory.glob("*/" + RECORD_FILE)) if directory.is_dir() else []:
            attempt_id = path.parent.name
            seen.add(attempt_id)
            try:
                record = json.loads(path.read_text("utf-8"))
                if record.get("attempt_id") != attempt_id or not ATTEMPT_ID.fullmatch(attempt_id):
                    raise ValueError("record identity")
            except (OSError, ValueError):
                states.append("unknown")  # an unreadable record counts, exactly as unresolved_runs
                continue
            if record.get("state") == "resolved":
                if attempt_id in wanted:
                    resolved[attempt_id] = record.get("cleanup")
                continue
            state, cleanup = self._reconcile_record(record)
            states.append(state)
            if state == "confirmed" and attempt_id in wanted:
                resolved[attempt_id] = cleanup
        for attempt_id, attempt in wanted.items():
            if attempt_id in seen:
                continue
            state, cleanup = self._reconcile_absent(attempt)
            states.append(state)
            if state == "confirmed":
                resolved[attempt_id] = cleanup
        if "owner_alive" in states:
            return {"state": "owner_alive", "reason_code": "verification_owner_alive", "resolved": resolved}
        if "unknown" in states:
            return {"state": "cleanup_unconfirmed", "reason_code": "verification_cleanup_unconfirmed",
                    "resolved": resolved}
        return {"state": "clear", "reason_code": None, "resolved": resolved}

    def _owner(self, owner) -> str:
        """`self`, `alive` (another live process), `dead`, or `unknown`."""
        if not isinstance(owner, dict) or not isinstance(owner.get("pid"), int):
            return "unknown"
        boot = self.facts.boot_id()
        if boot is None:
            return "unknown"
        if owner.get("boot_id") != boot:
            return "dead"  # another boot: nothing it started is still running
        ticks = self.facts.start_ticks(owner["pid"])
        if ticks is None or ticks != owner.get("start_ticks"):
            return "dead"
        mine = self.facts.owner()
        if mine is not None and mine["pid"] == owner["pid"] and mine["start_ticks"] == ticks:
            return "self"
        return "alive"

    def _reconcile_record(self, record: dict):
        owner = self._owner(record.get("owner"))
        if owner == "alive":
            return "owner_alive", None
        if owner == "unknown":
            return "unknown", None
        cleanup = self._close(record, self_owned=owner == "self")
        return ("confirmed" if cleanup["state"] == "confirmed" else "unknown"), cleanup

    def _reconcile_absent(self, attempt: dict):
        """A store attempt with no disk record: unresolved until exact absence is proven."""
        attempt_id = attempt["attempt_id"]
        if not ATTEMPT_ID.fullmatch(attempt_id):
            return "unknown", None
        owner = self._owner(attempt.get("owner"))
        if owner == "alive":
            return "owner_alive", None
        if owner == "unknown":
            return "unknown", None
        path = self._path(attempt_id)
        record = {"attempt_id": attempt_id, "plan_id": attempt.get("plan_id"),
                  "release_id": attempt.get("release_id"), "generation": attempt.get("generation"),
                  "owner": attempt.get("owner"), "started_at": attempt.get("started_at"),
                  "resources": attempt_resources(attempt_id), "children": [], "lifecycle": [],
                  "state": None, "cleanup": None, "record": str(path), "disk_record": "absent"}
        observation = self._observe(record, self_owned=owner == "self")
        if not observation["confirmed"]:
            return "unknown", None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            cleanup = self._resolve(record, observation, "never_started")
        except OSError:
            return "unknown", None
        return "confirmed", cleanup

    def _close(self, record: dict, *, self_owned: bool) -> dict:
        """A1.3 steps 2-5 for one attempt; the record says what was proven either way."""
        observation = self._observe(record, self_owned=self_owned)
        try:
            if observation["confirmed"]:
                self._step(record, "cleanup_confirmed")
                return self._resolve(record, observation, "confirmed")
            receipt = self._receipt(record, observation)
            if record.get("state") != "cleanup_unconfirmed":
                self._step(record, "cleanup_unconfirmed", receipt=receipt)
            return {"state": "unconfirmed", "receipt": receipt}
        except OSError:
            return {"state": "unconfirmed", "receipt": None}

    def _resolve(self, record: dict, observation: dict, state: str) -> dict:
        receipt = self._receipt(record, observation)
        cleanup = {"state": state, "receipt": receipt}
        record["cleanup"] = cleanup
        written = self._step(record, "resolved", receipt=receipt)
        return {**cleanup, "record_sha256": written["sha256"]}

    def _receipt(self, record: dict, observation: dict):
        try:
            return self.artifacts.put(canonical({"attempt_id": record["attempt_id"],
                                                 "observation": observation}),
                                      "verification-attempt-cleanup")["ref"]
        except Exception:
            return None

    def _observe(self, record: dict, *, self_owned: bool) -> dict:
        resources = attempt_resources(record["attempt_id"])
        containers = {role: self._container_gone(record["attempt_id"], role)
                      for role in resources["containers"]}
        compose = self._compose_gone(resources["project"])
        processes = self._processes_gone(record, self_owned=self_owned)
        parts = [*containers.values(), compose, processes]
        return {"confirmed": all(part["state"] == "confirmed" for part in parts),
                "containers": containers, "compose": compose, "processes": processes}

    def _listing(self, filters: list) -> dict:
        """One ownership-qualified listing: zero rows, one exact id, ambiguous, or an error."""
        listed = _docker(self.docker, ["ps", "-a", "--no-trunc", *filters, "--format", "{{.ID}}"],
                         timeout=LIMITS["docker_command_seconds"])
        if listed.returncode != 0:
            return {"state": "error", "ids": []}
        ids = listed.stdout.split()
        if not ids:
            return {"state": "absent", "ids": []}
        if len(ids) == 1 and CONTAINER_ID.fullmatch(ids[0]):
            return {"state": "one", "ids": ids}
        return {"state": "ambiguous", "ids": ids}

    def _container_gone(self, attempt_id: str, role: str) -> dict:
        container = OwnedContainer({"limits": LIMITS, "image": None}, self.docker, attempt_id, role)
        exact = ["--filter", "name=^/" + container.name + "$", "--filter", "label=" + LABEL + "=" + attempt_id]
        first = self._listing(exact)
        if first["state"] == "absent":
            return {"state": "confirmed", "name": container.name, "found": 0}
        if first["state"] != "one":
            return {"state": "unknown", "name": container.name, "listing": first["state"]}
        container.id = first["ids"][0]
        stop = container.stop(LIMITS["cleanup_seconds"])
        removal = container.remove()
        again = self._listing(exact)
        return {"state": "confirmed" if again["state"] == "absent" else "unknown", "name": container.name,
                "found": 1, "stop": {key: stop.get(key) for key in ("confirmed", "killed", "status")},
                "removed": removal.get("removed"), "listing": again["state"]}

    def _compose_gone(self, project: str) -> dict:
        directory = self.root / project
        down = None
        if directory.is_dir() and not directory.is_symlink():
            services = VerificationServices(self.root, self.artifacts, project=project)
            down = services._cleanup_observed() or {"status": "services_removed"}
        listed = self._listing(["--filter", "label=" + COMPOSE_LABEL + "=" + project])
        return {"state": "confirmed" if listed["state"] == "absent" else "unknown", "project": project,
                "down": None if down is None else down.get("status"), "listing": listed["state"],
                "directory_left": directory.exists()}

    def _processes_gone(self, record: dict, *, self_owned: bool) -> dict:
        owner = record.get("owner") or {}
        if owner.get("boot_id") != self.facts.boot_id():
            return {"state": "confirmed", "reason": "owner_boot_ended"}
        groups = [self._reclaim(child) for child in record.get("children") or []]
        result = {"groups": groups}
        confirmed = all(group["state"] == "confirmed" for group in groups)
        if not self_owned:
            # A dead owner may have created a child it had no time to record: its own cgroup must
            # hold nothing but this process. Nothing found there is killed (final review C1).
            members = self.facts.members(owner.get("cgroup"))
            others = None if members is None else [pid for pid in members if pid != os.getpid()]
            result["cgroup"] = "unreadable" if others is None else len(others)
            confirmed = confirmed and others == []
        return {"state": "confirmed" if confirmed else "unknown", **result}

    def _reclaim(self, child: dict) -> dict:
        """Kill a recorded child group only while its leader is provably that exact child."""
        pgid = child.get("pgid")
        if not isinstance(pgid, int) or pgid <= 1:
            return {"state": "unknown", "reason": "group_unrecorded"}
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return {"state": "confirmed", "pgid": pgid}
        except PermissionError:
            return {"state": "unknown", "pgid": pgid, "reason": "not_ours"}
        ticks = self.facts.start_ticks(child.get("pid"))
        if child.get("start_ticks") is None or ticks != child.get("start_ticks"):
            return {"state": "unknown", "pgid": pgid, "reason": "unclassified_survivor"}
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return {"state": "confirmed", "pgid": pgid, "killed": False}
        except PermissionError:
            return {"state": "unknown", "pgid": pgid, "reason": "not_ours"}
        gone = _group_gone(pgid)
        return {"state": "confirmed" if gone else "unknown", "pgid": pgid, "killed": True}


__all__ = ["ATTEMPTS_DIR", "FENCE_SECONDS", "CancellationBoundary", "EvaluationCancelled", "FenceLost",
           "FenceUnobservable", "HostFacts", "ReleaseVerifier", "bounded_fence"]
