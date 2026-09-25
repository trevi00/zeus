"""Durable conductor continuation over the existing Fleet, lanes and owners (INV-CONTINUATION-001).

A thin coordinator, not a second executor, scheduler, reviewer or release authority. It owns four
buckets in the Fleet control store - `continuation_policies` (one registered Git-pinned owner
policy per id), `continuation_intents` (one durable intent per routed observation),
`continuation_progress` (one selection-progress row per policy: attempts only) and
`continuation_research_receipts` (one immutable owner receipt per research intent;
`continuation_capacity_grants` holds one owner capacity grant per budget-refused repair intent) - and one in
each lane store, `continuation_bindings` (the trusted document a lane Operation claim attaches to
its assignment). Everything else is reached through its existing owner:

* `Fleet.enqueue` admits a successor (same id on every replay; the Fleet's own lanes, paths,
  pause and ledger decide when it runs) and finite `zeus operate run` executes it unchanged.
* `WorkerSessions.record_review` moves the logical session on the committed independent review
  decision row; the executor resumes it natively only from `correction_ready`.
* The conductor port starts an owned child running the existing guarded
  `Executor.decide_one("conductor", expected=...)` for exactly the pending conductor row; the
  Releases/ReleaseQueue records it writes are read back.
* HostDelivery and the approved backlog stay the owners of delivery and of the next item; the
  controller records the handoff and observes their durable result.
* The existing Portfolio investigation and research dispatch are the research owners after two
  distinct similar failures; only the owner's scoped receipt (`accept_research`) for the exact
  intent and attempt set releases that hold.

One tick is a few short store transactions with every external effect strictly between them: no
transaction is open across a lane store, Git, a process or the Fleet's own transaction. Each effect
is preceded by a durable intent state and followed by its observed evidence, and each state change
is a compare-and-swap on the intent version, so two controllers and a restart converge on one
intent, one successor id and one dispatch. An idle tick writes nothing and calls nothing.

Restart is a table, not a guess: `domain.continuation.RESUME` names the one action for every open
(route, state) a crash can leave behind. The conductor is never waited on: the Fleet's shared
capacity authority reserves its execution unit in the SAME transaction that commits the launch
identity (`dispatched`), before `conductor.start` spawns the DB-free guardian that owns the conduct
tree; later ticks (or `drain`, when admission is closed) `conductor.poll` its local evidence. The
unit and the intent leave `dispatched` together, in one Fleet settlement, and only on an exact
proof: the guardian's confirmed parent-and-tree cleanup receipt or the never-entered fence. A
decision that succeeded while cleanup is unknown is neither completed nor retried; that debt keeps
its slot for its named owner.
Every NEW effect - lane binding, Fleet admission, conductor start - first passes `_authorize`, the
one eligibility guard comparing the current pinned policy, frame, model and runtime identity with
the authorization stored on the intent; reconciling an already started effect never needs it.
"""
from __future__ import annotations

from codex_harness.application.execution_fence import current as current_fence
from codex_harness.application.portfolio import BUCKET_BINDINGS, PortfolioRefused, inherit_binding
from codex_harness.domain.continuation import (
    ADMITTED,
    AUTHORITY,
    AWAITING_OWNER,
    BINDING_SCHEMA,
    CAPACITY_AUTHORIZED,
    CAPACITY_EXTRA,
    CAPACITY_GRANT_SCHEMA,
    COMPLETED,
    CONDUCTOR,
    CORRECTION,
    COVERAGE_MIXED,
    COVERAGE_ORIGINAL,
    COVERAGE_SUPPLEMENT,
    DELIVERY,
    DELIVERY_ABSENT,
    DELIVERY_BOUND,
    DISPATCHED,
    EVIDENCE_REPAIR,
    INTENDED,
    LAUNCH_ABSENT,
    LAUNCH_EXITED,
    LAUNCH_RUNNING,
    LAUNCH_TIMEOUT,
    LAUNCH_UNKNOWN,
    MAX_ACTIONS_PER_TICK,
    MAX_HISTORY,
    MAX_LAUNCHES,
    MAX_SLOTS,
    MIXED_RECEIPT_SCHEMA,
    NEXT_ITEM,
    OPEN_STATES,
    PAUSED,
    PUBLISHED,
    RECOVERY,
    RECOVERY_REQUIRED,
    REFUSED,
    RESEARCH,
    RESEARCH_REQUIRED,
    RESUME,
    RETURNED,
    ROUTE_OWNERS,
    STATUS_SCHEMA,
    SUCCESSOR_ROUTES,
    TICK_SCHEMA,
    ContinuationRefused,
    attempt_of,
    authorization,
    bind_delivery,
    blocked_families,
    capacity_count,
    capacity_view,
    check_authorization,
    check_capacity_family,
    check_capacity_refusal,
    check_capacity_source,
    check_mixed_receipt,
    check_research_receipt,
    check_scope,
    check_scope_supplement,
    classify,
    delivery_tuple,
    effect_free,
    evidence_digest,
    fair_order,
    intent_id,
    intent_slot,
    is_member,
    launch_id,
    needs_research,
    observed_attempt,
    owners,
    policy_digest,
    progress_order,
    receipt_refs,
    receipt_view,
    record_attempt,
    refuse,
    research_attempts,
    successor_id,
    successor_manifest,
    supplement_view,
    transition,
    validate_binding,
    validate_capacity_grant,
    validate_policy,
    validate_receipt,
    validate_scope_supplement,
    view,
)
from codex_harness.domain.fleet import UNIT_CONDUCTOR, FleetRefused, held_units
from codex_harness.domain.model import ContractError, digest, utcnow
from codex_harness.domain.research_investigations import (
    REVOCATION_BUCKET,
    current_dispatch_id,
    revocation_held,
    revocation_task_id,
    successor_held,
    successor_key,
    successor_reads,
)
from codex_harness.domain.research_program import council_result

BUCKET_POLICIES = "continuation_policies"
BUCKET_INTENTS = "continuation_intents"
BUCKET_PROGRESS = "continuation_progress"
LANE_BINDINGS = "continuation_bindings"
FLEET_JOBS = "fleet_jobs"
FLEET_UNITS = "fleet_units"
BUCKET_RESEARCH_RECEIPTS = "continuation_research_receipts"
BUCKET_RESEARCH_SUPPLEMENTS = "continuation_research_supplements"
BUCKET_CAPACITY_GRANTS = "continuation_capacity_grants"
PROMOTIONS = "promotions"
INVESTIGATIONS = "portfolio_investigations"
RESEARCH_DISPATCHES = "research_investigation_dispatches"
RESEARCH_RECOVERIES = "research_dispatch_recoveries"
RESEARCH_SUCCESSORS, RESEARCH_HEADS = "research_dispatch_successors", "research_dispatch_heads"
MAX_LINEAGE = 1000
RESEARCH_RUNS = "autonomous_runs"
EVENT_TRANSITION = "operations.continuation_transition"
EVENT_BLOCKED = "operations.continuation_blocked"
TERMINAL_JOBS = frozenset({"accepted", "rejected", "failed", "exhausted", "unknown"})
MARKERS = frozenset({"unconfirmed", "pending_reconciliation"})
DELIVERY_ACTIVE = "active"
DELIVERY_HALTED = frozenset({"rolled_back", "failed", "blocked"})


class IntentChanged(ContractError):
    """Another controller (or a restart replay) moved the intent first; nothing was written here."""


class LaneRuntime:
    """One tick's view of `runtime(lane_id)`: each lane's identity is read once, and a failed read is
    remembered, so an unreadable runtime is one lane-wide outage for the tick, not a slot per job."""

    def __init__(self, port):
        self.port, self.seen = port, {}

    def __call__(self, lane_id: str):
        if lane_id not in self.seen:
            try:
                self.seen[lane_id] = (self.port(lane_id), None)
            except Exception as exc:
                self.seen[lane_id] = (None, exc)
        value, error = self.seen[lane_id]
        if error is not None:
            raise error
        return value

    def failed(self, lane_id: str) -> bool:
        return self.seen.get(lane_id, (None, None))[1] is not None


