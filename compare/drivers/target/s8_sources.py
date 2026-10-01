"""Target driver: `research.sources` on the target tree (S8 pilot 76: the discovery pressure app and adapter moved into research).

The API mirrors the reference driver's names over the target homes, wired as the composition wires them:
- `DiscoveryPressure`: the moved evaluator with coordination's `DiscoveryCensusReader` wired as its `census` port (a subclass: the
  scenario builds it from the store, the policy and the observer; V15), the same reader `composition.discovery_pressure` wires;
- `Fleet`: the S5 target composition's facade (`s5_fleet_composition.FleetFacade`) over the S5 registry/admission/pause/recovery objects,
  with M7's `Fleet._registry` (identical to `coordination.application.fleet.state.registry`, V15) as a static method;
- `discovery_pressure_facts`: M7 `adapters/monitoring.discovery_pressure_facts(store)` is exactly `status(store)` (V13/V14 note), so the
  driver binds that one-line delegation (no S9 dependency);
- `census`: coordination's `discovery_census.census`; the policy half comes from `research.domain.discovery_pressure`.
`patch_urlopen(double)` replaces the name `urlopen` of the moved `research.adapters.research` module with the labelled transport double.
The scenario reads the kernel's default clock where M7 read `utcnow`: the harness's scripted clock reaches it through the kernel `Clock`
port (`kernel.ids.SYSTEM_CLOCK`)."""

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s5_fleet_composition  # noqa: E402
import s8_sources  # noqa: E402
from codex_harness.composition import research_program_adapters as composition  # noqa: E402
from codex_harness.coordination.application.discovery_census_reader import (  # noqa: E402
    DiscoveryCensusReader,
)
from codex_harness.coordination.application.fleet import state as fleet_state  # noqa: E402
from codex_harness.coordination.domain.discovery_census import census  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.observation.adapters.observation_spool import MemorySpool  # noqa: E402
from codex_harness.observation.application.observations import (  # noqa: E402
    MemoryDirectory,
    Observer,
)
from codex_harness.observation.domain.observation import new_process_run_id  # noqa: E402
from codex_harness.research.adapters import research as research_module  # noqa: E402
from codex_harness.research.adapters.discovery_pressure import packaged_policy  # noqa: E402
from codex_harness.research.adapters.research import ResearchSources  # noqa: E402
from codex_harness.research.adapters.research_program import collect_live  # noqa: E402
from codex_harness.research.application import discovery_pressure as application  # noqa: E402
from codex_harness.research.domain import discovery_pressure as domain  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
ids.SYSTEM_CLOCK = PortClock(CLOCK)


class DiscoveryPressure(application.DiscoveryPressure):
    """The moved class with coordination's census reader wired, as `composition.discovery_pressure` wires it."""

    def __init__(self, store, policy_document, observer, *args, **kwargs):
        super().__init__(store, policy_document, observer, *args, census=DiscoveryCensusReader(), **kwargs)


class Fleet(s5_fleet_composition.FleetFacade):
    def __init__(self, store):
        super().__init__(store, lambda: CLOCK.now(timezone.utc).isoformat(), lambda: IDS.uuid4().hex)

    _registry = staticmethod(fleet_state.registry)


def discovery_pressure_facts(store):
    """M7 `adapters/monitoring.discovery_pressure_facts`: exactly `status(store)`."""
    return application.status(store)


@contextmanager
def patch_urlopen(double):
    saved = research_module.urlopen
    research_module.urlopen = double
    try:
        yield
    finally:
        research_module.urlopen = saved


# the composition's own wiring is the production one; the subclass above only lets the scenario build the evaluator from its M7 arguments
assert isinstance(composition.discovery_pressure(MemoryStore(), object()).census, DiscoveryCensusReader)

API = SimpleNamespace(
    ResearchSources=ResearchSources, collect_live=collect_live, packaged_policy=packaged_policy, MemoryStore=MemoryStore,
    MemorySpool=MemorySpool, DiscoveryPressure=DiscoveryPressure, status=application.status, Fleet=Fleet,
    MemoryDirectory=MemoryDirectory, Observer=Observer, new_process_run_id=new_process_run_id,
    discovery_pressure_facts=discovery_pressure_facts, census=census, decide=domain.decide, sample_fresh=domain.sample_fresh,
    unrecorded_hold=domain.unrecorded_hold, validate_intent=domain.validate_intent, validate_policy=domain.validate_policy,
    DiscoveryPaused=domain.DiscoveryPaused, BUCKET=domain.BUCKET, KEY=domain.KEY, PROACTIVE=domain.PROACTIVE,
    EXEMPT_INTENTS=domain.EXEMPT_INTENTS, INTENTS=domain.INTENTS, ContractError=ContractError, patch_urlopen=patch_urlopen)

if __name__ == "__main__":
    driver.finish("target", "research.sources", s8_sources.run(API))
