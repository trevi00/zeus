"""Fleet host migration (INV-FLEET-001, INV-HOST-MIGRATION-001): the D2 registry rebinding.

Memory store and a fabricated TARGET-host observation only; the real observation and a real
PostgreSQL registry are exercised by tests/test_host_migration_pg_rehearsal.py when disposable
servers are named.
"""
from __future__ import annotations

import copy

import pytest

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, BUCKET_REGISTRY, Fleet
from codex_harness.domain.fleet import (
    FleetRefused,
    config_digest,
    repository_identity,
    resolve_repository,
    validate_budget,
)
from codex_harness.domain.fleet_recovery import HOST_MIGRATION_PROOF_SCHEMA, HOST_MIGRATION_SCHEMA

OLD_REPO = "C:\\workspaces\\zeus\\worktrees\\fleet-001"
IDENTITY = "e" * 64
CONFIG = {"schema": "urn:zeus:fleet:1", "id": "zeus-local-fleet", "max_parallel": 2,
          "budget": validate_budget({"total": 160, "per_host": 160}),
          "lanes": [{"id": "harness", "team": "harness", "schema": "zeus_fleet_harness", "redis_namespace": "zeus-fleet-harness",
                     "repository": OLD_REPO, "runtime": "C:\\workspaces\\zeus\\artifacts\\f2h"},
                    {"id": "interface", "team": "interface", "schema": "zeus_fleet_interface",
                     "redis_namespace": "zeus-fleet-interface", "repository": OLD_REPO,
                     "runtime": "C:\\workspaces\\zeus\\artifacts\\f2i"}]}
CONFIG["lanes"] = [{k: lane[k] for k in sorted(lane)} for lane in CONFIG["lanes"]]
# D2: repository /srv/zeus/repo, runtimes per lane, the renamed schemas; ids/teams/namespaces kept.
TARGETS = {"harness": ("/srv/zeus/runtime/lanes/harness", "zeus_aibox_harness"),
           "interface": ("/srv/zeus/runtime/lanes/interface", "zeus_aibox_interface")}


def store(paused=True, jobs=()):
    memory = MemoryStore()
    with memory.transaction() as tx:
        tx.put(BUCKET_REGISTRY, CONFIG["id"], {"id": CONFIG["id"], "schema": CONFIG["schema"], "config": CONFIG,
                                               "config_sha256": config_digest(CONFIG), "registered_at": "t0"})
        for job in jobs:
            tx.put(BUCKET_JOBS, job["id"], job)
    if paused:
        Fleet(memory).pause()
    return memory


def request(**overrides):
    document = {"schema": HOST_MIGRATION_SCHEMA, "fleet": CONFIG["id"], "operator": "owner",
                "migration_id": "aibox-migration-001", "manifest_sha256": "a" * 64,
                "expected_config_sha256": config_digest(CONFIG), "source_repository_identity": IDENTITY,
                "lanes": [{"lane": lane["id"], "repository": {"from": OLD_REPO, "to": "/srv/zeus/repo"},
                           "runtime": {"from": lane["runtime"], "to": TARGETS[lane["id"]][0]},
                           "schema": {"from": lane["schema"], "to": TARGETS[lane["id"]][1]}}
                          for lane in CONFIG["lanes"]],
                "recorded_at": "2026-09-25T09:00:00Z"}
    document.update(overrides)
    return document


def proof(**lane_overrides):
    lanes = []
    for lane in ("harness", "interface"):
        row = {"id": lane, "active_runs": 0, "repository": {"target_identity": IDENTITY, "independent": True},
               "runtime": {"writable": True}, "schema": {"name": TARGETS[lane][1], "provisioned": True},
               "queued_bindings": []}
        row.update(lane_overrides.get(lane, {}))
        lanes.append(row)
    return {"schema": HOST_MIGRATION_PROOF_SCHEMA, "runner": {"state": "stopped"}, "lanes": lanes, "observed_at": "t1"}


