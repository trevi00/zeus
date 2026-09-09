"""Durable acceptance decisions; remote issue projection is a separate operation."""
import json
from datetime import datetime, timedelta, timezone

from codex_harness.domain.model import canonical, digest, require, utcnow
from codex_harness.domain.ticket_lifecycle import timestamp, validate_evidence, validate_packet


def require_no_promotion(tx, ticket_id):
    for intent in tx.scan("promotion_intents"):
        if intent.get("candidate", {}).get("zeus_ticket", {}).get("id") == ticket_id:
            require(intent["status"] in {"completed", "abandoned"},
                    "Ticket promotion unresolved; resume release or release-abandon first")


def event_document(tx, identity):
    row = tx.get("ticket_lifecycle_events", identity)
    require(row and row["id"] == digest({k: v for k, v in row.items() if k != "id"}),
            "Ticket lifecycle event missing or corrupted")
    return row


def verify_chain(tx, ticket):
    sequence, identity = ticket.get("lifecycle_sequence", 0), ticket.get("lifecycle_event")
    require(type(sequence) is int and sequence >= 0, "Invalid lifecycle sequence")
    while sequence:
        event = event_document(tx, identity)
        require(event["ticket_id"] == ticket["id"] and event["sequence"] == sequence
                and event["from_sequence"] == sequence - 1, "Ticket lifecycle chain mismatch")
        sequence, identity = sequence - 1, event["previous_event"]
    require(identity is None, "Unexpected initial lifecycle event")


def transition(tx, ticket, kind, reason, *, packet_ref=None, proof_ref=None, request_id=None):
    sequence = ticket.get("lifecycle_sequence", 0)
    previous = ticket.get("lifecycle_event")
    verify_chain(tx, ticket)
    require_no_promotion(tx, ticket["id"])
    event = {"ticket_id": ticket["id"], "revision": ticket["revision"], "content_hash": ticket["content_hash"],
             "from_sequence": sequence, "sequence": sequence + 1, "previous_event": previous,
             "previous_status": ticket["status"], "kind": kind, "reason": reason,
             "previous_updated_at": ticket.get("updated_at", ticket["created_at"]),
             "packet_ref": packet_ref, "proof_ref": proof_ref, "request_id": request_id, "at": utcnow()}
    event["id"] = digest(event)
    tx.put("ticket_lifecycle_events", event["id"], event)
    updated = {**ticket, "status": "closed" if kind == "closed" else "open",
               "lifecycle_sequence": sequence + 1, "lifecycle_event": event["id"], "updated_at": event["at"]}
    tx.put("tickets", ticket["id"], updated)
    for row in tx.scan("ticket_dispatches"):
        if row["ticket_id"] == ticket["id"] and row["status"] != "superseded":
            tx.put("ticket_dispatches", row["id"], {**row, "status": "superseded", "lifecycle_event": event["id"]})
    for row in tx.scan("ticket_github"):
        if row["ticket_id"] == ticket["id"]:
            tx.put("ticket_github", row["id"], {**row, "status": "pending",
                   "desired_state": "CLOSED" if kind == "closed" else "OPEN", "lifecycle_event": event["id"]})
    return event


