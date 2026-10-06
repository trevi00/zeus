"""The typed one-use Fleet admission permit on real PostgreSQL (INV-FLEET-001; FA-SPEC §6 tests 1 and 3).

Integration-gated like the ported PG tests: skipped unless `HARNESS_INTEGRATION=1` and a disposable `ZEUS_TEST_DSN` (one
fresh schema, dropped after; the `ported/conftest.py` pattern); a skip is not evidence. Every store transaction takes the
same control advisory lock, so concurrent admissions, enqueues and ordinary admission serialize as in production. The
expected results are FA-SPEC §3 and §6: exactly one claim of the permit's exact job, an unrelated concurrent enqueue
stays QUEUED, the ordinary dispatcher stays paused, and the Fleet control row is untouched. Fixtures are the
LABELLED ones of `test_fleet_admission_permit`; no process is launched.
"""
import json
import os
import threading
import uuid

import pytest
from test_fleet_admission_permit import World, refused
from test_fleet_maintenance import row_of

from codex_harness.coordination.application.fleet.admission_permit import FleetAdmissionPermits
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.storage.adapters.postgres_store import PostgresStore

pytestmark = pytest.mark.integration


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


class PgWorld(World):
    def __init__(self, store, tmp_path):
        from test_fleet import config
        from test_fleet_maintenance import BINDING, Clock

        from codex_harness.coordination.application.fleet.admission import AdmissionControl
        from codex_harness.coordination.application.fleet.maintenance import FleetMaintenance
        from codex_harness.coordination.application.fleet.pause import FleetPause
        from codex_harness.coordination.application.fleet.registry import FleetRegistry

        self.clock, self.store = Clock(), store
        self.registry = FleetRegistry(store, clock=self.clock)
        self.pause = FleetPause(store, clock=self.clock)
        self.admission = AdmissionControl(store, clock=self.clock)
        self.permits = FleetAdmissionPermits(store, clock=self.clock)
        self.maintenance = FleetMaintenance(store, clock=self.clock)
        self.registry.register(config(tmp_path))
        self.pause.pause()
        self.binding, self.action, self.job = dict(BINDING), None, None


def run_together(workers) -> list:
    barrier, results = threading.Barrier(len(workers)), []

    def wrap(work):
        barrier.wait()
        try:
            results.append(work())
        except FleetRefused as exc:
            results.append((exc.reason_code, exc.field))

    threads = [threading.Thread(target=wrap, args=(work,)) for work in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    return results


def test_concurrent_admissions_claim_the_exact_job_once_on_postgres(pgstore, tmp_path):
    w = PgWorld(pgstore, tmp_path).request_canary()
    w.grant()
    control = w.control_bytes()
    results = run_together([lambda: w.admit()["job"]["owner_token"] for _ in range(4)])
    tokens = [r for r in results if isinstance(r, str)]
    assert len(tokens) == 1 and sorted(r for r in results if not isinstance(r, str)) == [
        ("permit_already_used", "state")] * 3
    job = row_of(pgstore, "fleet_jobs", w.job["id"])
    assert job["status"] == "dispatching" and job["owner_token"] == tokens[0]
    assert row_of(pgstore, "fleet_admission_permits", w.permit_id)["owner_token"] == tokens[0]
    assert w.control_bytes() == control


def test_concurrent_unrelated_enqueue_and_ordinary_admission_stay_unadmitted_on_postgres(pgstore, tmp_path):
    from test_fleet import GOAL, manifest

    w = PgWorld(pgstore, tmp_path).request_canary()
    w.grant()
    workers = [lambda: w.admit()["job"]["id"],
               lambda: w.registry.enqueue("b", manifest("op-concurrent", ["docs/c.md"]), GOAL, [])["job"]["status"],
               lambda: w.admission.admit_one()["job"],
               lambda: w.admission.admit_one()["job"]]
    results = run_together(workers)
    assert w.job["id"] in results and results.count(None) == 2, results
    assert w.admission.admit_one()["job"] is None, "the ordinary dispatcher stays paused afterwards too"
    jobs = {job["id"]: job["status"] for job in w.registry.status()["jobs"]}
    assert jobs == {w.job["id"]: "dispatching", "op-concurrent": "queued"}
    refused(lambda: w.admission.reserve_unit("9" * 64, "conductor", "b", "intent-x"), "paused")


def test_concurrent_grants_write_one_permit_row_on_postgres(pgstore, tmp_path):
    w = PgWorld(pgstore, tmp_path).request_canary()
    results = run_together([lambda: w.grant()["cached"] for _ in range(4)])
    assert sorted(results) == [False, True, True, True], results
    assert [row["id"] for row in pgstore_scan(pgstore)] == [w.permit_id]
    assert json.dumps(row_of(pgstore, "fleet_admission_permits", w.permit_id)["history"]).count("acknowledged") == 1


def pgstore_scan(store) -> list:
    with store.transaction() as tx:
        return tx.scan("fleet_admission_permits")

