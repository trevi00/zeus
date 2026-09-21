"""One bounded operation: claim, assign, worker, evidence gate, lead review, receipt (INV-OPERATION-001).

The state machine reuses LocalCycle.step over the existing message path and executor entry points.
It adds a durable `operations` row that owns the id, a transactional outbox entry for the initial
six-W assignment, a wrapper that takes one machine call slot immediately before each underlying
executor start and settles it afterwards, and a deterministic evidence gate that runs before the
review reservation. It never runs the conductor, merges, deploys, retries, diagnoses, escalates a
budget or takes over an interrupted owner.
"""
from __future__ import annotations

from codex_harness.application.dge import DgeRefused, design_gate
from codex_harness.application.evidence_inspection import EvidenceInspections
from codex_harness.application.local_cycle import LocalCycle, flush_outbox
from codex_harness.application.operation_finalization import retire
from codex_harness.domain.dge import expired
from codex_harness.domain.model import ContractError, digest, envelope, require, utcnow
from codex_harness.domain.operation import (
    ACTION,
    LEAD,
    MAX_EXECUTIONS,
    WORKER,
    assignment_message_id,
    correlation_id,
    cycle_id,
    manifest_digest,
)
from codex_harness.domain.usage_policy import SUBSCRIPTION, accounting_mode, validate_budget

BUCKET = "operations"
RECEIPT_SCHEMA = "urn:zeus:operation-receipt:1"
HANDOFF_SCHEMA = "urn:zeus:operation-evidence-handoff:1"
HANDOFF_REASON = "evidence_gate_refused"
HANDOFF_OWNER = "lead:improvement"
HANDOFF_NEXT_ACTION = "inspect_evidence_contract"
HANDOFF_STATUS = "pending_owner"
MAX_HANDOFF_ITEMS = 32
INSPECTIONS = "evidence_inspections"
TERMINAL = {"accepted", "rejected", "failed", "unknown", "exhausted"}
MAX_STEPS = 6
MAX_IDLE = 2
CANDIDATE_FIELDS = ("base", "revision", "tree", "diff_hash")


class OperationRefused(ContractError):
    """Refused before any provider entry; the message carries a fixed reason code only."""

    def __init__(self, reason_code: str):
        super().__init__("operation refused: " + reason_code)
        self.reason_code = reason_code


class BudgetRefused(OperationRefused):
    pass


class EvidenceGateRefused(OperationRefused):
    pass


class DeadlineRefused(OperationRefused):
    """INV-AUTONOMOUS-001: the caller's absolute deadline passed before a provider start; the slot
    is never reserved and the deadline is never reset or extended by the operation."""


def default_labels(model: str):
    """Ledger provider labels: the worker task is the Claude implementer, a decision is Codex routing."""
    return lambda kind, agent: ("claude", model) if kind == "task" else ("codex", "model_routing")


class DesignGateRefused(OperationRefused):
    """INV-DGE-001: a v2 manifest without an approved design bound to exactly this plan; raised
    inside the claim transaction, so no operation, cycle or outbox row is written."""


