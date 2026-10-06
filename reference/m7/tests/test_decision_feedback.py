"""INV-DECISION-FEEDBACK-001 over REAL council runs.

Every run below is produced by the existing `CouncilRun` state machine with the labelled fixtures of
`test_council` (fault injection, never Claude, Codex, a DBA or a live council), so the rows this
collector reads are the actual stored shapes. The registry documents, the injected divergent run
histories and the broken stores are labelled fixtures; no model, network or provider is involved.
"""
import threading

import pytest
from test_autonomous import Artifacts, Clock, FakeExecutor
from test_autonomous import valid as autonomous_valid
from test_council import CouncilExecutor, FakeSnapshotPort, SnapshotArtifacts
from test_council import valid as council_valid
from test_operation import BOUND_GOAL, IDENTITY, Bus, Collector, FakeBudget

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.autonomous import AutonomousRun
from codex_harness.application.council import CouncilRun
from codex_harness.application.decision_feedback import (
    CANDIDATES,
    COLLECTIONS,
    CONFLICTS,
    GROUPS,
    OBSERVATIONS,
    READ_BUCKETS,
    WRITE_BUCKETS,
    DecisionFeedback,
)
from codex_harness.application.service import Harness
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain import decision_feedback as df
from codex_harness.domain.decision_feedback import DecisionFeedbackError, RegistryError

CANARY = "CANARY-must-never-be-emitted"
REPOSITORY = IDENTITY["repository"]
PATHS = ["docs/zeus/operations/autonomous-dge-001/RUNBOOK.md"]
CRITERIA = ["focused tests pass"]
REVISION, OTHER_REVISION = "1" * 40, "2" * 40
REGISTRY_SHA = "3" * 64
OTHER_PLAN = {"objective": "Add the other RUNBOOK note " + CANARY, "acceptance_criteria": list(CRITERIA),
              "allowed_paths": ["docs/zeus/operations/other-001/RUNBOOK.md"]}


def entry(**overrides) -> dict:
    row = {"id": "runbook-note", "source_kind": "council", "repository": REPOSITORY, "allowed_paths": list(PATHS),
           "acceptance_criteria_sha256": df.criteria_digest(CRITERIA), "remediation": "existing_owner_review"}
    row.update(overrides)
    return row


def registry(*entries) -> dict:
    return {"schema": df.REGISTRY_SCHEMA, "version": 1, "entries": list(entries) or [entry()]}


class Fixture:
    """One in-memory control plane plus the ONE content-addressed artifact store every run in a test
    writes its execution artifacts to, the way the operating runtime has a single artifact root. The
    collector reads those same artifacts; a per-run store would hide the binding it must verify."""

    def __init__(self):
        self.service = Harness(MemoryStore(), organization())
        self.artifacts = Artifacts()

    @property
    def store(self):
        return self.service.store


def council(svc, run_id, identity=None, **overrides) -> dict:
    """One real council run into the shared store (fixtures: executor, budget, snapshot port, clock)."""
    artifacts, clock = svc.artifacts, Clock()
    identity = identity or IDENTITY
    # The debate session is registered for the same repository identity the operation claim gate checks.
    run = CouncilRun(svc.service, CouncilExecutor(svc.service, artifacts, clock=clock), Bus(),
                     Workflow(svc.store, svc.service.org),
                     FakeBudget(), Collector(), verify_sources=lambda packet: [{**s, "bytes": 1} for s in packet["sources"]],
                     repository=identity["repository"], clock=clock, evidence=artifacts, snapshot=FakeSnapshotPort(clock),
                     artifacts=SnapshotArtifacts(artifacts))
    receipt = run.run(council_valid(id=run_id, **overrides), identity, BOUND_GOAL)
    assert receipt["status"] == "accepted", receipt["reason_code"]
    return receipt


def autonomous_v1(svc, run_id) -> dict:
    """One real v1 autonomous run: no conductor, no council topology (fixtures as above)."""
    artifacts, clock = svc.artifacts, Clock()
    run = AutonomousRun(svc.service, FakeExecutor(svc.service, artifacts, clock=clock), Bus(),
                        Workflow(svc.store, svc.service.org),
                        FakeBudget(), Collector(), verify_sources=lambda packet: [{**s, "bytes": 1} for s in packet["sources"]],
                        repository="r", clock=clock, evidence=artifacts)
    return run.run(autonomous_valid(id=run_id), IDENTITY, BOUND_GOAL)


def harness() -> Fixture:
    return Fixture()


