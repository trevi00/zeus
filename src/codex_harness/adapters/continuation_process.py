"""Owned, nonblocking conductor children (INV-CONTINUATION-001).

The conductor decision is one Codex call that can take many minutes, so the continuation never
waits for it inside a Fleet tick. `ConductorProcesses.start` spawns the existing
`zeus continuation conduct` in the lane environment as an owned `ProcessTree` (the Windows job
object with kill-on-close, the POSIX session group - the same ownership the background service and
the Fleet use) and returns; `poll` answers whether that launch is still running, has exited, was
provably never started, timed out, or cannot be told. The durable identity is the launch id the
controller committed BEFORE the start; the per-launch directory under the lane runtime is its
evidence, so a restarted controller reconciles a launch it no longer holds a handle for.

The child side is this module's `main`, a thin wrapper in front of the conduct command:

1. it takes `lock` without waiting (the `FileLock` probe convention of `observation_spool`) and
   holds it for its whole life; a lock it cannot take means another holder - it exits, no effect;
2. it creates `claim` exclusively with `child`; a claim that already exists (fenced) - it exits,
   no effect;
3. it runs the command, then writes `exit.json` atomically.

A reconciler that holds no handle answers from those files: `exit.json` -> exited; `lock` held ->
running (alive, but owned elsewhere); `lock` free and no claim -> it creates `claim` as `fenced`
WHILE holding the lock, which proves the launch never entered and never will -> absent; `lock` free
and claimed by the child without `exit.json` -> exited without a receipt (the committed decision
row, not this file, then decides; a still running row is recovery work). Only `absent` lets the
controller start another launch, and always under a NEW identity: nothing is relaunched blindly.

Timeout: an owned child past its deadline is ended through its tree and reported `timeout`; the
controller then settles from the decision row. A child owned by nobody here is never signalled.
Limit, stated rather than claimed away: on POSIX a wrapper killed on its own releases the lock while
its command may still run; its decision row then stays `running` and becomes recovery work.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from codex_harness.adapters.commands import no_console_kwargs
from codex_harness.adapters.process_tree import ProcessTree
from codex_harness.domain.continuation import (
    LAUNCH_ABSENT,
    LAUNCH_EXITED,
    LAUNCH_RUNNING,
    LAUNCH_TIMEOUT,
    LAUNCH_UNKNOWN,
)
from codex_harness.domain.fleet import lane_of
from codex_harness.domain.model import canonical
from codex_harness.domain.policy import POLICY

DEFAULT_ARGV = (sys.executable, "-m", "codex_harness.cli")
ENTRY_ARGV = (sys.executable, "-m", "codex_harness.adapters.continuation_process")
# The child's wall-clock bound is the decision allowance plus a fixed margin for process start and
# store I/O, never an extension of the decision itself.
CONDUCT_MARGIN_SECONDS = 120
CLAIM_CHILD, CLAIM_FENCED = "child", "fenced"
EXIT_FENCED = 3
LAUNCH_ID = re.compile(r"^[0-9a-f]{64}$")
TERMINATE_TIMEOUT, SETTLE_TIMEOUT = 5.0, 5.0


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


def _claim(directory: Path, who: str) -> str:
    """Create `claim` exclusively as `who`, or read who already holds it."""
    path = directory / "claim"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(who)
        handle.flush()
        os.fsync(handle.fileno())
    return who


def _exit_receipt(directory: Path) -> dict | None:
    try:
        document = json.loads((directory / "exit.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    code = document.get("exit_code") if isinstance(document, dict) else None
    return {"exit_code": code if type(code) is int else None}


def _write_exit(directory: Path, code: int) -> None:
    staging = directory / "exit.json.tmp"
    staging.write_text(json.dumps({"exit_code": int(code)}), encoding="utf-8")
    os.replace(staging, directory / "exit.json")


def observe(directory: Path) -> dict:
    """Reconcile one launch from its directory alone (no handle): see the module docstring."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        receipt = _exit_receipt(directory)
        if receipt is not None:
            return {"state": LAUNCH_EXITED, "owned": False, **receipt}
        lock = _try_lock(directory)
        if lock is None:
            return {"state": LAUNCH_RUNNING, "owned": False, "exit_code": None}
        try:
            claim = _claim(directory, CLAIM_FENCED)
            receipt = _exit_receipt(directory)
        finally:
            lock.release()
    except (OSError, ValueError) as exc:
        return {"state": LAUNCH_UNKNOWN, "owned": False, "exit_code": None, "error_type": type(exc).__name__}
    if receipt is not None:
        return {"state": LAUNCH_EXITED, "owned": False, **receipt}
    if claim == CLAIM_FENCED:
        return {"state": LAUNCH_ABSENT, "owned": False, "exit_code": None}
    if claim == CLAIM_CHILD:
        return {"state": LAUNCH_EXITED, "owned": False, "exit_code": None}
    return {"state": LAUNCH_UNKNOWN, "owned": False, "exit_code": None}


