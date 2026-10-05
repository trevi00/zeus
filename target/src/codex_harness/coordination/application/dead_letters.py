"""The dead-letter operator: list the dead-letter stream and replay one entry exactly once (S10 A5-1b, DESIGN-s10 §17a).

Layer: application
Context: coordination
Owns: bucket dead_letter_replays (one record per `(source, entry_id)`: intent or completed, with the operator
    reason and actor), DeadLetters.list, DeadLetters.replay, DeadLetters.trim
Does not own: the dead-letter stream and the publish (the injected bus, storage), the argument shape (entry.cli.dlq)
Entry points: DeadLetters.list, DeadLetters.replay, DeadLetters.trim
Contracts: INV-MESSAGE-001 (RSM G2: a replay of the same `(source, entry_id)` is recorded and never repeated)

A declared target addition (no M7 counterpart). The dead-letter record carries the FULL source stream name and the
stream entry id of the failed delivery, so `(source, entry_id)` names one failed message however many dead-letter
records it left. A replay records its intent in one transaction, publishes unbound as the original publisher did, then
records the outcome: an unfinished `intent` (a crash between the publish and the record) refuses `replay_in_doubt`
rather than publishing twice. A MessageDeliveryError from the publish is AMBIGUOUS (the XADD may have been accepted and
the response lost), so it is held on the same `intent` record with the exception class name only, never retried
(FLEET-REBUILD-S10-ACCEPT F1). A `failed` record left by the predecessor is in doubt the same way (F1 round 2). An
in-doubt replay is resolved by an operator decision outside this command (a follow-up), never by an automatic retry. Message-identity idempotency in the workflow makes a duplicate delivery a
no-op (RSM G1).
A body is never returned: the group carries its sha256 and size only.

Retention (XC-2a B1, TQ-XCUT-PLAN; REDIS-STREAMS-RELIABILITY safe retention): `trim` removes a group's stream entries
ONLY when its replay record is `completed` and was last updated longer ago than the retention (the observation
retention by default). An unreplayed, `intent` (in doubt), legacy `failed` (F1: in doubt) or body-conflict group, and a
completed one inside retention, is never touched. The record is written first (`trimmed_at`, `trimmed_entries`: ids
only) and the entries deleted after, so a crash between the two leaves the entries for the next run to trim and record
again, never an unrecorded deletion; a second run trims nothing.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import timezone

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import ID, digest, utcnow
from codex_harness.kernel.policy import POLICY
from codex_harness.kernel.timestamps import timestamp
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
            # F1 (round 2): `failed` is no longer produced by replay (an ambiguous publish stays `intent`). A `failed`
            # record written before the correction is readable but carries no proof that nothing was written, so it is
            # in doubt like `intent`, never retried automatically; the refusal leaves the stored audit unchanged.
            require(status not in (INTENT, FAILED), "replay_in_doubt")
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
            # F1: no proof of absence of the write; keep `intent` and record the class name, never the text.
            self._finish(key, {"error_type": type(exc.__cause__ or exc).__name__})
            raise ContractError("replay_in_doubt") from exc
        return self._finish(key, {"status": COMPLETED, "replayed_entry_id": replayed})

    def trim(self, now=None, retention_seconds: int = POLICY.observation_retention_seconds) -> dict:
        """Delete the stream entries of every group whose replay completed longer than `retention_seconds` ago
        (XC-2a B1). Returns the entry count and the `[source, entry_id]` groups: ids only, never a body."""
        require(isinstance(retention_seconds, int) and not isinstance(retention_seconds, bool)
                and retention_seconds >= 0, "trim_retention_invalid")
        moment = (now or self.clock.now())
        cutoff = moment.timestamp() - retention_seconds
        stamp = moment.astimezone(timezone.utc).isoformat()
        groups, doomed, found_groups = [], [], self._groups()
        with self.store.transaction() as tx:
            for (source, entry_id), group in sorted(found_groups.items()):
                key = replay_key(source, entry_id)
                found = tx.get(BUCKET, key)
                updated = None if found is None else timestamp(found.get("updated_at"))
                if (found is None or found["status"] != COMPLETED or updated is None or updated > cutoff
                        or len(set(group["bodies"])) != 1):
                    continue
                tx.put(BUCKET, key, {**found, "trimmed_at": stamp, "trimmed_entries": list(group["ids"])})
                groups.append([source, entry_id])
                doomed.extend(group["ids"])
        if doomed:
            try:
                self.bus.trim_dead_letters(doomed)
            except MessageDeliveryError as exc:
                raise ContractError("dead_letter_trim_failed") from exc
        return {"trimmed": len(doomed), "groups": groups}

    def _finish(self, key: str, outcome: dict) -> dict:
        with self.store.transaction() as tx:
            record = {**tx.get(BUCKET, key), **outcome, "updated_at": utcnow(self.clock)}
            tx.put(BUCKET, key, record)
        return record
