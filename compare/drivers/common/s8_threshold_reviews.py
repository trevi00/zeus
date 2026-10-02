"""Shared S8 scenario steps (`research.threshold_reviews`): M7 `application/threshold_reviews.py` (`ThresholdReviews`: `request`, `_row`,
`_queue`, `_prepare`, `prepare`, `complete`, `exhausted`), characterized BEFORE the module moves (DESIGN-s8 §17 V22: R-tr1..R-tr4). The golden
is placement-neutral: it observes SOURCE behaviour only; the move is a later commit of the same pilot.

Each case is labelled with the M7 `tests/test_threshold_reviews.py` test it mirrors (`m7_test`), or `none` (a branch of the module no M7 test
names, labelled where it is made). M7's tests drive the whole `Executor` with a policy repository; the golden is APPLICATION-level instead:
the executor's two halves (`review_threshold`, the V20 adapter, and the provider run) are replaced by `stage`, which builds the receipt, the
packet and the evidence document exactly as M7's test `runtime` builds them. Left out (named in the move report): the executor-subject tests
`test_dirty_attempt_does_not_poison_retry_workspace` (a Git workspace per attempt) and the OSError wrapper of
`test_post_commit_error_does_not_rewrite_success` (its `exhausted` half is `case_exhausted`).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a target)
driver builds. LABELLED doubles and plantings (nothing here is an actual Codex, Git, Docker, model or production verification):
- the store is a `MemoryStore`; the `threshold_proposals` row, its `threshold_proposal_runs` run and the evidence document are PLANTED in
  the shape `ThresholdProposals.collect` leaves them (identities are the module's own digests, so `_row` accepts them);
- the artifacts are `Artifacts` (the `document(ref)` of `FileArtifacts`) over scripted documents;
- the lease comes from the ordinary claim of each side (`api.claim`: M7 `Executor.decide_one` stopped at the V20 adapter boundary, the
  target coordination `claim_decision`), never planted;
- the organization is the packaged one; the clock and id source are the harness's, advanced one millisecond after every step.
The whole-store digest (16 hex) is recorded before and after every call, with a `wrote` flag: a refusal writes nothing.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

NAME = "skill_match.FULL_BODY_MIN_SCORE"
PROJECT = "project"
REV = "a" * 40
OTHER_REV = "b" * 40
BLOCKER = "native_task_success_and_release_review_required"
LEAD, CONDUCTOR = "lead:improvement", "conductor"


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_digest(store) -> str:
    with store.transaction() as tx:
        return canonical_digest([[r["bucket"], r["id"], canonical_digest(r["body"])] for r in tx.records()])[:16]


class Artifacts:
    """LABELLED. `FileArtifacts.document(ref)` over scripted documents: `add` stores a document under the reference its canonical bytes
    hash to, an unknown reference raises `FileNotFoundError`."""

    def __init__(self):
        self.docs, self.calls = {}, []

    def add(self, document) -> str:
        ref = "sha256:" + canonical_digest(document)
        self.docs[ref] = deepcopy(document)
        return ref

    def document(self, reference):
        self.calls.append(reference)
        if reference not in self.docs:
            raise FileNotFoundError(reference)
        return deepcopy(self.docs[reference])


# ---- the world ---------------------------------------------------------------------------------------------------------------
def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def outcome(fn, *args, **kwargs):
    """The characterized outcome of one call: its value, or the refusal (type, text)."""
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": value}


def step(w, fn, *args, **kwargs):
    """One call with the whole-store digest before and after and a `wrote` flag, then one tick of the fake clock."""
    before = store_digest(w.store)
    out = outcome(fn, *args, **kwargs)
    after = store_digest(w.store)
    w.api.advance(0.001)
    return {**out, "store_before": before, "store_after": after, "wrote": before != after}


class World:
    """One calculated threshold proposal in a MemoryStore, written the way `ThresholdProposals.collect` leaves it."""

    def __init__(self, api, tag="1"):
        self.api, self.tag = api, tag
        self.store, self.org, self.artifacts = api.MemoryStore(), api.organization(), Artifacts()
        proposal = {"id": "proposal-" + tag, "name": NAME, "current": 3, "suggested": 4, "policy_revision": REV,
                    "corpus_hash": "corpus-" + tag}
        self.evidence_ref = self.artifacts.add({"project_key": PROJECT, "proposals": [proposal]})
        run_id = api.digest([PROJECT, self.evidence_ref])
        self.row_id = api.digest([run_id, proposal["id"]])
        self.row = {"id": self.row_id, "run_id": run_id, "project_key": PROJECT, "evidence_ref": self.evidence_ref,
                    "proposal": proposal, "status": "calculated", "activation_ready": False, "activation_blockers": [BLOCKER]}
        self.run_id = run_id
        put(self.store, "threshold_proposals", self.row_id, self.row)
        put(self.store, "threshold_proposal_runs", run_id, {"id": run_id, "activation_ready": False, "proposals": [deepcopy(self.row)]})

    def reviews(self):
        return self.api.reviews(self.store, self.org, self.artifacts)

    def request(self):
        return step(self, self.reviews().request, self.row_id)

    def request_id(self):
        return self.api.digest(["threshold-assessment-v1", self.api.digest(self.row)])

    def decision_id(self, actor):
        return self.api.digest([self.request_id(), actor])

    def claim(self, actor):
        """The ordinary claim of `actor` (the lease, or None when nothing is claimable), then one tick of the fake clock."""
        before = store_digest(self.store)
        lease = self.api.claim(self.store, self.org, self.artifacts, actor)
        self.api.advance(0.001)
        return lease, before != store_digest(self.store)

    def request_row(self):
        return get(self.store, "threshold_review_requests", self.request_id())

    def decision_row(self, actor):
        return get(self.store, "decisions_pending", self.decision_id(actor))


def decision_view(row):
    if row is None:
        return None
    keep = ("actor", "phase", "status", "attempt", "generation", "owner", "lease_owner", "lease_until", "execution_deadline", "error",
            "completed_at", "retry_budget")
    out = {k: row.get(k) for k in keep}
    out["result"] = row.get("result")
    return out


def request_view(row):
    if row is None:
        return None
    return {"status": row["status"], "activation_ready": row["activation_ready"], "scope": row["scope"],
            "reviews": [{"actor": r["actor"], "accepted": r["result"]["accepted"], "generation": r["generation"],
                         "decision_id": r["decision_id"], "at": r["at"]} for r in row["reviews"]],
            "failure": row.get("failure"), "failed_decision": row.get("failed_decision"), "completed_at": row.get("completed_at"),
            "created_at": row.get("created_at")}


def state(w):
    """The request, both decisions, the conductor queue and the rows that must never appear (no dispatch, release or activation)."""
    return {"request": request_view(w.request_row()), "lead": decision_view(w.decision_row(LEAD)),
            "conductor": decision_view(w.decision_row(CONDUCTOR)),
            "decisions": sorted((r["actor"], r["status"]) for r in scan(w.store, "decisions_pending")),
            "no_effects": not (scan(w.store, "outbox") or scan(w.store, "releases") or scan(w.store, "deployment")),
            "store": store_digest(w.store)}


def lease_view(lease):
    if lease is None:
        return None
    return {k: lease.get(k) for k in ("id", "actor", "phase", "status", "attempt", "generation", "owner", "lease_until", "_bucket")}


# ---- one stage ---------------------------------------------------------------------------------------------------------------
def answer_of(accepted=True, blocked=False):
    return {"accepted": accepted, "reason": "fixture assessment", "blocked": blocked, "risks": [], "sre_assessment": "fixture",
            "arc42_assessment": "fixture"}


def receipt_of(w, lease, bundle, *, accepted=True, blocked=False, wrong_actor=False, inspection_blocked=False, interrupted=False,
               spoof_blockage=False, revision=REV, answer=None, review=None, result_changes=None):
    """LABELLED. The documents M7's executor leaves (M7 test `runtime`): the evidence the review ran on, the context packet, the execution
    receipt and the result the verdict carries."""
    add = w.artifacts.add
    answer = answer_of(accepted, blocked) if answer is None else answer
    evidence = add({"review": bundle if review is None else review})
    packet = add({"agent_id": "wrong" if wrong_actor else lease["actor"], "task_id": lease["id"],
                  "required": {"external_context": {"ref": evidence}}})
    receipt = add({"answer": answer, "context_ref": packet, "inspection_blocked": inspection_blocked, "interrupted": interrupted,
                   "research_binding": {"stage": "threshold_review", "evidence_ref": evidence, "basis_revision": revision}})
    result = {**(answer if isinstance(answer, dict) else answer_of(accepted, blocked)), "execution_ref": receipt, "basis_revision": revision}
    if inspection_blocked or spoof_blockage:
        result.update(accepted=False, inspection_blocked=True)
    result.update(result_changes or {})
    return result


def stage(w, actor, *, intervene=None, **options):
    """Claim `actor`'s decision, prepare, run the labelled execution, optionally change the world, complete. One record."""
    lease, wrote = w.claim(actor)
    out = {"lease": lease_view(lease), "claim_wrote": wrote}
    if lease is None:
        out["state"] = state(w)
        return out
    prepared = step(w, w.reviews().prepare, lease)
    out["prepare"] = prepared
    bundle = prepared.get("value")
    if bundle is None:
        out["state"] = state(w)
        return out
    result = receipt_of(w, lease, bundle, **options)
    if intervene is not None:
        intervene(w, lease)
    out["complete"] = step(w, w.reviews().complete, lease, bundle, result)
    out["state"] = state(w)
    return out


