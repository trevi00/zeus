"""Fleet domain and application over MemoryStore (INV-FLEET-001). Launchers here are labeled
fixtures (fault injection), never `zeus operate run`, Claude or the machine ledger."""
import json
from copy import deepcopy

import pytest

from codex_harness.adapters.monitoring import collect
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet, FleetRunner, LaunchRefused
from codex_harness.domain.fleet import (
    FleetRefused,
    classify_outcome,
    paths_conflict,
    validate_config,
)
from codex_harness.domain.operation import validate_manifest

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40


def config(tmp_path, **overrides):
    lanes = [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")},
             {"id": "b", "team": "beta", "repository": str(tmp_path / "repo-b"), "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": str(tmp_path / "rt-b")}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes, **overrides}


def manifest(op_id, paths, budget=None):
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": CANARY},
        "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": paths},
        "budget": budget or {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


def fleet(tmp_path, **overrides):
    store = MemoryStore()
    f = Fleet(store)
    f.register(config(tmp_path, **overrides))
    return f


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


def test_register_is_idempotent_refuses_mutation_and_hides_paths(tmp_path):
    store = MemoryStore()
    first = Fleet(store).register(config(tmp_path))
    assert first["cached"] is False and str(tmp_path) not in json.dumps(first) and "lane_a" not in json.dumps(first)
    assert Fleet(store).register(config(tmp_path))["cached"] is True
    with pytest.raises(FleetRefused, match="registration_conflict"):
        Fleet(store).register(config(tmp_path, max_parallel=1))
    with pytest.raises(FleetRefused, match="registration_conflict"):
        Fleet(store).register(config(tmp_path, id="fleet-2"))
    with pytest.raises(FleetRefused, match="unregistered"):
        Fleet(MemoryStore()).enqueue("a", manifest("op", ["docs/x.md"]), GOAL, [])
    with pytest.raises(FleetRefused, match="unregistered"):
        Fleet(MemoryStore()).pause()


def test_enqueue_validates_binding_dependencies_and_idempotency(tmp_path):
    f = fleet(tmp_path)
    with pytest.raises(FleetRefused, match="lane_unknown"):
        f.enqueue("z", manifest("op-1", ["docs/x.md"]), GOAL, [])
    with pytest.raises(FleetRefused, match="budget_mismatch"):
        f.enqueue("a", manifest("op-1", ["docs/x.md"], {"per_host": 1, "total": 8}), GOAL, [])
    with pytest.raises(FleetRefused, match="dependency_missing"):
        f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, ["absent"])
    with pytest.raises(FleetRefused, match="dependency_self"):
        f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, ["op-1"])
    first = f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    assert first["cached"] is False and first["job"]["status"] == "queued" and CANARY not in json.dumps(first)
    assert f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])["cached"] is True
    for lane, paths, deps in (("b", ["docs/x.md"], []), ("a", ["docs/y.md"], []), ("a", ["docs/x.md"], ["op-2"])):
        if deps:
            f.enqueue("b", manifest("op-2", ["other/z.md"]), GOAL, [])
        with pytest.raises(FleetRefused, match="binding_conflict"):
            f.enqueue(lane, manifest("op-1", paths), GOAL, deps)
    with pytest.raises(FleetRefused, match="binding_conflict"):
        f.enqueue("a", manifest("op-1", ["docs/x.md"]), {**GOAL, "criterion": "changed"}, [])