def feedback_for(svc, clock=None) -> DecisionFeedback:
    """The collector bound to the artifact store those runs really wrote to."""
    return DecisionFeedback(svc.store, evidence=svc.artifacts, **({"clock": clock} if clock else {}))


def collect(svc, *, registry_document=None, revision=REVISION, limit=100, after="", clock=None) -> dict:
    return feedback_for(svc, clock).collect(registry=registry_document or registry(), registry_revision=revision,
                                            registry_path="docs/zeus/procedures.json", registry_sha256=REGISTRY_SHA,
                                            repository=REPOSITORY, limit=limit, after=after)


def rows(svc, bucket) -> list:
    with svc.store.transaction() as tx:
        return tx.scan(bucket)


def source_snapshot(svc) -> list:
    """Every row this collector must leave alone: runs, sessions, events, tasks, incidents, hooks,
    the promoted graph and everything else outside its own four buckets and its receipts."""
    with svc.store.transaction() as tx:
        return [r for r in tx.records() if r["bucket"] not in WRITE_BUCKETS]


def edit_run(svc, run_id, **fields) -> dict:
    """Injected fault: the run row as another history would have left it; the collector never writes here."""
    with svc.store.transaction() as tx:
        row = tx.get("autonomous_runs", run_id)
        tx.put("autonomous_runs", run_id, {**row, **fields})
        return row


# ----- registry and pure contracts ----------------------------------------------------------------
def test_registry_pins_exact_contracts_and_refuses_malformed_entries_without_echoing_values():
    validated = df.validate_registry(registry())
    assert validated["entries"][0]["allowed_paths"] == sorted(PATHS) and validated["version"] == 1
    assert df.validate_registry(validated) == validated, "validation is idempotent and canonical"
    for change in ({"schema": "urn:zeus:procedure-registry:2"}, {"version": 2}, {"version": True}, {"entries": []},
                   {"entries": [entry(), entry()]}, {"extra": CANARY}):
        with pytest.raises(RegistryError) as info:
            df.validate_registry({**registry(), **change})
        assert CANARY not in str(info.value)
    for change in ({"id": ""}, {"id": "../escape"}, {"source_kind": "operation"}, {"repository": ""},
                   {"allowed_paths": []}, {"allowed_paths": ["../secrets"]}, {"allowed_paths": PATHS + PATHS},
                   {"acceptance_criteria_sha256": "nope"}, {"remediation": "auto_publish"}, {"unknown": CANARY}):
        with pytest.raises(RegistryError) as info:
            df.validate_registry(registry(entry(**change)))
        assert CANARY not in str(info.value)
    with pytest.raises(RegistryError, match="missing fields"):
        df.validate_registry(registry({k: v for k, v in entry().items() if k != "remediation"}))


def test_matching_is_exact_and_missing_or_ambiguous_entries_stay_unknown():
    contract = df.work_contract(REPOSITORY, "council", {"allowed_paths": list(PATHS), "acceptance_criteria": list(CRITERIA)})
    assert df.match_registry(contract, df.validate_registry(registry()))["procedure_id"] == "runbook-note"
    assert df.group_id(contract) == df.group_id(df.work_contract(REPOSITORY, "council",
                                                                 {"allowed_paths": list(reversed(PATHS)), "acceptance_criteria": list(CRITERIA)}))
    for change in ({"repository": "other"}, {"allowed_paths": ["docs/OTHER.md"]},
                   {"acceptance_criteria_sha256": df.criteria_digest(["other criterion"])}):
        unmatched = df.match_registry(contract, df.validate_registry(registry(entry(**change))))
        assert unmatched == {"matched": False, "reason": "no_registry_match", "procedure_id": None, "remediation": None}
    ambiguous = df.match_registry(contract, df.validate_registry(registry(entry(), entry(id="duplicate-contract"))))
    assert ambiguous["reason"] == "ambiguous_registry_match" and ambiguous["procedure_id"] is None
    assert df.criteria_digest(CRITERIA) != df.criteria_digest(CRITERIA + ["second"]), "criteria are the contract"
    assert df.criteria_digest(["a", "b"]) != df.criteria_digest(["b", "a"]), "order is part of the digest"
    for broken in ({"allowed_paths": [], "acceptance_criteria": CRITERIA}, {"allowed_paths": PATHS, "acceptance_criteria": []},
                   {"allowed_paths": PATHS, "acceptance_criteria": [""]}):
        with pytest.raises(DecisionFeedbackError, match="work_contract_unknown"):
            df.work_contract(REPOSITORY, "council", broken)