# ---- the cases ---------------------------------------------------------------------------------------------------------------
def case_ordering(api):
    """M7 `test_executor_orders_independent_assessments_without_dispatch_or_activation` and the request idempotence of `setup_review`."""
    w = World(api)
    out = {"m7_test": "test_executor_orders_independent_assessments_without_dispatch_or_activation"}
    out["request"] = w.request()
    out["request_again"] = w.request()
    out["state_requested"] = state(w)
    out["conductor_first"] = stage(w, CONDUCTOR)
    out["lead"] = stage(w, LEAD)
    out["conductor"] = stage(w, CONDUCTOR)
    prior = out["conductor"].get("prepare", {}).get("value", {}).get("prior_reviews", [])
    out["conductor_saw_lead_first"] = [r["actor"] for r in prior] == [LEAD]
    out["conductor_again"] = stage(w, CONDUCTOR)
    out["lead_again"] = stage(w, LEAD)
    out["request_terminal"] = w.request()
    return out


def case_rejection_or_blockage(api):
    """M7 `test_rejection_or_blockage_cannot_queue_conductor` (blocked False and True)."""
    out = {"m7_test": "test_rejection_or_blockage_cannot_queue_conductor"}
    for blocked in (False, True):
        w = World(api)
        w.request()
        run = stage(w, LEAD, accepted=False, blocked=blocked)
        run["conductor_claim"] = stage(w, CONDUCTOR)
        out["blocked" if blocked else "rejected"] = run
    return out