def test_admission_capacity_lane_paths_dependencies_pause_and_budget(tmp_path):
    f = fleet(tmp_path)
    same_repo = config(tmp_path)
    same_repo["lanes"][1]["repository"] = same_repo["lanes"][0]["repository"]
    shared = Fleet(MemoryStore())
    shared.register(same_repo)
    # Two lanes over the same repository: a directory prefix conflict with different case blocks.
    shared.enqueue("a", manifest("op-1", ["docs/guide"]), GOAL, [])
    shared.enqueue("b", manifest("op-2", ["Docs/Guide/x.md"]), GOAL, [])
    shared.enqueue("b", manifest("op-3", ["src/free.py"]), GOAL, [])
    first = shared.admit_one()
    assert first["job"]["id"] == "op-1" and first["job"]["status"] == "dispatching" and first["job"]["owner_token"]
    second = shared.admit_one()
    assert second["job"]["id"] == "op-3" and second["blocked"] == {"op-2": "path_conflict"}
    assert {j["id"]: j["reason_code"] for j in shared.status()["jobs"]} == {"op-1": None, "op-2": "path_conflict", "op-3": None}
    assert shared.admit_one()["job"] is None
    assert {j["id"]: j["reason_code"] for j in shared.status()["jobs"]}["op-2"] == "capacity"  # both slots now held
    assert shared.status()["lanes"] == [{"id": "a", "team": "alpha", "active_job": "op-1"},
                                       {"id": "b", "team": "beta", "active_job": "op-3"}]
    # Lane exclusivity and capacity on distinct repositories.
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    f.enqueue("a", manifest("op-2", ["docs/y.md"]), GOAL, [])
    f.enqueue("b", manifest("op-3", ["docs/x.md"]), GOAL, ["op-1"])
    f.enqueue("b", manifest("op-4", ["docs/z.md"]), GOAL, [])
    one = f.admit_one()
    assert one["job"]["id"] == "op-1" and one["blocked"] == {"op-2": "lane_busy", "op-3": "dependency_waiting", "op-4": "capacity"}
    assert {j["id"]: j["reason_code"] for j in f.status()["jobs"]} == {
        "op-1": None, "op-2": "lane_busy", "op-3": "dependency_waiting", "op-4": "capacity"}
    assert f.admit_one(budget_exhausted=True)["blocked"] == {"op-2": "budget_exhausted", "op-3": "budget_exhausted", "op-4": "budget_exhausted"}
    f.pause()
    assert f.status()["paused"] is True and f.admit_one()["blocked"]["op-4"] == "paused"
    assert {j["reason_code"] for j in f.status()["jobs"] if j["status"] == "queued"} == {"paused"}
    f.resume()
    assert f.admit_one()["job"]["id"] == "op-4"
    assert f.admit_one()["blocked"] == {"op-2": "capacity", "op-3": "capacity"}
    # Only the owner finalizes; a failed prerequisite blocks its dependent, not independent work.
    with pytest.raises(FleetRefused, match="owner_mismatch"):
        f.finalize("op-1", "not-the-owner", {"status": "failed", "reason_code": "x"})
    with pytest.raises(FleetRefused, match="not_dispatching"):
        f.finalize("op-2", "t", {"status": "failed", "reason_code": "x"})
    done = f.finalize("op-1", one["job"]["owner_token"], {"status": "failed", "reason_code": "exception:ValueError:" + CANARY, "exit_code": 1})
    assert done["status"] == "failed" and done["reason_code"] == "exception:ValueError"
    f.finalize("op-4", f.store.data["fleet_jobs", "op-4"]["owner_token"], {"status": "unknown", "reason_code": "receipt_missing", "exit_code": 0})
    nxt = f.admit_one()
    assert nxt["job"]["id"] == "op-2" and nxt["blocked"] == {"op-3": "capacity"}  # op-2 + unknown op-4 fill the cap
    # `unknown` retains the lane b reservation; a restart never relaunches it.
    assert f.reconciliation_required() == ["op-2", "op-4"]
    assert f.status()["lanes"][1]["active_job"] == "op-4"
    f.finalize("op-2", f.store.data["fleet_jobs", "op-2"]["owner_token"], {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0, "calls": {"reserved": 2, "settled": 2}})
    assert f.admit_one()["blocked"] == {"op-3": "lane_busy"}  # unknown op-4 still holds lane b
    assert {j["id"]: j["reason_code"] for j in f.status()["jobs"]}["op-3"] == "lane_busy"
    assert CANARY not in json.dumps(f.status()) and str(tmp_path) not in json.dumps(f.status())


def evidence_handoff(**overrides):
    """A fixture copy of the durable operation handoff a lane writes on an evidence refusal."""
    return {"schema": "urn:zeus:operation-evidence-handoff:1", "id": "h" * 64, "status": "pending_owner",
            "owner": "lead:improvement", "next_action": "inspect_evidence_contract",
            "reason_code": "evidence_gate_refused", "operation_id": "op-1", "correlation_id": "operation:op-1",
            "candidate": {"revision": "c" * 40, "path": "D:/secret/" + CANARY},
            "inspection": {"id": "i" * 64, "bound": True, "known": True, "verdict": "incomplete",
                           "passed": [{"check_id": "unit"}],
                           "remaining": [{"check_id": "lint"}, {"check_id": "types"}]}, **overrides}


def test_an_evidence_refused_lane_operation_stays_visible_as_pending_owner(tmp_path):
    f = fleet(tmp_path)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    token = f.admit_one()["job"]["owner_token"]
    view = f.finalize("op-1", token, {"status": "failed", "reason_code": "evidence_gate_refused", "exit_code": 1,
                                      "operation_status": "failed", "owner_handoff": evidence_handoff()})
    handoff = view["owner_handoff"]
    assert view["status"] == "failed" and view["reason_code"] == "evidence_gate_refused", "the outcome is unchanged"
    assert handoff["status"] == "pending_owner" and handoff["owner"] == "lead:improvement"
    assert handoff["next_action"] == "inspect_evidence_contract" and handoff["id"] == "h" * 64
    assert handoff["inspection_id"] == "i" * 64 and handoff["inspection_bound"] is True
    assert handoff["passed"] == 1 and handoff["remaining"] == 2, "counts only, never the items"
    assert "check_id" not in json.dumps(handoff) and CANARY not in json.dumps(handoff)
    assert f.store.data["fleet_jobs", "op-1"]["receipt"]["owner_handoff"] == handoff
    [job] = f.status()["jobs"]
    assert job["owner_handoff"] == handoff, "visible in the status a reader polls, not presented as running"
    assert f.reconciliation_required() == [] and CANARY not in json.dumps(f.status())


