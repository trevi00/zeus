"""Target driver: the S5 coordination atomic units (REBUILD-DESIGN-v2 §2.9) on the target tree.

Scenario family `effects.admission_unit` (target `MemoryStore`) and, when `ZEUS_REBUILD_PG_DSN` names a labelled
disposable PostgreSQL, `effects.admission_unit.pg` (target `PostgresStore`, one fresh schema per case migrated by the
target migrator; the durable `documents` rows are read back per case). The units run through the S5 compositions
(s5_coordination_composition: MessageHandler/Workflow, Operation, LocalCycle; s5_fleet_composition: the four Fleet
objects) with the scripted clock and ids reset per case, as the reference resets its patched sources.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import recorder as rec  # noqa: E402
import s5_coordination_composition as composition  # noqa: E402
import s5_fleet_composition  # noqa: E402
import s5_units  # noqa: E402
from codex_harness.coordination.application import (  # noqa: E402
    execution_fence,
    operation_finalization,
)
from codex_harness.coordination.application.operation import Operation  # noqa: E402
from codex_harness.coordination.domain import operation as operation_domain  # noqa: E402
from codex_harness.evidence.application.inspections import EvidenceRecords  # noqa: E402
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402

PG_DSN = os.environ.get("ZEUS_REBUILD_PG_DSN")
SCENARIO = "effects.admission_unit.pg" if PG_DSN else "effects.admission_unit"
POLICY = packaged_policy()


class Backend:
    """MemoryStore, or a fresh schema on the disposable PostgreSQL with its durable rows readable."""

    def __init__(self, name: str):
        self.schema = None
        if not PG_DSN:
            self.store = MemoryStore()
            return
        import psycopg
        from psycopg.conninfo import make_conninfo

        self.psycopg = psycopg
        self.schema = "s5_" + name
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{self.schema}"')
        self.dsn = make_conninfo(PG_DSN, options=f"-c search_path={self.schema},public")
        self.store = PostgresStore(self.dsn, clock=composition.PORT)
        self.store.migrate()

    def rows(self) -> list:
        if self.schema is None:
            return sorted([b, k, (v or {}).get("status") or ""] for (b, k), v in self.store.data.items())
        with self.psycopg.connect(self.dsn) as conn:
            return sorted([b, k, s or ""] for b, k, s in conn.execute(
                "SELECT bucket, id, body->>'status' FROM documents").fetchall())

    def drop(self) -> None:
        if self.schema is not None:
            with self.psycopg.connect(PG_DSN, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA "{self.schema}" CASCADE')


def reset():
    composition.CLOCK.reset()
    composition.IDS.reset()


def operation(service):
    return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                     evidence_records=EvidenceRecords(), clock=composition.PORT, ids=composition.IDPORT)


API = composition.api(
    backend=Backend, reset=reset, recording=lambda store: rec.RecordingStore(store), operation=operation,
    Fleet=s5_fleet_composition.FleetFacade, operation_finalization=operation_finalization,
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
    advance_fence=lambda tx, bucket, row_id, generation, owner: execution_fence.advance(
        tx, bucket, row_id, generation, owner, clock=composition.PORT))

if __name__ == "__main__":
    driver.finish("target", SCENARIO, s5_units.run(API))