# ---- one lane store -----------------------------------------------------------------------------
class LaneEvidence:
    """Reads and the two narrow effects on ONE lane store. Every method is its own short
    transaction; `sessions` is the lane's `WorkerSessions` owner (None: no session effect)."""

    def __init__(self, store, sessions=None):
        self.store, self.sessions = store, sessions

    def read(self, job: dict, target: str | None = None) -> dict:
        """The decisive lane evidence of one terminal job, from store reads only. `target` is the
        policy's delivery target: only ITS HostDelivery intent for the exact release and candidate
        is delivery evidence (`bind_delivery`); a plan of another target is foreign."""
        with self.store.transaction() as tx:
            operation = tx.get("operations", job["operation_id"])
            binding = tx.get(LANE_BINDINGS, job["operation_id"])
            evidence = {"operation": operation, "binding": binding, "task": None, "lead": None,
                        "conductor": None, "delivery": None, "session": None, "markers": []}
            if not isinstance(operation, dict):
                return evidence
            # An evidence-refused operation names its candidate task only in its owner handoff.
            handoff = operation.get("owner_handoff") if isinstance(operation.get("owner_handoff"), dict) else {}
            task_id = operation.get("task_id") or handoff.get("task_id")
            decision_id = operation.get("decision_id")
            if isinstance(task_id, str):
                evidence["task"] = tx.get("tasks", task_id)
            if isinstance(decision_id, str):
                evidence["lead"] = tx.get("decisions_pending", decision_id)
            owned = {task_id, decision_id} - {None}
            evidence["markers"] = sorted(
                record.get("record_id") or record.get("task_id") for record in tx.scan("observation_terminations")
                if isinstance(record, dict) and record.get("status") in MARKERS and record.get("task_id") in owned)
            if operation.get("status") == "accepted" and isinstance(decision_id, str):
                conductor = [row for row in tx.scan("decisions_pending")
                             if row.get("phase") == "review_conductor"
                             and ((row.get("message") or {}).get("what") or {}).get("details", {}).get(
                                 "decision_id") == decision_id]
                evidence["conductor"] = conductor[0] if conductor else None
                result = (evidence["conductor"] or {}).get("result") or {}
                release_id = (result.get("deployment") or {}).get("release_id") or result.get("release_id")
                if isinstance(release_id, str):
                    deliveries = [row for row in tx.scan("host_delivery_intents") if row.get("release_id") == release_id]
                    task = evidence["task"] if isinstance(evidence["task"], dict) else {}
                    candidate = (task.get("result") or {}).get("candidate") or {}
                    evidence["delivery"] = bind_delivery(deliveries, target, release_id, candidate.get("revision"),
                                                         tx.get("releases", release_id))
            session = (binding or {}).get("session") if isinstance(binding, dict) else None
            if isinstance(session, dict):
                evidence["session"] = tx.get("worker_sessions", session["task_id"])
        return evidence

    def bind(self, document: dict) -> dict:
        """Write the trusted binding once; the identical document replays, any other refuses."""
        document = validate_binding(document)
        with self.store.transaction() as tx:
            old = tx.get(LANE_BINDINGS, document["operation_id"])
            if old is not None:
                refuse(old == document, "binding_conflict", field="operation_id")
                return {"bound": True, "cached": True}
            if tx.get("operations", document["operation_id"]) is not None:
                # The operation already claimed without this binding: it cannot be attached late.
                raise ContinuationRefused("operation_already_claimed", "operator", "operation_id")
            tx.put(LANE_BINDINGS, document["operation_id"], document)
        return {"bound": True, "cached": False}

    def bound(self, operation_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(LANE_BINDINGS, operation_id)

    def record_review(self, task_id: str, decision_id: str) -> dict | None:
        """The session owner reads the committed decision row itself; a duplicate is a no-op."""
        if self.sessions is None:
            return None
        return self.sessions.record_review(task_id, decision_id)


# ---- the coordinator ----------------------------------------------------------------------------
class Continuation:
    """`store` is the Fleet control store. `lanes(lane_id)` returns that lane's `LaneEvidence`.
    `fleet` is the existing `Fleet`. `validate(manifest)` is the existing operation manifest
    validator the adapter binds to the packaged provider policy.

    `conductor` is the guarded conductor port (None: the conductor route waits for its owner):
    `start(lane_id, job, launch_id, token)` (returns once the guardian is spawned, never when the
    decision is made) and `poll(lane_id, launch_id) -> {state, owned, exit_code, cleanup_confirmed,
    proof}` with a state of `domain.continuation.LAUNCH_STATES`. Capacity is never the port's: the
    Fleet (sharing this control store) reserves and settles the execution unit.

    `evidence` is the research evidence port: `verify(ref)` reads the actual bounded bytes of one
    content-addressed reference from the trusted configured artifact store and checks their digest,
    or raises `ContinuationRefused` with a safe reason code. None: no research receipt is accepted or
    consumed (`research_evidence_unverified`)."""

    def __init__(self, store, fleet=None, lanes=None, conductor=None, validate=None, observer=None, clock=utcnow,
                 evidence=None):
        self.store, self.fleet, self.lanes, self.conductor = store, fleet, lanes, conductor
        self.validate, self.observer, self.clock, self.evidence = validate, observer, clock, evidence

    # ----- registry -----------------------------------------------------------------------
    def register(self, document, pin: dict) -> dict:
        policy = validate_policy(document)
        sha = policy_digest(policy)
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_POLICIES, policy["id"])
            if old is not None:
                refuse(old["policy_sha256"] == sha and old["pin"] == pin, "policy_conflict", field="id")
                return {"registered": True, "cached": True, "id": policy["id"], "policy_sha256": sha}
            tx.put(BUCKET_POLICIES, policy["id"], {"id": policy["id"], "policy": policy, "policy_sha256": sha,
                                                   "pin": dict(pin), "registered_at": self.clock()})
        return {"registered": True, "cached": False, "id": policy["id"], "policy_sha256": sha}

    def policy(self, policy_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(BUCKET_POLICIES, policy_id)

    def status(self, policy_id: str | None = None) -> dict:
        """Read-only projection: intents with route, state, cause, next owner/action, evidence
        references and predecessor/successor links. No manifest text, transcript or credential."""
        with self.store.transaction() as tx:
            policies = tx.scan(BUCKET_POLICIES)
            intents = tx.scan(BUCKET_INTENTS)
            receipts = tx.scan(BUCKET_RESEARCH_RECEIPTS)
            supplements = tx.scan(BUCKET_RESEARCH_SUPPLEMENTS)
            grants = tx.scan(BUCKET_CAPACITY_GRANTS)
        if policy_id is not None:
            policies = [row for row in policies if row["id"] == policy_id]
            intents = [row for row in intents if row.get("policy_id") == policy_id]
            grants = [row for row in grants if (row.get("grant") or {}).get("policy_id") == policy_id]
        # Explicit capacity is shown beside, never merged into, each family's original cap and count.
        by_id = {row["id"]: row for row in intents}
        grants = [capacity_view(row, by_id.get(row["id"])) for row in sorted(grants, key=lambda r: r["id"])]
        caps = {row["id"]: row["policy"]["max_corrections"] for row in policies}
        families = []
        for owner, family in sorted({(g["policy_id"], g["family"]) for g in grants}):
            mine = [g for g in grants if (g["policy_id"], g["family"]) == (owner, family)]
            cap, counted = caps.get(owner), capacity_count(intents, owner, family)
            extra = sum(g["explicit_capacity"] or 0 for g in mine)
            families.append({"policy_id": owner, "family": family, "original_cap": cap, "counted": counted,
                             "explicit_capacity": extra, "grants": [g["grant_sha256"] for g in mine],
                             "remaining": None if cap is None else max(0, cap + extra - counted)})
        # A research intent shows the exact attempt set an owner receipt must cover, and the stored
        # receipt (covered jobs, inspections, dispatch, evidence) once the owner recorded one. An owner
        # scope supplement is shown beside it, never merged into the original capture.
        receipts = {row["id"]: receipt_view(row) for row in receipts}
        supplements = {row["id"]: supplement_view(row) for row in supplements}
        views = [{**view(row), "attempts": research_attempts(intents, row), "receipt": receipts.get(row["id"]),
                  "supplement": supplements.get(row["id"])}
                 if row["route"] == RESEARCH else view(row)
                 for row in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"]))]
        counts: dict = {}
        for row in views:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        return {"schema": STATUS_SCHEMA, "authority": AUTHORITY,
                "policies": [{"id": row["id"], "enabled": row["policy"]["enabled"], "policy_sha256": row["policy_sha256"],
                              "pin": row["pin"]} for row in policies],
                "intents": views[-200:], "truncated": len(views) > 200, "counts": counts,
                "held_families": blocked_families(intents), "capacity": {"grants": grants, "families": families}}

    # ----- scoped research completion (owner receipt) -------------------------------------
    def accept_research(self, document) -> dict:
        """Record the owner's scoped research receipt for one `research_required` intent.

        Every binding is verified against authoritative reads first (`check_research_receipt`): the
        exact policy, intent and family, the COMPLETE current attempt set, each attempt's lane
        evidence digest and inspection, the Portfolio investigation holding those jobs and the
        resolved existing research dispatch whose bound run row is accepted. Stored once and never
        edited: the identical receipt replays (`cached`), any other for the same intent is
        `research_receipt_conflict`. Every accepted return, a replay included, first rechecks an
        execution-revocation lineage's retained fence; a refused replay keeps the stored receipt. It moves no intent: the next tick consumes it after verifying
        it again, so a restart or a second controller completes the hold exactly once.

        A schema-2 document is the mixed-cause family receipt (`check_mixed_receipt`): same entry,
        bucket, replay, conflict, fence and commit checks; it never reads or needs a scope supplement,
        and its row records `coverage: mixed_family`."""
        receipt = validate_receipt(document)
        facts = self._research_facts(receipt)
        stored = facts.pop("stored")
        supplement = self._supplement_of(facts, receipt)
        if stored is not None:
            refuse(stored.get("receipt") == receipt, "research_receipt_conflict", "operator", "intent_id")
            self._require_recovery(facts)   # a cached acceptance answers only while the fence still holds
            return self._receipt_result(stored, cached=True)
        self._require_recovery(facts)
        if isinstance(facts["intent"], dict) and facts["intent"].get("state") == RESEARCH_REQUIRED:
            facts["observed"] = self._observe_attempts(facts["jobs"])
        coverage = self._coverage(receipt, facts)
        self._verify_evidence(receipt_refs(receipt))
        if coverage == COVERAGE_SUPPLEMENT:
            self._verify_evidence([supplement["supplement"]["report_ref"], supplement["supplement"]["attestation_ref"]])
        now = self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_RESEARCH_RECEIPTS, receipt["intent_id"])
            if old is not None:
                refuse(old.get("receipt") == receipt, "research_receipt_conflict", "operator", "intent_id")
            # The retained fence again in THIS writer transaction (never a nested one): a concurrent
            # insertion, or a fence lost since the read, never returns acceptance.
            self._require_recovery({"recovery_held": self._recovery_held(tx, receipt["investigation"])})
            if old is not None:
                return self._receipt_result(old, cached=True)
            # Nothing moved between the verification and this write: same intent version, same set.
            intent = tx.get(BUCKET_INTENTS, receipt["intent_id"])
            refuse(isinstance(intent, dict) and intent.get("version") == facts["intent"].get("version")
                   and intent.get("state") == RESEARCH_REQUIRED, "research_intent_changed", "operator", "intent_id")
            intents = [row for row in tx.scan(BUCKET_INTENTS) if row.get("policy_id") == receipt["policy_id"]]
            refuse(research_attempts(intents, intent) == facts["attempts"], "research_attempts_changed", "operator",
                   "attempts")
            # How the attempt set is covered is part of the stored row: consumption requires the same
            # coverage (and the same immutable supplement) again, so status never merges the two.
            if coverage == COVERAGE_SUPPLEMENT:
                refuse(tx.get(BUCKET_RESEARCH_SUPPLEMENTS, receipt["intent_id"]) == supplement,
                       "research_coverage_changed", ROUTE_OWNERS[RESEARCH], "supplement")
            if coverage == COVERAGE_MIXED:
                # The dispatch that captured the members is still the CURRENT one, byte for byte.
                investigation = receipt["investigation"]
                current = current_dispatch_id(investigation, tx.get(RESEARCH_RECOVERIES, investigation),
                                              tx.get(RESEARCH_HEADS, investigation))
                refuse(tx.get(RESEARCH_DISPATCHES, current) == facts["dispatch"], "research_dispatch_mismatch",
                       ROUTE_OWNERS[RESEARCH], "dispatch")
            row = {"id": receipt["intent_id"], "schema": receipt["schema"], "receipt": receipt,
                   "receipt_sha256": digest(receipt), "accepted_at": now, "recorded_by": "owner",
                   "coverage": coverage,
                   "supplement_sha256": supplement["supplement_sha256"] if coverage == COVERAGE_SUPPLEMENT else None}
            tx.put(BUCKET_RESEARCH_RECEIPTS, row["id"], row)
        return self._receipt_result(row, cached=False)

    @staticmethod
    def _receipt_result(row: dict, cached: bool) -> dict:
        return {"accepted": True, "cached": cached, **receipt_view(row)}

    @staticmethod
    def _coverage(receipt: dict, facts: dict) -> str:
        """The check owning the receipt's version; returns how its attempt set is covered."""
        if receipt["schema"] == MIXED_RECEIPT_SCHEMA:
            return check_mixed_receipt(receipt, **{k: facts[k] for k in (
                "intent", "attempts", "policy", "jobs", "observed", "investigations", "dispatch", "run_result",
                "lineage", "bindings", "acceptance")})
        return check_research_receipt(receipt, **facts)

    @staticmethod
    def _supplement_of(facts: dict, receipt: dict | None = None) -> dict | None:
        """Move the stored supplement row out of the facts; the checks receive only its document. A
        mixed-cause receipt never uses a supplement, so none is read into its facts."""
        row = facts.pop("supplement_row")
        if receipt is not None and receipt.get("schema") == MIXED_RECEIPT_SCHEMA:
            return None
        if row is None:
            facts["supplement"] = None
            return None
        # A stored row that no longer matches its own digest is not the supplement that was verified.
        refuse(isinstance(row, dict) and isinstance(row.get("supplement"), dict)
               and row.get("supplement_sha256") == digest(row["supplement"]), "research_supplement_corrupt",
               ROUTE_OWNERS[RESEARCH], "supplement")
        facts["supplement"] = row["supplement"]
        return row

    # ----- owner research scope supplement ------------------------------------------------
    def supplement_research_scope(self, document) -> dict:
        """Record the owner's typed scope supplement for one `research_required` intent whose accepted
        current research dispatch sampled only part of its attempt set (SPEC "Research coverage
        ownership: accepted003 receipt refusal").

        Append-only and immutable: one row per intent in `continuation_research_supplements`, the
        identical document replays (`cached`), any other is `research_supplement_conflict`. The
        dispatch, its snapshot, the investigation, every failure verdict and every receipt stay as
        they are. Verified against the same authoritative reads as a receipt plus the persisted
        continuation lineage, the Portfolio bindings and the accepted run's promotion evidence
        (`check_scope_supplement`), and the report/attestation bytes through the trusted evidence
        port. It releases nothing by itself: a receipt still has to be accepted and consumed, and
        both re-verify it."""
        supplement = validate_scope_supplement(document)
        facts = self._research_facts(supplement)
        facts.pop("stored")
        stored = facts.pop("supplement_row")
        if stored is not None:
            refuse(stored.get("supplement") == supplement, "research_supplement_conflict", "operator", "intent_id")
            self._require_recovery(facts)
            return self._supplement_result(stored, cached=True)
        self._require_recovery(facts)
        if isinstance(facts["intent"], dict) and facts["intent"].get("state") == RESEARCH_REQUIRED:
            facts["observed"] = self._observe_attempts(facts["jobs"])
        check_scope_supplement(supplement, **facts)
        self._verify_evidence([supplement["report_ref"], supplement["attestation_ref"]])
        now = self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_RESEARCH_SUPPLEMENTS, supplement["intent_id"])
            if old is not None:
                refuse(old.get("supplement") == supplement, "research_supplement_conflict", "operator", "intent_id")
            self._require_recovery({"recovery_held": self._recovery_held(tx, supplement["investigation"])})
            if old is not None:
                return self._supplement_result(old, cached=True)
            intent = tx.get(BUCKET_INTENTS, supplement["intent_id"])
            refuse(isinstance(intent, dict) and intent.get("version") == facts["intent"].get("version")
                   and intent.get("state") == RESEARCH_REQUIRED, "research_intent_changed", "operator", "intent_id")
            intents = [row for row in tx.scan(BUCKET_INTENTS) if row.get("policy_id") == supplement["policy_id"]]
            refuse(research_attempts(intents, intent) == facts["attempts"], "research_attempts_changed", "operator",
                   "attempts")
            investigation = supplement["investigation"]
            current = current_dispatch_id(investigation, tx.get(RESEARCH_RECOVERIES, investigation),
                                          tx.get(RESEARCH_HEADS, investigation))
            refuse(current == supplement["dispatch"]["id"] and tx.get(RESEARCH_DISPATCHES, current) == facts["dispatch"],
                   "research_dispatch_mismatch", ROUTE_OWNERS[RESEARCH], "dispatch")
            row = {"id": supplement["intent_id"], "schema": supplement["schema"], "supplement": supplement,
                   "supplement_sha256": digest(supplement), "recorded_at": now, "recorded_by": "owner"}
            tx.put(BUCKET_RESEARCH_SUPPLEMENTS, row["id"], row)
        return self._supplement_result(row, cached=False)

    @staticmethod
    def _supplement_result(row: dict, cached: bool) -> dict:
        return {"supplemented": True, "cached": cached, **supplement_view(row)}

    def research_facts(self, document: dict) -> dict:
        """The exact authoritative reads `accept_research` checks a receipt against, for a server owner
        that assembles one (INV-OWNER-ACTIONS-001): the same reader, never a second copy of its rules.
        `document` names the policy, intent, investigation and attempt jobs (and its schema)."""
        return self._research_facts(document)

    def _research_facts(self, receipt: dict) -> dict:
        """The authoritative reads one receipt (or scope supplement) is checked against: control-store
        rows in ONE short transaction, then each attempt's lane evidence outside it. A lane or store
        failure raises: an unread attempt never approves."""
        with self.store.transaction() as tx:
            policy = tx.get(BUCKET_POLICIES, receipt["policy_id"])
            intent = tx.get(BUCKET_INTENTS, receipt["intent_id"])
            intents = [row for row in tx.scan(BUCKET_INTENTS) if row.get("policy_id") == receipt["policy_id"]]
            stored = tx.get(BUCKET_RESEARCH_RECEIPTS, receipt["intent_id"])
            investigation = tx.get(INVESTIGATIONS, receipt["investigation"])
            # The CURRENT dispatch of the investigation: after an owner-authorized recovery that is
            # the replacement (research-dispatch-recovery-001), so a receipt naming the failed
            # original, or a result of its run, can never approve.
            # A settled read-only successor head names the current one after that; a stale receipt
            # naming a predecessor then mismatches, and a broken retained chain holds.
            recovery = tx.get(RESEARCH_RECOVERIES, receipt["investigation"])
            dispatch = tx.get(RESEARCH_DISPATCHES, current_dispatch_id(receipt["investigation"], recovery,
                                                                       tx.get(RESEARCH_HEADS, receipt["investigation"])))
            recovery_held = self._recovery_held(tx, receipt["investigation"])
            run_id = (dispatch or {}).get("run_id") if isinstance(dispatch, dict) else None
            run = tx.get(RESEARCH_RUNS, run_id) if type(run_id) is str else None
            jobs = {a["job"]: tx.get(FLEET_JOBS, a["job"]) for a in receipt["attempts"]}
            # What an owner scope supplement is checked against: the stored supplement, the Portfolio
            # binding of every attempt job and the accepted run's own promotion evidence rows.
            supplement_row = tx.get(BUCKET_RESEARCH_SUPPLEMENTS, receipt["intent_id"])
            bindings = {a["job"]: tx.get(BUCKET_BINDINGS, a["job"]) for a in receipt["attempts"]}
            promotion = tx.get(PROMOTIONS, run_id) if type(run_id) is str else None
            proof = (promotion.get("evidence") if isinstance(promotion, dict) else None) or {}
            proof = proof if isinstance(proof, dict) else {}
            task_id, decision_id = proof.get("implementation_task_id"), proof.get("decision_id")
            acceptance = {"run": run, "promotion": promotion,
                          "task": tx.get("tasks", task_id) if type(task_id) is str else None,
                          "decision": tx.get("decisions_pending", decision_id) if type(decision_id) is str else None}
            # A mixed-cause receipt names each member's OWN investigation; each is read here as well.
            mixed = receipt.get("schema") == MIXED_RECEIPT_SCHEMA
            investigations = ({name: tx.get(INVESTIGATIONS, name)
                               for name in sorted({a["investigation"] for a in receipt["attempts"]})} if mixed else None)
        held = isinstance(intent, dict) and intent.get("route") == RESEARCH
        run_result = (council_result(run_id, dispatch.get("manifest_sha256"), run) if type(run_id) is str
                      else {"result": "unknown", "reason_code": "dispatch_not_started", "row_status": None})
        facts = {"stored": stored, "intent": intent, "attempts": research_attempts(intents, intent) if held else [],
                 "policy": policy, "jobs": jobs, "observed": {}, "investigation": investigation,
                 "dispatch": dispatch, "run_result": run_result, "recovery_held": recovery_held,
                 "supplement_row": supplement_row, "lineage": {row["id"]: row for row in intents},
                 "bindings": bindings, "acceptance": acceptance}
        return {**facts, "investigations": investigations} if mixed else facts

    @staticmethod
    def _recovery_held(tx, investigation: str) -> str | None:
        """An execution-revocation lineage answers only while its OWN retained task fence holds, and a
        settled read-only successor chain only while every retained predecessor fence and bound execution
        still holds: the named held condition, read through the caller's open transaction, else None."""
        recovery = tx.get(RESEARCH_RECOVERIES, investigation)
        revoked = revocation_task_id(recovery)
        held = None if revoked is None else revocation_held(
            recovery, fence=current_fence(tx, REVOCATION_BUCKET, revoked) if revoked else None,
            task=tx.get(REVOCATION_BUCKET, revoked) if revoked else None,
            delivery=tx.get("outbox_delivery", revoked) if revoked else None)
        head = tx.get(RESEARCH_HEADS, investigation)
        if held is not None or head is None:
            return held
        version = head.get("version") if isinstance(head, dict) else None
        chain = [tx.get(RESEARCH_SUCCESSORS, successor_key(investigation, v)) for v in range(2, version + 1)] \
            if type(version) is int and 2 <= version < MAX_LINEAGE else []
        deliveries, tasks = successor_reads(chain)
        return successor_held(investigation, head, chain, deliveries={d: tx.get("outbox_delivery", d) for d in deliveries},
                              tasks={t: tx.get("tasks", t) for t in tasks})

    @staticmethod
    def _require_recovery(facts: dict) -> None:
        """A revocation-mode lineage whose retained fence no longer holds never approves or releases."""
        code = facts.pop("recovery_held")
        refuse(code is None, "research_" + str(code), ROUTE_OWNERS[RESEARCH], "dispatch")

    def _verify_evidence(self, refs) -> None:
        """Every evidence ref's actual bytes (a receipt's `evidence_refs`, a supplement's report and
        attestation), read now through the trusted store and digest checked, outside any store
        transaction. Integrity holds at this observed read only: acceptance checks it, and each tick
        checks it again before consuming the receipt (a cached acceptance is history, never a
        substitute). A missing verifier or any port failure refuses by code."""
        refuse(self.evidence is not None, "research_evidence_unverified", "operator", "evidence_refs")
        for ref in refs:
            try:
                self.evidence.verify(ref)
            except ContinuationRefused:
                raise
            except Exception:
                # A port fault never releases; its raw message may carry a path and is not kept.
                raise ContinuationRefused("research_evidence_unreadable", ROUTE_OWNERS[RESEARCH],
                                          "evidence_refs") from None

    def _observe_attempts(self, jobs: dict) -> dict:
        """Each attempt's lane evidence now, one short lane transaction each; a failure raises."""
        refuse(self.lanes is not None, "lanes_unconfigured", "operator", "lanes")
        return {job_id: observed_attempt(job, self.lanes(job["lane"]).read(job))
                for job_id, job in jobs.items() if isinstance(job, dict)}

    def unresolved(self, policy_id: str, owned=()) -> list:
        """Conductor work of this policy no guardian of THIS process supervises: dispatched launches
        and every Fleet execution unit still held for one of its intents (a previous controller's
        guardian, an unconfirmed start, cleanup unknown or settlement pending). A heartbeat reports
        them as unresolved, never as idle."""
        owned = set(owned)
        with self.store.transaction() as tx:
            intents = [row for row in tx.scan(BUCKET_INTENTS) if row.get("policy_id") == policy_id]
            units = [row for row in tx.scan(FLEET_UNITS) if row.get("kind") == UNIT_CONDUCTOR]
        mine = {row["id"] for row in intents}
        refs = {(row.get("launch") or {}).get("id") or row["id"] for row in intents if row["state"] == DISPATCHED}
        refs |= set(held_units(unit for unit in units if unit.get("subject") in mine))
        return sorted(ref for ref in refs if ref not in owned)

    # ----- one tick -----------------------------------------------------------------------
    def tick(self, policy_id: str, *, pin_sha256: str | None = None, runtime=None) -> dict:
        """One bounded pass. `pin_sha256` is the digest of the pinned policy bytes re-read by the
        adapter this tick; `runtime(lane_id)` names the lane's actual image/profile/archive identity."""
        result = {"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": "idle", "actions": [],
                  "skipped": [], "reason_code": None, "owned_elsewhere": {"count": 0, "jobs": []}}
        row = self.policy(policy_id)
        if row is None:
            return {**result, "outcome": "disabled", "reason_code": "policy_unregistered"}
        policy = row["policy"]
        if not policy["enabled"]:
            return {**result, "outcome": "disabled", "reason_code": "policy_disabled"}
        if pin_sha256 is not None and pin_sha256 != row["pin"].get("sha256"):
            # No NEW effect under changed pinned bytes; already started launches are still settled
            # under the binding they were started with.
            drained = self.drain(policy_id)
            return {**result, "outcome": "refused", "reason_code": "policy_changed", "next_owner": "operator",
                    "actions": drained["actions"], "skipped": drained["skipped"]}
        with self.store.transaction() as tx:
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)}
            every = tx.scan(BUCKET_INTENTS)
        intents = [intent for intent in every if intent.get("policy_id") == policy_id]
        ctx = {"policy": policy, "sha": row["policy_sha256"], "pin": row["pin"].get("sha256"),
               "runtime": LaneRuntime(runtime) if runtime else None, "jobs": jobs}
        self._bind_initial(ctx, intents, owners(every, policy_id), result)
        for intent in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"])):
            if (intent["route"], intent["state"]) in RESUME:
                self._guarded(result, intent["id"], lambda i=intent: self._advance(ctx, i))
        with self.store.transaction() as tx:
            every = tx.scan(BUCKET_INTENTS)
            progress = tx.get(BUCKET_PROGRESS, policy_id)
        intents = [intent for intent in every if intent.get("policy_id") == policy_id]
        # Membership and ownership first, THEN the bounded fair pass: unrelated history and another
        # policy's lineage never occupy a slot. An unavailable lane (store or runtime identity) is
        # skipped visibly without spending a slot, at most MAX_ACTIONS_PER_TICK reads per lane. Each
        # attempt is recorded durably before its read, so the next pass - any controller, after a
        # restart - tries the least recently attempted candidate first: per-job read failures never
        # hold the same reads forever.
        candidates, elsewhere = self._candidates(policy, jobs, intents, owners(every, policy_id))
        result["owned_elsewhere"] = {"count": len(elsewhere), "jobs": elsewhere[:16]}
        budget, failures = MAX_ACTIONS_PER_TICK, {}
        live, since = {candidate["job_id"] for candidate in candidates}, int((progress or {}).get("sequence") or 0)
        for candidate in progress_order(fair_order(candidates, intents, limit=None), progress):
            lane = jobs[candidate["job_id"]]["lane"]
            if budget <= 0:
                break
            if failures.get(lane, 0) >= MAX_ACTIONS_PER_TICK:
                continue
            if self._guarded(result, candidate["job_id"], lambda c=candidate: self._attempt(policy_id, c, live, since)
                             or self._observe(ctx, c, intents)) == "unavailable":
                runtime_down = ctx["runtime"] is not None and ctx["runtime"].failed(lane)
                failures[lane] = MAX_ACTIONS_PER_TICK if runtime_down else failures.get(lane, 0) + 1
            else:
                budget -= 1
        if result["actions"]:
            result["outcome"] = "progressed"
        elif result["skipped"]:
            result["outcome"] = "blocked"
        return result

    def drain(self, policy_id: str) -> dict:
        """Admission closed (graceful stop, host pause, changed or unreadable pin): only launches
        already started are polled and settled under their original binding. Nothing new is bound,
        admitted or started, and with nothing dispatched this reads no lane and writes nothing."""
        result = {"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": "draining", "actions": [],
                  "skipped": [], "reason_code": None}
        with self.store.transaction() as tx:
            dispatched = [row for row in tx.scan(BUCKET_INTENTS)
                          if row.get("policy_id") == policy_id and row["state"] == DISPATCHED]
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)} if dispatched else {}
        for intent in sorted(dispatched, key=lambda r: (str(r.get("created_at")), r["id"])):
            self._guarded(result, intent["id"], lambda i=intent: self._reconcile_launch(i, jobs))
        return result

    def _guarded(self, result, subject, action) -> str | None:
        """One subject's work; a lost race or a named refusal is recorded, never raised past the tick,
        so one family's outage never stops another family's progress. Returns the skip reason code."""
        try:
            done = action()
        except IntentChanged:
            result["skipped"].append({"subject": subject, "reason_code": "intent_changed"})
            return "intent_changed"
        except ContinuationRefused as exc:
            result["skipped"].append({"subject": subject, "reason_code": exc.reason_code, "next_owner": exc.owner})
            return exc.reason_code
        except Exception as exc:  # a lane store, Git or Fleet outage: the intent stays for the next tick
            result["skipped"].append({"subject": subject, "reason_code": "unavailable",
                                      "error_type": type(exc).__name__})
            return "unavailable"
        if isinstance(done, dict) and "history" in done:
            # A stored intent row is never printed: only its identity, state and route leave.
            done = {"subject": done["id"], "effect": done["state"], "route": done["route"]}
        if done:
            result["actions"].append(done)
        return None

    # ----- candidates ---------------------------------------------------------------------
    @staticmethod
    def _family_of(job_id: str, intents: list) -> tuple[str, str | None]:
        for intent in intents:
            if intent.get("successor_job") == job_id:
                return intent["family"], intent["id"]
        return job_id, None

    def _candidates(self, policy: dict, jobs: dict, intents: list, owned: dict) -> tuple[list, list]:
        """Terminal member jobs of the policy with no intent for their current decisive evidence, and
        the member jobs another policy's intent owns (`owned`, excluded and reported, never observed).
        Jobs whose origin intent already exists are re-read only when their row changed."""
        seen = {(intent["origin_job"], intent.get("job_updated_at")) for intent in intents}
        out, elsewhere = [], []
        for job in sorted(jobs.values(), key=lambda j: j["id"]):
            if job.get("status") not in TERMINAL_JOBS or not is_member(policy, job):
                continue
            if (job["id"], job.get("updated_at")) in seen and not self._reclassifiable(job, intents):
                continue
            if job["id"] in owned:
                elsewhere.append({"job": job["id"], "policy_id": owned[job["id"]]})
                continue
            family, predecessor = self._family_of(job["id"], intents)
            out.append({"job_id": job["id"], "family": family, "predecessor": predecessor,
                        "finished_at": job.get("finished_at")})
        return out, elsewhere

    @staticmethod
    def _reclassifiable(job: dict, intents: list) -> bool:
        """An accepted job moves on through conductor -> delivery -> next item as its lane evidence
        changes, and a failure held for research is routed again once the research resolved; every
        other terminal job is routed exactly once per job row."""
        mine = [intent for intent in intents if intent["origin_job"] == job["id"]]
        return bool(mine) and all(intent["state"] == COMPLETED for intent in mine) and not any(
            intent["route"] in {NEXT_ITEM, *SUCCESSOR_ROUTES} for intent in mine)

    def _attempt(self, policy_id: str, candidate: dict, live: set, since: int) -> None:
        """Durable selection progress in its own short transaction BEFORE the lane read: a scheduling
        attempt only, never an intent, a verdict or evidence (`domain.continuation.record_attempt`)."""
        with self.store.transaction() as tx:
            tx.put(BUCKET_PROGRESS, policy_id, record_attempt(tx.get(BUCKET_PROGRESS, policy_id), policy_id,
                                                               candidate["job_id"], live, since))

    # ----- initial session binding --------------------------------------------------------
    def _bind_initial(self, ctx, intents, owned, result) -> None:
        """Bind a newly queued policy job to its own logical session BEFORE admission, so the first
        execution already runs as a task session. A successor is bound by its own intent instead."""
        policy, runtime = ctx["policy"], ctx["runtime"]
        successors = {intent.get("successor_job") for intent in intents}
        for job in sorted(ctx["jobs"].values(), key=lambda j: j["id"]):
            if (job.get("status") != "queued" or job["id"] in successors or job["id"] in owned
                    or not is_member(policy, job)):
                continue
            try:
                check_scope(policy, job, runtime(job["lane"]) if runtime else None)
            except ContinuationRefused:
                continue  # not eligible now: the job keeps its exact legacy behaviour
            except Exception as exc:  # an unreadable runtime identity: this job only, visibly
                result["skipped"].append({"subject": job["id"], "reason_code": "unavailable",
                                          "error_type": type(exc).__name__})
                continue
            lane = self.lanes(job["lane"])

            def bind(job=job, lane=lane):
                if lane.bound(job["id"]) is not None:
                    return None
                lane.bind({"schema": BINDING_SCHEMA, "operation_id": job["id"], "policy_sha256": ctx["sha"],
                           "intent_id": None, "family": job["id"], "route": None,
                           "session": {"task_id": job["id"], "repository": job["repository"]},
                           "workspace": None, "predecessor": None})
                return {"subject": job["id"], "effect": "session_bound"}
            self._guarded(result, job["id"], bind)

    # ----- a new observation --------------------------------------------------------------
    def _observe(self, ctx, candidate, intents):
        policy, runtime = ctx["policy"], ctx["runtime"]
        job = ctx["jobs"][candidate["job_id"]]
        lane = self.lanes(job["lane"])
        evidence = lane.read(job, policy["delivery_target"])
        family = candidate["family"]
        routed = classify(job, evidence)
        route = routed["route"]
        base = {"policy_id": policy["id"], "policy_sha256": ctx["sha"], "origin_job": job["id"], "lane": job["lane"],
                "family": family, "predecessor_intent": candidate["predecessor"],
                "job_updated_at": job.get("updated_at")}
        if route is None:
            if routed["reason_code"] in {"not_terminal", "conductor_running"}:
                return None
            return self._create({**base, "route": "refusal", "state": REFUSED, "reason_code": routed["reason_code"],
                                 "next_owner": routed.get("owner", "operator"),
                                 "evidence_sha256": evidence_digest(job, evidence, "refusal")}, attempt_of(evidence))
        current = runtime(job["lane"]) if runtime else None
        try:
            check_scope(policy, job, current)
        except ContinuationRefused as exc:
            return self._create({**base, "route": route, "state": REFUSED, "reason_code": exc.reason_code,
                                 "next_owner": exc.owner, "evidence_sha256": evidence_digest(job, evidence, route)},
                                attempt_of(evidence))
        # The exact binding every later NEW effect of this intent is re-checked against.
        base["authorization"] = authorization(ctx["sha"], ctx["pin"], job, current)
        evidence_sha = evidence_digest(job, evidence, route)
        if route == RECOVERY:
            return self._create({**base, "route": RECOVERY, "state": RECOVERY_REQUIRED,
                                 "reason_code": routed["reason_code"], "next_owner": ROUTE_OWNERS[RECOVERY],
                                 "evidence_sha256": evidence_sha, "evidence_refs": evidence["markers"]},
                                attempt_of(evidence))
        if route in SUCCESSOR_ROUTES:
            if needs_research(intents, family, evidence_sha):
                return self._create({**base, "route": RESEARCH, "state": RESEARCH_REQUIRED,
                                     "reason_code": "two_distinct_failures", "next_owner": ROUTE_OWNERS[RESEARCH],
                                     "evidence_sha256": evidence_sha,
                                     "family_jobs": sorted({i["origin_job"] for i in intents if i["family"] == family}
                                                           | {job["id"]})}, attempt_of(evidence))
            successors = [i for i in intents if i["family"] == family and i["route"] in SUCCESSOR_ROUTES
                          and i["state"] != REFUSED]
            if len(successors) >= policy["max_corrections"]:
                return self._create({**base, "route": route, "state": REFUSED, "reason_code": "correction_budget_exhausted",
                                     "next_owner": "operator", "evidence_sha256": evidence_sha}, attempt_of(evidence))
            return self._successor(ctx, base, job, evidence, route, routed, evidence_sha, lane)
        if route == CONDUCTOR:
            created = self._create({**base, "route": CONDUCTOR, "state": INTENDED, "reason_code": routed["reason_code"],
                                    "next_owner": ROUTE_OWNERS[CONDUCTOR], "evidence_sha256": evidence_sha},
                                   attempt_of(evidence))
            if created["state"] != INTENDED:
                return None  # an existing intent: its own state is advanced by `_advance`
            return self._dispatch(ctx, created, job) or created
        # DELIVERY: the conductor accepted; the release is queued for its existing owners. The
        # exact (policy target, release, candidate revision) tuple is carried by the intent and
        # re-validated against the persisted HostDelivery evidence at every reconciliation.
        delivery = evidence.get("delivery") or {}
        created = self._create({**base, "route": DELIVERY, "state": AWAITING_OWNER, "reason_code": routed["reason_code"],
                                "next_owner": ROUTE_OWNERS[DELIVERY], "evidence_sha256": evidence_sha,
                                "release_id": delivery.get("release_id"), "delivery_target": policy["delivery_target"],
                                "delivery_binding": delivery_tuple(delivery),
                                "evidence_refs": [ref for ref in (((evidence.get("conductor") or {}).get("result") or {})
                                                                  .get("execution_ref"),) if ref]},
                               attempt_of(evidence))
        if created["state"] != AWAITING_OWNER:
            return None
        return self._advance_delivery(created, evidence) or created

    def _successor(self, ctx, base, job, evidence, route, routed, evidence_sha, lane):
        """Intent first (with the complete successor identity), then the lane binding, then the
        existing Fleet admission - each step replayable to the same result after a lost response."""
        attempt = attempt_of(evidence)
        with self.store.transaction() as tx:
            key, _ = self._claim(tx, intent_id(job["id"], attempt, evidence_sha, route), base["policy_id"])
        plan = self._successor_plan(ctx["sha"], base["family"], job, evidence, route, routed, key, lane)
        if plan is None:
            # Recorded once for this evidence: the existing validator decides, nothing is trimmed.
            return self._create({**base, "route": route, "state": REFUSED, "reason_code": "successor_manifest_refused",
                                 "next_owner": "operator", "evidence_sha256": evidence_sha}, attempt, key=key)
        created = self._create({**base, "route": route, "state": INTENDED, "reason_code": routed["reason_code"],
                                "next_owner": ROUTE_OWNERS[route], "evidence_sha256": evidence_sha, **plan},
                               attempt, key=key)
        return self._publish(ctx, created)

    def _successor_plan(self, sha, family, job, evidence, route, routed, key, lane) -> dict | None:
        """The complete successor identity of intent `key`: manifest (the existing validator decides;
        None when it refuses), lane binding and session mode. Shared by a new observation and an
        owner capacity grant, so both derive the same successor for the same intent."""
        operation = evidence["operation"]
        task = evidence.get("task") or {}
        candidate = ((task.get("result") or {}).get("candidate") or {}) if isinstance(task, dict) else {}
        successor = successor_id(key)
        decision = evidence.get("conductor") if routed["reason_code"] == "conductor_rejected" else evidence.get("lead")
        references = {"predecessor_job": job["id"], "candidate_revision": candidate.get("revision"),
                      "candidate_tree": candidate.get("tree"),
                      "review_decision": (decision or {}).get("id") if route == CORRECTION else None,
                      "review_execution_ref": ((decision or {}).get("result") or {}).get("execution_ref")
                      if route == CORRECTION else None,
                      "inspection": ((operation.get("owner_handoff") or {}).get("inspection") or {}).get("id")
                      if route == EVIDENCE_REPAIR else None}
        manifest = successor_manifest(job["manifest"], route, successor, references)
        if self.validate is not None:
            try:
                manifest = self.validate(manifest)
            except ContractError:
                return None
        # The logical session of a family is keyed by its root job (see `_bind_initial`). Only a
        # correction of a session the owner moved to `correction_ready` on THIS review decision is
        # eligible for native resume; everything else is an explicit fresh evidence handoff.
        session, mode = None, "fresh_evidence_handoff"
        binding = evidence.get("binding") if isinstance(evidence.get("binding"), dict) else {}
        logical = {"task_id": family, "repository": job["repository"]}
        if route == CORRECTION and isinstance(decision, dict) and lane.sessions is not None:
            try:
                row = lane.record_review(logical["task_id"], decision["id"])
            except ContractError as exc:  # missing session, candidate mismatch: never a resume
                mode = "fresh_evidence_handoff:" + str(getattr(exc, "reason", "refused"))
            else:
                if isinstance(row, dict) and row.get("state") == "correction_ready":
                    session, mode = logical, "native_resume_eligible"
        workspace = None
        if isinstance(task.get("id"), str) and candidate.get("revision") and candidate.get("base"):
            workspace = {"origin_task_id": (binding.get("workspace") or {}).get("origin_task_id") or task["id"],
                         "head": candidate["revision"], "base": candidate["base"]}
        document = {"schema": BINDING_SCHEMA, "operation_id": successor, "policy_sha256": sha, "intent_id": key,
                    "family": family, "route": route, "session": session, "workspace": workspace,
                    "predecessor": {"job_id": job["id"], "task_id": task.get("id"),
                                    "candidate_revision": candidate.get("revision"),
                                    "decision_id": (decision or {}).get("id") if route == CORRECTION else None,
                                    "review_execution_ref": references["review_execution_ref"],
                                    "inspection_id": references["inspection"]}}
        return {"successor_job": successor, "manifest": manifest, "binding": document, "session_mode": mode,
                "evidence_refs": [ref for ref in (references["review_execution_ref"],) if ref]}

    # ----- the one eligibility guard ------------------------------------------------------
    def _authorize(self, ctx, intent: dict) -> dict:
        """Before every NEW effect (lane binding, Fleet admission, conductor start): the current
        pinned policy, frame, model and runtime identity must equal the intent's stored authorization.

        Drift refuses the effect and records the exact reason and next owner on the intent as a
        `hold` (written once, not on every idle tick); the state, the stored authorization and all
        evidence stay as they were. A hold clears only when the current binding equals the stored
        one again - it is never resolved by adopting the changed binding."""
        job = ctx["jobs"].get(intent["origin_job"])
        try:
            refuse(job is not None, "origin_job_missing", "fleet", "origin_job")
            refuse(intent.get("policy_sha256") == ctx["sha"], "policy_changed", field="policy_sha256")
            current = ctx["runtime"](job["lane"]) if ctx["runtime"] else None
            check_scope(ctx["policy"], job, current)
            check_authorization(intent.get("authorization"), authorization(ctx["sha"], ctx["pin"], job, current))
            if intent.get("capacity_grant") is not None:
                self._check_grant(ctx, intent)   # a granted repair: the grant and its bindings again
        except ContinuationRefused as exc:
            hold = {"reason_code": exc.reason_code, "next_owner": exc.owner, "field": exc.field}
            if intent.get("hold") != hold:
                self._note(intent, emit=True, hold=hold, next_owner=exc.owner)
            raise
        if intent.get("hold") is not None:
            intent = self._note(intent, emit=True, hold=None, next_owner=ROUTE_OWNERS.get(intent["route"], "operator"))
        return intent

    # ----- effects ------------------------------------------------------------------------
    def _publish(self, ctx, intent: dict) -> dict | None:
        if intent["state"] not in {INTENDED, PUBLISHED}:
            return None
        lane = self.lanes(intent["lane"])
        if intent["state"] == INTENDED:
            intent = self._authorize(ctx, intent)
            lane.bind(intent["binding"])
            intent = self._move(intent, PUBLISHED)
        if intent["state"] == PUBLISHED:
            refuse(self.fleet is not None, "fleet_unconfigured")
            intent = self._authorize(ctx, intent)
            with self.store.transaction() as tx:
                origin = tx.get(FLEET_JOBS, intent["origin_job"])
            self.fleet.enqueue(intent["lane"], intent["manifest"], origin["goal"], [])
            # Admission is confirmed, the origin's Portfolio ownership inherited and the intent moved in
            # ONE control-store transaction (no nested one): an interruption after the enqueue leaves
            # `published`, the replay re-admits the same id and binds once, and a conflicting target
            # binding refuses without advancing the intent (SPEC "Research coverage ownership").
            with self.store.transaction() as tx:
                admitted = tx.get(FLEET_JOBS, intent["successor_job"])
                refuse(admitted is not None and admitted.get("manifest_sha256") is not None, "admission_unconfirmed",
                       "fleet")
                ownership, _ = self._inherit(tx, intent)
                previous, intent = self._apply(tx, intent, ADMITTED, {"ownership": ownership})
            self._emit(previous, intent)
        return {"subject": intent["id"], "effect": intent["state"], "route": intent["route"],
                "successor_job": intent.get("successor_job")}

    def _inherit(self, tx, intent: dict) -> tuple[dict, bool]:
        """The successor inherits exactly its origin's Portfolio binding through this persisted intent
        (`portfolio.inherit_binding`); an unbound origin stays unbound, never guessed. Returns the
        ownership recorded on the intent and whether the binding already existed."""
        try:
            bound = inherit_binding(tx, intent["successor_job"], intent["origin_job"], {"intent_id": intent["id"]},
                                    self.clock())
        except PortfolioRefused as exc:
            raise ContinuationRefused("successor_" + exc.reason_code, "portfolio", "binding") from None
        if bound is None:
            return {"state": "origin_unbound", "project_id": None, "criterion_id": None}, False
        binding = bound["binding"]
        return ({"state": "inherited", "project_id": binding["project_id"], "criterion_id": binding["criterion_id"]},
                bound["cached"])

    # ----- explicit ownership reconciliation ----------------------------------------------
    def reconcile_ownership(self, intent_id: str) -> dict:
        """The owner's explicit reconciliation of ONE already admitted successor admitted before
        ownership was inherited. Proven only from the persisted exact parent/successor intent and both
        Fleet rows (the successor row carries the intent's own manifest on its lane; the origin row is
        the job the intent was authorized on), never from arbitrary job ids, names or text. It asserts
        PRESENT ownership only: no dispatch snapshot, capture or failure verdict is touched, and the
        intent itself is not moved. One transaction; identical replays are cached."""
        refuse(type(intent_id) is str and bool(intent_id), "ownership_intent_invalid", "operator", "intent_id")
        with self.store.transaction() as tx:
            intent = tx.get(BUCKET_INTENTS, intent_id)
            refuse(isinstance(intent, dict) and intent.get("route") in SUCCESSOR_ROUTES
                   and intent.get("state") in {ADMITTED, RETURNED, COMPLETED}
                   and type(intent.get("successor_job")) is str, "ownership_intent_invalid", "operator", "intent_id")
            refuse(tx.get(BUCKET_POLICIES, intent.get("policy_id")) is not None, "policy_unregistered", "operator",
                   "policy_id")
            successor = tx.get(FLEET_JOBS, intent["successor_job"])
            origin = tx.get(FLEET_JOBS, intent["origin_job"])
            source = (intent.get("authorization") or {}).get("source") or {}
            predecessor = (intent.get("binding") or {}).get("predecessor") or {}
            refuse(isinstance(successor, dict) and successor_id(intent["id"]) == intent["successor_job"]
                   and successor.get("id") == intent["successor_job"] and successor.get("lane") == intent.get("lane")
                   and successor.get("manifest") == intent.get("manifest")
                   and successor.get("manifest_sha256") is not None
                   and (intent.get("binding") or {}).get("operation_id") == intent["successor_job"],
                   "ownership_lineage_unproven", "operator", "successor_job")
            refuse(isinstance(origin, dict) and origin.get("lane") == intent.get("lane")
                   and source.get("job") == intent["origin_job"] == predecessor.get("job_id")
                   and source.get("manifest_sha256") == origin.get("manifest_sha256") is not None,
                   "ownership_lineage_unproven", "operator", "origin_job")
            ownership, cached = self._inherit(tx, intent)
            refuse(ownership["state"] == "inherited", "ownership_origin_unbound", "portfolio", "origin_job")
        return {"reconciled": True, "cached": cached, "intent_id": intent_id, "successor_job": intent["successor_job"], "origin_job": intent["origin_job"],
                **{k: ownership[k] for k in ("project_id", "criterion_id")},
                "authority": "present ownership through continuation lineage; not historical capture membership"}

    # ----- owner evidence-repair capacity grant -------------------------------------------
    def grant_capacity(self, document, *, pin_sha256: str | None = None, runtime=None) -> dict:
        """Record the owner's one-use capacity grant for ONE exact `evidence_repair` intent refused for
        `correction_budget_exhausted` (SPEC "Exact evidence-repair capacity authorization").

        Verified first against authoritative reads (`_grant_bindings`): the registered policy and the
        re-read pin, the intent refused at creation, the current runtime/frame authorization, the origin
        job's unchanged lane evidence, inspection and retained candidate, the family's latest research
        completed by exactly the pinned receipt (every consumption check rerun) and the rationale bytes.
        Then ONE control-store transaction stores the grant and moves THAT intent `refused -> intended`
        with the successor it always derived (compare-and-swap on its version), keeping the refusal as a
        snapshot and in the history. Nothing external happens here: the next tick binds and admits
        through the existing path, rechecking the grant before each new effect. The identical grant
        replays (`cached`); any other grant for the same intent is `capacity_grant_conflict`, and a
        reserved successor stays charged whatever its outcome."""
        grant = validate_capacity_grant(document)
        with self.store.transaction() as tx:
            stored = tx.get(BUCKET_CAPACITY_GRANTS, grant["intent_id"])
            row = tx.get(BUCKET_POLICIES, grant["policy_id"])
            intent = tx.get(BUCKET_INTENTS, grant["intent_id"])
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)}
        if stored is not None:
            refuse(stored.get("grant") == grant, "capacity_grant_conflict", "operator", "intent_id")
            return self._grant_result(stored, intent, cached=True)
        refuse(pin_sha256 is not None and runtime is not None, "capacity_policy_unverified", "operator", "pin")
        refuse(isinstance(row, dict) and row["policy_sha256"] == grant["policy_sha256"] and row["policy"]["enabled"]
               and row["pin"].get("sha256") == pin_sha256, "capacity_policy_foreign", "operator", "policy")
        check_capacity_refusal(grant, intent)
        ctx = {"policy": row["policy"], "sha": row["policy_sha256"], "pin": row["pin"].get("sha256"),
               "runtime": LaneRuntime(runtime), "jobs": jobs}
        job = jobs.get(intent["origin_job"])
        refuse(isinstance(job, dict), "capacity_source_changed", "operator", "source.job")
        current = ctx["runtime"](job["lane"])
        check_scope(ctx["policy"], job, current)
        check_authorization(intent["authorization"], authorization(ctx["sha"], ctx["pin"], job, current))
        bound = self._grant_bindings(ctx, grant, intent)
        job = bound["job"]   # the source row the bindings verified, compared again at commit
        plan = self._successor_plan(ctx["sha"], grant["family"], job, bound["evidence"], EVIDENCE_REPAIR,
                                    classify(job, bound["evidence"]), intent["id"], self.lanes(job["lane"]))
        refuse(plan is not None, "capacity_successor_refused", "operator", "manifest")
        grant_sha, now = digest(grant), self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_CAPACITY_GRANTS, grant["intent_id"])
            if old is not None:
                refuse(old.get("grant") == grant, "capacity_grant_conflict", "operator", "intent_id")
                return self._grant_result(old, tx.get(BUCKET_INTENTS, grant["intent_id"]), cached=True)
            # Nothing the verification read moved: same intent version, policy row, source row and receipt.
            current = tx.get(BUCKET_INTENTS, intent["id"])
            refuse(current == intent, "capacity_intent_changed", "operator", "intent_id")
            refuse(tx.get(BUCKET_POLICIES, grant["policy_id"]) == row, "capacity_policy_foreign", "operator", "policy")
            refuse(tx.get(FLEET_JOBS, job["id"]) == job, "capacity_source_changed", "operator", "source.job")
            refuse(tx.get(BUCKET_RESEARCH_RECEIPTS, bound["research"]["id"]) == bound["receipt"],
                   "capacity_research_mismatch", ROUTE_OWNERS[RESEARCH], "research_receipt_sha256")
            refuse(tx.get(FLEET_JOBS, plan["successor_job"]) is None, "capacity_successor_exists", "fleet",
                   "successor_job")
            every = tx.scan(BUCKET_INTENTS)
            check_capacity_family(grant, current, every, {j["id"]: j for j in tx.scan(FLEET_JOBS)})
            # A distinct owner decision per grant: an earlier grant's rationale never authorizes another.
            refuse(not any((other.get("grant") or {}).get("rationale_ref") == grant["rationale_ref"]
                           for other in tx.scan(BUCKET_CAPACITY_GRANTS)), "capacity_rationale_reused", "operator",
                   "rationale_ref")
            refusal = {key: current.get(key) for key in ("state", "reason_code", "next_owner", "evidence_sha256",
                                                          "version", "created_at", "updated_at")}
            refusal["history"] = list(current.get("history") or [])
            stored = {"id": intent["id"], "schema": CAPACITY_GRANT_SCHEMA, "grant": grant, "grant_sha256": grant_sha,
                      "successor_job": plan["successor_job"], "research_intent": bound["research"]["id"],
                      "capacity": {"max_corrections": ctx["policy"]["max_corrections"],
                                   "counted": capacity_count(every, grant["policy_id"], grant["family"]),
                                   "extra": CAPACITY_EXTRA},
                      "refusal": refusal, "recorded_at": now, "recorded_by": "owner"}
            # The one explicit authorization transition of this intent (never a TRANSITIONS edge).
            current.update(state=INTENDED, reason_code=CAPACITY_AUTHORIZED, next_owner=ROUTE_OWNERS[EVIDENCE_REPAIR],
                           capacity_grant=grant_sha, refusal=refusal, version=current["version"] + 1, updated_at=now,
                           **plan)
            current["history"] = current["history"][-(MAX_HISTORY - 1):] + [
                {"state": INTENDED, "previous": REFUSED, "reason_code": CAPACITY_AUTHORIZED, "error_type": None,
                 "grant": grant_sha, "at": now}]
            tx.put(BUCKET_CAPACITY_GRANTS, stored["id"], stored)
            tx.put(BUCKET_INTENTS, current["id"], current)
        self._emit(REFUSED, current)
        return self._grant_result(stored, current, cached=False)

    @staticmethod
    def _grant_result(row: dict, intent, cached: bool) -> dict:
        return {"granted": True, "cached": cached, **capacity_view(row, intent)}

    def _grant_bindings(self, ctx, grant: dict, intent: dict) -> dict:
        """What a grant is bound to, re-read now outside any transaction: this policy's scope, no active
        or unknown family work (Fleet jobs and units included), the origin's lane evidence, the latest
        family research and its stored receipt rechecked as at consumption, and the rationale bytes.
        Fleet rows are read here too, never taken from a tick-entry snapshot: a source row that moved
        between two effects of one tick (lane binding, then admission) refuses the second.
        Returns {evidence, research, receipt, job}; the first gap refuses by name."""
        with self.store.transaction() as tx:
            every = tx.scan(BUCKET_INTENTS)
            units = [row for row in tx.scan(FLEET_UNITS) if row.get("kind") == UNIT_CONDUCTOR]
            jobs = {row["id"]: row for row in tx.scan(FLEET_JOBS)}
        refuse(intent["origin_job"] not in owners(every, grant["policy_id"]), "capacity_scope_foreign", "operator",
               "source.job")
        family = {row["id"] for row in every if row.get("policy_id") == grant["policy_id"]
                  and row.get("family") == grant["family"]}
        refuse(not held_units(unit for unit in units if unit.get("subject") in family), "capacity_family_active",
               "operator", "family")
        research = check_capacity_family(grant, intent, every, jobs)
        job = jobs.get(intent["origin_job"])
        evidence = self.lanes(intent["lane"]).read(job, ctx["policy"]["delivery_target"])
        check_capacity_source(grant, intent, job, evidence)
        with self.store.transaction() as tx:
            receipt = tx.get(BUCKET_RESEARCH_RECEIPTS, research["id"])
        refuse(isinstance(receipt, dict), "capacity_research_mismatch", ROUTE_OWNERS[RESEARCH], "research_receipt_sha256")
        self._recheck_receipt(grant["policy_id"], grant["policy_sha256"], research, receipt, consumed=True)
        try:
            self._verify_evidence([grant["rationale_ref"]])
        except ContinuationRefused as exc:
            raise ContinuationRefused(exc.reason_code.replace("research_evidence", "capacity_rationale", 1), "operator",
                                      "rationale_ref") from None
        return {"evidence": evidence, "research": research, "receipt": receipt, "job": job}

    def _check_grant(self, ctx, intent: dict) -> None:
        """Before a granted intent's NEW effect: its stored grant, intact and naming this intent and
        successor under the current policy, and every binding re-read (`_grant_bindings`)."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_CAPACITY_GRANTS, intent["id"])
        refuse(isinstance(row, dict), "capacity_grant_missing", "operator", "capacity_grant")
        grant = row.get("grant")
        refuse(isinstance(grant, dict) and row.get("grant_sha256") == digest(grant) == intent["capacity_grant"]
               and grant.get("intent_id") == intent["id"] and row.get("successor_job") == intent.get("successor_job")
               == successor_id(intent["id"]), "capacity_grant_corrupt", "operator", "capacity_grant")
        refuse(grant["policy_id"] == ctx["policy"]["id"] and grant["policy_sha256"] == ctx["sha"],
               "capacity_policy_foreign", "operator", "policy")
        self._grant_bindings(ctx, grant, intent)

    def _dispatch(self, ctx, intent: dict, job: dict) -> dict | None:
        """Guard, then ONE Fleet transaction reserves the shared execution unit and commits the
        launch identity with its token (`dispatched`) BEFORE the guardian is spawned, then the start
        returns without waiting for the decision. No local count authorizes it; a full fleet refuses
        (`conductor_capacity`) and the intent stays. A failed or lost start response is not retried
        here: reconciliation of this same launch identity decides whether a guardian entered."""
        if self.conductor is None:
            moved = self._move(intent, AWAITING_OWNER, reason_code="conductor_port_unconfigured")
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        refuse(self.fleet is not None and getattr(self.fleet, "store", None) is self.store,
               "fleet_unconfigured", "fleet")
        intent = self._authorize(ctx, intent)
        sequence = int((intent.get("launch") or {}).get("sequence") or 0) + 1
        launch = {"id": launch_id(intent["id"], sequence), "sequence": sequence, "state": "starting",
                  "exit_code": None, "error_type": None}
        moved = {}

        def dispatched(tx, unit):
            moved["previous"], moved["row"] = self._apply(tx, intent, DISPATCHED, {"launch": {**launch, "token": unit["token"]}})
        try:
            self.fleet.reserve_unit(launch["id"], UNIT_CONDUCTOR, intent["lane"], intent["id"], within=dispatched)
        except FleetRefused as exc:
            raise ContinuationRefused("conductor_" + exc.reason_code, "fleet", exc.field) from exc
        if "row" not in moved:
            raise IntentChanged(intent["id"])  # the reservation already committed with its intent move
        intent = moved["row"]
        self._emit(moved["previous"], intent)
        launch = intent["launch"]
        try:
            started = self.conductor.start(intent["lane"], job, launch["id"], launch["token"])
        except Exception as exc:
            try:
                self._note(intent, launch={**launch, "state": "start_unconfirmed", "error_type": type(exc).__name__})
            except Exception:  # the next poll reconciles the same launch identity either way
                pass
            return {"subject": intent["id"], "effect": "launch_unconfirmed", "route": CONDUCTOR,
                    "error_type": type(exc).__name__}
        pid = (started or {}).get("pid") if isinstance(started, dict) else None
        intent = self._note(intent, launch={**launch, "state": "started", "pid": pid if type(pid) is int else None})
        # One non-blocking observation: a child that already finished settles in this tick.
        return self._reconcile_launch(intent, ctx["jobs"]) or {"subject": intent["id"], "effect": "conductor_started",
                                                               "route": CONDUCTOR}

    def _reconcile_launch(self, intent: dict, jobs: dict) -> dict | None:
        """Observe an already started launch and settle it from the committed decision row. Needs no
        eligibility: its outcome is retained under the binding it was started with."""
        job = jobs.get(intent["origin_job"])
        refuse(job is not None, "origin_job_missing", "fleet", "origin_job")
        launch = intent.get("launch") if isinstance(intent.get("launch"), dict) else None
        if launch is None:
            # A dispatch recorded without a launch identity: the decision row alone decides, and a
            # still running row becomes recovery work, never a relaunch.
            return self._settle_conductor(intent, job, {"state": LAUNCH_EXITED, "exit_code": None})
        refuse(self.conductor is not None, "conductor_port_unconfigured", "conductor")
        observed = self.conductor.poll(intent["lane"], launch["id"])
        observed = observed if isinstance(observed, dict) else {}
        state = observed.get("state")
        if state == LAUNCH_RUNNING:
            if observed.get("owned"):
                return None
            # Supervised by a guardian this process did not start (a previous controller's): only
            # this family waits, its unit stays held; never a second start.
            raise ContinuationRefused("conductor_owner_unknown", "conductor", "launch")
        if state == LAUNCH_ABSENT:
            # The fence proves the launch never entered and never will: the unit is released with it.
            moved = self._settle(intent, observed, AWAITING_OWNER, reason_code="conductor_not_launched",
                                 launch={**launch, "state": LAUNCH_ABSENT})
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        if state in {LAUNCH_EXITED, LAUNCH_TIMEOUT} and observed.get("cleanup_confirmed") is True:
            return self._settle_conductor(intent, job, observed)
        # Exited or timed out without a confirmed parent-and-tree receipt, a guardian that ended
        # without proof, or unreadable evidence: owned debt. The decision row is not even read - a
        # succeeded decision with unknown cleanup neither completes nor frees a retry.
        reason = "conductor_cleanup_unknown" if state in {LAUNCH_EXITED, LAUNCH_TIMEOUT, LAUNCH_UNKNOWN} \
            else "conductor_launch_unknown"
        if launch.get("state") != "cleanup_unknown":
            self._note(intent, emit=True, launch={**launch, "state": "cleanup_unknown"},
                       hold={"reason_code": reason, "next_owner": ROUTE_OWNERS[RECOVERY], "field": "launch"})
        raise ContinuationRefused(reason, ROUTE_OWNERS[RECOVERY], "launch")

    def _settle(self, intent, observed, target, **fields) -> dict:
        """Leave `dispatched`: the intent move and the Fleet unit's release commit together, and only
        on the observed proof. A launch recorded before shared units existed has no token, and so
        no unit to release: its intent moves alone."""
        token = (intent.get("launch") or {}).get("token")
        if not token:
            return self._move(intent, target, **fields)
        moved = {}

        def settled(tx, unit):
            moved["previous"], moved["row"] = self._apply(tx, intent, target, fields)
        try:
            self.fleet.settle_unit(intent["launch"]["id"], token, observed.get("proof"), within=settled)
        except FleetRefused as exc:
            raise ContinuationRefused("conductor_settlement_" + exc.reason_code, ROUTE_OWNERS[RECOVERY],
                                      exc.field) from exc
        if "row" not in moved:
            raise IntentChanged(intent["id"])  # already settled together with its intent
        self._emit(moved["previous"], moved["row"])
        return moved["row"]

    def _settle_conductor(self, intent, job, observed) -> dict | None:
        evidence = self.lanes(intent["lane"]).read(job)
        conductor = evidence.get("conductor") or {}
        status = conductor.get("status")
        fields = {}
        if isinstance(intent.get("launch"), dict):
            exit_code = observed.get("exit_code")
            fields["launch"] = {**intent["launch"], "state": observed.get("state"),
                                "exit_code": exit_code if type(exit_code) is int else None}
            if fields["launch"]["state"] is None:
                fields["launch"]["state"] = LAUNCH_EXITED
        if intent.get("hold") is not None:
            fields["hold"] = None
        if status == "succeeded":
            result = conductor.get("result") or {}
            decision = {"id": conductor.get("id"), "status": status, "accepted": result.get("accepted"),
                        "execution_ref": result.get("execution_ref")}
            moved = self._settle(intent, observed, RETURNED, decision=decision,
                                 evidence_refs=[ref for ref in (result.get("execution_ref"),) if ref], **fields)
            moved = self._move(moved, COMPLETED)
            return {"subject": moved["id"], "effect": "conductor_decided", "route": CONDUCTOR}
        if status in {None, "pending"} and int(conductor.get("attempt") or 0) == 0:
            # Provably not entered (no attempt) AND the prior tree proven gone: a later launch of a NEW
            # identity may claim it.
            moved = self._settle(intent, observed, AWAITING_OWNER, reason_code="conductor_not_claimed", **fields)
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        reason = "conductor_timeout" if observed.get("state") == LAUNCH_TIMEOUT else "conductor_" + str(status)
        moved = self._settle(intent, observed, RECOVERY_REQUIRED, reason_code=reason,
                             next_owner=ROUTE_OWNERS[RECOVERY], **fields)
        return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}

    def _advance_delivery(self, intent, evidence) -> dict | None:
        """Only the HostDelivery intent bound to this item's (target, release, candidate) moves it.
        Foreign, stale, ambiguous or mismatched evidence is a named wait: never a completion, never a
        pause of this family, and nothing is written."""
        delivery = evidence.get("delivery")
        refuse(isinstance(delivery, dict), "delivery_evidence_missing", "host_delivery", "release_id")
        refuse(delivery_tuple(delivery) == delivery_tuple(intent.get("delivery_binding")), "delivery_binding_changed",
               "host_delivery", "delivery_binding")
        if delivery["binding"] == DELIVERY_ABSENT:
            return None
        refuse(delivery["binding"] == DELIVERY_BOUND, "delivery_" + str(delivery["binding"]), "host_delivery",
               "delivery")
        plan = {"plan_id": delivery.get("plan_id"), "plan_sha256": delivery.get("plan_sha256"),
                "stage": delivery.get("stage")}
        stage = delivery.get("stage")
        if stage == DELIVERY_ACTIVE:
            moved = self._move(intent, COMPLETED, reason_code="delivery_active", delivery_plan=plan)
            nxt = self._create({key: intent[key] for key in ("policy_id", "policy_sha256", "origin_job", "lane", "family",
                                                             "job_updated_at")}
                               | {"route": NEXT_ITEM, "state": AWAITING_OWNER, "reason_code": "item_completed",
                                  "next_owner": ROUTE_OWNERS[NEXT_ITEM], "predecessor_intent": moved["id"],
                                  "evidence_sha256": intent["evidence_sha256"],
                                  "authorization": intent.get("authorization")},
                               {"generation": 0, "attempt": 0})
            return {"subject": moved["id"], "effect": "delivered", "route": DELIVERY, "next": nxt["id"]}
        if stage in DELIVERY_HALTED:
            moved = self._move(intent, PAUSED, reason_code="delivery_" + stage, next_owner="host_delivery",
                               delivery_plan=plan)
            return {"subject": moved["id"], "effect": moved["state"], "route": DELIVERY}
        return None

    # ----- restart: one action per (route, state), domain.continuation.RESUME -------------
    def _advance(self, ctx, intent):
        action = RESUME.get((intent["route"], intent["state"]))
        if action is None:
            return None
        return getattr(self, "_resume_" + action)(ctx, intent, ctx["jobs"].get(intent["origin_job"]))

    def _resume_publish(self, ctx, intent, job):
        return self._publish(ctx, intent)

    def _resume_await_successor(self, ctx, intent, job):
        successor = ctx["jobs"].get(intent["successor_job"])
        if successor is None or successor.get("status") not in TERMINAL_JOBS:
            return None
        moved = self._move(intent, RETURNED, reason_code="successor_" + successor["status"])
        return self._resume_complete(ctx, moved, job)

    def _resume_complete(self, ctx, intent, job):
        """`returned` already holds the exact committed outcome (successor status, or the conductor
        decision); completing it needs no other read and no effect."""
        moved = self._move(intent, COMPLETED)
        return {"subject": moved["id"], "effect": "successor_returned" if moved["route"] in SUCCESSOR_ROUTES
                else "returned_completed", "route": moved["route"]}

    def _resume_dispatch(self, ctx, intent, job):
        refuse(job is not None, "origin_job_missing", "fleet", "origin_job")
        return self._dispatch(ctx, intent, job)

    def _resume_reconcile_launch(self, ctx, intent, job):
        return self._reconcile_launch(intent, ctx["jobs"])

    def _resume_redispatch(self, ctx, intent, job):
        """A conductor intent waiting because its row was not claimed (or no port was configured).
        A new launch identity is started only for a row still provably not entered, within
        `MAX_LAUNCHES`, and only after the eligibility guard."""
        if self.conductor is None or job is None:
            return None
        conductor = self.lanes(intent["lane"]).read(job).get("conductor") or {}
        status = conductor.get("status")
        if status == "running":
            return None
        if status == "succeeded":  # decided by another owner (e.g. the manual command): record it
            result = conductor.get("result") or {}
            moved = self._move(intent, COMPLETED, reason_code="conductor_decided_elsewhere",
                               decision={"id": conductor.get("id"), "status": status,
                                         "accepted": result.get("accepted"), "execution_ref": result.get("execution_ref")})
            return {"subject": moved["id"], "effect": "conductor_decided", "route": CONDUCTOR}
        if not (status in {None, "pending"} and int(conductor.get("attempt") or 0) == 0):
            moved = self._move(intent, RECOVERY_REQUIRED, reason_code="conductor_" + str(status),
                               next_owner=ROUTE_OWNERS[RECOVERY])
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        if int((intent.get("launch") or {}).get("sequence") or 0) >= MAX_LAUNCHES:
            moved = self._move(intent, REFUSED, reason_code="conductor_launch_exhausted", next_owner="conductor")
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        intent = self._authorize(ctx, intent)
        return self._dispatch(ctx, self._move(intent, INTENDED), job)

    def _resume_observe_delivery(self, ctx, intent, job):
        if job is None:
            return None
        return self._advance_delivery(intent, self.lanes(intent["lane"]).read(job, ctx["policy"]["delivery_target"]))

    def _resume_observe_research(self, ctx, intent, job):
        """Only the owner's stored scoped receipt for THIS intent releases the hold, and only after
        it is verified again against the current rows and lane evidence (a changed attempt, a new
        failure, a withdrawn dispatch result, an unreadable lane or evidence bytes that are now
        missing, unreadable, tampered or oversized keep the family held). A coarse
        `researched` disposition intersecting the family is evidence, never approval: it is not read
        here. The stored receipt is never edited; the intent's compare-and-swap completes it once."""
        with self.store.transaction() as tx:
            stored = tx.get(BUCKET_RESEARCH_RECEIPTS, intent["id"])
        if stored is None:
            return None
        receipt, coverage = self._recheck_receipt(ctx["policy"]["id"], ctx["sha"], intent, stored)
        moved = self._move(intent, COMPLETED, reason_code="research_receipt_accepted",
                           evidence_refs=list(receipt["evidence_refs"]), research_receipt=stored["receipt_sha256"],
                           research_coverage=coverage)
        return {"subject": moved["id"], "effect": "research_resolved", "route": RESEARCH}

    def _recheck_receipt(self, policy_id: str, sha: str, intent: dict, stored: dict, consumed: bool = False) -> tuple:
        """Every consumption check of one stored receipt, against the current rows, lane evidence and
        evidence bytes; returns (receipt, coverage). `consumed`: the research intent already completed
        on exactly this receipt (a capacity grant rechecking it), whose held attempt set is still the
        one the receipt was checked against."""
        receipt = stored.get("receipt")
        refuse(isinstance(receipt, dict) and receipt.get("intent_id") == intent["id"]
               and receipt.get("policy_id") == policy_id and receipt.get("policy_sha256") == sha,
               "research_policy_foreign", "operator", "policy")
        if receipt.get("schema") == MIXED_RECEIPT_SCHEMA:
            # A mixed-cause row answers only as the exact canonical document that was accepted.
            try:
                intact = validate_receipt(receipt) == receipt and digest(receipt) == stored.get("receipt_sha256")
            except ContinuationRefused:
                intact = False
            refuse(intact, "research_receipt_corrupt", ROUTE_OWNERS[RESEARCH], "receipt")
        facts = self._research_facts(receipt)
        facts.pop("stored")
        supplement = self._supplement_of(facts, receipt)
        self._require_recovery(facts)   # before the lane reads and before the hold is released
        if consumed:
            current = facts["intent"]
            refuse(isinstance(current, dict) and current.get("state") == COMPLETED
                   and current.get("research_receipt") == stored.get("receipt_sha256") == digest(receipt),
                   "research_receipt_corrupt", ROUTE_OWNERS[RESEARCH], "receipt")
            facts["intent"] = {**current, "state": RESEARCH_REQUIRED}   # the hold this receipt released
        facts["observed"] = self._observe_attempts(facts["jobs"])
        coverage = self._coverage(receipt, facts)
        # The coverage the receipt was accepted under, again: an original-capture receipt never
        # becomes a supplement one, and a supplement receipt needs the same immutable supplement.
        refuse(coverage == (stored.get("coverage") or COVERAGE_ORIGINAL)
               and (coverage != COVERAGE_SUPPLEMENT or supplement["supplement_sha256"] == stored.get("supplement_sha256")),
               "research_coverage_changed", ROUTE_OWNERS[RESEARCH], "supplement")
        self._verify_evidence(receipt_refs(receipt))
        if coverage == COVERAGE_SUPPLEMENT:
            self._verify_evidence([supplement["supplement"]["report_ref"], supplement["supplement"]["attestation_ref"]])
        return receipt, coverage

    def _resume_await_backlog(self, ctx, intent, job):
        return None  # the approved backlog owns the next item; nothing to do here

    # ----- durable intent writes ----------------------------------------------------------
    @staticmethod
    def _claim(tx, key: str, policy_id: str) -> tuple:
        """The slot of one observation for this policy: its own row (a replay), else the first free
        slot past foreign refusals that never owned an effect. A foreign row that owns an effect is
        never reused, advanced or reported as this policy's progress: `intent_owned_elsewhere`."""
        for n in range(MAX_SLOTS):
            slot = intent_slot(key, n)
            old = tx.get(BUCKET_INTENTS, slot)
            if old is None or old.get("policy_id") == policy_id:
                return slot, old
            refuse(effect_free(old), "intent_owned_elsewhere", "operator", "policy_id")
        raise ContinuationRefused("intent_slots_exhausted", "operator", "intent_id")

    def _create(self, fields: dict, attempt: dict, key: str | None = None) -> dict:
        """`key` is a slot `_claim` already resolved (the successor id is derived from it); it must
        still be free or this policy's own."""
        now = self.clock()
        transition(None, fields["state"])
        with self.store.transaction() as tx:
            if key is None:
                key, old = self._claim(tx, intent_id(fields["origin_job"], attempt, fields["evidence_sha256"],
                                                     fields["route"]), fields["policy_id"])
            else:
                old = tx.get(BUCKET_INTENTS, key)
                refuse(old is None or old.get("policy_id") == fields["policy_id"], "intent_owned_elsewhere",
                       "operator", "policy_id")
            if old is not None:
                return old  # the same observation again: a replay, never a second intent
            row = {"id": key, "successor_job": None, "evidence_refs": [], "session_mode": None, **fields,
                   **attempt, "version": 1, "created_at": now, "updated_at": now,
                   "history": [{"state": fields["state"], "reason_code": fields.get("reason_code"), "at": now}]}
            tx.put(BUCKET_INTENTS, key, row)
        self._emit(None, row)
        return row

    def _move(self, intent: dict, target: str, **fields) -> dict:
        """Compare-and-swap on the intent version; a moved intent raises `IntentChanged`."""
        with self.store.transaction() as tx:
            previous, current = self._apply(tx, intent, target, fields)
        self._emit(previous, current)
        return current

    def _apply(self, tx, intent: dict, target: str, fields: dict) -> tuple:
        """The compare-and-swap write inside an open control-store transaction (its own, or the
        Fleet's when the move commits together with an execution unit); the caller emits after."""
        current = tx.get(BUCKET_INTENTS, intent["id"])
        if current is None or current.get("version") != intent.get("version"):
            raise IntentChanged(intent["id"])
        previous = current["state"]
        current["state"] = transition(previous, target)
        now = self.clock()
        current.update({k: v for k, v in fields.items() if k != "error_type"}, version=current["version"] + 1,
                       updated_at=now)
        current["history"] = (current.get("history") or [])[-(MAX_HISTORY - 1):] + [
            {"state": target, "previous": previous, "reason_code": current.get("reason_code"),
             "error_type": fields.get("error_type"), "at": now}]
        tx.put(BUCKET_INTENTS, intent["id"], current)
        return previous, current

    def _note(self, intent: dict, *, emit: bool = False, **fields) -> dict:
        """The same compare-and-swap for a field of an unchanged state: launch evidence or a hold."""
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_INTENTS, intent["id"])
            if current is None or current.get("version") != intent.get("version"):
                raise IntentChanged(intent["id"])
            current.update(fields, version=current["version"] + 1, updated_at=self.clock())
            tx.put(BUCKET_INTENTS, intent["id"], current)
        if emit:
            self._emit(current["state"], current)
        return current

    def _emit(self, previous, row) -> None:
        """After the commit, through the existing Observer port: identifiers and codes only."""
        if self.observer is None:
            return
        common = {"intent_id": row["id"], "family": row["family"], "route": row["route"], "state": row["state"],
                  "origin_job": row["origin_job"], "successor_job": row.get("successor_job"),
                  "next_owner": str(row.get("next_owner") or "none"), "next_action": view(row)["next_action"]}
        reason = row.get("reason_code") if isinstance(row.get("reason_code"), str) else None
        hold = row.get("hold") if row["state"] in OPEN_STATES and isinstance(row.get("hold"), dict) else None
        if row["state"] in {RESEARCH_REQUIRED, RECOVERY_REQUIRED, PAUSED, REFUSED} or hold is not None:
            if hold is not None:
                reason = hold.get("reason_code") if isinstance(hold.get("reason_code"), str) else None
            self.observer.emit(EVENT_BLOCKED, "unknown" if row["state"] == RECOVERY_REQUIRED else "blocked",
                               severity="warning", reason_code=_code(reason), attributes=common)
            return
        self.observer.emit(EVENT_TRANSITION, "observed", reason_code=_code(reason),
                           attributes={**common, "previous_state": previous})


def _code(reason):
    if not isinstance(reason, str):
        return None
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in reason)[:80]
    return cleaned if cleaned[:1].isalpha() else None


__all__ = ["BUCKET_CAPACITY_GRANTS", "BUCKET_INTENTS","BUCKET_POLICIES", "BUCKET_PROGRESS", "BUCKET_RESEARCH_RECEIPTS",
           "BUCKET_RESEARCH_SUPPLEMENTS", "LANE_BINDINGS",
           "Continuation", "IntentChanged", "LaneEvidence"]
