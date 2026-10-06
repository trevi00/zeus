"""R5 side driver for revision B (the candidate: `src`). Run as `python -I b.py --src <B src> ...`; builds the target use
cases over `storage.adapters.postgres_store.PostgresStore` wrapped by the `RecordingStore`, with fixture transports,
OUTSIDE production composition (critique #14), and runs `steps.Scenario`.

Reused existing compare drivers' composition (imported, files untouched): `drivers/target/s5_fleet_composition`
(`FleetFacade`), `s5_coordination_composition` (`Service`, `PORT`/`IDPORT`/`CLOCK`/`IDS` as the process's sources),
`s4_run_task_composition.run_task_for` and `s4_decision_composition.Composition`. The B target never has its standard
library patched; the fake clock and ids reach it through the kernel ports (`PortClock`/`PortIds`). The Operation wiring is
copied from `drivers/target/s5_operation.py` (a driver script, not importable: it runs `driver.start` at import).
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
sys.path.insert(0, str(common.COMPARE / "drivers" / "target"))
AUDIT = common.SpawnAudit()

import recorder as rec  # noqa: E402
import s4_decision_composition  # noqa: E402
import s4_run_task_composition  # noqa: E402
import s5_coordination_composition as composition  # noqa: E402
import s5_fleet_composition  # noqa: E402
import steps  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.coordination.application import fleet_backlog as backlog_module  # noqa: E402
from codex_harness.coordination.application.operation import Operation  # noqa: E402
from codex_harness.coordination.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.coordination.domain import operation as operation_domain  # noqa: E402
from codex_harness.evidence.application.inspections import EvidenceRecords  # noqa: E402
from codex_harness.intake.domain import backlog as backlog_domain  # noqa: E402
from codex_harness.kernel import ids as kernel_ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402
from s8_fleet_backlog import FakePortfolio, ticking, tokens  # noqa: E402

CLOCK, IDS, PORT, IDPORT, ORG = composition.CLOCK, composition.IDS, composition.PORT, composition.IDPORT, composition.ORG
execution_time.DOMAIN = common.DOMAIN
kernel_ids.SYSTEM_CLOCK = PORT


class B:
    def __init__(self):
        scratch = Path(ARGS.scratch)
        scratch.mkdir(parents=True, exist_ok=True)
        interpreter = scratch / "bin" / "python"
        interpreter.parent.mkdir(exist_ok=True)
        interpreter.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
        interpreter.chmod(0o755)
        self.recorder = rec.Recorder()
        self.store = rec.RecordingStore(PostgresStore(ARGS.dsn), self.recorder)
        self.log = steps.UnitLog(self.recorder)
        policy = packaged_policy()
        self.validate_manifest = lambda document: operation_domain.validate_manifest(document, policy)
        self.loader_api = SimpleNamespace(
            validate_manifest=self.validate_manifest, PLAN_SCHEMA=backlog_domain.PLAN_SCHEMA,
            repository_identity=fleet_domain.repository_identity, BacklogRefused=backlog_domain.BacklogRefused)
        self.fleet_facade = s5_fleet_composition.FleetFacade(self.store, ticking(), tokens())
        self.fleet = self.fleet_facade
        self.backlog = backlog_module.FleetBacklog(self.store, self.fleet_facade.registry, clock=ticking("2026-09-22T00:00:00"),
                                                   portfolio=FakePortfolio(self.loader_api))
        service = composition.Service(self.store)
        self.operation = Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                                   executor=None, bus=None, workflow=None, budget=None, collector=None,
                                   evidence_records=EvidenceRecords(), clock=PORT, ids=IDPORT)
        self.calls: list[str] = []
        claude = (lambda: s4_run_task_composition.ClaudeRefused()) if ARGS.fault == "claude_reached" else None
        transport = common.fixture_transport(steps.PLAN, self.calls, CLOCK.advance, ContractError, claude)
        git = SimpleNamespace(repository=scratch, _git=lambda *a, **kw: "" if a and a[0] == "status" else "revision",
                              inspect=lambda *a: {}, review_workspace=lambda *a: str(scratch))
        artifacts = FileArtifacts(ARGS.artifacts, clock=PORT)
        if ARGS.fault == "codex_unstubbed":
            from codex_harness.execution.adapters.providers.codex_app_server import AppServer

            transport = AppServer  # the REAL host transport, unstubbed: the provider guard refuses its spawn
        run_task, workflow = s4_run_task_composition.run_task_for(
            self.store, ORG, artifacts, git, interpreter, transport, clock=PORT, ids=IDPORT, monotonic=CLOCK.monotonic)
        self._workflow, self._run_task = workflow, run_task
        self.run_task = SimpleNamespace(submit_plan=self._submit_plan, execute=run_task.execute_one,
                                        provider_calls=lambda: len(self.calls))
        self.composition = s4_decision_composition.Composition(self.store, ORG, git, clock=PORT, ids=IDPORT,
                                                               monotonic=CLOCK.monotonic)
        self.decisions = SimpleNamespace(seed=self._seed, decide=self._decide, latest_release_id=self._latest_release)

    def advance(self, seconds):
        CLOCK.advance(seconds)

    def reseed(self, base):
        IDS.counter = base

    def _submit_plan(self, plan):
        self._workflow.submit(envelope("task.assign", "conductor", "lead:improvement", "plan", {"plan": plan}, "fixture",
                                       clock=PORT, ids=IDPORT))

    def _seed(self, phase, actor, candidate, release):
        data = {"candidate": candidate, "source_actor": "worker:implementation", "occurrence_id": "occurrence",
                "source_task_id": "task", "evidence_ref": "fixture:error"}
        if release is not None:
            data["release_id"] = release
        message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement", {}, "correlation",
                           clock=PORT, ids=IDPORT)
        with self.store.transaction() as tx:
            tx.put("decisions_pending", "decision-" + phase, {"id": "decision-" + phase, "actor": actor, "phase": phase,
                   "input": data, "message": message, "status": "pending", "attempt": 0})

    def _decide(self, actor):
        self.composition.verdict = lambda *a, **k: {"execution_ref": "fixture:review", "reason": "fixture finding", "accepted": True}
        return self.composition.decide_one(actor)

    def _latest_release(self):
        with self.store.transaction() as tx:
            rows = sorted(tx.scan("releases"), key=lambda r: r["id"])
        return rows[-1]["id"] if rows else None


def main() -> int:
    side = B()
    if ARGS.mode == "seed":
        steps.dump(Path(ARGS.out), {"seeded": False, "reason": "the fixture copy is seeded by A's driver only"})
        return 0
    scenario = steps.Scenario(side, ARGS.run8)
    result = scenario.run()
    if ARGS.inject_extra:
        bucket, key = ARGS.inject_extra.split("/", 1)
        with side.store.transaction() as tx:
            tx.put(bucket, key, {"id": key, "injected": True})
    common.write_result(ARGS.out, "B", {"src": str(Path(ARGS.src).resolve()), "package": sys.modules["codex_harness"].__file__},
                        result, side.log, AUDIT, {"provider_calls": len(side.calls)})
    return 0 if len(result["completed"]) == len(steps.STEPS) else 3


if __name__ == "__main__":
    sys.exit(main())
