"""Shared S8 scenario steps (`research.autonomous`): M7 `application/autonomous.py` (`AutonomousRun`: `status`, `claim`,
`_transition`, `run`, `_pipeline`, `_freeze_packet`, `_implement_and_promote`, `_role`, `_require_admitted`,
`_verify_execution`, `_deliver`, `_check_deadline`, `_residuals`, `_promote`, `_finish`; `AutonomousRefused`,
`provider_labels`, `bus_view`, `_safe_binding`, `row_digest`), characterized BEFORE the autonomous module moves (DESIGN-s8 §2 row
`research.autonomous` and §7 V12: the move goes to `coordination.application.autonomous` in the NEXT pilot, so this golden is
placement-neutral: it observes SOURCE behaviour only; the branch table `branch-table-research.txt` section
`application/autonomous.py`: 44 raises, each covered below or named unreachable with its reason).

- **a1_manifest**: M7 `test_manifest_reuses_operation_rules_and_refuses_naive_deadline_or_missing_research`.
- **a2_cycle**: M7 `test_normal_cycle_promotes_...` (the promotion in one transaction, the six starts, the labels, the durations,
  the invocations, the cached replay, the configuration mismatch), `status` (known and unknown run), the observer's stage events,
  `provider_labels`, `bus_view`, `_safe_binding`, `row_digest`, the delivery namespace on the run row (M7
  `test_the_run_row_records_its_delivery_namespace_...`).
- **a3_rejected**: M7 `test_rejected_review_and_rejected_design_never_promote_or_dispatch_further`, the other `design_*` and
  `operation_*` outcomes (`OUTCOME_BY_REASON`).
- **a4_artifacts**: M7 `test_missing_corrupt_or_unrelated_role_artifact_...`, `test_mismatched_review_verdict_or_shared_role_session_...`,
  `test_review_evidence_is_bound_to_the_reviewed_candidate_and_the_worker_to_its_base`,
  `test_unbound_stale_or_unsupported_role_output_...`, and every `_freeze_packet` / `_verify_execution` / `_role` refusal.
- **a5_deadline**: M7 `test_deadline_passing_after_the_review_or_before_the_worker_never_promotes`, `_check_deadline`.
- **a6_residue_budget**: M7 `test_running_residue_is_refused_without_takeover_and_budget_refusal_ends_exhausted`, the settlement and
  start-cap refusals, `role_residue`, `_require_admitted`, the run's own exception mapping, `_finish`.
- **a7_claim**: every `claim` refusal (`route_mismatch`, `running_residue`, `residue`, `deadline_expired`, `configuration_mismatch`,
  the ContractError mapping) and M7 `test_claim_pins_the_route_before_any_message_...` (the module side, through a direct bus double).
- **a8_promotion**: M7 `test_promotion_is_idempotent_refuses_conflict_and_rolls_back_with_the_receipt`, and every `_promote` refusal
  (`promotion_*_unproven`, `evidence_answer_mismatch`, `run_state_changed`, the deadline) with the digests of `autonomous_runs`,
  `operations`, `outbox` and the promotion buckets before and after.
- **a9_delivery**: `_deliver` (`foreign_message`, `publication_incomplete`, the dead-lettered invalid message, the foreign notice).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a
target) driver builds. The executor, the role artifacts, the evidence source and the clock are LABELLED doubles with the result
shapes of the M7 `tests/test_autonomous.py` fixtures (`FakeExecutor`, `Artifacts`, `Clock`, `evidence_ref_of`); the bus, the
collector and the budget are the labelled copies of `s5_operation` (M7 `tests/test_operation.py`). The real
`autonomous_roles`/`autonomous_evidence` adapters are later families and never run here; no model, Git, provider, network,
process or PostgreSQL is touched. Where a state has no honest call path (a prior row edited, a seam wrapped around `_promote`, a
direct call with a stub for `wrapped`) the case is LABELLED where it is made. M7 tests that need the S10 CLI or a Redis bus are
`unreachable`, named, at the end of group a9.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import s5_operation as O
import s8_research_program as R

CANARY = "CANARY-must-never-be-emitted"
BASE = O.BASE
CANDIDATE = "c" * 40          # the worker's commit; the independent review executes at this revision
SKILLS_REF = "sha256:" + "5" * 64
SOURCE_SHA = "b" * 64
LATE = "2031-01-01T00:00:00+00:00"   # past the fixed deadline below
START = "2029-01-01T00:00:00+00:00"
DEADLINE = "2030-01-01T00:00:00+00:00"
RUN = "auto-001"
REPO = "r"
PROMOTION_BUCKETS = ("promotions", "knowledge_nodes", "knowledge_edges")
WATCHED = ("autonomous_runs", "operations", "outbox") + PROMOTION_BUCKETS
GOAL, IDENTITY, BOUND_GOAL = O.GOAL, O.IDENTITY, O.BOUND_GOAL

RESEARCH = {"sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": SOURCE_SHA, "locator": "git", "revision": BASE,
                         "read_scope": "all"}],
            "claims": [{"id": "c1", "kind": "fact", "text": "advisory lock " + CANARY, "source_ids": ["s1"]}],
            "questions": [{"id": "q1", "question": "where is the runbook?", "blocking": True, "status": "answered",
                           "claim_ids": ["c1"]}],
            "ssot": {"searched_paths": ["docs"], "searched_symbols": ["RUNBOOK"], "authoritative_definition": "docs/zeus/operations",
                     "callers": [], "evidence": ["tests/test_dge.py"], "unknowns": ["contention"], "decision": "improve",
                     "rationale": "extend the runbook",
                     "transition": {"compatibility": "additive", "rollback": "revert", "retirement": "none"}},
            "needs_user": False, "user_question": None}
FINDING = {"id": "f1", "criterion": "focused tests pass", "severity": "minor", "scenario": "style", "claim_ids": ["c1"],
           "trigger": None, "impact": None, "mitigation": None}
ROLE_OUTPUTS = {"researcher": RESEARCH, "proposer": {"summary": "bind the plan", "claim_ids": ["c1"]},
                "attacker": {"findings": [FINDING]},
                "arbiter": {"verdict": "accept", "rationale": "ok", "research_question": None,
                            "dispositions": [{"finding_id": "f1", "decision": "deferred", "reason": "backlog"}]}}


def canonical_digest(value) -> str:
    return R.canonical_digest(value)


def manifest_document(**overrides):
    """M7 `manifest(**overrides)` (tests/test_autonomous.py): the `urn:zeus:autonomous:1` document."""
    document = {"schema": "urn:zeus:autonomous:1", "id": RUN, "base_revision": BASE, "goal": dict(GOAL),
                "plan": {"objective": "Add the RUNBOOK note " + CANARY, "acceptance_criteria": ["focused tests pass"],
                         "allowed_paths": ["docs/zeus/operations/autonomous-dge-001/RUNBOOK.md"]},
                "budget": {"per_host": 8, "total": 16},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2},
                "deadline": DEADLINE,
                "research": {"topic": "runbook note", "questions": ["where is the runbook?"], "search_scope": ["docs"]}}
    document.update(overrides)
    return document


def valid(api, **overrides):
    return api.validate_autonomous_manifest(manifest_document(**overrides), api.packaged_policy())


# ---- labelled doubles (M7 tests/test_autonomous.py) ----------------------------------------------------------------------
def evidence_ref_of(api, details) -> str:
    return "sha256:" + hashlib.sha256(api.canonical(details).encode()).hexdigest()


class Artifacts:
    """LABELLED. M7 `Artifacts`: content-addressed in-memory stand-in for FileArtifacts (put/document with integrity)."""

    def __init__(self, api):
        self.api, self.bodies, self.raises, self.override = api, {}, None, None   # labelled seams: raise / answer instead

    def put(self, body):
        key = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.bodies[key] = body
        return "sha256:" + key

    def corrupt(self, ref):
        self.bodies[ref[7:]] = self.bodies[ref[7:]] + " "   # bytes no longer hash to the reference

    def document(self, ref):
        if self.raises is not None:
            raise self.raises
        if self.override is not None:
            return self.override
        if ref not in {"sha256:" + k for k in self.bodies}:
            raise FileNotFoundError(ref)
        body = self.bodies[ref[7:]]
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != ref[7:]:
            raise self.api.EvidenceUnavailable("evidence_corrupt")   # what the FileArtifacts-backed port raises
        return json.loads(body)


class Clock:
    """LABELLED. M7 `Clock`: a settable ISO string; `after_review` (M7) moves it after the review. `flip` is the labelled
    extension: `flip = (reads, value)` makes every read after the first `reads` reads answer `value` (the clock passes the
    deadline between two steps of the run, deterministic by read count); `reads` is the number of reads made so far."""

    def __init__(self, now=START):
        self.now, self.after_review, self.flip, self.reads = now, None, None, 0

    def __call__(self):
        self.reads += 1
        if self.flip is not None and self.reads > self.flip[0]:
            return self.flip[1]
        return self.now


class Observer:
    """LABELLED. A recording observer: `emit` keeps (name, outcome, the keyword facts); `audit_system` None (no audit sink)."""

    audit_system = None

    def __init__(self):
        self.events = []

    def emit(self, name, outcome, **facts):
        self.events.append([name, outcome, facts])


class Executor:
    """LABELLED. M7 `FakeExecutor` (tests/test_autonomous.py): settles the guarded row the way the real executor would and
    persists the execution artifact plus the settled invocation reservation. `evidence` injects: none, corrupt, unrelated,
    verdict. `intercept` (labelled extension) maps an agent to `fn(call)` run in place of `execute_one`: `call()` is the real
    fixture execution; the return value is what the executor reports."""

    def __init__(self, api, svc, artifacts, outputs=None, verdict=True, role_status="succeeded", wrong_agent=False,
                 evidence="bound", shared_thread=False, clock=None, project_skills=False, review_basis=CANDIDATE,
                 implementation_basis=BASE, intercept=None, worker="succeeded"):
        self.api, self.svc, self.artifacts = api, svc, artifacts
        self.outputs, self.verdict = {**ROLE_OUTPUTS, **(outputs or {})}, verdict
        self.role_status, self.wrong_agent, self.calls = role_status, wrong_agent, []
        self.evidence, self.shared_thread, self.clock = evidence, shared_thread, clock
        self.project_skills, self.review_basis, self.implementation_basis = project_skills, review_basis, implementation_basis
        self.intercept = intercept or {}
        self.worker = worker   # labelled extension: the implementation task's settled status (not `succeeded` = a failed worker)

    def _persist(self, tx, record, bucket, answer, stage, evidence_ref, basis=BASE):
        if self.evidence == "none":
            return "sha256:" + "0" * 64
        key = record["id"] if self.evidence != "unrelated" else "someone-else"
        reservation = {"id": "res-" + record["id"], "bucket": bucket, "task_id": key, "generation": 1, "attempt": 1,
                       "invocation": 1, "stage": stage, "status": "settled", "outcome": "accepted",
                       "usage": {"source": "provider", "total_tokens": 1}}
        tx.put("invocation_reservations", reservation["id"], reservation)
        artifact = {"answer": answer, "thread_id": "thread-fixed" if self.shared_thread else "thread-" + record["id"],
                    "invocation": {"reservation": reservation["id"], "outcome": "accepted"},
                    "execution_assignment": {"provider": "codex" if bucket == "decisions_pending" or stage is not None
                                             else "claude"}}
        if stage is not None or self.project_skills:
            artifact["research_binding"] = {"stage": stage, "evidence_ref": evidence_ref, "basis_revision": basis}
            if self.project_skills:
                artifact["research_binding"]["project_skills_ref"] = SKILLS_REF
        ref = self.artifacts.put(self.api.canonical(artifact))
        if self.evidence == "corrupt":
            self.artifacts.corrupt(ref)
        return ref

    def execute_one(self, agent, expected=None):
        self.calls.append(agent)
        if agent in self.intercept:
            return self.intercept[agent](lambda: self._execute(agent, expected))
        return self._execute(agent, expected)

    def _execute(self, agent, expected):
        api = self.api
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
            details = task["message"]["what"]["details"]
            task.update(attempt=1, generation=1, lease_owner="fixture")
            if task["message"]["what"]["action"] == "dge_role":
                role = details["role"]
                task["status"] = self.role_status
                ref = self._persist(tx, task, "tasks", self.outputs[role], "dge:" + role, evidence_ref_of(api, details))
                task["result"] = {**self.outputs[role], "execution_ref": ref, "basis_revision": BASE}
                if self.wrong_agent:
                    task["agent"] = "lead:improvement"
            else:
                candidate = {"revision": CANDIDATE, "base": BASE, "tree": "t" * 40, "diff_hash": "d" * 64, "path": CANARY}
                inspection_id = "insp-" + task["id"]
                tx.put("evidence_inspections", inspection_id, {
                    "id": inspection_id, "policy_hash": "ph", "verdict": "all_checked",
                    "binding": {"task_id": task["id"], "generation": 1, "attempt": 1, "source_revision": candidate["revision"]},
                    "denominator": {"claims": 1, "checked": 1, "missing": 0}})
                answer = {"summary": CANARY, "tests": ["python -m pytest -q"]}
                ref = self._persist(tx, task, "tasks", answer, None, evidence_ref_of(api, details), self.implementation_basis)
                if self.worker != "succeeded":
                    task.update(status=self.worker, error="provider failed: " + CANARY)
                    tx.put("tasks", task["id"], task)
                    return task
                task.update(status="succeeded", result={**answer, "candidate": candidate, "execution_ref": ref,
                                                        "basis_revision": BASE,
                                                        "evidence_inspection": {"inspection_id": inspection_id,
                                                                                "verdict": "all_checked"}})
                report = api.envelope("task.result", task["agent"], "lead:improvement", "implement",
                                      {"task_id": task["id"], "result": task["result"]}, task["message"]["correlation_id"])
                tx.put("outbox", report["message_id"], {"message": report, "sent": False})
            tx.put("tasks", task["id"], task)
            return task

    def decide_one(self, agent, expected=None):
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            row = tx.get("decisions_pending", expected["id"])
            row.update(attempt=1, generation=1, lease_owner="fixture")
            answer = {"accepted": self.verdict, "reason": CANARY}
            ref = self._persist(tx, row, "decisions_pending", answer, None,
                                evidence_ref_of(self.api, row["message"]["what"]["details"]), self.review_basis)
            stored = {**answer, "execution_ref": ref, "basis_revision": self.review_basis}
            if self.evidence == "verdict":
                stored["accepted"] = True   # the row claims acceptance the artifact never gave (fixture)
            row.update(status="succeeded", result=stored)
            tx.put("decisions_pending", row["id"], row)
        if self.clock is not None and self.clock.after_review:
            self.clock.now = self.clock.after_review   # the review returns after the deadline passed (fixture)
        return row


class RouteBus(O.Bus):
    """LABELLED. The `RedisBus.for_run` shape the module reads (`namespace`, `route`) over the labelled in-memory bus; the
    real RedisBus is the S10 transport and never runs here."""

    def __init__(self, namespace=None, route=None):
        super().__init__()
        if namespace is not None:
            self.namespace = namespace
        if route is not None:
            self.route = route


class FailingBus(O.Bus):
    """LABELLED. A bus whose `publish` raises `MessageDeliveryError` from the `fail_from`-th publication on (1-based): the
    relay reports a retry, `flush_outbox(...)["complete"]` is False."""

    def __init__(self, api, fail_from=1):
        super().__init__()
        self.api, self.fail_from, self.attempts = api, fail_from, 0

    def publish(self, message):
        self.attempts += 1
        if self.attempts >= self.fail_from:
            raise self.api.MessageDeliveryError("transport unavailable (fixture)")
        return super().publish(message)


class SilentBus(O.Bus):
    """LABELLED. Publishes but delivers nothing: `receive` always answers None (delivery is not admission)."""

    def receive(self, agent, consumer):
        return None


class ScriptedBus(O.Bus):
    """LABELLED. `receive` answers the scripted (entry id, message-or-fields) rows in order, then None; `ack` and `dead_letter`
    are recorded; `fail_publish` makes every publication raise `MessageDeliveryError`."""

    def __init__(self, rows, api=None, fail_publish=False):
        super().__init__()
        self.rows, self.dead, self.api, self.fail_publish = list(rows), [], api, fail_publish

    def publish(self, message):
        if self.fail_publish:
            raise self.api.MessageDeliveryError("transport unavailable (fixture)")
        return super().publish(message)

    def receive(self, agent, consumer):
        return self.rows.pop(0) if self.rows else None

    def dead_letter(self, agent, entry_id, fields, reason):
        self.dead.append([entry_id, reason])
        super().dead_letter(agent, entry_id, fields, reason)


class StubWorkflow:
    """LABELLED. A workflow whose `handle` queues one command on the message's own correlation (what a handled report does) and
    returns a result object: the module's own publication proof after handling is observable without the real state machine."""

    def __init__(self, api, svc):
        self.api, self.svc, self.handled = api, svc, []

    def handle(self, message):
        self.handled.append(message["message_id"])
        command = self.api.envelope("task.assign", "conductor", "lead:researcher", "dge_role", {"role": "researcher"},
                                    message["correlation_id"])
        put(self.svc.store, "outbox", command["message_id"], {"message": command, "sent": False})
        return {"handled": message["message_id"]}