@pytest.mark.parametrize("inspection, bound, known", [
    # A handoff retained BEFORE the correction: contradictory flags beside populated item lists.
    ({"id": "i" * 64, "bound": False, "known": True, "verdict": "all_checked",
      "reason_code": "inspection_bound_elsewhere", "passed": [{"check_id": "unit"}, {"check_id": "lint"}],
      "remaining": []}, False, True),
    ({"id": "i" * 64, "bound": True, "known": False, "passed": [{"check_id": "unit"}], "remaining": [{"check_id": "lint"}]}, True, False),
    ({"id": "i" * 64, "bound": "yes", "known": "yes", "passed": [{"check_id": "unit"}], "remaining": []}, False, False),
    ({"id": "i" * 64, "bound": False, "known": False, "reason_code": "execution_binding_incomplete"}, False, False)])
def test_unbound_or_unknown_evidence_never_earns_progress_credit_through_the_fleet(tmp_path, inspection, bound, known):
    """Fleet decides credit itself: only `bound` AND `known` exactly true relay counts, so a stale
    or foreign handoff already on disk shows unknown progress instead of finished work."""
    f = fleet(tmp_path)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    token = f.admit_one()["job"]["owner_token"]
    view = f.finalize("op-1", token, {"status": "failed", "reason_code": "evidence_gate_refused", "exit_code": 1,
                                      "operation_status": "failed",
                                      "owner_handoff": evidence_handoff(inspection=inspection)})
    handoff = view["owner_handoff"]
    assert view["status"] == "failed" and view["reason_code"] == "evidence_gate_refused", "the outcome is unchanged"
    assert handoff["passed"] is None and handoff["remaining"] is None, "null progress, never a count"
    assert handoff["inspection_id"] == "i" * 64 and handoff["inspection_bound"] is bound
    assert handoff["inspection_known"] is known and handoff["inspection_reason_code"] == inspection.get("reason_code")
    assert handoff["status"] == "pending_owner" and handoff["owner"] == "lead:improvement"
    assert handoff["next_action"] == "inspect_evidence_contract" and handoff["id"] == "h" * 64
    assert "verdict" not in handoff and "check_id" not in json.dumps(handoff)
    [job] = f.status()["jobs"]
    assert job["owner_handoff"] == handoff == f.status()["jobs"][0]["owner_handoff"], "repeated reads are identical"
    assert f.store.data["fleet_jobs", "op-1"]["receipt"]["owner_handoff"] == handoff


@pytest.mark.parametrize("document", [None, {"schema": "urn:zeus:other:1"}, "pending_owner", {}])
def test_an_unrecognized_or_absent_handoff_document_is_never_relayed(tmp_path, document):
    f = fleet(tmp_path)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    token = f.admit_one()["job"]["owner_token"]
    view = f.finalize("op-1", token, {"status": "failed", "reason_code": "child_refused", "exit_code": 2,
                                      "owner_handoff": document})
    assert view["owner_handoff"] is None and view["status"] == "failed"
    assert "owner_handoff" not in f.status()["jobs"][0], "a job without a handoff keeps its exact shape"


def ticking():
    """Deterministic clock fixture: strictly increasing ISO timestamps, one per call."""
    counter = iter(range(1, 10_000))
    return lambda: "2026-09-18T00:00:00.%06d+00:00" % next(counter)


