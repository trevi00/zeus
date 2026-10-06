# Ported from SOURCE M7 tests/test_fleet.py, tests/test_operation.py and tests/test_fleet_recovery.py (S5 domain moves,
# DESIGN-s5 D): only the import paths and fixtures are rewritten to the target tree; assertions are unchanged.
# Adaptation: the recovery test's `interrupted` fixture built its job through the application Fleet (not moved in
# this task); here it builds the same job row (id, status, owner_token, lane) and config digest from the moved
# domain functions, so the test body is byte-identical.
import pytest

from codex_harness.coordination.domain.fleet import (
    FleetRefused,
    classify_outcome,
    config_digest,
    new_job,
    paths_conflict,
    validate_config,
)
from codex_harness.coordination.domain.fleet_recovery import (
    EVIDENCE_SCHEMA,
    validate_recovery_evidence,
)
from codex_harness.coordination.domain.operation import (
    ManifestError,
    assignment_message_id,
    validate_manifest,
)
from codex_harness.routing.adapters.provider_policy import packaged_policy

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
GOAL = {"path": "docs/zeus/operations/GOAL.md", "sha256": "b" * 64, "criterion": "one-start entry point",
        "rationale": "the runbook task exercises the entry point"}
TASK = "task-92b13b20"
OPERATION = "op-1"
CORRELATION = "operation:" + OPERATION
RUN = "1a" * 16
CONTAINER = "c7" * 32
RESERVATION = "d4" * 32
SLOT = "e9" * 16
NOW = "2026-09-21T00:00:00+00:00"
FLEET_GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


def config(tmp_path, **overrides):
    lanes = [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")},
             {"id": "b", "team": "beta", "repository": str(tmp_path / "repo-b"), "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": str(tmp_path / "rt-b")}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes, **overrides}


def manifest(**overrides):
    document = {"schema": "urn:zeus:operation:1", "id": "op-001", "base_revision": BASE, "goal": dict(GOAL),
                "plan": {"objective": "Add the RUNBOOK note " + CANARY, "acceptance_criteria": ["focused tests pass"],
                         "allowed_paths": ["docs/zeus/operations/operation-entrypoint-001/RUNBOOK.md"]},
                "budget": {"per_host": 4, "total": 8},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2}}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        if inner:
            document[outer][inner] = value
        else:
            document[outer] = value
    return document


def valid():
    return validate_manifest(manifest(), packaged_policy())


def evidence(job, **overrides):
    document = {"schema": EVIDENCE_SCHEMA, "job_id": job["id"], "operator": "owner",
                "expected": {"status": job["status"], "owner_token": job["owner_token"],
                             "lane": job["lane"], "config_sha256": overrides.pop("config_sha256")},
                "lane_operation": {"id": OPERATION, "correlation_id": CORRELATION, "task_id": TASK,
                                   "generation": 2},
                "container": {"run_id": RUN, "role": "worker", "name": "zeus-worker-" + RUN, "id": CONTAINER},
                "invocation": {"reservation_id": RESERVATION, "status": "unsettled_unknown"},
                "machine_slot": {"id": SLOT, "outcome": "interrupted_unknown"},
                "recorded_at": NOW}
    for key, value in overrides.items():
        document[key] = {**document[key], **value} if isinstance(value, dict) and key in document else value
    return document


def interrupted(tmp_path):
    cfg = validate_config(config(tmp_path))
    lane = [lane for lane in config(tmp_path)["lanes"] if lane["id"] == "a"][0]
    fleet_manifest = validate_manifest({
        "schema": "urn:zeus:operation:1", "id": OPERATION, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + OPERATION, "rationale": CANARY},
        "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": ["docs/x.md"]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())
    job = new_job(fleet_manifest, "m" * 64, lane, FLEET_GOAL, [], NOW)
    job.update(status="dispatching", owner_token="ab" * 16)
    return {"job": job, "lane": lane, "config_sha256": config_digest(cfg)}


def test_config_validation_canonical_digest_and_refusals(tmp_path):
    canonical = validate_config(config(tmp_path))
    assert canonical["lanes"][0] == dict(sorted(config(tmp_path)["lanes"][0].items()))
    assert canonical["max_parallel"] == 2
    lane = config(tmp_path)["lanes"]
    bad = [
        {"schema": "urn:zeus:fleet:2"}, {"id": "bad id"}, {"max_parallel": 0}, {"max_parallel": 3},
        {"max_parallel": True}, {"budget": {"per_host": 4, "total": 2}}, {"budget": {"per_host": "4", "total": 8}},
        {"lanes": []}, {"lanes": lane * 3}, {"lanes": [lane[0], {**lane[1], "id": "a"}]},
        {"lanes": [lane[0], {**lane[1], "schema": "lane_a"}]}, {"lanes": [lane[0], {**lane[1], "redis_namespace": "fleet-a"}]},
        {"lanes": [{**lane[0], "schema": "public"}]}, {"lanes": [{**lane[0], "schema": "pg_temp"}]},
        {"lanes": [{**lane[0], "schema": "Lane-A"}]}, {"lanes": [{**lane[0], "repository": "relative/repo"}]},
        {"lanes": [{**lane[0], "runtime": str(tmp_path / "rt-a") + "/../rt-a"}]},
        {"lanes": [lane[0], {**lane[1], "runtime": str(tmp_path / "rt-a" / "inner")}]},
        {"lanes": [{**lane[0], "runtime": str(tmp_path / "repo-a" / ".runtime")}]},
        {"lanes": [{**lane[0], "dsn": "postgresql://x"}]}, {"token": "x"},
    ]
    for overrides in bad:
        with pytest.raises(FleetRefused) as info:
            validate_config(config(tmp_path, **overrides))
        assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
    assert paths_conflict("Docs/A.md", "docs\\a.md") and paths_conflict("docs", "docs/x/y.md")
    assert not paths_conflict("docs/a.md", "docs/a.md.bak") and not paths_conflict("src", "srcs/x")


