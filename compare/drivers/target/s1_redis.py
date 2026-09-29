"""Target driver: `storage.redis` on the target tree against the same labelled disposable Redis.

The namespace is always passed explicitly (composition supplies it in production) and the storage
token comes from the injected id source.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s1_redis  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.storage.adapters import redis_bus  # noqa: E402
from codex_harness.storage.ports import MessageDeliveryError, TransportChanged  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
CLOCK_PORT, IDS_PORT = PortClock(CLOCK), PortIds(IDS)

API = SimpleNamespace(
    bus=lambda url, namespace: redis_bus.RedisBus(url, namespace, ids=IDS_PORT),
    for_run=lambda url, run_id, namespace: redis_bus.RedisBus.for_run(url, run_id, namespace, ids=IDS_PORT),
    run_namespace=redis_bus.run_namespace, TRANSPORT_SCHEMA=redis_bus.TRANSPORT_SCHEMA, digest=digest,
    envelope=lambda *a, **k: envelope(*a, clock=CLOCK_PORT, ids=IDS_PORT, **k),
    MessageDeliveryError=MessageDeliveryError, TransportChanged=TransportChanged, ContractError=ContractError)

if __name__ == "__main__":
    url = os.environ["ZEUS_REBUILD_REDIS_URL"]
    driver.finish("target", "storage.redis", s1_redis.run(API, url, urlparse(url).path, CLOCK, IDS))
