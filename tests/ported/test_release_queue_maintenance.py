"""Ported SOURCE main b9d8f15 (S2R) suite `tests/test_release_queue_maintenance.py` run against the target.

Every assertion is S2R's, unchanged. Adaptations are import lines only: `ReleaseQueue` is the `m7_delivery` shim's
(review's `ReleaseQueue` with the composition's ticket binding, execution fences, clock and ids, as composition wires
it), `MemoryStore` is storage's, `current_fence` coordination's execution fence, `ContractError` and `POLICY` the
kernel's, `MAINTENANCE_SCOPE` review's.

S2R docstring follows.

INV-HOST-DELIVERY-MAINTENANCE-001: the ReleaseQueue maintenance hold.

The hold takes the SAME `deployment_locks:controller` exclusion every controller takes, under its own
execution-fence scope; it never touches a release queue row, attempt, generation or release status; its
`within` commits or rolls back with it; ownership, heartbeat and release are exact-owner only. The
PostgreSQL test runs only with `HARNESS_INTEGRATION=1` (a skip is not evidence)."""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timedelta, timezone

import pytest
from m7_delivery import ReleaseQueue

from codex_harness.coordination.application.execution_fence import current as current_fence
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.policy import POLICY
from codex_harness.review.application.release_queue import MAINTENANCE_SCOPE
from codex_harness.storage.adapters.memory_store import MemoryStore

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)
MID = "active_generation_1:" + "0" * 64


def queued(store, release_id="release-1", status="queued"):
    with store.transaction() as tx:
        tx.put("releases", release_id, {"id": release_id, "status": "reviewed", "candidate": {}})
        tx.put("release_queue", release_id, {"id": release_id, "status": status, "at": NOW.isoformat(), "attempt": 0})


def rows(store, bucket):
    with store.transaction() as tx:
        return copy.deepcopy({row["id"]: row for row in tx.scan(bucket)})


def lock(store):
    with store.transaction() as tx:
        return copy.deepcopy(tx.get("deployment_locks", "controller"))


def test_hold_excludes_claim_and_retry_and_touches_no_queue_row():
    store = MemoryStore()
    queued(store)
    queue = ReleaseQueue(store)
    now = datetime.now(timezone.utc)   # `retry` reads the real clock, so the hold does too here
    before_queue, before_releases = rows(store, "release_queue"), rows(store, "releases")
    claim = queue.hold_maintenance(MID, now=now)
    assert claim["id"] == MID and claim["scope"] == MAINTENANCE_SCOPE and claim["generation"] == 1
    assert lock(store) == {"maintenance_id": MID, "owner": claim["owner"], "lease_until": claim["lease_until"]}
    assert claim["lease_until"] == (now + timedelta(seconds=POLICY.release_lease_seconds)).isoformat()
    # Every ordinary controller is excluded for as long as the lease is held.
    assert queue.claim(now=now + timedelta(seconds=5)) is None
    with store.transaction() as tx:
        tx.put("release_queue", "release-2", {"id": "release-2", "status": "blocked", "at": NOW.isoformat()})
        tx.put("releases", "release-2", {"id": "release-2", "status": "reviewed", "candidate": {}})
    with pytest.raises(ContractError, match="Release controller still running"):
        queue.retry("release-2", "labelled retry while held")
    assert queue.hold_maintenance(MID, now=now + timedelta(seconds=5)) is None
    assert rows(store, "release_queue")["release-1"] == before_queue["release-1"]
    assert rows(store, "releases")["release-1"] == before_releases["release-1"]
    assert queue.release_maintenance(claim) is True
    assert queue.claim(now=now + timedelta(seconds=6))["id"] == "release-1"


def test_within_commits_with_the_hold_or_rolls_back_with_it():
    store = MemoryStore()
    queue = ReleaseQueue(store)
    seen = []

    def write(tx, claim):
        seen.append(claim)
        tx.put("host_delivery_intents", "plan-1", {"id": "plan-1", "generations": [{"id": MID}]})

    claim = queue.hold_maintenance(MID, now=NOW, within=write)
    assert seen == [claim] and rows(store, "host_delivery_intents")["plan-1"]["generations"] == [{"id": MID}]
    queue.release_maintenance(claim)

    before = copy.deepcopy(store.data)

    def refuse(tx, claim):
        tx.put("host_delivery_intents", "plan-2", {"id": "plan-2"})
        raise ContractError("labelled drift inside the hold")

    with pytest.raises(ContractError):
        queue.hold_maintenance(MID, now=NOW + timedelta(seconds=1), within=refuse)
    # The lease, the fence advance and the within's own write all rolled back together.
    assert store.data == before
    with store.transaction() as tx:
        assert current_fence(tx, MAINTENANCE_SCOPE, MID)["generation"] == 1


