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
  and the service process of one target. They share the descriptor mechanics exactly: an atomic
  replace under a target-specific lock that compares the expected predecessor first.
* `CANARIES` maps the incumbent fixed check ids to real checks. A plan names one of them by id; no
  plan ever supplies a command, an argv, a path or a check body.

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
import signal
import subprocess
import sys
import time
import uuid
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
    KIND_PROCESS,
    KIND_SCHEDULED_TASK,
    RECEIPT_SCHEMA,
    DeliveryRefused,
    descriptor_digest,
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
RECEIPT_FILE = "startup-receipt.json"
WORK_FILE = "work.json"
STATE_FILE = "controller-state.json"
PAUSE_FILE = "pause"
STOP_FILE = "stop"
LOCK_DIR = "switch.lock"
CANARY_RECEIPT_FILE = "owner-canary-receipt.json"

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


# ----- host targets ----------------------------------------------------------------------------
class HostTargetBase:
    """The descriptor, receipt and drain mechanics every target kind shares.

    The descriptor is immutable: it is replaced, never edited, under a target-specific lock and
    only when the descriptor that is there right now is exactly the expected predecessor.
    """

    def __init__(self, *, lock_timeout: float = LOCK_TIMEOUT):
        self.lock_timeout = lock_timeout

    @staticmethod
    def state_dir(target: dict) -> Path:
        return Path(target["state_dir"])

    @classmethod
    def path(cls, target: dict, name: str) -> Path:
        return cls.state_dir(target) / name

    # --- the immutable descriptor --------------------------------------------------------------
    def current(self, target: dict):
        document = _read_json(self.path(target, DESCRIPTOR_FILE))
        if document is None:
            return None
        try:
            return validate_descriptor(document)
        except DeliveryRefused:
            return None

    def switch(self, target: dict, descriptor: dict, *, expected) -> dict:
        """Atomically replace the descriptor after comparing the expected predecessor."""
        lock = self.path(target, LOCK_DIR)
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    # A held lock is a conflicting change on this target, never something to break.
                    raise DeliveryRefused("target_lock_held", "target_id") from None
                time.sleep(STOP_POLL)
            except OSError as exc:
                raise DeliveryRefused("target_lock_unavailable", "state_dir") from exc
        try:
            current = self.current(target)
            observed = None if current is None else descriptor_digest(current)
            if observed != expected:
                raise DeliveryRefused("descriptor_changed", "expected_descriptor")
            _write_json(self.path(target, DESCRIPTOR_FILE), descriptor)
            return {"written": True, "descriptor_sha256": descriptor_digest(descriptor)}
        finally:
            try:
                lock.rmdir()
            except OSError:
                pass

    # --- what the launched process said about itself -------------------------------------------
    def receipt(self, target: dict):
        return _read_json(self.path(target, RECEIPT_FILE))

    # --- draining -------------------------------------------------------------------------------
    def drain(self, target: dict) -> dict:
        """Pause new admission and report what is still running and what is unconfirmed.

        `work.json` is the service's own report. A missing report beside a RUNNING service is not
        an empty one: it is an unconfirmed effect, because nothing observed that the service had
        finished its work.
        """
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

    def start(self, target: dict, descriptor: dict) -> dict:
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
        return _read_json(self.path(target, STATE_FILE)) or {}

    def running(self, target: dict) -> bool:
        return _alive(self._state(target).get("pid"))

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

    def start(self, target: dict, descriptor: dict) -> dict:
        """Stop the previous instance, prove it is gone, then start exactly one new process.

        The old receipt is removed before the start, so the next consumption check cannot read the
        previous instance's evidence as the new one's. A previous process that cannot be proven
        gone raises instead of starting a second one beside it.
        """
        stopped = self.stop(target)
        if not stopped["stopped"]:
            raise DeliveryRefused("previous_instance_unconfirmed", "target_id")
        for name in (RECEIPT_FILE, STOP_FILE + ".json", PAUSE_FILE + ".json"):
            try:
                self.path(target, name).unlink()
            except OSError:
                pass
        argv = [self.python, "-m", "codex_harness.adapters.host_delivery", "service",
                "--state-dir", str(self.state_dir(target)), "--max-seconds", str(self.max_seconds)]
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **no_console_kwargs(process_group=True))
        _write_json(self.path(target, STATE_FILE),
                    {"pid": process.pid, "started_at": _utcnow(),
                     "descriptor_sha256": descriptor_digest(descriptor)})
        return {"started": True, "pid": process.pid}


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

    def start(self, target: dict, descriptor: dict) -> dict:
        stopped = self.stop(target)
        if not stopped["stopped"]:
            raise DeliveryRefused("previous_instance_unconfirmed", "target_id")
        for name in (RECEIPT_FILE, STOP_FILE + ".json", PAUSE_FILE + ".json"):
            try:
                self.path(target, name).unlink()
            except OSError:
                pass
        # The task's own registration owns its launcher, its window policy and its process tree.
        result = self.runner(["schtasks", "/Run", "/TN", target["service"]], timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("Scheduled task could not be started")
        _write_json(self.path(target, STATE_FILE),
                    {"service": target["service"], "started_at": _utcnow(),
                     "descriptor_sha256": descriptor_digest(descriptor)})
        return {"started": True, "service": target["service"]}


def host_ports(**kwargs) -> dict:
    """The host adapters by target kind, as the coordinator expects them."""
    return {KIND_PROCESS: ProcessHostTarget(**kwargs), KIND_SCHEDULED_TASK: ScheduledTaskHostTarget()}


# ----- the incumbent fixed canary checks --------------------------------------------------------
def startup_identity_canary(target: dict, descriptor: dict) -> dict:
    """The service contract of an owned process target: it is still there, still itself.

    The receipt is re-read AFTER activation was proposed and the process is checked to be alive, so
    a process that wrote a receipt and died is not an activation.
    """
    receipt = _read_json(HostTargetBase.path(target, RECEIPT_FILE))
    if not isinstance(receipt, dict):
        return {"passed": False, "reason_code": "canary_receipt_missing", "evidence": None}
    if receipt.get("descriptor_sha256") != descriptor_digest(descriptor):
        return {"passed": False, "reason_code": "canary_descriptor_mismatch", "evidence": None}
    state = _read_json(HostTargetBase.path(target, STATE_FILE)) or {}
    pid = state.get("pid") if target.get("kind") == KIND_PROCESS else receipt.get("pid")
    if not _alive(pid):
        return {"passed": False, "reason_code": "canary_process_absent", "evidence": None}
    return {"passed": True, "reason_code": None, "evidence": receipt.get("instance_id")}


def collect_monitor_canary(target: dict, descriptor: dict, *, store=None) -> dict:
    """The service contract of the collect target: a FRESH read-only monitor source shows this
    runtime as the consumed one.

    It is the incumbent collector's own projection that answers, so a canary cannot pass on a
    snapshot that was collected before the switch or on a descriptor nobody consumed.
    """
    if store is None:
        return {"passed": False, "reason_code": "canary_store_unavailable", "evidence": None}
    from codex_harness.adapters.monitoring import host_delivery_facts

    facts = host_delivery_facts(store)
    row = next((entry for entry in facts.get("targets", [])
                if entry.get("target_id") == target["target_id"]), None)
    if row is None:
        return {"passed": False, "reason_code": "canary_target_unobserved", "evidence": None}
    if row.get("descriptor_sha256") != descriptor_digest(descriptor) or not row.get("consumed"):
        return {"passed": False, "reason_code": "canary_descriptor_not_active", "evidence": None}
    return {"passed": True, "reason_code": None, "evidence": row.get("instance_id")}


def owner_qualified_canary(target: dict, descriptor: dict) -> dict:
    """A real qualified worker operation is OWNER acceptance work, not something a controller runs.

    This check therefore looks for the owner's own receipt for exactly this descriptor. No model,
    provider or worker is started from here, and an absent receipt is an honest not-passed.
    """
    receipt = _read_json(HostTargetBase.path(target, CANARY_RECEIPT_FILE))
    if not isinstance(receipt, dict):
        return {"passed": False, "reason_code": "canary_owner_receipt_missing", "evidence": None}
    if receipt.get("descriptor_sha256") != descriptor_digest(descriptor):
        return {"passed": False, "reason_code": "canary_owner_receipt_stale", "evidence": None}
    return {"passed": bool(receipt.get("passed")), "evidence": receipt.get("evidence"),
            "reason_code": None if receipt.get("passed") else "canary_owner_receipt_failed"}


def canary_checks(store=None) -> dict:
    """The fixed check id -> check map. A plan selects one by id and supplies nothing else."""
    return {CANARY_STARTUP: startup_identity_canary,
            CANARY_COLLECT: lambda target, descriptor: collect_monitor_canary(target, descriptor,
                                                                              store=store),
            CANARY_FLEET: owner_qualified_canary}


# ----- the launched service ----------------------------------------------------------------------
def startup_receipt(descriptor: dict) -> dict:
    """What a launched process reports about ITSELF: its instance, its process and what it loaded."""
    return {"schema": RECEIPT_SCHEMA, "target_id": descriptor["target_id"],
            "instance_id": uuid.uuid4().hex, "pid": os.getpid(), "started_at": _utcnow(),
            "module_root": str(Path(codex_harness.__file__).resolve().parent),
            "descriptor_sha256": descriptor_digest(descriptor), "revision": descriptor["revision"],
            "worker_image": descriptor["worker_image"],
            "profile_digest": descriptor["profile_digest"]}


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

    store = service.store if store is None else store
    if enabled is None:
        enabled = configured_enabled(settings())
    github = None if git is None else GitHubDelivery(git)
    return HostDelivery(store, service.org, github=github, hosts=host_ports(),
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


__all__ = ["CANARY_RECEIPT_FILE", "DESCRIPTOR_FILE", "ENABLED_SETTING", "MAX_PLAN_BYTES",
           "RECEIPT_FILE", "STATE_FILE", "WORK_FILE", "GitHubDelivery", "HostTargetBase",
           "ProcessHostTarget", "ScheduledTaskHostTarget", "add_parser", "canary_checks",
           "collect_monitor_canary", "configured_enabled", "controller", "execute", "host_ports",
           "load_plan", "main", "normalize_checks", "owner_qualified_canary", "refusal", "run_loop",
           "serve", "startup_identity_canary", "startup_receipt"]


if __name__ == "__main__":
    sys.exit(main())
