"""Host-side ports for the durable delivery controller (INV-HOST-DELIVERY-001).

Four concrete things live here and nothing else decides policy:

* `load_plan` reads the owner-approved plan through the existing `GitSource` at an explicit commit
  and through the same bounded blob reader the approved backlog uses. The working tree is never
  read: editing a checked-out file changes nothing until it is committed and named in the plan.
* `GitHubDelivery` publishes and merges through the EXISTING `GitWorkspace` contracts (its target
  check, its tree and patch re-derivation, its `--match-head-commit` merge) and observes the real
  checks of the exact PR head with `gh`. Nothing here parses a check's output; a required check is
  a pass only when the provider says it finished successfully for that head.
* `ProcessHostTarget` and `ScheduledTaskHostTarget` own the immutable descriptor file, the drain
  and the service process of one target. They share the whole lifecycle exactly: descriptor
  replacement, pause, stop, cleanup, launch and the state that identifies the launched instance all
  run under ONE guard per target (`HostTargetBase.guard`), which proves ownership before the first
  mutation and reconciles what is actually on the target before it touches anything. Two
  controllers therefore cannot interleave their operations on one service, and unrelated targets
  never wait for each other. Inside that guard the instance that is really there is classified
  against the authority the coordinator passes in (`replaces`), never against whatever receipt
  happens to lie on the target: only the intended instance is recognized, only the named
  predecessor or this delivery's own interrupted instance is replaced, and anything foreign,
  contradictory or unidentified refuses before the stop and the cleanup.
* `CANARIES` maps the incumbent fixed check ids to real checks. A plan names one of them by id; no
  plan ever supplies a command, an argv, a path or a check body.

A launched service is bound to the OWNER-REGISTERED runtime root of its target: it is started with
that root as its working directory and with that root's `src` ahead of everything else on
`PYTHONPATH`, so the code it imports is the code that lives there. What it reports back about itself
is observed, never copied from the descriptor it was handed: the package directory it actually
imported, the root that package came from, the revision that root is actually at (its own checked
out `HEAD`, or the owner's `runtime.json` attestation when the root is not a checkout) and the
effective worker image and profile digest of that runtime. An idle process that merely echoes a
requested descriptor therefore cannot qualify anything.

The service process is deliberately NOT owned through `ProcessTree`. That owner's Windows boundary
is a job object with KILL_ON_JOB_CLOSE (see `adapters.background_service`), so the tree ends when
the handle closes - exactly right for a launcher that outlives its child, and exactly wrong for a
transient controller that must leave a service running behind it. The child is therefore started
with the same `commands.no_console_kwargs` policy the rest of the harness uses (hidden and in its
own group on Windows, a new session on POSIX) and is identified afterwards by its recorded pid and
by the startup receipt it writes about itself. On the current Windows host the real target is the
registered scheduled task, whose own launcher already owns its tree.

`python -m codex_harness.adapters.host_delivery service --state-dir DIR` is that launched service in
its smallest honest form: it reads the descriptor it was pointed at, reports the identity it
actually loaded, and idles. It opens no database, bus, provider or model.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import codex_harness
from codex_harness.adapters.commands import no_console_kwargs, run_process
from codex_harness.adapters.operation_cli import GitSource
from codex_harness.application.host_delivery import HostDelivery
from codex_harness.domain.host_delivery import (
    CANARY_COLLECT,
    CANARY_FLEET,
    CANARY_STARTUP,
    FAILED_OUTCOMES,
    INSTANCE_INTENDED,
    KIND_MANAGED,
    KIND_MANAGED_SYSTEMD,
    KIND_PROCESS,
    KIND_SCHEDULED_TASK,
    KIND_SYSTEMD,
    RECEIPT_SCHEMA,
    REPLACEABLE_INSTANCES,
    DeliveryRefused,
    LifecycleInterrupted,
    canary_request_matches,
    descriptor_digest,
    instance_authority,
    receipt_identity,
    validate_descriptor,
    validate_plan,
)
from codex_harness.domain.model import ContractError, require

MAX_PLAN_BYTES = 64 * 1024
MAX_STATE_BYTES = 64 * 1024
# The host setting that opts this host into actual delivery. Absent means disabled: registration,
# reconciliation and status still work, and nothing external is touched.
ENABLED_SETTING = "ZEUS_HOST_DELIVERY_ENABLED"
TRUE_VALUES = {"1", "true", "yes", "on"}

DESCRIPTOR_FILE = "descriptor.json"
# The owner's attestation of what a prepared runtime ROOT is, read from the root itself and only
# when that root is not a Git checkout. It is never written, edited or read from a plan here.
RUNTIME_FILE = "runtime.json"
RECEIPT_FILE = "startup-receipt.json"
WORK_FILE = "work.json"
STATE_FILE = "controller-state.json"
PAUSE_FILE = "pause"
STOP_FILE = "stop"
# The one lifecycle lock of a target, under its original name: it guards the descriptor
# replacement AND the pause, stop, cleanup, launch and state publication of that target's service.
LOCK_DIR = "switch.lock"
CANARY_RECEIPT_FILE = "owner-canary-receipt.json"
# The server owner's request for its actual canary of one exact published plan (aibox SPEC s14 G2).
CANARY_REQUEST_FILE = "owner-canary-request.json"

# Bounded waits for the host boundary; nothing here is unbounded and nothing sleeps under a lease.
STOP_TIMEOUT = 20.0
STOP_POLL = 0.1
LOCK_TIMEOUT = 20.0
SERVICE_MAX_SECONDS = 900


def configured_enabled(settings: dict) -> bool:
    """The host opt-in. Anything but an explicit affirmative value keeps delivery disabled."""
    value = (settings or {}).get(ENABLED_SETTING)
    return type(value) is str and value.strip().lower() in TRUE_VALUES


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, limit: int = MAX_STATE_BYTES):
    """A bounded JSON file, or None. A malformed or oversized file is None, never a guess."""
    try:
        if path.stat().st_size > limit:
            return None
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, document) -> None:
    """Atomic replace: a reader never sees a half-written descriptor, receipt or state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    temporary.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


