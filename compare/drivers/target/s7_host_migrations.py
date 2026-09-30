"""Target driver: `delivery.host_migrations` on the target tree.

`HostMigrations` takes only a store: it reads no clock and no id source, so nothing is wired beyond the target
`MemoryStore`. The domain names the cases read (`policy`) are delivery's moved `domain.host_migration` module, the
descriptor names are delivery's `domain.host_delivery`, and `digest` is the kernel's."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s7_host_migrations  # noqa: E402
from codex_harness.delivery.application import host_migration as application  # noqa: E402
from codex_harness.delivery.domain import host_migration as policy  # noqa: E402
from codex_harness.delivery.domain.host_delivery import (  # noqa: E402
    DESCRIPTOR_SCHEMA,
    descriptor_digest,
)
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

API = SimpleNamespace(
    MemoryStore=MemoryStore, HostMigrations=application.HostMigrations, BUCKET=application.BUCKET,
    BUCKET_TRANSITIONS=application.BUCKET_TRANSITIONS, BUCKET_CHECKPOINTS=application.BUCKET_CHECKPOINTS,
    policy=policy, DESCRIPTOR_SCHEMA=DESCRIPTOR_SCHEMA, descriptor_digest=descriptor_digest, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "delivery.host_migrations", s7_host_migrations.run(API))