class ConductorProcesses:
    """The conductor port of `application.continuation.Continuation` over owned child trees.

    One instance lives as long as its Fleet runner (or one CLI tick), so the handles of its own
    children persist across ticks. `max_active` is the bounded concurrency slot conductors take.
    `command(lane, manifest_path)` overrides the conduct argv (tests use a labelled sleeping child)."""

    def __init__(self, config: dict, host: dict, *, argv=DEFAULT_ARGV, entry=ENTRY_ARGV, command=None,
                 max_active: int = 1, seconds: float | None = None, spawn=ProcessTree.spawn,
                 clock=time.monotonic, environment=None):
        self.config, self.host, self.argv, self.entry = config, host, tuple(argv), tuple(entry)
        self.command, self.max_active, self.spawn, self.clock = command, max_active, spawn, clock
        self.seconds = POLICY.decision_seconds + CONDUCT_MARGIN_SECONDS if seconds is None else seconds
        self.environment = environment
        self.children: dict[str, dict] = {}

    def _environment(self, lane: dict) -> dict:
        if self.environment is not None:
            return self.environment(lane, self.host)
        from codex_harness.adapters.fleet_runtime import lane_environment
        return lane_environment(lane, self.host)

    def active(self) -> list[str]:
        """Launch ids of children this process started that are still running. A child that ended
        but was not yet polled is no longer work: its exit receipt settles it on any later poll,
        here or after a restart, so an unavailable store never holds a graceful stop open."""
        return sorted(launch for launch, child in self.children.items() if child["tree"].process.poll() is None)

    def available(self) -> bool:
        return len(self.active()) < self.max_active

    def start(self, lane_id: str, job: dict, launch: str) -> dict:
        lane = lane_of(self.config, lane_id)
        directory = launch_directory(lane["runtime"], launch)
        if launch in self.children:
            return {"pid": self.children[launch]["tree"].process.pid, "cached": True}
        env = self._environment(lane)
        directory.mkdir(parents=True, exist_ok=True)
        if (directory / "claim").exists():
            # This identity already entered or was fenced: its evidence decides, never a second start.
            return {"pid": None, "cached": True}
        manifest = directory / "operation.json"
        manifest.write_text(canonical(job["manifest"]) + "\n", encoding="utf-8", newline="\n")
        command = (list(self.command(lane, manifest)) if self.command is not None else
                   [*self.argv, "--repository", lane["repository"], "continuation", "conduct", "--file", str(manifest)])
        tree = self.spawn([*self.entry, "--launch", str(directory), "--", *command], cwd=lane["repository"], env=env,
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children[launch] = {"tree": tree, "directory": directory, "deadline": self.clock() + self.seconds}
        return {"pid": tree.process.pid, "cached": False}

    def poll(self, lane_id: str, launch: str) -> dict:
        child = self.children.get(launch)
        if child is not None:
            code = child["tree"].process.poll()
            if code is None and self.clock() < child["deadline"]:
                return {"state": LAUNCH_RUNNING, "owned": True, "exit_code": None}
            timed_out = code is None
            confirmed = self._release(launch)
            observed = observe(child["directory"])
            if timed_out:
                return {**observed, "state": LAUNCH_TIMEOUT, "owned": True, "cleanup_confirmed": confirmed}
            if observed["state"] == LAUNCH_EXITED and observed.get("exit_code") is None:
                observed = {**observed, "exit_code": code}
            return {**observed, "owned": True, "cleanup_confirmed": confirmed}
        try:
            directory = launch_directory(lane_of(self.config, lane_id)["runtime"], launch)
        except Exception as exc:
            return {"state": LAUNCH_UNKNOWN, "owned": False, "exit_code": None, "error_type": type(exc).__name__}
        return observe(directory)

    def join(self, poll_seconds: float = 0.2) -> None:
        """Wait until every owned child has ended or passed its deadline (a one-shot CLI tick owns
        its children until then, so it never leaves one behind). The controller still polls them."""
        while any(c["tree"].process.poll() is None and self.clock() < c["deadline"] for c in self.children.values()):
            time.sleep(poll_seconds)

    def _release(self, launch: str) -> bool:
        """End what is left of the tree and close the owned handle; True when confirmed gone."""
        child = self.children.pop(launch)
        tree = child["tree"]
        try:
            receipt = tree.terminate("the conductor launch ended or passed its deadline",
                                     timeout=TERMINATE_TIMEOUT, settle=SETTLE_TIMEOUT)
            return bool(receipt.get("confirmed"))
        except Exception:
            return False
        finally:
            try:
                tree.close()
            except Exception:
                pass


def main(argv=None) -> int:
    """Child side: lock, exclusive claim, run the command, write the exit receipt."""
    parser = argparse.ArgumentParser(prog="continuation-conductor-child")
    parser.add_argument("--launch", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return 2
    lock = _try_lock(args.launch)
    if lock is None:
        return EXIT_FENCED
    try:
        if _claim(args.launch, CLAIM_CHILD) != CLAIM_CHILD:
            return EXIT_FENCED
        with open(args.launch / "conduct.log", "ab") as log:
            code = subprocess.call(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   **no_console_kwargs())
        _write_exit(args.launch, code)
        return code
    finally:
        lock.release()


__all__ = ["CONDUCT_MARGIN_SECONDS", "ConductorProcesses", "launch_directory", "main", "observe"]


if __name__ == "__main__":
    sys.exit(main())