def system(api, clock=None, bus=None, budget=None, observer=None, verify_sources=None, with_workflow=True, workflow=None, **executor):
    """M7 `build(clock=None, **kwargs)`: a `Harness` over a `MemoryStore`, the labelled executor and the run."""
    svc = api.Harness(api.MemoryStore(), api.organization())
    artifacts, clock = Artifacts(api), clock or Clock()
    fake = Executor(api, svc, artifacts, clock=clock, **executor)
    budget = budget or O.FakeBudget()
    budget.error = api.ContractError
    collector = O.Collector()
    bus = bus if bus is not None else O.Bus()
    verify = verify_sources or (lambda packet: [{**s, "bytes": 1} for s in packet["sources"]])
    run = api.AutonomousRun(svc, fake, bus, workflow or (api.Workflow(svc.store, svc.org) if with_workflow else None), budget, collector,
                            verify_sources=verify, repository=REPO, observer=observer, clock=clock, evidence=artifacts)
    return SimpleNamespace(api=api, svc=svc, run=run, executor=fake, budget=budget, collector=collector, bus=bus, clock=clock,
                           artifacts=artifacts, observer=observer)


# ---- observations ------------------------------------------------------------------------------------------------------
def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def snap(store) -> dict:
    """The digests (and counts) of the watched buckets and of the whole store."""
    with store.transaction() as tx:
        rows = tx.records()
    out = {}
    for bucket in WATCHED:
        mine = sorted([r["id"], canonical_digest(r["body"])] for r in rows if r["bucket"] == bucket)
        out[bucket] = {"n": len(mine), "digest": canonical_digest(mine)}
    out["all"] = canonical_digest(sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows))
    return out


def attempt(fn, *args, **kwargs):
    """The characterized outcome of one call: a digest of its value, or the refusal (type, reason code, text)."""
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:   # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:200]}
    return {"value": canonical_digest(value)}


def refused(snapshot_store, fn, *args, **kwargs):
    """A call with the store digests before and after (a refusal leaves the watched buckets as they were, or says how not)."""
    before = snap(snapshot_store)
    result = attempt(fn, *args, **kwargs)
    after = snap(snapshot_store)
    return {**result, "before": before, "after": after, "changed": [k for k in before if before[k] != after[k]]}


def receipt_view(receipt) -> dict:
    """The decision facts of a receipt (never the whole text) and the digest of the whole receipt."""
    starts = receipt.get("starts") or {}
    return {"status": receipt.get("status"), "reason_code": receipt.get("reason_code"), "exit_code": receipt.get("exit_code"),
            "cached": receipt.get("cached"), "stage": receipt.get("stage"),
            "starts": {"reserved": starts.get("reserved"), "settled": starts.get("settled"),
                       "providers": [s.get("provider") for s in starts.get("slots", [])],
                       "agents": [s.get("agent") for s in starts.get("slots", [])],
                       "kinds": [s.get("kind") for s in starts.get("slots", [])]},
            "invocations": receipt.get("invocations"), "durations": sorted(receipt.get("durations") or {}),
            "roles": sorted(receipt.get("roles") or {}), "design": receipt.get("design"),
            "residuals": receipt.get("residuals"), "operation": receipt.get("operation"),
            "promotion": None if receipt.get("promotion") is None else {
                **{k: receipt["promotion"].get(k) for k in ("id", "repository", "graph_sha256", "cached", "edges")},
                "nodes": len(receipt["promotion"].get("nodes") or [])},
            "bus": receipt.get("bus"), "ssot_decision": receipt.get("ssot_decision"),
            "leaks_canary": CANARY in json.dumps(receipt, sort_keys=True, default=str),
            "digest": canonical_digest(receipt)}


def cycle(s, manifest=None, identity=None, goal=None):
    """`run` over the system, reported: the receipt view (or the refusal), the executor calls, the budget, the store digests."""
    manifest = manifest if manifest is not None else valid(s.api)
    try:
        receipt = s.run.run(manifest, identity or IDENTITY, goal or BOUND_GOAL)
        outcome = receipt_view(receipt)
    except Exception as exc:   # the refusal is the characterized result
        receipt = None
        outcome = {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:200]}
    row = get(s.svc.store, "autonomous_runs", manifest["id"])
    return {"outcome": outcome, "calls": list(s.executor.calls), "reserved": [[b["provider"], b["model"]] for b in s.budget.reserved],
            "settled": len(s.budget.settled), "row": None if row is None else {"status": row["status"], "stage": row["stage"],
                                                                            "reason_code": row["reason_code"]},
            "store": snap(s.svc.store)}, receipt


def case(api, **options):
    """A fresh system and one `run`; the second value is the system (to read further)."""
    s = system(api, **options)
    result, _ = cycle(s)
    return result, s


def tables(s) -> dict:
    """What a rejected run left in the store: knowledge, promotion and the operation row."""
    return {"knowledge_nodes": len(scan(s.svc.store, "knowledge_nodes")), "promotions": len(scan(s.svc.store, "promotions")),
            "dge_session": get(s.svc.store, "dge_sessions", RUN + ".design") is not None,
            "operation": get(s.svc.store, "operations", RUN + ".impl") is not None}


