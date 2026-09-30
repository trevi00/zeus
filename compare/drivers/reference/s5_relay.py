"""Reference driver: `coordination.outbox_relay` (M7 outbox.relay / pin_route with M7's message schema and ports)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s5_relay  # noqa: E402

from codex_harness.adapters.contracts import validate_message  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import outbox  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import envelope  # noqa: E402
from codex_harness.ports import MessageDeliveryError, TransportChanged  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
API = SimpleNamespace(MemoryStore=MemoryStore, relay=outbox.relay, pin_route=outbox.pin_route,
                      validate_message=validate_message, MessageDeliveryError=MessageDeliveryError,
                      TransportChanged=TransportChanged, envelope=envelope, advance=CLOCK.advance, org=organization())

if __name__ == "__main__":
    driver.finish("reference", "coordination.outbox_relay", s5_relay.run(API))
