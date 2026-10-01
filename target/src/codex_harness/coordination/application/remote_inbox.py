"""The raw inbound Buzz event state: `pending` until processed, idempotent by event id (design §6.2 steps 2 and 6).

Layer: application
Context: coordination
Owns: the `remote_inbox` bucket: insert_pending, mark_processed, pending, compact
Does not own: parsing or admitting a command (RemoteControl, Batch B), the relay query and the cursor (observation)
Entry points: RemoteInbox.insert_pending, RemoteInbox.mark_processed, RemoteInbox.pending, RemoteInbox.compact
Contracts: INV-IDEMPOTENCY-001

Every method joins the CALLER's transaction (the V5 owner-operation pattern), so the bridge-lease check, the insert
and the processed mark of one event commit together (buzz DESIGN §6.2 step 2, §6.5). Rows are
`{id, event_id, author, created_at, received_at, channel, state: pending|processed, outcome}`; an owner-authored
row may also carry the raw `event` so a crash-left `pending` row is resumable without the relay re-sending it (F2).
F6 bounding is `compact`, not deletion (owner decision DA-R1: the storage Transaction port has no delete): a processed
no-command row older than the horizon loses its raw `event` body and gets `compacted: true`, keeping its identity
(event_id, author, created_at, received_at, channel, outcome), so a duplicate of it is still `duplicate`.
"""

from __future__ import annotations

from codex_harness.kernel.errors import require

BUCKET = "remote_inbox"
OUTCOMES = ("ignored_not_owner", "display_only", "command_admitted", "command_refused", "stub_recorded")
# Outcomes that carried a command (or may have: the Batch A stub keeps what it was handed): the raw event is kept.
COMMAND_OUTCOMES = ("command_admitted", "command_refused", "stub_recorded")
META = ("event_id", "author", "created_at", "received_at", "channel")


class RemoteInbox:
    def insert_pending(self, tx, meta: dict) -> str:
        """`"inserted"` for a new event id, `"duplicate"` when the row exists (the row is never changed)."""
        require(all(meta.get(name) not in (None, "") for name in META), "Inbox row needs " + ", ".join(META))
        if tx.get(BUCKET, meta["event_id"]) is not None:
            return "duplicate"
        row = {name: meta[name] for name in META}
        if meta.get("event") is not None:
            row["event"] = meta["event"]
        tx.put(BUCKET, meta["event_id"], {"id": meta["event_id"], **row, "state": "pending", "outcome": None})
        return "inserted"

    def mark_processed(self, tx, event_id: str, outcome: str) -> dict:
        require(outcome in OUTCOMES, "Unknown inbox outcome")
        row = tx.get(BUCKET, event_id)
        require(row is not None and row["state"] == "pending", "Only a pending inbox row can be processed")
        row.update(state="processed", outcome=outcome)
        if outcome not in COMMAND_OUTCOMES:
            row.pop("event", None)
        tx.put(BUCKET, event_id, row)
        return row

    def compact(self, tx, older_than: int) -> int:
        """Reclaim the body of processed no-command rows received before `older_than`; the number compacted.

        Pending rows and rows whose outcome carried (or may have carried) a command are never touched.
        """
        count = 0
        for row in tx.scan(BUCKET):
            if (row["state"] == "processed" and row["outcome"] not in COMMAND_OUTCOMES
                    and row["received_at"] < older_than and not row.get("compacted")):
                row.pop("event", None)
                row["compacted"] = True
                tx.put(BUCKET, row["id"], row)
                count += 1
        return count

    def pending(self, tx) -> list[dict]:
        rows = [row for row in tx.scan(BUCKET) if row["state"] == "pending"]
        return sorted(rows, key=lambda row: (row["received_at"], row["created_at"], row["event_id"]))
