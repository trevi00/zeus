"""Reference driver: `research.sources` (M7 `ResearchSources` and the discovery-pressure hold before its fetch).

The API holds plain M7 objects:
- `adapters.research.ResearchSources`; `adapters.research_program.collect_live`; `adapters.discovery_pressure.packaged_policy`;
  `adapters.store.MemoryStore`; `adapters.observation_spool.MemorySpool`; `adapters.monitoring.discovery_pressure_facts`;
- `application.discovery_pressure`: `DiscoveryPressure` and `status`; `application.fleet.Fleet`;
  `application.observations`: `MemoryDirectory`, `Observer`; `domain.observation.new_process_run_id`;
- `domain.discovery_pressure`: `census`, `decide`, `sample_fresh`, `unrecorded_hold`, `validate_intent`, `validate_policy`,
  `DiscoveryPaused`, `BUCKET`, `KEY`, `PROACTIVE`, `EXEMPT_INTENTS`, `INTENTS`; `domain.model.ContractError`;
- `patch_urlopen(double)`: a context manager replacing the name `urlopen` of the `adapters.research` module with a LABELLED
  transport double (the real `urlopen` is never called; the labelled fault seam of the transport cases).
Plain M7 objects or lambdas over them only. The clock and the id source are the harness's (`determinism.install`)."""

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s8_sources  # noqa: E402

from codex_harness.adapters import monitoring  # noqa: E402
from codex_harness.adapters import research as research_module  # noqa: E402
from codex_harness.adapters.discovery_pressure import packaged_policy  # noqa: E402
from codex_harness.adapters.observation_spool import MemorySpool  # noqa: E402
from codex_harness.adapters.research import ResearchSources  # noqa: E402
from codex_harness.adapters.research_program import collect_live  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.discovery_pressure import DiscoveryPressure, status  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.application.observations import MemoryDirectory, Observer  # noqa: E402
from codex_harness.domain import discovery_pressure as domain  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402
from codex_harness.domain.observation import new_process_run_id  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)


@contextmanager
def patch_urlopen(double):
    saved = research_module.urlopen
    research_module.urlopen = double
    try:
        yield
    finally:
        research_module.urlopen = saved


API = SimpleNamespace(
    ResearchSources=ResearchSources, collect_live=collect_live, packaged_policy=packaged_policy, MemoryStore=MemoryStore,
    MemorySpool=MemorySpool, DiscoveryPressure=DiscoveryPressure, status=status, Fleet=Fleet,
    MemoryDirectory=MemoryDirectory, Observer=Observer, new_process_run_id=new_process_run_id,
    discovery_pressure_facts=monitoring.discovery_pressure_facts, census=domain.census, decide=domain.decide,
    sample_fresh=domain.sample_fresh, unrecorded_hold=domain.unrecorded_hold, validate_intent=domain.validate_intent,
    validate_policy=domain.validate_policy, DiscoveryPaused=domain.DiscoveryPaused, BUCKET=domain.BUCKET, KEY=domain.KEY,
    PROACTIVE=domain.PROACTIVE, EXEMPT_INTENTS=domain.EXEMPT_INTENTS, INTENTS=domain.INTENTS, ContractError=ContractError,
    patch_urlopen=patch_urlopen)

if __name__ == "__main__":
    driver.finish("reference", "research.sources", s8_sources.run(API))
