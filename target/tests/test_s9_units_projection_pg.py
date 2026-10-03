"""S9 units, target-only: the X2a metrics projection joins the Collector's transaction on PostgreSQL (DESIGN-s9-units "Design v1";
DESIGN-s9-X §2.2; INV-OBSERVATION-001).

The `ProjectingStore` aggregates have no SOURCE counterpart, so `effects.s9_units` does not compare them. Integration-gated: skipped
unless `HARNESS_INTEGRATION=1` and a disposable `ZEUS_TEST_DSN` (one fresh schema, dropped after; the `ported/conftest.py` pattern).
A Collector batch whose receipt put fails once leaves NO `observation_metrics` row and no observation; the next pass counts each
event once. A second case fails AFTER the projection has been applied (the batch's last statement), so only PostgreSQL's rollback
can remove the aggregates.
"""
import os
import uuid
from contextlib import contextmanager

import pytest

from codex_harness.observation.adapters.observation_schema import validate_observation
from codex_harness.observation.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.observation.application.metrics_projector import (
    METRICS_BUCKET,
    MetricsProjector,
    ProjectingStore,
)
from codex_harness.observation.application.observations import EVENT_BUCKET, Collector, Observer
from codex_harness.observation.domain.observation import new_process_run_id
from codex_harness.storage.adapters.postgres_store import PostgresStore

PROVIDERS = ("claude-code-cli", "codex-app-server")
RECEIPTS = "observation_collections"
PROJECTED = "zeus_metrics_projected_observations_total"


@pytest.fixture
def pgstore():
    dsn = os.environ.get("ZEUS_TEST_DSN")
    if os.environ.get("HARNESS_INTEGRATION") != "1" or not dsn:
        pytest.skip("Integration environment required (HARNESS_INTEGRATION=1 and a disposable ZEUS_TEST_DSN)")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        store = PostgresStore(make_conninfo(dsn, options=f"-c search_path={schema},public"))
        store.migrate()
        yield store
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class FaultStore:
    """Fails one `put` into `fail_bucket`, or (`fail_after_body`) the unit's last statement, once; a unit fault boundary."""

    def __init__(self, store):
        self.store, self.fail_bucket, self.fail_after_body = store, None, False

    @contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            yield _Faulty(tx, self)
            if self.fail_after_body:
                self.fail_after_body = False
                raise OSError("injected failure after the projection was applied")


class _Faulty:
    def __init__(self, tx, owner):
        self.tx, self.owner = tx, owner

    def __getattr__(self, name):
        return getattr(self.tx, name)

    def put(self, bucket, key, body):
        if bucket == self.owner.fail_bucket:
            self.owner.fail_bucket = None
            raise OSError("injected failure at " + bucket)
        self.tx.put(bucket, key, body)


def build(tmp_path, pgstore):
    base = FaultStore(pgstore)
    projector = MetricsProjector(providers=PROVIDERS)
    root = tmp_path / "obs"
    o = Observer(pgstore, FileSpool(root, new_process_run_id(), max_bytes=1 << 20, fsync=False), component="unit",
                 directory=SpoolDirectory(root), alert_window_seconds=300)
    for seconds in range(3):
        assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": seconds}) is not None
    collector = Collector(ProjectingStore(base, projector), SpoolDirectory(root), validate=validate_observation)
    return base, projector, collector


def stored(pgstore, projector):
    with pgstore.transaction() as tx:
        return {"events": len(tx.scan(EVENT_BUCKET)), "receipts": len(tx.scan(RECEIPTS)),
                "metric_rows": len(tx.scan(METRICS_BUCKET)), "snapshot": projector.snapshot(tx)}


def projected(state):
    [row] = [r for r in state["snapshot"] if r["metric"] == PROJECTED]
    return {tuple(item["labels"]): item["value"] for item in row["series"]}


@pytest.mark.parametrize("fault", ["receipt_put", "after_projection"])
def test_failed_batch_leaves_no_metrics_and_the_next_pass_counts_once(tmp_path, pgstore, fault):
    base, projector, collector = build(tmp_path, pgstore)
    if fault == "receipt_put":
        base.fail_bucket = RECEIPTS
    else:
        base.fail_after_body = True
    failed = collector.collect()
    assert failed["sink_failures"] == 1 and failed["inserted"] == 0
    assert stored(pgstore, projector) == {"events": 0, "receipts": 0, "metric_rows": 0, "snapshot": []}

    again = collector.collect()
    assert again["inserted"] == 3 and again["sink_failures"] == 0
    state = stored(pgstore, projector)
    assert state["events"] == 3 and state["receipts"] == 1 and state["metric_rows"] > 0
    assert projected(state) == {("general",): 3}

    assert collector.collect()["inserted"] == 0   # nothing left in the spool: no second count
    assert projected(stored(pgstore, projector)) == {("general",): 3}
