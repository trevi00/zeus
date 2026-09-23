"""Guarded, nonblocking conductor launches (INV-CONTINUATION-001, SPEC two-strike ownership design).

The conductor decision is one Codex call that can take many minutes, so the continuation never
waits for it inside a Fleet tick. Three owners, separated on purpose:

* the Fleet reserves the launch's execution unit and commits its launch identity and token BEFORE
  anything is spawned, and releases it only on an exact proof (application.fleet.settle_unit);
* `ConductorProcesses.start` spawns ONE hidden per-launch guardian (this module's `main`) outside
  the controller's own process tree and returns; it never spawns that identity again;
* the guardian owns the inner conduct `ProcessTree` (the Windows job object with kill-on-close, the
  POSIX session group), its monotonic deadline and its cleanup, and touches NO database: a blocked
  or failed store read, a Fleet tick that never returns or a controller that exits cannot suppress
  its deadline or its cleanup attempts. Polling only observes its receipts.

The per-launch directory `<lane runtime>/continuation/launches/<launch id>` is the local evidence:

1. `spawn` - created exclusively by the controller before the guardian exists (one-shot spawn);
   `launch.json` - the identity (launch id, unit token) the guardian binds every receipt to;
2. `lock` - taken by the guardian without waiting and held for its whole life;
3. `debt.json` - flushed write-ahead debt, written BEFORE the claim; a write failure starts nothing;
4. `claim` - created exclusively as `child`; one that already exists (`fenced`) - exit, no effect;
5. the guardian runs the command as its own tree until it exits, its deadline passes or a stop is
   requested (`stop` file, POSIX SIGTERM), then `ProcessTree.terminate` ends what is left;
6. `cleanup.json` - written atomically ONLY when the parent AND the tree were each confirmed ended.
   Unconfirmed cleanup is retried a bounded number of times; then `unresolved.json` records the
   deliberate unresolved handoff and the debt stays. A proof that cannot be persisted is retried
   and never assumed.

`observe` reconciles from those files alone: a valid proof -> `exited`/`timeout` with
`cleanup_confirmed` and the proof; `lock` held -> `running`; `lock` free and no claim -> it writes
`claim=fenced` WHILE holding the lock (so a delayed guardian can execute nothing) -> `absent` with the
fence proof; `lock` free and claimed without a proof -> `unknown` (the guardian ended or was killed
without proving cleanup), even when an old `exit.json` exists. Only a proof releases the unit.

Limits, stated rather than claimed away: a guardian killed outright leaves UNKNOWN debt - nothing
here kills a pid read back from a file or infers cleanup from an ancestor's death; on POSIX its
conduct group may outlive it, and a descendant that calls setsid leaves the group. On Windows the
guardian asks to break away from a controller job; when that job forbids it the guardian stays in
the controller's job (reported as `breakaway: False`) and dies with it as unknown debt. Windows job
behaviour of this module is an owner qualification gate, not proven by POSIX tests.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from codex_harness.adapters.commands import no_console_kwargs
from codex_harness.adapters.process_tree import ProcessTree, TreeOwnershipError, TreeOwnershipLeak
from codex_harness.domain.continuation import (
    LAUNCH_ABSENT,
    LAUNCH_EXITED,
    LAUNCH_RUNNING,
    LAUNCH_TIMEOUT,
    LAUNCH_UNKNOWN,
)
from codex_harness.domain.fleet import PROOF_CLEANUP, PROOF_FENCED, lane_of
from codex_harness.domain.model import canonical
from codex_harness.domain.policy import POLICY

DEFAULT_ARGV = (sys.executable, "-m", "codex_harness.cli")
ENTRY_ARGV = (sys.executable, "-m", "codex_harness.adapters.continuation_process")
# The child's wall-clock bound is the decision allowance plus a fixed margin for process start and
# store I/O, never an extension of the decision itself.
CONDUCT_MARGIN_SECONDS = 120
CLAIM_CHILD, CLAIM_FENCED = "child", PROOF_FENCED
EXIT_FENCED = 3
EXIT_IDENTITY = 4        # launch.json missing or not this launch: nothing claimed, nothing started
EXIT_DEBT_UNWRITTEN = 5  # the write-ahead debt did not reach the disk: nothing claimed, nothing started
EXIT_UNRESOLVED = 124    # cleanup (or its proof) could not be confirmed: the debt stays
LAUNCH_ID = re.compile(r"^[0-9a-f]{64}$")
GUARDIAN_SCHEMA = "urn:zeus:conductor-guardian:1"
TERMINATE_TIMEOUT, SETTLE_TIMEOUT = 5.0, 5.0
CLEANUP_ATTEMPTS, PERSIST_ATTEMPTS, RETRY_DELAY, POLL_SECONDS = 3, 5, 0.5, 0.2
# Windows: leave a controller job so controller teardown does not end the guardian (by value, as
# `subprocess` exposes it only on Windows).
CREATE_BREAKAWAY_FROM_JOB = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)


def launch_directory(runtime_root, launch: str) -> Path:
    """`<lane runtime>/continuation/launches/<launch id>`; the id is a controller digest, never a path."""
    if not (isinstance(launch, str) and LAUNCH_ID.fullmatch(launch)):
        raise ValueError("launch id must be 64 lowercase hex")
    return Path(runtime_root) / "continuation" / "launches" / launch


def _try_lock(directory: Path):
    lock = FileLock(str(directory / "lock"), is_singleton=False)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return None
    return lock


def _exclusive(path: Path, text: str) -> bool:
    """Create `path` exclusively with `text`, flushed; False when it already exists."""
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _claim(directory: Path, who: str) -> str:
    """Create `claim` exclusively as `who`, or read who already holds it."""
    if _exclusive(directory / "claim", who):
        return who
    return (directory / "claim").read_text(encoding="utf-8").strip()


def _write_atomic(path: Path, document: dict) -> None:
    """Flushed to disk under a staging name, then renamed over `path`: a reader sees all or nothing."""
    staging = path.with_name(path.name + ".tmp")
    with open(staging, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(document, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, path)


def _read(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return document if isinstance(document, dict) else None


def _identity(directory: Path) -> dict | None:
    """The launch identity the controller wrote before spawning, if it names THIS directory."""
    document = _read(directory / "launch.json")
    if (document is None or document.get("schema") != GUARDIAN_SCHEMA or document.get("launch") != directory.name
            or not (type(document.get("token")) is str and document["token"])):
        return None
    return document


def _proof(directory: Path) -> dict | None:
    """The observation a durable cleanup receipt permits, or None when there is no valid one.

    It must name this launch and the token of `launch.json`, and confirm the parent AND the tree."""
    receipt = _read(directory / "cleanup.json")
    if receipt is None:
        return None
    identity = _identity(directory)
    parent = receipt.get("parent") if isinstance(receipt.get("parent"), dict) else {}
    tree = receipt.get("tree") if isinstance(receipt.get("tree"), dict) else {}
    if (identity is None or receipt.get("schema") != GUARDIAN_SCHEMA or receipt.get("kind") != PROOF_CLEANUP
            or receipt.get("launch") != directory.name or receipt.get("token") != identity["token"]
            or not (receipt.get("confirmed") is True and parent.get("confirmed") is True
                    and tree.get("confirmed") is True)):
        return None
    code = receipt.get("exit_code")
    return {"state": LAUNCH_TIMEOUT if receipt.get("timed_out") is True else LAUNCH_EXITED, "owned": False,
            "exit_code": code if type(code) is int else None, "cleanup_confirmed": True, "proof": receipt}


def observe(directory: Path) -> dict:
    """Reconcile one launch from its directory alone (no handle, no database): see the module docstring."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        found = _proof(directory)
        if found is not None:
            return found
        lock = _try_lock(directory)
        if lock is None:
            return {"state": LAUNCH_RUNNING, "owned": False, "exit_code": None}
        try:
            claim = _claim(directory, CLAIM_FENCED)
            found = _proof(directory)
        finally:
            lock.release()
    except (OSError, ValueError) as exc:
        return {"state": LAUNCH_UNKNOWN, "owned": False, "exit_code": None, "cleanup_confirmed": False,
                "error_type": type(exc).__name__}
    if found is not None:
        return found
    if claim == CLAIM_FENCED:
        return {"state": LAUNCH_ABSENT, "owned": False, "exit_code": None,
                "proof": {"kind": PROOF_FENCED, "launch": directory.name, "claim": CLAIM_FENCED}}
    # Entered, and its guardian is gone without a proof: never "exited", whatever else is on disk.
    reason = "cleanup_unresolved" if (directory / "unresolved.json").exists() else "guardian_ended_without_proof"
    return {"state": LAUNCH_UNKNOWN, "owned": False, "exit_code": None, "cleanup_confirmed": False,
            "reason_code": reason}


