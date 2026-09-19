"""Owner delivery records (local-operations-desk-001): explicitly owner-reported, never inferred.

Everything here runs over MemoryStore. Nothing in this file contacts GitHub or any network: a
record is what the OWNER states after verifying bindings from a preserved receipt, and these tests
assert exactly that boundary, not that a deployment happened.
"""
import json

import pytest

from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, Fleet
from codex_harness.domain.fleet import FleetRefused, validate_delivery
from codex_harness.domain.operation import validate_manifest

BASE = "a" * 40
CANDIDATE = "1" * 40
MERGE = "2" * 40
DEPLOYED = "3" * 40
REF = "sha256:" + "d" * 64
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


def config(tmp_path):
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1,
            "budget": {"per_host": 4, "total": 8},
            "lanes": [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"),
                       "schema": "lane_a", "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")}]}


def manifest(op_id):
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit", "rationale": "r"},
        "plan": {"objective": "o", "acceptance_criteria": ["ok"], "allowed_paths": ["docs/x.md"]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


def document(job_id, **overrides):
    return {"schema": "urn:zeus:owner-delivery:1", "job_id": job_id, "candidate_revision": CANDIDATE,
            "merge_revision": MERGE, "deployed_revision": DEPLOYED,
            "recorded_at": "2026-09-19T10:00:00+00:00", "evidence_refs": [REF],
            "report_url": "https://github.com/owner/repo/pull/157", **overrides}


def accepted_fleet(tmp_path, status="accepted"):
    store = MemoryStore()
    fleet = Fleet(store)
    fleet.register(config(tmp_path))
    job = fleet.enqueue("a", manifest("op-157"), GOAL, [])["job"]
    with store.transaction() as tx:
        row = tx.get(BUCKET_JOBS, job["id"])
        row.update(status=status, owner_token=None, finished_at="2026-09-19T09:00:00+00:00")
        tx.put(BUCKET_JOBS, job["id"], row)
    return fleet, job["id"]


# ----- document validation ---------------------------------------------------------------------
def test_a_complete_document_is_canonicalized():
    canonical = validate_delivery(document("op-157"))
    assert canonical == document("op-157")
    nullable = validate_delivery(document("op-157", deployed_revision=None, report_url=None))
    assert nullable["deployed_revision"] is None and nullable["report_url"] is None


@pytest.mark.parametrize("overrides, field", [
    ({"schema": "urn:zeus:owner-delivery:2"}, None),
    ({"candidate_revision": "short"}, "candidate_revision"),
    ({"candidate_revision": "A" * 40}, "candidate_revision"),
    ({"merge_revision": None}, "merge_revision"),
    ({"deployed_revision": "zz" + "3" * 38}, "deployed_revision"),
    ({"recorded_at": "2026-09-19T10:00:00"}, "recorded_at"),
    ({"recorded_at": "yesterday"}, "recorded_at"),
    ({"recorded_at": 1758276000}, "recorded_at"),
    ({"evidence_refs": []}, "evidence_refs"),
    ({"evidence_refs": ["not-a-digest"]}, "evidence_refs"),
    ({"evidence_refs": [REF, REF]}, "evidence_refs"),
    ({"report_url": "http://github.com/owner/repo"}, "report_url"),
    ({"report_url": "https://example.com/owner/repo"}, "report_url"),
    ({"report_url": "javascript:alert(1)"}, "report_url"),
])
def test_malformed_documents_are_refused_with_a_code_and_a_field(overrides, field):
    with pytest.raises(FleetRefused) as refused:
        validate_delivery(document("op-157", **overrides))
    assert refused.value.reason_code.startswith("delivery_")
    if field is not None:
        assert refused.value.field == field
    assert CANDIDATE not in str(refused.value) and MERGE not in str(refused.value)


def test_unknown_or_missing_fields_are_refused():
    with pytest.raises(FleetRefused, match="delivery_fields"):
        validate_delivery({**document("op-157"), "approved": True})
    incomplete = document("op-157")
    del incomplete["merge_revision"]
    with pytest.raises(FleetRefused, match="delivery_fields"):
        validate_delivery(incomplete)


# ----- recording -------------------------------------------------------------------------------
def test_recording_requires_an_existing_accepted_job(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path, status="queued")
    with pytest.raises(FleetRefused, match="job_not_accepted"):
        fleet.record_delivery(job_id, document(job_id))
    with pytest.raises(FleetRefused, match="job_unknown"):
        fleet.record_delivery("op-unknown", document("op-unknown"))
    assert fleet.delivery(job_id) is None


def test_the_document_must_name_its_own_job(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path)
    with pytest.raises(FleetRefused, match="delivery_job_mismatch"):
        fleet.record_delivery(job_id, document("op-other"))
    assert fleet.delivery(job_id) is None


def test_an_identical_document_replays_and_a_different_one_is_refused(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path)
    first = fleet.record_delivery(job_id, document(job_id))
    assert first["cached"] is False and first["delivery"]["authority"] == "owner_recorded"
    replay = fleet.record_delivery(job_id, document(job_id))
    assert replay["cached"] is True and replay["delivery"] == first["delivery"]
    with pytest.raises(FleetRefused, match="delivery_conflict"):
        fleet.record_delivery(job_id, document(job_id, deployed_revision="4" * 40))
    with pytest.raises(FleetRefused, match="delivery_conflict"):
        fleet.record_delivery(job_id, document(job_id, report_url=None))
    stored = fleet.delivery(job_id)
    assert stored["deployed_revision"] == DEPLOYED and stored["report_url"].endswith("/157")


def test_recording_never_changes_the_job_or_grants_authority(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path)
    with fleet.store.transaction() as tx:
        before = tx.get(BUCKET_JOBS, job_id)
    fleet.record_delivery(job_id, document(job_id))
    with fleet.store.transaction() as tx:
        after = tx.get(BUCKET_JOBS, job_id)
    assert after == before
    assert fleet.status()["jobs"][0]["status"] == "accepted"


def test_merged_and_deployed_stay_distinguishable(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path)
    recorded = fleet.record_delivery(job_id, document(job_id, deployed_revision=None))
    assert recorded["delivery"]["merge_revision"] == MERGE
    assert recorded["delivery"]["deployed_revision"] is None


# ----- projection ------------------------------------------------------------------------------
def test_a_job_without_a_record_keeps_its_exact_shape(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path)
    view = fleet.status()["jobs"][0]
    assert "delivery" not in view  # missing evidence stays unknown, never "not delivered"
    fleet.record_delivery(job_id, document(job_id))
    projected = fleet.status()["jobs"][0]
    assert projected["delivery"] == {"schema": "urn:zeus:owner-delivery:1", "authority": "owner_recorded",
                                     "job_id": job_id, "candidate_revision": CANDIDATE,
                                     "merge_revision": MERGE, "deployed_revision": DEPLOYED,
                                     "recorded_at": "2026-09-19T10:00:00+00:00",
                                     "evidence_refs": [REF],
                                     "report_url": "https://github.com/owner/repo/pull/157"}
    assert {k: v for k, v in projected.items() if k != "delivery"} == view


def test_one_jobs_record_is_never_projected_onto_another(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path)
    fleet.record_delivery(job_id, document(job_id))
    second = fleet.enqueue("a", manifest("op-158"), GOAL, [])["job"]
    with fleet.store.transaction() as tx:
        row = tx.get(BUCKET_JOBS, second["id"])
        row.update(status="accepted", finished_at="2026-09-19T11:00:00+00:00")
        tx.put(BUCKET_JOBS, second["id"], row)
    views = {job["id"]: job for job in fleet.status()["jobs"]}
    assert "delivery" not in views["op-158"] and views["op-157"]["delivery"]["job_id"] == "op-157"


def test_the_projection_carries_no_paths_schemas_or_manifest_text(tmp_path):
    fleet, job_id = accepted_fleet(tmp_path)
    fleet.record_delivery(job_id, document(job_id))
    rendered = json.dumps(fleet.status())
    assert str(tmp_path) not in rendered and "lane_a" not in rendered
