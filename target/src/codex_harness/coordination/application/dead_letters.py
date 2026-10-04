"""The dead-letter operator: list the dead-letter stream and replay one entry exactly once (S10 A5-1b, DESIGN-s10 §17a).

Layer: application
Context: coordination
Owns: bucket dead_letter_replays (one record per `(source, entry_id)`: intent, completed or failed, with the operator
    reason and actor), DeadLetters.list, DeadLetters.replay
Does not own: the dead-letter stream and the publish (the injected bus, storage), the argument shape (entry.cli.dlq)
Entry points: DeadLetters.list, DeadLetters.replay
Contracts: INV-MESSAGE-001 (RSM G2: a replay of the same `(source, entry_id)` is recorded and never repeated)

A declared target addition (no M7 counterpart). The dead-letter record carries the FULL source stream name and the
stream entry id of the failed delivery, so `(source, entry_id)` names one failed message however many dead-letter
records it left. A replay records its intent in one transaction, publishes unbound as the original publisher did, then
records the outcome: an unfinished `intent` (a crash between the publish and the record) refuses `replay_in_doubt`
rather than publishing twice. Message-identity idempotency in the workflow makes a duplicate delivery a no-op (RSM G1).
A body is never returned: the group carries its sha256 and size only.
"""

from __future__ import annotations

import hashlib
import unicodedata

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import ID, digest, utcnow
from codex_harness.storage.ports import MessageDeliveryError

BUCKET = "dead_letter_replays"
INTENT, COMPLETED, FAILED = "intent", "completed", "failed"
REASON_CUT = 200


def replay_key(source: str, entry_id: str) -> str:
    return digest([source, entry_id])


class DeadLetters:
    def __init__(self, store, bus, *, clock, limit: int = 10000):
        self.store, self.bus, self.clock, self.limit = store, bus, clock, limit

    def _groups(self) -> dict:
        records = self.bus.dead_letters(self.limit)
        require(len(records) <= self.limit, "dead_letter_backlog_exceeds_limit")
        groups: dict = {}
        for dead_letter_id, fields in records:
            body = fields.get("body", "")
            group = groups.setdefault((fields.get("source"), fields.get("entry_id")),
                                      {"ids": [], "reasons": set(), "bodies": []})
            group["ids"].append(dead_letter_id)
            group["reasons"].add(str(fields.get("reason", ""))[:REASON_CUT])
            group["bodies"].append(body)
        return groups

    @staticmethod
    def _identity(source, entry_id, group: dict) -> dict:
        body = group["bodies"][0]
        raw = body if isinstance(body, bytes) else str(body).encode()
        return {"source": source, "entry_id": entry_id, "dead_letter_ids": list(group["ids"]),
                "reasons": sorted(group["reasons"]), "body_sha256": hashlib.sha256(raw).hexdigest(),
                "body_bytes": len(raw), "body_conflict": len(set(group["bodies"])) > 1}

    def list(self) -> dict:
        groups = self._groups()
        with self.store.transaction() as tx:
            rows = []
            for (source, entry_id), group in sorted(groups.items()):
                found = tx.get(BUCKET, replay_key(source, entry_id))
                replay = None if found is None else {"status": found["status"], "attempts": found["attempts"],
                                                     "replayed_entry_id": found.get("replayed_entry_id")}
                rows.append({**self._identity(source, entry_id, group), "records": len(group["ids"]),
                             "replay": replay})
        return {"dead_letters": rows, "groups": len(rows), "records": sum(row["records"] for row in rows)}

    def replay(self, source: str, entry_id: str, *, reason: str, actor: str) -> dict:
        require(isinstance(reason, str) and 1 <= len(reason) <= 500
                and not any(unicodedata.category(c) == "Cc" for c in reason), "replay_reason_invalid")
        require(isinstance(actor, str) and ID.fullmatch(actor) is not None, "replay_actor_invalid")
        group = self._groups().get((source, entry_id))
        require(group is not None, "dead_letter_missing")
        require(len(set(group["bodies"])) == 1, "dead_letter_body_conflict")
        try:
            message = self.bus.decode({"body": group["bodies"][0]})
            recipient = message["who"]["recipient"]
        except Exception as exc:
            raise ContractError("body_invalid") from exc
        # A run-scoped namespace names another stream; it is refused here (a disclosed follow-up).
        require(self.bus.stream(recipient) == source, "route_mismatch")
        key, now = replay_key(source, entry_id), utcnow(self.clock)
        with self.store.transaction() as tx:
            previous = tx.get(BUCKET, key)
            status = None if previous is None else previous["status"]
            require(status != COMPLETED, "already_replayed")
            require(status != INTENT, "replay_in_doubt")
            record = {"id": key, "status": INTENT, "source": source, "entry_id": entry_id,
                      "dead_letter_ids": list(group["ids"]), "reasons": sorted(group["reasons"]),
                      "body_sha256": self._identity(source, entry_id, group)["body_sha256"],
                      "operator_reason": reason, "actor": actor,
                      "attempts": (previous["attempts"] if previous else 0) + 1,
                      "created_at": previous["created_at"] if previous else now, "updated_at": now}
            tx.put(BUCKET, key, record)
        try:
            replayed = self.bus.publish(message)
        except MessageDeliveryError as exc:
            self._finish(key, {"status": FAILED, "error_type": str(exc) or type(exc).__name__})
            raise ContractError("replay_delivery_failed") from exc
        return self._finish(key, {"status": COMPLETED, "replayed_entry_id": replayed})

    def _finish(self, key: str, outcome: dict) -> dict:
        with self.store.transaction() as tx:
            record = {**tx.get(BUCKET, key), **outcome, "updated_at": utcnow(self.clock)}
            tx.put(BUCKET, key, record)
        return record
