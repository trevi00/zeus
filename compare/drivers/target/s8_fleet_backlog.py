"""Target driver: `coordination.fleet_backlog` on the target tree (S8 pilot 97: `coordination.application.fleet_backlog`).

The API mirrors the reference driver's names over the target homes. The Fleet is the S5 split composed by `s5_fleet_composition.FleetFacade`
(FleetRegistry, AdmissionControl, FleetPause over one store, clock and token source); `fleet_port` hands `FleetBacklog` the facade's `FleetRegistry`,
the object M7's `Fleet` became for `enqueue` (R-fb1). `FleetClass` is `FleetRegistry`, the type of a default-built fleet. The scenario passes scripted
clocks and token sources to everything; the one default clock read (`FleetBacklog(store)`'s `utcnow` on an unregistered tick) is the harness's scripted
clock, reaching the target through the kernel `Clock` port (`kernel.ids.SYSTEM_CLOCK`; the target's standard library is never patched)."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s5_fleet_composition  # noqa: E402
import s8_fleet_backlog  # noqa: E402
from codex_harness.coordination.application import fleet_backlog as module  # noqa: E402
from codex_harness.coordination.application.fleet.registry import FleetRegistry  # noqa: E402
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS  # noqa: E402
from codex_harness.coordination.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.intake.domain import backlog as backlog_domain  # noqa: E402
from codex_harness.intake.domain.portfolio import PortfolioRefused  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from s1_target import PortClock  # noqa: E402

ids.SYSTEM_CLOCK = PortClock(determinism.FakeClock())

COMPOSED = s5_fleet_composition.api()

API = SimpleNamespace(
    MemoryStore=COMPOSED["MemoryStore"], Fleet=COMPOSED["Fleet"], FleetClass=FleetRegistry, fleet_port=lambda fleet: fleet.registry,
    FleetBacklog=module.FleetBacklog, BUCKET_PLANS=module.BUCKET_PLANS, BUCKET_INTENTS=module.BUCKET_INTENTS, BUCKET_JOBS=BUCKET_JOBS,
    OBSERVED_OUTCOMES=module.OBSERVED_OUTCOMES, LOGGER=module.LOGGER, ALL=list(module.__all__), PortfolioRefused=PortfolioRefused,
    repository_identity=fleet_domain.repository_identity, binding=backlog_domain.binding, PLAN_SCHEMA=backlog_domain.PLAN_SCHEMA,
    MAX_ATTEMPTS=backlog_domain.MAX_ATTEMPTS, MAX_DEFERRALS=backlog_domain.MAX_DEFERRALS, BacklogRefused=backlog_domain.BacklogRefused,
    expected_binding=backlog_domain.expected_binding, new_intent=backlog_domain.new_intent, validate_plan=backlog_domain.validate_plan,
    validate_pin=backlog_domain.validate_pin, validate_manifest=COMPOSED["validate_manifest"])

if __name__ == "__main__":
    driver.finish("target", "coordination.fleet_backlog", s8_fleet_backlog.fleet_backlog(API))