# ---- a1 --------------------------------------------------------------------------------------------------------------------
def a1_manifest(api, ws):
    out = {"valid": {"search_scope": valid(api)["research"]["search_scope"], "digest": canonical_digest(valid(api))}}
    for name, change in (("naive_deadline", {"deadline": "2030-01-01T00:00:00"}), ("research_without_questions", {"research": {"topic": "x"}}),
                         ("budget_with_bool", {"budget": {"per_host": True, "total": 2}}), ("extra_field", {"extra": 1}),
                         ("empty_questions", {"research": {"topic": "x", "questions": [], "search_scope": ["docs"]}}),
                         ("wrong_schema", {"schema": "urn:zeus:autonomous:2"})):
        try:
            valid(api, **change)
            result = {"valid": True}
        except Exception as exc:   # the refusal is the characterized result
            result = {"refused": type(exc).__name__, "message": str(exc)[:200], "leaks_canary": CANARY in str(exc)}
        out["refused_" + name] = result
    return out


# ---- a2 --------------------------------------------------------------------------------------------------------------------
def a2_cycle(api, ws):
    out = {}
    s = system(api)
    before = snap(s.svc.store)
    receipt = s.run.run(valid(api), IDENTITY, BOUND_GOAL)
    out["normal"] = {"receipt": receipt_view(receipt), "calls": list(s.executor.calls),
                     "reserved": [[b["provider"], b["model"], b["purpose"]] for b in s.budget.reserved],
                     "settled": len(s.budget.settled), "before": before, "after": snap(s.svc.store)}
    with s.svc.store.transaction() as tx:
        session = tx.get("dge_sessions", RUN + ".design")
        events = tx.scan("dge_events")
        promotion = tx.get("promotions", RUN)
        operation = tx.get("operations", RUN + ".impl")
        assignment = tx.get("tasks", operation["assignment_message_id"])
        run_row = tx.get("autonomous_runs", RUN)
        out["normal"]["store"] = {
            "session": {"origin": session["origin"], "owner": session["owner"], "state": session["state"],
                        "has_thread": bool(session["research_binding"]["evidence"]["thread_id"])},
            "events": {"origins": [e["origin"] for e in events], "all_bound": all(e["binding"] for e in events)},
            "knowledge": {"nodes": len(tx.scan("knowledge_nodes")), "edges": len(tx.scan("knowledge_edges"))},
            "promotion": {"graph_matches_receipt": promotion["graph_sha256"] == receipt["promotion"]["graph_sha256"],
                          "review_reservation": promotion["evidence"]["review_reservation_id"],
                          "keys": sorted(promotion["evidence"])},
            "operation": {"status": operation["status"], "deadline": operation["deadline"], "deadline_is_manifest": operation["deadline"] == valid(api)["deadline"],
                          "assignment_deadline": assignment["message"]["when"]["deadline"]},
            "run_row": {k: run_row[k] for k in ("status", "stage", "reason_code", "delivery" if "delivery" in run_row else "bus")}
            | {"history": [[h["from"], h["to"]] for h in run_row["history"]]}}
    arbiter = receipt["roles"]["arbiter"]
    out["normal"]["arbiter_binding"] = {"origin": arbiter["origin"], "has_answer": "answer" in arbiter,
                                       "reservation_prefix": arbiter["evidence"]["reservation_id"][:4], "keys": sorted(arbiter)}
    out["status_known"] = {"view": receipt_view(api.AutonomousRun(s.svc).status(RUN)), "keys": sorted(api.AutonomousRun(s.svc).status(RUN)),
                           "authority": api.AutonomousRun(s.svc).status(RUN)["authority"]}
    out["status_unknown"] = refused(s.svc.store, api.AutonomousRun(s.svc).status, "nope")
    try:   # M7: the operator `dge submit` cannot add events to an executor-bound session
        api.DebateSessions(s.svc.store).submit(RUN + ".design", {
            "schema": "urn:zeus:debate-event:1", "id": "op-1", "expected_version": 3, "packet_digest": receipt["packet_digest"],
            "round": 1, "role": "proposer", "payload": {}})
        out["operator_submit"] = {"refused": None}
    except api.DgeRefused as exc:
        out["operator_submit"] = {"refused": type(exc).__name__, "reason_code": exc.reason_code}
    before = snap(s.svc.store)
    replay_run = api.AutonomousRun(s.svc, Executor(api, s.svc, Artifacts(api)), O.Bus(), None, O.FakeBudget(), O.Collector())
    replay = replay_run.run(valid(api), IDENTITY, BOUND_GOAL)
    out["replay_cached"] = {"receipt": receipt_view(replay), "starts_equal": replay["starts"] == receipt["starts"],
                            "unchanged": snap(s.svc.store) == before, "executor_calls": list(replay_run.executor.calls)}
    out["configuration_mismatch"] = refused(s.svc.store, api.AutonomousRun(s.svc).run, valid(api), {**IDENTITY, "runtime": "other"},
                                            BOUND_GOAL)
    out["configuration_mismatch_goal"] = refused(s.svc.store, api.AutonomousRun(s.svc).run, valid(api), IDENTITY,
                                                 {**BOUND_GOAL, "bytes": 4})
    out["configuration_mismatch_manifest"] = refused(s.svc.store, api.AutonomousRun(s.svc).run, valid(api, deadline="2031-06-01T00:00:00+00:00"),
                                                     IDENTITY, BOUND_GOAL)
    # the observer's stage events (_log) and the delivery observations of _deliver
    o = system(api, observer=Observer())
    cycle_result, _ = cycle(o)
    out["observer"] = {"outcome": cycle_result["outcome"]["status"], "events": [[e[0], e[1], e[2]] for e in o.observer.events
                                                                               if e[0].startswith("operations.")],
                       "kinds": sorted({e[0] for e in o.observer.events})}
    # M7 test_the_run_row_records_its_delivery_namespace_and_a_bus_without_one_records_none
    n = system(api)
    n.bus.namespace = "ns:run:" + "0" * 32
    out["bus_namespace_recorded"] = {"bus": cycle(n)[0]["outcome"]["bus"]}
    out["bus_without_namespace"] = {"bus": cycle(system(api))[0]["outcome"]["bus"]}
    out["bus_view"] = {
        "none": api.bus_view(None), "plain": api.bus_view(O.Bus()), "named": api.bus_view(RouteBus(namespace="ns")),
        "empty_text": api.bus_view(SimpleNamespace(namespace="")), "not_text": api.bus_view(SimpleNamespace(namespace=3)),
        "url_never": api.bus_view(SimpleNamespace(namespace="ns:run:x", url="redis://host/0")) }
    out["provider_labels"] = {f"{kind}/{agent}": list(api.provider_labels("model-x")(kind, agent)) for kind, agent in (
        ("task", "worker:implementation"), ("task", "lead:researcher"), ("decision", "lead:improvement"),
        ("decision", "worker:implementation"), ("task", "lead:improvement"))}
    bound = {"origin": "executor_bound", "answer": {"x": 1}, "task_id": "t", "evidence": {"thread_id": "th"}}
    out["safe_binding"] = {"strips_answer": api.safe_binding(bound), "no_answer_key": api.safe_binding({"a": 1}),
                           "input_unchanged": "answer" in bound}
    with s.svc.store.transaction() as tx:
        out["row_digest"] = {"known": api.row_digest(tx, RUN) == receipt["packet_digest"], "unknown": api.row_digest(tx, "ghost"),
                             "row_without_digest": None}
    claimed = system(api)
    claimed.run.claim(valid(api), IDENTITY, BOUND_GOAL)
    with claimed.svc.store.transaction() as tx:
        out["row_digest"]["row_without_digest"] = api.row_digest(tx, RUN)
    out["receipt_keys"] = sorted(receipt)
    return out


# ---- a3 --------------------------------------------------------------------------------------------------------------------
def a3_rejected(api, ws):
    out = {}
    result, s = case(api, verdict=False)   # M7: the review rejects
    out["review_rejected"] = {**result, "tables": tables(s)}
    reject = {"verdict": "reject", "rationale": "no", "research_question": None,
              "dispositions": [{"finding_id": "f1", "decision": "resolved", "reason": "r"}]}
    result, s = case(api, outputs={"arbiter": reject})
    out["design_rejected"] = {**result, "tables": tables(s)}
    needs = {"verdict": "needs_research", "rationale": "unknown", "research_question": "which lock?",
             "dispositions": [{"finding_id": "f1", "decision": "blocking", "reason": "r"}]}
    result, s = case(api, outputs={"arbiter": needs})
    out["design_needs_research"] = {**result, "tables": tables(s)}
    revise = {"verdict": "revise", "rationale": "again", "research_question": None,
              "dispositions": [{"finding_id": "f1", "decision": "deferred", "reason": "r"}]}
    result, s = case(api, outputs={"arbiter": revise})
    out["design_exhausted_by_revise"] = {**result, "tables": tables(s)}
    result, s = case(api, worker="failed")
    out["operation_failed"] = {**result, "tables": tables(s)}
    out["outcome_by_reason"] = dict(sorted(api.OUTCOME_BY_REASON.items()))
    return out



# ---- seams (LABELLED: each edits a state no honest call path reaches, or wraps one step of the run) ----------------------
def edit(s, bucket, key, **fields):
    row = get(s.svc.store, bucket, key)
    row.update(fields)
    put(s.svc.store, bucket, key, row)


def after(s, agent, fn):
    """The labelled executor seam: the real fixture execution of `agent`, then `fn(s, row)` edits what it persisted."""
    def intercepted(call):
        row = call()
        fn(s, row)
        return row
    s.executor.intercept[agent] = intercepted


class Wrapped:
    """LABELLED. A stand-in for the `BudgetedExecutor` a direct call of `_role` / `_implement_and_promote` / `_finish` is given:
    `slots` is what the module reads; `execute_one` delegates to the labelled executor."""

    def __init__(self, s, slots=()):
        self.slots, self.s = list(slots), s

    def execute_one(self, agent, expected=None):
        return self.s.executor.execute_one(agent, expected=expected)


def slot(settled=True, agent="lead:researcher"):
    return {"id": "slot-x", "kind": "task", "agent": agent, "provider": "codex", "outcome": "accepted", "settled": settled,
            "settle_error": None, "operation": None, "extra": "dropped by _finish"}


def claimed(api, **options):
    """A system with the run claimed (the row at stage `research`) and its manifest."""
    s = system(api, **options)
    manifest = valid(api)
    claim = s.run.claim(manifest, IDENTITY, BOUND_GOAL)
    return s, manifest, claim["row"]


def tamper_cycle(api, tamper, **options):
    """A normal cycle whose `_promote` is wrapped (LABELLED seam): `tamper(s)` edits the stored rows right before the promotion
    transaction; the digests of the watched buckets are taken at that moment and again at the end."""
    s = system(api, **options)
    original, seen = s.run._promote, {}

    def seam(*args, **kwargs):
        tamper(s)
        seen["before"] = snap(s.svc.store)
        return original(*args, **kwargs)
    s.run._promote = seam
    result, _ = cycle(s)
    result["promotion_before"] = seen.get("before")
    result["promotion_buckets_unchanged"] = (seen.get("before") is not None and all(
        seen["before"][b] == result["store"][b] for b in PROMOTION_BUCKETS))
    result["tables"] = tables(s)
    return result