def test_outcome_states_preserve_the_source_status_and_terminal_accepted_is_not_correctness():
    states = {status: df.outcome_facts({"id": "r", "status": status, "reason_code": "promoted"})
              for status in ("running", "accepted", "rejected", "failed", "cancelled", "exhausted",
                             "needs_user", "needs_research", "expired", "unknown")}
    assert [states[s]["state"] for s in ("running", "accepted", "rejected", "failed", "cancelled")] == \
        ["pending", "accepted", "rejected", "failed", "cancelled"]
    assert {states[s]["state"] for s in ("exhausted", "needs_user", "needs_research", "expired", "unknown")} == {"unknown"}
    assert states["exhausted"]["source_status"] == "exhausted" and states["exhausted"]["reason_code"] == "promoted"
    assert states["running"]["terminal"] is False and states["accepted"]["terminal"] is True
    assert "not proof that the decision was correct" in states["accepted"]["authority"]
    assert df.outcome_facts({"id": "r"})["state"] == "unknown" and df.outcome_facts({"id": "r"})["source_status"] is None
    assert df.quality_facts()["label"] == "unknown", "no judgment label is manufactured here"


# ----- collection ---------------------------------------------------------------------------------
def test_two_distinct_council_runs_make_one_candidate_and_repeated_collection_is_idempotent():
    svc = harness()
    council(svc, "council-001")
    first = collect(svc)
    assert first["counts"]["scanned"] == 1 and first["counts"]["eligible"] == 1
    assert rows(svc, CANDIDATES) == [], "one executed run is a measured no-candidate result"
    council(svc, "council-002")
    before = source_snapshot(svc)
    second = collect(svc)
    assert second["counts"]["scanned"] == 2 and second["counts"]["eligible"] == 2
    assert second["counts"]["observations_recorded"] == 1 and second["counts"]["observations_unchanged"] == 1
    assert second["counts"]["candidates_created"] == 1 and second["truncated"] is False and second["next_cursor"] is None
    candidates = rows(svc, CANDIDATES)
    assert len(candidates) == 1 and candidates[0]["status"] == "needs_analysis" and candidates[0]["verified"] is False
    assert [o["run_id"] for o in candidates[0]["occurrences"]] == ["council-001", "council-002"]
    assert candidates[0]["distinct_runs"] == 2 and candidates[0]["outcomes"]["accepted"] == 2
    assert candidates[0]["quality"]["label"] == "unknown" and candidates[0]["procedure_id"] == "runbook-note"
    assert candidates[0]["registry"] == {"revision": REVISION, "path": "docs/zeus/procedures.json", "sha256": REGISTRY_SHA}
    assert all(o["execution_ref"].startswith("sha256:") for o in candidates[0]["occurrences"])
    third = collect(svc)
    assert third["counts"]["observations_unchanged"] == 2 and third["counts"]["candidates_created"] == 0
    assert third["counts"]["candidates_updated"] == 0, "the same input adds no occurrence and no candidate"
    assert rows(svc, CANDIDATES) == candidates and third["id"] == second["id"], "same input, same receipt identity"
    assert len(rows(svc, GROUPS)) == 1 and rows(svc, GROUPS)[0]["run_ids"] == ["council-001", "council-002"]
    assert source_snapshot(svc) == before, "no row outside this collector's own buckets is written"
    assert rows(svc, "incidents") == [] and rows(svc, "hooks") == [], "successful repetition is not an incident"
    assert {n["kind"] for n in rows(svc, "knowledge_nodes")} and CANDIDATES not in {r["bucket"] for r in before}, \
        "candidates stay out of the promoted graph the runs themselves wrote"
    assert CANARY not in str(candidates) and CANARY not in str(third), "no plan objective or payload text is copied"


def test_distinct_run_membership_is_exact_past_the_window_and_bounded_at_the_durable_cap():
    """The pure bounds at their real values: the reported window is presentation, the membership that
    the distinct-run count and the unreferenced remainder are derived from is exact."""
    members = []
    for index in range(df.MAX_OCCURRENCES + 5):
        members = df.add_member(members, "run-%04d" % index)["run_ids"]
    assert len(members) == len(set(members)) == df.MAX_OCCURRENCES + 5
    assert df.add_member(members, members[0]) == {"run_ids": members, "capped": False}, "a known run adds nothing"
    window = df.occurrence_window(members)
    assert len(window["referenced"]) == df.MAX_OCCURRENCES and window["unreferenced"] == 5
    assert df.occurrence_window(window["referenced"])["unreferenced"] == 0, "the window never grows itself"
    full = ["run-%05d" % index for index in range(df.MAX_MEMBERS)]
    assert df.add_member(full, "run-beyond") == {"run_ids": full, "capped": True}
    assert df.add_member(full, full[0]) == {"run_ids": full, "capped": False}, "a known run never trips the cap"
    assert [limit for limit in df.LIMITS if "membership is exact" in limit], "the report names the durable bound"


