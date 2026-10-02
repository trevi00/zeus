"""Reference driver: `coordination.fleet_backlog` (M7 `application/fleet_backlog.py`: `FleetBacklog`).

The API holds plain M7 objects: `adapters.store.MemoryStore`, the REAL `application.fleet.Fleet` (its own `register`, `enqueue`, `admit_one`,
`finalize`, `pause`, `resume`, `status`; `FleetBacklog` receives it as it is), the module's names, `application.portfolio.PortfolioRefused`,
`domain.fleet.repository_identity`/`binding`, `domain.fleet_backlog` (`PLAN_SCHEMA`, `MAX_*`, `BacklogRefused`, `expected_binding`, `new_intent`,
`validate_plan`, `validate_pin`) and `domain.operation.validate_manifest` bound to the packaged provider policy. The scenario passes scripted clocks and
token sources to everything; no default clock is read."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_fleet_backlog  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import fleet_backlog as module  # noqa: E402
from codex_harness.application.fleet import BUCKET_JOBS, Fleet  # noqa: E402
from codex_harness.application.portfolio import PortfolioRefused  # noqa: E402
from codex_harness.domain import fleet as fleet_domain  # noqa: E402
from codex_harness.domain import fleet_backlog as backlog_domain  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
POLICY = packaged_policy()

API = SimpleNamespace(
    MemoryStore=MemoryStore, Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token), FleetClass=Fleet,
    fleet_port=lambda fleet: fleet, FleetBacklog=module.FleetBacklog, BUCKET_PLANS=module.BUCKET_PLANS, BUCKET_INTENTS=module.BUCKET_INTENTS,
    BUCKET_JOBS=BUCKET_JOBS, OBSERVED_OUTCOMES=module.OBSERVED_OUTCOMES, LOGGER=module.LOGGER, ALL=list(module.__all__),
    PortfolioRefused=PortfolioRefused, repository_identity=fleet_domain.repository_identity, binding=fleet_domain.binding,
    PLAN_SCHEMA=backlog_domain.PLAN_SCHEMA, MAX_ATTEMPTS=backlog_domain.MAX_ATTEMPTS, MAX_DEFERRALS=backlog_domain.MAX_DEFERRALS,
    BacklogRefused=backlog_domain.BacklogRefused, expected_binding=backlog_domain.expected_binding, new_intent=backlog_domain.new_intent,
    validate_plan=backlog_domain.validate_plan, validate_pin=backlog_domain.validate_pin,
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY))

if __name__ == "__main__":
    driver.finish("reference", "coordination.fleet_backlog", s8_fleet_backlog.fleet_backlog(API))
