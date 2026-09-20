"""Operating portfolio over MemoryStore (docs/zeus/operations/operating-portfolio-001/SPEC.md).

Every Fleet job here is produced by the real `Fleet` API with fixture launchers and injected
outcomes; nothing spawns a process, contacts a provider or reads the machine ledger. The
assertions are about what the store and the projection actually hold: a candidate is a coarse
triage family of identical status and reason code, never a confirmed cause, and a criterion is
accepted only because the owner recorded it.
"""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from codex_harness.adapters import monitoring
from codex_harness.adapters.portfolio import packaged_definitions, portfolio, portfolio_reconciler
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS, Fleet, FleetRunner
from codex_harness.application.portfolio import (
    BUCKET_INVESTIGATIONS,
    Portfolio,
    PortfolioRefused,
    classified_failure,
    failure_families,
    family_id,
    reconcile,
    status_projection,
)
from codex_harness.domain.model import digest
from codex_harness.domain.operation import validate_manifest

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}
PROJECT, CRITERION = "sterk-migration", "projects"
REFS = ["sha256:" + "d" * 64, "docs/zeus/operations/operating-portfolio-001/SPEC.md"]


def config(tmp_path):
    lanes = [{"id": lane, "team": "team-" + lane, "repository": str(tmp_path / ("repo-" + lane)),
              "schema": "lane_" + lane, "redis_namespace": "fleet-" + lane,
              "runtime": str(tmp_path / ("rt-" + lane))} for lane in ("a", "b")]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 400, "total": 800}, "lanes": lanes}


def manifest(op_id, path):
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit", "rationale": CANARY},
        "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": [path]},
        "budget": {"per_host": 400, "total": 800},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


def fleet(tmp_path):
    store = MemoryStore()
    f = Fleet(store)
    f.register(config(tmp_path))
    return f


def enqueue(f, op_id, lane="a"):
    return f.enqueue(lane, manifest(op_id, "docs/" + op_id + ".md"), GOAL, [])["job"]["id"]


def finish(f, op_id, status, reason_code, lane="a"):
    """Enqueue, admit through the real admission path and record one injected terminal outcome."""
    enqueue(f, op_id, lane)
    while True:
        job = f.admit_one()["job"]
        if job is None:
            raise AssertionError("fixture job was not admissible")
        outcome = {"status": status, "reason_code": reason_code, "exit_code": 1} if job["id"] == op_id else {
            "status": "accepted", "reason_code": "lead_accepted", "exit_code": 0}
        f.finalize(job["id"], job["owner_token"], outcome)
        if job["id"] == op_id:
            return job["id"]


def clock(marks):
    return lambda: marks.pop(0) if marks else "2026-09-20T23:59:59+00:00"


def test_definitions_are_validated_and_every_goal_is_visible_before_any_binding(tmp_path):
    definitions = packaged_definitions()
    view = portfolio(MemoryStore()).status()
    assert view["schema"] == "urn:zeus:portfolio-status:1"
    assert view["definition_sha256"] == digest(Portfolio(MemoryStore(), definitions).definitions)
    assert [p["id"] for p in view["projects"]] == [p["id"] for p in definitions["projects"]]
    for project in view["projects"]:
        assert project["jobs"] == [] and project["jobs_truncated"] is False
        assert {c["status"] for c in project["criteria"]} == {"pending"}
        assert all(c["evidence_refs"] == [] for c in project["criteria"])
        assert project["counts"] == {"criteria_total": len(project["criteria"]), "criteria_accepted": 0,
                                     "jobs_total": 0}
    assert view["investigations"] == [] and view["investigations_truncated"] is False
    assert view["unbound_jobs"] == 0 and view["unclassified_failures"] == 0
    project = deepcopy(definitions["projects"][0])
    broken = [{"schema": "urn:zeus:portfolio-definitions:2"}, {"projects": []}, {"projects": {}},
              {"projects": [{**project, "id": "bad id " + CANARY}]},
              {"projects": [{**project, "title": CANARY * 40}]},
              {"projects": [{**project, "source_ref": str(tmp_path / "x.md")}]},
              {"projects": [{**project, "source_ref": "../secrets.md"}]},
              {"projects": [{**project, "criteria": []}]},
              {"projects": [{**project, "criteria": [{"id": "x", "text": ""}]}]},
              {"projects": [{**project, "criteria": [{"id": "x", "text": "t", "done": True}]}]},
              {"projects": [{**project, "criteria": project["criteria"] + [project["criteria"][0]]}]},
              {"projects": [project, project]}, {"extra": 1}]
    for override in broken:
        with pytest.raises(PortfolioRefused) as info:
            Portfolio(MemoryStore(), {**definitions, **override})
        # Refusals name the field, never the value.
        assert CANARY not in str(info.value) and str(tmp_path) not in str(info.value)
        assert info.value.reason_code.startswith("definitions_")


