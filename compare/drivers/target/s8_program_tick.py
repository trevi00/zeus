"""Target driver: `research.program_tick` on the target tree (S8 pilot 75: `research.adapters.research` and the pilot 73/74 moves).

The API mirrors the reference driver's names over the target homes, wired as the composition wires them:
- `GitCapture`/`GitSource`: host_os's `process_groups.run_process` and `git_source.GitSource` injected (pilot 74, R-q2), through
  `composition.research_program_adapters.git_capture`'s own keywords;
- `ProgramRunner`: the moved runner with the dge `verify_sources` wired (V14, R-q3b: `composition.research_program_adapters`);
- `ResearchProgram`: its three injected ports (pilot 73, R-p4/R-p5): coordination's `ResearchLaunchFacts`, the `execution_fence` module
  and the `outbox_relay` module;
- `research_program_facts`: M7 `adapters/monitoring.research_program_facts(store)` is exactly `ResearchProgram(store).monitor()`, so
  the driver binds that one-line delegation over the wired `ResearchProgram` (no S9 dependency).
`patch(name, value)` replaces one module attribute of the moved adapter (`derive_manifest`), as M7's patch did: the moved code reads
the module global at call time. The scenario reads the kernel's default clock where M7 read `utcnow`: the harness's scripted clock
reaches it through the kernel `Clock` port (`kernel.ids.SYSTEM_CLOCK`) and the harness id source replaces the module's `uuid4`."""

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
import s8_program_tick  # noqa: E402
from codex_harness.composition import research_program_adapters as composition  # noqa: E402
from codex_harness.coordination.application import execution_fence, outbox_relay  # noqa: E402
from codex_harness.coordination.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS  # noqa: E402
from codex_harness.coordination.application.research_launch_facts import (  # noqa: E402
    ResearchLaunchFacts,
)
from codex_harness.host_os.adapters import git_source, process_groups  # noqa: E402
from codex_harness.intake.application.portfolio import Portfolio, family_id  # noqa: E402
from codex_harness.intake.domain.portfolio import BUCKET_INVESTIGATIONS  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.research.adapters import dge_sources  # noqa: E402
from codex_harness.research.adapters import research_program as adapter  # noqa: E402
from codex_harness.research.adapters.research import ResearchSources  # noqa: E402
from codex_harness.research.application import research_program as application  # noqa: E402
from codex_harness.research.domain.autonomous import manifest_digest  # noqa: E402
from codex_harness.research.domain.council import validate_any_manifest  # noqa: E402
from codex_harness.research.domain.discovery_pressure import DiscoveryPaused  # noqa: E402
from codex_harness.research.domain.research_program import ProgramRefused, validate_config  # noqa: E402
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
ids.SYSTEM_CLOCK = PortClock(CLOCK)
application.uuid4 = IDS.uuid4   # the default cycle owner token: the harness id source, as the reference run installed it


class ResearchProgram(application.ResearchProgram):
    """The moved class with its three composition ports wired (a subclass: the scenario builds it from the store alone)."""

    def __init__(self, store, **kwargs):
        super().__init__(store, launch_facts=ResearchLaunchFacts(), fences=execution_fence, outbox_quarantine=outbox_relay,
                         **kwargs)


class GitCapture(adapter.GitCapture):
    """The moved class with its two host_os ports wired, as `composition.git_capture` wires them."""

    def __init__(self, repository, *args, **kwargs):
        super().__init__(repository, *args, run_process=process_groups.run_process, git_source=git_source.GitSource, **kwargs)


class ProgramRunner(adapter.ProgramRunner):
    """The moved runner with the dge verifier wired (V14), as `composition.program_runner` wires it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, verify_sources=dge_sources.verify_sources, **kwargs)


def research_program_facts(store):
    """M7 `adapters/monitoring.research_program_facts`: exactly `ResearchProgram(store).monitor()`."""
    return ResearchProgram(store).monitor()


@contextmanager
def patch(name, value):
    saved = getattr(adapter, name)
    setattr(adapter, name, value)
    try:
        yield
    finally:
        setattr(adapter, name, saved)


# the composition's own wiring is the production one; the subclasses above only let the scenario build each object from its M7 arguments
assert composition.git_capture(".").run_process is process_groups.run_process
assert composition.program_runner(*([None] * 7), ".", None).verify_sources is dge_sources.verify_sources

API = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=ResearchProgram, ProgramRunner=ProgramRunner, GitCapture=GitCapture,
    GitSource=git_source.GitSource, CaptureError=adapter.CaptureError, FileArtifacts=FileArtifacts,
    ResearchSources=ResearchSources, collect_live=adapter.collect_live, research_program_facts=research_program_facts,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES, RUNS=RUNS,
    BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS, Portfolio=Portfolio, family_id=family_id,
    ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config,
    DiscoveryPaused=DiscoveryPaused, validate_any_manifest=validate_any_manifest, manifest_digest=manifest_digest,
    POLICY=packaged_policy(), patch=patch)

if __name__ == "__main__":
    driver.finish("target", "research.program_tick", s8_program_tick.run(API))