def test_a_group_past_the_reported_window_keeps_exact_distinct_membership_across_collections(monkeypatch):
    """More distinct executed runs in one contract group than the candidate reports references for.
    The reported window is narrowed to two by fixture: the code path is identical, and 51 real council
    runs in one MemoryStore cost ~10 minutes (every transaction deep-copies the whole store). The
    distinct-run count stays exact, and collecting the same group a second time adds no occurrence, no
    unrecorded remainder and no candidate: membership is durable and keyed by run identity, so it can
    never be inflated by re-reading runs that are already members but outside the reported window."""
    monkeypatch.setattr(df, "MAX_OCCURRENCES", 2)
    svc = harness()
    total = df.MAX_OCCURRENCES + 1
    for index in range(total):
        council(svc, "council-%03d" % index)
    first = collect(svc, limit=df.MAX_SCAN)
    assert first["counts"]["scanned"] == total and first["counts"]["eligible"] == total
    assert first["counts"]["candidates_created"] == 1
    candidate = rows(svc, CANDIDATES)[0]
    assert candidate["distinct_runs"] == total and len(candidate["occurrences"]) == df.MAX_OCCURRENCES
    assert candidate["unrecorded_runs"] == total - df.MAX_OCCURRENCES == 1
    assert candidate["membership_capped"] is False and sum(candidate["outcomes"].values()) == df.MAX_OCCURRENCES
    group = rows(svc, GROUPS)[0]
    assert len(group["run_ids"]) == len(set(group["run_ids"])) == total
    assert group["unreferenced_occurrences"] == 1 and group["referenced_occurrences"] == df.MAX_OCCURRENCES
    second = collect(svc, limit=df.MAX_SCAN)
    assert second["counts"]["observations_unchanged"] == total and second["counts"]["observations_recorded"] == 0
    assert second["counts"]["candidates_created"] == 0 and second["counts"]["candidates_updated"] == 0
    assert rows(svc, CANDIDATES) == [candidate], "a second collection of the same runs changes nothing"
    assert {k: v for k, v in rows(svc, GROUPS)[0].items() if k != "updated_at"} == \
        {k: v for k, v in group.items() if k != "updated_at"}, "the membership itself is unchanged"
    assert len(rows(svc, OBSERVATIONS)) == total


def test_one_run_a_different_contract_or_a_v1_source_never_groups_into_a_candidate():
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002", plan=dict(OTHER_PLAN))
    receipt = collect(svc)
    assert receipt["counts"]["eligible"] == 1 and receipt["reasons"]["no_registry_match"] == 1
    assert rows(svc, CANDIDATES) == [] and len(rows(svc, GROUPS)) == 2, "different scopes stay separate groups"
    assert len(rows(svc, OBSERVATIONS)) == 2, "both decisions are observed; only one matches the registry"
    assert autonomous_v1(svc, "auto-001")["status"] == "accepted"
    v1 = collect(svc)
    assert v1["counts"]["scanned"] == 3 and v1["reasons"]["source_kind_unknown"] == 1
    assert len(rows(svc, OBSERVATIONS)) == 2, "a run without the council topology earns no evidence credit"
    foreign = feedback_for(svc).collect(registry=registry(entry(repository="elsewhere")), registry_revision=REVISION,
                                        registry_path="docs/zeus/procedures.json", registry_sha256=REGISTRY_SHA,
                                        repository="elsewhere", limit=100)
    assert foreign["counts"]["foreign_repository"] == 3 and foreign["counts"]["eligible"] == 0
    assert rows(svc, CANDIDATES) == [], "another repository's runs never group with this one"