def test_queued_reasons_persist_change_only_on_new_facts_and_reach_the_monitor(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from codex_harness.adapters import monitoring
    monkeypatch.setattr(monitoring, "docker_facts", lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, "redis_facts", lambda url, agents: [])
    f = Fleet(MemoryStore(), clock=ticking())
    f.register(config(tmp_path))
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    f.enqueue("b", manifest("op-2", ["docs/y.md"]), GOAL, [])
    f.enqueue("a", manifest("op-3", ["docs/z.md"]), GOAL, ["op-1"])
    row = lambda job_id: f.store.data["fleet_jobs", job_id]  # noqa: E731
    created = {j: row(j)["updated_at"] for j in ("op-1", "op-2", "op-3")}
    # Budget exhaustion is observed and persisted before any claim.
    assert f.admit_one(budget_exhausted=True)["job"] is None
    assert row("op-1")["reason_code"] == row("op-2")["reason_code"] == "budget_exhausted"
    stamped = {j: row(j)["updated_at"] for j in ("op-1", "op-2", "op-3")}
    assert all(stamped[j] > created[j] for j in stamped)
    # Same observation again: no row changes, no timestamp moves (not a heartbeat).
    assert f.admit_one(budget_exhausted=True)["job"] is None
    assert {j: row(j)["updated_at"] for j in ("op-1", "op-2", "op-3")} == stamped
    # Admission clears the reason of the claimed job; the others record the new facts.
    admitted = f.admit_one()
    assert admitted["job"]["id"] == "op-1" and row("op-1")["reason_code"] is None
    assert row("op-1")["updated_at"] > stamped["op-1"]
    assert row("op-2")["reason_code"] == "capacity" and row("op-3")["reason_code"] == "lane_busy"
    f.pause()
    assert f.admit_one()["blocked"] == {"op-2": "paused", "op-3": "paused"}
    f.resume()
    f.finalize("op-1", row("op-1")["owner_token"], {"status": "failed", "reason_code": "child_refused", "exit_code": 2})
    nxt = f.admit_one()
    assert nxt["job"]["id"] == "op-2" and row("op-3")["reason_code"] == "dependency_failed"
    # The reasons survive `status` and the monitor envelope, and a status read writes nothing.
    service, _ = monitoring.read_only(SimpleNamespace(store=f.store, org=SimpleNamespace(agents={})), None)
    before = deepcopy(f.store.data)
    data = collect(service, None, str(tmp_path), "redis://127.0.0.1/0")["sources"]["fleet"]["data"]
    assert {j["id"]: (j["status"], j["reason_code"]) for j in data["jobs"]} == {
        "op-1": ("failed", "child_refused"), "op-2": ("dispatching", None), "op-3": ("queued", "dependency_failed")}
    assert f.store.data == before


def test_authorize_budget_is_idle_only_cas_immutable_and_survives_pause_and_register(tmp_path):
    f = Fleet(MemoryStore(), clock=ticking())
    registered = f.register(config(tmp_path))
    original_digest, original_config = registered["config_sha256"], deepcopy(f.store.data["fleet_registry", "fleet-1"])
    old, new = {"per_host": 4, "total": 8}, {"per_host": 6, "total": 12}
    # Stale expected total, decreasing, invalid and unchanged ceilings are refused without a write.
    before = deepcopy(f.store.data)
    for kwargs, code in (
        (dict(per_host=6, total=12, expected_total=7), "budget_expected_mismatch"),
        (dict(per_host=6, total=12, expected_total=True), "budget_expected_mismatch"),
        (dict(per_host=3, total=12, expected_total=8), "budget_decrease"),
        (dict(per_host=4, total=7, expected_total=8), "budget_decrease"),
        (dict(per_host=4, total=8, expected_total=8), "budget_no_increase"),
        (dict(per_host=0, total=8, expected_total=8), "config_invalid"),
        (dict(per_host=9, total=8, expected_total=8), "config_invalid"),
        (dict(per_host="6", total=12, expected_total=8), "config_invalid"),
    ):
        with pytest.raises(FleetRefused, match=code):
            f.authorize_budget(**kwargs)
    assert f.store.data == before
    with pytest.raises(FleetRefused, match="unregistered"):
        Fleet(MemoryStore()).authorize_budget(6, 12, 8)
    # Queued, dispatching and unknown jobs each refuse the grant; terminal jobs do not.
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    with pytest.raises(FleetRefused, match="fleet_not_idle"):
        f.authorize_budget(6, 12, 8)
    token = f.admit_one()["job"]["owner_token"]
    with pytest.raises(FleetRefused, match="fleet_not_idle"):
        f.authorize_budget(6, 12, 8)
    f.finalize("op-1", token, {"status": "unknown", "reason_code": "receipt_missing", "exit_code": 0})
    with pytest.raises(FleetRefused, match="fleet_not_idle"):
        f.authorize_budget(6, 12, 8)
    assert f.store.data.get(("fleet_control", "admission"))["budget"] == old and f.budget_grants() == []
    idle = Fleet(MemoryStore(), clock=ticking())
    idle.register(config(tmp_path))
    idle.enqueue("a", manifest("op-0", ["docs/x.md"]), GOAL, [])
    idle.finalize("op-0", idle.admit_one()["job"]["owner_token"], {"status": "rejected", "reason_code": "lead_rejected", "exit_code": 1})
    idle.pause()
    granted = idle.authorize_budget(6, 12, 8)
    assert granted["granted"] is True and granted["prior"] == old and granted["budget"] == new and granted["paused"] is True
    # No automatic resume; pause/resume preserve the effective budget; registry/digest untouched.
    assert idle.status()["paused"] is True and idle.status()["budget"] == new
    idle.resume()
    assert idle.status()["paused"] is False and idle.status()["budget"] == new
    idle.pause()
    assert idle.status()["budget"] == new and idle.registered()["config"]["budget"] == new
    assert idle.registered()["config_sha256"] == original_digest
    assert idle.store.data["fleet_registry", "fleet-1"] == original_config
    grants = idle.budget_grants()
    assert len(grants) == 1 and grants[0]["prior"] == old and grants[0]["budget"] == new
    assert grants[0]["config_sha256"] == original_digest and grants[0]["granted_at"] == granted["granted_at"]
    # The original registration stays idempotent and cannot undo the grant.
    assert idle.register(config(tmp_path))["cached"] is True and idle.status()["budget"] == new
    with pytest.raises(FleetRefused, match="registration_conflict"):
        idle.register(config(tmp_path, budget=new))
    assert idle.status()["budget"] == new
    # New manifests must carry the effective ceilings; old ones are refused at enqueue.
    with pytest.raises(FleetRefused, match="budget_mismatch"):
        idle.enqueue("a", manifest("op-old", ["docs/o.md"]), GOAL, [])
    idle.enqueue("a", manifest("op-new", ["docs/n.md"], new), GOAL, [])
    # The historical job keeps its frozen manifest and ceilings.
    assert idle.store.data["fleet_jobs", "op-0"]["manifest"]["budget"] == old
    # The new manifest is admitted under the new ceilings; the fleet drains before the next grant.
    idle.resume()
    token = idle.admit_one()["job"]["owner_token"]
    idle.finalize("op-new", token, {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0})
    # Two competing grants over the same expected total: the second sees the moved total.
    first = idle.authorize_budget(6, 13, 12)
    with pytest.raises(FleetRefused, match="budget_expected_mismatch"):
        Fleet(idle.store).authorize_budget(7, 14, 12)
    assert [g["id"] for g in idle.budget_grants()] == ["grant-00000001", "grant-00000002"]
    assert idle.budget_grants()[1]["prior"] == new and idle.status()["budget"] == first["budget"] == {"per_host": 6, "total": 13}
    assert CANARY not in json.dumps(idle.budget_grants()) and str(tmp_path) not in json.dumps(idle.budget_grants())


def test_admission_blocks_a_queued_job_with_stale_ceilings(tmp_path):
    """Control-plane guard only: the control row is edited directly (fixture) to stand in for a
    grant that raced an enqueue on another connection; the CLI grant itself refuses queued work."""
    f = fleet(tmp_path)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    with f.store.transaction() as tx:
        tx.put("fleet_control", "admission", {**tx.get("fleet_control", "admission"), "budget": {"per_host": 6, "total": 12}})
    decision = f.admit_one()
    assert decision["job"] is None and decision["blocked"] == {"op-1": "budget_stale"}
    assert f.status()["jobs"][0]["reason_code"] == "budget_stale" and f.status()["budget"] == {"per_host": 6, "total": 12}


def test_two_dispatchers_cannot_double_claim_and_projection_bounds_sample(tmp_path):
    f = fleet(tmp_path, max_parallel=1)
    for i in range(102):
        f.enqueue("a", manifest("op-%03d" % i, ["docs/%d.md" % i]), GOAL, [])
    other = Fleet(f.store)
    a, b = f.admit_one(), other.admit_one()
    assert a["job"]["id"] == "op-000" and b["job"] is None and b["blocked"]["op-001"] == "capacity"
    # The first admission persisted `capacity` on all 101 waiting jobs at the same instant as the
    # claim; the second dispatcher observed the same reasons and wrote nothing (timestamps equal).
    rows = {k[1]: v for k, v in f.store.data.items() if k[0] == "fleet_jobs"}
    assert {r["reason_code"] for r in rows.values() if r["status"] == "queued"} == {"capacity"}
    assert len({r["updated_at"] for r in rows.values()}) == 1 and rows["op-000"]["reason_code"] is None
    view = f.status()
    assert view["truncated"] is True and len(view["jobs"]) == 100
    sampled = {j["id"] for j in view["jobs"]}
    assert "op-000" not in sampled and "op-001" not in sampled  # last 100 by (updated_at, id)
    assert all(j["status"] == "queued" and j["reason_code"] == "capacity" for j in view["jobs"])
    # `active_job` is derived from every reserving job, including one outside the sample.
    assert view["lanes"][0]["active_job"] == "op-000" and view["jobs"][-1]["calls"] == {"reserved": None, "settled": None}
    assert set(view["jobs"][0]) == {"id", "lane", "team", "status", "reason_code", "operation_id", "goal",
                                    "dependencies", "calls", "created_at", "updated_at"}
    assert Fleet(MemoryStore()).status() == {"schema": "urn:zeus:fleet-status:1", "registered": False, "lanes": [], "jobs": []}


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


class FakeLauncher:
    """Fixture launcher: records concurrency, never spawns a process."""

    def __init__(self, outcomes, refuse=(), explode=(), exhausted=False):
        self.outcomes, self.refuse, self.explode, self.exhausted = outcomes, refuse, explode, exhausted
        self.running, self.peak, self.launched = set(), 0, []

    def budget_exhausted(self, budget):
        return self.exhausted

    def launch(self, job):
        assert job["status"] == "dispatching" and job["owner_token"]
        if job["id"] in self.refuse:
            raise LaunchRefused("isolation_required")
        if job["id"] in self.explode:
            raise OSError("spawn interrupted (fixture)")
        self.launched.append(job["id"])
        self.running.add(job["id"])
        self.peak = max(self.peak, len(self.running))
        return {"job_id": job["id"]}

    def wait(self, handles, seconds):
        return list(handles)

    def outcome(self, handle, job):
        self.running.discard(handle["job_id"])
        return deepcopy(self.outcomes[handle["job_id"]])


def test_runner_overlaps_independent_jobs_drains_once_and_keeps_unknown(tmp_path):
    f = fleet(tmp_path)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    f.enqueue("b", manifest("op-2", ["docs/y.md"]), GOAL, [])
    f.enqueue("a", manifest("op-3", ["docs/z.md"]), GOAL, ["op-1"])
    f.enqueue("b", manifest("op-4", ["docs/w.md"]), GOAL, [])
    f.enqueue("b", manifest("op-5", ["docs/v.md"]), GOAL, [])
    accepted = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0, "calls": {"reserved": 2, "settled": 2}}
    launcher = FakeLauncher({"op-1": accepted, "op-2": {"status": "rejected", "reason_code": "lead_rejected", "exit_code": 1},
                             "op-3": {"status": "unknown", "reason_code": "receipt_missing", "exit_code": 0}},
                            refuse={"op-4"}, explode={"op-5"})
    sleeps = []
    summary = FleetRunner(f, launcher, sleep=sleeps.append, interval=0).run(once=True)
    assert launcher.peak == 2 and launcher.launched == ["op-1", "op-2", "op-3"]
    assert summary["admitted"] == ["op-1", "op-2", "op-3", "op-4", "op-5"] and sleeps == []
    assert [(x["id"], x["status"]) for x in summary["finalized"]] == [
        ("op-1", "accepted"), ("op-2", "rejected"), ("op-4", "failed"), ("op-5", "unknown"), ("op-3", "unknown")]
    assert summary["reconciliation_required"] == ["op-3", "op-5"] and summary["finalize_failures"] == []
    jobs = {j["id"]: j for j in f.status()["jobs"]}
    assert jobs["op-4"]["reason_code"] == "isolation_required" and jobs["op-5"]["reason_code"] == "spawn_uncertain"
    assert jobs["op-1"]["calls"] == {"reserved": 2, "settled": 2}
    # A restarted runner never relaunches op-3/op-5 and admits nothing new (lanes reserved).
    again = FakeLauncher({})
    assert FleetRunner(f, again, sleep=sleeps.append, interval=0).run(once=True)["admitted"] == [] and again.launched == []
    f.enqueue("a", manifest("op-6", ["docs/u.md"]), GOAL, [])
    stopped = FleetRunner(f, again, sleep=sleeps.append, interval=0)
    stopped.stop()
    assert stopped.run(once=False)["stopped"] is True and again.launched == []
    exhausted = FleetRunner(f, FakeLauncher({}, exhausted=True), sleep=sleeps.append, interval=0).run(once=True)
    assert exhausted["blocked"] == {"op-6": "budget_exhausted"} and exhausted["admitted"] == []
    assert {j["id"]: j["reason_code"] for j in f.status()["jobs"]}["op-6"] == "budget_exhausted"


