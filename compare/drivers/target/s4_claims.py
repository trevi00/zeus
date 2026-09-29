"""Target driver: `coordination.decision_claims` on the target tree (coordination claim_decision).

The owner id is the first id of a fresh scripted id source (the reference draws it the same way inside
decide_one); clocks are injected; the recovery guard, ticket binding and its superseded type are injected as
composition will.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_claims  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.coordination.application.decision_claims import claim_decision  # noqa: E402
from codex_harness.coordination.application.execution_recovery import (
    ExecutionRecovery,  # noqa: E402
)
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT = PortClock(CLOCK)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000e6e6"  # this process's clock-domain identity
ORG = packaged_organization()


def fresh():
    CLOCK.reset()
    IDS.reset()
    return MemoryStore()


def claim(store, agent, expected=None):
    owner = str(determinism.FakeIds().uuid4())
    row = claim_decision(store, ORG, agent, owner, expected, recovery=ExecutionRecovery(store, ORG, None),
                         ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                         clock=PORT, monotonic=CLOCK.monotonic)
    return row


API = SimpleNamespace(fresh=fresh, claim=claim,
                      envelope=lambda *a, **k: envelope(*a, **k, clock=PORT, ids=PortIds(IDS)), advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "coordination.decision_claims", s4_claims.run(API))
