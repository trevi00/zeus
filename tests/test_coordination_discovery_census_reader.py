"""S8 pilot 76: coordination's `DiscoveryCensusReader` runs the census block of M7 `DiscoveryPressure._evaluate` over M7-shaped rows
(INV-DISCOVERY-PRESSURE-001; DESIGN-s8 V15). Checked on the TARGET against labelled fixture rows and literals."""
from codex_harness.coordination.application.discovery_census_reader import DiscoveryCensusReader
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.domain.discovery_census import census
from codex_harness.coordination.domain.fleet import effective_config
from codex_harness.intake.domain.backlog import BUCKET_INTENTS, BUCKET_PLANS
from codex_harness.kernel.ids import digest
from codex_harness.storage.adapters.memory_store import MemoryStore

T0 = "2026-09-22T00:00:00+00:00"
BUDGET = {"per_host": 192, "total": 192, "mode": "subscription"}  # LABELLED FIXTURE (the sources scenario's)
CONFIG = {
    "schema": "urn:zeus:fleet:1", "id": "fleet-fixture", "max_parallel": 2, "budget": dict(BUDGET),
    "lanes": [{"id": lane, "team": lane, "repository": "/fixture/repo-" + lane, "schema": "lane_" + lane,
               "redis_namespace": "fleet-" + lane, "runtime": "/fixture/rt-" + lane} for lane in ("a", "b")]}


class Recording:
    """A transaction view that records every read as (operation, bucket)."""

    def __init__(self, tx):
        self.tx, self.reads = tx, []

    def scan(self, bucket):
        self.reads.append(("scan", bucket))
        return self.tx.scan(bucket)

    def get(self, bucket, key):
        self.reads.append(("get", bucket, key))
        return self.tx.get(bucket, key)

    def put(self, *args):
        raise AssertionError("the census reader writes nothing")


def job(job_id, status="queued", lane="a", paths=("src/x/",)):
    return {"id": job_id, "status": status, "lane": lane, "repository": "/fixture/repo-" + lane, "dependencies": [],
            "created_at": T0, "updated_at": T0, "manifest": {"budget": dict(BUDGET), "plan": {"allowed_paths": list(paths)}}}


def fixture_store():
    store = MemoryStore()
    FleetRegistry(store).register(CONFIG)
    with store.transaction() as tx:
        tx.put("fleet_jobs", "qa0", job("qa0", paths=("src/a0/",)))
        tx.put("fleet_jobs", "run-a", job("run-a", status="dispatching", paths=("src/shared/",)))
        tx.put(BUCKET_PLANS, "plan-1", {"plan_id": "plan-1", "plan": {"enabled": False, "items": []}, "plan_sha256": "c" * 64})
    return store


def test_the_reads_are_m7s_in_m7s_order_and_the_bundle_is_the_census_and_the_config_digest():
    store, ledger = fixture_store(), {"host": "fixture", "this_host": 0, "all_hosts": 0, "unreadable": 0}
    with store.transaction() as tx:
        recording = Recording(tx)
        bundle = DiscoveryCensusReader().observe(recording, ledger)
        registry, control = tx.scan("fleet_registry")[0], tx.get("fleet_control", "admission") or {"paused": False}
        expected = census(config=effective_config(registry["config"], control), control=control,
                          jobs={row["id"]: row for row in tx.scan("fleet_jobs")}, units=tx.scan("fleet_units"),
                          plans=tx.scan(BUCKET_PLANS), intents=tx.scan(BUCKET_INTENTS),
                          continuation_intents=tx.scan("continuation_intents"), aliases={}, ledger=ledger)
    assert recording.reads == [
        ("scan", "fleet_registry"), ("get", "fleet_control", "admission"), ("scan", "fleet_jobs"), ("scan", "fleet_units"),
        ("scan", BUCKET_PLANS), ("scan", BUCKET_INTENTS), ("scan", "continuation_intents"),
        ("scan", "fleet_relocations"), ("scan", "fleet_host_migrations")]
    assert list(bundle) == ["observed", "fleet_config_sha256"]
    assert bundle["observed"] == expected and bundle["observed"]["registered"] is True
    assert bundle["fleet_config_sha256"] == digest(CONFIG)


def test_an_unregistered_store_reads_no_aliases_and_has_no_config_digest():
    store = MemoryStore()
    with store.transaction() as tx:
        recording = Recording(tx)
        bundle = DiscoveryCensusReader().observe(recording, None)
    assert bundle == {"observed": {"registered": False}, "fleet_config_sha256": None}
    assert ("scan", "fleet_relocations") not in recording.reads
    assert recording.reads[:2] == [("scan", "fleet_registry"), ("get", "fleet_control", "admission")]