def spawn_guardian(argv, *, cwd=None, env=None):
    """The hidden guardian, outside the controller's tree: its own POSIX session (a controller
    group signal does not reach it), on Windows no window, its own group and a breakaway from the
    controller's job when that job allows it. `breakaway` records which one it got."""
    common = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name != "nt":
        process = subprocess.Popen(argv, start_new_session=True, **common)
        process.breakaway = None
        return process
    try:  # pragma: no cover - exercised on Windows hosts
        process = subprocess.Popen(argv, **common, **no_console_kwargs(
            process_group=True, creationflags=CREATE_BREAKAWAY_FROM_JOB))
        process.breakaway = True
    except OSError:  # pragma: no cover - the controller's job forbids breakaway; nothing was created
        process = subprocess.Popen(argv, **common, **no_console_kwargs(process_group=True))
        process.breakaway = False
    return process


class ConductorProcesses:
    """The conductor port of `application.continuation.Continuation`: guardian spawn and local
    observation. It holds NO capacity: the Fleet's unit reservation is the only admission authority.

    One instance lives as long as its Fleet runner (or one CLI tick), so the handles of the
    guardians it spawned are reaped across ticks. `command(lane, manifest_path)` overrides the
    conduct argv (tests use a labelled sleeping child); `spawn` overrides the guardian spawn."""

    def __init__(self, config: dict, host: dict, *, argv=DEFAULT_ARGV, entry=ENTRY_ARGV, command=None,
                 seconds: float | None = None, spawn=spawn_guardian, environment=None):
        self.config, self.host, self.argv, self.entry = config, host, tuple(argv), tuple(entry)
        self.command, self.spawn = command, spawn
        self.seconds = POLICY.decision_seconds + CONDUCT_MARGIN_SECONDS if seconds is None else seconds
        self.environment = environment
        self.children: dict[str, dict] = {}

    def _environment(self, lane: dict) -> dict:
        if self.environment is not None:
            return self.environment(lane, self.host)
        from codex_harness.adapters.fleet_runtime import lane_environment
        return lane_environment(lane, self.host)

    def active(self) -> list[str]:
        """Launch ids whose guardian this process spawned and which is still alive. A guardian
        that ended is no longer this process's work: its receipt (or its absence) is settled on a
        later poll, here or after a restart, so an unavailable store never holds a stop open."""
        return sorted(launch for launch, child in self.children.items() if child["guardian"].poll() is None)

    def start(self, lane_id: str, job: dict, launch: str, token: str) -> dict:
        lane = lane_of(self.config, lane_id)
        directory = launch_directory(lane["runtime"], launch)
        if launch in self.children:
            return {"pid": self.children[launch]["guardian"].pid, "cached": True}
        if not (type(token) is str and token):
            raise ValueError("a launch starts only under its reserved unit token")
        env = self._environment(lane)
        directory.mkdir(parents=True, exist_ok=True)
        # One-shot: the marker exists before the guardian does, so no later start of this identity -
        # here, after a lost response or after a restart - ever spawns a second one.
        if not _exclusive(directory / "spawn", "controller"):
            return {"pid": None, "cached": True}
        manifest = directory / "operation.json"
        manifest.write_text(canonical(job["manifest"]) + "\n", encoding="utf-8", newline="\n")
        _write_atomic(directory / "launch.json", {"schema": GUARDIAN_SCHEMA, "launch": launch, "token": token,
                                                  "seconds": self.seconds})
        command = (list(self.command(lane, manifest)) if self.command is not None else
                   [*self.argv, "--repository", lane["repository"], "continuation", "conduct", "--file", str(manifest)])
        guardian = self.spawn([*self.entry, "--launch", str(directory), "--seconds", repr(float(self.seconds)),
                               "--", *command], cwd=lane["repository"], env=env)
        self.children[launch] = {"guardian": guardian, "directory": directory}
        return {"pid": guardian.pid, "cached": False, "breakaway": getattr(guardian, "breakaway", None)}

    def poll(self, lane_id: str, launch: str) -> dict:
        child = self.children.get(launch)
        if child is not None:
            if child["guardian"].poll() is None:
                # Its durable proof already answers, even while the guardian is still exiting.
                try:
                    found = _proof(child["directory"])
                except (OSError, ValueError):
                    found = None
                if found is not None:
                    return {**found, "owned": True}
                return {"state": LAUNCH_RUNNING, "owned": True, "exit_code": None}
            self.children.pop(launch)  # reaped; its evidence answers from here on
            return observe(child["directory"])
        try:
            directory = launch_directory(lane_of(self.config, lane_id)["runtime"], launch)
        except Exception as exc:
            return {"state": LAUNCH_UNKNOWN, "owned": False, "exit_code": None, "cleanup_confirmed": False,
                    "error_type": type(exc).__name__}
        return observe(directory)

    def request_stop(self, launches=None) -> list[str]:
        """Ask guardians to end their trees now (local files only, no database); each still proves
        its cleanup before its unit can be settled. Returns the launches asked."""
        asked = []
        for launch in (sorted(self.children) if launches is None else launches):
            child = self.children.get(launch)
            if child is None:
                continue
            try:
                (child["directory"] / "stop").write_text("stop", encoding="utf-8")
            except OSError:
                continue
            asked.append(launch)
        return asked

    def join(self, poll_seconds: float = 0.2) -> None:
        """Wait until every guardian this process spawned has ended (each is bounded by its own
        deadline and bounded cleanup), so a one-shot CLI tick leaves nothing it has not observed."""
        while self.active():
            time.sleep(poll_seconds)