def test_a_pending_outcome_joins_later_and_a_changed_terminal_history_is_a_conflict():
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    terminal = edit_run(svc, "council-001", status="running", reason_code=None, finished_at=None)
    pending = collect(svc)
    assert pending["counts"]["eligible"] == 2 and rows(svc, CANDIDATES)[0]["outcomes"]["pending"] == 1
    observation = [o for o in rows(svc, OBSERVATIONS) if o["run_id"] == "council-001"][0]
    assert observation["outcome"]["state"] == "pending" and observation["outcome"]["terminal"] is False
    assert observation["quality"]["label"] == "unknown", "a pending outcome is not a judgment"
    with svc.store.transaction() as tx:
        tx.put("autonomous_runs", "council-001", terminal)  # the run reaches its real terminal state
    joined = collect(svc)
    assert joined["counts"]["observations_updated"] == 1 and joined["counts"]["conflicts"] == 0
    updated = [o for o in rows(svc, OBSERVATIONS) if o["run_id"] == "council-001"][0]
    assert updated["outcome"]["state"] == "accepted" and [h["state"] for h in updated["outcome_history"]] == ["pending"]
    assert updated["first_seen_at"] == observation["first_seen_at"], "the decision facts are immutable"
    assert rows(svc, CANDIDATES)[0]["outcomes"]["accepted"] == 2 and rows(svc, CONFLICTS) == []
    edit_run(svc, "council-001", status="failed", reason_code="review_rejected")  # injected divergent history
    conflicted = collect(svc)
    assert conflicted["counts"]["conflicts"] == 1 and conflicted["reasons"]["source_history_conflict"] == 1
    assert [o for o in rows(svc, OBSERVATIONS) if o["run_id"] == "council-001"][0]["outcome"]["state"] == "accepted"
    conflict = rows(svc, CONFLICTS)[0]
    assert conflict["kind"] == "terminal_outcome_changed" and conflict["observed"]["source_status"] == "failed"
    assert conflict["stored"]["source_status"] == "accepted" and "owner_inspection_required" in conflict["disposition"]
    assert rows(svc, CANDIDATES)[0]["outcomes"]["accepted"] == 2, "a conflict never rewrites the candidate evidence"
    assert collect(svc)["counts"]["conflicts"] == 1 and len(rows(svc, CONFLICTS)) == 1, "one conflict, not one per read"


class Interleaved:
    """Deterministic coordination fixture: the wrapped store runs `between` once, after the reading
    transaction of a collection has committed and before its recording transaction opens. That is the
    exact window in which another collector can record the run this page read earlier."""

    def __init__(self, store, between):
        self.store, self.between, self.transactions = store, between, 0

    def transaction(self):
        self.transactions += 1
        if self.transactions == 2:
            self.between()
        return self.store.transaction()


def interleaved_collect(svc, between) -> dict:
    return DecisionFeedback(Interleaved(svc.store, between), evidence=svc.artifacts).collect(
        registry=registry(), registry_revision=REVISION, registry_path="docs/zeus/procedures.json",
        registry_sha256=REGISTRY_SHA, repository=REPOSITORY)


def test_a_page_read_before_the_terminal_outcome_is_stale_and_not_a_changed_history():
    """Two coordinated collectors over ONE run reaching its real terminal state. The slow collector
    read the run while it was still running; the fast collector recorded the terminal outcome first.
    Recording the stale page must revalidate against the authoritative row and report `source_page_stale`,
    never a `terminal_outcome_changed` conflict against a history that never changed."""
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    terminal = edit_run(svc, "council-001", status="running", reason_code=None, finished_at=None)
    fast = {}

    def between():
        with svc.store.transaction() as tx:
            tx.put("autonomous_runs", "council-001", terminal)  # the run reaches its real terminal state
        fast.update(collect(svc))                               # the faster collector records it first

    late = interleaved_collect(svc, between)
    assert fast["counts"]["observations_recorded"] == 2 and fast["counts"]["conflicts"] == 0
    stored = [o for o in rows(svc, OBSERVATIONS) if o["run_id"] == "council-001"][0]
    assert stored["outcome"]["state"] == "accepted" and stored["outcome"]["terminal"] is True
    assert late["counts"]["observations_stale"] == 1 and late["counts"]["conflicts"] == 0
    assert late["counts"]["observations_unchanged"] == 1 and late["reasons"] == {"matched": 2}
    assert rows(svc, CONFLICTS) == [], "a stale page is not a changed source history"
    assert "source_page_stale" in df.RECORD_REASONS, "the stale disposition is a fixed reason code"
    assert [o for o in rows(svc, OBSERVATIONS) if o["run_id"] == "council-001"][0] == stored
    assert late["counts"]["eligible"] == 2 and rows(svc, CANDIDATES)[0]["outcomes"]["accepted"] == 2
    # Discriminating control: the same code path still refuses a terminal history that really changed.
    edit_run(svc, "council-001", status="failed", reason_code="review_rejected")  # injected divergent history
    conflicted = collect(svc)
    assert conflicted["counts"]["conflicts"] == 1 and rows(svc, CONFLICTS)[0]["kind"] == "terminal_outcome_changed"
    assert [o for o in rows(svc, OBSERVATIONS) if o["run_id"] == "council-001"][0] == stored


