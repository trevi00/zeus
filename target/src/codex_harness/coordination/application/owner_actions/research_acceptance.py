"""G1 scoped research acceptance.

Layer: application
Context: coordination
Owns: the assessor decision row (decisions_pending) inside the
    action's unit
Does not own: the receipt (Continuation research acceptance), the guardian (assessments)
Entry points: ResearchAcceptanceFamily
Contracts: INV-OWNER-ACTIONS-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_DISPATCHES,
    CONTINUATION_INTENTS,
    CONTINUATION_RECEIPTS,
    DECISIONS,
    FLEET_JOBS,
    LAUNCH_ABSENT,
    LAUNCH_EXITED,
    LAUNCH_RUNNING,
    LAUNCH_UNKNOWN,
    _decided,
)
from codex_harness.coordination.domain.continuation import (
    MIXED_RECEIPT_SCHEMA,
    RESEARCH_RECEIPT_SCHEMA,
    RESEARCH_REQUIRED,
    SHA256,
    ContinuationRefused,
    attempt_scope_id,
    observed_attempt,
    research_attempts,
)
from codex_harness.coordination.domain.owner_actions import (
    ASSESSED,
    ASSESSING,
    ASSESSMENT_ACTION,
    ASSESSMENT_SENDER,
    ASSESSOR,
    COMPLETED,
    EVIDENCE_REF,
    INTENDED,
    INVOKING,
    MAX_ASSESSMENT_LAUNCHES,
    OWNER_PHASE,
    REFUSED,
    REJECTED,
    UNKNOWN,
    VERDICT_ACCEPTED,
    VERDICT_REJECTED,
    VERDICT_UNKNOWN,
    OwnerActionRefused,
    assemble_receipt,
    assessment_decision_id,
    assessment_document,
    assessment_input,
    assessment_launch_id,
    assessment_verdict,
    dispatch_acceptance,
    lineage_edges,
    research_binding,
    reusable_assessment,
)
from codex_harness.intake.domain.portfolio import family_id
from codex_harness.kernel.ids import digest
from codex_harness.kernel.message import envelope
from codex_harness.research.domain.research_attempt_scope import check_scope_capture


class ResearchAcceptanceFamily:
    """G1: the independent scoped assessment of a held research family and the receipt it assembles."""

    def __init__(self, store, *, assessments=None, continuation=None, lanes=None, org=None,
                 message_clock=None, ids=None, actions=None):
        self.store = store
        self.assessments = assessments
        self.continuation = continuation
        self.lanes = lanes
        self.org = org
        self.message_clock = message_clock
        self.ids = ids
        self.actions = actions

    # ===== G1: scoped research acceptance ===========================================================
    def research_binding(self, continuation: dict, intent: dict, intents: list) -> dict:
        """The exact receipt binding of one held intent, from the continuation's own readers. A family
        whose accepted research is not there yet, ambiguous, or needs an owner scope supplement is a
        named wait (raised), never a guess."""
        if self.lanes is None:
            raise OwnerActionRefused("lanes_unconfigured", "lanes")
        attempts = research_attempts(intents, intent)
        scope = attempt_scope_id(intent["id"]) if type(intent.get("id")) is str and SHA256.fullmatch(intent["id"]) \
            else None
        with self.store.transaction() as tx:
            jobs = {a["job"]: tx.get(FLEET_JOBS, a["job"]) for a in attempts}
            # A dispatch an earlier receipt of this family already consumed is that hold's history: the
            # completed research reset the family's count, so it never covers a later attempt set.
            consumed = {((r.get("receipt") or {}).get("investigation"),
                         ((r.get("receipt") or {}).get("dispatch") or {}).get("run_id"))
                        for r in tx.scan(CONTINUATION_RECEIPTS)
                        if r.get("id") != intent["id"] and (r.get("receipt") or {}).get("family") == intent["family"]}
            claimed = scope is not None and tx.get(BUCKET_DISPATCHES, scope) is not None
        if not all(isinstance(job, dict) for job in jobs.values()):
            raise OwnerActionRefused("research_attempt_unavailable", "attempts")
        causes = {job_id: (job.get("status"), job.get("reason_code")) for job_id, job in jobs.items()}
        members = sorted(jobs)
        candidates = []
        # INV-RESEARCH-ATTEMPT-SCOPE-001: once this intent's attempt scope is claimed it is the intent's ONLY
        # research identity (schema 1, original capture): a historical family dispatch naming the same jobs
        # never covers it, and a pending or failed scope never falls back to one.
        names = [scope] if claimed else sorted({family_id(*cause) for cause in causes.values()})
        for investigation in names:
            facts = self.continuation.research_facts({
                "schema": RESEARCH_RECEIPT_SCHEMA, "policy_id": continuation["id"], "intent_id": intent["id"],
                "investigation": investigation, "attempts": [{"job": job} for job in members]})
            if facts.get("recovery_held") is not None:
                raise OwnerActionRefused("research_" + str(facts["recovery_held"]), "dispatch")
            dispatch = facts.get("dispatch")
            if isinstance(dispatch, dict) and dispatch.get("state") == "resolved" \
                    and (investigation, dispatch.get("run_id")) not in consumed \
                    and dispatch.get("result") == VERDICT_ACCEPTED \
                    and (facts.get("run_result") or {}).get("result") == VERDICT_ACCEPTED \
                    and set(members) & set(dispatch.get("job_ids") or []):
                candidates.append((investigation, facts))
        if not candidates:
            raise OwnerActionRefused("research_dispatch_pending", "dispatch")
        if len(candidates) > 1:
            raise OwnerActionRefused("research_dispatch_ambiguous", "dispatch")
        investigation, facts = candidates[0]
        dispatch = facts["dispatch"]
        if claimed:
            # Exactly this intent's scope and current attempt pairs, members of the one cause it captured: never
            # a mixed receipt, and never widened by an owner supplement (named waits, not an assessment).
            if not check_scope_capture(dispatch, intent_id=intent["id"], attempts=attempts):
                raise OwnerActionRefused("research_scope_capture_mismatch", "dispatch")
            if set(causes.values()) != {(dispatch.get("family_status"), dispatch.get("reason_code"))}:
                raise OwnerActionRefused("research_scope_membership", "attempts")
        mixed = not claimed and len({family_id(*cause) for cause in causes.values()}) > 1
        if not mixed and not set(members) <= set(dispatch.get("job_ids") or []):
            # A partial capture needs the owner's typed scope supplement; this coordinator never writes one.
            raise OwnerActionRefused("research_scope_supplement_required", "dispatch")
        observed = {job_id: observed_attempt(job, self.lanes(job["lane"]).read(job)) for job_id, job in jobs.items()}
        rows = []
        for attempt in attempts:
            entry = {"job": attempt["job"], "evidence_sha256": attempt["evidence_sha256"],
                     "inspection": observed[attempt["job"]]["inspection"]}
            if mixed:
                status, reason = causes[attempt["job"]]
                entry.update(investigation=family_id(status, reason), status=status, reason_code=reason)
            rows.append(entry)
        binding = research_binding(intent, continuation, rows, investigation,
                                   {**dispatch, "id": dispatch.get("id", dispatch.get("investigation"))},
                                   MIXED_RECEIPT_SCHEMA if mixed else RESEARCH_RECEIPT_SCHEMA)
        return {"binding": binding, "facts": facts, "intents": intents, "intent": intent,
                "members": [{"job": job, "status": causes[job][0], "reason_code": causes[job][1],
                             "inspection": observed[job]["inspection"]} for job in members]}

    def _current_research(self, continuation: dict, action: dict) -> dict:
        """The binding recomputed NOW; an action whose binding moved on is refused, never re-pointed."""
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, action["subject"]["intent_id"])
            intents = [r for r in tx.scan(CONTINUATION_INTENTS) if r.get("policy_id") == continuation["id"]]
        if not (isinstance(intent, dict) and intent.get("state") == RESEARCH_REQUIRED):
            raise OwnerActionRefused("research_intent_not_held", "intent_id")
        found = self.research_binding(continuation, intent, intents)
        if found["binding"] != action["binding"]:
            raise OwnerActionRefused("research_binding_changed", "binding")
        return found

    def advance(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        state = action["state"]
        if state == INTENDED:
            return self._begin_assessment(policy_row, continuation, action)
        if state == ASSESSING:
            return self._observe_assessment(action)
        if state == ASSESSED:
            return self._assemble(continuation, action)
        if state == INVOKING:
            return self._invoke(action)
        return None

    def _begin_assessment(self, policy_row: dict, continuation: dict, action: dict) -> dict:
        with self.store.transaction() as tx:
            decisions = [d for d in tx.scan(DECISIONS) if d.get("phase") == OWNER_PHASE]
        reused = reusable_assessment(decisions, action)
        if reused is not None:
            # An executed independent assessment already binds exactly this action: no new call. It is
            # promoted only through the same bound launch outcome as a fresh one (R1): the verdict is
            # kept as `decided` evidence and never asked for again.
            if self.assessments is None:
                raise OwnerActionRefused("assessor_unconfigured", "assessments")
            verdict = assessment_verdict(reused, action)
            bound = self._reused_launch(action, reused)
            if bound is None:
                return self.actions.effect(self.actions.move(action, UNKNOWN, "assessment_execution_unbound",
                                               decided=_decided(verdict), decision_id=reused["id"], reused=True))
            sequence, launch_id = bound
            row = self.actions.move(action, ASSESSING, "assessment_reused", decided=_decided(verdict),
                             decision_id=reused["id"], launches=sequence, launch_id=launch_id, reused=True)
            return self._observe_assessment(row) or self.actions.effect(row)
        if self.assessments is None or self.org is None:
            raise OwnerActionRefused("assessor_unconfigured", "assessments")
        try:
            found = self._current_research(continuation, action)
        except OwnerActionRefused as exc:
            return self.actions.effect(self.actions.move(action, REFUSED, exc.reason_code))
        context = self.assessments.context(action["binding"], found)
        if not isinstance(context, dict) or not isinstance(context.get("report"), str):
            # The assessor would judge nothing: the report bytes it must read are not there.
            return self.actions.effect(self.actions.move(action, UNKNOWN, "assessment_context_unavailable"))
        decision_id = assessment_decision_id(action["id"])
        launch = assessment_launch_id(action["id"], 1)
        data = assessment_input(action, context)
        message = envelope("review.result", ASSESSMENT_SENDER, ASSESSOR, ASSESSMENT_ACTION,
                           {"owner_action": action["id"], "binding_sha256": action["binding_sha256"]}, action["id"],
                           clock=self.message_clock, ids=self.ids)  # R6: the S5 envelope seam
        self.org.authorize(message)

        def request(tx):
            # The ONE decision row, written with the intent in the same transaction: a crash leaves
            # both or neither, and the decision id is the action's own, so a replay never adds a row.
            old = tx.get(DECISIONS, decision_id)
            if old is None:
                tx.put(DECISIONS, decision_id, {"id": decision_id, "actor": ASSESSOR, "phase": OWNER_PHASE,
                                                "input": data, "message": message, "status": "pending",
                                                "attempt": 0})
            elif (old.get("input") or {}).get("binding_sha256") != action["binding_sha256"]:
                raise OwnerActionRefused("assessment_identity_conflict", "decision_id")

        row = self.actions.move(action, ASSESSING, "assessment_scheduled", extra=request, decision_id=decision_id,
                         launches=1, launch_id=launch, correlation_id=message["correlation_id"])
        self.assessments.start(launch, decision_id, message["correlation_id"])
        return self.actions.effect(row)

    def _observe_assessment(self, action: dict) -> dict | None:
        with self.store.transaction() as tx:
            decision = tx.get(DECISIONS, action["decision_id"])
        verdict = assessment_verdict(decision, action)
        if self.assessments is None:
            return None
        launch = self.assessments.poll(action["launch_id"])
        if verdict["verdict"] is not None:
            return self._settle_assessment(action, verdict, launch)
        state = launch.get("state")
        if state == LAUNCH_RUNNING:
            return None
        if state == LAUNCH_UNKNOWN or launch.get("cleanup_confirmed") is False:
            # The guardian ended without proving its cleanup: an unknown effect, never a relaunch.
            return self.actions.effect(self.actions.move(action, UNKNOWN, "assessment_launch_unknown"))
        never_entered = isinstance(decision, dict) and decision.get("status") == "pending" \
            and int(decision.get("attempt") or 0) == 0
        if never_entered and int(action.get("launches") or 0) < MAX_ASSESSMENT_LAUNCHES:
            # Proven ended (or fenced) without claiming the decision: ONE more bounded launch.
            sequence = int(action["launches"]) + 1
            launch_id = assessment_launch_id(action["id"], sequence)
            row = self.actions.move(action, ASSESSING, "assessment_relaunched", launches=sequence, launch_id=launch_id)
            self.assessments.start(launch_id, action["decision_id"], action["correlation_id"])
            return self.actions.effect(row)
        return self.actions.effect(self.actions.move(action, ASSESSED, "assessment_unfinished", verdict=VERDICT_UNKNOWN))

    def _settle_assessment(self, action: dict, verdict: dict, launch: dict) -> dict | None:
        """A decided assessment is promoted only on ONE authoritative bound execution outcome (R1): its
        guardian's cleanup proof, whose exit code is the assess child's own ownership and call-ledger
        settlement result. A success persisted while the launch still runs waits; unknown cleanup, a
        timeout, an unsettled or unowned execution, or no bound execution at all ends as a named unknown
        that keeps the verdict as `decided` evidence and never asks the model again."""
        decided = _decided(verdict)
        state = launch.get("state")
        if state == LAUNCH_RUNNING:
            if action.get("decided") == decided:
                return None
            return self.actions.effect(self.actions.move(action, ASSESSING, "assessment_awaiting_cleanup", decided=decided))
        if state == LAUNCH_UNKNOWN or launch.get("cleanup_confirmed") is not True:
            reason = "assessment_execution_unbound" if state == LAUNCH_ABSENT else "assessment_launch_unknown"
        elif state != LAUNCH_EXITED:
            reason = "assessment_launch_timeout"
        elif launch.get("exit_code") != 0:
            reason = "assessment_settlement_unresolved"
        else:
            return self.actions.effect(self.actions.move(action, ASSESSED, verdict["reason_code"], verdict=verdict["verdict"],
                                           execution_ref=verdict.get("execution_ref"), decided=decided))
        return self.actions.effect(self.actions.move(action, UNKNOWN, reason, decided=decided))

    def _reused_launch(self, action: dict, decision: dict) -> tuple | None:
        """The one launch of this action that executed `decision`: only the action's own decision row has
        launch identities; exactly one of them may have entered. Anything else is no bound execution."""
        if decision.get("id") != assessment_decision_id(action["id"]):
            return None
        entered = []
        for sequence in range(1, MAX_ASSESSMENT_LAUNCHES + 1):
            launch_id = assessment_launch_id(action["id"], sequence)
            if self.assessments.poll(launch_id).get("state") != LAUNCH_ABSENT:
                entered.append((sequence, launch_id))
        return entered[0] if len(entered) == 1 else None

    def _assemble(self, continuation: dict, action: dict) -> dict:
        verdict = action.get("verdict")
        if verdict == VERDICT_REJECTED:
            return self.actions.effect(self.actions.move(action, REJECTED, action.get("reason_code") or "assessment_rejected"))
        if verdict != VERDICT_ACCEPTED:
            return self.actions.effect(self.actions.move(action, UNKNOWN, action.get("reason_code") or "assessment_unknown"))
        try:
            found = self._current_research(continuation, action)
        except OwnerActionRefused as exc:
            return self.actions.effect(self.actions.move(action, REFUSED, exc.reason_code))
        if self.assessments is None:
            raise OwnerActionRefused("assessor_unconfigured", "assessments")
        document = assessment_document(action, {"verdict": verdict, "decision_id": action["decision_id"],
                                                "execution_ref": action["execution_ref"]})
        reference = self.assessments.document(document)
        facts = found["facts"]
        report = ((facts.get("acceptance") or {}).get("run") or {}).get("report") or {}
        refs = [ref for ref in (report.get("execution_ref"), action["execution_ref"])
                if type(ref) is str and EVIDENCE_REF.fullmatch(ref)]
        binding = action["binding"]
        extras = {}
        if binding["schema"] == MIXED_RECEIPT_SCHEMA:
            members = [a["job"] for a in binding["attempts"]]
            captured = sorted(set(members) & set((facts.get("dispatch") or {}).get("job_ids") or []))
            acceptance = facts.get("acceptance") or {}
            extras = {"captured": captured,
                      "lineage": lineage_edges(members, captured, found["intents"], found["intent"]),
                      "acceptance": dispatch_acceptance(acceptance.get("run"), acceptance.get("promotion"),
                                                        acceptance.get("task"))}
        receipt = assemble_receipt(binding, evidence_refs=refs, assessment_ref=reference, **extras)
        row = self.actions.move(action, INVOKING, "receipt_assembled", receipt=receipt, receipt_sha256=digest(receipt),
                         assessment_ref=reference)
        return self._invoke(row)

    def _invoke(self, action: dict) -> dict:
        """The existing validated API with the persisted receipt; a replay is its identical, cached call."""
        try:
            result = self.continuation.accept_research(action["receipt"])
        except ContinuationRefused as exc:
            return self.actions.effect(self.actions.move(action, REFUSED, exc.reason_code))
        return self.actions.effect(self.actions.move(action, COMPLETED, "research_receipt_accepted",
                                       accepted={"cached": result.get("cached"),
                                                 "receipt_sha256": result.get("receipt_sha256"),
                                                 "coverage": result.get("coverage")}))
