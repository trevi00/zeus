"""Target driver: `research.program_records` on the target tree (S8 pilot 73: `research.application.research_program`, V11/V13).

The API mirrors the reference driver's names over the target homes. `ResearchProgram` gets its three injected ports (R-p4, R-p5):
coordination's `ResearchLaunchFacts`, the `execution_fence` module (structurally `ExecutionFences`) and the `outbox_relay` module
(structurally `OutboxQuarantine`, through the public `quarantine`). The owner-action row constructors are
`coordination.domain.owner_actions`; the moved Portfolio and audit_progress are the reference API's names over their target homes.
The scenario reads the kernel's default clock where M7 read `utcnow`; the harness's scripted clock reaches it through the kernel
`Clock` port (`kernel.ids.SYSTEM_CLOCK`), the one default `utcnow` reads, and the harness id source replaces the module's `uuid4`."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_program_records  # noqa: E402
from codex_harness.coordination.application import execution_fence, outbox_relay  # noqa: E402
from codex_harness.coordination.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS  # noqa: E402
from codex_harness.coordination.application.research_launch_facts import (  # noqa: E402
    ResearchLaunchFacts,
)
from codex_harness.coordination.domain import owner_actions  # noqa: E402
from codex_harness.intake.application.portfolio import Portfolio, family_id  # noqa: E402
from codex_harness.intake.domain.portfolio import (  # noqa: E402
    BUCKET_INVESTIGATIONS,
    RESEARCH_REQUIRED,
)
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.application import audit_progress as progress_application  # noqa: E402
from codex_harness.research.application import research_program as application  # noqa: E402
from codex_harness.research.domain.audit_progress import LOW_YIELD, candidate_row  # noqa: E402
from codex_harness.research.domain.research_hold import attempt_scope_id  # noqa: E402
from codex_harness.research.domain.research_program import (  # noqa: E402
    ProgramRefused,
    validate_config,
)
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
ids.SYSTEM_CLOCK = PortClock(CLOCK)
application.uuid4 = IDS.uuid4   # the default cycle owner token: the harness id source, as the reference run installed it


class ResearchProgram(application.ResearchProgram):
    """The moved class with its three composition ports wired (a subclass: the scenario also reads class attributes)."""

    def __init__(self, store, **kwargs):
        super().__init__(store, launch_facts=ResearchLaunchFacts(), fences=execution_fence, outbox_quarantine=outbox_relay,
                         **kwargs)


API = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=ResearchProgram, application=application,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES,
    BUCKET_RECOVERIES=application.BUCKET_RECOVERIES, BUCKET_SUCCESSORS=application.BUCKET_SUCCESSORS,
    BUCKET_HEADS=application.BUCKET_HEADS, RUNS=RUNS, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS,
    BUCKET_PROGRESS_STATE=progress_application.BUCKET_STATE, BUCKET_PROGRESS_WINDOWS=progress_application.BUCKET_WINDOWS,
    RESEARCH_REQUIRED=RESEARCH_REQUIRED, Portfolio=Portfolio, family_id=family_id, LOW_YIELD=LOW_YIELD,
    progress_candidate_row=candidate_row, owner_actions=owner_actions, attempt_scope_id=attempt_scope_id, digest=digest,
    ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config, POLICY=packaged_policy())

if __name__ == "__main__":
    driver.finish("target", "research.program_records", s8_program_records.run(API))
