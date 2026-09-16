"""One autonomous cycle: research, immutable packet, independent debate roles, existing Operation v2
implementation/review, evidence-bound promotion (INV-AUTONOMOUS-001).

A durable `autonomous_runs` row owns the run id. Every role is one fresh task from the conductor to a
dedicated lead through the outbox and bus, claimed and executed by the existing executor under the
machine call budget, then bound to its persisted row. The packet is frozen through the existing
DebateSessions with origin `executor_bound`; the operator `dge submit` cannot add events to it.
The approved design launches the existing Operation v2. Promotion happens only after re-reading the
exact accepted records in the same transaction that writes the graph and the receipt. Fixed round,
fixed start cap, no rework, no retry, no takeover.
"""
from __future__ import annotations

import time

from codex_harness.application.dge import SESSIONS, DebateSessions, DgeRefused
from codex_harness.application.evidence_inspection import EvidenceInspections
from codex_harness.application.local_cycle import MESSAGE_DRAIN
from codex_harness.application.operation import BudgetedExecutor, Operation
from codex_harness.application.promotion import promote
from codex_harness.domain.autonomous import (
    ARBITER,
    CONDUCTOR,
    DEBATE_ROLES,
    MAX_STARTS,
    ORIGIN_EXECUTOR,
    PROPOSER,
    RECEIPT_SCHEMA,
    RESEARCHER,
    ROLE_ACTION,
    ROLE_AGENTS,
    TERMINAL,
    TRUST,
    correlation_id,
    event_from_role,
    manifest_digest,
    operation_manifest,
    packet_from_research,
    role_binding,
    role_message_id,
    session_id,
    verified_graph,
)
from codex_harness.domain.dge import expired, packet_digest
from codex_harness.domain.model import ContractError, envelope, require, utcnow
from codex_harness.domain.operation import WORKER

BUCKET = "autonomous_runs"
OPERATIONS = "operations"
OUTCOME_BY_REASON = {"deadline_expired": "expired", "start_cap_reached": "exhausted", "budget_exhausted": "exhausted",
                     "needs_user": "needs_user", "design_needs_research": "needs_research", "design_rejected": "rejected",
                     "design_exhausted": "exhausted", "review_rejected": "rejected"}


class AutonomousRefused(ContractError):
    def __init__(self, reason_code: str):
        super().__init__("autonomous refused: " + reason_code)
        self.reason_code = reason_code


