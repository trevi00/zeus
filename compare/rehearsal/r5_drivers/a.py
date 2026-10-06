"""R5 side driver for revision A (the oracle: M7 `reference/m7/src`, or the rebaseline wheel's tree for the live run;
AMD-1 A). Run as `python -I a.py --src <A src> ...`; builds the M7 use cases over a `PostgresStore` wrapped by the
`RecordingStore`, with fixture transports, OUTSIDE production composition (critique #14), and runs `steps.Scenario`.

M7 specifics (the compare drivers' notes, repeated where they bind here): the clock and uuid4 are the fake sources
installed by `determinism.install`; `envelope()` draws a uuid even when its `message_id` is replaced, so ids are reseeded
per step (`steps.ID_STRIDE`); the executor's `_run` is replaced by the fixture verdict ONLY around a decision (the task
execution uses the stubbed transports), and `executor_module.ClaudeCodeRuntime` is the loud stub.

Reused existing compare drivers (patterns copied with provenance, files untouched): `reference/s4_run_task.py` (the
fixture transport, fixture interpreter, Executor over FileArtifacts), `reference/s4_review_decisions.py` (the seeded
`decisions_pending` row and the fixture verdict), `reference/s8_fleet_backlog.py` (the use-case API), `reference/s5_operation.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

ARGS = common.parse()
common.bootstrap(ARGS.src)
AUDIT = common.SpawnAudit()

import determinism  # noqa: E402
import recorder as rec  # noqa: E402
import steps  # noqa: E402
from codex_harness.adapters import executor as executor_module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import PostgresStore  # noqa: E402
from codex_harness.application import execution_time, operation, workflow  # noqa: E402,F401
from codex_harness.application import fleet_backlog as backlog_module  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.domain import fleet_backlog as backlog_domain  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain.model import ContractError, envelope  # noqa: E402
from s8_fleet_backlog import FakePortfolio, config, ticking, tokens  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={"codex_harness.application.execution_time": {"DOMAIN": common.DOMAIN}})


class A:
    def __init__(self):
        scratch = Path(ARGS.scratch)
        scratch.mkdir(parents=True, exist_ok=True)
        interpreter = scratch / "bin" / "python"
        interpreter.parent.mkdir(exist_ok=True)
        interpreter.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
        interpreter.chmod(0o755)
        sys.executable = str(interpreter)
        self.recorder = rec.Recorder()
        self.store = common.ReadLoggingStore(rec.RecordingStore(PostgresStore(ARGS.dsn), self.recorder))
        self.log = steps.UnitLog(self.recorder)
        self.org = organization()
        self.service = Harness(self.store, self.org)
        policy = packaged_policy()
        self.validate_manifest = lambda document: operation_domain.validate_manifest(document, policy)
        self.loader_api = SimpleNamespace(
            validate_manifest=self.validate_manifest, PLAN_SCHEMA=backlog_domain.PLAN_SCHEMA,
            repository_identity=fleet_domain.repository_identity, BacklogRefused=backlog_domain.BacklogRefused)
        self.fleet = Fleet(self.store, clock=ticking(), token=tokens())
        self.backlog = backlog_module.FleetBacklog(self.store, self.fleet, clock=ticking("2026-09-22T00:00:00"),
                                                   portfolio=FakePortfolio(self.loader_api))
        self.operation = operation.Operation(self.service, None, None, None, None, None)
        self.calls: list[str] = []
        fault = ARGS.fault
        claude = (lambda: executor_module.ClaudeCodeRuntime()) if fault == "claude_reached" else None
        if fault != "codex_unstubbed":
            executor_module.AppServer = common.fixture_transport(steps.PLAN, self.calls, CLOCK.advance, ContractError, claude)
        executor_module.ClaudeCodeRuntime = common.ClaudeRefused
        git = SimpleNamespace(repository=scratch, _git=lambda *a, **kw: "" if a and a[0] == "status" else "revision",
                              inspect=lambda *a: {}, review_workspace=lambda *a: str(scratch))
        self.executor = Executor(self.service, git, FileArtifacts(ARGS.artifacts))
        self.observed = common.tap_observer(self.executor.observer)
        self.run_task = SimpleNamespace(submit_plan=self._submit_plan, execute=self.executor.execute_one,
                                        provider_calls=lambda: len(self.calls))
        self.decisions = SimpleNamespace(seed=self._seed, decide=self._decide, latest_release_id=self._latest_release)

    # -- scenario seams ---------------------------------------------------------------------------------------
    def advance(self, seconds):
        CLOCK.advance(seconds)

    def reseed(self, base):
        IDS.counter = base

    @property
    def recorder_view(self):
        return self.log

    def _submit_plan(self, plan):
        self.executor.workflow.submit(envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": plan}, "fixture"))

    def _seed(self, phase, actor, candidate, release):
        data = {"candidate": candidate, "source_actor": "worker:implementation", "occurrence_id": "occurrence",
                "source_task_id": "task", "evidence_ref": "fixture:error"}
        if release is not None:
            data["release_id"] = release
        message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement", {}, "correlation")
        with self.store.transaction() as tx:
            tx.put("decisions_pending", "decision-" + phase, {"id": "decision-" + phase, "actor": actor, "phase": phase,
                   "input": data, "message": message, "status": "pending", "attempt": 0})

    def _decide(self, actor):
        saved = self.executor._run
        self.executor._run = lambda *a, **k: {"execution_ref": "fixture:review", "reason": "fixture finding", "accepted": True}
        try:
            return self.executor.decide_one(actor)
        finally:
            self.executor._run = saved

    def _latest_release(self):
        with self.store.transaction() as tx:
            rows = sorted(tx.scan("releases"), key=lambda r: r["id"])
        return rows[-1]["id"] if rows else None


def main() -> int:
    side = A()
    if ARGS.mode == "seed":
        side.store.migrate()
        side.fleet.register(config())
        side.fleet.pause()
        steps.dump(Path(ARGS.out), {"seeded": True})
        return 0
    if ARGS.inject_readonly:
        def _ro():
            with side.store.transaction() as tx:
                tx.get("rh_injected", "read-only")

        side.inject_readonly = _ro
    scenario = steps.Scenario(side, ARGS.run8)
    result = scenario.run()
    if ARGS.inject_extra:
        bucket, key = ARGS.inject_extra.split("/", 1)
        with side.store.transaction() as tx:
            tx.put(bucket, key, {"id": key, "injected": True})
    common.write_result(ARGS.out, "A", {"src": str(Path(ARGS.src).resolve()), "package": sys.modules["codex_harness"].__file__},
                        result, side.log, AUDIT, {"provider_calls": len(side.calls), "observer_events": side.observed})
    return 0 if len(result["completed"]) == len(steps.STEPS) else 3


if __name__ == "__main__":
    sys.exit(main())