def test_a_source_row_that_cannot_be_re_read_stays_unknown_and_writes_nothing():
    """The same coordinated window, with the authoritative row unreadable when the record transaction
    revalidates it: unknown stays unknown, and neither an update nor a conflict is invented."""
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    terminal = edit_run(svc, "council-001", status="running", reason_code=None, finished_at=None)
    collect(svc)                                                # the run is observed while still pending
    with svc.store.transaction() as tx:
        tx.put("autonomous_runs", "council-001", terminal)      # it then reaches its terminal state
    before = rows(svc, OBSERVATIONS)

    def between():
        with svc.store.transaction() as tx:                     # injected fault: the row under this id
            row = tx.get("autonomous_runs", "council-001")       # is no longer this run's own row
            tx.put("autonomous_runs", "council-001", {**row, "id": "another-run"})

    receipt = interleaved_collect(svc, between)
    assert "source_row_unavailable" in df.RECORD_REASONS
    assert receipt["reasons"]["source_row_unavailable"] == 1 and receipt["counts"]["conflicts"] == 0
    assert receipt["counts"]["observations_updated"] == 0 and rows(svc, CONFLICTS) == []
    assert rows(svc, OBSERVATIONS) == before, "the stored observation is left exactly as it was"


@pytest.mark.parametrize("break_it, reason", [
    (lambda svc: _break_task(svc, execution_ref="sha256:" + "9" * 64), "decision_execution_unproven"),
    (lambda svc: _break_task(svc, status="failed"), "decision_execution_unproven"),
    (lambda svc: _break_event(svc), "decision_event_unproven"),
    (lambda svc: _break_session(svc, owner="someone-else"), "decision_session_unproven"),
    (lambda svc: _break_session(svc, origin="operator_submitted"), "decision_session_unproven"),
    (lambda svc: _break_run(svc, identity={}), "run_identity_unknown"),
])
def test_an_unproven_decision_identity_refuses_evidence_credit(break_it, reason):
    svc = harness()
    council(svc, "council-001")
    break_it(svc)
    receipt = collect(svc)
    assert receipt["counts"]["eligible"] == 0 and receipt["reasons"] == {reason: 1}
    assert rows(svc, OBSERVATIONS) == [] and rows(svc, GROUPS) == [] and rows(svc, CANDIDATES) == []


def _break_task(svc, **fields):
    with svc.store.transaction() as tx:
        event = [e for e in tx.scan("dge_events") if e["role"] == "arbiter"][0]
        task = tx.get("tasks", event["binding"]["task_id"])
        result = {**task["result"], **{k: v for k, v in fields.items() if k == "execution_ref"}}
        tx.put("tasks", task["id"], {**task, **{k: v for k, v in fields.items() if k != "execution_ref"}, "result": result})


def _break_event(svc):
    with svc.store.transaction() as tx:
        event = [e for e in tx.scan("dge_events") if e["role"] == "arbiter"][0]
        tx.put("dge_events", event["id"], {**event, "origin": "operator_submitted"})


def _break_session(svc, **fields):
    with svc.store.transaction() as tx:
        session = tx.scan("dge_sessions")[0]
        tx.put("dge_sessions", session["id"], {**session, **fields})


def _break_run(svc, **fields):
    edit_run(svc, "council-001", **fields)


@pytest.mark.parametrize("break_it, reason", [
    (lambda svc: _detach_artifacts(svc), "decision_artifact_missing"),
    (lambda svc: _corrupt_artifacts(svc), "decision_artifact_corrupt"),
    (lambda svc: _swap_artifacts(svc), "decision_artifact_unproven"),
])
def test_only_the_stored_execution_artifact_earns_evidence_credit_never_a_matching_reference(break_it, reason):
    """The rows keep binding one execution identity in every case below; only the content-addressed
    bytes behind `execution_ref` change. A reference string that matches in the run, event and task
    rows is not the executor's answer, so none of these is an observation."""
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    break_it(svc)
    receipt = collect(svc)
    assert reason in df.EVIDENCE_REASONS, "the refusal is one of the fixed evidence codes"
    assert receipt["counts"]["eligible"] == 0 and receipt["reasons"] == {reason: 2}
    assert rows(svc, OBSERVATIONS) == [] and rows(svc, GROUPS) == [] and rows(svc, CANDIDATES) == []
    assert rows(svc, CONFLICTS) == [], "an unproven artifact is unknown, not a source history conflict"
    assert CANARY not in str(receipt), "a refusal names the missing binding, never a row or artifact body"


