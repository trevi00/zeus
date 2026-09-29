"""Target driver: `coordination.workflow_lease` on the target tree (the moved-ahead Workflow lease operations).

The clock, the id source and the monotonic clock are injected; intake's ticket_binding is injected as composition
will; the adoption gate (research, S8) is not reached by these tasks, so an adoption stand-in that refuses if it
is ever consulted is injected (it would fail the comparison loudly rather than approve anything).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import functools  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_workflow  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.coordination.application.workflow import Workflow  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel.errors import ExecutionFailure  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, IDPORT = PortClock(CLOCK), PortIds(IDS)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000e5e5"  # this process's clock-domain identity
ORG = packaged_organization()


def adoption_not_reached(tx, details):
    raise AssertionError("the research adoption gate (S8) is not part of this scenario")


API = SimpleNamespace(
    MemoryStore=MemoryStore,
    workflow=lambda store: Workflow(store, ORG, ticket_binding=tickets.ticket_binding,
                                    TicketSuperseded=tickets.TicketSuperseded, adoption=adoption_not_reached,
                                    clock=PORT, ids=IDPORT, monotonic=CLOCK.monotonic),
    envelope=functools.partial(envelope, clock=PORT, ids=IDPORT), ExecutionFailure=ExecutionFailure,
    advance=CLOCK.advance, org=ORG)

if __name__ == "__main__":
    driver.finish("target", "coordination.workflow_lease", s4_workflow.run(API))
