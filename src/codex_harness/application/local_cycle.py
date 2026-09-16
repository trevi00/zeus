"""Bounded, persistent execution loop over one correlation (INV-LOCAL-CYCLE-001).

The cycle reuses the existing message path (bus receive → Workflow.handle → outbox relay → ACK)
and the existing executor entry points (execute_one / decide_one). It adds only a durable policy
row (`local_cycles`) that counts executor starts, records an in-flight marker before each start
and stops on anything that is not a plain success. It never runs the conductor, consumes the
release queue, merges or deploys.
"""
from __future__ import annotations

from codex_harness.application.workflow import ClaimGuardRefused
from codex_harness.domain.model import ContractError, require, utcnow

WORKER = "worker:implementation"
LEAD = "lead:improvement"
ROLES = (WORKER, LEAD)
LEAD_PHASES = {"review_lead"}
OPEN_TASK = {"queued", "retry", "running"}
OPEN_DECISION = {"pending", "retry", "running"}
STOP_STATES = {"retry", "failed", "blocked", "expired", "superseded", "inspection_blocked", "cancelled"}
MESSAGE_DRAIN = 16

# INV-CYCLE-HANDOFF-001: the read-only projection names only these stored fields.
HANDOFF_SCHEMA = "urn:zeus:cycle-handoff:1"
CYCLE_FIELDS = ("id", "correlation_id", "status", "max_executions", "executions", "in_flight",
                "stopped_reason", "last_execution", "created_at", "updated_at")
TARGET_BUCKETS = {"task": "tasks", "decision": "decisions_pending"}
CANDIDATE_FIELDS = ("base", "revision", "tree", "diff_hash")