class BudgetedExecutor:
    """Reserve one machine slot right before each executor start, settle right after.

    Reservation happens only here, only when LocalCycle already chose a candidate, so an idle,
    stopped or cached turn never takes a slot. A settlement failure keeps the slot counted and is
    reported; the provider itself never reserves again.
    """

    def __init__(self, executor, budget, ceilings: dict, purpose: str, model: str, gate=None, labels=None, before=None):
        # The shared usage policy binds the accounting mode once; an unknown mode is refused here,
        # before any reservation. Finite ceilings keep the legacy reservation call unchanged.
        self.executor, self.budget, self.ceilings = executor, budget, validate_budget(ceilings)
        self.mode = accounting_mode(self.ceilings)
        self.purpose, self.model, self.gate = purpose, model, gate
        # `labels(kind, agent)` names the actual provider and model of each start for the ledger;
        # `before(kind, agent)` runs ahead of every reservation (deadline check), never after one.
        self.labels, self.before = labels or default_labels(model), before
        self.slots: list[dict] = []

    def _call(self, kind, agent, expected, call):
        if self.before is not None:
            self.before(kind, agent)
        if kind == "decision" and self.gate is not None:
            self.gate(expected)  # before the reservation, before any provider entry
        provider, model = self.labels(kind, agent)
        arguments = {"per_host": self.ceilings["per_host"], "total": self.ceilings["total"],
                     "purpose": self.purpose + ":" + kind, "provider": provider, "model": model}
        if self.mode == SUBSCRIPTION:
            # The kwarg travels only for subscription accounting: finite callers and their existing
            # fake ledgers see the exact legacy call. The ledger itself rejects unknown modes.
            arguments["mode"] = self.mode
        try:
            slot = self.budget.reserve(**arguments)
        except ContractError as exc:
            raise BudgetRefused("budget_exhausted") from exc
        record = {"id": slot["id"], "kind": kind, "agent": agent, "provider": provider, "reserved_at": slot.get("reserved_at"),
                  "outcome": None, "settled": False, "accounting_mode": self.mode}
        self.slots.append(record)
        outcome, error = "exception", None
        try:
            result = call(agent, expected=expected)
            outcome = str(result.get("status")) if isinstance(result, dict) else "no_claim"
            return result
        except Exception as exc:
            error = exc
            raise
        finally:
            try:
                self.budget.settle(slot["id"], outcome=outcome, detail={"kind": kind, "agent": agent,
                                   "error_type": type(error).__name__ if error else None})
                record.update(outcome=outcome, settled=True)
            except Exception as exc:  # the slot stays counted; the operation reports the failure
                record.update(outcome=outcome, settled=False, settle_error=type(exc).__name__)

    def execute_one(self, agent, expected=None):
        return self._call("task", agent, expected, self.executor.execute_one)

    def decide_one(self, agent, expected=None):
        return self._call("decision", agent, expected, self.executor.decide_one)