# ---- a4 --------------------------------------------------------------------------------------------------------------------
def a4_artifacts(api, ws):
    out = {}
    for name, evidence in (("none", "none"), ("corrupt", "corrupt"), ("unrelated", "unrelated")):   # the 253 parametrization
        result, s = case(api, evidence=evidence)
        out["evidence_" + name] = {**result, "tables": tables(s)}
    result, s = case(api, evidence="verdict", verdict=False)   # 263: the row says accepted, the artifact says rejected
    out["verdict_mismatch"] = {**result, "operation_status": result["outcome"]["operation"]["status"], "tables": tables(s)}
    result, s = case(api, shared_thread=True)
    out["shared_session"] = {**result, "tables": tables(s)}
    result, s = case(api, project_skills=True)   # 275: bound at the candidate and at the base
    review = s.executor.artifacts.document(get(s.svc.store, "decisions_pending", result["outcome"]["operation"]["decision_id"])["result"]["execution_ref"])
    out["skills_bound_to_candidate_and_base"] = {**result, "review_binding": review["research_binding"] | {"evidence_ref": "<digest>"},
                                                 "tables": tables(s)}
    result, s = case(api, project_skills=True, review_basis=BASE)
    out["skills_review_at_base_refused"] = {**result, "tables": tables(s)}
    result, s = case(api, project_skills=True, implementation_basis=CANDIDATE)
    out["skills_worker_at_candidate_refused"] = {**result, "tables": tables(s)}
    result, s = case(api, wrong_agent=True)   # 299: unbound output
    out["unbound_agent"] = {**result, "tables": tables(s)}
    critical = {"findings": [{**FINDING, "id": "f2", "severity": "critical"}]}
    result, s = case(api, outputs={"attacker": critical})
    out["unsupported_critical"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"researcher": {**RESEARCH, "needs_user": True, "user_question": "which doc?"}})
    out["needs_user"] = {**result, "tables": tables(s), "ssot_decision": result["outcome"]["ssot_decision"]}
    s = system(api)
    out["manifest_deadline_in_the_past"] = {**refused(s.svc.store, s.run.run, valid(api, deadline="2000-01-01T00:00:00+00:00"),
                                                        IDENTITY, BOUND_GOAL), "executor_calls": list(s.executor.calls),
                                            "reserved": len(s.budget.reserved)}
    # _freeze_packet: the researcher's output is refused, never repaired (`packet_invalid:<type>`)
    broken = {k: v for k, v in RESEARCH.items() if k != "ssot"}
    result, s = case(api, outputs={"researcher": broken})
    out["packet_invalid_missing_field"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"researcher": {**RESEARCH, "needs_user": True, "user_question": None}})
    out["packet_invalid_needs_user_without_question"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"researcher": {**RESEARCH, "claims": [{"id": "c1", "kind": "fact", "text": "x", "source_ids": ["nope"]}]}})
    out["packet_invalid_unknown_source"] = {**result, "tables": tables(s)}
    result, s = case(api, outputs={"researcher": {**RESEARCH, "ssot": {**RESEARCH["ssot"], "decision": "guess"}}})
    out["packet_invalid_ssot_decision"] = {**result, "tables": tables(s)}
    # verify_sources: a ContractError carries its own reason code or is named `source_verification_failed`
    class SourceRefused(api.ContractError):
        reason_code = "source_not_in_git"

    def refuse_with_code(packet):
        raise SourceRefused("source text must not surface")

    def refuse_plain(packet):
        raise api.ContractError("source text must not surface")

    def crash(packet):
        raise RuntimeError("verifier crashed (fixture)")
    for name, verify in (("source_reason_code", refuse_with_code), ("source_default_reason", refuse_plain),
                         ("source_verifier_crash", crash), ("source_bound_empty", lambda packet: [])):
        result, s = case(api, verify_sources=verify)
        out[name] = {**result, "tables": tables(s)}
    # _verify_execution: the evidence port's own failures (fixed codes only)
    for name, fault in (("port_contract_error", api.ContractError("port text must not surface")),
                        ("port_unavailable", api.EvidenceUnavailable("evidence_corrupt")),
                        ("port_os_error", OSError("port text must not surface"))):
        s = system(api)
        s.artifacts.raises = fault
        result, _ = cycle(s)
        out[name] = {**result, "tables": tables(s)}
    s = system(api)
    s.artifacts.override = {}
    out["port_artifact_without_answer"] = {**cycle(s)[0], "tables": tables(s)}

    def reservation_open(s, row):
        edit(s, "invocation_reservations", "res-" + row["id"], status="open")
    s = system(api)
    after(s, "lead:researcher", reservation_open)
    out["reservation_unsettled"] = {**cycle(s)[0], "tables": tables(s)}

    s = system(api)
    after(s, "lead:researcher", lambda s, row: edit(s, "invocation_reservations", "res-" + row["id"], task_id="someone-else"))
    out["reservation_of_another_record"] = {**cycle(s)[0], "tables": tables(s)}
    s = system(api)
    after(s, "lead:researcher", lambda s, row: edit(s, "tasks", row["id"], result={**get(s.svc.store, "tasks", row["id"])["result"], "extra": 1}))
    out["role_answer_is_not_the_artifact_answer"] = {**cycle(s)[0], "tables": tables(s)}
    s = system(api)
    after(s, "lead:researcher", lambda s, row: edit(s, "tasks", row["id"], result={**get(s.svc.store, "tasks", row["id"])["result"], "basis_revision": "9" * 40}))
    out["role_base_mismatch"] = {**cycle(s)[0], "tables": tables(s)}
    s = system(api)
    after(s, "lead:researcher", lambda s, row: edit(s, "tasks", row["id"], status="cancelled"))
    out["role_row_not_succeeded"] = {**cycle(s)[0], "tables": tables(s)}
    s = system(api)
    after(s, "lead:researcher", lambda s, row: edit(s, "tasks", row["id"], generation=None))
    out["role_row_without_generation"] = {**cycle(s)[0], "tables": tables(s)}
    result, s = case(api, role_status="failed")
    out["role_not_succeeded"] = {**result, "tables": tables(s)}
    return out


# ---- a5 --------------------------------------------------------------------------------------------------------------------
def a5_deadline(api, ws):
    out = {}
    clock = Clock()
    clock.after_review = LATE   # 317: the review returns after the deadline passed
    result, s = case(api, clock=clock)
    out["after_the_review"] = {**result, "operation_status": result["outcome"]["operation"]["status"], "tables": tables(s)}
    s = system(api)
    original = s.executor.execute_one

    def late_arbiter(agent, expected=None):
        row = original(agent, expected)
        if agent == "lead:arbiter":
            s.run.clock.now = LATE   # the clock passes the deadline between the design and the worker (fixture)
        return row
    s.executor.execute_one = late_arbiter
    out["before_the_worker"] = {**cycle(s)[0], "reserved_n": len(s.budget.reserved), "tables": tables(s)}
    out["child_operation_deadline"] = {"unreachable": "Operation.run over the operation fixtures (the coordination.operation family: its "
                                                      "`deadline_expired` case); here the module's own propagation is the cases above and below"}
    # The clock passes the deadline after its N-th read (the count of reads is part of the characterized behaviour: each read is
    # a `_check_deadline`, a transition, a claim or an Operation check, in that order).
    for name, reads in (("at_the_research_role", 1), ("between_two_roles", 5), ("before_the_implementation_check", 21),
                        ("inside_the_operation_before_the_worker", 23), ("inside_the_operation_before_the_review", 25),
                        ("after_the_review", 26), ("inside_the_promotion_transaction", 28), ("after_the_promotion", 30)):
        s = system(api)
        s.clock.flip = (reads, LATE)
        result, receipt = cycle(s)
        out["flip_" + name] = {"after_reads": reads, **result, "operation_status": (result["outcome"].get("operation") or {}).get("status"),
                               "reads_total": s.clock.reads, "tables": tables(s)}
    # _check_deadline: expired at, before and after the deadline, and in the offset form
    s = system(api)
    manifest = valid(api)
    checks = {}
    for name, now in (("before", "2029-12-31T23:59:59+00:00"), ("at", DEADLINE), ("after", LATE), ("offset_form_before", "2030-01-01T08:59:59+09:00"),
                      ("offset_form_at", "2030-01-01T09:00:00+09:00")):
        s.clock.now = now
        checks[name] = attempt(s.run._check_deadline, manifest)
    out["check_deadline"] = checks
    out["check_deadline_naive_clock"] = None
    s.clock.now = "2029-06-01T00:00:00"
    out["check_deadline_naive_clock"] = attempt(s.run._check_deadline, manifest)
    return out



def only(s, bucket):
    rows = scan(s.svc.store, bucket)
    return rows[0] if len(rows) == 1 else None


def row_view(row):
    return None if row is None else {"status": row["status"], "stage": row["stage"], "reason_code": row["reason_code"],
                                     "history": [[h["from"], h["to"]] for h in row["history"]], "durations": row["durations"],
                                     "packet_digest": row["packet_digest"], "ssot_decision": row["ssot_decision"]}


