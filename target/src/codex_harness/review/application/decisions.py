"""ReviewDecisions: one claimed decision -> reviewer verdict -> the decision commit unit (REBUILD-DESIGN-v2 §2.9).

Layer: application
Context: review
Owns: ReviewDecisions.decide (M7 `Executor.decide_one` after the claim transaction) and the unit it commits
    (`_commit_decision`), with `_review_hook`, `_recovered_effect`, the failure disposition, the reconciliation
    block and `_session_review` (M7 `adapters/executor.py:1688-1850, 1524-1650, 1857-1969, 562-575`). The bodies
    are M7's; every non-owner write or fence goes through the owner's tx-taking operation behind a port this
    context declares (DESIGN-review-decisions §1-§2); release_queue and improvement_loops are review's own writes
Does not own: the claim (coordination `claim_decision`; coordination's TaskRunner hands over the claimed row);
    the provider call (execution, `VerdictInvoker`); audit/threshold reviews (S8, injected; unwired refuses)
Entry points: ReviewDecisions.decide
Contracts: INV-RELEASE-001, INV-SESSION-001, INV-OBSERVATION-001, INV-RESEARCH-004, INV-RECURRENCE-001

The single transaction per unit (§2.9 rule 2) is opened here, and only here; the owner operations join it. The
lease fence is re-checked at the start of the unit and again before the terminal write, where M7 does so (rule 3).
The reviewer invocation happens at depth 0 (rule 4).
"""

from __future__ import annotations

from codex_harness.kernel.errors import ContractError, ExecutionFailure, require
from codex_harness.kernel.ids import digest, utcnow
from codex_harness.kernel.message import envelope
from codex_harness.kernel.policy import POLICY


def _threshold_review_unwired(lease):
    raise ContractError("Threshold review is not wired")  # S8 supplies it; never a silent default