class LocalCycle:
    """One correlation, one executor start per step, counts that survive restart."""

    def __init__(self, service, executor=None, bus=None, workflow=None):
        self.service, self.executor, self.bus = service, executor, bus
        self.workflow = workflow

    # ----- policy -------------------------------------------------------------------------
    def start(self, cycle_id: str, correlation_id: str, max_executions: int) -> dict:
        require(isinstance(cycle_id, str) and bool(cycle_id.strip()), "Cycle id required")
        require(isinstance(correlation_id, str) and bool(correlation_id.strip()), "Correlation id required")
        require(type(max_executions) is int and max_executions > 0, "max_executions must be a positive integer")
        with self.service.store.transaction() as tx:
            old = tx.get("local_cycles", cycle_id)
            if old:
                # INV-LOCAL-CYCLE-001: the same request is idempotent; a different policy is refused,
                # never overwritten, so a restart cannot reset or enlarge the budget.
                require(old["correlation_id"] == correlation_id and old["max_executions"] == max_executions,
                        "Conflicting cycle policy")
                return old
            row = {"id": cycle_id, "correlation_id": correlation_id, "max_executions": max_executions,
                   "executions": 0, "status": "active", "in_flight": None, "stopped_reason": None,
                   "last_execution": None, "created_at": utcnow(), "updated_at": utcnow()}
            tx.put("local_cycles", cycle_id, row)
            return row

    def status(self, cycle_id: str) -> dict:
        with self.service.store.transaction() as tx:
            row = tx.get("local_cycles", cycle_id)
        require(row is not None, "Unknown cycle")
        return row

    def handoff(self, cycle_id: str) -> dict:
        """Read-only view for the next operating session (INV-CYCLE-HANDOFF-001).

        One read transaction over the cycle row and the CURRENT row its last_execution addresses.
        Nothing is written, published, opened, probed, reset or executed; the target is an
        observation of the row as stored now, never proof of what the historical execution did.
        """
        with self.service.store.transaction() as tx:
            row = tx.get("local_cycles", cycle_id)
            require(row is not None, "Unknown cycle")
            last = row.get("last_execution")
            kind = last.get("kind") if isinstance(last, dict) else None
            target_id = last.get("id") if isinstance(last, dict) else None
            bucket = TARGET_BUCKETS.get(kind) if isinstance(kind, str) else None
            target = tx.get(bucket, target_id) if bucket and isinstance(target_id, str) else None
        cycle = {key: row.get(key) for key in CYCLE_FIELDS}
        return {"schema": HANDOFF_SCHEMA, "authority": "observation_only", "automatic_resume": False,
                "cycle": cycle,
                "remaining_executions": max(0, cycle["max_executions"] - cycle["executions"]),
                "target_record": _target_record(cycle["correlation_id"], last, kind, target_id, target)}

    # ----- one turn -----------------------------------------------------------------------
    def step(self, cycle_id: str) -> dict:
        cycle = self.status(cycle_id)
        if cycle["status"] != "active":
            return {"cycle": cycle, "action": "none", "reason": cycle["status"]}
        if cycle["in_flight"] is not None:
            # A marker left by another process is never released here (INV-LOCAL-CYCLE-001).
            return {"cycle": cycle, "action": "refused", "reason": "in_flight_residue"}
        messages = self._deliver(cycle) if self.bus is not None else []
        cycle = self.status(cycle_id)
        if cycle["status"] != "active":
            return {"cycle": cycle, "action": "messages", "messages": messages, "reason": cycle["stopped_reason"]}
        candidate = self._candidate(cycle)
        if candidate.get("stop"):
            cycle = self._stop(cycle_id, candidate["stop"])
            return {"cycle": cycle, "action": "stopped", "messages": messages, "reason": candidate["stop"]}
        if candidate.get("state"):
            cycle = self._set(cycle_id, status=candidate["state"])
            return {"cycle": cycle, "action": "none", "messages": messages, "reason": candidate["state"]}
        if not candidate.get("agent"):
            return {"cycle": cycle, "action": "none", "messages": messages, "reason": "idle"}
        agent, kind, target = candidate["agent"], candidate["kind"], candidate["id"]
        require(self.executor is not None, "Executor required for a cycle step")
        with self.service.store.transaction() as tx:
            current = tx.get("local_cycles", cycle_id)
            require(current is not None and current["status"] == "active" and current["in_flight"] is None,
                    "Cycle changed before execution")
            if current["executions"] >= current["max_executions"]:
                current.update(status="stopped", stopped_reason="budget_exhausted", updated_at=utcnow())
                tx.put("local_cycles", cycle_id, current)
                return {"cycle": current, "action": "stopped", "messages": messages, "reason": "budget_exhausted"}
            # The slot is taken durably before the executor starts; a crash between here and the
            # settlement below leaves the marker, and the next step refuses rather than re-enters.
            current.update(executions=current["executions"] + 1,
                           in_flight={"agent": agent, "kind": kind, "id": target, "at": utcnow()},
                           updated_at=utcnow())
            tx.put("local_cycles", cycle_id, current)
        # The candidate was chosen outside the claim transaction; the guard makes the existing claim
        # refuse, unclaimed and before any provider entry, anything but this row in this correlation.
        expected = {"id": target, "correlation_id": current["correlation_id"],
                    "statuses": {"queued"} if kind == "task" else {"pending"}}
        result = None
        try:
            result = (self.executor.execute_one(agent, expected=expected) if kind == "task"
                      else self.executor.decide_one(agent, expected=expected))
        except ClaimGuardRefused as exc:
            cycle = self._settle(cycle_id, {"agent": agent, "kind": kind, "id": target, "status": "refused",
                                            "error": str(exc)}, "claim_guard_refused")
            self._flush()
            return {"cycle": cycle, "action": "refused", "messages": messages, "reason": cycle["stopped_reason"]}
        except Exception as exc:  # the executor already recorded the task outcome; the cycle only stops
            cycle = self._settle(cycle_id, {"agent": agent, "kind": kind, "id": target, "status": "exception",
                                            "error": type(exc).__name__}, "exception:" + type(exc).__name__)
            self._flush()
            return {"cycle": cycle, "action": "executed", "messages": messages, "reason": cycle["stopped_reason"]}
        self._flush()
        summary = {"agent": agent, "kind": kind, "id": target,
                   "status": result.get("status") if isinstance(result, dict) else None,
                   "claimed": result is not None, "result_id": result.get("id") if isinstance(result, dict) else None}
        stop, state = self._outcome(result, kind)
        cycle = self._settle(cycle_id, summary, stop, state)
        return {"cycle": cycle, "action": "executed", "messages": messages,
                "reason": cycle["stopped_reason"] or cycle["status"], "execution": summary}

    # ----- helpers ------------------------------------------------------------------------
    def _flush(self):
        if self.bus is not None:
            self.service.flush_outbox(self.bus)

    def _deliver(self, cycle) -> list[dict]:
        """Existing serve semantics: handle, relay outbox, then ACK. A foreign message is left
        pending (not ACKed, not dead-lettered) and stops the cycle; a notice stops it after ACK."""
        workflow = self.workflow
        receipts = []
        for agent in ROLES:
            consumer = f"{agent}:cycle:{cycle['id']}"
            for _ in range(MESSAGE_DRAIN):
                row = self.bus.receive(agent, consumer)
                if not row:
                    break
                entry_id, fields = row
                try:
                    message = self.bus.decode(fields)
                    require(message["who"]["recipient"] == agent, "Message routed to wrong agent")
                    self.service.org.authorize(message)
                except (ContractError, KeyError, ValueError) as exc:
                    self.bus.dead_letter(agent, entry_id, fields, str(exc))
                    receipts.append({"entry_id": entry_id, "rejected": type(exc).__name__})
                    continue
                if message["correlation_id"] != cycle["correlation_id"]:
                    receipts.append({"entry_id": entry_id, "message_id": message["message_id"],
                                     "refused": "foreign_correlation"})
                    self._stop(cycle["id"], "foreign_correlation")
                    return receipts
                if message["type"] == "incident.report":
                    result = self.service.record_incident(message)
                else:
                    result = workflow.handle(message)
                self.service.flush_outbox(self.bus)
                self.bus.ack(agent, entry_id)
                receipts.append({"entry_id": entry_id, "message_id": message["message_id"],
                                 "type": message["type"], "handled": bool(result)})
                if message["type"] == "execution.notice":
                    self._stop(cycle["id"], "execution_notice:" + str(message["what"]["details"].get("reason_code")))
                    return receipts
        return receipts

    def _candidate(self, cycle) -> dict:
        """Choose at most one executor entry; fail closed on anything the existing claim policy
        could pick instead of this correlation (INV-LOCAL-CYCLE-001)."""
        correlation = cycle["correlation_id"]
        with self.service.store.transaction() as tx:
            tasks = [t for t in tx.scan("tasks") if t.get("agent") in ROLES]
            decisions = [d for d in tx.scan("decisions_pending") if d.get("actor") in ROLES or d.get("actor") == "conductor"]
        mine_tasks = [t for t in tasks if _correlation(t) == correlation]
        mine_decisions = [d for d in decisions if _correlation(d) == correlation and d.get("actor") in ROLES]
        for row in mine_tasks + mine_decisions:
            if row.get("status") == "running":
                return {"stop": "in_flight_residue"}
        for row in mine_tasks + mine_decisions:
            if row.get("status") in STOP_STATES:
                return {"stop": row["status"] + ":" + str(row.get("error") or row.get("phase") or row["id"])}
        for row in mine_decisions:
            if row.get("status") in OPEN_DECISION and row.get("phase") not in LEAD_PHASES:
                return {"stop": "diagnose_pending" if row.get("phase") == "diagnose" else "unsupported_phase:" + str(row.get("phase"))}
        foreign = [t for t in tasks if _correlation(t) != correlation and t.get("status") in OPEN_TASK]
        foreign += [d for d in decisions if d.get("actor") in ROLES and _correlation(d) != correlation
                    and d.get("status") in OPEN_DECISION]
        if foreign:
            return {"stop": "foreign_queue:" + foreign[0]["id"]}
        for task in sorted(mine_tasks, key=lambda t: (str(t.get("created_at")), t["id"])):
            if task["status"] == "queued":
                return {"agent": task["agent"], "kind": "task", "id": task["id"]}
        for decision in sorted(mine_decisions, key=lambda d: d["id"]):
            if decision["status"] == "pending":
                return {"agent": decision["actor"], "kind": "decision", "id": decision["id"]}
        if any(d.get("actor") == "conductor" and _correlation(d) == correlation and d.get("status") in OPEN_DECISION
               for d in decisions):
            return {"state": "awaiting_operator"}
        return {}

    @staticmethod
    def _outcome(result, kind):
        if result is None:
            return "no_execution_claimed", None
        status = result.get("status")
        if status != "succeeded":
            return "execution_" + str(status), None
        if kind == "decision" and result.get("phase") == "review_lead" and (result.get("result") or {}).get("accepted") is True:
            return None, "awaiting_operator"
        return None, None

    def _settle(self, cycle_id, summary, stop=None, state=None):
        with self.service.store.transaction() as tx:
            current = tx.get("local_cycles", cycle_id)
            require(current is not None and current["in_flight"] is not None, "Cycle in-flight marker missing")
            current.update(in_flight=None, last_execution={**summary, "at": utcnow()}, updated_at=utcnow())
            if stop:
                current.update(status="stopped", stopped_reason=stop)
            elif state:
                current.update(status=state)
            tx.put("local_cycles", cycle_id, current)
            return current

    def _stop(self, cycle_id, reason):
        return self._set(cycle_id, status="stopped", stopped_reason=reason)

    def _set(self, cycle_id, **fields):
        with self.service.store.transaction() as tx:
            current = tx.get("local_cycles", cycle_id)
            require(current is not None, "Unknown cycle")
            current.update(**fields, updated_at=utcnow())
            tx.put("local_cycles", cycle_id, current)
            return current


