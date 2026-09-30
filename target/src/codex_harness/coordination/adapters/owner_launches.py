"""The owner-action guarded launches: the independent assessor and the policy v2 research tick.

Layer: adapters
Context: coordination
Owns: `Assessments` (bounded report context, the assessment document, one guardian per launch) and
    `ResearchLaunches` (the provider probe, one guarded `research-program run` per launch)
Does not own: the guardian protocol (guarded_launch), the provider resolution (execution: injected `resolve`), the
    version-call runner (host_os chokepoint: injected `run`), the artifact store (storage: injected)
Entry points: Assessments, ResearchLaunches
Contracts: INV-OWNER-ACTIONS-001, INV-DISCOVERY-PRESSURE-001

S6 named transcription of M7 `adapters/owner_actions.py` (the Assessments..ResearchLaunches region, verbatim except
the named seams: `spawn` is required at `start`; `run` and `resolve` are required at `probe`).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from codex_harness.coordination.adapters.guarded_launch import (
    CONDUCT_MARGIN_SECONDS,
    DEFAULT_ARGV,
    ENTRY_ARGV,
    GUARDIAN_SCHEMA,
    _exclusive,
    _write_atomic,
    launch_directory,
    observe,
)
from codex_harness.coordination.domain.owner_actions import EVIDENCE_REF, MAX_REPORT_CHARS
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import canonical
from codex_harness.kernel.policy import POLICY


class Assessments:
    """Context from the trusted artifact store, the assessment document, and one guardian per launch.

    `root` is the launch directory root (`<runtime>/owner-actions`); `command(decision_id, correlation)`
    overrides the assessor argv (tests use a labelled child); `spawn` overrides the guardian spawn."""

    def __init__(self, artifacts, root, *, argv=DEFAULT_ARGV, entry=ENTRY_ARGV, command=None, spawn=None,
                 seconds: float | None = None, environment=None):
        self.artifacts, self.root, self.argv, self.entry = artifacts, Path(root), tuple(argv), tuple(entry)
        self.command, self.spawn, self.environment = command, spawn, environment
        self.seconds = POLICY.decision_seconds + CONDUCT_MARGIN_SECONDS if seconds is None else seconds
        self.children: dict = {}

    def context(self, binding: dict, found: dict) -> dict:
        """The bound report the assessor must read: the accepted council's frozen report execution
        receipt (its answer), bounded. Unreadable evidence is no context, never an empty report."""
        run = ((found.get("facts") or {}).get("acceptance") or {}).get("run") or {}
        report = run.get("report") if isinstance(run.get("report"), dict) else {}
        ref = report.get("execution_ref")
        if not (type(ref) is str and EVIDENCE_REF.fullmatch(ref)):
            return {"report": None}
        try:
            document = self.artifacts.document(ref)
        except (OSError, ValueError, ContractError):
            return {"report": None}
        answer = document.get("answer")
        return {"report": canonical(answer)[:MAX_REPORT_CHARS] if answer is not None else None,
                "report_digest": report.get("sha256"), "evidence_refs": [ref], "members": found.get("members") or []}

    def document(self, document: dict) -> str:
        return self.artifacts.put(canonical(document), "owner-assessment")["ref"]

    def start(self, launch: str, decision_id: str, correlation_id: str) -> dict:
        command = (list(self.command(decision_id, correlation_id)) if self.command is not None else
                   [*self.argv, "owner-actions", "assess", "--decision", decision_id, "--correlation", correlation_id])
        env = self.environment() if self.environment is not None else None
        return _start_guardian(self, launch, decision_id, command, env=env)

    def poll(self, launch: str) -> dict:
        return _poll_guardian(self, launch)

    def join(self, poll_seconds: float = 0.2) -> None:
        while any(child.poll() is None for child in self.children.values()):
            time.sleep(poll_seconds)


def _start_guardian(port, launch: str, token: str, command: list, *, env=None, cwd=None) -> dict:
    """ONE spawn per launch identity: the exclusive `spawn` marker is created before the guardian exists,
    so a lost response, a restart or a second coordinator gets `cached`, never a second child."""
    require(port.spawn is not None, "Guarded child spawn is not wired")
    directory = launch_directory(port.root, launch)
    if launch in port.children:
        return {"cached": True}
    directory.mkdir(parents=True, exist_ok=True)
    if not _exclusive(directory / "spawn", "owner-actions"):
        return {"cached": True}  # one-shot: this identity was spawned before (a lost response, a restart)
    _write_atomic(directory / "launch.json", {"schema": GUARDIAN_SCHEMA, "launch": launch, "token": token,
                                              "seconds": port.seconds})
    argv = [*port.entry, "--launch", str(directory), "--seconds", repr(float(port.seconds)), "--", *command]
    guardian = port.spawn(argv, env=env) if cwd is None else port.spawn(argv, env=env, cwd=cwd)
    port.children[launch] = guardian
    return {"cached": False, "pid": guardian.pid}


def _poll_guardian(port, launch: str) -> dict:
    child = port.children.get(launch)
    if child is not None and child.poll() is None:
        return {"state": "running", "owned": True}
    port.children.pop(launch, None)
    return observe(launch_directory(port.root, launch))


# ----- the guarded research tick (policy v2 `research`) -----------------------------------------------------
class ResearchLaunches:
    """`probe()` before any effect, `start(launch, program, lane)` once per launch id and `poll(launch)`.

    `repository(lane_id)` is the lane's registered repository path: the child runs there with
    `ZEUS_REPOSITORY`/`HARNESS_REPOSITORY` naming it, so the program's own `repository_mismatch` check sees
    the identity it was registered with. The guardian bound is the implementation allowance plus the
    conductor margin (`domain.policy`), never restated here. `command` (tests: a LABELLED child),
    `spawn`, `resolve` and `run` are the test seams."""

    def __init__(self, root, repository, *, argv=DEFAULT_ARGV, entry=ENTRY_ARGV, command=None, spawn=None,
                 seconds: float | None = None, resolve=None, run=None):
        self.root, self.repository, self.argv, self.entry = Path(root), repository, tuple(argv), tuple(entry)
        self.command, self.spawn, self.run = command, spawn, run
        self.resolve = resolve
        self.seconds = POLICY.task_seconds + CONDUCT_MARGIN_SECONDS if seconds is None else seconds
        self.children: dict = {}

    def probe(self) -> dict:
        """The provider executables the child would resolve on this PATH, each answering `--version`. No
        model call and no store; anything unresolved or failing is `ok: false` with a fixed code."""
        # S6 seams: the provider resolution (execution) and the chokepoint runner are injected.
        require(self.resolve is not None and self.run is not None, "Research probe is not wired")
        found = self.resolve()
        record = {"ok": False, "codex": found.get("codex"), "node": found.get("node"), "reason_code": None}
        for name in ("codex", "node"):
            if not found.get(name):
                return {**record, "reason_code": name + "_unresolved"}
            try:
                done = self.run([found[name], "--version"], capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
                                check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {**record, "reason_code": name + "_unavailable", "error_type": type(exc).__name__}
            if done.returncode != 0:
                return {**record, "reason_code": name + "_version_failed"}
        return {**record, "ok": True}

    def start(self, launch: str, program_id: str, lane: str) -> dict:
        repository = str(self.repository(lane))
        command = (list(self.command(program_id, launch)) if self.command is not None else
                   [*self.argv, "research-program", "run", program_id, "--ticks", "1", "--cycle-owner", launch,
                    # INV-DISCOVERY-PRESSURE-001: an owner-dispatched research launch answers a recorded failure
                    # family (an incident), so it is exempt from proactive-discovery pressure; stated, not defaulted.
                    "--intent", "incident"])
        env = {**os.environ, "ZEUS_REPOSITORY": repository, "HARNESS_REPOSITORY": repository}
        return _start_guardian(self, launch, launch, command, env=env, cwd=repository)

    def poll(self, launch: str) -> dict:
        return _poll_guardian(self, launch)
