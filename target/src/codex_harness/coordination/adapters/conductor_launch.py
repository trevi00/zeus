"""The continuation conductor port: guardian spawn and local observation of one conductor launch.

Layer: adapters
Context: coordination
Owns: `ConductorProcesses` (the per-process guardian handles, stop requests and the conduct argv)
Does not own: the guardian protocol (guarded_launch), the lane environment (LaneLauncher, pending S10: injected),
    the Fleet unit (coordination.application.fleet)
Entry points: ConductorProcesses
Contracts: INV-CONTINUATION-001

S6 named transcription of M7 `adapters/continuation_process.ConductorProcesses` (verbatim except the named seams:
`spawn` is required at `start`; the lane environment is injected, never imported).
"""
from __future__ import annotations

import time

from codex_harness.coordination.adapters.guarded_launch import (
    CONDUCT_MARGIN_SECONDS,
    DEFAULT_ARGV,
    ENTRY_ARGV,
    GUARDIAN_SCHEMA,
    _exclusive,
    _proof,
    _write_atomic,
    launch_directory,
    observe,
)
from codex_harness.coordination.domain.continuation import LAUNCH_RUNNING, LAUNCH_UNKNOWN
from codex_harness.coordination.domain.fleet import lane_of
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import canonical
from codex_harness.kernel.policy import POLICY


class ConductorProcesses:
    """The conductor port of `application.continuation.Continuation`: guardian spawn and local
    observation. It holds NO capacity: the Fleet's unit reservation is the only admission authority.

    One instance lives as long as its Fleet runner (or one CLI tick), so the handles of the
    guardians it spawned are reaped across ticks. `command(lane, manifest_path)` overrides the
    conduct argv (tests use a labelled sleeping child); `spawn` overrides the guardian spawn."""

    def __init__(self, config: dict, host: dict, *, argv=DEFAULT_ARGV, entry=ENTRY_ARGV, command=None,
                 seconds: float | None = None, spawn=None, environment=None):
        self.config, self.host, self.argv, self.entry = config, host, tuple(argv), tuple(entry)
        self.command, self.spawn = command, spawn
        self.seconds = POLICY.decision_seconds + CONDUCT_MARGIN_SECONDS if seconds is None else seconds
        self.environment = environment
        self.children: dict[str, dict] = {}
        self.stop_asked: set[str] = set()

    def _environment(self, lane: dict) -> dict:
        # S6 seam: the lane environment belongs with LaneLauncher (pending S10) and is injected.
        require(self.environment is not None, "Lane environment is not wired")
        return self.environment(lane, self.host)

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
        require(self.spawn is not None, "Guarded child spawn is not wired")
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

    def request_stop(self, launches=None) -> dict:
        """Ask guardians to end their trees now (local files only, no database); each still proves
        its cleanup before its unit can be settled. A launch already asked is not asked again.

        Returns `asked` (the launches whose `stop` file was written by this call) and `failed`
        (`launch` and `error_type` of each request that could not be written; it is retried by the
        next call, and the guardian's own deadline still bounds that launch). Asking is not cleanup."""
        asked, failed = [], []
        for launch in (sorted(self.children) if launches is None else launches):
            child = self.children.get(launch)
            if child is None or launch in self.stop_asked:
                continue
            try:
                (child["directory"] / "stop").write_text("stop", encoding="utf-8")
            except OSError as exc:
                failed.append({"launch": launch, "error_type": type(exc).__name__})
                continue
            self.stop_asked.add(launch)
            asked.append(launch)
        return {"asked": asked, "failed": failed}

    def join(self, poll_seconds: float = 0.2) -> None:
        """Wait until every guardian this process spawned has ended (each is bounded by its own
        deadline and bounded cleanup), so a one-shot CLI tick leaves nothing it has not observed."""
        while self.active():
            time.sleep(poll_seconds)
