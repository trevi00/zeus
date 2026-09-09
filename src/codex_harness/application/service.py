from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
from uuid import uuid4

from codex_harness.domain.model import (
    Incident,
    Organization,
    digest,
    envelope,
    hook_apply,
    require,
    utcnow,
)
from codex_harness.domain.policy import POLICY
from codex_harness.ports import MessageBus, Store


class Harness:
    def __init__(self, store: Store, organization: Organization):
        organization.validate()
        self.store = store
        self.org = organization

    def record_incident(self, message: dict, *, independent_occurrence: str | None = None,
                        transaction=None) -> dict:
        self.org.authorize(message)
        require(message["type"] == "incident.report", "Expected incident.report")
        details = message["what"]["details"]
        require(set(details) == {"occurrence_id", "root_cause", "scope", "evidence_refs"},
                "Invalid incident fields")
        require(isinstance(details["evidence_refs"], list), "Evidence refs must be an array")
        incident = Incident(details["occurrence_id"], details["root_cause"], details["scope"],
                            tuple(details["evidence_refs"]))
        body = asdict(incident)
        body["evidence_refs"] = list(incident.evidence_refs)
        body["fingerprint"] = incident.fingerprint
        if independent_occurrence is not None:
            require(isinstance(independent_occurrence, str) and bool(independent_occurrence.strip()),
                    "Independent occurrence must identify a task")
            body["independent_occurrence"] = independent_occurrence
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            receipt = tx.get("inbox", message["message_id"])
            if receipt:
                require(receipt["hash"] == digest(message), "Message ID reused with different content")
                require(receipt.get("independent_occurrence") == independent_occurrence,
                        "Message ID reused with different occurrence authority")
                return receipt["result"]
            previous = tx.get("incidents", incident.occurrence_id)
            require(previous is None or previous == body, "Occurrence ID reused with different content")
            tx.put("incidents", incident.occurrence_id, body)
            occurrences = [r for r in tx.scan("incidents") if r["fingerprint"] == incident.fingerprint]
            # INV-RECURRENCE-001: retries retain evidence but are not independent incidents.
            independent = {r.get("independent_occurrence", r["occurrence_id"]) for r in occurrences}
            new_independent = previous is None and not any(
                r["occurrence_id"] != incident.occurrence_id
                and r.get("independent_occurrence", r["occurrence_id"])
                == body.get("independent_occurrence", incident.occurrence_id) for r in occurrences)
            hook_id = "hook-" + incident.fingerprint[:24]
            created = False
            existing = tx.get("hooks", hook_id)
            update_required = existing and existing["status"] == "active" and new_independent
            if len(independent) >= POLICY.recurrence_threshold and (existing is None or update_required):
                hook = {"id": hook_id, "fingerprint": incident.fingerprint, "status": "required",
                        "scope": incident.scope, "root_cause": incident.root_cause,
                        "occurrences": sorted(r["occurrence_id"] for r in occurrences),
                        "evidence_refs": sorted({e for r in occurrences for e in r["evidence_refs"]}),
                        "version": 1, "spec": None, "revision": None, "author": None,
                        "reviews": [], "canary": None}
                if update_required:
                    hook["version"] = existing["version"]
                    hook["previous_active"] = {k: v for k, v in existing.items() if k != "previous_active"}
                tx.put("hooks", hook_id, hook)
                lead = self.org.actor(message["who"]["recipient"])
                notification = envelope("hook.required", lead.id, lead.parent or "conductor",
                                        "implement_hook", {"hook_id": hook_id,
                                        "evidence_refs": sorted({e for r in occurrences
                                                                for e in r["evidence_refs"]})},
                                        message["correlation_id"], message["message_id"])
                if lead.role == "conductor":
                    notification = envelope("task.assign", lead.id, "lead:improvement", "plan",
                                            {"objective": "Implement mandatory recurrence hook", "hook": hook,
                                             "importance": "important"},
                                            message["correlation_id"], message["message_id"])
                self.org.authorize(notification)
                tx.put("outbox", notification["message_id"], {"message": notification, "sent": False})
                tx.put("events", str(uuid4()), {"type": "hook.required", "hook_id": hook_id,
                                               "at": utcnow()})
                created = True
            result = {"occurrences": len(independent), "duplicate_occurrence": previous is not None,
                      "hook_id": hook_id if len(independent) >= POLICY.recurrence_threshold else None, "hook_created": created}
            tx.put("inbox", message["message_id"], {"hash": digest(message), "result": result,
                                                   "independent_occurrence": independent_occurrence})
            return result

    def get_hook(self, hook_id: str) -> dict:
        with self.store.transaction() as tx:
            hook = tx.get("hooks", hook_id)
            require(hook is not None, "Hook not found")
            return hook

    def propose(self, hook_id: str, actor: str, spec: dict, revision: str) -> dict:
        self.org.actor(actor, "worker")
        require(bool(revision), "Candidate revision required")
        hook_apply(spec, [], "windows")
        with self.store.transaction() as tx:
            hook = tx.get("hooks", hook_id)
            require(hook is not None and hook["status"] in {"required", "candidate", "rejected"},
                    "Cannot replace this hook")
            hook.update(status="candidate", spec=spec, revision=revision, author=actor,
                        version=hook["version"] + 1, reviews=[], canary=None)
            tx.put("hooks", hook_id, hook)
            tx.put("events", str(uuid4()), {"type": "hook.proposed", "hook_id": hook_id,
                                           "revision": revision, "spec_hash": digest(spec), "at": utcnow()})
            return hook

    def review(self, hook_id: str, actor: str, revision: str, spec_hash: str,
               passed: bool, evidence_ref: str, *, transaction=None) -> dict:
        reviewer = self.org.actor(actor)
        require(type(passed) is bool, "Review verdict must be boolean")
        require(reviewer.role in {"lead", "conductor"} and bool(evidence_ref), "Invalid reviewer/evidence")
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            hook = tx.get("hooks", hook_id)
            require(hook is not None and hook["status"] in {"candidate", "reviewed"}, "Not reviewable")
            require(hook["revision"] == revision and digest(hook["spec"]) == spec_hash, "Stale review")
            author = self.org.actor(hook["author"], "worker")
            if reviewer.role == "lead":
                require(author.parent == actor, "Only the author's lead may review")
            else:
                require(any(r["role"] == "lead" and r["passed"] for r in hook["reviews"]),
                        "Lead review must precede conductor review")
            require(not any(r["actor"] == actor for r in hook["reviews"]), "Duplicate review")
            hook["reviews"].append({"actor": actor, "role": reviewer.role, "passed": passed,
                                    "revision": revision, "spec_hash": spec_hash,
                                    "evidence_ref": evidence_ref})
            if not passed:
                hook["status"] = "rejected"
            elif reviewer.role == "conductor":
                hook["status"] = "reviewed"
            tx.put("hooks", hook_id, hook)
            return hook

    def record_canary(self, hook_id: str, revision: str, spec_hash: str, checks: dict) -> dict:
        required_checks = {"reproduction", "normal_case", "cli_start"}
        require(set(checks) == required_checks and all(type(v) is bool for v in checks.values()),
                "Canary needs reproduction, normal_case, cli_start booleans")
        with self.store.transaction() as tx:
            hook = tx.get("hooks", hook_id)
            require(hook is not None and hook["status"] == "reviewed", "Reviews must precede canary")
            require(hook["revision"] == revision and digest(hook["spec"]) == spec_hash, "Stale canary")
            hook["canary"] = {"checks": checks, "revision": revision, "spec_hash": spec_hash}
            hook["status"] = "verified" if all(checks.values()) else "rejected"
            tx.put("hooks", hook_id, hook)
            return hook

    def activate(self, hook_id: str, *, transaction=None) -> dict:
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            hook = tx.get("hooks", hook_id)
            require(hook is not None and hook["status"] == "verified", "Candidate not verified")
            # @invariant INV-RELEASE-001: activation is bound to the reviewed artifact.
            require(hook["canary"]["spec_hash"] == digest(hook["spec"]), "Artifact changed after canary")
            hook["status"] = "active"
            tx.put("hooks", hook_id, hook)
            tx.put("events", str(uuid4()), {"type": "hook.activated", "hook_id": hook_id,
                                           "revision": hook["revision"], "at": utcnow()})
            return hook

    def rollback(self, hook_id: str, reason: str) -> None:
        require(bool(reason), "Rollback requires reason")
        with self.store.transaction() as tx:
            hook = tx.get("hooks", hook_id)
            require(hook is not None and hook["status"] == "active", "Hook not active")
            hook = hook.get("previous_active") or {**hook, "status": "rolled_back"}
            tx.put("hooks", hook_id, hook)
            tx.put("events", str(uuid4()), {"type": "hook.rolled_back", "hook_id": hook_id,
                                           "reason": reason, "at": utcnow()})

    def prepare_command(self, argv: list[str], platform: str) -> list[str]:
        hooks = self.active_hooks()
        matches = [h for h in hooks if hook_apply(h["spec"], argv, platform) != argv]
        require(len(matches) <= 1, "Conflicting active hooks; explicit resolution required")
        return hook_apply(matches[0]["spec"], argv, platform) if matches else list(argv)

    def active_hooks(self) -> list[dict]:
        with self.store.transaction() as tx:
            hooks = sorted(tx.scan("hooks"), key=lambda x: x["id"])
        return [active for h in hooks
                if (active := h if h["status"] == "active" else h.get("previous_active"))]

    def checkpoint(self, agent: str, expected_generation: int, state: dict, execution: dict | None = None) -> dict:
        self.org.actor(agent)
        require(all(state.get(k) for k in ("next_action", "source_revision", "graph_snapshot")),
                "Incomplete checkpoint")
        with self.store.transaction() as tx:
            if execution:
                from codex_harness.application.workflow import Workflow

                Workflow(self.store, self.org)._owned(tx, execution)
            old = tx.get("sessions", agent) or {"generation": 0}
            require(old["generation"] == expected_generation, "Stale session writer")
            record = {"agent_id": agent, "generation": expected_generation + 1,
                      "session_id": str(uuid4()), "checkpoint": state}
            tx.put("sessions", agent, record)
            return record

    def flush_outbox(self, bus: MessageBus, limit: int = 100) -> dict:
        from codex_harness.application.outbox import relay

        return relay(self.store, self.org, bus, limit)