# ---- the guardian ------------------------------------------------------------------------------
def _terminate(tree, reason: str, attempts: int, sleep) -> dict:
    """Bounded cleanup through the owned tree. False or an exception never means absent."""
    receipt: dict = {"confirmed": False}
    for attempt in range(1, attempts + 1):
        try:
            receipt = tree.terminate(reason, timeout=TERMINATE_TIMEOUT, settle=SETTLE_TIMEOUT)
        except Exception as exc:
            receipt = {"confirmed": False, "error_type": type(exc).__name__}
        receipt = dict(receipt) if isinstance(receipt, dict) else {"confirmed": False}
        receipt["attempts"] = attempt
        if receipt.get("confirmed") is True and (receipt.get("parent") or {}).get("confirmed") is True \
                and (receipt.get("tree") or {}).get("confirmed") is True:
            return receipt
        receipt["confirmed"] = False
        if attempt < attempts:
            sleep(RETRY_DELAY)
    return receipt


def _persist(path: Path, document: dict, attempts: int, sleep) -> bool:
    for attempt in range(attempts):
        try:
            _write_atomic(path, document)
            return True
        except OSError:
            if attempt + 1 < attempts:
                sleep(RETRY_DELAY)
    return False


def _summary(part) -> dict:
    part = part if isinstance(part, dict) else {}
    code = part.get("exit_code")
    return {"confirmed": part.get("confirmed") is True, "exit_code": code if type(code) is int else None,
            "method": part.get("method") if isinstance(part.get("method"), str) else None}


