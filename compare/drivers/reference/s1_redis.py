"""Reference driver: `storage.redis` on SOURCE M7 against a labelled disposable Redis.

M7 `RedisBus` (incarnation identity, bound/unbound publish, group delivery, reclaim, dead-letter,
compaction, run-scoped namespaces). `ZEUS_REBUILD_REDIS_URL` names the runner's network-less
fixture server (Unix socket only). Clock and ids are the scripted fakes patched into this process.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s1_redis  # noqa: E402

from codex_harness.adapters import bus as bus_module  # noqa: E402
from codex_harness.domain.model import ContractError, digest, envelope  # noqa: E402
from codex_harness.ports import MessageDeliveryError, TransportChanged  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    bus=lambda url, namespace: bus_module.RedisBus(url, namespace),
    for_run=lambda url, run_id, namespace: bus_module.RedisBus.for_run(url, run_id, namespace),
    run_namespace=bus_module.run_namespace, TRANSPORT_SCHEMA=bus_module.TRANSPORT_SCHEMA, digest=digest,
    envelope=envelope, MessageDeliveryError=MessageDeliveryError, TransportChanged=TransportChanged,
    ContractError=ContractError)

if __name__ == "__main__":
    url = os.environ["ZEUS_REBUILD_REDIS_URL"]
    driver.finish("reference", "storage.redis", s1_redis.run(API, url, urlparse(url).path, CLOCK, IDS))