# ----- what a runtime root actually IS ------------------------------------------------------
def _git_directory(root: Path) -> Path | None:
    """The Git directory of this root, following a worktree's `gitdir:` pointer. No git runs."""
    marker = root / ".git"
    if marker.is_dir():
        return marker
    try:
        text = marker.read_text("utf-8")
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    pointer = Path(text.split(":", 1)[1].strip())
    pointer = pointer if pointer.is_absolute() else (root / pointer)
    return pointer if pointer.is_dir() else None


def checkout_revision(root: Path) -> str | None:
    """The commit this checkout is ACTUALLY at, read from its own refs; never from a descriptor.

    Plain file reads of `HEAD`, the loose ref it names and `packed-refs` - no subprocess, no
    network and no index. A root that is not a checkout answers None rather than a guess.
    """
    directory = _git_directory(Path(root))
    if directory is None:
        return None
    try:
        head = (directory / "HEAD").read_text("utf-8").strip()
    except OSError:
        return None
    if re.fullmatch(r"[0-9a-f]{40}", head):
        return head
    if not head.startswith("ref:"):
        return None
    reference = head.split(":", 1)[1].strip()
    # A linked worktree keeps its own HEAD but shares branch refs with the main repository, named
    # by its `commondir` file; a ref is looked up there after the worktree's own directory.
    for base in _ref_directories(directory):
        try:
            loose = (base / reference).read_text("utf-8").strip()
            return loose if re.fullmatch(r"[0-9a-f]{40}", loose) else None
        except OSError:
            pass
        try:
            packed = (base / "packed-refs").read_text("utf-8")
        except OSError:
            continue
        for line in packed.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == reference and re.fullmatch(r"[0-9a-f]{40}", parts[0]):
                return parts[0]
    return None


def _ref_directories(directory: Path) -> list[Path]:
    """The Git directory itself, then its `commondir` when it has one. No git runs."""
    directories = [directory]
    try:
        common = (directory / "commondir").read_text("utf-8").strip()
    except OSError:
        return directories
    if common:
        pointer = Path(common)
        pointer = pointer if pointer.is_absolute() else directory / pointer
        if pointer.is_dir():
            directories.append(pointer)
    return directories


def runtime_revision(root) -> str | None:
    """What revision the runtime root is at: its own checkout, else the owner's attestation."""
    revision = checkout_revision(Path(root))
    if revision is not None:
        return revision
    attestation = _read_json(Path(root) / RUNTIME_FILE)
    value = attestation.get("revision") if isinstance(attestation, dict) else None
    return value if type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) else None


def effective_worker_image(config=None) -> str:
    """The worker image THIS runtime is configured with, as `adapters.isolated_worker` reads it.

    Effective configuration, not a model call: a host that configures no isolation image reports
    the explicit token `none`, which a delivery must then bind deliberately.
    """
    if config is None:
        config = _host_settings()
    value = str((config or {}).get("ZEUS_WORKER_IMAGE")
                or (config or {}).get("HARNESS_WORKER_IMAGE") or "").strip()
    return value or "none"


def effective_profile_digest() -> str | None:
    """The digest of the worker profile THIS loaded code packages; None when it cannot be loaded."""
    from codex_harness.adapters.worker_profile import load_profile
    from codex_harness.adapters.worker_profile import profile_digest as digest_of

    try:
        return digest_of(load_profile("worker-v1"))
    except Exception:
        return None


def _host_settings() -> dict:
    from codex_harness.adapters.configuration import settings

    try:
        return settings()
    except Exception:
        # A malformed host configuration is not a reason to invent one; the receipt that follows
        # simply carries no effective image and is refused rather than accepted.
        return {}


def loaded_runtime() -> dict:
    """What THIS process actually loaded: the package directory and the root it came from."""
    module_root = Path(codex_harness.__file__).resolve().parent
    # `<root>/src/codex_harness` is this repository's layout; an installed package that is not
    # under a `src` directory reports its own parent, and the comparison in the domain decides.
    root = module_root.parent.parent if module_root.parent.name == "src" else module_root.parent
    return {"module_root": str(module_root), "runtime_root": str(root)}


# ----- the owner-approved plan, read from Git ------------------------------------------------
def load_plan(source: GitSource, revision: str, path: str) -> dict:
    """The pinned plan with the identity of the exact committed bytes it was read from."""
    from codex_harness.adapters.fleet_backlog import read_blob
    from codex_harness.domain.fleet_backlog import BacklogRefused

    try:
        data = read_blob(source, revision, path, MAX_PLAN_BYTES, "plan")
    except BacklogRefused as exc:
        # The same bounded committed-bytes reader, under this component's own refusal type.
        raise DeliveryRefused(exc.reason_code, exc.field) from exc
    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise DeliveryRefused("plan_not_json") from exc
    return {"plan": validate_plan(document), "bytes": len(data),
            "pin": {"revision": revision, "path": path,
                    "sha256": hashlib.sha256(data).hexdigest()}}