def case_wrong_receipt_identity(api):
    """M7 `test_wrong_receipt_identity_cannot_complete_review`."""
    w = World(api)
    w.request()
    return {"m7_test": "test_wrong_receipt_identity_cannot_complete_review", "run": stage(w, LEAD, wrong_actor=True)}


def case_changed_basis_or_lease(api):
    """M7 `test_changed_basis_or_lease_during_execution_cannot_commit` (lease, record, policy; the policy change is the receipt's basis
    revision differing from the bundle's, the V20 adapter's own current-policy check never runs)."""
    out = {"m7_test": "test_changed_basis_or_lease_during_execution_cannot_commit"}

    def lease_change(w, lease):
        row = get(w.store, "decisions_pending", lease["id"])
        row.update(owner="other", lease_owner="other", generation=row["generation"] + 1)
        put(w.store, "decisions_pending", row["id"], row)

    def record_change(w, lease):
        row = get(w.store, "threshold_proposals", w.row_id)
        row["activation_blockers"].append("changed")
        put(w.store, "threshold_proposals", row["id"], row)

    for name, intervene, options in (("lease", lease_change, {}), ("record", record_change, {}),
                                     ("policy", None, {"revision": OTHER_REV})):
        w = World(api)
        w.request()
        run = stage(w, LEAD, intervene=intervene, **options)
        run["conductor_rows"] = sorted(r["actor"] for r in scan(w.store, "decisions_pending") if r["actor"] == CONDUCTOR)
        out[name] = run
    return out