class TicketLifecycle:
    def __init__(self, tickets, artifacts, authority):
        self.tickets, self.store, self.artifacts, self.authority = tickets, tickets.store, artifacts, authority

    def prepare(self, ticket_id, evidence):
        ticket, policy = self.tickets.get(ticket_id), self.authority.policy()
        require(isinstance(evidence, dict) and set(evidence) == {"solution_commit", "criteria", "environment_ref", "reason"},
                "Closure input needs solution_commit, criteria, environment_ref and reason")
        now = datetime.now(timezone.utc)
        packet = {**evidence, "version": 1, "ticket_id": ticket_id, "revision": ticket["revision"],
            "content_hash": ticket["content_hash"], "sequence": ticket.get("lifecycle_sequence", 0),
            "expected_status": ticket["status"], "criteria_hash": digest(ticket["content"]["acceptance_criteria"]),
            "issued_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat(),
            **{k: policy[k] for k in ("policy_commit", "policy_hash", "scope")}}
        self._evidence(packet, ticket, policy, now)
        ref = self.artifacts.put(canonical(packet), "ticket-closure-packet")["ref"]
        return {"packet_ref": ref, "packet": packet, "signing_namespace": "zeus-ticket-close-v1",
                "signing_payload": canonical(packet), "status": "awaiting_signatures"}

    def _evidence(self, packet, ticket, policy, now=None):
        refs = validate_packet(packet, ticket, policy, now)
        size, documents = 0, {}
        for ref in refs:
            body = self.artifacts.text(ref, 1024 * 1024)
            size += len(body.encode("utf-8"))
            require(size <= 8 * 1024 * 1024, "Closure evidence exceeds total budget")
            document = json.loads(body)
            require(body == canonical(document), "Closure evidence must use canonical JSON bytes")
            validate_evidence(document, packet, environment=ref == packet["environment_ref"])
            require(timestamp(document["observed_at"]) >= timestamp(ticket.get("updated_at", ticket["created_at"])),
                    "Evidence predates ticket revision or lifecycle transition")
            require(timestamp(packet["issued_at"]) - timestamp(document["observed_at"]) <=
                    timedelta(seconds=policy["definition"]["max_evidence_age_seconds"]), "Closure evidence too old")
            documents[ref] = document
        for criterion in packet["criteria"]:
            require(all(documents[ref].get("criterion_index") == criterion["index"]
                        for ref in criterion["evidence_refs"]), "Evidence belongs to another acceptance criterion")

    @staticmethod
    def _anchor(tx, policy):
        anchor = {k: policy[k] for k in ("policy_commit", "policy_hash", "scope")}
        current = tx.get("ticket_trust_anchors", "deployment")
        require(current is None or all(current[k] == v for k, v in anchor.items()),
                "Configured trust anchor differs from pinned authority; authenticated rotation required")
        if current is None:
            tx.put("ticket_trust_anchors", "deployment", {**anchor, "pinned_at": utcnow(),
                "bootstrap_source": "out_of_band_deployment_configuration", "bootstrap_human_presence_verified": False})

    def close(self, packet_ref, signatures):
        packet = self.artifacts.document(packet_ref)
        require(isinstance(packet.get("ticket_id"), str), "Closure ticket ID required")
        ticket = self.tickets.get(packet["ticket_id"])
        with self.store.transaction() as tx:
            existing = tx.get("ticket_closures", packet_ref)
            if existing:
                event = event_document(tx, existing["event_id"])
                current = tx.get("tickets", packet["ticket_id"])
                require(current["status"] == "closed" and current.get("lifecycle_event") == event["id"],
                        "Stale closure retry after lifecycle change")
                return {"decision": event, "replayed": True, "verification": "not_repeated"}
        policy = self.authority.policy()
        self._evidence(packet, ticket, policy)
        proof = self.authority.verify(packet_ref, packet, signatures)
        proof_ref = self.artifacts.put(canonical(proof), "ticket-closure-signature-verification")["ref"]
        # No signer process or artifact write runs while the PostgreSQL transaction is held.
        with self.store.transaction() as tx:
            self._anchor(tx, policy)
            current = tx.get("tickets", ticket["id"])
            existing = tx.get("ticket_closures", packet_ref)
            if existing:
                require(current["status"] == "closed" and current.get("lifecycle_event") == existing["event_id"],
                        "Stale closure retry after lifecycle change")
                return {"decision": event_document(tx, existing["event_id"]), "replayed": True, "verification": "not_repeated"}
            revision = tx.get("ticket_revisions", f'{ticket["id"]}:{packet["revision"]}')
            require(revision and digest(revision["content"]) == packet["content_hash"], "Ticket content changed")
            self._evidence(packet, {**revision, **current, "content": revision["content"]}, policy)
            for signer in proof["signatures"]:
                require(datetime.now(timezone.utc) < timestamp(policy["enrolled"][signer["principal"]]["valid_before"]),
                        "Signer expired before closure commit")
                self.artifacts.text(signer["signature_ref"], 16384)
            slot = f'{ticket["id"]}:{packet["sequence"]}'
            require(tx.get("ticket_closure_sequences", slot) is None, "Closure sequence already consumed")
            event = transition(tx, current, "closed", packet["reason"], packet_ref=packet_ref, proof_ref=proof_ref)
            tx.put("ticket_closures", packet_ref, {"packet_ref": packet_ref, "event_id": event["id"]})
            tx.put("ticket_closure_sequences", slot, {"packet_ref": packet_ref, "event_id": event["id"]})
            return {"decision": event, "replayed": False, "verification": "performed"}

    def reopen(self, ticket_id, expected_revision, expected_sequence, reason, expected_status="closed"):
        require(type(expected_revision) is int and type(expected_sequence) is int, "Exact reopen revision and sequence required")
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 4000, "Reopen reason required")
        require(expected_status in {"open", "dispatched", "closed"}, "Invalid expected reopen state")
        request_id = digest({"ticket_id": ticket_id, "revision": expected_revision,
                             "from_sequence": expected_sequence, "expected_status": expected_status, "reason": reason})
        with self.store.transaction() as tx:
            ticket = tx.get("tickets", ticket_id)
            require(ticket, "Ticket not found")
            existing = tx.get("ticket_reopens", request_id)
            if existing:
                require(ticket["status"] in {"open", "dispatched"} and ticket.get("lifecycle_event") == existing["event_id"],
                        "Stale reopen retry after another lifecycle transition")
                return {"decision": event_document(tx, existing["event_id"]), "replayed": True,
                        "verification": "not_required_authority_removed"}
            require(ticket["revision"] == expected_revision and ticket.get("lifecycle_sequence", 0) == expected_sequence
                    and ticket["status"] == expected_status, "Stale reopen revision, sequence or state")
            # Reopen removes authority; it cannot approve a subsequent close or deployment.
            event = transition(tx, ticket, "reopened", reason, request_id=request_id)
            tx.put("ticket_reopens", request_id, {"event_id": event["id"]})
            return {"decision": event, "replayed": False, "verification": "not_required_authority_removed"}

    def verify_closed(self, ticket, heartbeat=None):
        with self.store.transaction() as tx:
            verify_chain(tx, ticket)
            event = event_document(tx, ticket.get("lifecycle_event"))
            require(event["kind"] == "closed" and event["ticket_id"] == ticket["id"]
                    and event["sequence"] == ticket.get("lifecycle_sequence")
                    and event["revision"] == ticket["revision"] and event["content_hash"] == ticket["content_hash"],
                    "Closed ticket lacks its current closure decision")
            revision = tx.get("ticket_revisions", f'{ticket["id"]}:{ticket["revision"]}')
            require(revision and digest(revision["content"]) == ticket["content_hash"], "Closure revision missing or corrupted")
        packet, proof = self.artifacts.document(event["packet_ref"]), self.artifacts.document(event["proof_ref"])
        policy = self.authority.policy(heartbeat)
        snapshot = {**revision, "status": event["previous_status"], "lifecycle_sequence": event["from_sequence"],
                    "updated_at": event["previous_updated_at"]}
        self._evidence(packet, snapshot, policy, timestamp(event["at"]))
        signatures = [{k: r[k] for k in ("principal", "signature_ref")} for r in proof["signatures"]]
        self.authority.verify(event["packet_ref"], packet, signatures, heartbeat=heartbeat)
        with self.store.transaction() as tx:
            self._anchor(tx, policy)
        return event