class Operation:
    def __init__(self, service, executor=None, bus=None, workflow=None, budget=None, collector=None, observer=None):
        self.service, self.executor, self.bus, self.workflow = service, executor, bus, workflow
        self.budget, self.collector, self.observer = budget, collector, observer

    # ----- read-only ----------------------------------------------------------------------
    def status(self, operation_id: str) -> dict:
        with self.service.store.transaction() as tx:
            row = tx.get(BUCKET, operation_id)
        require(row is not None, "Unknown operation")
        return self._receipt(row)

    @staticmethod
    def _receipt(row) -> dict:
        """Safe projection: identities, digests, codes and counts; no manifest text or raw errors."""
        keys = ("id", "status", "reason_code", "manifest_sha256", "identity", "goal", "design", "correlation_id",
                "cycle_id", "assignment_message_id", "task_id", "decision_id", "lead_accepted", "calls", "evidence",
                "cycle", "collection", "finalization", "owner_handoff", "accounting_mode", "claimed_at",
                "updated_at", "finished_at")
        return {"schema": RECEIPT_SCHEMA, "authority": "operation_receipt; not merge, deploy or completion",
                **{k: row.get(k) for k in keys}}

    # ----- claim --------------------------------------------------------------------------
    def claim(self, manifest: dict, identity: dict, goal: dict, deadline: str | None = None) -> dict:
        """Atomically own the id, record the binding and queue the assignment in the outbox."""
        operation_id, correlation, cycle = manifest["id"], correlation_id(manifest), cycle_id(manifest)
        binding = {"manifest_sha256": manifest_digest(manifest), "identity": identity, "goal": goal}
        message = self._assignment(manifest, deadline)
        with self.service.store.transaction() as tx:
            old = tx.get(BUCKET, operation_id)
            if old is not None:
                if {k: old.get(k) for k in binding} != binding:
                    raise OperationRefused("configuration_mismatch")
                if old["status"] in TERMINAL:
                    return {"row": old, "cached": True}
                raise OperationRefused("running_residue")  # interrupted or concurrent; never taken over
            if tx.get("local_cycles", cycle) is not None or tx.get("tasks", message["message_id"]) is not None:
                raise OperationRefused("cycle_residue")
            design = None
            if "design" in manifest:
                # INV-DGE-001: same transaction as the first claim; a refusal writes nothing.
                try:
                    design = design_gate(tx, manifest["design"], repository=identity.get("repository"),
                                         base_revision=manifest["base_revision"], plan=manifest["plan"], now=utcnow())
                except DgeRefused as exc:
                    raise DesignGateRefused(exc.reason_code) from exc
            row = {"id": operation_id, "status": "running", "reason_code": None, **binding, "design": design,
                   "deadline": deadline, "accounting_mode": accounting_mode(manifest["budget"]),
                   "correlation_id": correlation, "cycle_id": cycle, "assignment_message_id": message["message_id"],
                   "max_executions": MAX_EXECUTIONS, "task_id": None, "decision_id": None, "lead_accepted": None,
                   "calls": {"reserved": 0, "settled": 0, "slots": []}, "evidence": {}, "cycle": None,
                   "collection": None, "claimed_at": utcnow(), "updated_at": utcnow(), "finished_at": None}
            tx.put(BUCKET, operation_id, row)
            # INV-LOCAL-CYCLE-001 row shape, created durably with the claim so no preexisting
            # same-cycle state is adopted and a crash leaves both or neither.
            tx.put("local_cycles", cycle, {"id": cycle, "correlation_id": correlation, "max_executions": MAX_EXECUTIONS,
                                            "executions": 0, "status": "active", "in_flight": None,
                                            "stopped_reason": None, "last_execution": None,
                                            "created_at": utcnow(), "updated_at": utcnow()})
            if tx.get("outbox", message["message_id"]) is None:
                tx.put("outbox", message["message_id"], {"message": message, "sent": False})
        return {"row": row, "cached": False}

    @staticmethod
    def _assignment(manifest, deadline: str | None = None) -> dict:
        details = {"plan": {k: manifest["plan"][k] for k in ("objective", "acceptance_criteria", "allowed_paths")},
                   "operation": {"id": manifest["id"], "manifest_sha256": manifest_digest(manifest),
                                 "goal": dict(manifest["goal"]), "base_revision": manifest["base_revision"]}}
        if "design" in manifest:
            # The worker and reviewer can trace the plan authority; the reference is not knowledge.
            details["operation"]["design"] = dict(manifest["design"])
        message = envelope("task.assign", LEAD, WORKER, ACTION, details, correlation_id(manifest))
        message["message_id"] = assignment_message_id(manifest)
        message["where"] = {**message["where"], "revision": manifest["base_revision"],
                            "allowed_paths": list(manifest["plan"]["allowed_paths"])}
        message["how"] = {**message["how"], "acceptance_criteria": list(manifest["plan"]["acceptance_criteria"])}
        message["why"] = {"objective": manifest["plan"]["objective"], "evidence_refs": []}
        if deadline is not None:
            # The caller's remaining absolute deadline travels with the assignment; it is never reset here.
            message["when"] = {**message["when"], "deadline": deadline}
        return message

    # ----- evidence gate ------------------------------------------------------------------
    def evidence_gate(self, expected: dict) -> dict:
        """The exact pending review decision and its succeeded candidate task, bound to a real
        `evidence_inspections` row that is all_checked for that execution and revision."""
        require(isinstance(expected, dict) and isinstance(expected.get("id"), str), "Review guard required")
        with self.service.store.transaction() as tx:
            decision = tx.get("decisions_pending", expected["id"])
            if not (decision and decision.get("status") == "pending" and decision.get("phase") == "review_lead"
                    and decision.get("actor") == LEAD
                    and (decision.get("message") or {}).get("correlation_id") == expected.get("correlation_id")):
                raise EvidenceGateRefused("review_decision_mismatch")
            details = ((decision.get("message") or {}).get("what") or {}).get("details") or {}
            task = tx.get("tasks", details.get("task_id")) if isinstance(details.get("task_id"), str) else None
            result = decision.get("input")
            if not (task and task.get("status") == "succeeded" and task.get("agent") == WORKER
                    and task.get("result") == result and isinstance(result, dict)
                    and (task.get("message") or {}).get("correlation_id") == expected.get("correlation_id")):
                raise EvidenceGateRefused("worker_result_unbound")
            candidate = result.get("candidate")
            inspection = result.get("evidence_inspection")
            if not (isinstance(candidate, dict) and isinstance(candidate.get("revision"), str)
                    and isinstance(inspection, dict) and isinstance(inspection.get("inspection_id"), str)):
                raise EvidenceGateRefused("evidence_inspection_missing")
            binding = {"task_id": task["id"], "generation": task.get("generation"), "attempt": task.get("attempt"),
                       "source_revision": candidate["revision"]}
            try:
                # A summary string is not proof; the row itself must exist and bind to this execution.
                row = EvidenceInspections(self.service.store, None).require_all_checked(
                    tx, inspection["inspection_id"], binding=binding)
            except ContractError as exc:
                raise EvidenceGateRefused("evidence_inspection_refused") from exc
        return {"task_id": task["id"], "decision_id": decision["id"], "inspection_id": row["id"],
                "source_revision": candidate["revision"]}

    # ----- run ----------------------------------------------------------------------------
    def run(self, manifest: dict, identity: dict, goal: dict, ceilings: dict | None = None,
            deadline: str | None = None, clock=utcnow, labels=None) -> dict:
        """`deadline` (aware ISO 8601, optional) is checked by `clock` before every provider start;
        a passed deadline ends `failed`/`deadline_expired` without a reservation and is never reset.
        An override `ceilings` must satisfy the same usage policy as the manifest budget, checked
        before the claim so an unknown mode leaves no row behind."""
        ceilings = validate_budget(ceilings) if ceilings is not None else None
        claimed = self.claim(manifest, identity, goal, deadline)
        if claimed["cached"]:
            return {**self._receipt(claimed["row"]), "cached": True, "exit_code": 0 if claimed["row"]["status"] == "accepted" else 1}
        row = claimed["row"]
        require(self.executor is not None and self.budget is not None, "Operation run needs an executor and a call budget")

        def before(kind, agent):
            if deadline is not None and expired(deadline, clock()):
                raise DeadlineRefused("deadline_expired")
        wrapped = BudgetedExecutor(self.executor, self.budget, ceilings or manifest["budget"],
                                   "operation:" + manifest["id"], manifest["claude"]["model"], gate=self.evidence_gate,
                                   labels=labels, before=before)
        cycle = LocalCycle(self.service, wrapped, self.bus, self.workflow, observer=self.observer)
        outcome = {"status": "unknown", "reason_code": "no_terminal_outcome"}
        idle, steps = 0, []
        try:
            for _ in range(MAX_STEPS):
                if self.bus is not None:
                    # Implementation015: only this operation's own unsent intents (the assignment,
                    # the worker's result and the workflow's commands) are published here, never a
                    # page of the shared queue. An unfinished scoped publication stops the run
                    # before any further reservation or provider entry; it is not a retry.
                    publication = flush_outbox(self.service, self.bus, self.observer, row["correlation_id"])
                    if not publication["complete"]:
                        outcome = {"status": "failed", "reason_code": "publication_incomplete"}
                        break
                step = cycle.step(row["cycle_id"])
                steps.append({"action": step["action"], "reason": _code(step.get("reason"))})
                outcome = self._classify(step, wrapped)
                if any(not s["settled"] for s in wrapped.slots) and outcome["status"] not in TERMINAL:
                    # An unsettled counted slot stops here: no further LocalCycle turn, reservation
                    # or provider entry. The slot stays counted; the receipt records the failure.
                    outcome = {"status": "failed", "reason_code": "settlement_failed"}
                if outcome["status"] in TERMINAL:
                    break
                if step["action"] == "none" and step.get("reason") == "idle":
                    idle += 1
                    if idle >= MAX_IDLE:
                        outcome = {"status": "failed", "reason_code": "idle"}
                        break
        except Exception as exc:
            outcome = {"status": "failed", "reason_code": "exception:" + type(exc).__name__}
        return self._finish(row, manifest, wrapped, outcome, steps)

    def _classify(self, step, wrapped) -> dict:
        cycle, last = step["cycle"], step["cycle"].get("last_execution") or {}
        if cycle["status"] == "awaiting_operator":
            return self._accepted(cycle, last)
        if last.get("kind") == "decision" and last.get("status") == "succeeded":
            return self._decided(cycle, last)
        if cycle["status"] == "stopped":
            reason = _code(cycle.get("stopped_reason"))
            if reason in {"budget_exhausted", "exception:BudgetRefused"}:
                return {"status": "exhausted", "reason_code": "budget_exhausted"}
            if reason == "exception:EvidenceGateRefused":
                return {"status": "failed", "reason_code": "evidence_gate_refused"}
            if reason == "exception:DeadlineRefused":
                return {"status": "failed", "reason_code": "deadline_expired"}
            if reason.startswith("execution_") or reason.startswith("exception:") or reason in {
                    "retry", "failed", "blocked", "expired", "superseded", "inspection_blocked", "cancelled",
                    "publication_incomplete"}:
                return {"status": "failed", "reason_code": reason}
            return {"status": "unknown", "reason_code": reason}
        return {"status": "running", "reason_code": None}

    def _decided(self, cycle, last) -> dict:
        with self.service.store.transaction() as tx:
            decision = tx.get("decisions_pending", last["id"])
        result = (decision or {}).get("result") if isinstance(decision, dict) else None
        accepted = result.get("accepted") if isinstance(result, dict) else None
        if accepted is False:
            return {"status": "rejected", "reason_code": "lead_rejected", "decision_id": last["id"]}
        if accepted is True:
            return self._accepted(cycle, last)
        return {"status": "unknown", "reason_code": "review_verdict_unknown", "decision_id": last["id"]}

    def _accepted(self, cycle, last) -> dict:
        """`awaiting_operator` alone is insufficient: the decision row must be a succeeded, accepted
        review_lead result for the candidate the worker task produced."""
        with self.service.store.transaction() as tx:
            decision = tx.get("decisions_pending", last.get("id")) if isinstance(last.get("id"), str) else None
            details = (((decision or {}).get("message") or {}).get("what") or {}).get("details") or {}
            task = tx.get("tasks", details.get("task_id")) if isinstance(details.get("task_id"), str) else None
        result = (decision or {}).get("result")
        candidate = ((task or {}).get("result") or {}).get("candidate") if task else None
        reviewed = ((decision or {}).get("input") or {}).get("candidate")
        if (decision and decision.get("status") == "succeeded" and decision.get("phase") == "review_lead"
                and isinstance(result, dict) and result.get("accepted") is True and task and task.get("status") == "succeeded"
                and isinstance(candidate, dict) and isinstance(reviewed, dict)
                and candidate.get("revision") == reviewed.get("revision")):
            return {"status": "accepted", "reason_code": "lead_accepted", "decision_id": decision["id"], "task_id": task["id"]}
        return {"status": "unknown", "reason_code": "acceptance_unproven", "decision_id": last.get("id")}

    # ----- evidence refusal handoff -------------------------------------------------------
    def _owner_handoff(self, row, status, reason, evidence, cycle, at) -> dict | None:
        """One bounded, idempotent owner handoff for an evidence-refused operation, or None.

        It is written in the SAME durable finalization as the terminal status, beside the untouched
        failed outcome and the cancelled pending review: a handoff is a visible request for an owner,
        never a retry, an acceptance, a model call, a merge or a deployment, and it schedules
        nothing. Only identities, digests, codes, counts and check ids leave here - no raw output,
        exception text, command string or credential. An inspection that is missing or not bound to
        this execution is reported as explicitly unknown, never as a clean denominator.
        """
        if status != "failed" or reason != HANDOFF_REASON:
            return None
        # The refusal happens BEFORE the review reservation, so the operation outcome names no task
        # yet: the candidate execution is the cycle's own last target record, read as it stands now.
        target = cycle.get("target_record") or {}
        target_id = _string(target.get("id"))
        task_id = _string(evidence.get("task_id"))
        if task_id is None and target.get("kind") == "task":
            task_id = target_id
        with self.service.store.transaction() as tx:
            if task_id is None and target.get("kind") == "decision" and target_id is not None:
                # The refused turn is the review decision itself; it names the candidate task it guards.
                decision = tx.get("decisions_pending", target_id) or {}
                details = ((decision.get("message") or {}).get("what") or {}).get("details") or {}
                task_id = _string(details.get("task_id"))
            task = tx.get("tasks", task_id) if task_id else None
            task = task if isinstance(task, dict) else {}
            result = task.get("result") if isinstance(task.get("result"), dict) else {}
            reported = result.get("evidence_inspection") if isinstance(result.get("evidence_inspection"), dict) else {}
            inspection_id = _string(evidence.get("inspection_id")) or _string(reported.get("inspection_id"))
            inspection = tx.get(INSPECTIONS, inspection_id) if inspection_id else None
        candidate = evidence.get("candidate") if isinstance(evidence.get("candidate"), dict) else {}
        if not candidate:
            stored = result.get("candidate")
            candidate = stored if isinstance(stored, dict) else {}
        revision = _string(candidate.get("revision"))
        binding = {"task_id": task_id, "generation": task.get("generation"), "attempt": task.get("attempt"),
                   "source_revision": revision}
        record = {"schema": HANDOFF_SCHEMA, "status": HANDOFF_STATUS, "owner": HANDOFF_OWNER,
                  "next_action": HANDOFF_NEXT_ACTION, "reason_code": reason,
                  "authority": "owner_handoff; grants no retry, acceptance, model call, merge or deployment",
                  "retry": "none; this handoff schedules no follow-up and relaunches nothing",
                  "operation_id": row["id"], "correlation_id": row["correlation_id"],
                  "manifest_sha256": row.get("manifest_sha256"), **binding,
                  "candidate": {k: _string(candidate.get(k)) for k in CANDIDATE_FIELDS},
                  "refs": {"execution_ref": _string(evidence.get("execution_ref")),
                           "review_execution_ref": _string(evidence.get("review_execution_ref"))},
                  "inspection": _inspection_summary(inspection_id, inspection, binding), "at": at}
        record["id"] = digest(["operation_evidence_handoff", row["id"], task_id, revision, inspection_id])
        return record

    def _finish(self, row, manifest, wrapped, outcome, steps) -> dict:
        collection, collection_failed = None, False
        if self.collector is not None:
            try:
                summary = self.collector.collect()
                collection = {k: summary.get(k) for k in ("files", "records", "inserted", "sink_failures", "corrupt", "refused")}
                collection_failed = bool(summary.get("sink_failures"))
            except Exception as exc:
                collection, collection_failed = {"error_type": type(exc).__name__}, True
        unsettled = [s for s in wrapped.slots if not s["settled"]]
        status, reason = outcome["status"], outcome["reason_code"]
        lead_accepted = status == "accepted"
        if lead_accepted and (unsettled or collection_failed):
            status, reason = "failed", "settlement_failed" if unsettled else "collection_failed"
        handoff = LocalCycle(self.service).handoff(row["cycle_id"])
        evidence = self._evidence(handoff, outcome)
        at = utcnow()
        # Read before the terminal transaction, written inside it: the same failed status, the same
        # cancelled pending review, plus one visible owner handoff when evidence itself was refused.
        owner_handoff = self._owner_handoff(row, status, reason, evidence, handoff, at)
        with self.service.store.transaction() as tx:
            current = tx.get(BUCKET, row["id"])
            require(current is not None and current["status"] == "running", "Operation row changed during the run")
            current["owner_handoff"] = owner_handoff
            current.update(status=status, reason_code=reason, lead_accepted=lead_accepted,
                           task_id=evidence.pop("task_id", None), decision_id=outcome.get("decision_id"),
                           calls={"reserved": len(wrapped.slots), "settled": sum(s["settled"] for s in wrapped.slots),
                                  "slots": [{k: s.get(k) for k in ("id", "kind", "agent", "provider", "outcome", "settled", "settle_error")}
                                            for s in wrapped.slots]},
                           evidence=evidence, cycle=handoff, collection=collection, steps=steps,
                           updated_at=at, finished_at=at)
            tx.put(BUCKET, row["id"], current)
            # INV-OPERATION-FINALIZATION-001: the same transaction retires owned unstarted follow-ups;
            # a rollback leaves neither the terminal status nor a disposition. The summary is cleanup
            # evidence beside the outcome, never a change to it.
            current["finalization"] = retire(tx, current, current["finished_at"])
            tx.put(BUCKET, row["id"], current)
        self._observe_finalized(current)
        return {**self._receipt(current), "cached": False, "exit_code": 0 if status == "accepted" else 1}

    def _observe_finalized(self, current) -> None:
        """Counts and codes only, after the commit; unresolved rows are a warning, not a repair."""
        if self.observer is None:
            return
        summary = current["finalization"]
        unresolved = len(summary["unresolved"])
        self.observer.emit("operations.operation_finalized", "observed" if not unresolved else "blocked",
                           severity="warning" if unresolved else "info", correlation_id=current["correlation_id"],
                           reason_code=_code(current.get("reason_code")).replace(":", "_"),
                           attributes={"operation_id": current["id"], "operation_status": current["status"],
                                       "retired_tasks": len(summary["retired"]["tasks"]),
                                       "retired_decisions": len(summary["retired"]["decisions_pending"]),
                                       "unresolved": unresolved, "already_terminal": summary["already_terminal"]})

    def _evidence(self, handoff, outcome) -> dict:
        target = handoff.get("target_record") or {}
        out = {"task_id": outcome.get("task_id"), "execution_ref": (target.get("result") or {}).get("execution_ref"),
               "candidate": (target.get("result") or {}).get("candidate"), "inspection_id": None, "review_execution_ref": None}
        with self.service.store.transaction() as tx:
            if isinstance(outcome.get("decision_id"), str):
                decision = tx.get("decisions_pending", outcome["decision_id"]) or {}
                result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
                out["review_execution_ref"] = _string(result.get("execution_ref"))
                details = ((decision.get("message") or {}).get("what") or {}).get("details") or {}
                if out["task_id"] is None and isinstance(details.get("task_id"), str):
                    out["task_id"] = details["task_id"]
            if isinstance(out["task_id"], str):
                task = tx.get("tasks", out["task_id"]) or {}
                result = task.get("result") if isinstance(task.get("result"), dict) else {}
                out["execution_ref"] = _string(result.get("execution_ref"))
                inspection = result.get("evidence_inspection")
                out["inspection_id"] = _string(inspection.get("inspection_id")) if isinstance(inspection, dict) else None
                candidate = result.get("candidate")
                out["candidate"] = ({k: _string(candidate.get(k)) for k in CANDIDATE_FIELDS}
                                    if isinstance(candidate, dict) else None)
        return out


