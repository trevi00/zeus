"""Shared S6 scenario steps (`coordination.continuation_research`): the OWNER research paths of M7 `Continuation`
(DESIGN-s6 §7; TRACE-s6 §2), in the sequences of the M7 tests (tests/test_continuation_research.py).

- **receipt** (flow `held`). `accept_research` of the exact scoped receipt, its consumption by the tick
  (`research_resolved`, one evidence-repair successor), the cached replay and `research_receipt_conflict`, every
  transform of the M7 refusal matrix (nothing stored, the family stays held), an absent verifier, evidence that is not
  held at acceptance, evidence lost after acceptance (the hold stays until it verifies again), a restarted controller
  and a second one consuming the stored receipt once, an unreadable or changed lane after acceptance.
- **supplement** (flow `accepted003`). The baseline receipt refuses `research_scope_unverified`; explicit ownership
  reconciliation of the repair intent; the labelled promotion rows; `supplement_research_scope` (recorded, cached,
  conflict); the receipt then accepted with coverage `owner_supplement` and consumed by a tick; every forged change
  of the M7 refusal matrix; a supplement (or its proofs) changed after acceptance keeps the hold.
- **capacity** (flow `budget_refused`). Without a grant the ticks change nothing and `status` names the owner action;
  one exact grant reserves one successor that the next tick admits through the ordinary path; every change of the M7
  refusal matrix refuses with no effect; the identical grant replays cached and a conflicting one is refused; stale
  grant authority holds before the next new effect until it verifies again.

Layer: harness (never shipped)

The starting states are the RECORDED, labelled rows of `compare/fixtures/s6/research.json` (generated from the M7
test flows by `compare/fixtures/s6/generate_research.py`); every case starts from a fresh `load`. `api` is the
`s6_tick` API plus `Continuation(..., evidence=)`, and the M7 `domain.continuation` names the M7 document builders use
(`RESEARCH_RECEIPT_SCHEMA`, `SUPPLEMENT_SCHEMA`, `CAPACITY_GRANT_SCHEMA`, `observed_attempt`, `successor_id`). The
evidence port is a LABELLED double (`put(text)` and `verify(ref)`, plain exceptions for what is not held or does not
verify; M7 maps them to `research_evidence_unreadable`). The compared results are the owner-command results or
refusals, whether a refused call wrote anything, a compact projection of the intents, receipts, supplements, grants
and jobs, and the digests of both stores.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from s6_tick import Conductor, Lanes, call, canonical_digest, records, ticking, tokens

FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "s6" / "research.json").read_text(
    encoding="utf-8"))
TEXTS = FIXTURE["texts"]
POLICY_ID = "policy-1"
INVESTIGATIONS = "portfolio_investigations"
DISPATCHES = "research_investigation_dispatches"
RECEIPTS, SUPPLEMENTS, GRANTS = ("continuation_research_receipts", "continuation_research_supplements",
                                 "continuation_capacity_grants")
BINDINGS, LANE_BINDINGS = "portfolio_bindings", "continuation_bindings"


def digest_of(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


REPORT_REF = digest_of(TEXTS["report"])


class Evidence:
    """LABELLED double of the research-evidence port: `put(text)` holds the text under its digest reference;
    `verify(ref)` passes when the ref is held and its text still has that digest, and raises a plain exception
    otherwise (M7 maps every one to `research_evidence_unreadable`)."""

    def __init__(self, held):
        self.held, self.blocked = dict(held), set()

    def put(self, text):
        ref = digest_of(text)
        self.held[ref] = text
        return ref

    def verify(self, ref):
        if ref in self.blocked:
            raise PermissionError("evidence unreadable (injected)")
        if ref not in self.held:
            raise FileNotFoundError("evidence bytes not held (injected)")
        if digest_of(self.held[ref]) != ref:
            raise ValueError("evidence bytes changed (injected)")


class RWorld:
    """Fresh stores loaded from one recorded flow: a control store (the Fleet's, also the Portfolio's) and a lane
    store, every row put in fixture order; a Fleet over the control store (its registry row exists), the lane port,
    the labelled evidence port and one controller."""

    def __init__(self, api, flow):
        self.api, self.flow = api, flow
        data = FIXTURE["flows"][flow]
        self.ids, self.document, self.pin, self.runtime_document = (data["ids"], data["policy_document"], data["pin"],
                                                                    data["runtime"])
        self.clock = ticking()
        self.control, self.lane_store = api.MemoryStore(), api.MemoryStore()
        for store, rows in ((self.control, data["control"]), (self.lane_store, data["lane"])):
            with store.transaction() as tx:
                for row in rows:
                    tx.put(row["bucket"], row["id"], row["body"])
        self.fleet = api.Fleet(self.control, self.clock, tokens())
        self.conductor = Conductor(self.lane_store)
        self.lanes = Lanes(api, self.lane_store)
        self.evidence = Evidence(data["evidence"])
        self.controller = self.build()

    def runtime(self, lane_id):
        return dict(self.runtime_document)

    def build(self, lanes=None, evidence="port"):
        return self.api.Continuation(self.control, fleet=self.fleet, lanes=lanes or self.lanes,
                                     conductor=self.conductor, validate=self.api.validate_manifest, clock=self.clock,
                                     evidence=self.evidence if evidence == "port" else evidence)

    def tick(self, controller=None):
        return (controller or self.controller).tick(POLICY_ID, pin_sha256=self.pin["sha256"], runtime=self.runtime)

    def state(self):
        return {"control": canonical_digest(records(self.control)), "lane": canonical_digest(records(self.lane_store)),
                "conductor_calls": list(self.conductor.calls)}


def load(api, flow):
    return RWorld(api, flow)


# ---- reading the stores -------------------------------------------------------------------------------
def scan(store, bucket):
    with store.transaction() as tx:
        return {row["id"]: row for row in tx.scan(bucket)}


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def intents(world):
    return scan(world.control, "continuation_intents")


def jobs(world):
    return scan(world.control, "fleet_jobs")


def only(rows, **match):
    found = [row for row in rows.values() if all(row.get(k) == v for k, v in match.items())]
    assert len(found) == 1, found
    return found[0]


def mutate(world, bucket, key, change):
    """A LABELLED injected fault: one authoritative row changed in place. Returns the row to restore."""
    row = get(world.control, bucket, key)
    put(world.control, bucket, key, {**row, **change})
    return (bucket, key, row)


def restore(world, undo):
    put(world.control, *undo)


def guarded(world, fn, *args, **kwargs):
    """`call`, plus whether the call left every record of both stores unchanged."""
    before = world.state()
    out = call(fn, *args, **kwargs)
    out["records_unchanged"] = before == world.state()
    return out


def view(world):
    """The research-owner fields of every intent, the stored owner documents and the Fleet jobs (compact)."""
    rows = sorted(intents(world).values(), key=lambda r: (str(r.get("created_at")), r["id"]))
    return {
        "intents": [{"id": r["id"], "route": r.get("route"), "state": r.get("state"), "reason_code": r.get("reason_code"),
                     "family": r.get("family"), "origin_job": r.get("origin_job"), "successor_job": r.get("successor_job"),
                     "research_coverage": r.get("research_coverage"), "research_receipt": r.get("research_receipt"),
                     "capacity_grant": r.get("capacity_grant"), "version": r.get("version"),
                     "hold": (r.get("hold") or {}).get("reason_code"),
                     "ownership": (r.get("ownership") or {}).get("state"),
                     "history": [[e.get("state"), e.get("reason_code")] for e in r.get("history") or []]}
                    for r in rows],
        "receipts": sorted([[k, v.get("receipt_sha256"), v.get("coverage")] for k, v in scan(world.control, RECEIPTS).items()]),
        "supplements": sorted([[k, v.get("supplement_sha256")] for k, v in scan(world.control, SUPPLEMENTS).items()]),
        "grants": sorted([[k, v.get("grant_sha256")] for k, v in scan(world.control, GRANTS).items()]),
        "jobs": {k: [v.get("status"), v.get("reason_code")] for k, v in sorted(jobs(world).items())}}


def shown(world, intent_id):
    status = world.controller.status(POLICY_ID)
    row = next(r for r in status["intents"] if r["id"] == intent_id)
    return {"row": {k: row.get(k) for k in ("state", "next_action", "receipt", "supplement", "capacity_grant",
                                             "research_receipt", "refusal")},
            "held_families": status["held_families"], "capacity": status.get("capacity")}


def research_rows(world):
    """What the research owners wrote: the investigations and the dispatches (never rewritten by a receipt)."""
    return canonical_digest([scan(world.control, INVESTIGATIONS), scan(world.control, DISPATCHES)])


def research_of(world):
    return intents(world)[world.ids["research_intent"]]


def dispatch_of(world):
    return get(world.control, DISPATCHES, world.ids["investigation"])


def skipped(result, subject):
    value = result.get("value") or {}
    return [s for s in value.get("skipped", []) if s["subject"] == subject]


def outcome(world, subject):
    return {"state": intents(world)[subject]["state"], "jobs": len(jobs(world))}


# ---- the owner's documents (the shapes of the M7 test helpers) -----------------------------------------
def receipt_for(world, **overrides):
    """What the owner submits: the attempt set the status projection names for this intent, each attempt's
    inspection from its own lane evidence, the dispatch binding and the evidence refs (the report is held)."""
    dc = world.api.domain
    research, dispatch = research_of(world), dispatch_of(world)
    assert world.evidence.put(TEXTS["report"]) == REPORT_REF
    attempts = next(r for r in world.controller.status(POLICY_ID)["intents"] if r["id"] == research["id"])["attempts"]
    rows, lane = jobs(world), world.api.LaneEvidence(world.lane_store)
    return {"schema": dc.RESEARCH_RECEIPT_SCHEMA, "intent_id": research["id"], "policy_id": POLICY_ID,
            "policy_sha256": world.controller.policy(POLICY_ID)["policy_sha256"], "family": research["family"],
            "attempts": [{**a, "inspection": dc.observed_attempt(rows[a["job"]], lane.read(rows[a["job"]]))["inspection"]}
                         for a in attempts],
            "investigation": world.ids["investigation"],
            "dispatch": {key: dispatch[key] for key in ("program", "run_id", "manifest_sha256", "snapshot_sha256")},
            "evidence_refs": [REPORT_REF], **overrides}


def accepted_promotion(world, dispatch, revision="9" * 40):
    """LABELLED synthetic promotion evidence of the accepted council run, the rows the real promotion writes
    (as M7's `accepted_promotion`): no model or provider produced them."""
    run_id, graph = dispatch["run_id"], "7" * 64
    run = get(world.control, "autonomous_runs", run_id)
    put(world.control, "autonomous_runs", run_id, {**run, "promotion": {"id": run_id, "graph_sha256": graph}})
    put(world.control, "tasks", "impl-003", {"id": "impl-003", "agent": "worker", "status": "succeeded",
                                             "result": {"candidate": {"revision": revision}}})
    put(world.control, "decisions_pending", "review-003", {
        "id": "review-003", "phase": "review_lead", "status": "succeeded",
        "input": {"candidate": {"revision": revision}}, "result": {"accepted": True}})
    put(world.control, "promotions", run_id, {"id": run_id, "graph_sha256": graph, "evidence": {
        "decision_id": "review-003", "implementation_task_id": "impl-003"}})
    return {"graph_sha256": graph, "candidate_revision": revision, "decision_id": "review-003"}


def supplement_for(world, repair, acceptance, **overrides):
    dc = world.api.domain
    receipt, dispatch = receipt_for(world), dispatch_of(world)
    attestation = world.evidence.put(TEXTS["attestation"])
    return {"schema": dc.SUPPLEMENT_SCHEMA,
            **{k: receipt[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "attempts", "investigation")},
            "dispatch": {**receipt["dispatch"], "id": dispatch["id"], "job_ids_sha256": dispatch["job_ids_sha256"]},
            "captured": [repair["origin_job"]],
            "descendants": [{"job": repair["successor_job"], "parent_job": repair["origin_job"], "intent_id": repair["id"]}],
            "acceptance": acceptance, "report_ref": REPORT_REF, "attestation_ref": attestation, **overrides}


def grant_for(world, **overrides):
    """What the owner submits: the exact refused intent, its source attempt, the inspection and retained candidate
    its lane shows, the completed research receipt digest and a stored rationale."""
    dc = world.api.domain
    refused = intents(world)[world.ids["refused_intent"]]
    child = world.ids["child"]
    rationale = world.evidence.put(TEXTS["rationale"])
    evidence = world.api.LaneEvidence(world.lane_store).read(jobs(world)[child])
    candidate = evidence["task"]["result"]["candidate"]
    return {"schema": dc.CAPACITY_GRANT_SCHEMA, "policy_id": POLICY_ID,
            "policy_sha256": world.controller.policy(POLICY_ID)["policy_sha256"], "family": refused["family"],
            "intent_id": refused["id"], "route": dc.EVIDENCE_REPAIR, "refusal": "correction_budget_exhausted",
            "source": {"job": child, "generation": refused["generation"], "attempt": refused["attempt"],
                       "evidence_sha256": refused["evidence_sha256"],
                       "inspection": evidence["operation"]["owner_handoff"]["inspection"]["id"]},
            "candidate": {"revision": candidate["revision"], "tree": candidate["tree"]},
            "research_receipt_sha256": intents(world)[world.ids["research_intent"]]["research_receipt"],
            "rationale_ref": rationale, **overrides}


def grant(world, document, controller=None, **ports):
    ports = {"pin_sha256": world.pin["sha256"], "runtime": world.runtime, **ports}
    return (controller or world.controller).grant_capacity(document, **ports)


# ---- group 1: receipt (flow held) -------------------------------------------------------------------------
def _drop_one(document, world):
    return {"attempts": document["attempts"][:1]}


def _foreign_sha(document, world):
    return {"policy_sha256": "0" * 64}


def _foreign_policy(document, world):
    return {"policy_id": "policy-2"}


def _wrong_intent(document, world):
    return {"intent_id": only(intents(world), route="evidence_repair")["id"]}


def _unknown_intent(document, world):
    return {"intent_id": "0" * 64}


def _changed_attempt(document, world):
    return {"attempts": [{**document["attempts"][0], "evidence_sha256": "0" * 64}, document["attempts"][1]]}


def _wrong_inspection(document, world):
    return {"attempts": [{**document["attempts"][0], "inspection": "insp-other"}, document["attempts"][1]]}


def _other_family(document, world):
    return {"family": "op-other"}


def _no_evidence(document, world):
    return {"evidence_refs": []}


def _mutable_evidence(document, world):
    return {"evidence_refs": ["docs/notes.md"]}


def _other_run(document, world):
    return {"dispatch": {**document["dispatch"], "run_id": "rp-001.c999"}}


def _unknown_investigation(document, world):
    return {"investigation": "0" * 64}


RECEIPT_REFUSALS = [(f.__name__.lstrip("_"), f) for f in (
    _drop_one, _foreign_sha, _foreign_policy, _wrong_intent, _unknown_intent, _changed_attempt, _wrong_inspection,
    _other_family, _no_evidence, _mutable_evidence, _other_run, _unknown_investigation)]


def exact_receipt(api) -> dict:
    world = load(api, "held")
    out = {"start": view(world), "held_families": world.controller.status(POLICY_ID)["held_families"]}
    research = research_of(world)
    before_rows, old_jobs = research_rows(world), jobs(world)
    old_repair = only(intents(world), origin_job=world.ids["root"], route="evidence_repair")
    out["tick_before"] = call(world.tick)
    document = receipt_for(world)
    out["attempt_jobs"] = [a["job"] for a in document["attempts"]]
    out["accepted"] = guarded(world, world.controller.accept_research, document)
    out["after_accept"] = view(world)
    out["tick"] = call(world.tick)
    out["after_tick"] = view(world)
    out["status"] = shown(world, research["id"])
    out["research_rows_unchanged"] = before_rows == research_rows(world)
    out["failure_verdicts_unchanged"] = all(jobs(world)[k] == old_jobs[k] for k in old_jobs)
    out["old_repair_unchanged"] = intents(world)[old_repair["id"]] == old_repair
    stored, count = scan(world.control, RECEIPTS), len(jobs(world))
    out["replay"] = guarded(world, world.controller.accept_research, document)
    out["tick_again"] = call(world.tick)
    out["tick_restarted"] = call(world.tick, world.build())
    out["one_successor"] = len(jobs(world)) == count and scan(world.control, RECEIPTS) == stored
    out["conflict"] = guarded(world, world.controller.accept_research, {**document, "evidence_refs": ["sha256:" + "6" * 64]})
    out["final"] = view(world)
    out["state"] = world.state()
    return out


def refusal_matrix(api) -> dict:
    out = {}
    for name, change in RECEIPT_REFUSALS:
        world = load(api, "held")
        document = receipt_for(world)
        refused = guarded(world, world.controller.accept_research, {**document, **change(document, world)})
        tick = call(world.tick)
        out[name] = {"accept": refused, "receipts": len(scan(world.control, RECEIPTS)), "tick": tick,
                     "research": outcome(world, world.ids["research_intent"])}
    return out


def evidence_at_acceptance(api) -> dict:
    out = {}
    never = digest_of("never stored")
    faults = {
        "absent_verifier": None,
        "never_stored": lambda w: [never],
        "one_missing": lambda w: sorted([REPORT_REF, never]),
        "blocked": lambda w: (w.evidence.blocked.add(REPORT_REF), [REPORT_REF])[1],
        "tampered": lambda w: (w.evidence.held.__setitem__(REPORT_REF, TEXTS["report"] + "edited after storage\n"),
                               [REPORT_REF])[1]}
    for name, fault in faults.items():
        world = load(api, "held")
        document = receipt_for(world)
        if fault is None:
            unverified = world.build(evidence=None)
            out[name] = {"accept": guarded(world, unverified.accept_research, document)}
            out[name]["receipts"] = len(scan(world.control, RECEIPTS))
            out[name]["accepted"] = call(world.controller.accept_research, document)
            out[name]["tick_unverified"] = call(world.tick, world.build(evidence=None))
            out[name]["research"] = outcome(world, world.ids["research_intent"])
            continue
        document = {**document, "evidence_refs": fault(world)}
        out[name] = {"accept": guarded(world, world.controller.accept_research, document)}
        out[name]["tick"] = call(world.tick)
        out[name]["research"] = outcome(world, world.ids["research_intent"])
    return out


def evidence_lost_after_acceptance(api) -> dict:
    out = {}
    def remove(world):
        world.evidence.held.pop(REPORT_REF)

    def tamper(world):
        world.evidence.held[REPORT_REF] = TEXTS["report"] + "edited after storage\n"

    def block(world):
        world.evidence.blocked.add(REPORT_REF)

    def heal(world):
        world.evidence.blocked.discard(REPORT_REF)
        world.evidence.held[REPORT_REF] = TEXTS["report"]

    for name, fault in (("removed", remove), ("tampered", tamper), ("blocked", block)):
        world = load(api, "held")
        world.controller.accept_research(receipt_for(world))
        stored = scan(world.control, RECEIPTS)
        fault(world)
        lost = call(world.tick, world.build())
        held = {"tick": lost, "research": outcome(world, world.ids["research_intent"]),
                "receipts_unchanged": scan(world.control, RECEIPTS) == stored}
        heal(world)
        again = call(world.tick, world.build())
        second = call(world.tick)
        out[name] = {"lost": held, "restored_tick": again, "next_tick": second, "final": view(world),
                     "receipts_unchanged": scan(world.control, RECEIPTS) == stored}
    return out


def restarted_controllers(api) -> dict:
    world = load(api, "held")
    world.controller.accept_research(receipt_for(world))
    first, second = world.build(), world.build()   # a restarted process and a second controller
    out = {"first": call(world.tick, first), "second": call(world.tick, second), "default": call(world.tick)}
    rows = intents(world)
    research = rows[world.ids["research_intent"]]
    out["completions"] = len([h for h in research["history"] if h["state"] == "completed"])
    out["repairs"] = len([r for r in rows.values()
                          if r["origin_job"] == world.ids["successor"] and r["route"] == "evidence_repair"])
    out["final"] = view(world)
    return out


def lane_after_acceptance(api) -> dict:
    world = load(api, "held")
    world.controller.accept_research(receipt_for(world))
    research_id, successor = world.ids["research_intent"], world.ids["successor"]
    world.lanes.failing = set(jobs(world))
    out = {"unreadable": call(world.tick, world.build())}
    out["unreadable_research"] = outcome(world, research_id)
    world.lanes.failing = set()
    row = get(world.lane_store, "operations", successor)   # LABELLED injected fault: the covered attempt changed
    handoff = row["owner_handoff"]
    put(world.lane_store, "operations", successor, {
        **row, "owner_handoff": {**handoff, "inspection": {**handoff["inspection"], "id": "insp-replaced"}}})
    out["changed"] = call(world.tick)
    out["changed_research"] = outcome(world, research_id)
    return out


def receipt(api) -> dict:
    return {"exact": exact_receipt(api), "refusals": refusal_matrix(api), "evidence_at_acceptance": evidence_at_acceptance(api),
            "evidence_lost": evidence_lost_after_acceptance(api), "restarted": restarted_controllers(api),
            "lane_after_acceptance": lane_after_acceptance(api)}


# ---- group 2: supplement (flow accepted003) -----------------------------------------------------------------
def owned003(world):
    repair = intents(world)[world.ids["repair_intent"]]
    reconciled = call(world.controller.reconcile_ownership, repair["id"])
    acceptance = accepted_promotion(world, dispatch_of(world))
    return repair, reconciled, acceptance


def _descendant(document, **change):
    return {"descendants": [{**document["descendants"][0], **change}]}


def _via_research_intent(document, world):
    return _descendant(document, intent_id=document["intent_id"])


def _other_repair(document, world):
    return next(row for row in intents(world).values() if row["route"] == "evidence_repair"
                and row["family"] != document["family"])


def _foreign_parent(document, world):
    other = _other_repair(document, world)
    return _descendant(document, parent_job=other["origin_job"], intent_id=other["id"])


def _arbitrary_job(document, world):
    other = _other_repair(document, world)
    extra = {"job": other["successor_job"], "parent_job": other["origin_job"], "intent_id": other["id"]}
    return {"descendants": document["descendants"] + [extra]}


def _captured_too_much(document, world):
    return {"captured": sorted(document["captured"] + [document["descendants"][0]["job"]])}


def _incomplete(document, world):
    return {"attempts": document["attempts"][:1]}


def _stale_sample(document, world):
    return {"dispatch": {**document["dispatch"], "job_ids_sha256": "0" * 64}}


def _other_candidate(document, world):
    return {"acceptance": {**document["acceptance"], "candidate_revision": "8" * 40}}


def _missing_attestation(document, world):
    return {"attestation_ref": digest_of("never stored")}


def _no_descendants(document, world):
    return {"descendants": []}


SUPPLEMENT_REFUSALS = [(f.__name__.lstrip("_"), f) for f in (
    _via_research_intent, _foreign_parent, _arbitrary_job, _captured_too_much, _incomplete, _stale_sample,
    _other_candidate, _missing_attestation, _no_descendants)]


def supplement_release(api) -> dict:
    world = load(api, "accepted003")
    research, repair = research_of(world), intents(world)[world.ids["repair_intent"]]
    root, successor = world.ids["root"], world.ids["successor"]
    out = {"start": view(world)}
    baseline = receipt_for(world)
    out["baseline"] = guarded(world, world.controller.accept_research, baseline)
    out["unowned_supplement"] = guarded(world, world.controller.supplement_research_scope,
                                        supplement_for(world, repair, {"graph_sha256": "7" * 64,
                                                                       "candidate_revision": "9" * 40,
                                                                       "decision_id": "review-003"}))
    before_bindings = scan(world.control, BINDINGS)
    out["reconciled"] = guarded(world, world.controller.reconcile_ownership, repair["id"])
    out["binding_added"] = sorted(set(scan(world.control, BINDINGS)) - set(before_bindings))
    out["reconcile_replay"] = guarded(world, world.controller.reconcile_ownership, repair["id"])
    acceptance = accepted_promotion(world, dispatch_of(world))
    out["ownership_alone"] = guarded(world, world.controller.accept_research, baseline)
    before_rows, old_jobs = research_rows(world), jobs(world)
    document = supplement_for(world, repair, acceptance)
    out["supplement"] = guarded(world, world.controller.supplement_research_scope, document)
    out["tick_after_supplement"] = call(world.tick)
    out["supplement_state"] = outcome(world, research["id"])
    out["supplement_replay"] = guarded(world, world.controller.supplement_research_scope, document)
    out["supplement_conflict"] = guarded(world, world.controller.supplement_research_scope,
                                         {**document, "captured": [root, successor]})
    receipt_document = receipt_for(world)
    out["receipt_attempts"] = [a["job"] for a in receipt_document["attempts"]]
    out["accepted"] = guarded(world, world.controller.accept_research, receipt_document)
    out["tick"] = call(world.tick)
    out["after_tick"] = view(world)
    out["status"] = shown(world, research["id"])
    out["other_research_supplements"] = [row["supplement"] for row in world.controller.status(POLICY_ID)["intents"]
                                         if row["route"] == "research" and row["id"] != research["id"]]
    out["research_rows_unchanged"] = before_rows == research_rows(world)
    out["failure_verdicts_unchanged"] = all(jobs(world)[k] == old_jobs[k] for k in old_jobs)
    count = len(jobs(world))
    out["tick_restarted"] = call(world.tick, world.build())
    out["one_successor"] = len(jobs(world)) == count
    out["state"] = world.state()
    return out


def supplement_refusals(api) -> dict:
    out = {}
    for name, change in SUPPLEMENT_REFUSALS:
        world = load(api, "accepted003")
        repair, _, acceptance = owned003(world)
        document = supplement_for(world, repair, acceptance)
        forged = {**document, **change(document, world)}
        refused = guarded(world, world.controller.supplement_research_scope, forged)
        out[name] = {"supplement": refused, "supplements": len(scan(world.control, SUPPLEMENTS)),
                     "receipt": guarded(world, world.controller.accept_research, receipt_for(world))}
    world = load(api, "accepted003")
    repair, _, acceptance = owned003(world)
    document = supplement_for(world, repair, acceptance)
    review = get(world.control, "decisions_pending", "review-003")   # LABELLED injected fault: the review did not accept
    put(world.control, "decisions_pending", "review-003", {**review, "result": {"accepted": False}})
    out["unaccepted_review"] = {"supplement": guarded(world, world.controller.supplement_research_scope, document),
                                "supplements": len(scan(world.control, SUPPLEMENTS))}
    return out


def supplement_rechecked(api) -> dict:
    out = {}

    def review_withdrawn(world):
        row = get(world.control, "decisions_pending", "review-003")
        put(world.control, "decisions_pending", "review-003", {**row, "status": "retry"})
        return ("decisions_pending", "review-003", row)

    def attestation_lost(world):
        [row] = scan(world.control, SUPPLEMENTS).values()
        ref = row["supplement"]["attestation_ref"]
        text = world.evidence.held.pop(ref)
        return ("evidence", ref, text)

    def ownership_changed(world):
        return mutate(world, BINDINGS, world.ids["successor"], {"project_id": "other"})

    def supplement_tampered(world):
        [row] = scan(world.control, SUPPLEMENTS).values()
        put(world.control, SUPPLEMENTS, row["id"], {**row, "supplement": {**row["supplement"], "captured": []}})
        return (SUPPLEMENTS, row["id"], row)

    for name, fault in (("review_withdrawn", review_withdrawn), ("attestation_lost", attestation_lost),
                        ("ownership_changed", ownership_changed), ("supplement_tampered", supplement_tampered)):
        world = load(api, "accepted003")
        repair, _, acceptance = owned003(world)
        world.controller.supplement_research_scope(supplement_for(world, repair, acceptance))
        world.controller.accept_research(receipt_for(world))
        stored, research_id = scan(world.control, RECEIPTS), world.ids["research_intent"]
        undo = fault(world)
        result = call(world.tick, world.build())
        held = {"tick": result, "research": outcome(world, research_id),
                "receipts_unchanged": scan(world.control, RECEIPTS) == stored}
        if undo[0] == "evidence":
            world.evidence.held[undo[1]] = undo[2]
        else:
            restore(world, undo)
        again = call(world.tick)
        out[name] = {"held": held, "restored_tick": again, "final": view(world)}
    return out


def supplement(api) -> dict:
    return {"release": supplement_release(api), "refusals": supplement_refusals(api),
            "rechecked": supplement_rechecked(api)}


# ---- group 3: capacity grant (flow budget_refused) ---------------------------------------------------------
def family_of(world):
    """The family's rows as M7's `budget_refused` names them, found in the recorded intents."""
    rows = intents(world)
    research = rows[world.ids["research_intent"]]
    child = world.ids["child"]
    edge = only(rows, successor_job=child, route="correction")
    parent = edge["origin_job"]
    return {"root": research["family"], "parent": parent, "child": child, "edge": edge, "research": research,
            "earlier": only(rows, origin_job=parent, route="research"), "refused": rows[world.ids["refused_intent"]]}


def _job_row(key_of, change):
    def fault(document, world, family):
        row = get(world.control, "fleet_jobs", key_of(family))
        put(world.control, "fleet_jobs", row["id"], {**row, **change})
        return {}
    return fault


def _marker(document, world, family):
    task = get(world.lane_store, "operations", family["child"])["owner_handoff"]["task_id"]
    put(world.lane_store, "observation_terminations", "marker-1", {"record_id": "marker-1", "task_id": task,
                                                                   "status": "unconfirmed"})
    return {}


def _lost_rationale(document, world, family):
    world.evidence.held.pop(document["rationale_ref"])   # LABELLED injected fault: the bytes are gone
    return {}


def _pending_research(document, world, family):
    row = get(world.control, "continuation_intents", family["research"]["id"])
    put(world.control, "continuation_intents", row["id"], {**row, "state": "research_required"})
    return {}


def _mutate_row(bucket, key_of, change):
    def fault(document, world, family):
        mutate(world, bucket, key_of(family), change)
        return {}
    return fault


CAPACITY_FAULTS = [
    ("invalid_field", lambda d, w, f: {"extra": True}),
    ("wrong_route", lambda d, w, f: {"route": "correction"}),
    ("wrong_refusal", lambda d, w, f: {"refusal": "successor_manifest_refused"}),
    ("foreign_policy_sha", lambda d, w, f: {"policy_sha256": "0" * 64}),
    ("unregistered_policy", lambda d, w, f: {"policy_id": "policy-9"}),
    ("changed_pin", lambda d, w, f: {"_pin_sha256": "0" * 64}),
    ("unverified_pin", lambda d, w, f: {"_pin_sha256": None}),
    ("changed_image", lambda d, w, f: {"_runtime": lambda lane: {**w.runtime(lane), "image": "other:1"}}),
    ("unknown_intent", lambda d, w, f: {"intent_id": "0" * 64}),
    ("wrong_intent", lambda d, w, f: {"intent_id": f["edge"]["id"]}),
    ("research_intent", lambda d, w, f: {"intent_id": f["research"]["id"]}),
    ("foreign_family", lambda d, w, f: {"family": "op-z"}),
    ("changed_evidence", lambda d, w, f: {"source": {**d["source"], "evidence_sha256": "1" * 64}}),
    ("changed_attempt", lambda d, w, f: {"source": {**d["source"], "attempt": d["source"]["attempt"] + 1}}),
    ("changed_inspection", lambda d, w, f: {"source": {**d["source"], "inspection": "insp-other"}}),
    ("foreign_candidate", lambda d, w, f: {"candidate": {**d["candidate"], "revision": "8" * 40}}),
    ("foreign_tree", lambda d, w, f: {"candidate": {**d["candidate"], "tree": "8" * 40}}),
    ("stale_receipt", lambda d, w, f: {"research_receipt_sha256":
                                       scan(w.control, RECEIPTS)[f["earlier"]["id"]]["receipt_sha256"]}),
    ("missing_rationale", lambda d, w, f: {"rationale_ref": digest_of("never")}),
    ("lost_rationale", _lost_rationale),
    ("unknown_execution", _marker),
    ("changed_source_row", _job_row(lambda f: f["child"], {"updated_at": "2099-01-01T00:00:00+00:00"})),
    ("active_family_job", _job_row(lambda f: f["parent"], {"status": "dispatching"})),
    ("unknown_family_job", _job_row(lambda f: f["root"], {"status": "unknown"})),
    ("unresolved_research", _pending_research),
    ("tampered_receipt", _mutate_row(RECEIPTS, lambda f: f["research"]["id"], {"coverage": "x"})),
    ("withdrawn_review", _mutate_row("decisions_pending", lambda f: "review-003", {"status": "retry"})),
    ("changed_ownership", _mutate_row(BINDINGS, lambda f: f["parent"], {"project_id": "other"})),
]


def no_grant(api) -> dict:
    world = load(api, "budget_refused")
    refused_id = world.ids["refused_intent"]
    before = (intents(world), jobs(world))
    out = {"tick": call(world.tick), "tick_restarted": call(world.tick, world.build())}
    out["unchanged"] = before == (intents(world), jobs(world))
    out["status"] = shown(world, refused_id)
    out["state"] = world.state()
    return out


def one_grant(api) -> dict:
    world = load(api, "budget_refused")
    dc = api.domain
    family = family_of(world)
    refused = family["refused"]
    before_intents = {k: v for k, v in intents(world).items() if k != refused["id"]}
    before_jobs, before_receipts, before_rows = jobs(world), scan(world.control, RECEIPTS), research_rows(world)
    document = grant_for(world)
    successor = dc.successor_id(refused["id"])
    out = {"start": view(world), "successor": successor}
    out["granted"] = guarded(world, grant, world, document)
    out["after_grant"] = view(world)
    out["reserved_not_effected"] = {"jobs_unchanged": jobs(world) == before_jobs,
                                    "binding": get(world.lane_store, LANE_BINDINGS, successor)}
    out["tick"] = call(world.tick)
    out["after_tick"] = view(world)
    job = jobs(world)[successor]
    binding = get(world.lane_store, LANE_BINDINGS, successor)
    out["successor_job"] = {"evidence_repair": "Evidence repair" in job["manifest"]["plan"]["objective"],
                            "allowed_paths_inherited": job["manifest"]["plan"]["allowed_paths"]
                            == before_jobs[family["child"]]["manifest"]["plan"]["allowed_paths"]}
    out["binding"] = {"head": binding["workspace"]["head"], "session": binding["session"],
                      "inspection": binding["predecessor"]["inspection_id"]}
    out["history_counts_gates_kept"] = {
        "other_intents_unchanged": all(intents(world)[k] == v for k, v in before_intents.items()),
        "other_jobs_unchanged": all(jobs(world)[k] == v for k, v in before_jobs.items()),
        "receipts_unchanged": scan(world.control, RECEIPTS) == before_receipts,
        "research_rows_unchanged": research_rows(world) == before_rows,
        "policy_cap": world.controller.policy(POLICY_ID)["policy"]["max_corrections"]}
    out["status"] = shown(world, refused["id"])
    out["replay_restarted"] = guarded(world, grant, world, document, controller=world.build())
    count = len(jobs(world))
    out["tick_restarted"] = call(world.tick, world.build())
    out["no_second_successor"] = len(jobs(world)) == count
    out["conflict"] = guarded(world, grant, world, {**document, "rationale_ref": world.evidence.put(
        TEXTS["rationale"] + "again\n")})
    out["final_grants"] = sorted(scan(world.control, GRANTS))
    out["state"] = world.state()
    return out


def grant_refusals(api) -> dict:
    out = {}
    for name, change in CAPACITY_FAULTS:
        world = load(api, "budget_refused")
        family = family_of(world)
        document = grant_for(world)
        changed = change(document, world, family)
        ports = {key[1:]: changed.pop(key) for key in list(changed) if key.startswith("_")}
        before = (intents(world), jobs(world))
        refused = guarded(world, grant, world, {**document, **changed}, **ports)
        out[name] = {"grant": refused, "grants": len(scan(world.control, GRANTS)),
                     "intents_and_jobs_unchanged": before == (intents(world), jobs(world)),
                     "binding": get(world.lane_store, LANE_BINDINGS, api.domain.successor_id(family["refused"]["id"]))}
    return out


def stale_authority(api) -> dict:
    out = {}

    def grant_tampered(world, refused):
        row = get(world.control, GRANTS, refused["id"])
        put(world.control, GRANTS, row["id"], {**row, "grant": {**row["grant"], "family": "op-z"}})
        return (GRANTS, row["id"], row)

    def rationale_gone(world, refused):
        ref = get(world.control, GRANTS, refused["id"])["grant"]["rationale_ref"]
        return ("evidence", ref, world.evidence.held.pop(ref))

    def source_moved(world, refused):
        return mutate(world, "fleet_jobs", refused["origin_job"], {"updated_at": "2099-01-01T00:00:00+00:00"})

    for name, fault in (("grant_tampered", grant_tampered), ("rationale_gone", rationale_gone),
                        ("source_moved", source_moved)):
        world = load(api, "budget_refused")
        refused = family_of(world)["refused"]
        grant(world, grant_for(world))
        undo = fault(world, refused)
        before = jobs(world)
        result = call(world.tick, world.build())
        intent = intents(world)[refused["id"]]
        held = {"tick": result, "state": intent["state"], "hold": (intent.get("hold") or {}).get("reason_code"),
                "jobs_unchanged": jobs(world) == before,
                "binding": get(world.lane_store, LANE_BINDINGS, intent["successor_job"])}
        if undo[0] == "evidence":
            world.evidence.held[undo[1]] = undo[2]
        else:
            restore(world, undo)
        again = call(world.tick)
        after = intents(world)[refused["id"]]
        out[name] = {"held": held, "restored_tick": again, "state": after["state"], "hold": after["hold"],
                     "jobs_added": len(jobs(world)) - len(before)}
    return out


def capacity(api) -> dict:
    return {"no_grant": no_grant(api), "one_grant": one_grant(api), "refusals": grant_refusals(api),
            "stale_authority": stale_authority(api)}


def run(api) -> dict:
    return {"receipt": receipt(api), "supplement": supplement(api), "capacity": capacity(api),
            "unreachable": {
                "portfolio_researched_disposition": "the coarse Portfolio disposition is written by the Portfolio "
                                                    "(a later slice); the recorded rows carry none",
                "repair_fails_again_after_grant": "needs the lane executor (Operation) to run the granted repair; the "
                                                   "recorded flows carry lane rows only"}}
