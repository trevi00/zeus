"""Owner research receipts and scope supplements.

Layer: application
Context: coordination
Owns: buckets continuation_research_receipts, continuation_research_supplements
Does not own: the research rows it reads (research, intake), the evidence bytes (the evidence port)
Entry points: ResearchAcceptance
Contracts: INV-CONTINUATION-001, INV-RESEARCH-ATTEMPT-SCOPE-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.state import (
    BUCKET_BINDINGS,
    BUCKET_INTENTS,
    BUCKET_POLICIES,
    BUCKET_RESEARCH_RECEIPTS,
    BUCKET_RESEARCH_SUPPLEMENTS,
    FLEET_JOBS,
    INVESTIGATIONS,
    MAX_LINEAGE,
    PROMOTIONS,
    RESEARCH_DISPATCHES,
    RESEARCH_HEADS,
    RESEARCH_RECOVERIES,
    RESEARCH_RUNS,
    RESEARCH_SUCCESSORS,
)
from codex_harness.coordination.application.execution_fence import current as current_fence
from codex_harness.coordination.domain.continuation import (
    ATTEMPT_SCOPE_PREFIX,
    COMPLETED,
    COVERAGE_MIXED,
    COVERAGE_ORIGINAL,
    COVERAGE_SUPPLEMENT,
    MIXED_RECEIPT_SCHEMA,
    RESEARCH,
    RESEARCH_REQUIRED,
    ROUTE_OWNERS,
    ContinuationRefused,
    attempt_scope_id,
    check_mixed_receipt,
    check_research_receipt,
    check_scope_supplement,
    observed_attempt,
    receipt_refs,
    receipt_view,
    refuse,
    research_attempts,
    supplement_view,
    validate_receipt,
    validate_scope_supplement,
)
from codex_harness.kernel.ids import digest, utcnow
from codex_harness.research.domain.research_investigations import (
    REVOCATION_BUCKET,
    current_dispatch_id,
    revocation_held,
    revocation_task_id,
    successor_held,
    successor_key,
    successor_reads,
)
from codex_harness.research.domain.research_program import council_result


class ResearchAcceptance:
    """The owner research receipts and scope supplements: authoritative reads, evidence
    verification and the one-unit acceptance, and the recheck every consumption repeats."""

    def __init__(self, store, *, clock=utcnow, evidence=None, lanes=None):
        self.store = store
        self.clock = clock
        self.evidence = evidence
        self.lanes = lanes

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
        self.verify_evidence(receipt_refs(receipt))
        if coverage == COVERAGE_SUPPLEMENT:
            self.verify_evidence([supplement["supplement"]["report_ref"], supplement["supplement"]["attestation_ref"]])
        now = self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_RESEARCH_RECEIPTS, receipt["intent_id"])
            if old is not None:
                refuse(old.get("receipt") == receipt, "research_receipt_conflict", "operator", "intent_id")
            # The retained fence again in THIS writer transaction (never a nested one): a concurrent
            # insertion, or a fence lost since the read, never returns acceptance.
            self._require_recovery({"recovery_held": self._held(tx, receipt)})
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
        self.verify_evidence([supplement["report_ref"], supplement["attestation_ref"]])
        now = self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_RESEARCH_SUPPLEMENTS, supplement["intent_id"])
            if old is not None:
                refuse(old.get("supplement") == supplement, "research_supplement_conflict", "operator", "intent_id")
            self._require_recovery({"recovery_held": self._held(tx, supplement)})
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
            if str(receipt["investigation"]).startswith(ATTEMPT_SCOPE_PREFIX):
                # INV-RESEARCH-ATTEMPT-SCOPE-001: an attempt-scope claim is its own current dispatch; it has
                # no recovery or successor, so no recovery or head row ever redirects it.
                dispatch = tx.get(RESEARCH_DISPATCHES, receipt["investigation"])
            else:
                # The CURRENT dispatch of the investigation: after an owner-authorized recovery that is
                # the replacement (research-dispatch-recovery-001), so a receipt naming the failed
                # original, or a result of its run, can never approve.
                # A settled read-only successor head names the current one after that; a stale receipt
                # naming a predecessor then mismatches, and a broken retained chain holds.
                recovery = tx.get(RESEARCH_RECOVERIES, receipt["investigation"])
                dispatch = tx.get(RESEARCH_DISPATCHES, current_dispatch_id(
                    receipt["investigation"], recovery, tx.get(RESEARCH_HEADS, receipt["investigation"])))
            recovery_held = self._held(tx, receipt)
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

    def _held(self, tx, receipt: dict) -> str | None:
        """The named held condition of one receipt's (or supplement's) binding, read through the
        caller's open transaction: its intent's attempt-scope claim, else its investigation's lineage."""
        return self._scope_held(tx, receipt) or self._recovery_held(tx, receipt["investigation"])

    @staticmethod
    def _scope_held(tx, receipt: dict) -> str | None:
        """INV-RESEARCH-ATTEMPT-SCOPE-001: once an attempt-scope claim exists for the intent, in ANY state
        (a scoped failure is final), it is the ONLY identity a receipt, supplement or owner binding of
        that intent may name: any other (a family, a recovery, another scope) holds as `scope_claimed`.
        With no claim this is None and nothing else changes."""
        try:
            scope = attempt_scope_id(receipt.get("intent_id"))
        except ContinuationRefused:
            return None     # not an intent id: no scope can be claimed for it; the checks refuse it by name
        if receipt.get("investigation") == scope or tx.get(RESEARCH_DISPATCHES, scope) is None:
            return None
        return "scope_claimed"

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

    def verify_evidence(self, refs) -> None:
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

    def recheck_receipt(self, policy_id: str, sha: str, intent: dict, stored: dict, consumed: bool = False) -> tuple:
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
        self.verify_evidence(receipt_refs(receipt))
        if coverage == COVERAGE_SUPPLEMENT:
            self.verify_evidence([supplement["supplement"]["report_ref"], supplement["supplement"]["attestation_ref"]])
        return receipt, coverage