class CeilingLauncher(FakeLauncher):
    """Fixture launcher that records the ceilings the runner asks about and exhausts the old ones."""

    def __init__(self, outcomes, old):
        super().__init__(outcomes)
        self.old, self.asked = old, []

    def budget_exhausted(self, budget):
        self.asked.append(dict(budget))
        return budget == self.old


def test_running_service_refreshes_effective_ceilings_before_new_admission(tmp_path):
    f = fleet(tmp_path, max_parallel=1)
    old, new = {"per_host": 4, "total": 8}, {"per_host": 5, "total": 9}
    launcher = CeilingLauncher({"op-1": {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0}}, old)
    runner = FleetRunner(f, launcher, interval=0)
    scans = []

    def between_scans(seconds):
        # The service sleeps between scans; the operator grants and enqueues in the meantime.
        scans.append(seconds)
        if len(scans) == 1:
            assert f.authorize_budget(5, 9, 8)["budget"] == new
            f.enqueue("a", manifest("op-1", ["docs/x.md"], new), GOAL, [])
        else:
            runner.stop()
    runner.sleep = between_scans
    summary = runner.run(once=False)
    assert launcher.asked[0] == old and launcher.asked[-1] == new and launcher.launched == ["op-1"]
    assert summary["admitted"] == ["op-1"] and summary["finalized"][0]["status"] == "accepted" and summary["stopped"] is True


