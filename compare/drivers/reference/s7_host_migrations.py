"""Reference driver: `delivery.host_migrations` (M7 `HostMigrations`, the store-only host-migration receipt recorder).

The API holds plain M7 objects: `MemoryStore` (`adapters.store`), `HostMigrations` and the bucket names `BUCKET`,
`BUCKET_TRANSITIONS`, `BUCKET_CHECKPOINTS` (`application.host_migration`), `policy` (the M7 `domain.host_migration`
module: `MANIFEST_SCHEMA`, `EVIDENCE_SCHEMA`, `TRANSITION_SCHEMA`, `CHECKPOINT_SCHEMA`, `INTENT_SCHEMA`,
`SUCCESSOR_SCHEMA`, `GATES`, `FORWARD`, `REVERSE_STEPS`, `OBSERVATION`, the states, `ROLLBACK_R0`/`ROLLBACK_R1`,
`MigrationRefused`, `validate_manifest`, `validate_transition`, `validate_intent`, `validate_managed_lineage`,
`transition_id`, `managed_consumption_subject`, `managed_canary_subject`, `evidence_receipt`, `reverse_maps`),
`DESCRIPTOR_SCHEMA` and `descriptor_digest` (M7 `domain.host_delivery`) and `digest` (`domain.model`). The module
reads no clock and no id source; `determinism.install` is used as every reference driver does."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_host_migrations  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_migration as application  # noqa: E402
from codex_harness.domain import host_migration as policy  # noqa: E402
from codex_harness.domain.host_delivery import DESCRIPTOR_SCHEMA, descriptor_digest  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
API = SimpleNamespace(
    MemoryStore=MemoryStore, HostMigrations=application.HostMigrations, BUCKET=application.BUCKET,
    BUCKET_TRANSITIONS=application.BUCKET_TRANSITIONS, BUCKET_CHECKPOINTS=application.BUCKET_CHECKPOINTS,
    policy=policy, DESCRIPTOR_SCHEMA=DESCRIPTOR_SCHEMA, descriptor_digest=descriptor_digest, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "delivery.host_migrations", s7_host_migrations.run(API))
