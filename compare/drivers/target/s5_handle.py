"""Target driver: `coordination.workflow_handle` on the target tree (DESIGN-s5 §M).

The S4 Workflow (submit/claim/complete) is composed with the real, moved `operation_finalization.park` (its clock
injected), and the MessageHandler (handle/cancel/request_rebase/context) runs over that Workflow. The clock, id source
and monotonic clock are injected; the adoption gate is the moved research gate and intake's ticket binding is injected.
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
import s5_handle  # noqa: E402
from codex_harness.coordination.application import (  # noqa: E402
    execution_time,
    operation_finalization,
)
from codex_harness.coordination.application.messages import MessageHandler  # noqa: E402
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


class WorkflowAndMessages:
    """The golden's one M7 `Workflow`: task ownership from the S4 Workflow, messages from the MessageHandler."""

    MESSAGE_METHODS = ("handle", "cancel", "request_rebase", "context")

    def __init__(self, store):
        self.workflow = Workflow(store, ORG, ticket_binding=tickets.ticket_binding,
                                 TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption,
                                 park_terminal=functools.partial(operation_finalization.park, clock=PORT),
                                 clock=PORT, ids=IDPORT, monotonic=CLOCK.monotonic)
        self.messages = MessageHandler(self.workflow)

    def __getattr__(self, name):
        return getattr(self.messages if name in self.MESSAGE_METHODS else self.workflow, name)


API = SimpleNamespace(MemoryStore=MemoryStore, workflow=WorkflowAndMessages,
                      envelope=functools.partial(envelope, clock=PORT, ids=IDPORT), advance=CLOCK.advance, org=ORG)

if __name__ == "__main__":
    driver.finish("target", "coordination.workflow_handle", s5_handle.run(API))