# ----- GitHub ----------------------------------------------------------------------------------
def normalize_checks(rows) -> list[dict]:
    """The provider's check rollup reduced to `{name, state}` in this component's vocabulary.

    A check run that has not completed is `pending`; only an explicit successful conclusion is
    `success`; skipped, cancelled, neutral, timed out, stale, failed and everything a future
    provider version invents are `failure`, because none of them is a pass.
    """
    normalized = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("context")
        if not isinstance(name, str) or not name:
            continue
        if row.get("status") is not None or row.get("conclusion") is not None:
            status = str(row.get("status") or "").upper()
            conclusion = str(row.get("conclusion") or "").upper()
            state = ("pending" if status not in {"COMPLETED"} and not conclusion
                     else "success" if conclusion == "SUCCESS" else "failure")
        else:
            raw = str(row.get("state") or "").upper()
            state = ("success" if raw == "SUCCESS" else
                     "pending" if raw in {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS"} else "failure")
        normalized.append({"name": name, "state": state})
    return normalized


class GitHubDelivery:
    """Publication, exact-head CI observation and merge for one repository.

    Every mutation goes through the existing `GitWorkspace`, so the candidate's target repository,
    tree, patch and head binding are re-derived by their owner and never re-implemented here. The
    observation is read-only and is also what reconciles a lost response: the PR for this exact
    head either exists or it does not, and nothing is reissued before that is known.
    """

    def __init__(self, workspace, *, runner=run_process, timeout: int = 60):
        self.workspace, self.runner, self.timeout = workspace, runner, timeout

    def _repository(self) -> str:
        require(bool(self.workspace.remote), "GitHub repository must be configured")
        return self.workspace.remote

    def observe(self, candidate: dict):
        """The PR for this candidate's branch, or None. Read-only; it mutates nothing anywhere."""
        result = self.runner(["gh", "pr", "list", "--repo", self._repository(), "--head",
                              candidate["branch"], "--state", "all", "--json",
                              "number,url,headRefOid,state,mergeCommit,statusCheckRollup"],
                             timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("GitHub pull request listing unavailable")
        try:
            rows = json.loads(result.stdout or "[]")
        except ValueError as exc:
            raise RuntimeError("GitHub pull request listing unreadable") from exc
        rows = [row for row in rows if isinstance(row, dict)
                and row.get("state") in {"OPEN", "MERGED"}]
        if not rows:
            return None
        row = next((r for r in rows if r.get("headRefOid") == candidate["revision"]), rows[0])
        merge = row.get("mergeCommit") or {}
        return {"number": row.get("number"), "url": row.get("url"), "head": row.get("headRefOid"),
                "state": row.get("state"),
                "merged_revision": merge.get("oid") if isinstance(merge, dict) else None,
                "checks": normalize_checks(row.get("statusCheckRollup"))}

    def publish(self, candidate: dict) -> dict:
        """Publish through the existing workspace contract; the body carries identities only."""
        body = ("Host delivery of a reviewed release candidate.\n\n"
                "revision: " + candidate["revision"] + "\ntree: " + candidate["tree"] + "\n")
        published = self.workspace.publish(candidate, "Host delivery " + candidate["revision"][:12],
                                           body)
        return {"number": published.get("number"), "url": published.get("url"),
                "head": published.get("headRefOid") or candidate["revision"], "state": "OPEN",
                "checks": []}

    def merge(self, candidate: dict) -> dict:
        merged = self.workspace.merge(candidate)
        return {"merged": bool(merged.get("merged")),
                "merged_revision": merged.get("merged_revision") or merged.get("revision")}

    def qualify(self, candidate: dict, merged_revision) -> dict:
        """The merged revision carries the reviewed tree, through the workspace's own check.

        The coordinator calls this for a merge it performed AND for one it only observed, so a
        recovered merge can never inherit an acceptance the merged tree does not satisfy.
        """
        return self.workspace.qualify_merged(candidate, merged_revision)


# ----- host targets ----------------------------------------------------------------------------
class HostTargetBase:
    """The descriptor, receipt, drain and service-lifecycle mechanics every target kind shares.

    The descriptor is immutable: it is replaced, never edited, under this target's lifecycle guard
    and only when the descriptor that is there right now is exactly the expected predecessor.

    Switching that descriptor, stopping the old service, retiring its files, starting the new one
    and publishing the resulting state are ONE operation on one service, not five independent file
    writes, so they all run under the same guard. Everything that mutates a target goes through it;
    unrelated targets share nothing and never wait for each other.
    """

    def __init__(self, *, lock_timeout: float = LOCK_TIMEOUT):
        self.lock_timeout = lock_timeout

    @staticmethod
    def state_dir(target: dict) -> Path:
        return Path(target["state_dir"])

    @classmethod
    def path(cls, target: dict, name: str) -> Path:
        return cls.state_dir(target) / name

    # --- the shared target lifecycle guard -------------------------------------------------------
    @contextmanager
    def guard(self, target: dict, authorize=None):
        """Hold this target's lifecycle lock, and prove ownership before the first mutation.

        The lock is one directory per target, so two controllers cannot interleave their lifecycle
        operations on the same service while unrelated targets keep moving. `authorize` is the
        caller's fence check and runs INSIDE the lock, before anything has been written, stopped or
        deleted: a controller that passed its own outer check, was superseded while it waited here
        and then resumed stops nothing, deletes nothing and starts nothing.

        A lock that is already held is a conflicting change on this target: it is waited for within
        `lock_timeout` and then refused, never broken on age - an owner that crashed holding it is
        an actual recovery condition and not something a successor may decide for itself. No store
        transaction is ever open while this is held; the caller's `authorize` opens and closes its
        own short one.
        """
        lock = self.path(target, LOCK_DIR)
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise DeliveryRefused("target_lock_held", "target_id") from None
                time.sleep(STOP_POLL)
            except OSError as exc:
                raise DeliveryRefused("target_lock_unavailable", "state_dir") from exc
        try:
            if authorize is not None:
                authorize()
            yield
        finally:
            try:
                lock.rmdir()
            except OSError:
                pass

    @staticmethod
    def _still_owned(authorize, effect: str) -> None:
        """Re-check ownership after a bounded wait that can outlive a lease.

        A loss HERE is not a refusal, because the stop it follows already happened: it is raised as
        an interrupted lifecycle so the coordinator records an ambiguous effect and the next owner
        reconciles this target. Nothing after it is cleaned up or started by this controller.
        """
        if authorize is None:
            return
        try:
            authorize()
        except Exception as exc:
            raise LifecycleInterrupted(effect, exc) from exc

    # --- the immutable descriptor --------------------------------------------------------------
    def current(self, target: dict):
        document = _read_json(self.path(target, DESCRIPTOR_FILE))
        if document is None:
            return None
        try:
            return validate_descriptor(document)
        except DeliveryRefused:
            return None

    def switch(self, target: dict, descriptor: dict, *, expected, authorize=None) -> dict:
        """Atomically replace the descriptor after comparing the expected predecessor.

        Ownership is proven first, inside the guard and before the comparison, so a superseded
        controller reports the ownership it lost rather than a descriptor its successor moved.
        """
        with self.guard(target, authorize):
            current = self.current(target)
            observed = None if current is None else descriptor_digest(current)
            if observed != expected:
                raise DeliveryRefused("descriptor_changed", "expected_descriptor")
            _write_json(self.path(target, DESCRIPTOR_FILE), descriptor)
            return {"written": True, "descriptor_sha256": descriptor_digest(descriptor)}

    # --- what the launched process said about itself -------------------------------------------
    def receipt(self, target: dict):
        return _read_json(self.path(target, RECEIPT_FILE))

    def launch_record(self, target: dict):
        """The state THIS component wrote when it last launched this target, or None.

        It is written only inside the lifecycle guard, by the controller that performed the launch,
        and names that launch's descriptor, its start time and its process or service identity. It
        is the trusted evidence of what this component started - not a claim a service makes about
        itself - which is what lets a transition whose startup identity was never confirmed be
        reconciled without guessing at a live pid.
        """
        return _read_json(self.path(target, STATE_FILE))

    def _liveness(self, target: dict, receipt):
        """Whether an instance is running here, or None when that could not be observed at all."""
        try:
            return bool(self.running(target))
        except Exception:
            return None

    def observe(self, target: dict) -> dict:
        """Everything this target says about the instance on it right now. It mutates nothing.

        Presence and readability are reported separately from content: a receipt or launch file
        that exists but cannot be read is an unknown, never an absence.
        """
        receipt = self.receipt(target)
        return {"receipt": receipt, "receipt_present": self.path(target, RECEIPT_FILE).exists(),
                "launch": self.launch_record(target),
                "launch_present": self.path(target, STATE_FILE).exists(),
                "running": self._liveness(target, receipt)}

    def identity(self, target: dict) -> dict:
        """The durable identity evidence of this target, for the coordinator to capture BEFORE it
        replaces a descriptor. Read only: nothing is locked, stopped, launched or written."""
        observed = self.observe(target)
        named = receipt_identity(observed["receipt"], present=observed["receipt_present"])
        current = self.current(target)
        return {"descriptor_sha256": None if current is None else descriptor_digest(current),
                "instance_id": named["instance_id"], "receipt": named["state"],
                "launch": observed["launch"], "running": observed["running"]}

    # --- draining -------------------------------------------------------------------------------
    def drain(self, target: dict, *, authorize=None) -> dict:
        """Pause new admission and report what is still running and what is unconfirmed.

        The pause is a mutation of this target's state directory, so it happens under the same
        guard as the rest of the lifecycle: a stale controller pauses nothing, and a pause can
        never land between a successor's cleanup and its launch.

        `work.json` is the service's own report. A missing report beside a RUNNING service is not
        an empty one: it is an unconfirmed effect, because nothing observed that the service had
        finished its work.
        """
        with self.guard(target, authorize):
            _write_json(self.path(target, PAUSE_FILE + ".json"), {"paused": True, "at": _utcnow()})
            running = self.running(target)
            work = _read_json(self.path(target, WORK_FILE))
        if not running:
            return {"drained": True, "unconfirmed": 0, "running": False, "active": 0}
        if not isinstance(work, dict):
            return {"drained": False, "unconfirmed": 1, "running": True, "active": None}
        active = work.get("active")
        unconfirmed = work.get("unconfirmed")
        return {"drained": active == 0, "unconfirmed": int(unconfirmed or 0), "running": True,
                "active": active}

    def running(self, target: dict) -> bool:
        raise NotImplementedError

    def stop(self, target: dict) -> dict:
        raise NotImplementedError

    # --- the one protected service lifecycle -----------------------------------------------------
    def start(self, target: dict, descriptor: dict, *, authorize=None, replaces=None) -> dict:
        """Reconcile, classify, stop, retire, launch and publish the new state, in one guard.

        Two facts are checked, in this order and both before any effect. The descriptor on the
        target must be exactly the one being started: a foreign one refuses, because something
        other than this delivery owns the target then. Then the instance that is ACTUALLY there is
        classified against `replaces`, the durable authority the coordinator captured from its own
        transition. A live instance really running this descriptor is RECOGNIZED rather than killed
        and restarted, which is what makes a restart - forward or rollback - reconcile instead of
        churn; the authorized predecessor or this delivery's own interrupted instance may be
        replaced; a clean target may be started on positive evidence of absence; and a foreign,
        unidentified, contradictory or simply unauthorized instance refuses BEFORE the stop and
        before any receipt is removed. Not being the intended instance is never by itself
        permission to end one. Ownership is proven again after the bounded stop, which can outlive
        a lease, and never after a mutation it would have to undo.
        """
        with self.guard(target, authorize):
            context = self._prepare(target, descriptor)
            self._reconcile(target, descriptor)
            authority = instance_authority(descriptor, self.observe(target), replaces)
            if authority["state"] == INSTANCE_INTENDED:
                return {"started": False, "recovered": True,
                        "instance_id": authority["instance_id"],
                        "launch": self.launch_record(target)}
            if authority["state"] not in REPLACEABLE_INSTANCES:
                raise DeliveryRefused(authority["reason_code"], "target_id")
            # A target kind whose instances hold shared execution debt refuses here, BEFORE the
            # stop, so a live instance that still owns that debt keeps running to settle it.
            self._activation_gate(target, descriptor)
            stopped = self.stop(target)
            if not stopped["stopped"]:
                # A target kind that knows WHY it could not stop (a managed instance with active or
                # unknown work) names that; every other kind keeps the incumbent code.
                raise DeliveryRefused(stopped.get("reason_code") or "previous_instance_unconfirmed",
                                      "target_id")
            self._still_owned(authorize, "service_stopped")
            # And again after the stop, immediately before anything is retired or launched.
            self._activation_gate(target, descriptor)
            self._retire(target)
            return self._launch(target, descriptor, context)

    def _activation_gate(self, target: dict, descriptor: dict) -> None:
        """What must be settled before an instance of this kind may be activated; nothing by default."""
        return None

    def _prepare(self, target: dict, descriptor: dict):
        """Everything that must hold BEFORE anything is stopped; it mutates nothing."""
        return None

    def _reconcile(self, target: dict, descriptor: dict) -> None:
        """What is on the target right now, compared with the descriptor about to be started."""
        current = self.current(target)
        observed = None if current is None else descriptor_digest(current)
        if observed != descriptor_digest(descriptor):
            raise DeliveryRefused("descriptor_foreign", "target_id")

    def _retire(self, target: dict) -> None:
        """Retire the previous instance's own files, after it has been proven gone.

        The old receipt goes before the start, so the next consumption check cannot read the
        previous instance's evidence as the new one's.
        """
        for name in (RECEIPT_FILE, STOP_FILE + ".json", PAUSE_FILE + ".json"):
            try:
                self.path(target, name).unlink()
            except OSError:
                pass

    def _launch(self, target: dict, descriptor: dict, context) -> dict:
        raise NotImplementedError


def _reaped(pid) -> bool:
    """Collect a POSIX child of THIS process that has already exited.

    An exited child of the running process stays visible to `kill(pid, 0)` as a zombie until its
    parent collects it, so a controller that started the service in this same process would read
    its own finished child as still running and could never confirm a stop. A pid that is not this
    process's child answers `ChildProcessError` and is left to the liveness check below.
    """
    if os.name == "nt":
        return False
    try:
        collected, _ = os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        return False
    return collected == pid


def _alive(pid) -> bool:
    """Whether this pid currently exists. Pid reuse is not resolved here, which is why activation
    is decided by the startup receipt's instance id rather than by liveness."""
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
        result = run_process(["tasklist", "/FI", "PID eq " + str(pid), "/NH"], timeout=20)
        return result.returncode == 0 and str(pid) in result.stdout
    if _reaped(pid):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


class ProcessHostTarget(HostTargetBase):
    """A service this controller starts as its own detached child process.

    This is the POSIX host target and the target the tests use; it is a real process with a real
    descriptor file, a real startup receipt and a real stop path. It is deliberately not a job
    object: see the module docstring.
    """

    kind = KIND_PROCESS

    def __init__(self, *, python=None, max_seconds: int = SERVICE_MAX_SECONDS, **kwargs):
        super().__init__(**kwargs)
        self.python = python or sys.executable
        self.max_seconds = max_seconds

    def _state(self, target: dict) -> dict:
        return self.launch_record(target) or {}

    def running(self, target: dict) -> bool:
        return _alive(self._state(target).get("pid"))

    def _liveness(self, target: dict, receipt):
        """Liveness for the classification, from the recorded launch AND from the receipt's pid.

        A process that reported a startup but is not in this component's launch record is still a
        live process on this target: it is an instance to identify and refuse, never an absence to
        start over.
        """
        if self.running(target):
            return True
        pid = receipt.get("pid") if isinstance(receipt, dict) else None
        return _alive(pid)

    def stop(self, target: dict) -> dict:
        """End the recorded process within a bounded wait; an unconfirmed stop is reported as one."""
        state = self._state(target)
        pid = state.get("pid")
        _write_json(self.path(target, STOP_FILE + ".json"), {"stop": True, "at": _utcnow()})
        if not _alive(pid):
            return {"stopped": True, "was_running": False, "pid": pid}
        if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
            run_process(["taskkill", "/PID", str(pid), "/T"], timeout=20)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + STOP_TIMEOUT
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(STOP_POLL)
        return {"stopped": not _alive(pid), "was_running": True, "pid": pid}

    @staticmethod
    def runtime_environment(root: Path) -> dict:
        """Bind the child's imports to the owner-registered runtime root, and to nothing else.

        The root's `src` goes ahead of an inherited `PYTHONPATH` and the root becomes the child's
        repository, so the package it imports is the one that lives there. A root that holds no
        importable harness is refused before a process exists, rather than silently launching this
        controller's own code and calling it the delivered runtime.
        """
        if not (root / "src" / "codex_harness" / "__init__.py").is_file():
            raise DeliveryRefused("runtime_root_unavailable", "root")
        environment = dict(os.environ)
        inherited = environment.get("PYTHONPATH")
        source = str(root / "src")
        environment["PYTHONPATH"] = source + (os.pathsep + inherited if inherited else "")
        environment["ZEUS_REPOSITORY"] = environment["HARNESS_REPOSITORY"] = str(root)
        return environment

    def _prepare(self, target: dict, descriptor: dict) -> dict:
        """The registered runtime root must hold an importable harness before anything is stopped."""
        root = Path(descriptor["root"])
        return {"root": root, "environment": self.runtime_environment(root)}

    def _launch(self, target: dict, descriptor: dict, context: dict) -> dict:
        """Exactly one new process, and the recorded state that identifies it, under the guard."""
        argv = [self.python, "-m", "codex_harness.adapters.host_delivery", "service",
                "--state-dir", str(self.state_dir(target)), "--max-seconds", str(self.max_seconds)]
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, cwd=str(context["root"]),
                                   env=context["environment"],
                                   **no_console_kwargs(process_group=True))
        record = {"pid": process.pid, "started_at": _utcnow(),
                  "descriptor_sha256": descriptor_digest(descriptor)}
        _write_json(self.path(target, STATE_FILE), record)
        # The launch record goes back to the caller as it was written, under this guard: it is the
        # evidence that identifies THIS launch if its startup identity is never confirmed.
        return {"started": True, "pid": process.pid, "launch": record}


class ScheduledTaskHostTarget(HostTargetBase):
    """The current Windows host target: an already registered scheduled task.

    This adapter only starts and ends the task the owner registered under its own name; it never
    creates, deletes or reconfigures one, and no name, path or argument comes from a candidate.
    """

    kind = KIND_SCHEDULED_TASK

    def __init__(self, *, runner=run_process, timeout: int = 60, **kwargs):
        super().__init__(**kwargs)
        self.runner, self.timeout = runner, timeout

    def _query(self, target: dict) -> str:
        result = self.runner(["schtasks", "/Query", "/TN", target["service"], "/FO", "LIST"],
                             timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("Scheduled task status unavailable")
        return result.stdout or ""

    def running(self, target: dict) -> bool:
        return "Running" in self._query(target)

    def stop(self, target: dict) -> dict:
        result = self.runner(["schtasks", "/End", "/TN", target["service"]], timeout=self.timeout)
        deadline = time.monotonic() + STOP_TIMEOUT
        while self.running(target) and time.monotonic() < deadline:
            time.sleep(STOP_POLL)
        return {"stopped": not self.running(target), "exit_code": result.returncode}

    def _launch(self, target: dict, descriptor: dict, context) -> dict:
        # The task's own registration owns its launcher, its window policy and its process tree;
        # the runtime root it starts from is the owner's registration, which this never rewrites.
        result = self.runner(["schtasks", "/Run", "/TN", target["service"]], timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("Scheduled task could not be started")
        record = {"service": target["service"], "started_at": _utcnow(),
                  "descriptor_sha256": descriptor_digest(descriptor)}
        _write_json(self.path(target, STATE_FILE), record)
        return {"started": True, "service": target["service"], "launch": record}


def host_ports(*, fleet=None, systemd_control=None, **kwargs) -> dict:
    """The host adapters by target kind, as the coordinator expects them.

    The managed Fleet target is only ever USED for a target the owner registered with that kind;
    registering none keeps every existing target exactly as it was. `fleet` is its activation-gate
    authority (the host store's Fleet); without one a managed start refuses rather than assuming
    that no execution debt exists. `systemd_control` is the validated launcher control directory
    of the systemd target (`systemd_control_dir`); without one a systemd start refuses by name.
    """
    from codex_harness.adapters.host_migration import SystemdHostTarget
    from codex_harness.adapters.managed_runtime import ManagedFleetTarget, SystemdManagedFleetTarget

    return {KIND_PROCESS: ProcessHostTarget(**kwargs), KIND_SCHEDULED_TASK: ScheduledTaskHostTarget(),
            KIND_MANAGED: ManagedFleetTarget(fleet=fleet),
            # The same managed target, its guardian owned by the owner-fixed unit (aibox SPEC s14 G3).
            KIND_MANAGED_SYSTEMD: SystemdManagedFleetTarget(fleet=fleet),
            KIND_SYSTEMD: SystemdHostTarget(control=systemd_control or {"control_dir": None,
                                                                        "reason_code": "control_dir_unconfigured"})}


def systemd_control_dir(settings: dict) -> dict:
    """The launcher control directory from `ZEUS_AIBOX_ROOT` (the setting the deploy/aibox units
    set): `<root>/runtime/control`, absolute, an existing real directory, no link on the way.

    Returned as `{"control_dir", "reason_code"}` so a missing or invalid setting is reported by
    the systemd target at its first effect instead of failing every other target's construction.
    """
    value = (settings or {}).get("ZEUS_AIBOX_ROOT")
    if not (type(value) is str and value.strip()):
        return {"control_dir": None, "reason_code": "control_dir_unconfigured"}
    root = Path(value)
    control = root / "runtime" / "control"
    if not root.is_absolute() or ".." in root.parts:
        return {"control_dir": None, "reason_code": "control_dir_invalid"}
    for path in (root, root / "runtime", control):
        if path.is_symlink() or not path.is_dir():
            return {"control_dir": None, "reason_code": "control_dir_invalid"}
    return {"control_dir": str(control), "reason_code": None}


# ----- the incumbent fixed canary checks --------------------------------------------------------
# Every canary is called with the target, the descriptor this delivery switched to and `startup`:
# the OBSERVED startup evidence of the instance that reported it (its instance id, the root and
# package it actually loaded, and the revision that runtime is at). The canary decides whether that
# observed runtime may become the active one, so it binds the instance and the runtime and never
# reads the final active pointer - which this delivery has deliberately not written yet.
def startup_identity_canary(target: dict, descriptor: dict, startup: dict) -> dict:
    """The service contract of an owned process target: it is still there, still itself.

    The receipt is re-read AFTER the startup was observed and the process is checked to be alive,
    so a process that wrote a receipt and died is not an activation, and a receipt that has since
    been replaced by another instance is a stale one rather than this instance's evidence.
    """
    receipt = _read_json(HostTargetBase.path(target, RECEIPT_FILE))
    if not isinstance(receipt, dict):
        return {"passed": False, "reason_code": "canary_receipt_missing", "evidence": None}
    if receipt.get("descriptor_sha256") != descriptor_digest(descriptor):
        return {"passed": False, "reason_code": "canary_descriptor_mismatch", "evidence": None}
    if receipt.get("instance_id") != (startup or {}).get("instance_id"):
        return {"passed": False, "reason_code": "canary_instance_changed", "evidence": None}
    state = _read_json(HostTargetBase.path(target, STATE_FILE)) or {}
    pid = state.get("pid") if target.get("kind") == KIND_PROCESS else receipt.get("pid")
    if not _alive(pid):
        return {"passed": False, "reason_code": "canary_process_absent", "evidence": None}
    return {"passed": True, "reason_code": None, "evidence": receipt.get("instance_id")}


def collect_monitor_canary(target: dict, descriptor: dict, startup: dict, *, store=None) -> dict:
    """The service contract of the collect target: a FRESH read-only monitor source shows exactly
    this runtime as the instance that started on this target.

    It is the incumbent collector's own projection that answers, and it answers about the OBSERVED
    startup, not about the active pointer: the descriptor this source reports must be the one that
    was switched to, its startup must have been observed, and the instance it names must be the
    instance whose receipt this delivery accepted. A snapshot taken before the switch names another
    descriptor or another instance and is refused, and a source that cannot be read at all is
    unavailable rather than a pass.
    """
    if store is None:
        return {"passed": False, "reason_code": "canary_store_unavailable", "evidence": None}
    from codex_harness.adapters.monitoring import host_delivery_facts

    try:
        facts = host_delivery_facts(store)
    except Exception as exc:
        return {"passed": False, "reason_code": "canary_source_unavailable", "evidence": None,
                "error_type": type(exc).__name__}
    row = next((entry for entry in facts.get("targets", [])
                if entry.get("target_id") == target["target_id"]), None)
    if row is None:
        return {"passed": False, "reason_code": "canary_target_unobserved", "evidence": None}
    if row.get("descriptor_sha256") != descriptor_digest(descriptor) or not row.get("startup_observed"):
        return {"passed": False, "reason_code": "canary_descriptor_not_observed", "evidence": None}
    instance = (startup or {}).get("instance_id")
    if not instance or row.get("observed_instance_id") != instance:
        return {"passed": False, "reason_code": "canary_instance_not_observed", "evidence": None}
    if row.get("observed_revision") != descriptor["revision"]:
        return {"passed": False, "reason_code": "canary_runtime_not_observed", "evidence": None}
    return {"passed": True, "reason_code": None, "evidence": row.get("observed_instance_id")}


def owner_qualified_canary(target: dict, descriptor: dict, startup: dict) -> dict:
    """A real qualified worker operation is OWNER acceptance work, not something a controller runs.

    This check therefore looks for the owner's own receipt for exactly this descriptor, and for the
    instance it was taken against when the owner recorded one. No model, provider or worker is
    started from here, and an absent receipt is an honest not-passed.
    """
    receipt = _read_json(HostTargetBase.path(target, CANARY_RECEIPT_FILE))
    if not isinstance(receipt, dict):
        if canary_request_matches(_read_json(HostTargetBase.path(target, CANARY_REQUEST_FILE)), target, descriptor):
            # The owner is running its actual canary of exactly this delivery: not passed, and pending
            # only until the delivery's own consumption deadline (`HostDelivery._consume`).
            return {"passed": False, "pending": True, "reason_code": "canary_owner_receipt_pending",
                    "evidence": None}
        return {"passed": False, "reason_code": "canary_owner_receipt_missing", "evidence": None}
    if receipt.get("descriptor_sha256") != descriptor_digest(descriptor):
        return {"passed": False, "reason_code": "canary_owner_receipt_stale", "evidence": None}
    if receipt.get("instance_id") is not None \
            and receipt.get("instance_id") != (startup or {}).get("instance_id"):
        return {"passed": False, "reason_code": "canary_owner_receipt_stale", "evidence": None}
    return {"passed": bool(receipt.get("passed")), "evidence": receipt.get("evidence"),
            "reason_code": None if receipt.get("passed") else "canary_owner_receipt_failed"}


def canary_checks(store=None) -> dict:
    """The fixed check id -> check map. A plan selects one by id and supplies nothing else."""
    return {CANARY_STARTUP: startup_identity_canary,
            CANARY_COLLECT: lambda target, descriptor, startup: collect_monitor_canary(
                target, descriptor, startup, store=store),
            CANARY_FLEET: owner_qualified_canary}


# ----- the launched service ----------------------------------------------------------------------
def startup_receipt(descriptor: dict) -> dict:
    """What a launched process reports about ITSELF: its instance, its process and what it loaded.

    Only the target and the descriptor digest say which descriptor was read. The runtime identity -
    the root, the package directory, the revision that root is at, and the effective worker image
    and profile digest of this runtime - is OBSERVED here, so a process launched from an old
    runtime reports the old runtime and is refused instead of echoing what it was handed.
    """
    loaded = loaded_runtime()
    return {"schema": RECEIPT_SCHEMA, "target_id": descriptor["target_id"],
            "instance_id": uuid.uuid4().hex, "pid": os.getpid(), "started_at": _utcnow(),
            "runtime_root": loaded["runtime_root"], "module_root": loaded["module_root"],
            "descriptor_sha256": descriptor_digest(descriptor),
            "revision": runtime_revision(loaded["runtime_root"]) or "",
            "worker_image": effective_worker_image(),
            "profile_digest": effective_profile_digest() or ""}


def serve(state_dir: str, max_seconds: int = SERVICE_MAX_SECONDS) -> int:
    """The smallest honest service: load the descriptor, report the identity, idle, exit.

    It reports the identity it ACTUALLY loaded, not the one it was told to claim: a descriptor
    file that is missing or malformed writes no receipt and exits nonzero, so the controller's
    consumption check sees no evidence rather than a fabricated one.
    """
    root = Path(state_dir)
    document = _read_json(root / DESCRIPTOR_FILE)
    try:
        descriptor = validate_descriptor(document)
    except DeliveryRefused:
        return 2
    _write_json(root / WORK_FILE, {"active": 0, "unconfirmed": 0, "at": _utcnow()})
    _write_json(root / RECEIPT_FILE, startup_receipt(descriptor))
    deadline = time.monotonic() + max(1, int(max_seconds))
    while time.monotonic() < deadline:
        if (root / (STOP_FILE + ".json")).exists():
            return 0
        time.sleep(STOP_POLL)
    return 0


# ----- CLI -----------------------------------------------------------------------------------------
def add_parser(commands) -> None:
    delivery = commands.add_parser("host-delivery",
                                   help="Durable delivery of a reviewed release to a host target; "
                                        "opt-in, reuses Releases approval and the ReleaseQueue fence")
    sub = delivery.add_subparsers(dest="delivery_command", required=True)
    targets = sub.add_parser("register-targets",
                             help="Register the owner's authorized host target registry "
                                  "(urn:zeus:host-delivery-targets:1); host configuration only")
    targets.add_argument("--file", type=Path, required=True)
    register = sub.add_parser("register", help="Register one owner-approved plan read at a commit")
    register.add_argument("--revision", required=True, help="40-hex commit the plan is read at")
    register.add_argument("--path", required=True, help="Repository-relative plan path")
    tick = sub.add_parser("tick", help="Advance at most one delivery by at most one stage")
    tick.add_argument("--plan", default=None, help="One registered plan id; omitted selects one")
    run_command = sub.add_parser("run", help="Bounded tick loop; an empty queue idles without "
                                             "provider calls")
    run_command.add_argument("--once", action="store_true", help="One tick, then exit")
    run_command.add_argument("--interval", type=int, default=15, help="Seconds between ticks")
    run_command.add_argument("--max-ticks", type=int, default=0, dest="max_ticks",
                             help="Stop after this many ticks; 0 runs until stopped")
    status = sub.add_parser("status", help="Read the delivery projection; store read only")
    status.add_argument("--plan", default=None, help="One plan id; omitted reads every plan")


def refusal(exc: Exception) -> dict:
    """What the CLI prints for a failure: a code and a type, never raw text, a path or a value."""
    code = getattr(exc, "reason_code", None)
    if code is None and isinstance(exc, ContractError):
        code = "contract_refused"
    return {"status": "refused", "reason_code": code or "error", "error_type": type(exc).__name__,
            "exit_code": 1}


def controller(service, *, enabled=None, observer=None, git=None, store=None) -> HostDelivery:
    """The coordinator with its existing owners and this host's real ports wired."""
    from codex_harness.adapters.configuration import settings
    from codex_harness.application.fleet import Fleet

    store = service.store if store is None else store
    if enabled is None:
        enabled = configured_enabled(settings())
    github = None if git is None else GitHubDelivery(git)
    # The managed target's activation gate reads the ACTUAL Fleet of this host store.
    return HostDelivery(store, service.org, github=github,
                        hosts=host_ports(fleet=Fleet(store), systemd_control=systemd_control_dir(settings())),
                        canaries=canary_checks(store), observer=observer, enabled=enabled)


def _git(service):
    """The existing configured workspace; built only for the commands that need Git or GitHub."""
    from codex_harness.bootstrap import build_executor

    return build_executor(service).git


def execute(service, args) -> dict:
    command = args.delivery_command
    if command == "register-targets":
        document = json.loads(Path(args.file).read_text("utf-8"))
        return {**HostDelivery(service.store, service.org).register_targets(document), "exit_code": 0}
    if command == "register":
        git = _git(service)
        loaded = load_plan(GitSource(str(git.repository)), args.revision, args.path)
        receipt = HostDelivery(service.store, service.org).register(loaded["plan"], loaded["pin"])
        return {**receipt, "bytes": loaded["bytes"], "exit_code": 0}
    if command == "status":
        projection = HostDelivery(service.store, service.org,
                                  enabled=configured_enabled(_settings())).status(args.plan)
        return {**projection, "exit_code": 0 if projection.get("registered") or args.plan is None else 1}
    observer = _observer(service)
    try:
        delivery = controller(service, observer=observer, git=_git(service))
        if command == "tick":
            result = delivery.tick(args.plan)
            return {**result, "exit_code": 1 if result["outcome"] in FAILED_OUTCOMES else 0}
        return {**run_loop(delivery, once=bool(args.once), interval=args.interval,
                           max_ticks=args.max_ticks), "exit_code": 0}
    finally:
        if observer is not None:
            observer.close()


def _settings() -> dict:
    from codex_harness.adapters.configuration import settings

    return settings()


def _observer(service):
    from codex_harness.bootstrap import build_observer

    return build_observer(service.store, "cli.host-delivery")


def run_loop(delivery: HostDelivery, *, once: bool = False, interval: int = 15,
             max_ticks: int = 0, sleep=time.sleep) -> dict:
    """Bounded tick loop. An idle queue sleeps; it calls no provider and starts no model.

    A stop is graceful: the signal sets a flag, the tick in flight finishes, and the loop returns
    its counts. Nothing here kills a service, a child or a lease.
    """
    stopping = {"stop": False}

    def stop(*_):
        stopping["stop"] = True

    installed = []
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        handler = getattr(signal, name, None)
        if handler is None:
            continue
        try:
            installed.append((handler, signal.signal(handler, stop)))
        except (ValueError, OSError):
            pass
    counts: dict[str, int] = {}
    ticks = 0
    try:
        while not stopping["stop"]:
            result = delivery.tick()
            ticks += 1
            counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
            if once or (max_ticks and ticks >= max_ticks):
                break
            sleep(max(1, int(interval)))
    finally:
        for handler, previous in installed:
            try:
                signal.signal(handler, previous)
            except (ValueError, OSError):
                pass
    return {"schema": "urn:zeus:host-delivery-run:1", "ticks": ticks, "outcomes": counts,
            "stopped": stopping["stop"]}


def main(argv=None) -> int:
    """`python -m codex_harness.adapters.host_delivery service --state-dir DIR`.

    Only the launched service runs this way; every owner command goes through `zeus host-delivery`.
    """
    parser = argparse.ArgumentParser(prog="codex_harness.adapters.host_delivery")
    sub = parser.add_subparsers(dest="command", required=True)
    service = sub.add_parser("service")
    service.add_argument("--state-dir", required=True, dest="state_dir")
    service.add_argument("--max-seconds", type=int, default=SERVICE_MAX_SECONDS, dest="max_seconds")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return serve(args.state_dir, args.max_seconds)


__all__ = ["CANARY_RECEIPT_FILE", "CANARY_REQUEST_FILE", "DESCRIPTOR_FILE", "ENABLED_SETTING", "MAX_PLAN_BYTES",
           "RECEIPT_FILE", "RUNTIME_FILE", "STATE_FILE", "WORK_FILE", "GitHubDelivery",
           "HostTargetBase", "ProcessHostTarget", "ScheduledTaskHostTarget", "add_parser",
           "canary_checks", "checkout_revision", "collect_monitor_canary", "configured_enabled",
           "controller", "effective_profile_digest", "effective_worker_image", "execute",
           "host_ports", "load_plan", "loaded_runtime", "main", "normalize_checks",
           "owner_qualified_canary", "refusal", "run_loop", "runtime_revision", "serve",
           "startup_identity_canary", "startup_receipt"]


if __name__ == "__main__":
    sys.exit(main())
