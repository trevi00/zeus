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
    assert shared.admit_one()["job"] is None
    assert shared.status()["lanes"] == [{"id": "a", "team": "alpha", "active_job": "op-1"},
                                       {"id": "b", "team": "beta", "active_job": "op-3"}]
    # Lane exclusivity and capacity on distinct repositories.
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    f.enqueue("a", manifest("op-2", ["docs/y.md"]), GOAL, [])
    f.enqueue("b", manifest("op-3", ["docs/x.md"]), GOAL, ["op-1"])
    f.enqueue("b", manifest("op-4", ["docs/z.md"]), GOAL, [])
    one = f.admit_one()
    assert one["job"]["id"] == "op-1" and one["blocked"] == {"op-2": "lane_busy", "op-3": "dependency_waiting", "op-4": "capacity"}
    assert f.admit_one(budget_exhausted=True)["blocked"] == {"op-2": "budget_exhausted", "op-3": "budget_exhausted", "op-4": "budget_exhausted"}
    f.pause()
    assert f.status()["paused"] is True and f.admit_one()["blocked"]["op-4"] == "paused"
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
    assert CANARY not in json.dumps(f.status()) and str(tmp_path) not in json.dumps(f.status())


def test_two_dispatchers_cannot_double_claim_and_projection_bounds_sample(tmp_path):
    f = fleet(tmp_path, max_parallel=1)
    for i in range(102):
        f.enqueue("a", manifest("op-%03d" % i, ["docs/%d.md" % i]), GOAL, [])
    other = Fleet(f.store)
    a, b = f.admit_one(), other.admit_one()
    assert a["job"]["id"] == "op-000" and b["job"] is None and b["blocked"]["op-001"] == "capacity"
    view = f.status()
    assert view["truncated"] is True and len(view["jobs"]) == 100 and view["jobs"][0]["id"] == "op-000"
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