def test_the_real_artifacts_of_the_same_two_runs_do_verify():
    """The discriminating control for the three faults above: the untouched artifact store verifies."""
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    receipt = collect(svc)
    assert receipt["counts"]["eligible"] == 2 and receipt["reasons"] == {"matched": 2}
    evidence = [o["evidence"] for o in rows(svc, OBSERVATIONS)]
    assert all(e["status"] == "verified" and e["artifact"]["verified"] is True for e in evidence)
    assert all(e["artifact"]["port"] == "execution_evidence" for e in evidence)
    assert all(e["artifact"]["reservation_id"] for e in evidence), "the settled reservation is named"
    assert len({e["artifact"]["output_sha256"] for e in evidence}) == 2
    with pytest.raises(DecisionFeedbackError, match="evidence_port_unavailable"):
        DecisionFeedback(svc.store).collect(registry=registry(), registry_revision=REVISION,
                                            registry_path="docs/zeus/procedures.json",
                                            registry_sha256=REGISTRY_SHA, repository=REPOSITORY)


def _decision_refs(svc) -> list:
    with svc.store.transaction() as tx:
        return [e["binding"]["execution_ref"] for e in tx.scan("dge_events") if e["role"] == "arbiter"]


def _detach_artifacts(svc):
    """Injected fault: every row still names its reference; the artifact store no longer holds it."""
    svc.artifacts = Artifacts()


def _corrupt_artifacts(svc):
    """Injected fault: the stored bytes no longer hash to the reference the rows name."""
    for ref in _decision_refs(svc):
        svc.artifacts.corrupt(ref)


def _swap_artifacts(svc):
    """Injected fault: each decision consistently names the OTHER decision's real, intact artifact in
    its event, task and run rows. Every reference string matches; the bytes are another execution's."""
    with svc.store.transaction() as tx:
        events = [e for e in tx.scan("dge_events") if e["role"] == "arbiter"]
        refs = [e["binding"]["execution_ref"] for e in events]
        assert len(set(refs)) == 2, "two executions, two distinct artifacts (otherwise nothing is swapped)"
        for event, other in zip(events, reversed(refs)):
            tx.put("dge_events", event["id"], {**event, "binding": {**event["binding"], "execution_ref": other}})
            task = tx.get("tasks", event["binding"]["task_id"])
            tx.put("tasks", task["id"], {**task, "result": {**task["result"], "execution_ref": other}})
        for run in tx.scan("autonomous_runs"):
            binding = run["roles"]["conductor"]
            swapped = [r for r in refs if r != binding["execution_ref"]][0]
            tx.put("autonomous_runs", run["id"],
                   {**run, "roles": {**run["roles"], "conductor": {**binding, "execution_ref": swapped}}})


def test_a_bounded_scan_reports_truncation_and_continues_from_the_cursor():
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    first = collect(svc, limit=1)
    assert first["truncated"] is True and first["next_cursor"] == "council-001" and first["scan_limit"] == 1
    assert first["counts"]["scanned"] == 1 and rows(svc, CANDIDATES) == []
    second = collect(svc, limit=1, after=first["next_cursor"])
    assert second["truncated"] is False and second["next_cursor"] is None and second["after"] == "council-001"
    assert second["counts"]["candidates_created"] == 1 and rows(svc, CANDIDATES)[0]["distinct_runs"] == 2
    assert [limit for limit in df.LIMITS if "continuation cursor" in limit], "the report names the scan limit"
    for invalid in (0, df.MAX_SCAN + 1, True, "10", None):
        with pytest.raises(DecisionFeedbackError, match="invalid_scan_limit"):
            collect(svc, limit=invalid)
    for revision, path, sha, code in ((REVISION[:39], "docs/p.json", REGISTRY_SHA, "registry_revision_invalid"),
                                      ("HEAD", "docs/p.json", REGISTRY_SHA, "registry_revision_invalid"),
                                      (REVISION, "../p.json", REGISTRY_SHA, "registry_path_invalid"),
                                      (REVISION, "docs/p.json", "not-a-digest", "registry_sha256_invalid")):
        with pytest.raises(DecisionFeedbackError) as info:
            feedback_for(svc).collect(registry=registry(), registry_revision=revision, registry_path=path,
                                      registry_sha256=sha, repository=REPOSITORY)
        assert info.value.reason_code == code, "the registry pin is part of the candidate evidence"