def test_binding_is_exact_immutable_and_leaves_fleet_rows_untouched(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    job_id = enqueue(f, "op-1")
    with pytest.raises(PortfolioRefused) as unknown_job:
        book.bind("op-absent", PROJECT, CRITERION)
    assert unknown_job.value.reason_code == "job_unknown"
    for target in ((("no-such-project"), CRITERION), (PROJECT, "no-such-criterion")):
        with pytest.raises(PortfolioRefused) as info:
            book.bind(job_id, *target)
        assert info.value.reason_code in {"project_unknown", "criterion_unknown"}
    before = deepcopy(f.store.data)
    assert book.bind(job_id, PROJECT, CRITERION)["cached"] is False
    assert book.bind(job_id, PROJECT, CRITERION)["cached"] is True     # replay, no second row
    with pytest.raises(PortfolioRefused) as conflict:
        book.bind(job_id, "research-improvement", "recurrence")
    assert conflict.value.reason_code == "binding_conflict"
    assert {k: v for k, v in f.store.data.items() if k[0] == BUCKET_JOBS} == {
        k: v for k, v in before.items() if k[0] == BUCKET_JOBS}
    row = f.store.data[("portfolio_bindings", job_id)]
    assert (row["project_id"], row["criterion_id"]) == (PROJECT, CRITERION)
    project = next(p for p in book.status()["projects"] if p["id"] == PROJECT)
    assert project["jobs"] == [{"id": job_id, "criterion_id": CRITERION, "lane": "a", "status": "queued",
                                "reason_code": None, "updated_at": f.status()["jobs"][0]["updated_at"]}]
    assert project["counts"]["jobs_total"] == 1 and book.status()["unbound_jobs"] == 0


def test_criterion_acceptance_comes_only_from_the_owner_record(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    job_id = finish(f, "op-1", "accepted", "lead_accepted")
    book.bind(job_id, PROJECT, CRITERION)

    def criterion():
        project = next(p for p in book.status()["projects"] if p["id"] == PROJECT)
        return next(c for c in project["criteria"] if c["id"] == CRITERION)
    # An accepted job is work, not the owner's criterion decision.
    assert criterion()["status"] == "pending" and criterion()["evidence_refs"] == []
    for bad in ([], "sha256:x", [""], [REFS[0]] * 2, ["x" * 201], [REFS[0], 3]):
        with pytest.raises(PortfolioRefused) as info:
            book.accept(PROJECT, CRITERION, bad)
        assert info.value.reason_code == "evidence_invalid"
    assert book.accept(PROJECT, CRITERION, REFS)["cached"] is False
    assert book.accept(PROJECT, CRITERION, list(REFS))["cached"] is True
    with pytest.raises(PortfolioRefused) as conflict:
        book.accept(PROJECT, CRITERION, [REFS[0]])
    assert conflict.value.reason_code == "acceptance_conflict"
    assert criterion() == {"id": CRITERION, "text": criterion()["text"], "status": "accepted",
                           "evidence_refs": REFS}
    counts = next(p for p in book.status()["projects"] if p["id"] == PROJECT)["counts"]
    assert counts["criteria_accepted"] == 1 and counts["criteria_total"] == 3
    # The returned record is a copy: mutating it never reaches the store or the next projection.
    criterion()["evidence_refs"].append(CANARY)
    assert criterion()["evidence_refs"] == REFS


def test_two_terminal_failures_make_one_durable_candidate_and_replay_adds_nothing(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions(), )
    finish(f, "op-1", "failed", "child_refused")
    finish(f, "op-2", "failed", "child_refused", lane="b")
    finish(f, "op-3", "rejected", "lead_rejected")           # family of one: not a candidate
    finish(f, "op-4", "failed", "exception:OSError: /home/owner/secret " + CANARY)
    finish(f, "op-5", "failed", None)                        # no observed reason: excluded, counted
    finish(f, "op-6", "unknown", "receipt_missing", lane="b")  # uncertain: existing Fleet semantics
    enqueue(f, "op-7")                                        # still queued: not a failure
    marks = ["2026-09-20T01:00:00+00:00", "2026-09-20T02:00:00+00:00"]
    summary = reconcile(f.store, clock(marks))
    assert summary["created"] == 1 and summary["updated"] == 0 and summary["families"] == 3
    assert summary["unclassified_failures"] == 1 and summary["scanned"] == 7
    view = book.status()
    candidate = view["investigations"][0]
    assert len(view["investigations"]) == 1 and view["investigations_truncated"] is False
    assert candidate == {"id": family_id("failed", "child_refused"), "family_status": "failed",
                         "reason_code": "child_refused", "state": "research_required", "count": 2,
                         "job_ids": ["op-1", "op-2"], "evidence_refs": [],
                         "updated_at": "2026-09-20T01:00:00+00:00"}
    assert view["unclassified_failures"] == 1 and view["unbound_jobs"] == 7
    # Replay over an unchanged fleet writes nothing at all.
    before = deepcopy(f.store.data)
    assert reconcile(f.store, clock(list(marks)))["created"] == 0
    assert f.store.data == before
    assert json.dumps(view) .count(CANARY) == 0 and "/home/owner" not in json.dumps(view)
    # The uncertain and the active work keep their existing Fleet semantics: `op-6` is still the
    # fleet's reconciliation duty, it is not a failure family, and nothing here took it over.
    assert f.reconciliation_required() == ["op-6"]
    assert {j["id"] for j in f.status()["jobs"] if j["status"] == "queued"} == {"op-7"}


def test_classifier_separates_an_observed_code_from_an_unknown_one(tmp_path):
    """Positive and negative controls for the grouping rule on synthetic rows (fixture data).

    `Fleet.finalize` stores `unknown` whenever no safe reason was observed, so a grouper that
    accepted it would invent one shared symptom out of two unrelated failures.
    """
    assert classified_failure({"id": "j", "status": "failed", "reason_code": "child_refused"}) == (
        "failed", "child_refused")
    assert classified_failure({"id": "j", "status": "rejected", "reason_code": "lead_rejected"}) == (
        "rejected", "lead_rejected")
    for row in ({"status": "failed", "reason_code": "unknown"}, {"status": "failed", "reason_code": None},
                {"status": "failed", "reason_code": ""}, {"status": "failed", "reason_code": "raw: " + CANARY},
                {"status": "unknown", "reason_code": "receipt_missing"},
                {"status": "accepted", "reason_code": "lead_accepted"},
                {"status": "exhausted", "reason_code": "budget_exhausted"},
                {"status": "dispatching", "reason_code": None}, {"status": "queued", "reason_code": "capacity"}):
        assert classified_failure({"id": "j", **row}) is None
    families, unclassified = failure_families([
        {"id": "j-1", "status": "failed", "reason_code": "unknown"},
        {"id": "j-2", "status": "failed", "reason_code": "unknown"},
        {"id": "j-3", "status": "failed", "reason_code": "child_refused"},
        {"id": "j-3", "status": "failed", "reason_code": "child_refused"},   # replay of one job
        {"id": "j-4", "status": "unknown", "reason_code": "receipt_missing"}])
    assert families == {("failed", "child_refused"): {"j-3"}} and unclassified == 2
    store = MemoryStore()
    with store.transaction() as tx:
        for row in ({"id": "j-1", "status": "failed", "reason_code": "unknown", "lane": "a"},
                    {"id": "j-2", "status": "failed", "reason_code": "unknown", "lane": "a"}):
            tx.put(BUCKET_JOBS, row["id"], row)
    assert reconcile(store)["candidates"] == [] and store.data.get((BUCKET_INVESTIGATIONS,)) is None
    assert [k for k in store.data if k[0] == BUCKET_INVESTIGATIONS] == []


def test_new_failures_extend_a_candidate_without_touching_the_owner_disposition(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions(), )
    finish(f, "op-1", "failed", "child_refused")
    finish(f, "op-2", "failed", "child_refused", lane="b")
    reconcile(f.store, clock(["2026-09-20T01:00:00+00:00"]))
    candidate = book.status()["investigations"][0]["id"]
    for bad in (("confirmed", REFS), ("researched", []), ("researched", [CANARY * 40])):
        with pytest.raises(PortfolioRefused) as info:
            book.disposition(candidate, *bad)
        assert info.value.reason_code in {"disposition_invalid", "evidence_invalid"}
    with pytest.raises(PortfolioRefused) as unknown:
        book.disposition("0" * 64, "deferred", REFS)
    assert unknown.value.reason_code == "candidate_unknown"
    decided = Portfolio(f.store, packaged_definitions(), clock=clock(["2026-09-20T03:00:00+00:00"]))
    assert decided.disposition(candidate, "deferred", REFS)["cached"] is False
    assert decided.disposition(candidate, "deferred", list(REFS))["cached"] is True
    for conflict in (("researched", REFS), ("deferred", [REFS[0]])):
        with pytest.raises(PortfolioRefused) as info:
            book.disposition(candidate, *conflict)
        assert info.value.reason_code == "disposition_conflict"
    # A third failure of the same family stays visible through the count; the decision survives.
    finish(f, "op-3", "failed", "child_refused")
    assert reconcile(f.store, clock(["2026-09-20T04:00:00+00:00"]))["updated"] == 1
    assert book.status()["investigations"][0] == {
        "id": candidate, "family_status": "failed", "reason_code": "child_refused", "state": "deferred",
        "count": 3, "job_ids": ["op-1", "op-2", "op-3"], "evidence_refs": REFS,
        "updated_at": "2026-09-20T04:00:00+00:00"}
    assert f.store.data[(BUCKET_INVESTIGATIONS, candidate)]["decided_at"] == "2026-09-20T03:00:00+00:00"


def test_projection_samples_jobs_and_candidates_while_counting_every_row(tmp_path):
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    ids = [enqueue(f, "op-%03d" % n) for n in range(55)]
    for job_id in ids:
        book.bind(job_id, PROJECT, CRITERION)
    project = next(p for p in book.status()["projects"] if p["id"] == PROJECT)
    assert project["counts"]["jobs_total"] == 55 and project["jobs_truncated"] is True
    assert len(project["jobs"]) == 50
    rows = {row["id"]: row for row in f.status()["jobs"]}
    latest = sorted(ids, key=lambda i: (rows[i]["updated_at"], i))[-50:]
    assert [job["id"] for job in project["jobs"]] == latest
    # Synthetic candidate rows (fixture, not observed failures) prove the queue bound and count.
    synthetic = [{"id": "%064d" % n, "family_status": "failed", "reason_code": "code_%d" % n,
                  "state": "research_required", "count": 9, "job_ids": ["j-%d" % i for i in range(60)],
                  "evidence_refs": [], "updated_at": "2026-09-20T00:%02d:00+00:00" % n} for n in range(51)]
    view = status_projection(book.definitions, [], [], [], synthetic)
    assert view["investigations_truncated"] is True and len(view["investigations"]) == 50
    assert view["investigations"][-1]["id"] == synthetic[-1]["id"]
    assert len(view["investigations"][0]["job_ids"]) == 50 and view["investigations"][0]["count"] == 9


def test_monitor_envelope_is_additive_read_only_and_unavailable_on_store_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(monitoring, "docker_facts", lambda repository, containers=None: [])
    monkeypatch.setattr(monitoring, "redis_facts", lambda url, agents: [])
    f = fleet(tmp_path)
    book = portfolio(f.store, packaged_definitions())
    job_id = finish(f, "op-1", "failed", "child_refused")
    book.bind(job_id, PROJECT, CRITERION)
    book.accept(PROJECT, CRITERION, REFS)
    service, _ = monitoring.read_only(SimpleNamespace(store=f.store, org=SimpleNamespace(agents={})), None)
    before = deepcopy(f.store.data)
    sources = monitoring.collect(service, None, str(tmp_path), "redis://127.0.0.1/0")["sources"]
    envelope = sources["portfolio"]
    assert envelope["status"] == "ok" and envelope["data"]["schema"] == "urn:zeus:portfolio-status:1"
    assert len(envelope["data"]["projects"]) == 3 and envelope["data"]["unbound_jobs"] == 0
    assert sources["fleet"]["status"] == "ok"          # the legacy sources are untouched
    text = json.dumps(envelope)
    assert CANARY not in text and str(tmp_path) not in text and "lane_a" not in text
    assert f.store.data == before                      # the collector never writes or reconciles

    class Broken:
        def transaction(self):
            raise RuntimeError("injected outage (fixture)")
    broken = monitoring.collect(SimpleNamespace(store=Broken(), org=SimpleNamespace(agents={})), None,
                                str(tmp_path), "redis://x")["sources"]
    assert broken["portfolio"] == {"status": "unavailable", "observed_at": broken["portfolio"]["observed_at"],
                                   "error": "RuntimeError", "data": None}
    assert broken["docker"]["status"] == "ok"          # one failed source never hides the others


class FixtureLauncher:
    """Fixture launcher: injects one outcome per job and never spawns a process."""

    def __init__(self, outcomes):
        self.outcomes, self.launched = outcomes, []

    def budget_exhausted(self, budget):
        return False

    def launch(self, job):
        self.launched.append(job["id"])
        return {"job_id": job["id"]}

    def wait(self, handles, seconds):
        return list(handles)

    def outcome(self, handle, job):
        return dict(self.outcomes[handle["job_id"]])


def test_runner_reconciles_once_per_tick_and_its_failure_never_blocks_admission(tmp_path):
    f = fleet(tmp_path)
    failed = {"status": "failed", "reason_code": "child_refused", "exit_code": 1}
    enqueue(f, "op-1")
    enqueue(f, "op-2", lane="b")
    plain = FleetRunner(f, FixtureLauncher({"op-1": failed, "op-2": failed}), interval=0).run(once=True)
    assert plain["reconciliation"] == {"state": "disabled", "error_type": None}
    assert [k for k in f.store.data if k[0] == BUCKET_INVESTIGATIONS] == []   # opt-in only
    enqueue(f, "op-3")
    runner = FleetRunner(f, FixtureLauncher({"op-3": failed}), interval=0,
                         reconcile=portfolio_reconciler(f.store))
    summary = runner.run(once=True)
    assert summary["finalized"] == [{"id": "op-3", "status": "failed", "reason_code": "child_refused"}]
    assert summary["reconciliation"] == {"state": "ok", "error_type": None}
    candidate = portfolio(f.store).status()["investigations"][0]
    assert candidate["count"] == 3 and candidate["job_ids"] == ["op-1", "op-2", "op-3"]
    assert candidate["state"] == "research_required"

    def broken():
        raise RuntimeError("injected reconciliation outage (fixture)")
    enqueue(f, "op-4")
    launcher = FixtureLauncher({"op-4": {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0}})
    degraded = FleetRunner(f, launcher, interval=0, reconcile=broken).run(once=True)
    assert degraded["reconciliation"] == {"state": "unavailable", "error_type": "RuntimeError"}
    assert degraded["admitted"] == ["op-4"] and launcher.launched == ["op-4"]
    assert degraded["finalized"][0]["status"] == "accepted"