# ---- a6 --------------------------------------------------------------------------------------------------------------------
def a6_residue_budget(api, ws):
    out = {}
    s = system(api)
    s.run.claim(valid(api), IDENTITY, BOUND_GOAL)
    other = api.AutonomousRun(s.svc, Executor(api, s.svc, Artifacts(api)), O.Bus(), api.Workflow(s.svc.store, s.svc.org), O.FakeBudget(),
                              O.Collector())
    out["running_residue_without_takeover"] = {**refused(s.svc.store, other.run, valid(api), IDENTITY, BOUND_GOAL),
                                               "executor_calls": list(other.executor.calls)}
    for name, refuse_after in (("budget_refused_after_2", 2), ("budget_refused_after_5", 5), ("budget_refused_at_once", 0)):   # 343
        budget = O.FakeBudget(refuse_after=refuse_after)
        result, s = case(api, budget=budget)
        out[name] = {**result, "tables": tables(s)}
    for name, settle_fail in (("settlement_fails_for_the_first_role", 1), ("settlement_fails_for_the_worker", 5)):
        result, s = case(api, budget=O.FakeBudget(settle_fail=settle_fail))
        out[name] = {**result, "tables": tables(s)}
    s = system(api)
    s.executor.intercept["lead:researcher"] = lambda call: None
    out["no_execution_claimed"] = {**cycle(s)[0], "tables": tables(s)}

    def explode(call):
        raise RuntimeError("executor crashed (fixture)")
    s = system(api)
    s.executor.intercept["lead:attacker"] = explode
    out["executor_exception"] = {**cycle(s)[0], "tables": tables(s)}
    s = system(api, bus=FailingBus(api, fail_from=1))
    out["publication_incomplete_before_delivery"] = {**cycle(s)[0], "published": len(s.bus.published), "tables": tables(s)}
    s = system(api, bus=FailingBus(api, fail_from=2))

    def add_report(s, row):   # LABELLED: the role's own execution also queued a report on its correlation
        report = api.envelope("task.result", "worker:implementation", "lead:improvement", "implement",
                              {"task_id": row["id"], "result": {}}, row["message"]["correlation_id"])
        put(s.svc.store, "outbox", report["message_id"], {"message": report, "sent": False})
    after(s, "lead:researcher", add_report)
    out["publication_incomplete_after_execution"] = {**cycle(s)[0], "published": len(s.bus.published), "tables": tables(s)}
    # M7 role_residue: the role message already exists in the outbox, or as a task
    manifest = valid(api)
    for name, bucket in (("role_residue_outbox", "outbox"), ("role_residue_task", "tasks")):
        s = system(api)
        put(s.svc.store, bucket, api.role_message_id(manifest, "researcher"), {"message": {"stale": True}} if bucket == "outbox" else {"id": "stale"})
        out[name] = {**cycle(s)[0], "tables": tables(s)}
    s = system(api, bus=SilentBus())
    out["expected_execution_missing_by_delivery"] = {**cycle(s)[0], "tables": tables(s)}
    # _require_admitted (direct, LABELLED rows)
    s = system(api)
    expected = {"id": "m1", "correlation_id": "c1", "statuses": {"queued"}}
    admitted = {}
    admitted["missing"] = refused(s.svc.store, s.run._require_admitted, expected)
    put(s.svc.store, "tasks", "m1", "not a row")
    admitted["not_a_row"] = refused(s.svc.store, s.run._require_admitted, expected)
    put(s.svc.store, "tasks", "m1", {"id": "m1", "status": "queued", "message": "not a message"})
    admitted["message_not_a_dict"] = refused(s.svc.store, s.run._require_admitted, expected)
    put(s.svc.store, "tasks", "m1", {"id": "m1", "status": "queued", "message": {"correlation_id": "other"}})
    admitted["foreign_correlation"] = refused(s.svc.store, s.run._require_admitted, expected)
    put(s.svc.store, "tasks", "m1", {"id": "m1", "status": "running", "message": {"correlation_id": "c1"}})
    admitted["not_queued"] = refused(s.svc.store, s.run._require_admitted, expected)
    put(s.svc.store, "tasks", "m1", {"id": "m1", "status": "queued", "message": {"correlation_id": "c1"}})
    admitted["queued"] = refused(s.svc.store, s.run._require_admitted, expected)
    out["require_admitted"] = admitted
    # the start cap (LABELLED: a stub for `wrapped` holding as many slots as the case needs; v1 reaches neither through `run`)
    s, manifest, row = claimed(api)
    out["role_start_cap"] = {**refused(s.svc.store, s.run._role, manifest, row, Wrapped(s, [slot()] * 6), "researcher", {"role": "researcher"}),
                             "max_starts": row["max_starts"]}
    s, manifest, row = claimed(api)
    s.run._transition(RUN, "research", "arbiter")
    design = {"id": RUN + ".design", "state": "design_approved", "packet_digest": "p" * 64, "decision_event_id": "arb", "version": 3}
    calls = []
    out["implement_start_cap"] = {**refused(s.svc.store, s.run._implement_and_promote, manifest, IDENTITY, BOUND_GOAL, row,
                                            Wrapped(s, [slot()] * 5), {}, {}, design, "arbiter"),
                                  "row": row_view(get(s.svc.store, "autonomous_runs", RUN))}
    out["implement_before_implementation_hook"] = {**refused(s.svc.store, s.run._implement_and_promote, manifest, IDENTITY, BOUND_GOAL, row,
                                                           Wrapped(s, [slot()] * 4), {}, {}, design, "arbiter",
                                                           before_implementation=lambda: (calls.append("hook"), (_ for _ in ()).throw(
                                                               api.AutonomousRefused("snapshot_changed")))[1]),
                                                 "hook_calls": list(calls), "row": row_view(get(s.svc.store, "autonomous_runs", RUN))}
    out["implement_design_not_approved"] = {**refused(s.svc.store, s.run._implement_and_promote, manifest, IDENTITY, BOUND_GOAL, row,
                                                      Wrapped(s, []), {}, {}, {**design, "state": "weird"}, "arbiter"),
                                            "row_design": get(s.svc.store, "autonomous_runs", RUN)["design"]}
    # _transition (direct)
    s, manifest, row = claimed(api)
    transitions = {}
    transitions["wrong_stage"] = refused(s.svc.store, s.run._transition, RUN, "packet", "proposer")
    transitions["unknown_run"] = refused(s.svc.store, s.run._transition, "ghost", "research", "packet")
    first = s.run._transition(RUN, "research", "packet", merge={"durations": {"a": 1.0}}, packet_digest="d1")
    second = s.run._transition(RUN, "packet", None, merge={"durations": {"b": 2.0}, "roles": {"x": {"y": 1}}})
    third = s.run._transition(RUN, "packet", "packet", merge={"invocations": {"k": 1}})
    transitions["merge_keeps_prior_keys"] = {"first": row_view(first), "second_durations": second["durations"], "second_roles": second["roles"],
                                             "stage_kept": second["stage"], "same_stage_adds_no_history": len(third["history"]) == len(second["history"]),
                                             "third_invocations": third["invocations"]}
    edit(s, "autonomous_runs", RUN, status="failed")
    transitions["terminal_row"] = refused(s.svc.store, s.run._transition, RUN, "packet", "proposer")
    out["transition"] = transitions
    # run without its ports: the claim is committed, then the requirement refuses and leaves a running row
    s = system(api)
    bare = api.AutonomousRun(s.svc)
    out["run_without_ports"] = {**refused(s.svc.store, bare.run, valid(api), IDENTITY, BOUND_GOAL),
                                "row": row_view(get(s.svc.store, "autonomous_runs", RUN))}
    out["run_without_evidence_port"] = {**refused(s.svc.store, api.AutonomousRun(s.svc, s.executor, s.bus, api.Workflow(s.svc.store, s.svc.org),
                                                                                 s.budget, s.collector).run, valid(api, id="auto-002"), IDENTITY, BOUND_GOAL),
                                        "row": row_view(get(s.svc.store, "autonomous_runs", "auto-002"))}
    # _finish (direct)
    finish = {}
    s, manifest, row = claimed(api)
    finish["unsettled_accepted_is_failed"] = {"receipt": receipt_view(s.run._finish(row, Wrapped(s, [slot(), slot(False)]),
                                                                                    {"status": "accepted", "reason_code": "promoted"})),
                                              "row": row_view(get(s.svc.store, "autonomous_runs", RUN))}
    s, manifest, row = claimed(api)
    receipt = s.run._finish(row, Wrapped(s, [slot(), slot()]), {"status": "accepted", "reason_code": "promoted"})
    finish["accepted_without_promotion_is_unknown"] = {"receipt": receipt_view(receipt), "starts": receipt["starts"],
                                                       "row": row_view(get(s.svc.store, "autonomous_runs", RUN))}
    s, manifest, row = claimed(api)
    edit(s, "autonomous_runs", RUN, promotion={"id": RUN})
    finish["accepted_with_promotion"] = receipt_view(s.run._finish(row, Wrapped(s, [slot()]), {"status": "accepted", "reason_code": "promoted"}))
    s, manifest, row = claimed(api)
    finish["rejected_passes_through"] = receipt_view(s.run._finish(row, Wrapped(s, [slot(), slot(False)]),
                                                                   {"status": "rejected", "reason_code": "review_rejected"}))
    s, manifest, row = claimed(api)
    edit(s, "autonomous_runs", RUN, status="failed")
    finish["row_not_running"] = refused(s.svc.store, s.run._finish, row, Wrapped(s, []), {"status": "failed", "reason_code": "x"})
    s, manifest, row = claimed(api)
    finish["row_missing"] = refused(s.svc.store, s.run._finish, {**row, "id": "ghost"}, Wrapped(s, []), {"status": "failed", "reason_code": "x"})
    out["finish"] = finish
    # _residuals: the findings of a session (a critical one blocks)
    critical = {"findings": [FINDING, {**FINDING, "id": "f2", "severity": "critical", "trigger": "t", "impact": "i", "mitigation": "m"}]}
    arbiter = {"verdict": "needs_research", "rationale": "unknown", "research_question": "which lock?",
               "dispositions": [{"finding_id": "f1", "decision": "deferred", "reason": "r"},
                                {"finding_id": "f2", "decision": "blocking", "reason": "r"}]}
    result, s = case(api, outputs={"attacker": critical, "arbiter": arbiter})
    out["residuals_with_a_blocking_critical"] = {**result, "residuals": result["outcome"]["residuals"]}
    out["residuals_unknown_session"] = attempt(s.run._residuals, "ghost")
    out["residuals_unknown_session_value"] = s.run._residuals("ghost")
    return out


# ---- a7 --------------------------------------------------------------------------------------------------------------------
NS = "ns:run:" + "1" * 32


def route_bus(run_id=RUN, namespace=NS, **overrides):
    return RouteBus(namespace=namespace, route={"scope": "run", "run_id": run_id, "namespace": namespace, **overrides})


def claim_view(claim):
    row = claim["row"]
    return {"cached": claim["cached"], "status": row["status"], "stage": row["stage"], "max_starts": row["max_starts"],
            "topology": row["topology"], "bus": row["bus"], "correlation_id": row["correlation_id"], "session_id": row["session_id"],
            "operation_id": row["operation_id"], "deadline": row["deadline"], "starts": row["starts"], "history": row["history"],
            "digest": canonical_digest(row)}


