"""Ported SOURCE main b9d8f15 (S2R) suite `tests/test_fleet_maintenance_readiness.py` run against the target.

Every assertion is S2R's, unchanged. Adaptations are import lines only: `Fleet` is the `m7_coordination` facade over the
split Fleet objects (`maintenance_readiness` routes to `FleetPause`), the bucket and control names are
`coordination.application.fleet.state`'s, `MemoryStore` is storage's.

S2R docstring follows.

INV-HOST-DELIVERY-MAINTENANCE-001: the Fleet's read-only maintenance readiness (the restart phase's only Fleet
read; ALL-PRIMARY-20260930 carries no maintenance admission, so no permit can exist).

The Fleet is the REAL one over an in-memory store; the activation hold, the reserving job and the held unit are
LABELLED injected rows of the product shapes. No lane, process, model or provider is touched.
"""
from __future__ import annotations

import copy

from m7_coordination import Fleet
from test_fleet import config

from codex_harness.coordination.application.fleet.state import (
    ACTIVATION_HOLD,
    BUCKET_CONTROL,
    BUCKET_JOBS,
    BUCKET_UNITS,
    CONTROL_KEY,
)
from codex_harness.storage.adapters.memory_store import MemoryStore


def rows(store) -> dict:
    return copy.deepcopy(store.data)


def put(store, bucket, key, body) -> None:
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def paused_fleet(tmp_path) -> tuple:
    store = MemoryStore()
    fleet = Fleet(store)
    fleet.register(config(tmp_path))
    fleet.pause()
    return store, fleet


def test_an_unregistered_fleet_is_reported_and_nothing_is_written():
    store = MemoryStore()
    before = rows(store)
    assert Fleet(store).maintenance_readiness() == {
        "registered": False, "paused": False, "owner_paused": False, "activation_hold": False, "reserving": [],
        "units_held": [], "open_permits": []}
    assert rows(store) == before


def test_an_owner_paused_quiet_fleet_is_ready_and_the_read_writes_nothing(tmp_path):
    store, fleet = paused_fleet(tmp_path)
    before = rows(store)
    assert fleet.maintenance_readiness() == {
        "registered": True, "paused": True, "owner_paused": True, "activation_hold": False, "reserving": [],
        "units_held": [], "open_permits": []}
    assert rows(store) == before


def test_an_unpaused_fleet_is_not_owner_paused(tmp_path):
    store = MemoryStore()
    fleet = Fleet(store)
    fleet.register(config(tmp_path))
    ready = fleet.maintenance_readiness()
    assert ready["registered"] is True and ready["paused"] is False and ready["owner_paused"] is False


def test_an_activation_hold_is_not_an_owner_pause(tmp_path):
    store, fleet = paused_fleet(tmp_path)
    with store.transaction() as tx:
        control = tx.get(BUCKET_CONTROL, CONTROL_KEY)
    put(store, BUCKET_CONTROL, CONTROL_KEY, {**control, ACTIVATION_HOLD: {"descriptor_sha256": "0" * 64}})
    ready = fleet.maintenance_readiness()
    assert (ready["paused"], ready["owner_paused"], ready["activation_hold"]) == (True, False, True)


def test_reserving_jobs_and_held_units_are_named(tmp_path):
    store, fleet = paused_fleet(tmp_path)
    put(store, BUCKET_JOBS, "job-dispatching", {"id": "job-dispatching", "status": "dispatching", "lane": "a"})
    put(store, BUCKET_JOBS, "job-unknown", {"id": "job-unknown", "status": "unknown", "lane": "b"})
    put(store, BUCKET_JOBS, "job-queued", {"id": "job-queued", "status": "queued", "lane": "a"})
    put(store, BUCKET_JOBS, "job-accepted", {"id": "job-accepted", "status": "accepted", "lane": "a"})
    put(store, BUCKET_UNITS, "unit-held", {"id": "unit-held", "state": "reserved", "kind": "conductor"})
    put(store, BUCKET_UNITS, "unit-released", {"id": "unit-released", "state": "released", "kind": "conductor"})
    ready = fleet.maintenance_readiness()
    assert ready["reserving"] == ["job-dispatching", "job-unknown"]
    assert ready["units_held"] == ["unit-held"] and ready["open_permits"] == []