def _check_item(finding) -> dict:
    """One check's identity and state: no cause text, no command and no observed output."""
    claim = finding.get("claim") if isinstance(finding.get("claim"), dict) else {}
    return {"check_id": _string(claim.get("check_id")), "reported": _string(claim.get("status")),
            "state": _string(finding.get("state"))}


def _inspection_summary(inspection_id, row, binding) -> dict:
    """What the owner is told about the inspection the refusal rests on.

    `bound` is the same question the gate asked: does a real row exist for exactly this execution
    and revision? A missing row, a row for another execution and a row whose findings cannot be read
    are each explicitly unknown; none of them is summarized as a passing denominator.
    """
    if inspection_id is None:
        return {"id": None, "bound": False, "known": False, "reason_code": "inspection_missing"}
    if not isinstance(row, dict) or not isinstance(row.get("findings"), list):
        return {"id": inspection_id, "bound": False, "known": False, "reason_code": "inspection_unknown"}
    bound = all(row.get("binding", {}).get(k) == v for k, v in binding.items() if v is not None)
    passed, remaining, claims = [], [], {}
    for finding in row["findings"]:
        if not isinstance(finding, dict):
            continue
        item = _check_item(finding)
        claims[item["reported"]] = claims.get(item["reported"], 0) + 1
        (passed if item["state"] == "checked" else remaining).append(item)
    denominator = row.get("denominator") if isinstance(row.get("denominator"), dict) else {}
    return {"id": inspection_id, "bound": bound, "known": True,
            "reason_code": None if bound else "inspection_bound_elsewhere",
            "verdict": _string(row.get("verdict")), "policy_hash": _string(row.get("policy_hash")),
            "denominator": {k: v for k, v in denominator.items() if type(v) is int},
            "claim_status_counts": claims,
            "passed": passed[:MAX_HANDOFF_ITEMS], "remaining": remaining[:MAX_HANDOFF_ITEMS],
            "truncated": len(passed) > MAX_HANDOFF_ITEMS or len(remaining) > MAX_HANDOFF_ITEMS}


def _code(reason) -> str:
    """Only the finite head of a stored reason leaves; colon details may carry raw error text."""
    if not isinstance(reason, str):
        return "unknown"
    head, _, tail = reason.partition(":")
    if head == "exception":
        return "exception:" + tail.split(":", 1)[0]
    return head


def _string(value):
    return value if isinstance(value, str) else None


def identity_digest(values: dict) -> dict:
    """Safe digests for endpoint or namespace identity; no value is stored."""
    return {k: digest(str(v)) for k, v in sorted(values.items())}