def test_monitor_snapshot_carries_fleet_envelope_and_survives_store_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from codex_harness.adapters import monitoring
    monkeypatch.setattr(monitoring, "docker_facts", lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, "redis_facts", lambda url, agents: [])
    f = fleet(tmp_path)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    service, _ = monitoring.read_only(SimpleNamespace(store=f.store, org=SimpleNamespace(agents={})), None)
    before = deepcopy(f.store.data)
    envelope = collect(service, None, str(tmp_path), "redis://127.0.0.1/0")["sources"]["fleet"]
    assert envelope["status"] == "ok" and envelope["data"]["registered"] is True
    assert envelope["data"]["jobs"][0]["status"] == "queued" and envelope["data"]["truncated"] is False
    text = json.dumps(envelope)
    assert CANARY not in text and str(tmp_path) not in text and "lane_a" not in text and "redis://" not in text
    assert f.store.data == before
    empty = collect(monitoring.ReadOnlyService(SimpleNamespace(store=MemoryStore(), org=SimpleNamespace(agents={}))),
                    None, str(tmp_path), "redis://127.0.0.1/0")["sources"]["fleet"]
    assert empty["data"] == {"schema": "urn:zeus:fleet-status:1", "registered": False, "lanes": [], "jobs": []}

    class Broken:
        def transaction(self):
            raise RuntimeError("injected outage (fixture)")
    broken = collect(SimpleNamespace(store=Broken(), org=SimpleNamespace(agents={})), None, str(tmp_path), "redis://x")
    assert broken["sources"]["fleet"] == {"status": "unavailable", "observed_at": broken["sources"]["fleet"]["observed_at"],
                                          "error": "RuntimeError", "data": None}


# ----- the optional managed runtime control (HOST-RUNTIME.md) -----------------------------------------
class RecordingControl:
    """Labelled fixture control: scripted pause and stop answers, every heartbeat recorded."""

    def __init__(self):
        self.paused = self.stopping = self.unreadable = self.unwritable = False
        self.beats = []

    def admission_open(self):
        if self.unreadable:
            raise OSError("labelled injected unreadable pause")
        return not self.paused

    def stop_requested(self):
        return self.stopping

    def heartbeat(self, state):
        if self.unwritable:
            raise OSError("labelled injected unwritable heartbeat")
        self.beats.append(dict(state))