def test_d2_rebinds_every_lane_keeps_identities_and_resolves_frozen_history():
    frozen = {"id": "job-1", "lane": "harness", "status": "accepted", "repository": repository_identity(OLD_REPO)}
    memory = store(jobs=[frozen])
    fleet = Fleet(memory)
    result = fleet.migrate_host(request(), proof())
    assert result["migrated"] and result["cached"] is False
    with memory.transaction() as tx:
        registry = tx.get(BUCKET_REGISTRY, CONFIG["id"])
        receipt = tx.scan("fleet_host_migrations")[0]
        job = tx.get(BUCKET_JOBS, "job-1")
        aliases = fleet._repository_aliases(tx)
    lanes = {lane["id"]: lane for lane in registry["config"]["lanes"]}
    assert {k: (v["repository"], v["runtime"], v["schema"]) for k, v in lanes.items()} == \
        {k: ("/srv/zeus/repo", *TARGETS[k]) for k in TARGETS}
    assert [(v["team"], v["redis_namespace"]) for v in lanes.values()] == \
        [("harness", "zeus-fleet-harness"), ("interface", "zeus-fleet-interface")]
    assert receipt["prior_config"] == CONFIG and receipt["prior_config_sha256"] == config_digest(CONFIG)
    assert registry["config_sha256"] == receipt["config_sha256"] != config_digest(CONFIG)
    assert job == frozen  # history keeps its original path identity
    assert resolve_repository(job["repository"], aliases) == repository_identity("/srv/zeus/repo")
    assert fleet.migrate_host(request(), proof())["cached"] is True
    with pytest.raises(FleetRefused, match="host_migration_conflict"):
        fleet.migrate_host(request(recorded_at="2026-09-25T10:00:00Z"), proof())


@pytest.mark.parametrize("mutate, reason", [
    (lambda r: r.update(expected_config_sha256="0" * 64), "config_expected_mismatch"),
    (lambda r: r["lanes"].pop(), "host_migration_lanes_incomplete"),
    (lambda r: r["lanes"][0]["schema"].update(to="public"), "config_invalid"),
    (lambda r: r["lanes"][0]["runtime"].update(**{"from": "C:\\elsewhere"}), "source_binding_mismatch"),
    (lambda r: r["lanes"][0]["repository"].update(to="relative/repo"), "host_migration_invalid"),
    (lambda r: r["lanes"][1]["schema"].update(to="zeus_aibox_harness"), "config_duplicate"),
])
def test_invalid_requests_refuse_without_a_write(mutate, reason):
    memory = store()
    document = request()
    mutate(document)
    with pytest.raises(FleetRefused) as refused:
        Fleet(memory).migrate_host(document, proof())
    assert refused.value.reason_code == reason
    with memory.transaction() as tx:
        assert tx.get(BUCKET_REGISTRY, CONFIG["id"])["config"] == CONFIG
        assert tx.scan("fleet_host_migrations") == []


@pytest.mark.parametrize("lanes, reason", [
    ({"harness": {"repository": {"target_identity": "f" * 64, "independent": True}}}, "repository_identity_mismatch"),
    ({"harness": {"schema": {"name": "zeus_aibox_harness", "provisioned": False}}}, "target_schema_unprovisioned"),
    ({"interface": {"active_runs": 1}}, "lane_run_active"),
    ({"interface": {"runtime": {"writable": False}}}, "runtime_unwritable"),
])
def test_target_observation_failures_refuse(lanes, reason):
    with pytest.raises(FleetRefused) as refused:
        Fleet(store()).migrate_host(request(), proof(**lanes))
    assert refused.value.reason_code == reason


def test_unpaused_fleet_or_running_runner_refuses():
    with pytest.raises(FleetRefused, match="fleet_not_paused"):
        Fleet(store(paused=False)).migrate_host(request(), proof())
    running = proof()
    running["runner"] = {"state": "running"}
    with pytest.raises(FleetRefused, match="runner_not_stopped"):
        Fleet(store()).migrate_host(request(), running)
    queued = {"id": "job-q", "lane": "harness", "status": "queued", "repository": repository_identity(OLD_REPO)}
    with pytest.raises(FleetRefused, match="queued_binding_incomplete"):
        Fleet(store(jobs=[queued])).migrate_host(request(), proof())
    bound = proof(harness={"queued_bindings": [{"job_id": "job-q", "base_present": True, "goal_matches": True}]})
    assert Fleet(store(jobs=[queued])).migrate_host(request(), copy.deepcopy(bound))["migrated"]