def test_owned_heartbeat_and_release_are_exact_owner_only():
    store = MemoryStore()
    queue = ReleaseQueue(store)
    first = queue.hold_maintenance(MID, now=NOW)
    with store.transaction() as tx:
        assert queue.owned_maintenance(tx, first, NOW + timedelta(seconds=1))["owner"] == first["owner"]
    renewed = queue.heartbeat_maintenance(first, now=NOW + timedelta(seconds=600))
    assert renewed["lease_until"] == (NOW + timedelta(seconds=600 + POLICY.release_lease_seconds)).isoformat()
    assert lock(store)["lease_until"] == renewed["lease_until"]
    # Expired: the owner itself can no longer write, heartbeat or pretend to hold.
    late = NOW + timedelta(seconds=600 + POLICY.release_lease_seconds + 1)
    with pytest.raises(ContractError, match="Stale maintenance controller"):
        with store.transaction() as tx:
            queue.owned_maintenance(tx, renewed, late)
    with pytest.raises(ContractError):
        queue.heartbeat_maintenance(renewed, now=late)
    # A successor takes the lease; the fence generation increments under a new owner.
    successor = queue.hold_maintenance(MID, now=late)
    assert successor["generation"] == 2 and successor["owner"] != first["owner"]
    for stale in (first, renewed):
        with pytest.raises(ContractError):
            with store.transaction() as tx:
                queue.owned_maintenance(tx, stale, late)
        with pytest.raises(ContractError):
            queue.heartbeat_maintenance(stale, now=late)
        assert queue.release_maintenance(stale) is False
    assert lock(store)["owner"] == successor["owner"]
    # A forged claim that names the successor's owner but an older fence generation is refused too.
    with pytest.raises(ContractError):
        with store.transaction() as tx:
            queue.owned_maintenance(tx, {**successor, "generation": 1}, late)
    # An ordinary controller's lease is never cleared by a maintenance release.
    assert queue.release_maintenance(successor) is True
    queued(store)
    claim = queue.claim(now=late + timedelta(seconds=1))
    assert queue.release_maintenance({**successor, "owner": claim["owner"]}) is False
    assert lock(store)["owner"] == claim["owner"] and lock(store)["release_id"] == "release-1"


def test_a_corrupted_maintenance_fence_fails_closed():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put("execution_fences", MAINTENANCE_SCOPE + ":" + MID, {"generation": "one", "owner": None})
    with pytest.raises(ContractError):
        ReleaseQueue(store).hold_maintenance(MID, now=NOW)
    assert lock(store) is None


def test_postgres_concurrent_hold_and_claim_have_one_owner(isolated_pgstore):
    store = isolated_pgstore
    queued(store)
    queue = ReleaseQueue(store)
    barrier, results = threading.Barrier(2), {}

    def hold():
        barrier.wait()
        results["hold"] = queue.hold_maintenance(MID, now=NOW)

    def claim():
        barrier.wait()
        results["claim"] = queue.claim(now=NOW)

    threads = [threading.Thread(target=hold), threading.Thread(target=claim)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    owners = [name for name in ("hold", "claim") if results.get(name) is not None]
    assert len(owners) == 1, results
    holder = results[owners[0]]
    assert lock(store)["owner"] == holder["owner"]
    later = NOW + timedelta(seconds=POLICY.release_lease_seconds + 1)
    if owners == ["hold"]:
        # Expired and stolen: the old hold cannot write, heartbeat or clear the new lock.
        successor = queue.hold_maintenance(MID, now=later)
        with pytest.raises(ContractError):
            with store.transaction() as tx:
                queue.owned_maintenance(tx, holder, later)
        with pytest.raises(ContractError):
            queue.heartbeat_maintenance(holder, now=later)
        assert queue.release_maintenance(holder) is False
        assert lock(store)["owner"] == successor["owner"]
    else:
        assert queue.hold_maintenance(MID, now=NOW + timedelta(seconds=1)) is None
        stolen = queue.hold_maintenance(MID, now=later)
        assert stolen is not None and lock(store)["owner"] == stolen["owner"]
        with pytest.raises(ContractError):
            queue.heartbeat(holder, now=later)