def guard(directory: Path, command: list, *, seconds: float, spawn=ProcessTree.spawn, clock=time.monotonic,
          sleep=time.sleep, stopping=lambda: False, attempts: int = CLEANUP_ATTEMPTS,
          persist_attempts: int = PERSIST_ATTEMPTS) -> int:
    """One launch, from lock to proof. Uses no database; returns the guardian's exit code."""
    lock = _try_lock(directory)
    if lock is None:
        return EXIT_FENCED
    try:
        identity = _identity(directory)
        if identity is None:
            return EXIT_IDENTITY
        if (directory / "claim").exists():
            return EXIT_FENCED  # entered or fenced before: its evidence is never rewritten
        base = {"schema": GUARDIAN_SCHEMA, "launch": identity["launch"], "token": identity["token"]}
        debt = {**base, "state": "starting", "guardian_pid": os.getpid(), "pid": None, "boundary": None,
                "deadline_seconds": seconds}
        try:
            _write_atomic(directory / "debt.json", debt)
        except OSError:
            return EXIT_DEBT_UNWRITTEN  # no claim yet: a reconciler fences it as never entered
        if _claim(directory, CLAIM_CHILD) != CLAIM_CHILD:
            return EXIT_FENCED
        deadline = clock() + seconds
        try:
            with open(directory / "conduct.log", "ab") as log:
                tree = spawn(list(command), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        except TreeOwnershipLeak as exc:
            # Something was created and cannot be proven gone: a deliberate unresolved handoff.
            _persist(directory / "unresolved.json", {**base, "reason_code": "spawn_leak",
                                                     "detail": {"cleanup": (exc.detail or {}).get("cleanup")}},
                     persist_attempts, sleep)
            _persist(directory / "debt.json", {**debt, "state": "cleanup_unknown"}, persist_attempts, sleep)
            return EXIT_UNRESOLVED
        except (OSError, TreeOwnershipError, ValueError) as exc:
            # Nothing was created: that is itself the cleanup proof of this launch.
            proof = {**base, "kind": PROOF_CLEANUP, "spawned": False, "error_type": type(exc).__name__,
                     "exit_code": None, "timed_out": False, "stopped": False, "confirmed": True,
                     "parent": {"confirmed": True, "exit_code": None, "method": "not_created"},
                     "tree": {"confirmed": True, "exit_code": None, "method": "not_created"}}
            return 0 if _persist(directory / "cleanup.json", proof, persist_attempts, sleep) else EXIT_UNRESOLVED
        debt = {**debt, "state": "running", "pid": tree.process.pid, "boundary": dict(tree.boundary)}
        try:
            _write_atomic(directory / "debt.json", debt)
        except OSError:
            pass  # the flushed `starting` debt still stands for this launch; supervision continues
        reason = "exited"
        while tree.process.poll() is None:
            if clock() >= deadline:
                reason = "timeout"
                break
            if stopping() or (directory / "stop").exists():
                reason = "stopped"
                break
            sleep(POLL_SECONDS)
        natural = tree.process.poll() if reason == "exited" else None
        receipt = _terminate(tree, "the conductor launch " + reason, attempts, sleep)
        if receipt.get("confirmed") is not True:
            # The handle stays open to the end of this process; parent exit alone proves nothing.
            unresolved = {**base, "reason_code": "cleanup_unconfirmed", "attempts": receipt.get("attempts"),
                          "error_type": receipt.get("error_type"), "parent": _summary(receipt.get("parent")),
                          "tree": _summary(receipt.get("tree"))}
            _persist(directory / "unresolved.json", unresolved, persist_attempts, sleep)
            _persist(directory / "debt.json", {**debt, "state": "cleanup_unknown"}, persist_attempts, sleep)
            return EXIT_UNRESOLVED
        parent = _summary(receipt.get("parent"))
        code = natural if type(natural) is int else parent["exit_code"]
        proof = {**base, "kind": PROOF_CLEANUP, "spawned": True, "exit_code": code, "timed_out": reason == "timeout",
                 "stopped": reason == "stopped", "confirmed": True, "parent": parent,
                 "tree": _summary(receipt.get("tree")), "attempts": receipt.get("attempts")}
        if not _persist(directory / "cleanup.json", proof, persist_attempts, sleep):
            # Cleaned but not provable: the debt stays and nothing may release the unit.
            _persist(directory / "unresolved.json", {**base, "reason_code": "proof_unwritten"}, persist_attempts,
                     sleep)
            return EXIT_UNRESOLVED
        try:
            tree.close()  # only after the durable proof
        except Exception:
            pass
        return code if type(code) is int and 0 <= code < 256 else 1
    finally:
        lock.release()


def main(argv=None) -> int:
    """Guardian side: lock, write-ahead debt, exclusive claim, owned conduct tree, cleanup proof."""
    parser = argparse.ArgumentParser(prog="continuation-conductor-guardian")
    parser.add_argument("--launch", required=True, type=Path)
    parser.add_argument("--seconds", required=True, type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return 2
    requested = {"stop": False}
    if os.name != "nt":
        # Recorded, never raised (the background_service convention): a stop cannot unwind the
        # guardian between spawning the tree and holding it; it is acted on at the next poll.
        signal.signal(signal.SIGTERM, lambda signum, frame: requested.update(stop=True))
    return guard(args.launch, command, seconds=args.seconds, stopping=lambda: requested["stop"])


__all__ = ["CONDUCT_MARGIN_SECONDS", "ConductorProcesses", "guard", "launch_directory", "main", "observe",
           "spawn_guardian"]


if __name__ == "__main__":
    sys.exit(main())