class HeldLauncher(FakeLauncher):
    """Fixture launcher whose children keep running until the test releases them."""

    def __init__(self, outcomes, on_wait):
        super().__init__(outcomes)
        self.released, self.on_wait, self.waits = set(), on_wait, 0

    def wait(self, handles, seconds):
        self.waits += 1
        self.on_wait(self)
        return [h for h in handles if h["job_id"] in self.released]


def test_a_paused_runner_admits_nothing_new_while_its_owned_child_finishes(tmp_path):
    f = fleet(tmp_path)
    # A reservation this runner does not own (an earlier runner's dispatching job) is unresolved.
    f.enqueue("b", manifest("op-0", ["docs/w.md"]), GOAL, [])
    assert f.admit_one()["job"]["id"] == "op-0"
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    accepted = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0}
    control = RecordingControl()

    def script(launcher):
        if launcher.waits == 1:
            control.paused = True  # the drain closes admission while op-1 is still running
            f.enqueue("a", manifest("op-2", ["docs/y.md"]), GOAL, ["op-1"])
        if launcher.waits == 3:
            launcher.released.add("op-1")

    launcher = HeldLauncher({"op-1": accepted, "op-2": accepted}, script)
    runner = FleetRunner(f, launcher, interval=0, control=control)
    runner.sleep = lambda seconds: setattr(control, "stopping", True)
    summary = runner.run(once=False)
    assert launcher.launched == ["op-1"] and summary["admitted"] == ["op-1"]
    assert summary["finalized"] == [{"id": "op-1", "status": "accepted", "reason_code": "lead_accepted"}]
    assert {j["id"]: j["status"] for j in f.status()["jobs"]}["op-2"] == "queued"
    assert control.beats[0] == {"admission": "open", "active": 1, "unresolved": 1}
    assert {"admission": "paused", "active": 1, "unresolved": 1} in control.beats
    assert control.beats[-2] == {"admission": "paused", "active": 0, "unresolved": 1}
    assert control.beats[-1] == {"admission": "stopping", "active": 0, "unresolved": 1}
    assert summary["stopped"] is True and summary["heartbeat"] == {"state": "ok", "error_type": None}


def test_an_unreadable_control_closes_admission_and_an_unwritable_heartbeat_is_not_invented(tmp_path):
    f = fleet(tmp_path)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    control = RecordingControl()
    control.unreadable = control.unwritable = True
    launcher = FakeLauncher({})
    summary = FleetRunner(f, launcher, interval=0, control=control).run(once=True)
    assert launcher.launched == [] and summary["admitted"] == [] and control.beats == []
    assert summary["control"] == {"state": "unavailable", "error_type": "OSError"}
    assert summary["heartbeat"] == {"state": "unavailable", "error_type": "OSError"}
    # Without a control the runner is exactly the previous one: no heartbeat, no control state.
    plain = FleetRunner(f, FakeLauncher({"op-1": {"status": "accepted", "reason_code": "lead_accepted",
                                                  "exit_code": 0}}), interval=0).run(once=True)
    assert plain["admitted"] == ["op-1"] and "heartbeat" not in plain and "control" not in plain


# ---- shared execution units (SPEC two-strike ownership design) -----------------------------------
UNIT_A, UNIT_B, UNIT_C = "1" * 64, "2" * 64, "3" * 64


def cleanup(unit, token, **overrides):
    """The shape of a guardian cleanup receipt (LABELLED: written here, not by a guardian)."""
    return {"kind": "cleanup", "launch": unit, "token": token, "confirmed": True, "exit_code": 0,
            "timed_out": False, "parent": {"confirmed": True}, "tree": {"confirmed": True}, **overrides}


def test_worker_jobs_and_execution_units_share_one_capacity_in_either_order(tmp_path):
    f = fleet(tmp_path, max_parallel=1)
    f.enqueue("a", manifest("op-1", ["docs/a.md"]), GOAL, [])
    # Unit first: the queued worker waits with the persisted `capacity` reason.
    held = f.reserve_unit(UNIT_A, "conductor", "b", "intent-1")
    assert held["cached"] is False and f.held_units() == [UNIT_A]
    decision = f.admit_one()
    assert decision["job"] is None and decision["blocked"] == {"op-1": "capacity"}
    # Replaying the same unit id (a lost response) is the same reservation, never a second slot.
    assert f.reserve_unit(UNIT_A, "conductor", "b", "intent-1") == {**held, "cached": True}
    with pytest.raises(FleetRefused, match="unit_conflict"):
        f.reserve_unit(UNIT_A, "conductor", "b", "intent-2")
    f.settle_unit(UNIT_A, held["token"], cleanup(UNIT_A, held["token"]))
    job = f.admit_one()["job"]
    assert job["id"] == "op-1"
    # Worker first: the dispatching job fills the fleet and no unit is reserved.
    with pytest.raises(FleetRefused, match="capacity"):
        f.reserve_unit(UNIT_B, "conductor", "b", "intent-2")
    assert f.held_units() == []
    f.finalize(job["id"], job["owner_token"], {"status": "unknown", "reason_code": "outcome_uncertain"})
    with pytest.raises(FleetRefused, match="capacity"):
        f.reserve_unit(UNIT_B, "conductor", "b", "intent-2")  # an unknown job keeps its slot too
    other = fleet(tmp_path / "paused", max_parallel=2)
    other.pause()
    with pytest.raises(FleetRefused, match="paused"):
        other.reserve_unit(UNIT_C, "conductor", "a", "intent-3")