def case_blockage_and_interruption(api):
    """M7 `test_execution_blockage_and_interruption_are_taken_from_receipt` (the four parametrizations)."""
    out = {"m7_test": "test_execution_blockage_and_interruption_are_taken_from_receipt"}
    for name, options in (("inspection_blocked", {"inspection_blocked": True}),
                          ("inspection_blocked_interrupted", {"inspection_blocked": True, "interrupted": True}),
                          ("interrupted", {"interrupted": True}), ("spoof_blockage", {"spoof_blockage": True})):
        w = World(api)
        w.request()
        run = stage(w, LEAD, **options)
        run["conductor_claim"] = stage(w, CONDUCTOR)
        out[name] = run
    return out


def case_conductor_rejection(api):
    """M7 `test_conductor_rejection_and_terminal_request_idempotence`."""
    w = World(api)
    w.request()
    out = {"m7_test": "test_conductor_rejection_and_terminal_request_idempotence"}
    out["lead"] = stage(w, LEAD)
    out["conductor"] = stage(w, CONDUCTOR, accepted=False)
    out["terminal_request"] = w.request()
    out["lead_claim"] = stage(w, LEAD)
    return out


def case_attempt_exhaustion(api):
    """M7 `test_attempt_exhaustion_is_visible_on_request`: the claim finds the pinned budget spent and the decision-claim hook marks the
    request failed (`ThresholdReviews.exhausted`); a second request returns the failed row."""
    w = World(api)
    w.request()
    decision = w.decision_row(LEAD)
    decision["retry_budget"] = {"max_attempts": api.max_attempts, "version": 1}
    decision["attempt"] = api.max_attempts
    put(w.store, "decisions_pending", decision["id"], decision)
    out = {"m7_test": "test_attempt_exhaustion_is_visible_on_request"}
    out["claim"] = stage(w, LEAD)
    out["request_again"] = w.request()
    return out


def case_previous_generation_receipt(api):
    """M7 `test_receipt_from_previous_generation_is_not_reused`: the first attempt loses its lease; the second attempt prepares its own
    bundle (its own generation) and is handed the first attempt's cached execution (evidence of the first bundle)."""
    w = World(api)
    w.request()
    cached = {}

    def lose_lease(world, lease):
        row = get(world.store, "decisions_pending", lease["id"])
        row.update(status="retry", owner="replacement", lease_owner="replacement", generation=row["generation"] + 1)
        put(world.store, "decisions_pending", row["id"], row)

    lease, _ = w.claim(LEAD)
    bundle = step(w, w.reviews().prepare, lease)
    cached["result"] = receipt_of(w, lease, bundle["value"])
    lose_lease(w, lease)
    out = {"m7_test": "test_receipt_from_previous_generation_is_not_reused", "first_lease": lease_view(lease), "first_prepare": bundle}
    out["first_complete"] = step(w, w.reviews().complete, lease, bundle["value"], cached["result"])
    second, _ = w.claim(LEAD)
    out["second_lease"] = lease_view(second)
    prepared = step(w, w.reviews().prepare, second)
    out["second_prepare"] = prepared
    out["second_complete"] = step(w, w.reviews().complete, second, prepared["value"], cached["result"])
    out["state"] = state(w)
    return out


