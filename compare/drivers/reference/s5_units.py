"""Reference driver: the S5 coordination atomic units (REBUILD-DESIGN-v2 §2.9) on M7.

Scenario family `effects.admission_unit` (M7 `MemoryStore`) and, when `ZEUS_REBUILD_PG_DSN` names a labelled
disposable PostgreSQL, `effects.admission_unit.pg` (M7 `PostgresStore`, one fresh schema per case migrated by M7's
own migrator; the durable `documents` rows are read back per case). Fake clock and deterministic ids, reset per case.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import recorder as rec  # noqa: E402
import s5_units  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.contracts import validate_message  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore, PostgresStore  # noqa: E402
from codex_harness.application import (  # noqa: E402,F401
    execution_fence,
    execution_time,
    local_cycle,
    operation,
    operation_finalization,
    outbox,
    workflow,
)
from codex_harness.application.execution_recovery import ExecutionRecovery  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain.model import envelope  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000a5a5"}})
PG_DSN = os.environ.get("ZEUS_REBUILD_PG_DSN")
SCENARIO = "effects.admission_unit.pg" if PG_DSN else "effects.admission_unit"
ORG = organization()
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
        self.store = PostgresStore(self.dsn)
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
    CLOCK.reset()
    IDS.reset()


API = SimpleNamespace(
    backend=Backend, reset=reset, advance=CLOCK.advance, recording=lambda store: rec.RecordingStore(store),
    workflow=lambda store: workflow.Workflow(store, ORG), service=lambda store: Harness(store, ORG),
    operation=lambda service: operation.Operation(service), LocalCycle=local_cycle.LocalCycle,
    Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token),
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
    validate_message=validate_message,
    advance_fence=lambda tx, bucket, row_id, generation, owner: execution_fence.advance(tx, bucket, row_id,
                                                                                       generation, owner),
    envelope=envelope, operation_finalization=operation_finalization, outbox=outbox, org=ORG,
    recovery=lambda store, root: ExecutionRecovery(store, ORG, FileArtifacts(Path(root))),
    artifact_root=lambda: tempfile.mkdtemp(prefix="zeus-s5-units-recovery-"))

if __name__ == "__main__":
    driver.finish("reference", SCENARIO, s5_units.run(API))
