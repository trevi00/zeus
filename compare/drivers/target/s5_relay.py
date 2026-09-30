"""Target driver: `coordination.outbox_relay` on the target tree (DESIGN-s5 §O).

The moved relay runs with observation's health owner operation and the injected clock and id source; the fixture bus
validates with the target's own message schema.
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
import s5_relay  # noqa: E402
from codex_harness.coordination.application import outbox_relay  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.observation.application.health import HealthRecords  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.message_schema import validate_message  # noqa: E402
from codex_harness.storage.ports import MessageDeliveryError, TransportChanged  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, IDPORT = PortClock(CLOCK), PortIds(IDS)
API = SimpleNamespace(MemoryStore=MemoryStore,
                      relay=functools.partial(outbox_relay.relay, health=HealthRecords().record, clock=PORT, ids=IDPORT),
                      pin_route=outbox_relay.pin_route, validate_message=validate_message,
                      MessageDeliveryError=MessageDeliveryError, TransportChanged=TransportChanged,
                      envelope=functools.partial(envelope, clock=PORT, ids=IDPORT), advance=CLOCK.advance,
                      org=packaged_organization())

if __name__ == "__main__":
    driver.finish("target", "coordination.outbox_relay", s5_relay.run(API))