def case_lease_actor_or_aggregate(api):
    """M7 `test_caller_cannot_change_lease_actor_or_aggregate` ({'actor': 'conductor'}, {'_bucket': 'tasks'}), plus a lease without an
    aggregate; the honest lease then completes."""
    out = {"m7_test": "test_caller_cannot_change_lease_actor_or_aggregate"}
    for name, override in (("actor", {"actor": CONDUCTOR}), ("bucket_tasks", {"_bucket": "tasks"}), ("no_bucket", {"_bucket": None})):
        w = World(api)
        w.request()
        lease, _ = w.claim(LEAD)
        forged = {k: v for k, v in {**lease, **override}.items() if not (k == "_bucket" and v is None)}
        refusal = step(w, w.reviews().prepare, forged)
        honest = stage_from(w, lease)
        out[name] = {"forged": refusal, "honest": honest}
    return out


def stage_from(w, lease, **options):
    """`complete` for a lease already claimed (prepare, execute, complete)."""
    prepared = step(w, w.reviews().prepare, lease)
    result = receipt_of(w, lease, prepared["value"], **options)
    return {"prepare": prepared, "complete": step(w, w.reviews().complete, lease, prepared["value"], result), "state": state(w)}


def case_empty_answer(api):
    """M7 `test_empty_execution_answer_cannot_satisfy_assessment`."""
    w = World(api)
    w.request()
    lease, _ = w.claim(LEAD)
    prepared = step(w, w.reviews().prepare, lease)
    result = receipt_of(w, lease, prepared["value"])
    receipt = w.artifacts.document(result["execution_ref"])
    receipt["answer"] = {}
    result["execution_ref"] = w.artifacts.add(receipt)
    return {"m7_test": "test_empty_execution_answer_cannot_satisfy_assessment", "prepare": prepared,
            "complete": step(w, w.reviews().complete, lease, prepared["value"], result), "state": state(w)}


def case_run_membership(api):
    """M7 `test_collection_run_membership_is_required`."""
    w = World(api)
    request = w.request()
    run = get(w.store, "threshold_proposal_runs", w.run_id)
    run["proposals"] = []
    put(w.store, "threshold_proposal_runs", run["id"], run)
    return {"m7_test": "test_collection_run_membership_is_required", "first": request, "again": w.request(), "state": state(w)}


def case_exhausted(api):
    """The module half of M7 `test_post_commit_error_does_not_rewrite_success` (the OSError wrapper is the executor's) and the branches of
    `exhausted` no test names: a stale exhausted lead cannot fail the conductor's pending stage; a request that is absent, a decision that
    is not the awaited one, and the awaited decision."""
    out = {"m7_test": "test_post_commit_error_does_not_rewrite_success (module half)"}
    w = World(api)
    w.request()
    out["lead"] = stage(w, LEAD)
    lead = w.decision_row(LEAD)

    def exhaust(world, decision):
        with world.store.transaction() as tx:
            return world.api.exhausted(tx, decision)

    out["stale_lead"] = step(w, exhaust, w, lead)
    out["state_after_stale"] = state(w)
    conductor = w.decision_row(CONDUCTOR)
    out["conductor_exhausted"] = step(w, exhaust, w, conductor)
    out["state_after_conductor"] = state(w)
    out["conductor_exhausted_again"] = step(w, exhaust, w, conductor)
    absent = {**conductor, "input": {"request_id": "absent-request"}}
    out["request_absent"] = step(w, exhaust, w, absent)
    v = World(api, "2")
    v.request()
    stranger = {**v.decision_row(LEAD), "id": "another-decision"}
    out["other_decision"] = step(v, exhaust, v, stranger)
    out["lead_exhausted"] = step(v, exhaust, v, v.decision_row(LEAD))
    out["state_lead_exhausted"] = state(v)
    return out


