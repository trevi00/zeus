"""Target driver: `coordination.session_checkpoints` on the target tree (the moved-ahead Harness.checkpoint).

The Workflow is built as in s4_submit (real adoption gate, terminal-operation parking a stand-in) and injected into
SessionCheckpoints as composition will; the clock and the id source are injected.
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
import s4_sessions  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.coordination.application.sessions import SessionCheckpoints  # noqa: E402
from codex_harness.coordination.application.workflow import Workflow  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.research.application.audit_gate import require_adoption  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, IDPORT = PortClock(CLOCK), PortIds(IDS)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000e5e5"  # this process's clock-domain identity
ORG = packaged_organization()


def no_operations(tx, message):
    """This scenario creates no operations, so M7 park returns None for every message here; S5 moves
    operation_finalization.park with its own characterization."""
    return None


def build_workflow(store):
    return Workflow(store, ORG, ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                    adoption=require_adoption, park_terminal=no_operations, clock=PORT, ids=IDPORT,
                    monotonic=CLOCK.monotonic)


API = SimpleNamespace(
    MemoryStore=MemoryStore,
    workflow=build_workflow,
    checkpoints=lambda store: SessionCheckpoints(store, ORG, workflow=build_workflow(store), ids=IDPORT),
    envelope=functools.partial(envelope, clock=PORT, ids=IDPORT), advance=CLOCK.advance, org=ORG)

if __name__ == "__main__":
    driver.finish("target", "coordination.session_checkpoints", s4_sessions.run(API))
