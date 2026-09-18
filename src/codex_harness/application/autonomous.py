"""One autonomous cycle: research, immutable packet, independent debate roles, existing Operation v2
implementation/review, evidence-bound promotion (INV-AUTONOMOUS-001).

A durable `autonomous_runs` row owns the run id. Every role is one fresh task from the conductor to a
dedicated lead through the outbox and bus, claimed and executed by the existing executor under the
machine call budget, then bound to its persisted row AND to the execution artifact behind its
`execution_ref` (answer bytes, settled reservation of that task/generation/attempt/stage, base
revision and exact input evidence) through the injected evidence port. The packet is frozen through
the existing DebateSessions with origin `executor_bound`; the operator `dge submit` cannot add events
to it. The approved design launches the existing Operation v2 with the remaining absolute deadline.
Promotion happens only after re-reading the exact accepted records and re-verifying the worker and
reviewer artifacts in the same transaction that writes the graph and the receipt, before the deadline.
Fixed round, fixed start cap, no rework, no retry, no takeover.
"""
from __future__ import annotations

import time

from codex_harness.application.dge import SESSIONS, DebateSessions, DgeRefused
from codex_harness.application.evidence_inspection import EvidenceInspections
from codex_harness.application.local_cycle import (
    MESSAGE_DRAIN,
    flush_outbox,
    observe_accepted,
    observe_acknowledged,
    observe_received,
    observe_rejected,
)
from codex_harness.application.operation import BudgetedExecutor, BudgetRefused, Operation
from codex_harness.application.promotion import promote
from codex_harness.domain.autonomous import (
    ARBITER,
    CONDUCTOR,
    DEBATE_ROLES,
    ORIGIN_EXECUTOR,
    PROPOSER,
    RECEIPT_SCHEMA,
    RESEARCHER,
    ROLE_ACTION,
    TERMINAL,
    TRUST,
    correlation_id,
    event_from_role,
    evidence_ref_for,
    execution_evidence,
    independent_roles,
    manifest_digest,
    operation_manifest,
    packet_from_research,
    role_binding,
    role_message_id,
    session_id,
    verified_graph,
)
from codex_harness.domain.council import profile
from codex_harness.domain.dge import expired, packet_digest
from codex_harness.domain.model import ContractError, envelope, require, utcnow
from codex_harness.domain.operation import WORKER

BUCKET = "autonomous_runs"
OPERATIONS = "operations"
RESERVATIONS = "invocation_reservations"
OUTCOME_BY_REASON = {"deadline_expired": "expired", "start_cap_reached": "exhausted", "budget_exhausted": "exhausted",
                     "needs_user": "needs_user", "design_needs_research": "needs_research", "design_rejected": "rejected",
                     "design_exhausted": "exhausted", "review_rejected": "rejected", "operation_exhausted": "exhausted",
                     "operation_unknown": "unknown"}
SLOT_FIELDS = ("id", "kind", "agent", "provider", "outcome", "settled", "settle_error", "operation")
BLOCKER_RULE = ("critical only: concrete reachable trigger, cited packet evidence, affected fixed criterion, "
                "material impact and minimal mitigation; styling, optional refactoring and unsupported "
                "hypotheticals are minor and never block")


class AutonomousRefused(ContractError):
    def __init__(self, reason_code: str):
        super().__init__("autonomous refused: " + reason_code)
        self.reason_code = reason_code


def provider_labels(model: str):
    """Actual ledger labels: dedicated design leads run on Codex routing, the worker task on Claude,
    every decision on Codex routing."""
    return lambda kind, agent: ("claude", model) if kind == "task" and agent == WORKER else ("codex", "model_routing")