def case_request_refusals(api):
    """No M7 test (every `require` of `_row`, reached through `request`): each planted fault of the proposal row, its run or its artifact."""
    out = {"m7_test": "none"}

    def row_change(**changes):
        def mutate(w):
            row = {**get(w.store, "threshold_proposals", w.row_id), **changes}
            put(w.store, "threshold_proposals", w.row_id, row)
            run = get(w.store, "threshold_proposal_runs", w.run_id)
            run["proposals"] = [row]
            put(w.store, "threshold_proposal_runs", w.run_id, run)
        return mutate

    def run_change(**changes):
        def mutate(w):
            put(w.store, "threshold_proposal_runs", w.run_id, {**get(w.store, "threshold_proposal_runs", w.run_id), **changes})
        return mutate

    def remove(bucket, key_of):
        def mutate(w):
            with w.store.transaction() as tx:
                tx.data.pop((bucket, key_of(w)), None)
        return mutate

    def artifact(document_of):
        def mutate(w):
            w.artifacts.docs[w.evidence_ref] = document_of(w)
        return mutate

    faults = (
        ("absent_row", remove("threshold_proposals", lambda w: w.row_id)),
        ("not_calculated", row_change(status="ready")),
        ("activation_ready", row_change(activation_ready=True)),
        ("blocker_missing", row_change(activation_blockers=[])),
        ("run_missing", remove("threshold_proposal_runs", lambda w: w.run_id)),
        ("run_activation_ready", run_change(activation_ready=True)),
        ("row_not_in_run", run_change(proposals=[])),
        ("artifact_project", artifact(lambda w: {"project_key": "other", "proposals": [w.row["proposal"]]})),
        ("artifact_proposal", artifact(lambda w: {"project_key": PROJECT, "proposals": []})),
        ("run_identity", row_change(run_id="a-run-id-that-is-not-the-digest")),
        ("row_identity", row_change(id="a-row-id-that-is-not-the-digest")),
    )
    for name, mutate in faults:
        w = World(api)
        mutate(w)
        if name == "run_identity":  # the run stored under the row's (wrong) run id, bound to the changed row
            put(w.store, "threshold_proposal_runs", "a-run-id-that-is-not-the-digest", get(w.store, "threshold_proposal_runs", w.run_id))
        out[name] = w.request()
    return out


def case_prepare_refusals(api):
    """No M7 test (every `require` of `_prepare`, reached through `prepare`): the claimed lead lease against a world changed after the
    claim, and the aggregate/bucket guard."""
    out = {"m7_test": "none"}

    def decision_change(**changes):
        def mutate(w, lease):
            put(w.store, "decisions_pending", lease["id"], {**get(w.store, "decisions_pending", lease["id"]), **changes})
        return mutate

    def request_change(**changes):
        def mutate(w, lease):
            put(w.store, "threshold_review_requests", w.request_id(), {**w.request_row(), **changes})
        return mutate

    def request_gone(w, lease):
        with w.store.transaction() as tx:
            tx.data.pop(("threshold_review_requests", w.request_id()), None)

    def row_changed(w, lease):
        row = get(w.store, "threshold_proposals", w.row_id)
        run = get(w.store, "threshold_proposal_runs", w.run_id)
        row["activation_blockers"] = [BLOCKER, "changed"]
        run["proposals"] = [deepcopy(row)]
        put(w.store, "threshold_proposals", w.row_id, row)
        put(w.store, "threshold_proposal_runs", w.run_id, run)

    for name, mutate in (("wrong_phase", decision_change(phase="proposal")), ("wrong_actor", decision_change(actor=CONDUCTOR)),
                         ("request_missing", request_gone), ("identity", request_change(id="another-request")),
                         ("order", request_change(status="assessed")), ("conductor_order", request_change(status="awaiting_conductor")),
                         ("input_changed", request_change(binding="not-the-binding")), ("row_changed", row_changed)):
        w = World(api)
        w.request()
        lease, _ = w.claim(LEAD)
        mutate(w, lease)
        out[name] = step(w, w.reviews().prepare, lease)
    return out