class AutonomousRun:
    def __init__(self, service, executor=None, bus=None, workflow=None, budget=None, collector=None,
                 verify_sources=None, repository=None, observer=None, clock=utcnow):
        self.service, self.executor, self.bus, self.workflow = service, executor, bus, workflow
        self.budget, self.collector, self.verify_sources = budget, collector, verify_sources
        self.repository, self.observer, self.clock = repository, observer, clock

    # ----- read-only ----------------------------------------------------------------------
    def status(self, run_id: str) -> dict:
        with self.service.store.transaction() as tx:
            row = tx.get(BUCKET, run_id)
        if row is None:
            raise AutonomousRefused("unknown_run")
        return self._receipt(row)

    @staticmethod
    def _receipt(row) -> dict:
        keys = ("id", "status", "stage", "reason_code", "manifest_sha256", "identity", "goal", "correlation_id", "session_id",
                "operation_id", "deadline", "max_starts", "starts", "invocations", "roles", "packet_digest", "ssot_decision",
                "design", "operation", "residuals", "promotion", "durations", "history", "claimed_at", "updated_at", "finished_at")
        return {"schema": RECEIPT_SCHEMA, "trust": TRUST, "authority": "autonomous_receipt; not merge, deploy, completion or truth",
                **{k: row.get(k) for k in keys}}

    # ----- claim --------------------------------------------------------------------------
    def claim(self, manifest: dict, identity: dict, goal: dict) -> dict:
        binding = {"manifest_sha256": manifest_digest(manifest), "identity": identity, "goal": goal}
        run_id, session, operation = manifest["id"], session_id(manifest), manifest["id"] + ".impl"
        with self.service.store.transaction() as tx:
            old = tx.get(BUCKET, run_id)
            if old is not None:
                if {k: old.get(k) for k in binding} != binding:
                    raise AutonomousRefused("configuration_mismatch")
                if old["status"] in TERMINAL:
                    return {"row": old, "cached": True}
                raise AutonomousRefused("running_residue")  # interrupted or concurrent owner; never taken over
            if tx.get(SESSIONS, session) is not None or tx.get(OPERATIONS, operation) is not None:
                raise AutonomousRefused("residue")
            now = self.clock()
            if expired(manifest["deadline"], now):
                raise AutonomousRefused("deadline_expired")
            row = {"id": run_id, "status": "running", "stage": "research", "reason_code": None, **binding,
                   "correlation_id": correlation_id(manifest), "session_id": session, "operation_id": operation,
                   "deadline": manifest["deadline"], "max_starts": MAX_STARTS, "starts": {"reserved": 0, "settled": 0, "slots": []},
                   "invocations": {}, "roles": {}, "packet_digest": None, "ssot_decision": None, "design": None,
                   "operation": None, "residuals": {"critical": [], "minor": []}, "promotion": None, "durations": {},
                   "history": [{"at": now, "from": None, "to": "research"}], "claimed_at": now, "updated_at": now, "finished_at": None}
            tx.put(BUCKET, run_id, row)
        return {"row": row, "cached": False}

    def _transition(self, run_id: str, expected_stage: str, stage: str | None = None, **fields) -> dict:
        """Every write records the prior state it expects; a changed row stops the run."""
        with self.service.store.transaction() as tx:
            current = tx.get(BUCKET, run_id)
            if not (current and current["status"] == "running" and current["stage"] == expected_stage):
                raise AutonomousRefused("run_state_changed")
            now = self.clock()
            if stage is not None and stage != expected_stage:
                current["history"].append({"at": now, "from": expected_stage, "to": stage})
                current["stage"] = stage
            current.update(**fields, updated_at=now)
            tx.put(BUCKET, run_id, current)
            return current

    # ----- run ----------------------------------------------------------------------------
    def run(self, manifest: dict, identity: dict, goal: dict) -> dict:
        claimed = self.claim(manifest, identity, goal)
        if claimed["cached"]:
            return {**self._receipt(claimed["row"]), "cached": True, "exit_code": 0 if claimed["row"]["status"] == "accepted" else 1}
        row = claimed["row"]
        require(self.executor is not None and self.budget is not None and self.bus is not None and self.workflow is not None,
                "Autonomous run needs an executor, a call budget, a bus and a workflow")
        wrapped = BudgetedExecutor(self.executor, self.budget, manifest["budget"], "autonomous:" + manifest["id"],
                                   manifest["claude"]["model"])
        try:
            outcome = self._pipeline(manifest, identity, goal, row, wrapped)
        except AutonomousRefused as exc:
            outcome = {"status": OUTCOME_BY_REASON.get(exc.reason_code, "failed"), "reason_code": exc.reason_code}
        except Exception as exc:
            outcome = {"status": "failed", "reason_code": "exception:" + type(exc).__name__}
        return self._finish(row, wrapped, outcome)

    def _pipeline(self, manifest, identity, goal, row, wrapped) -> dict:
        run_id, base = row["id"], manifest["base_revision"]
        research = self._role(manifest, row, wrapped, RESEARCHER, {
            "role": RESEARCHER, "run_id": run_id, "base_revision": base, "topic": manifest["research"]["topic"],
            "questions": manifest["research"]["questions"], "search_scope": manifest["research"]["search_scope"],
            "goal": goal, "plan": manifest["plan"], "deadline": manifest["deadline"]})
        self._log("packet", run_id, "started")
        try:
            frozen = packet_from_research(manifest, research["answer"])
        except ContractError as exc:
            raise AutonomousRefused("packet_invalid:" + type(exc).__name__) from exc
        if frozen["needs_user"]:
            self._transition(run_id, "research", "packet", ssot_decision=frozen["ssot"]["decision"])
            raise AutonomousRefused("needs_user")
        packet = frozen["packet"]
        try:
            bound = self.verify_sources(packet)
        except ContractError as exc:
            raise AutonomousRefused(getattr(exc, "reason_code", "source_verification_failed")) from exc
        sessions = DebateSessions(self.service.store, self.clock)
        registered = sessions.register(packet, self.repository, bound, origin=ORIGIN_EXECUTOR, owner=run_id,
                                       binding=_safe_binding(research))
        digest_value = registered["session"]["packet_digest"]
        self._transition(run_id, "research", "packet", packet_digest=digest_value, ssot_decision=frozen["ssot"]["decision"])
        prior, version = {}, 0
        for role in DEBATE_ROLES:
            self._transition(run_id, "packet" if role == PROPOSER else DEBATE_ROLES[DEBATE_ROLES.index(role) - 1], role)
            binding = self._role(manifest, row, wrapped, role, {
                "role": role, "run_id": run_id, "base_revision": base, "packet_digest": digest_value, "packet": packet,
                "ssot": frozen["ssot"], "round": 1, "prior_outputs": prior, "acceptance_criteria": manifest["plan"]["acceptance_criteria"],
                "blocker_rule": "critical only: concrete reachable trigger, cited packet evidence, affected fixed criterion, "
                                "material impact and minimal mitigation; styling, optional refactoring and unsupported "
                                "hypotheticals are minor and never block"})
            try:
                event = event_from_role(role, binding["answer"], digest_value, version, binding["task_id"])
                recorded = sessions.submit(row["session_id"], event, owner=run_id, binding=_safe_binding(binding))
            except (ContractError, DgeRefused) as exc:
                raise AutonomousRefused("debate_refused:" + getattr(exc, "reason_code", type(exc).__name__)) from exc
            prior[role] = {"event_id": event["id"], "payload": event["payload"], "binding": _safe_binding(binding)}
            version = recorded["session"]["version"]
        design = recorded["session"]
        self._transition(run_id, ARBITER, ARBITER, design={k: design.get(k) for k in ("id", "state", "packet_digest", "decision_event_id", "version")},
                         residuals=self._residuals(row["session_id"]))
        if design["state"] != "design_approved":
            raise AutonomousRefused("design_" + {"rejected": "rejected", "needs_research": "needs_research"}.get(design["state"], "exhausted"))
        if len(wrapped.slots) + 2 > MAX_STARTS:
            raise AutonomousRefused("start_cap_reached")
        self._check_deadline(manifest)
        self._transition(run_id, ARBITER, "implementation")
        self._log("implementation", run_id, "started")
        started = time.monotonic()
        operation = Operation(self.service, self.executor, self.bus, self.workflow, self.budget, self.collector)
        receipt = operation.run(operation_manifest(manifest, digest_value), identity, goal)
        wrapped.slots.extend([{**s, "operation": receipt["id"]} for s in receipt["calls"]["slots"]])
        self._transition(run_id, "implementation", "implementation", durations={**row.get("durations", {}), "implementation": time.monotonic() - started},
                         operation={k: receipt.get(k) for k in ("id", "status", "reason_code", "task_id", "decision_id", "evidence")})
        if receipt["status"] != "accepted":
            raise AutonomousRefused("review_rejected" if receipt["status"] == "rejected" else "operation_" + receipt["status"])
        self._transition(run_id, "implementation", "promotion")
        promotion = self._promote(manifest, goal, row, receipt, research, prior)
        return {"status": "accepted", "reason_code": "promoted", "promotion": promotion}

    # ----- roles --------------------------------------------------------------------------
    def _role(self, manifest, row, wrapped, role, details) -> dict:
        run_id, correlation, agent = row["id"], row["correlation_id"], ROLE_AGENTS[role]
        self._check_deadline(manifest)
        if len(wrapped.slots) >= MAX_STARTS:
            raise AutonomousRefused("start_cap_reached")
        message = envelope("task.assign", CONDUCTOR, agent, ROLE_ACTION, details, correlation)
        message["message_id"] = role_message_id(manifest, role)
        message["where"] = {**message["where"], "revision": manifest["base_revision"], "allowed_paths": []}
        message["how"] = {**message["how"], "acceptance_criteria": list(manifest["plan"]["acceptance_criteria"])}
        message["why"] = {"objective": manifest["plan"]["objective"], "evidence_refs": []}
        message["when"] = {**message["when"], "deadline": manifest["deadline"]}
        self.service.org.authorize(message)
        with self.service.store.transaction() as tx:
            if tx.get("tasks", message["message_id"]) is not None or tx.get("outbox", message["message_id"]) is not None:
                raise AutonomousRefused("role_residue")  # no double dispatch, no takeover
            tx.put("outbox", message["message_id"], {"message": message, "sent": False})
        self._log(role, run_id, "started")
        started = time.monotonic()
        self.service.flush_outbox(self.bus)
        self._deliver(agent, correlation)
        expected = {"id": message["message_id"], "correlation_id": correlation, "statuses": {"queued"}}
        result = wrapped.execute_one(agent, expected=expected)
        self.service.flush_outbox(self.bus)
        if any(not s["settled"] for s in wrapped.slots):
            raise AutonomousRefused("settlement_failed")
        if result is None:
            raise AutonomousRefused("no_execution_claimed")
        if result.get("status") != "succeeded":
            raise AutonomousRefused("role_" + str(result.get("status")))
        with self.service.store.transaction() as tx:
            task = tx.get("tasks", message["message_id"])
            invocations = [r for r in tx.scan("invocation_reservations") if r.get("task_id") == message["message_id"]]
        try:
            binding = role_binding(task, role=role, base_revision=manifest["base_revision"], correlation=correlation)
        except ContractError as exc:
            raise AutonomousRefused(str(exc)) from exc
        current = self._transition(run_id, role if role != RESEARCHER else "research", None)
        self._transition(run_id, current["stage"], None, roles={**current["roles"], role: _safe_binding(binding)},
                         invocations={**current["invocations"], role: len(invocations)},
                         durations={**current["durations"], role: time.monotonic() - started})
        self._log(role, run_id, "succeeded")
        return binding

    def _deliver(self, agent: str, correlation: str) -> None:
        """Existing serve semantics for the dedicated lead: handle, relay outbox, ACK. A foreign message
        is left pending and stops the run; nothing is dead-lettered on its behalf."""
        consumer = agent + ":autonomous"
        for _ in range(MESSAGE_DRAIN):
            row = self.bus.receive(agent, consumer)
            if not row:
                return
            entry_id, fields = row
            try:
                message = self.bus.decode(fields)
                require(message["who"]["recipient"] == agent, "Message routed to wrong agent")
                self.service.org.authorize(message)
            except (ContractError, KeyError, ValueError) as exc:
                self.bus.dead_letter(agent, entry_id, fields, str(exc))
                continue
            if message["correlation_id"] != correlation:
                raise AutonomousRefused("foreign_message")
            self.workflow.handle(message)
            self.service.flush_outbox(self.bus)
            self.bus.ack(agent, entry_id)

    def _check_deadline(self, manifest):
        if expired(manifest["deadline"], self.clock()):
            raise AutonomousRefused("deadline_expired")

    def _residuals(self, session: str) -> dict:
        with self.service.store.transaction() as tx:
            row = tx.get(SESSIONS, session) or {}
        findings = row.get("findings") or []
        return {"critical": [{"id": f["id"], "status": f["status"]} for f in findings if f["severity"] == "critical"],
                "minor": [{"id": f["id"], "status": f["status"]} for f in findings if f["severity"] == "minor"]}

    # ----- promotion ----------------------------------------------------------------------
    def _promote(self, manifest, goal, row, receipt, research, prior) -> dict:
        """Re-read the exact records inside the promotion transaction; the receipt alone is insufficient."""
        run_id = row["id"]
        with self.service.store.transaction() as tx:
            operation = tx.get(OPERATIONS, receipt["id"])
            task = tx.get("tasks", receipt.get("task_id")) if isinstance(receipt.get("task_id"), str) else None
            decision = tx.get("decisions_pending", receipt.get("decision_id")) if isinstance(receipt.get("decision_id"), str) else None
            if not (operation and operation["status"] == "accepted" and operation["lead_accepted"] is True):
                raise AutonomousRefused("promotion_operation_unproven")
            result = (task or {}).get("result") if isinstance((task or {}).get("result"), dict) else None
            if not (task and task["status"] == "succeeded" and task["agent"] == WORKER and result
                    and isinstance(result.get("candidate"), dict) and isinstance(result.get("evidence_inspection"), dict)):
                raise AutonomousRefused("promotion_task_unproven")
            verdict = (decision or {}).get("result") if isinstance((decision or {}).get("result"), dict) else None
            reviewed = ((decision or {}).get("input") or {}).get("candidate") if decision else None
            if not (decision and decision["status"] == "succeeded" and decision.get("phase") == "review_lead" and verdict
                    and verdict.get("accepted") is True and isinstance(reviewed, dict)
                    and reviewed.get("revision") == result["candidate"].get("revision")):
                raise AutonomousRefused("promotion_review_unproven")
            candidate = result["candidate"]
            binding = {"task_id": task["id"], "generation": task.get("generation"), "attempt": task.get("attempt"),
                       "source_revision": candidate["revision"]}
            try:
                inspection = EvidenceInspections(self.service.store, None).require_all_checked(
                    tx, result["evidence_inspection"].get("inspection_id"), binding=binding)
            except ContractError as exc:
                raise AutonomousRefused("promotion_inspection_unproven") from exc
            session = tx.get(SESSIONS, row["session_id"])
            if not (session and session["state"] == "design_approved" and session.get("owner") == run_id
                    and session.get("origin") == ORIGIN_EXECUTOR and session["packet_digest"] == row_digest(tx, run_id)):
                raise AutonomousRefused("promotion_design_unproven")
            refs = {"base_revision": manifest["base_revision"], "goal": {"path": goal["path"], "sha256": goal["sha256"]},
                    "packet_digest": session["packet_digest"], "research_execution_ref": research["execution_ref"],
                    "research_task_id": research["task_id"], "session_id": session["id"],
                    "decision_event_id": session["decision_event_id"],
                    "role_bindings": {role: prior[role]["binding"] for role in DEBATE_ROLES},
                    "candidate": {k: candidate.get(k) for k in ("revision", "base", "tree", "diff_hash")},
                    "implementation_task_id": task["id"], "implementation_execution_ref": result.get("execution_ref"),
                    "decision_id": decision["id"], "review_execution_ref": verdict.get("execution_ref"),
                    "inspection_id": inspection["id"], "operation_id": operation["id"],
                    "verification_scope": {"review": "independent read-only review at the candidate commit",
                                           "inspection": "all_checked command replays for the worker's test claims",
                                           "not_verified": ["semantic truth of research claims", "merge", "deploy"]}}
            graph = verified_graph(run_id, refs)
            promotion = promote(tx, run_id, graph, {k: refs[k] for k in ("implementation_task_id", "decision_id", "inspection_id",
                                                                             "operation_id", "session_id", "packet_digest")})
            current = tx.get(BUCKET, run_id)
            if not (current and current["status"] == "running" and current["stage"] == "promotion"):
                raise AutonomousRefused("run_state_changed")
            current.update(promotion={k: promotion[k] for k in ("id", "repository", "graph_sha256", "nodes", "edges", "cached")},
                           updated_at=self.clock())
            tx.put(BUCKET, run_id, current)
        return current["promotion"]

    # ----- finish -------------------------------------------------------------------------
    def _finish(self, row, wrapped, outcome) -> dict:
        unsettled = [s for s in wrapped.slots if not s["settled"]]
        status, reason = outcome["status"], outcome["reason_code"]
        if status == "accepted" and unsettled:
            status, reason = "failed", "settlement_failed"
        with self.service.store.transaction() as tx:
            current = tx.get(BUCKET, row["id"])
            require(current is not None and current["status"] == "running", "Autonomous row changed during the run")
            if status == "accepted" and current.get("promotion") is None:
                status, reason = "unknown", "promotion_unrecorded"
            current.update(status=status, reason_code=reason,
                           starts={"reserved": len(wrapped.slots), "settled": sum(bool(s["settled"]) for s in wrapped.slots),
                                   "slots": [{k: s.get(k) for k in ("id", "kind", "agent", "outcome", "settled", "settle_error", "operation")}
                                             for s in wrapped.slots]},
                           updated_at=self.clock(), finished_at=self.clock())
            tx.put(BUCKET, row["id"], current)
        self._log(current["stage"], row["id"], status)
        return {**self._receipt(current), "cached": False, "exit_code": 0 if status == "accepted" else 1}

    def _log(self, stage: str, run_id: str, state: str) -> None:
        if self.observer is not None:
            self.observer.emit("operations.autonomous_stage", "observed", correlation_id="autonomous:" + run_id,
                               attributes={"run_id": run_id, "stage": stage, "state": state})


def _safe_binding(binding: dict) -> dict:
    return {k: v for k, v in binding.items() if k != "answer"}


def row_digest(tx, run_id: str):
    row = tx.get(BUCKET, run_id) or {}
    return row.get("packet_digest")


__all__ = ["AutonomousRefused", "AutonomousRun", "BUCKET", "packet_digest"]