class AutonomousRun:
    def __init__(self, service, executor=None, bus=None, workflow=None, budget=None, collector=None,
                 verify_sources=None, repository=None, observer=None, clock=utcnow, evidence=None):
        self.service, self.executor, self.bus, self.workflow = service, executor, bus, workflow
        self.budget, self.collector, self.verify_sources = budget, collector, verify_sources
        self.repository, self.observer, self.clock, self.evidence = repository, observer, clock, evidence

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
                "design", "operation", "residuals", "promotion", "durations", "history", "claimed_at", "updated_at", "finished_at",
                "topology", "snapshot", "report")  # INV-COUNCIL-001: v2 receipts; None on v1 rows
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
            shape = profile(manifest)  # v1: six starts and lead:<role>; v2: seven starts and the council agents
            row = {"id": run_id, "status": "running", "stage": "research", "reason_code": None, **binding,
                   "correlation_id": correlation_id(manifest), "session_id": session, "operation_id": operation,
                   "deadline": manifest["deadline"], "max_starts": shape["max_starts"], "topology": shape["topology"],
                   "starts": {"reserved": 0, "settled": 0, "slots": []},
                   "invocations": {}, "roles": {}, "packet_digest": None, "ssot_decision": None, "design": None,
                   "operation": None, "residuals": {"critical": [], "minor": []}, "promotion": None, "durations": {},
                   "history": [{"at": now, "from": None, "to": "research"}], "claimed_at": now, "updated_at": now, "finished_at": None}
            tx.put(BUCKET, run_id, row)
        return {"row": row, "cached": False}

    def _transition(self, run_id: str, expected_stage: str, stage: str | None = None, merge: dict | None = None, **fields) -> dict:
        """Every write records the prior state it expects; a changed row stops the run. `merge` adds
        keys into the CURRENT row's dict fields (durations, roles, invocations), never a stale copy."""
        with self.service.store.transaction() as tx:
            current = tx.get(BUCKET, run_id)
            if not (current and current["status"] == "running" and current["stage"] == expected_stage):
                raise AutonomousRefused("run_state_changed")
            now = self.clock()
            if stage is not None and stage != expected_stage:
                current["history"].append({"at": now, "from": expected_stage, "to": stage})
                current["stage"] = stage
            for key, value in (merge or {}).items():
                current[key] = {**(current.get(key) or {}), **value}
            current.update(**fields, updated_at=now)
            tx.put(BUCKET, run_id, current)
            return current

    # ----- run ----------------------------------------------------------------------------
    def run(self, manifest: dict, identity: dict, goal: dict) -> dict:
        claimed = self.claim(manifest, identity, goal)
        if claimed["cached"]:
            return {**self._receipt(claimed["row"]), "cached": True, "exit_code": 0 if claimed["row"]["status"] == "accepted" else 1}
        row = claimed["row"]
        require(self.executor is not None and self.budget is not None and self.bus is not None and self.workflow is not None
                and self.evidence is not None, "Autonomous run needs an executor, a call budget, a bus, a workflow and an evidence port")
        wrapped = BudgetedExecutor(self.executor, self.budget, manifest["budget"], "autonomous:" + manifest["id"],
                                   manifest["claude"]["model"], labels=provider_labels(manifest["claude"]["model"]))
        try:
            outcome = self._pipeline(manifest, identity, goal, row, wrapped)
        except AutonomousRefused as exc:
            outcome = {"status": OUTCOME_BY_REASON.get(exc.reason_code, "failed"), "reason_code": exc.reason_code}
        except Exception as exc:
            outcome = {"status": "failed", "reason_code": "exception:" + type(exc).__name__}
        return self._finish(row, wrapped, outcome)

    def _pipeline(self, manifest, identity, goal, row, wrapped) -> dict:
        """v1 flow, unchanged: research -> packet -> proposer/attacker/arbiter -> implementation -> promotion."""
        run_id, base = row["id"], manifest["base_revision"]
        research, frozen, sessions, digest_value = self._freeze_packet(manifest, goal, row, wrapped)
        packet, prior, version, bindings = frozen["packet"], {}, 0, {RESEARCHER: research}
        for role in DEBATE_ROLES:
            self._transition(run_id, "packet" if role == PROPOSER else DEBATE_ROLES[DEBATE_ROLES.index(role) - 1], role)
            binding = self._role(manifest, row, wrapped, role, {
                "role": role, "run_id": run_id, "base_revision": base, "packet_digest": digest_value, "packet": packet,
                "ssot": frozen["ssot"], "round": 1, "prior_outputs": prior, "acceptance_criteria": manifest["plan"]["acceptance_criteria"],
                "blocker_rule": BLOCKER_RULE})
            bindings[role] = binding
            try:
                independent_roles(bindings)  # no role resumes another role's provider session
                event = event_from_role(role, binding["answer"], digest_value, version, binding["task_id"])
                recorded = sessions.submit(row["session_id"], event, owner=run_id, binding=_safe_binding(binding))
            except DgeRefused as exc:
                raise AutonomousRefused("debate_refused:" + exc.reason_code) from exc
            except ContractError as exc:
                raise AutonomousRefused(str(exc) if str(exc) == "role_session_shared" else "debate_refused:" + type(exc).__name__) from exc
            prior[role] = {"event_id": event["id"], "payload": event["payload"], "binding": _safe_binding(binding)}
            version = recorded["session"]["version"]
        return self._implement_and_promote(manifest, identity, goal, row, wrapped, research, prior, recorded["session"], ARBITER)

    def _freeze_packet(self, manifest, goal, row, wrapped):
        """Research at base, then the immutable packet through the existing validator and Git source check."""
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
        return research, frozen, sessions, digest_value

    def _implement_and_promote(self, manifest, identity, goal, row, wrapped, research, prior, design, last_stage,
                               council=None, before_implementation=None) -> dict:
        """Approved design -> existing Operation v2 -> same-transaction promotion. `before_implementation`
        and `council` are the v2 snapshot guard and promotion recheck (INV-COUNCIL-001); None for v1."""
        run_id = row["id"]
        digest_value = design["packet_digest"]
        self._transition(run_id, last_stage, last_stage, design={k: design.get(k) for k in ("id", "state", "packet_digest", "decision_event_id", "version")},
                         residuals=self._residuals(row["session_id"]))
        if design["state"] != "design_approved":
            raise AutonomousRefused("design_" + {"rejected": "rejected", "needs_research": "needs_research"}.get(design["state"], "exhausted"))
        if len(wrapped.slots) + 2 > profile(manifest)["max_starts"]:
            raise AutonomousRefused("start_cap_reached")
        self._check_deadline(manifest)
        if before_implementation is not None:
            before_implementation()
        self._transition(run_id, last_stage, "implementation")
        self._log("implementation", run_id, "started")
        started = time.monotonic()
        operation = Operation(self.service, self.executor, self.bus, self.workflow, self.budget, self.collector,
                              observer=self.observer)
        # The same absolute deadline is checked before the worker and the reviewer start; never reset.
        receipt = operation.run(operation_manifest(manifest, digest_value), identity, goal, deadline=manifest["deadline"],
                                clock=self.clock, labels=provider_labels(manifest["claude"]["model"]))
        wrapped.slots.extend([{**s, "operation": receipt["id"]} for s in receipt["calls"]["slots"]])
        self._transition(run_id, "implementation", "implementation",
                         merge={"durations": {"implementation": time.monotonic() - started},
                                "invocations": self._operation_invocations(receipt)},
                         operation={k: receipt.get(k) for k in ("id", "status", "reason_code", "task_id", "decision_id", "evidence")})
        if receipt["status"] != "accepted":
            if receipt.get("reason_code") == "deadline_expired":
                raise AutonomousRefused("deadline_expired")
            raise AutonomousRefused("review_rejected" if receipt["status"] == "rejected" else "operation_" + receipt["status"])
        self._check_deadline(manifest)  # a late success authorizes nothing
        self._transition(run_id, "implementation", "promotion")
        started = time.monotonic()
        promotion = self._promote(manifest, goal, row, receipt, research, prior, council)
        self._transition(run_id, "promotion", None, merge={"durations": {"promotion": time.monotonic() - started}})
        return {"status": "accepted", "reason_code": "promoted", "promotion": promotion}

    # ----- roles --------------------------------------------------------------------------
    def _role(self, manifest, row, wrapped, role, details) -> dict:
        shape = profile(manifest)
        run_id, correlation, agent = row["id"], row["correlation_id"], shape["agents"][role]
        self._check_deadline(manifest)
        if len(wrapped.slots) >= shape["max_starts"]:
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
        flush_outbox(self.service, self.bus, self.observer)
        self._deliver(agent, correlation)
        expected = {"id": message["message_id"], "correlation_id": correlation, "statuses": {"queued"}}
        try:
            result = wrapped.execute_one(agent, expected=expected)
        except BudgetRefused as exc:
            raise AutonomousRefused("budget_exhausted") from exc
        flush_outbox(self.service, self.bus, self.observer)
        if any(not s["settled"] for s in wrapped.slots):
            raise AutonomousRefused("settlement_failed")
        if result is None:
            raise AutonomousRefused("no_execution_claimed")
        if result.get("status") != "succeeded":
            raise AutonomousRefused("role_" + str(result.get("status")))
        with self.service.store.transaction() as tx:
            task = tx.get("tasks", message["message_id"])
            invocations = [r for r in tx.scan(RESERVATIONS) if r.get("task_id") == message["message_id"]]
            try:
                binding = role_binding(task, role=role, base_revision=manifest["base_revision"], correlation=correlation, agent=agent)
                # The stored row alone is not proof: the artifact behind execution_ref must be this
                # execution's own answer, reservation, stage, base and exact input evidence.
                binding["evidence"] = self._verify_execution(tx, task, "tasks", "dge:" + role, manifest["base_revision"],
                                                             evidence_ref_for(details), exact=True)
            except ContractError as exc:
                raise AutonomousRefused(str(exc)) from exc
        current = self._transition(run_id, role if role != RESEARCHER else "research", None)
        self._transition(run_id, current["stage"], None,
                         merge={"roles": {role: _safe_binding(binding)}, "invocations": {role: len(invocations)},
                                "durations": {role: time.monotonic() - started}})
        self._log(role, run_id, "succeeded")
        return binding

    def _verify_execution(self, tx, record, bucket, stage, basis_revision, evidence_ref=None, *, exact=False) -> dict:
        """Load the execution artifact through the injected port and check it against the record and
        the authoritative reservation row in the caller's transaction (fixed codes only)."""
        result = record.get("result") if isinstance(record, dict) and isinstance(record.get("result"), dict) else {}
        try:
            artifact = self.evidence.document(result.get("execution_ref"))
        except ContractError as exc:
            raise ContractError(getattr(exc, "reason_code", "evidence_invalid")) from exc
        except Exception as exc:
            raise ContractError("evidence_missing") from exc
        reservation_id = (artifact.get("invocation") or {}).get("reservation") if isinstance(artifact, dict) else None
        reservation = tx.get(RESERVATIONS, reservation_id) if isinstance(reservation_id, str) else None
        return execution_evidence(record, artifact, reservation, bucket=bucket, stage=stage, basis_revision=basis_revision,
                                  evidence_ref=evidence_ref, exact=exact)

    def _operation_invocations(self, receipt) -> dict:
        counts = {}
        with self.service.store.transaction() as tx:
            rows = tx.scan(RESERVATIONS)
        for label, bucket, key in (("implementation", "tasks", receipt.get("task_id")), ("review", "decisions_pending", receipt.get("decision_id"))):
            if isinstance(key, str):
                counts[label] = len([r for r in rows if r.get("bucket") == bucket and r.get("task_id") == key])
        return counts

    def _deliver(self, agent: str, correlation: str) -> list:
        """Existing serve semantics for the dedicated lead: handle, relay outbox, ACK. A foreign message
        is left pending and stops the run; nothing is dead-lettered on its behalf. Returns the handled
        messages so a caller can prove a specific report went through the workflow."""
        consumer, handled = agent + ":autonomous", []
        for _ in range(MESSAGE_DRAIN):
            row = self.bus.receive(agent, consumer)
            if not row:
                return handled
            entry_id, fields = row
            message = None
            try:
                message = self.bus.decode(fields)
                observe_received(self.observer, entry_id, message)
                require(message["who"]["recipient"] == agent, "Message routed to wrong agent")
                self.service.org.authorize(message)
            except (ContractError, KeyError, ValueError) as exc:
                self.bus.dead_letter(agent, entry_id, fields, str(exc))
                observe_rejected(self.observer, entry_id, message, type(exc).__name__, dead_letter=True)
                continue
            if message["correlation_id"] != correlation:
                observe_rejected(self.observer, entry_id, message, "foreign_message", dead_letter=False)
                raise AutonomousRefused("foreign_message")
            result = self.workflow.handle(message)
            observe_accepted(self.observer, message, result)
            flush_outbox(self.service, self.bus, self.observer)
            self.bus.ack(agent, entry_id)
            observe_acknowledged(self.observer, entry_id, message)
            handled.append(message)
        return handled

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
    def _promote(self, manifest, goal, row, receipt, research, prior, council=None) -> dict:
        """Re-read the exact records and re-verify the worker and reviewer artifacts inside the
        promotion transaction; the receipt, an accepted row or a matching revision alone is insufficient.
        `council` (INV-COUNCIL-001, v2 only) is a callable run inside the same transaction that rechecks
        the DBA, snapshot and report provenance and returns the extra design refs and receipt evidence;
        the v1 worker/reviewer gates above and below it are unchanged."""
        run_id = row["id"]
        debate_roles = profile(manifest)["debate_roles"]
        with self.service.store.transaction() as tx:
            if expired(manifest["deadline"], self.clock()):
                raise AutonomousRefused("deadline_expired")
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
            try:
                # The persisted artifacts must be the executions that produced the stored answers: the
                # worker's answer and the reviewer's verdict (`accepted` must be the artifact's own).
                # The worker executed at the implementation base; the independent review executed at the
                # reviewed candidate commit. The executor records that context binding (with project skills
                # configured, at stage None too), so each artifact is checked against its own basis.
                implementation = self._verify_execution(tx, task, "tasks", None, manifest["base_revision"])
                review = self._verify_execution(tx, decision, "decisions_pending", None, reviewed["revision"])
                if (self.evidence.document(verdict.get("execution_ref")).get("answer") or {}).get("accepted") is not True:
                    raise ContractError("evidence_answer_mismatch")
            except ContractError as exc:
                raise AutonomousRefused("promotion_evidence_unproven:" + str(exc).split(":")[-1].strip()) from exc
            session = tx.get(SESSIONS, row["session_id"])
            if not (session and session["state"] == "design_approved" and session.get("owner") == run_id
                    and session.get("origin") == ORIGIN_EXECUTOR and session["packet_digest"] == row_digest(tx, run_id)):
                raise AutonomousRefused("promotion_design_unproven")
            extra = council(tx) if council is not None else {"refs": None, "evidence": {}}
            refs = {"base_revision": manifest["base_revision"], "goal": {"path": goal["path"], "sha256": goal["sha256"]},
                    "packet_digest": session["packet_digest"], "research_execution_ref": research["execution_ref"],
                    "research_task_id": research["task_id"], "session_id": session["id"],
                    "decision_event_id": session["decision_event_id"], "council": extra["refs"],
                    "role_bindings": {role: prior[role]["binding"] for role in debate_roles},
                    "candidate": {k: candidate.get(k) for k in ("revision", "base", "tree", "diff_hash")},
                    "implementation_task_id": task["id"], "implementation_execution_ref": result.get("execution_ref"),
                    "implementation_reservation_id": implementation["reservation_id"],
                    "decision_id": decision["id"], "review_execution_ref": verdict.get("execution_ref"),
                    "review_reservation_id": review["reservation_id"],
                    "inspection_id": inspection["id"], "operation_id": operation["id"],
                    "verification_scope": {"review": "independent read-only review at the candidate commit",
                                           "inspection": "all_checked command replays for the worker's test claims",
                                           "not_verified": ["semantic truth of research claims", "merge", "deploy"]}}
            graph = verified_graph(run_id, refs)
            promotion = promote(tx, run_id, graph, {**{k: refs[k] for k in ("implementation_task_id", "implementation_reservation_id",
                                                                                 "decision_id", "review_reservation_id", "inspection_id",
                                                                                 "operation_id", "session_id", "packet_digest")},
                                                    **extra["evidence"]})
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
                                   "slots": [{k: s.get(k) for k in SLOT_FIELDS} for s in wrapped.slots]},
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


__all__ = ["AutonomousRefused", "AutonomousRun", "BUCKET", "packet_digest", "provider_labels"]