def test_classify_outcome_binds_exit_code_to_exact_durable_receipt():
    job = {"operation_id": "op", "manifest_sha256": "m" * 64}
    accepted = {"id": "op", "manifest_sha256": "m" * 64, "status": "accepted", "reason_code": "lead_accepted",
                "calls": {"reserved": 2, "settled": 2}}
    assert classify_outcome(0, accepted, job) == {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0,
                                                  "calls": {"reserved": 2, "settled": 2}, "operation_status": "accepted"}
    assert classify_outcome(1, accepted, job)["status"] == "unknown"
    assert classify_outcome(0, None, job)["reason_code"] == "receipt_missing"
    assert classify_outcome(1, None, job) == {"status": "failed", "reason_code": "child_refused", "exit_code": 1,
                                              "calls": {"reserved": None, "settled": None}, "operation_status": None}
    assert classify_outcome(0, {**accepted, "manifest_sha256": "x" * 64}, job)["reason_code"] == "receipt_mismatch"
    assert classify_outcome(1, {**accepted, "status": "rejected", "reason_code": "lead_rejected"}, job)["status"] == "rejected"
    assert classify_outcome(0, {**accepted, "status": "failed"}, job)["reason_code"] == "exit_contradicts_receipt"
    assert classify_outcome(1, {**accepted, "status": "exhausted", "reason_code": "budget_exhausted"}, job)["status"] == "exhausted"
    assert classify_outcome(1, {**accepted, "status": "running"}, job)["reason_code"] == "lane_operation_not_terminal"
    assert classify_outcome(0, accepted, job, read_error="OperationalError") == {
        "status": "unknown", "reason_code": "lane_read_uncertain", "error_type": "OperationalError", "exit_code": 0,
        "calls": {"reserved": 2, "settled": 2}, "operation_status": "accepted"}
    assert classify_outcome(None, accepted, job)["reason_code"] == "exit_unknown"


@pytest.mark.parametrize("field, value", [
    ("schema", "urn:zeus:operation:2"), ("id", "../x"), ("id", ""), ("base_revision", "abc"), ("extra", 1),
    ("goal.path", "../GOAL.md"), ("goal.path", ".git/config.md"), ("goal.path", "C:\\GOAL.md"), ("goal.path", "goal.txt"),
    ("goal.sha256", "B" * 64), ("goal.criterion", ""), ("plan.acceptance_criteria", []), ("plan.allowed_paths", ["src/../x"]),
    ("plan.allowed_paths", []), ("budget.per_host", True), ("budget.total", 1), ("budget.per_host", "2"),
    ("claude.max_budget_usd", float("inf")), ("claude.max_budget_usd", 50), ("claude.timeout_seconds", 5),
    ("claude.timeout_seconds", 300.0), ("claude.model", "gpt-5"), ("claude.model", True)])
def test_manifest_refuses_unknown_wrong_typed_unsafe_and_out_of_policy_values(field, value):
    with pytest.raises(ManifestError) as info:
        validate_manifest(manifest(**{field: value}), packaged_policy())
    assert CANARY not in str(info.value) and "gpt-5" not in str(info.value)


def test_manifest_accepts_the_documented_example_and_is_deterministic():
    first, second = valid(), valid()
    assert first == second and first["budget"] == {"per_host": 4, "total": 8}
    assert assignment_message_id(first) == assignment_message_id(second)
    assert assignment_message_id(validate_manifest(manifest(id="op-002"), packaged_policy())) != assignment_message_id(first)
    with pytest.raises(ManifestError, match="missing fields"):
        validate_manifest({k: v for k, v in manifest().items() if k != "goal"}, packaged_policy())


# ----- the evidence document ---------------------------------------------------------------
def test_evidence_document_is_strict_and_never_echoes_values(tmp_path):
    setup = interrupted(tmp_path)
    good = evidence(setup["job"], config_sha256=setup["config_sha256"])
    assert validate_recovery_evidence(good) == good
    bad = [
        {"schema": "urn:zeus:fleet-recovery-evidence:2"}, {"job_id": "bad id"}, {"operator": ""},
        {"expected": {"status": "queued"}}, {"expected": {"status": "accepted"}},
        {"expected": {"owner_token": "short"}}, {"expected": {"config_sha256": "x" * 64}},
        {"lane_operation": {"correlation_id": "operation:other"}},
        {"lane_operation": {"generation": 0}}, {"lane_operation": {"generation": True}},
        {"container": {"name": "zeus-worker-other"}}, {"container": {"id": "z" * 64}},
        {"container": {"run_id": RUN.upper()}},
        {"invocation": {"status": "reserved"}}, {"invocation": {"reservation_id": "0" * 63}},
        {"machine_slot": {"outcome": "not a token: " + CANARY}}, {"machine_slot": {"id": SLOT + "00"}},
        {"recorded_at": "2026-09-21T00:00:00"},
        {"recorded_at": None},
    ]
    for override in bad:
        with pytest.raises(FleetRefused) as info:
            validate_recovery_evidence(evidence(setup["job"], config_sha256=setup["config_sha256"], **override))
        assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
    with pytest.raises(FleetRefused, match="recovery_invalid_fields"):
        validate_recovery_evidence({**good, "extra": 1})
    with pytest.raises(FleetRefused, match="recovery_schema"):
        validate_recovery_evidence("not a document")