def _correlation(row) -> str | None:
    message = row.get("message")
    return message.get("correlation_id") if isinstance(message, dict) else None


def _target_record(correlation, last, kind, target_id, target) -> dict:
    """Availability of the current target row plus whitelisted metadata only when it matches.
    Task input, prompt, summary, output, raw error, messages, settings and paths never leave."""
    head = {"kind": kind if isinstance(kind, str) else None,
            "id": target_id if isinstance(target_id, str) else None}
    if not isinstance(last, dict):
        return {"availability": "none", **head}
    if kind not in TARGET_BUCKETS:
        return {"availability": "unsupported_kind", **head}
    if target is None:
        return {"availability": "missing", **head}
    if _correlation(target) != correlation:
        return {"availability": "correlation_mismatch", **head}
    result = target.get("result")
    result = result if isinstance(result, dict) else {}
    candidate = result.get("candidate")
    candidate = ({key: _string(candidate.get(key)) for key in CANDIDATE_FIELDS}
                 if isinstance(candidate, dict) else None)
    inspection = result.get("evidence_inspection")
    accepted = result.get("accepted") if kind == "decision" else None
    return {"availability": "found", **head,
            "status": _string(target.get("status")),
            "attempt": _integer(target.get("attempt")),
            "generation": _integer(target.get("generation")),
            "phase": _string(target.get("phase")),
            "result": {"candidate": candidate,
                       "execution_ref": _string(result.get("execution_ref")),
                       "evidence_verdict": _string(inspection.get("verdict")) if isinstance(inspection, dict) else None,
                       "accepted": accepted if isinstance(accepted, bool) else None}}


def _string(value) -> str | None:
    return value if isinstance(value, str) else None


def _integer(value) -> int | None:
    return value if type(value) is int else None