def test_a_store_failure_is_unavailable_not_zero_samples():
    class BrokenStore:
        """Injected fault: the control-plane store is unreachable."""

        def transaction(self):
            raise RuntimeError("store unavailable (injected fault)")

    class BrokenScan:
        """Injected fault: the connection breaks part-way through the bounded page."""

        def transaction(self):
            class Tx:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                @staticmethod
                def entries(bucket, after="", limit=100):
                    raise OSError("connection reset (injected fault)")
            return Tx()

    for store in (BrokenStore(), BrokenScan()):
        feedback = DecisionFeedback(store, evidence=Artifacts())
        with pytest.raises(DecisionFeedbackError) as info:
            feedback.collect(registry=registry(), registry_revision=REVISION, registry_path="docs/zeus/procedures.json",
                             registry_sha256=REGISTRY_SHA, repository=REPOSITORY)
        assert info.value.reason_code == "source_unavailable"
        with pytest.raises(DecisionFeedbackError, match="source_unavailable"):
            feedback.status()
        with pytest.raises(DecisionFeedbackError, match="source_unavailable"):
            feedback.report()


def test_concurrent_collectors_serialize_into_one_candidate_and_one_set_of_occurrences():
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    errors = []

    def worker():
        try:
            collect(svc)
        except Exception as exc:  # a serialization failure must surface, never pass silently
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    candidates, groups = rows(svc, CANDIDATES), rows(svc, GROUPS)
    assert len(candidates) == 1 and candidates[0]["distinct_runs"] == 2 and len(groups) == 1
    assert [o["run_id"] for o in candidates[0]["occurrences"]] == ["council-001", "council-002"]
    assert len(rows(svc, OBSERVATIONS)) == 2 and len(rows(svc, COLLECTIONS)) == 1, "one receipt for one input"


def test_status_and_report_expose_counts_limits_and_no_promotion_authority():
    svc = harness()
    council(svc, "council-001")
    council(svc, "council-002")
    receipt = collect(svc)
    feedback = DecisionFeedback(svc.store)
    status = feedback.status()
    assert status["counts"][OBSERVATIONS] == {"counted": 2, "truncated": False, "next_cursor": None}
    assert status["counts"][CANDIDATES]["counted"] == 1 and status["observed_outcomes"]["accepted"] == 2
    assert status["quality"]["label"] == "unknown" and "no promotion authority" in status["authority"]
    bounded = feedback.status(limit=1)
    assert bounded["counts"][OBSERVATIONS] == {"counted": 1, "truncated": True, "next_cursor": "council-001"}
    report = feedback.report(collection_id=receipt["id"])
    assert report["candidates"][0]["status"] == "needs_analysis" and report["collection_found"] is True
    assert report["collection"]["counts"]["eligible"] == 2 and report["conflicts"] == []
    assert list(report["limits"]) == list(df.LIMITS) and report["candidates_truncated"] is False
    assert feedback.report(collection_id="collection:missing")["collection"] is None
    assert feedback.report(collection_id="collection:missing")["collection_found"] is False
    assert "needs_analysis" in report["candidates"][0]["status"] and report["candidates"][0]["verified"] is False


@pytest.mark.integration
def test_postgres_collection_is_idempotent_across_restarts(isolated_pgstore):
    """The same two real council runs, replayed into an isolated schema, then collected twice."""
    memory = harness()
    council(memory, "council-001")
    council(memory, "council-002")
    with memory.store.transaction() as source, isolated_pgstore.transaction() as target:
        for record in source.records():
            if record["bucket"] in READ_BUCKETS:
                target.put(record["bucket"], record["id"], record["body"])
    first = DecisionFeedback(isolated_pgstore, evidence=memory.artifacts).collect(
        registry=registry(), registry_revision=REVISION, registry_path="docs/zeus/procedures.json",
        registry_sha256=REGISTRY_SHA, repository=REPOSITORY)
    assert first["counts"]["candidates_created"] == 1 and first["counts"]["eligible"] == 2
    # A restart is a new instance over the same rows: the receipt identity and the evidence repeat.
    second = DecisionFeedback(isolated_pgstore, evidence=memory.artifacts).collect(
        registry=registry(), registry_revision=REVISION, registry_path="docs/zeus/procedures.json",
        registry_sha256=REGISTRY_SHA, repository=REPOSITORY)
    assert second["id"] == first["id"] and second["counts"]["candidates_created"] == 0
    assert second["counts"]["observations_unchanged"] == 2
    with isolated_pgstore.transaction() as tx:
        candidates = tx.scan(CANDIDATES)
        assert len(candidates) == 1 and candidates[0]["distinct_runs"] == 2
        assert [o["run_id"] for o in candidates[0]["occurrences"]] == ["council-001", "council-002"]