class ReviewDecisions:
    """The decision use case. Constructor-injected owners; no state beyond them (one instance per process)."""

    def __init__(self, store, organization, *, ownership, failures, outbox, events, releases, hooks, observer,
                 invoker, git, release_policy, ticket_binding, TicketSuperseded, require_dispatch,
                 ReconciliationRequired, PostExecutionRecordFailure, worker_sessions=None, audit_execution=None,
                 threshold_review=_threshold_review_unwired, clock=None, ids=None):
        # `observer` satisfies review.ports ObservationMarkers and ObservationAudit (one Observer, S4 moved ahead).
        self.store, self.organization = store, organization
        self.ownership, self.failures, self.outbox, self.events = ownership, failures, outbox, events
        self.releases, self.hooks, self.observer, self.invoker, self.git = releases, hooks, observer, invoker, git
        self.release_policy, self.ticket_binding, self.TicketSuperseded = release_policy, ticket_binding, TicketSuperseded
        self.require_dispatch = require_dispatch
        self.ReconciliationRequired, self.PostExecutionRecordFailure = ReconciliationRequired, PostExecutionRecordFailure
        self.worker_sessions, self.audit_execution, self.threshold_review = worker_sessions, audit_execution, threshold_review
        self.clock, self.ids = clock, ids

    def decide(self, agent: str, decision: dict) -> dict | None:
        """Run the reviewer for a decision `claim_decision` returned, and commit its verdict (M7 decide_one)."""
        try:
            phase, data = decision["phase"], decision["input"]
            lease = {**decision, "_bucket": "decisions_pending"}
            cwd = str(self.git.repository)
            if phase == 'audit_review':
                require(self.audit_execution is not None, 'Audit executor unavailable')
                return self.audit_execution.review(lease)
            if phase == 'threshold_review':
                return self.threshold_review(lease)
            if phase.startswith("review_"):
                candidate = data["candidate"]
                inspected = self.git.inspect(candidate["revision"], candidate["base"])
                cwd = self.git.review_workspace(candidate["revision"], decision["id"])
                data = {**data, "independent_diff": inspected}
            result = self.invoker.invoke(agent, decision["id"], "Evaluate " + phase + ". Assess Google SRE "
                                         "reliability, arc42 architecture impact, existing graph/contracts, measurable benefit, "
                                         "evidence and rollback. Accept only when justified. For diagnosis, confirm a root "
                                         "cause only from evidence, never from generic error similarity; reuse a known cause "
                                         "ID only when the cause and scope are the same.", data, cwd,
                                         "diagnosis" if phase == "diagnose" else "verdict", True,
                                         heartbeat=lambda: self.ownership.heartbeat(lease), lease=lease,
                                         workload="design" if phase == "diagnose" else "final_validation")
            if phase.startswith("review_"):
                require(not self.git._git("status", "--porcelain", cwd=cwd), "Reviewer modified its checkout")
                require(self.git._git("rev-parse", "HEAD", cwd=cwd) == data["candidate"]["revision"],
                        "Reviewer changed its commit")
            if result.get("inspection_blocked"):
                # INV-RELEASE-001: blockage cannot create reviews or downstream effects.
                result = {**result, "accepted": False}
                with self.store.transaction() as tx:
                    current = self.ownership.owned(tx, lease)
                    self.ownership.validate(tx, current)
                    self._recovered_effect(current, agent, phase, data)
                    current.update(status="inspection_blocked", result=result, completed_at=utcnow(self.clock))
                    self.ownership.record(tx, current)
                    self.observer.close_unconfirmed(tx, lease, "accepted")  # a recorded terminal outcome
                    self.ownership.notice(tx, current, 'inspection_blocked', utcnow(self.clock))
                return current
            if result.get("blocked"):
                require(not result["accepted"], "Blocked review cannot approve")
                with self.store.transaction() as tx:
                    current = self.ownership.owned(tx, lease)
                    self.ownership.validate(tx, current)
                    self._recovered_effect(current, agent, phase, data)
                    current.update(status="blocked", result=result, completed_at=utcnow(self.clock))
                    self.ownership.record(tx, current)
                    self.observer.close_unconfirmed(tx, lease, "accepted")  # a recorded terminal outcome
                    self.ownership.notice(tx, current, 'decision_blocked', utcnow(self.clock))
                return current
            current = self._commit_decision(decision, agent, phase, data, result, lease)
            self._session_review(phase, data, current)
            return current
        except self.ReconciliationRequired as exc:
            return self._block_for_reconciliation({**decision, "_bucket": "decisions_pending"}, agent, exc)
        except self.PostExecutionRecordFailure as exc:
            return self._fail_decision({**decision, "_bucket": "decisions_pending"}, agent, exc, block=[exc.record_id])
        except Exception as exc:
            lease = {**decision, "_bucket": "decisions_pending"}
            error, disposition = self._failure_disposition(lease, exc)
            return self._fail_decision(lease, agent, error, **disposition)

    def _session_review(self, phase, data, current) -> None:
        """After the decision committed (never inside its transaction): the session owner reads the
        committed review row itself. Best effort: the continuation controller records the same
        decision idempotently on its next tick, so a refusal or outage here changes no outcome."""
        if self.worker_sessions is None or phase != "review_lead" or (current or {}).get("status") != "succeeded":
            return
        continuation = ((data.get("origin") or {}).get("continuation") or {}) if isinstance(data, dict) else {}
        session = continuation.get("session") if isinstance(continuation, dict) else None
        if not isinstance(session, dict) or type(session.get("task_id")) is not str:
            return
        try:
            self.worker_sessions.record_review(session["task_id"], current["id"])
        except Exception:
            pass

    def _failure_disposition(self, lease, exc):
        """INV-OBSERVATION-001: how a failure outside `_run` closes or keeps this attempt's marker.

        No open marker: nothing was reserved, an ordinary retry. An open marker with a
        runner-observed output failure or a contract rejection of an already persisted answer:
        the outcome was observed, the marker closes with the failure record and the retry stays.
        Anything else with an open marker (an acceptance write, a workspace capture, a decision
        commit that failed) cannot prove the effects were accepted: the attempt is blocked, and the
        failure is published under the same boundary/type/digest wording as failures inside `_run`;
        the foreign exception text never reaches the task row, the CLI or the diagnosis request.
        A sink read that fails here is treated as unknown, which blocks.
        """
        try:
            pending = self.observer.pending_terminations(lease["id"], strict=True)
        except Exception:
            pending = [{"record_id": self.observer.termination_id(lease)}]
        if not pending:
            return exc, {}
        if isinstance(exc, (ExecutionFailure, ContractError)):
            return exc, {"closure": "observed_failure"}
        record_id = self.observer.record_termination(
            lease, reservation_id=None, classification="unknown", stream_hash=None, error=exc, boundary="acceptance")
        return self.PostExecutionRecordFailure(record_id, exc, "acceptance"), {"block": [record_id]}

    def _record_reconciliation_block(self, tx, bucket, lease, agent, current, record_ids):
        event = {"type": "execution.reconciliation_required", "bucket": bucket, "task_id": lease["id"],
                 "generation": current.get("generation", 0), "attempt": current.get("attempt"),
                 "records": list(record_ids)}
        identity = digest(event)
        if tx.get("events", identity) is None:
            self.events.append(tx, identity, {**event, "at": utcnow(self.clock)})  # coordination owns `events`
        # The lead learns about the block through the existing informational notice path
        # (execution.notice → outbox), not through the observation record.
        self.ownership.notice(tx, current, 'reconciliation_required', utcnow(self.clock), identity)
        self.observer.audit(tx, "development.reconciliation_required", "blocked",
                            identity=["reconciliation_required", bucket, lease["id"], current.get("generation"),
                                      current.get("attempt")],
                            execution=self.observer.for_lease(lease, role=agent),
                            correlation_id=self.observer.correlation(lease), causation_id=lease["id"],
                            reason_code="reconciliation_required", severity="critical",
                            attributes={"terminations": len(record_ids), "record_id": str(record_ids[0])})

    def _block_for_reconciliation(self, lease, agent, exc):
        """INV-OBSERVATION-001: no provider ran; the execution stops until an operator reconciles."""
        bucket = lease.get("_bucket", "tasks")
        try:
            with self.store.transaction() as tx:
                current = self.ownership.owned(tx, lease)
                current.update(status="blocked", error="reconciliation_required", lease_until=None, lease_owner=None)
                self.ownership.record(tx, current)
                self._record_reconciliation_block(tx, bucket, lease, agent, current,
                                                  [row.get("record_id") for row in exc.records])
                return current
        except ContractError as failure:
            return self._lost_execution(lease, exc, failure)

    def _lost_execution(self, lease, error, rejection_error=None):
        # INV-SESSION-001: a stale executor cannot publish failure or diagnosis.
        contained = self.failures.contain_time(lease, rejection_error) or self.failures.contain_time(lease, error)
        if contained is not None:
            return contained
        return self.failures.reconcile(lease, error, rejection_error)

    def _fail_decision(self, lease, agent, error, *, block=None, closure=None):
        try:
            with self.store.transaction() as tx:
                current = self.failures.fail(tx, lease, error)
                if closure:
                    self.observer.close_unconfirmed(tx, lease, closure)
                if block and current.get("status") == "retry":
                    current.update(status="blocked", error="reconciliation_required")
                    self.ownership.record(tx, current)
                    self._record_reconciliation_block(tx, "decisions_pending", lease, agent, current, block)
                return current
        except ContractError as failure:
            return self._lost_execution(lease, error, failure)

    @staticmethod
    def _recovered_effect(current, agent, phase, data):
        if current.get('recovery_receipt'):
            effect_input = {k: v for k, v in data.items() if k != 'independent_diff'}
            require(current['actor'] == agent and current['phase'] == phase
                    and effect_input == current['input'], 'Recovered decision effect input changed')

    def _commit_decision(self, decision, agent, phase, data, result, lease):
        # INV-SESSION-001 / INV-RELEASE-001: all effects commit under the same
        # current lease. A failure cannot leave a review, hook or deploy request behind.
        with self.store.transaction() as tx:
            current = self.ownership.owned(tx, lease)
            self.ownership.validate(tx, current)
            self._recovered_effect(current, agent, phase, data)
            try:
                self.ticket_binding(tx, data)
            except self.TicketSuperseded as exc:
                current.update(status="superseded", result=result, error=str(exc), completed_at=utcnow(self.clock))
                self.ownership.record(tx, current)
                self.observer.close_unconfirmed(tx, lease, "accepted")  # a recorded terminal outcome
                self.ownership.notice(tx, current, 'ticket_superseded', utcnow(self.clock))
                return current
            message = decision["message"]
            next_message = None
            if phase == "diagnose" and result["confirmed"]:
                incident = envelope("incident.report", data["source_actor"], agent, "record_incident",
                                    {"occurrence_id": data["occurrence_id"], "root_cause": result["root_cause"],
                                     "scope": result["scope"], "evidence_refs": [data["evidence_ref"], result["execution_ref"]]},
                                    message["correlation_id"], message["message_id"], clock=self.clock, ids=self.ids)
                self.hooks.record_incident(incident,
                                           independent_occurrence=data.get("source_task_id"), transaction=tx)
            elif phase == "research_lead" and result["accepted"]:
                self.require_dispatch({"proposal": data})
                result["proposal"] = data
                next_message = envelope("review.result", agent, "conductor", "assess_research",
                                        {"decision_id": decision["id"], "result": result},
                                        message["correlation_id"], message["message_id"], clock=self.clock, ids=self.ids)
            elif phase == "proposal" and result["accepted"]:
                self.require_dispatch({"proposal": data})
                next_message = self.ownership.next_message(message, agent, "lead:improvement", "plan",
                                                           {"proposal": data, "approval": result})
                next_message["where"]["revision"] = result["basis_revision"]
            elif phase == "review_lead":
                policy = self.release_policy(data['candidate'])
                release = self.releases.propose(data["candidate"], policy, transaction=tx)
                self.releases.review(release["id"], agent, data["candidate"]["revision"],
                                     result["accepted"], result["execution_ref"], transaction=tx)
                self._review_hook(data["candidate"], agent, result, tx)
                importance = (data.get("origin", {}).get("plan", {}).get("origin", {})
                              .get("importance"))
                result.update(candidate=data["candidate"], release_id=release["id"],
                              origin={"plan": {"origin": ({"importance": importance}
                                                           if importance is not None else {})}})
                if result["accepted"]:
                    next_message = envelope("review.result", agent, "conductor", "review",
                                            {"decision_id": decision["id"], "result": result},
                                            message["correlation_id"], message["message_id"], clock=self.clock,
                                            ids=self.ids)
            elif phase == "review_conductor":
                self.releases.review(data["release_id"], agent, data["candidate"]["revision"],
                                     result["accepted"], result["execution_ref"], transaction=tx)
                self._review_hook(data["candidate"], agent, result, tx)
                if result["accepted"]:
                    tx.put("release_queue", data["release_id"],
                           {"id": data["release_id"], "status": "queued", "at": utcnow(self.clock)})
                    result["deployment"] = {"status": "queued", "release_id": data["release_id"]}
            if phase in {"review_lead", "review_conductor"} and not result["accepted"]:
                loop = tx.get("improvement_loops", message["correlation_id"]) or {
                    "id": message["correlation_id"], "reworks": 0, "rejected_trees": []}
                tree = data["candidate"]["tree"]
                stagnated = tree in loop["rejected_trees"]
                if loop["reworks"] >= POLICY.max_reworks or stagnated:
                    loop["status"] = "stagnated" if stagnated else "budget_exhausted"
                else:
                    loop.update(status="reworking", reworks=loop["reworks"] + 1)
                    loop["rejected_trees"].append(tree)
                    recipient = "worker:implementation" if phase == "review_lead" else "lead:improvement"
                    importance = (data.get("origin", {}).get("plan", {}).get("origin", {})
                                  .get("importance"))
                    rework_plan = {
                        "objective": "Reimplement the rejected improvement and address every review finding",
                        "acceptance_criteria": [result["reason"]],
                        "previous_candidate": data["candidate"], "review_feedback": result,
                    }
                    if phase == "review_lead":
                        rework_plan["origin"] = ({"importance": importance}
                                                 if importance is not None else {})
                    next_message = self.ownership.next_message(message, agent, recipient,
                        "implement" if phase == "review_lead" else "plan",
                        {"plan": rework_plan, "rework": loop["reworks"],
                         **({"importance": importance} if phase == "review_conductor"
                            and importance is not None else {})})
                    if data["candidate"].get("hook_id"):
                        hook = tx.get("hooks", data["candidate"]["hook_id"])
                        next_message["what"]["details"]["plan"].setdefault("origin", {})["hook"] = hook
                tx.put("improvement_loops", loop["id"], loop)
            current = self.ownership.owned(tx, lease)
            current.update(status="succeeded", result=result, completed_at=utcnow(self.clock))
            self.ownership.record(tx, current)
            self.observer.close_unconfirmed(tx, lease, "accepted")  # INV-OBSERVATION-001: with the outcome
            if next_message:
                self.organization.authorize(next_message)
                self.outbox.append(tx, next_message)  # coordination owns `outbox` (§2.7)
            return current

    def _review_hook(self, candidate, agent, result, transaction):
        if candidate.get("hook_id"):
            hook = transaction.get("hooks", candidate["hook_id"])
            require(hook is not None, "Hook not found")
            if not any(r["actor"] == agent for r in hook["reviews"]):
                self.hooks.review(hook["id"], agent, candidate["revision"], digest(hook["spec"]),
                                  result["accepted"], result["execution_ref"],
                                  transaction=transaction)