def test_only_an_exact_parent_and_tree_proof_releases_a_unit_exactly_once(tmp_path):
    f = fleet(tmp_path)
    token = f.reserve_unit(UNIT_A, "conductor", "a", "intent-1")["token"]
    refused = [(cleanup(UNIT_A, token, tree={"confirmed": False}), "proof_unconfirmed"),  # parent exited only
               (cleanup(UNIT_A, token, parent={"confirmed": False}), "proof_unconfirmed"),
               (cleanup(UNIT_A, token, confirmed=False), "proof_unconfirmed"),
               (cleanup(UNIT_B, token), "proof_identity_mismatch"),
               (cleanup(UNIT_A, "other"), "proof_identity_mismatch"),
               ({"kind": "fenced", "launch": UNIT_A}, "proof_invalid"),
               ({"kind": "exit", "launch": UNIT_A}, "proof_invalid"), (None, "proof_invalid")]
    for proof, reason in refused:
        with pytest.raises(FleetRefused, match=reason):
            f.settle_unit(UNIT_A, token, proof)
    with pytest.raises(FleetRefused, match="owner_mismatch"):
        f.settle_unit(UNIT_A, "stale-token", cleanup(UNIT_A, token))
    assert f.held_units() == [UNIT_A], "no refused proof released anything"

    def failing_commit(tx, unit):  # LABELLED fault: the settlement transaction fails before its commit
        raise ConnectionError("commit failed (injected)")
    with pytest.raises(ConnectionError):
        f.settle_unit(UNIT_A, token, cleanup(UNIT_A, token), within=failing_commit)
    assert f.held_units() == [UNIT_A], "a failed commit keeps the unit held"
    writes = []
    first = f.settle_unit(UNIT_A, token, cleanup(UNIT_A, token), within=lambda tx, unit: writes.append(unit["id"]))
    again = f.settle_unit(UNIT_A, token, cleanup(UNIT_A, token), within=lambda tx, unit: writes.append(unit["id"]))
    assert first["cached"] is False and again["cached"] is True and writes == [UNIT_A], "settled exactly once"
    assert first["unit"]["state"] == "released" and "token" not in first["unit"]
    with pytest.raises(FleetRefused, match="settlement_conflict"):
        f.settle_unit(UNIT_A, token, cleanup(UNIT_A, token, exit_code=1))
    fenced = f.reserve_unit(UNIT_B, "conductor", "a", "intent-2")["token"]
    released = f.settle_unit(UNIT_B, fenced, {"kind": "fenced", "launch": UNIT_B, "claim": "fenced"})
    assert released["unit"]["settlement"]["kind"] == "fenced" and f.held_units() == []


def test_simultaneous_controllers_never_start_more_units_than_the_shared_capacity(tmp_path):
    """Real threads, each its own Fleet object over ONE store: the store's transaction is the
    serialization boundary (MemoryStore's lock here; PostgreSQL's control advisory lock in
    production, not exercised in this image)."""
    import threading

    f = fleet(tmp_path, max_parallel=2)
    for op, lane in (("op-1", "a"), ("op-2", "b")):
        f.enqueue(lane, manifest(op, ["docs/" + op + ".md"]), GOAL, [])
    barrier, outcomes = threading.Barrier(6), []

    def conductor(index):
        barrier.wait()
        try:
            Fleet(f.store).reserve_unit(str(index) * 64, "conductor", "a", "intent-%d" % index)
            outcomes.append("unit")
        except FleetRefused as exc:
            outcomes.append(exc.reason_code)

    def worker():
        barrier.wait()
        outcomes.append("job" if Fleet(f.store).admit_one()["job"] is not None else "none")
    threads = [threading.Thread(target=conductor, args=(i,)) for i in range(4, 8)]
    threads += [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    started = outcomes.count("unit") + outcomes.count("job")
    with f.store.transaction() as tx:
        reserving = [row for row in tx.scan("fleet_jobs") if row["status"] == "dispatching"]
    assert started == 2 == len(reserving) + len(f.held_units()), "zero excess start"
    assert len(outcomes) == 6 and set(outcomes) - {"unit", "job"} <= {"capacity", "none"}


def test_held_units_keep_the_fleet_from_idle_only_operations(tmp_path):
    f = fleet(tmp_path)
    f.reserve_unit(UNIT_A, "conductor", "a", "intent-1")
    with pytest.raises(FleetRefused, match="fleet_not_idle"):
        f.authorize_budget(5, 9, 8)
    assert [unit["id"] for unit in f.units()] == [UNIT_A] and "unknown cleanup" in f.units()[0]["next_action"]
