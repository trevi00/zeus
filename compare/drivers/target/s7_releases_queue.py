"""Target driver: `review.releases_queue` on the target tree, wired as composition will wire it.

`ReleaseQueue` takes intake's ticket_binding, coordination's execution_fence module (structurally the
`review.ports.ExecutionFences`) and the clock/id ports; `Releases` takes intake's ticket_binding and
TicketSuperseded, coordination's EventJournal, research's HookRollback and the same ports. The scripted clock and ids
reach the target only through those ports (no patching)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_releases_queue  # noqa: E402
from codex_harness.coordination.application import execution_fence  # noqa: E402
from codex_harness.coordination.application.events import EventJournal  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.research.application.hook_rollback import HookRollback  # noqa: E402
from codex_harness.review.application import release_queue  # noqa: E402
from codex_harness.review.application import releases as review_releases  # noqa: E402
from codex_harness.review.domain import releases as domain  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, IDPORT = PortClock(CLOCK), PortIds(IDS)
ORG = packaged_organization()
API = SimpleNamespace(
    MemoryStore=MemoryStore,
    queue=lambda store: release_queue.ReleaseQueue(store, ticket_binding=tickets.ticket_binding, fences=execution_fence,
                                                   clock=PORT, ids=IDPORT),
    releases=lambda store: review_releases.Releases(
        store, ORG, ticket_binding=tickets.ticket_binding, clock=PORT, ticket_superseded=tickets.TicketSuperseded,
        events=EventJournal(), hooks=HookRollback(), ids=IDPORT),
    POLICY=POLICY, TicketSuperseded=tickets.TicketSuperseded,
    evaluator_successor_id=domain.evaluator_successor_id,
    reverification_successor_id=domain.reverification_successor_id,
    environment_successor_id=domain.environment_successor_id, expected_evaluator_pin=domain.expected_evaluator_pin,
    EnvironmentReverificationRefused=domain.EnvironmentReverificationRefused,
    UnsupportedEvaluatorReverification=domain.UnsupportedEvaluatorReverification, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "review.releases_queue", s7_releases_queue.run(API))
