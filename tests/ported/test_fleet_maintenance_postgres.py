"""Ported PR-3 suite `tests/test_fleet_maintenance_postgres.py` (e6e15f00, `feat/host-delivery-maintain-pr3`, under Codex review G1-06) run against the target.

Every assertion is PR-3's, unchanged. Adaptations, all import, construction and patch-target: `Fleet` is the `m7_coordination` facade, `BUCKET_MAINTENANCE` is `coordination.application.fleet.state`'s and the domain modules are coordination's. The test stays PostgreSQL-gated (`isolated_pgstore` skips without `HARNESS_INTEGRATION=1` and a disposable `ZEUS_TEST_DSN`; a skip is not evidence).

PR-3 docstring follows.

The one-job maintenance canary permit on real PostgreSQL (INV-FLEET-001 maintenance amendment,
INV-HOST-DELIVERY-MAINTENANCE-001).

These run only with `HARNESS_INTEGRATION=1` against an isolated schema (`isolated_pgstore`); without it
they SKIP, and a skip is not evidence. Every store transaction takes the same control advisory lock,
so concurrent admissions, enqueues and ordinary admission serialize exactly as in production. Owner
action rows are LABELLED fixtures (test_fleet_maintenance.put_action); no process is launched.
"""
import threading

import pytest
from m7_coordination import Fleet
from test_fleet import GOAL, config, manifest
from test_fleet_maintenance import (
    MID,
    Clock,
    admit,
    enqueue_canary,
    permit_for,
    put_action,
    refused,
    row_of,
)

from codex_harness.coordination.application.fleet.state import BUCKET_MAINTENANCE
from codex_harness.coordination.domain.fleet import FleetRefused

pytestmark = pytest.mark.integration


def owner_paused(store, tmp_path) -> tuple[Fleet, dict]:
    f = Fleet(store, clock=Clock())
    f.register(config(tmp_path))
    f.pause()
    permit = permit_for()
    f.grant_maintenance_canary(permit)
    put_action(store, permit)
    enqueue_canary(f, permit)
    return f, permit


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


def test_concurrent_admissions_claim_once_on_postgres(isolated_pgstore, tmp_path):
    f, permit = owner_paused(isolated_pgstore, tmp_path)
    results = run_together([lambda: admit(Fleet(isolated_pgstore, clock=Clock()), permit)["job"]["owner_token"]
                            for _ in range(4)])
    tokens = [r for r in results if isinstance(r, str)]
    assert len(tokens) == 1 and sorted(r for r in results if not isinstance(r, str)) == [
        ("maintenance_already_used", "state")] * 3
    job = row_of(isolated_pgstore, "fleet_jobs", permit["job_id"])
    assert job["status"] == "dispatching" and job["owner_token"] == tokens[0]
    row = row_of(isolated_pgstore, BUCKET_MAINTENANCE, MID)
    assert row["state"] == "admitted" and row["owner_token"] == tokens[0]


def test_concurrent_unrelated_enqueue_and_admit_one_stay_unadmitted(isolated_pgstore, tmp_path):
    f, permit = owner_paused(isolated_pgstore, tmp_path)
    other = Fleet(isolated_pgstore, clock=Clock())
    workers = [lambda: admit(Fleet(isolated_pgstore, clock=Clock()), permit)["job"]["id"],
               lambda: other.enqueue("b", manifest("op-concurrent", ["docs/c.md"]), GOAL, [])["job"]["status"],
               lambda: other.admit_one()["job"],
               lambda: other.admit_one()["job"]]
    results = run_together(workers)
    assert permit["job_id"] in results and results.count(None) == 2, results
    assert other.admit_one()["job"] is None, "the ordinary dispatcher stays paused afterwards too"
    jobs = {job["id"]: job["status"] for job in other.status()["jobs"]}
    assert jobs == {permit["job_id"]: "dispatching", "op-concurrent": "queued"}
    refused(lambda: other.reserve_unit("9" * 64, "conductor", "b", "intent-x"), "paused")


def test_resume_refused_while_a_permit_is_open_on_postgres(isolated_pgstore, tmp_path):
    f, permit = owner_paused(isolated_pgstore, tmp_path)
    control = row_of(isolated_pgstore, "fleet_control", "admission")
    refused(f.resume, "maintenance_debt_unsettled", "maintenance")
    assert row_of(isolated_pgstore, "fleet_control", "admission") == control
    closed = f.close_maintenance_canary(permit, "maintenance_cancelled")
    assert (closed["job_status"], closed["launched"]) == ("failed", False)
    assert f.resume()["paused"] is False
    assert f.admit_one()["job"] is None, "no stale canary executes after the resume"

