"""Reference driver: `research.program_tick` (M7 `ProgramRunner.run`/`tick` and the `ResearchProgram` calls they make).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `adapters.research_program`: `ProgramRunner`, `GitCapture`, `CaptureError`,
  `collect_live`; `adapters.operation_cli.GitSource`; `adapters.artifacts.FileArtifacts`; `adapters.research.ResearchSources`
  (the real feed class, whose `fetch` the case replaces); `adapters.monitoring.research_program_facts`;
- `application.research_program`: `ResearchProgram` and the bucket names `BUCKET_PROGRAMS`, `BUCKET_CANDIDATES`,
  `BUCKET_CYCLES`, `BUCKET_DISPATCHES`; `application.autonomous.BUCKET` (`RUNS`); `application.portfolio`: `Portfolio`,
  `family_id`, `BUCKET_INVESTIGATIONS`; `application.fleet.BUCKET_JOBS`;
- `domain.model.ContractError`; `domain.research_program`: `ProgramRefused`, `validate_config`;
  `domain.discovery_pressure.DiscoveryPaused`; `domain.council.validate_any_manifest`; `domain.autonomous.manifest_digest`;
- `POLICY` = `adapters.providers.packaged_policy()` (the `POLICY` of M7's research-program tests, not `domain.policy`);
- `patch(name, value)`: a context manager replacing one name of the `adapters.research_program` module (the
  labelled fault seam, e.g. `derive_manifest`).
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
import s8_program_tick  # noqa: E402

from codex_harness.adapters import monitoring  # noqa: E402
from codex_harness.adapters import research_program as adapter  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.operation_cli import GitSource  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.research import ResearchSources  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import research_program as application  # noqa: E402
from codex_harness.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.application.fleet import BUCKET_JOBS  # noqa: E402
from codex_harness.application.portfolio import (  # noqa: E402
    BUCKET_INVESTIGATIONS,
    Portfolio,
    family_id,
)
from codex_harness.domain.autonomous import manifest_digest  # noqa: E402
from codex_harness.domain.council import validate_any_manifest  # noqa: E402
from codex_harness.domain.discovery_pressure import DiscoveryPaused  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402
from codex_harness.domain.research_program import ProgramRefused, validate_config  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)


@contextmanager
def patch(name, value):
    saved = getattr(adapter, name)
    setattr(adapter, name, value)
    try:
        yield
    finally:
        setattr(adapter, name, saved)


API = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=application.ResearchProgram, ProgramRunner=adapter.ProgramRunner,
    GitCapture=adapter.GitCapture, GitSource=GitSource, CaptureError=adapter.CaptureError, FileArtifacts=FileArtifacts,
    ResearchSources=ResearchSources, collect_live=adapter.collect_live,
    research_program_facts=monitoring.research_program_facts,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES, RUNS=RUNS,
    BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS, Portfolio=Portfolio, family_id=family_id,
    ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config,
    DiscoveryPaused=DiscoveryPaused, validate_any_manifest=validate_any_manifest, manifest_digest=manifest_digest,
    POLICY=packaged_policy(), patch=patch)

if __name__ == "__main__":
    driver.finish("reference", "research.program_tick", s8_program_tick.run(API))