def case_complete_refusals(api):
    """No M7 test beyond those above (every `require` of `complete` before its transaction, each from a fresh world at the lead stage)."""
    out = {"m7_test": "none"}
    variants = (
        ("result_not_bool", {"result_changes": {"accepted": "yes"}}),
        ("result_no_reason", {"result_changes": {"reason": 7}}),
        ("evidence_review_differs", {"review": {"request_id": "another"}}),
        ("basis_revision_differs", {"result_changes": {"basis_revision": OTHER_REV}}),
        ("inspection_status_differs", {"result_changes": {"inspection_blocked": True, "accepted": False}}),
        ("interrupted", {"interrupted": True}),
        ("blocked_execution_approves", {"inspection_blocked": True, "result_changes": {"accepted": True}}),
        ("answer_without_blocked", {"answer": {"accepted": True, "reason": "fixture"}}),
        ("answer_not_dict", {"answer": ["accepted"]}),
        ("assessment_differs", {"result_changes": {"reason": "another reason"}}),
        ("blocked_accepts", {"blocked": True}),
        ("blocked_by_result", {"result_changes": {"blocked": True}, "accepted": True}),
    )
    for name, options in variants:
        w = World(api)
        w.request()
        out[name] = stage(w, LEAD, **options)
    w = World(api)
    w.request()
    lease, _ = w.claim(LEAD)
    prepared = step(w, w.reviews().prepare, lease)
    changed = {**prepared["value"], "scope": "another_scope"}
    result = receipt_of(w, lease, prepared["value"], review=changed)
    out["bundle_basis_changed"] = {"complete": step(w, w.reviews().complete, lease, changed, result), "state": state(w)}
    return out


def case_records(api):
    """V22 R-tr3 (no M7 test; M7's `ExecutionRecovery` builds `ThresholdReviews(...)._row` at `execution_recovery.py:94` and puts the
    request inline at `:252`): `row` over the planted row and its refusals; `restore` writes the request under its id, again, and a changed one."""
    out = {"m7_test": "none"}
    w = World(api)
    records = api.records(w.store, w.org, w.artifacts)

    def row_of(world, row_id):
        with world.store.transaction() as tx:
            return records.row(tx, row_id)

    out["row"] = step(w, row_of, w, w.row_id)
    out["row_absent"] = step(w, row_of, w, "absent-row")
    request = {"id": "request-1", "row_id": w.row_id, "status": "failed", "reviews": [], "binding": w.api.digest(w.row)}

    def restore(world, body):
        with world.store.transaction() as tx:
            return records.restore(tx, body)

    out["restore"] = step(w, restore, w, request)
    out["restored"] = get(w.store, "threshold_review_requests", "request-1")
    out["restore_again"] = step(w, restore, w, request)
    out["restore_changed"] = step(w, restore, w, {**request, "status": "awaiting_lead"})
    out["restored_changed"] = get(w.store, "threshold_review_requests", "request-1")
    refused = step(w, restore, w, {"row_id": w.row_id})
    out["restore_without_id"] = refused
    return out


CASES = (case_ordering, case_rejection_or_blockage, case_wrong_receipt_identity, case_changed_basis_or_lease,
         case_blockage_and_interruption, case_conductor_rejection, case_attempt_exhaustion, case_previous_generation_receipt,
         case_lease_actor_or_aggregate, case_empty_answer, case_run_membership, case_exhausted, case_request_refusals,
         case_prepare_refusals, case_complete_refusals, case_records)


def run(api) -> dict:
    return {fn.__name__[len("case_"):]: fn(api) for fn in CASES}