def a7_claim(api, ws):
    out = {}
    manifest = valid(api)
    s = system(api)
    before = snap(s.svc.store)
    out["fresh"] = {"claim": claim_view(s.run.claim(manifest, IDENTITY, BOUND_GOAL)), "before": before, "after": snap(s.svc.store)}
    out["running_residue"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    out["configuration_mismatch_identity"] = refused(s.svc.store, s.run.claim, manifest, {**IDENTITY, "runtime": "other"}, BOUND_GOAL)
    out["configuration_mismatch_goal"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, {**BOUND_GOAL, "bytes": 4})
    out["configuration_mismatch_manifest"] = refused(s.svc.store, s.run.claim, valid(api, budget={"per_host": 4, "total": 8}), IDENTITY, BOUND_GOAL)
    out["configuration_mismatch_before_running_residue"] = out["configuration_mismatch_identity"]["reason_code"]
    edit(s, "autonomous_runs", RUN, status="accepted")
    out["terminal_is_cached"] = {**refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)}
    cached = s.run.claim(manifest, IDENTITY, BOUND_GOAL)
    out["terminal_is_cached"]["claim"] = {"cached": cached["cached"], "status": cached["row"]["status"]}
    for status in ("rejected", "failed", "unknown", "exhausted", "needs_user", "needs_research", "expired"):
        edit(s, "autonomous_runs", RUN, status=status)
        out["terminal_cached_" + status] = s.run.claim(manifest, IDENTITY, BOUND_GOAL)["cached"]
    edit(s, "autonomous_runs", RUN, status="weird")
    out["unknown_status_is_running_residue"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    # residue of a half-written run: the design session or the operation row exists without a run row
    for name, bucket, key in (("residue_session", "dge_sessions", RUN + ".design"), ("residue_operation", "operations", RUN + ".impl")):
        s = system(api)
        put(s.svc.store, bucket, key, {"id": key, "status": "stale"})
        out[name] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    s = system(api)
    s.clock.now = LATE
    out["deadline_expired"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    s = system(api)
    s.clock.now = DEADLINE
    out["deadline_expired_at_the_deadline"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    s = system(api)
    put(s.svc.store, "dge_sessions", RUN + ".design", {"id": "stale"})
    s.clock.now = LATE
    out["residue_before_deadline"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    # the route (SPEC "Council isolation resubmission"), through a direct bus double
    s = system(api, bus=route_bus())
    before = snap(s.svc.store)
    claim = s.run.claim(manifest, IDENTITY, BOUND_GOAL)
    pins = {c: get(s.svc.store, "outbox_routes", c) for c in ("autonomous:" + RUN, "operation:" + RUN + ".impl")}
    out["route_pinned"] = {"claim": claim_view(claim), "pins": {c: p and {k: v for k, v in p.items() if k != "pinned_at"} for c, p in pins.items()},
                           "pinned_at_is_the_claim_time": [p["pinned_at"] for p in pins.values()] == [claim["row"]["claimed_at"]] * 2,
                           "outbox_rows": len(scan(s.svc.store, "outbox")), "before": before, "after": snap(s.svc.store)}
    out["route_pinned_then_residue"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    s2 = system(api, bus=route_bus("auto-999"))
    out["route_mismatch"] = {**refused(s2.svc.store, s2.run.claim, manifest, IDENTITY, BOUND_GOAL), "outbox_routes": len(scan(s2.svc.store, "outbox_routes"))}
    s.run.bus = route_bus("auto-999")
    out["route_mismatch_before_the_row_checks"] = refused(s.svc.store, s.run.claim, manifest, IDENTITY, BOUND_GOAL)
    s3 = system(api, bus=route_bus())
    pin = {"id": "autonomous:" + RUN, "schema": "urn:zeus:outbox-route:1", "scope": "run", "run_id": RUN, "namespace": NS, "pinned_at": "earlier"}
    put(s3.svc.store, "outbox_routes", "autonomous:" + RUN, pin)
    claim = s3.run.claim(manifest, IDENTITY, BOUND_GOAL)
    out["route_same_pin_is_idempotent"] = {"claim": claim_view(claim), "pin_kept": get(s3.svc.store, "outbox_routes", "autonomous:" + RUN) == pin,
                                           "operation_pin": get(s3.svc.store, "outbox_routes", "operation:" + RUN + ".impl") is not None}
    s4 = system(api, bus=route_bus())
    put(s4.svc.store, "outbox_routes", "autonomous:" + RUN, {**pin, "namespace": "ns:run:" + "f" * 32})
    out["route_conflict"] = {**refused(s4.svc.store, s4.run.claim, manifest, IDENTITY, BOUND_GOAL),
                             "pin_kept": get(s4.svc.store, "outbox_routes", "autonomous:" + RUN)["namespace"],
                             "run_row": get(s4.svc.store, "autonomous_runs", RUN)}
    s5 = system(api, bus=route_bus())
    put(s5.svc.store, "outbox_routes", "operation:" + RUN + ".impl", {**pin, "id": "operation:" + RUN + ".impl", "run_id": "auto-999"})
    out["route_conflict_on_the_operation_correlation"] = {**refused(s5.svc.store, s5.run.claim, manifest, IDENTITY, BOUND_GOAL),
                                                          "role_pin_rolled_back": get(s5.svc.store, "outbox_routes", "autonomous:" + RUN)}
    # a route that is not a trusted run route of this bus is no route: the legacy path records the namespace only
    for name, bus in (("route_namespace_differs_from_the_bus", RouteBus(namespace=NS, route={"scope": "run", "run_id": RUN, "namespace": "other"})),
                      ("route_scope_not_run", RouteBus(namespace=NS, route={"scope": "global", "run_id": RUN, "namespace": NS})),
                      ("route_missing_field", RouteBus(namespace=NS, route={"scope": "run", "namespace": NS})),
                      ("route_empty_text", RouteBus(namespace=NS, route={"scope": "run", "run_id": "", "namespace": NS})),
                      ("route_not_a_dict", RouteBus(namespace=NS, route="run")),
                      ("namespace_only", RouteBus(namespace=NS)), ("route_without_namespace", RouteBus(route={"scope": "run", "run_id": RUN, "namespace": NS}))):
        s = system(api, bus=bus)
        claim = s.run.claim(manifest, IDENTITY, BOUND_GOAL)
        out[name] = {"bus": claim["row"]["bus"], "pins": len(scan(s.svc.store, "outbox_routes"))}
    out["route_invalid"] = {"unreachable": "`pin_route` raises `route_invalid` only for a route `_run_route` rejects, and `claim` pins only "
                                           "what `bus_route` returned (a validated run route); the mapping `AutonomousRefused(str(exc))` is "
                                           "observed through `route_conflict` above"}
    # a whole run on a run-scoped bus: the pinned route is the bus's route, every message is published once on it
    s = system(api, bus=route_bus())
    result, receipt = cycle(s)
    attempts = scan(s.svc.store, "outbox_attempts")
    out["routed_cycle"] = {**result, "delivered": sum(1 for a in attempts if a["status"] == "delivered"), "attempts": len(attempts),
                           "route_pins": sorted(r["id"] for r in scan(s.svc.store, "outbox_routes")), "outbox_all_sent": all(r["sent"] for r in scan(s.svc.store, "outbox")),
                           "published": len(s.bus.published)}
    restart = api.AutonomousRun(s.svc, s.executor, route_bus(), api.Workflow(s.svc.store, s.svc.org), s.budget, s.collector,
                                verify_sources=s.run.verify_sources, repository=REPO, clock=s.clock, evidence=s.artifacts)
    before = snap(s.svc.store)
    out["routed_restart_is_cached"] = {"cached": restart.run(manifest, IDENTITY, BOUND_GOAL)["cached"], "unchanged": snap(s.svc.store) == before}
    return out


# ---- a8 --------------------------------------------------------------------------------------------------------------------
def standalone_refs():
    """M7 `test_promotion_is_idempotent_...`: the references of a graph, LABELLED (nothing here is a verified execution)."""
    return {"base_revision": BASE, "goal": {"path": "g.md", "sha256": SOURCE_SHA}, "packet_digest": "p" * 64,
            "research_execution_ref": "sha256:" + "e" * 64, "research_task_id": "t1", "session_id": "s", "decision_event_id": "arb",
            "role_bindings": {}, "candidate": {"revision": "c" * 40, "base": BASE, "tree": "t" * 40, "diff_hash": "d" * 64},
            "implementation_task_id": "t2", "implementation_execution_ref": "sha256:" + "e" * 64, "decision_id": "d1",
            "review_execution_ref": "sha256:" + "f" * 64, "inspection_id": "i1", "operation_id": "op", "verification_scope": {}}


def promotion_standalone(api):
    out = {}
    store = api.MemoryStore()
    refs = standalone_refs()
    graph = api.verified_graph("run-1", refs)
    out["graph"] = {"repository": graph["repository"], "nodes": [n["id"] for n in graph["nodes"]], "edges": graph["edges"],
                    "digest": canonical_digest(graph)}
    with store.transaction() as tx:
        first = api.promote(tx, "run-1", graph, {"decision_id": "d1"})
        again = api.promote(tx, "run-1", graph, {"decision_id": "d1"})
        conflict = attempt(api.promote, tx, "run-1", api.verified_graph("run-1", {**refs, "inspection_id": "i2"}), {})
        namespace = attempt(api.promote, tx, "run-2", graph, {})
    out["first"] = {"cached": first["cached"], "repository": first["repository"], "keys": sorted(first), "digest": canonical_digest(first)}
    out["replay"] = {"cached": again["cached"], "same_graph": again["graph_sha256"] == first["graph_sha256"], "digest": canonical_digest(again)}
    out["conflict"] = conflict
    out["namespace_mismatch"] = namespace
    out["store_after_replays"] = {"nodes": len(scan(store, "knowledge_nodes")), "edges": len(scan(store, "knowledge_edges")),
                                  "promotions": len(scan(store, "promotions")), "digest": snap(store)["all"]}
    before = snap(store)
    try:
        with store.transaction() as tx:
            api.promote(tx, "run-3", api.verified_graph("run-3", refs), {})
            raise RuntimeError("commit failure (fixture)")
    except RuntimeError as exc:
        out["rollback_receipt"] = {"raised": type(exc).__name__, "message": str(exc)}
    out["rollback"] = {"promotion": get(store, "promotions", "run-3"), "nodes": len(scan(store, "knowledge_nodes")),
                       "unchanged": snap(store) == before}
    return out


def a8_promotion(api, ws):
    out = {"standalone": promotion_standalone(api)}
    s = system(api)
    before = snap(s.svc.store)
    receipt = s.run.run(valid(api), IDENTITY, BOUND_GOAL)
    out["promoted_once"] = {"receipt": receipt_view(receipt), "before": before, "after": snap(s.svc.store),
                            "promotion_record_keys": sorted(get(s.svc.store, "promotions", RUN))}
    manifest = valid(api)
    prior = {role: {"binding": receipt["roles"][role]} for role in ("proposer", "attacker", "arbiter")}
    args = (manifest, BOUND_GOAL, get(s.svc.store, "autonomous_runs", RUN), receipt["operation"], receipt["roles"]["researcher"], prior)
    out["replay_after_the_run_finished"] = refused(s.svc.store, s.run._promote, *args)   # the row is no longer at `promotion`
    edit(s, "autonomous_runs", RUN, status="running", stage="promotion")
    replay = refused(s.svc.store, s.run._promote, *args)   # LABELLED row edit: the idempotent replay of the promotion itself
    out["replay_idempotent_promotion"] = {**replay, "row_promotion": get(s.svc.store, "autonomous_runs", RUN)["promotion"]}
    # a council seam (INV-COUNCIL-001; the council run is a later pilot): the recheck runs in the same transaction and may add refs
    s = system(api)
    original, seen = s.run._promote, []

    def seam(*a):
        def council(tx):
            seen.append(tx.get("autonomous_runs", RUN)["stage"])
            return {"refs": {"dba": "d" * 8}, "evidence": {"council_note": "n"}}
        return original(*a[:6], council)
    s.run._promote = seam
    result, _ = cycle(s)
    promotion = get(s.svc.store, "promotions", RUN)
    out["council_seam_adds_refs"] = {**result, "council_saw_stage": seen, "evidence_keys": sorted(promotion["evidence"]),
                                     "design_node_has_council": "council" in get(s.svc.store, "knowledge_nodes", "verified:" + RUN + ":design")["body"]}
    s = system(api)
    original = s.run._promote

    def refusing(*a):
        def council(tx):
            raise api.AutonomousRefused("council_changed")
        return original(*a[:6], council)
    s.run._promote = refusing
    out["council_seam_refuses"] = {**cycle(s)[0], "tables": tables(s)}

    def op(**f):
        return lambda s: edit(s, "operations", RUN + ".impl", **f)

    def task(**f):
        return lambda s: edit(s, "tasks", only_task(s), **f)

    def only_task(s):
        return get(s.svc.store, "operations", RUN + ".impl")["assignment_message_id"]

    def decision(**f):
        return lambda s: edit(s, "decisions_pending", only(s, "decisions_pending")["id"], **f)

    def task_result(drop=(), **f):
        def apply(s):
            row = get(s.svc.store, "tasks", only_task(s))
            row["result"] = {**{k: v for k, v in row["result"].items() if k not in drop}, **f}
            put(s.svc.store, "tasks", row["id"], row)
        return apply

    def decision_edit(fn):
        def apply(s):
            row = only(s, "decisions_pending")
            fn(row)
            put(s.svc.store, "decisions_pending", row["id"], row)
        return apply

    def inspection(**f):
        return lambda s: edit(s, "evidence_inspections", only(s, "evidence_inspections")["id"], **f)

    def reservation(of, **f):
        def apply(s):
            key = only_task(s) if of == "task" else only(s, "decisions_pending")["id"]
            edit(s, "invocation_reservations", "res-" + key, **f)
        return apply

    def artifact_of(s, of):
        row = get(s.svc.store, "tasks", only_task(s)) if of == "task" else only(s, "decisions_pending")
        return row["result"]["execution_ref"]

    tampers = {
        "operation_lead_not_accepted": op(lead_accepted=False), "operation_not_accepted": op(status="failed"),
        "task_not_succeeded": task(status="failed"), "task_other_agent": task(agent="lead:improvement"),
        "task_without_candidate": task_result(drop=("candidate",)), "task_without_inspection_ref": task_result(drop=("evidence_inspection",)),
        "task_result_not_a_dict": task(result="text"),
        "review_not_succeeded": decision(status="failed"), "review_other_phase": decision(phase="design_lead"),
        "review_verdict_rejected": decision_edit(lambda r: r["result"].update(accepted=False)),
        "review_without_candidate": decision_edit(lambda r: r["input"].pop("candidate", None)),
        "review_of_another_revision": decision_edit(lambda r: r["input"].__setitem__("candidate", {"revision": "9" * 40})),
        "inspection_incomplete": inspection(verdict="incomplete"),
        "inspection_of_another_attempt": inspection(binding={"task_id": "x", "generation": 1, "attempt": 1, "source_revision": CANDIDATE}),
        "inspection_ghost": task_result(evidence_inspection={"inspection_id": "ghost", "verdict": "all_checked"}),
        "evidence_worker_reservation_unsettled": reservation("task", status="open"),
        "evidence_review_reservation_of_another_record": reservation("decision", task_id="someone-else"),
        "evidence_worker_answer_changed": task_result(summary="another answer"),
        "design_not_approved": lambda s: edit(s, "dge_sessions", RUN + ".design", state="rejected"),
        "design_other_owner": lambda s: edit(s, "dge_sessions", RUN + ".design", owner="someone-else"),
        "design_other_origin": lambda s: edit(s, "dge_sessions", RUN + ".design", origin="operator"),
        "design_other_packet": lambda s: edit(s, "autonomous_runs", RUN, packet_digest="0" * 64),
        "run_row_changed_stage": lambda s: edit(s, "autonomous_runs", RUN, stage="implementation"),
        "run_row_changed_status": lambda s: edit(s, "autonomous_runs", RUN, status="failed"),
    }
    results = {name: tamper_cycle(api, fn) for name, fn in tampers.items()}
    out["refusals"] = results
    # the artifact faults of the evidence port at promotion time
    port = {}
    for name, how in (("worker_artifact_corrupt", lambda s: s.artifacts.corrupt(artifact_of(s, "task"))),
                      ("review_artifact_corrupt", lambda s: s.artifacts.corrupt(artifact_of(s, "decision"))),
                      ("port_without_answer", lambda s: setattr(s.artifacts, "override", {})),
                      ("port_contract_error", lambda s: setattr(s.artifacts, "raises", api.ContractError("port text must not surface"))),
                      ("port_os_error", lambda s: setattr(s.artifacts, "raises", OSError("port text must not surface")))):
        port[name] = tamper_cycle(api, how)
    out["evidence_port_at_promotion"] = port
    out["evidence_answer_mismatch"] = {**cycle(system(api, evidence="verdict", verdict=False))[0]}   # 263 at the promotion
    return out


# ---- a9 --------------------------------------------------------------------------------------------------------------------
CORRELATION = "autonomous:" + RUN
AGENT = "lead:researcher"


def delivered(api, rows, observer=None, agent=AGENT, stub_workflow=False, fail_publish=False):
    """`_deliver` over a scripted bus (LABELLED): the handled messages or the refusal, the bus's acks, dead letters and
    publications, the observer's events, the buckets that changed."""
    bus = ScriptedBus(rows, api, fail_publish)
    s = system(api, bus=bus, observer=observer)
    if stub_workflow:
        s.run.workflow = StubWorkflow(api, s.svc)
    before = snap(s.svc.store)
    result = attempt(lambda: [m["message_id"] for m in s.run._deliver(agent, CORRELATION)])
    after = snap(s.svc.store)
    return {**result, "acked": list(bus.acked), "dead_letters": list(bus.dead), "published": len(bus.published), "rows_left": len(bus.rows),
            "handled": len(getattr(s.run.workflow, "handled", [])) if stub_workflow else None,
            "events": None if observer is None else [[e[0], e[1], e[2]] for e in observer.events],
            "changed": [k for k, v in before.items() if v != after[k]],
            "outbox_sent": [r["sent"] for r in scan(s.svc.store, "outbox")]}


def a9_delivery(api, ws):
    out = {}
    foreign = api.envelope("task.assign", "conductor", AGENT, "dge_role", {"role": "researcher"}, "autonomous:other-run")
    out["empty_bus"] = delivered(api, [])
    out["foreign_message"] = delivered(api, [("1-0", {"body": foreign})], Observer())
    wrong_recipient = api.envelope("task.assign", "conductor", "lead:attacker", "dge_role", {"role": "attacker"}, CORRELATION)
    out["wrong_recipient_is_dead_lettered"] = delivered(api, [("1-0", {"body": wrong_recipient})], Observer())
    unauthorized = api.envelope("task.assign", "lead:researcher", AGENT, "dge_role", {"role": "researcher"}, CORRELATION)
    out["unauthorized_route_is_dead_lettered"] = delivered(api, [("1-0", {"body": unauthorized})], Observer())
    out["undecodable_is_dead_lettered"] = delivered(api, [("1-0", {"nobody": 1})], Observer())
    out["dead_letter_then_foreign"] = delivered(api, [("1-0", {"body": wrong_recipient}), ("2-0", {"body": foreign})], Observer())
    out["drain_is_bounded"] = delivered(api, [(str(i) + "-0", {"nobody": i}) for i in range(20)])
    out["notice_off_the_reporting_edge_is_dead_lettered"] = delivered(
        api, [("1-0", {"body": api.envelope("execution.notice", "conductor", AGENT, "observe_execution", {"notice": "stale"}, "autonomous:other-run")})],
        Observer())
    notice = api.envelope("execution.notice", "worker:implementation", "lead:improvement", "observe_execution", {"notice": "stale"},
                          "autonomous:other-run")
    out["foreign_notice_unproven_is_a_foreign_message"] = delivered(api, [("1-0", {"body": notice})], Observer(), agent="lead:improvement")
    # the handled message of this run: the workflow's commands are published before the ACK; an unfinished publication stops the run
    mine = api.envelope("task.assign", "conductor", AGENT, "dge_role", {"role": "researcher"}, CORRELATION)
    out["handled_then_published_then_acked"] = delivered(api, [("1-0", {"body": mine})], Observer(), stub_workflow=True)
    out["handled_but_unpublished_is_not_acked"] = delivered(api, [("1-0", {"body": mine})], Observer(), stub_workflow=True, fail_publish=True)
    out["foreign_notice_proven"] = {"unreachable": "the proof is the stored transition of the shared execution store "
                                                   "(`execution_notices.receive_foreign`, the execution_notices family); "
                                                   "only its refusal is reachable with a labelled store"}
    # publication after the handled message: the run's own commands must be published before the ACK
    s = system(api, bus=FailingBus(api, fail_from=2))
    out["publication_incomplete_after_handling"] = {**cycle(s)[0], "published": len(s.bus.published), "acked": list(s.bus.acked),
                                                    "tables": tables(s)}
    s = system(api, bus=FailingBus(api, fail_from=3))
    out["publication_incomplete_later"] = {**cycle(s)[0], "published": len(s.bus.published), "acked": list(s.bus.acked),
                                           "tables": tables(s)}
    s = system(api)
    out["acked_in_a_normal_cycle"] = {**cycle(s)[0]["outcome"], "acked": len(s.bus.acked), "published": len(s.bus.published)}
    out["m7_the_cli_owner_wires_one_run_scoped_bus_per_run_and_records_it_on_the_receipt"] = {
        "unreachable": "S10 CLI: the real `autonomous_cli.run` wiring over the real RedisBus constructor; the module side (the namespace on "
                       "the run row, `bus_view`) is a2_cycle"}
    out["m7_a_global_relay_interleaved_after_the_commit_never_publishes_or_marks_a_scoped_message"] = {
        "unreachable": "S10 CLI/server: the real RedisBus and the global supervisor relay; the module side is the pinned route "
                       "(a7_claim `route_pinned`, `routed_cycle`)"}
    out["m7_two_run_owners_interleave_on_their_own_routes_and_legacy_global_work_still_progresses"] = {
        "unreachable": "S10 CLI/server: two real RedisBus owners and the global relay on one fixture Redis"}
    out["m7_claim_pins_the_route_before_any_message_and_refuses_a_changed_or_foreign_route_redis_bus"] = {
        "unreachable": "S10 CLI: the real RedisBus.for_run; the claim logic over a direct bus double is a7_claim"}
    return out



# ---- coverage (the branch table and the M7 tests, each pointer checked to exist in the result) --------------------------------
RAISES = {   # `application/autonomous.py` @ e38aa722: the 44 raises of branch-table-research.txt, by source line
    "100 unknown_run": ["a2_cycle.status_unknown"],
    "121 route_mismatch": ["a7_claim.route_mismatch", "a7_claim.route_mismatch_before_the_row_checks"],
    "126 configuration_mismatch": ["a2_cycle.configuration_mismatch", "a2_cycle.configuration_mismatch_goal",
                                   "a2_cycle.configuration_mismatch_manifest", "a7_claim.configuration_mismatch_identity",
                                   "a7_claim.configuration_mismatch_goal", "a7_claim.configuration_mismatch_manifest"],
    "129 running_residue": ["a7_claim.running_residue", "a7_claim.unknown_status_is_running_residue", "a6_residue_budget.running_residue_without_takeover"],
    "131 residue": ["a7_claim.residue_session", "a7_claim.residue_operation", "a7_claim.residue_before_deadline"],
    "134 deadline_expired (claim)": ["a7_claim.deadline_expired", "a7_claim.deadline_expired_at_the_deadline",
                                     "a4_artifacts.manifest_deadline_in_the_past"],
    "152 AutonomousRefused(str(ContractError)) from pin_route": ["a7_claim.route_conflict", "a7_claim.route_conflict_on_the_operation_correlation"],
    "152 route_invalid": ["a7_claim.route_invalid"],
    "162 run_state_changed (_transition)": ["a6_residue_budget.transition.wrong_stage", "a6_residue_budget.transition.unknown_run",
                                            "a6_residue_budget.transition.terminal_row"],
    "185 except AutonomousRefused (OUTCOME_BY_REASON)": ["a3_rejected.outcome_by_reason", "a3_rejected.design_rejected",
                                                         "a6_residue_budget.budget_refused_after_2"],
    "187 except Exception (exception:<type>)": ["a6_residue_budget.executor_exception", "a4_artifacts.source_verifier_crash"],
    "208 debate_refused:<DgeRefused code>": ["a5_deadline.before_the_worker"],
    "210 debate_refused:<ContractError> / role_session_shared": ["a4_artifacts.shared_session", "a4_artifacts.unsupported_critical"],
    "226 packet_invalid:<type>": ["a4_artifacts.packet_invalid_missing_field", "a4_artifacts.packet_invalid_needs_user_without_question",
                                  "a4_artifacts.packet_invalid_unknown_source", "a4_artifacts.packet_invalid_ssot_decision"],
    "229 needs_user": ["a4_artifacts.needs_user"],
    "234 source verification (reason_code or source_verification_failed)": ["a4_artifacts.source_reason_code", "a4_artifacts.source_default_reason"],
    "251 design_<state>": ["a3_rejected.design_rejected", "a3_rejected.design_needs_research", "a3_rejected.design_exhausted_by_revise",
                           "a6_residue_budget.implement_design_not_approved"],
    "253 start_cap_reached (implementation)": ["a6_residue_budget.implement_start_cap"],
    "272 deadline_expired (operation receipt)": ["a5_deadline.flip_inside_the_operation_before_the_worker"],
    "273 review_rejected / operation_<status>": ["a3_rejected.review_rejected", "a3_rejected.operation_failed",
                                                 "a6_residue_budget.budget_refused_after_5"],
    "287 start_cap_reached (role)": ["a6_residue_budget.role_start_cap"],
    "297 role_residue": ["a6_residue_budget.role_residue_outbox", "a6_residue_budget.role_residue_task"],
    "304 publication_incomplete (before delivery)": ["a6_residue_budget.publication_incomplete_before_delivery"],
    "311 budget_exhausted": ["a6_residue_budget.budget_refused_after_2", "a6_residue_budget.budget_refused_at_once"],
    "314 settlement_failed": ["a6_residue_budget.settlement_fails_for_the_first_role"],
    "316 no_execution_claimed": ["a6_residue_budget.no_execution_claimed"],
    "318 role_<status>": ["a4_artifacts.role_not_succeeded"],
    "322 publication_incomplete (after execution)": ["a6_residue_budget.publication_incomplete_after_execution"],
    "333 AutonomousRefused(str(ContractError)) from role_binding / _verify_execution": [
        "a4_artifacts.evidence_none", "a4_artifacts.evidence_corrupt", "a4_artifacts.evidence_unrelated", "a4_artifacts.unbound_agent",
        "a4_artifacts.role_base_mismatch", "a4_artifacts.role_row_not_succeeded", "a4_artifacts.role_row_without_generation",
        "a4_artifacts.reservation_unsettled", "a4_artifacts.reservation_of_another_record",
        "a4_artifacts.role_answer_is_not_the_artifact_answer", "a4_artifacts.port_artifact_without_answer"],
    "349 expected_execution_missing": ["a6_residue_budget.require_admitted.missing", "a6_residue_budget.require_admitted.not_a_row",
                                       "a6_residue_budget.expected_execution_missing_by_delivery"],
    "352 expected_execution_foreign": ["a6_residue_budget.require_admitted.message_not_a_dict", "a6_residue_budget.require_admitted.foreign_correlation"],
    "354 expected_execution_not_queued": ["a6_residue_budget.require_admitted.not_queued"],
    "363 ContractError(reason_code or evidence_invalid)": ["a4_artifacts.port_contract_error", "a4_artifacts.port_unavailable"],
    "365 evidence_missing": ["a4_artifacts.evidence_none", "a4_artifacts.port_os_error"],
    "411 foreign_message (foreign notice the store does not prove)": ["a9_delivery.foreign_notice_unproven_is_a_foreign_message"],
    "417 foreign_message": ["a9_delivery.foreign_message", "a9_delivery.dead_letter_then_foreign"],
    "425 publication_incomplete (after handling)": ["a9_delivery.handled_but_unpublished_is_not_acked"],
    "433 deadline_expired (_check_deadline)": ["a5_deadline.check_deadline", "a5_deadline.flip_between_two_roles",
                                               "a5_deadline.flip_before_the_implementation_check", "a5_deadline.after_the_review"],
    "453 deadline_expired (promotion transaction)": ["a5_deadline.flip_inside_the_promotion_transaction"],
    "458 promotion_operation_unproven": ["a8_promotion.refusals.operation_lead_not_accepted", "a8_promotion.refusals.operation_not_accepted"],
    "462 promotion_task_unproven": ["a8_promotion.refusals.task_not_succeeded", "a8_promotion.refusals.task_other_agent",
                                    "a8_promotion.refusals.task_without_candidate", "a8_promotion.refusals.task_without_inspection_ref",
                                    "a8_promotion.refusals.task_result_not_a_dict"],
    "468 promotion_review_unproven": ["a8_promotion.refusals.review_not_succeeded", "a8_promotion.refusals.review_other_phase",
                                      "a8_promotion.refusals.review_verdict_rejected", "a8_promotion.refusals.review_without_candidate",
                                      "a8_promotion.refusals.review_of_another_revision"],
    "476 promotion_inspection_unproven": ["a8_promotion.refusals.inspection_incomplete", "a8_promotion.refusals.inspection_of_another_attempt",
                                          "a8_promotion.refusals.inspection_ghost"],
    "486 evidence_answer_mismatch (reviewer verdict)": ["a8_promotion.evidence_answer_mismatch", "a4_artifacts.verdict_mismatch"],
    "488 promotion_evidence_unproven:<code>": ["a8_promotion.refusals.evidence_worker_reservation_unsettled",
                                               "a8_promotion.refusals.evidence_review_reservation_of_another_record",
                                               "a8_promotion.refusals.evidence_worker_answer_changed",
                                               "a8_promotion.evidence_port_at_promotion.worker_artifact_corrupt",
                                               "a8_promotion.evidence_port_at_promotion.review_artifact_corrupt",
                                               "a8_promotion.evidence_port_at_promotion.port_without_answer",
                                               "a8_promotion.evidence_port_at_promotion.port_contract_error",
                                               "a8_promotion.evidence_port_at_promotion.port_os_error",
                                               "a4_artifacts.skills_review_at_base_refused", "a4_artifacts.skills_worker_at_candidate_refused"],
    "492 promotion_design_unproven": ["a8_promotion.refusals.design_not_approved", "a8_promotion.refusals.design_other_owner",
                                      "a8_promotion.refusals.design_other_origin", "a8_promotion.refusals.design_other_packet"],
    "515 run_state_changed (promotion)": ["a8_promotion.refusals.run_row_changed_stage", "a8_promotion.replay_after_the_run_finished"],
}
M7_TESTS = {   # tests/test_autonomous.py @ e38aa722: 15 test functions, 17 node ids (the parametrized one counts three)
    "test_manifest_reuses_operation_rules_and_refuses_naive_deadline_or_missing_research": ["a1_manifest"],
    "test_normal_cycle_promotes_in_one_transaction_and_reports_six_starts_labels_durations_and_invocations": [
        "a2_cycle.normal", "a2_cycle.operator_submit", "a2_cycle.replay_cached", "a2_cycle.configuration_mismatch"],
    "test_rejected_review_and_rejected_design_never_promote_or_dispatch_further": ["a3_rejected.review_rejected", "a3_rejected.design_rejected"],
    "test_missing_corrupt_or_unrelated_role_artifact_refuses_before_the_next_role[none]": ["a4_artifacts.evidence_none"],
    "test_missing_corrupt_or_unrelated_role_artifact_refuses_before_the_next_role[corrupt]": ["a4_artifacts.evidence_corrupt"],
    "test_missing_corrupt_or_unrelated_role_artifact_refuses_before_the_next_role[unrelated]": ["a4_artifacts.evidence_unrelated"],
    "test_mismatched_review_verdict_or_shared_role_session_never_promotes": ["a4_artifacts.verdict_mismatch", "a4_artifacts.shared_session"],
    "test_review_evidence_is_bound_to_the_reviewed_candidate_and_the_worker_to_its_base": [
        "a4_artifacts.skills_bound_to_candidate_and_base", "a4_artifacts.skills_review_at_base_refused",
        "a4_artifacts.skills_worker_at_candidate_refused"],
    "test_unbound_stale_or_unsupported_role_output_stops_before_the_next_role": [
        "a4_artifacts.unbound_agent", "a4_artifacts.unsupported_critical", "a4_artifacts.needs_user", "a4_artifacts.manifest_deadline_in_the_past"],
    "test_deadline_passing_after_the_review_or_before_the_worker_never_promotes": [
        "a5_deadline.after_the_review", "a5_deadline.before_the_worker", "a5_deadline.child_operation_deadline"],
    "test_running_residue_is_refused_without_takeover_and_budget_refusal_ends_exhausted": [
        "a6_residue_budget.running_residue_without_takeover", "a6_residue_budget.budget_refused_after_2", "a6_residue_budget.budget_refused_after_5"],
    "test_promotion_is_idempotent_refuses_conflict_and_rolls_back_with_the_receipt": ["a8_promotion.standalone"],
    "test_the_cli_owner_wires_one_run_scoped_bus_per_run_and_records_it_on_the_receipt": [
        "a9_delivery.m7_the_cli_owner_wires_one_run_scoped_bus_per_run_and_records_it_on_the_receipt"],
    "test_a_global_relay_interleaved_after_the_commit_never_publishes_or_marks_a_scoped_message": [
        "a9_delivery.m7_a_global_relay_interleaved_after_the_commit_never_publishes_or_marks_a_scoped_message"],
    "test_two_run_owners_interleave_on_their_own_routes_and_legacy_global_work_still_progresses": [
        "a9_delivery.m7_two_run_owners_interleave_on_their_own_routes_and_legacy_global_work_still_progresses"],
    "test_claim_pins_the_route_before_any_message_and_refuses_a_changed_or_foreign_route": [
        "a7_claim.route_pinned", "a7_claim.route_mismatch", "a7_claim.route_conflict",
        "a9_delivery.m7_claim_pins_the_route_before_any_message_and_refuses_a_changed_or_foreign_route_redis_bus"],
    "test_the_run_row_records_its_delivery_namespace_and_a_bus_without_one_records_none": [
        "a2_cycle.bus_namespace_recorded", "a2_cycle.bus_without_namespace"],
}


def resolve(result, path):
    node = result
    for part in path.split("."):
        node = node[part]   # a pointer that does not resolve is a driver error, never a silent gap
    return node


def coverage(result) -> dict:
    for table in (RAISES, M7_TESTS):
        for pointers in table.values():
            for pointer in pointers:
                resolve(result, pointer)
    unreachable = sorted(p for pointers in list(RAISES.values()) + list(M7_TESTS.values()) for p in pointers
                         if isinstance(resolve(result, p), dict) and "unreachable" in resolve(result, p))
    return {"raises": {k: v for k, v in RAISES.items()}, "m7_tests": {k: v for k, v in M7_TESTS.items()},
            "unreachable": {p: resolve(result, p)["unreachable"] for p in unreachable},
            "counts": {"raises_in_branch_table": 44, "raise_entries": len(RAISES), "m7_test_functions": 15, "m7_node_ids": len(M7_TESTS)}}


GROUPS = (("a1_manifest", a1_manifest), ("a2_cycle", a2_cycle), ("a3_rejected", a3_rejected), ("a4_artifacts", a4_artifacts),
          ("a5_deadline", a5_deadline), ("a6_residue_budget", a6_residue_budget), ("a7_claim", a7_claim),
          ("a8_promotion", a8_promotion), ("a9_delivery", a9_delivery))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["cases_per_group"] = counts
        result["coverage"] = coverage(result)
        return result
    finally:
        ws.close()
