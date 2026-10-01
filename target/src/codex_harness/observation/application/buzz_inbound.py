"""One inbound reconciliation pass per bound channel: relay events into the remote inbox (design §6.2 steps 1-6).

Layer: application
Context: observation
Owns: the `buzz_cursors` and `buzz_passes` buckets; the pass order (lower bound, query, inbox commit, owner sink,
    cursor, pass record)
Does not own: `remote_inbox` and `bridge_owner` rows (coordination, reached through the injected ports), command
    semantics (the injected sink; Batch B), the relay protocol (the injected RelayClient)
Entry points: InboundPass.run
Contracts: INV-OBSERVATION-001, INV-IDEMPOTENCY-001

Every transaction re-reads the bridge lease generation first (buzz DESIGN §6.5), so a stale bridge commits nothing.
Each event commits alone: lease check, idempotent `insert_pending` and, for a non-owner author, `ignored_not_owner`,
together with the pass keyset. The owner sink runs AFTER that commit; a sink exception leaves the row `pending`
and the next pass resumes it (F2). The cursor is written after the inbox commit and never moves backwards.

The query lower bound is `min(cursor_time - LOOKBACK, now - LOOKBACK, every unretired pass's lower)` (§6.2.1, P1).
EOSE and short pages are observations, never proof (§6.2 step 4): a finished pass is always recorded
`gap_unknown`, with the `ended` reason, and stays an unresolved checkpoint until its upper bound is older than
`now - LOOKBACK`; it then retires from the operational view but stays recorded. A crash leaves the pass
`running` with its keyset, and the next run resumes it with `until` + `before_id` (the relay's composite keyset).
"""

from __future__ import annotations

LOOKBACK = 780  # COMMAND_TTL 600 + MAX_SKEW 60 + DELIVERY_SLACK 120 (§6.2.1)
PASSES = "buzz_passes"
CURSORS = "buzz_cursors"


class InboundPass:
    def __init__(self, store, relay, inbox, lease, sink, owners, channels, clock, lookback: int = LOOKBACK):
        self.store, self.relay, self.inbox, self.lease, self.sink = store, relay, inbox, lease, sink
        self.owners, self.channels, self.clock, self.lookback = frozenset(owners), tuple(channels), clock, lookback

    def run(self, generation: int) -> dict:
        """Run every bound channel once under `generation`; the per-channel result."""
        return {channel: self._channel(channel, generation) for channel in self.channels}

    # -- one channel ------------------------------------------------------------------------------------

    def _channel(self, channel: str, generation: int) -> dict:
        now = int(self.clock())
        key, record = self._open_pass(channel, generation, now)
        self._advance_cursor(channel, generation, record["high"])  # a crashed run's cursor catches up first
        query = {"kinds": [9], "#h": [channel], "since": record["lower"]}
        if record["keyset"] is not None:
            query["until"], query["before_id"] = record["keyset"]
        result = self.relay.query_all(query)
        events = sorted(result["events"], key=lambda event: (-event["created_at"], event["id"]))
        inserted = 0
        for event in events:
            inserted += self._commit_event(channel, generation, key, event, now) == "inserted"
            self._advance_cursor(channel, generation, self._read_pass(key)["high"])
        processed, failed = self._sink_pending(channel, generation)
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            record = tx.get(PASSES, key)
            record.update(state="gap_unknown", coverage="gap_unknown", ended=result["ended"],
                          pages=result["pages"], unverified=result["unverified"], finished_at=now)
            tx.put(PASSES, key, record)
        return {"ended": result["ended"], "events": len(events), "inserted": inserted, "sunk": processed,
                "sink_failed": failed, "lower": record["lower"], "pass": key}

    def _open_pass(self, channel: str, generation: int, now: int) -> tuple[str, dict]:
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            rows = [row for row in tx.scan(PASSES) if row["channel"] == channel]
            for row in rows:  # §6.2 step 4: an interval retires only once older than the admission horizon
                if row["state"] != "running" and row["retired_at"] is None and row["upper"] < now - self.lookback:
                    row["retired_at"] = now
                    tx.put(PASSES, row["id"], row)
            for row in rows:
                if row["state"] == "running":
                    return row["id"], row
            cursor = tx.get(CURSORS, channel)
            lower = now - self.lookback
            if cursor is not None:
                lower = min(lower, cursor["created_at"] - self.lookback)
            lower = min([lower] + [row["lower"] for row in rows if row["retired_at"] is None])
            key = f"{channel}:{len(rows) + 1:08d}"
            record = {"id": key, "channel": channel, "lower": lower, "upper": now, "keyset": None, "high": None,
                      "events": 0, "state": "running", "coverage": None, "ended": None, "retired_at": None}
            tx.put(PASSES, key, record)
            return key, record

    def _commit_event(self, channel: str, generation: int, key: str, event: dict, now: int) -> str:
        owner = event["pubkey"] in self.owners
        meta = {"event_id": event["id"], "author": event["pubkey"], "created_at": event["created_at"],
                "received_at": now, "channel": channel}
        if owner:
            meta["event"] = event  # the raw owner event keeps a crash-left pending row resumable (F2)
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            status = self.inbox.insert_pending(tx, meta)
            if status == "inserted" and not owner:
                self.inbox.mark_processed(tx, event["id"], "ignored_not_owner")
            record = tx.get(PASSES, key)
            position = [event["created_at"], event["id"]]
            record["keyset"] = position
            record["high"] = max(record["high"] or position, position)
            record["events"] += 1
            tx.put(PASSES, key, record)
        return status

    def _read_pass(self, key: str) -> dict:
        with self.store.transaction() as tx:
            return tx.get(PASSES, key)

    def _advance_cursor(self, channel: str, generation: int, position) -> None:
        """Written after the inbox commit; monotone in `(created_at, id)`."""
        if position is None:
            return
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            cursor = tx.get(CURSORS, channel)
            if cursor is None or [cursor["created_at"], cursor["event_id"]] < list(position):
                tx.put(CURSORS, channel, {"id": channel, "channel": channel, "created_at": position[0],
                                          "event_id": position[1]})

    def _sink_pending(self, channel: str, generation: int) -> tuple[int, int]:
        with self.store.transaction() as tx:
            rows = [row for row in self.inbox.pending(tx) if row["channel"] == channel and row["author"] in self.owners]
        processed = failed = 0
        for row in rows:
            try:
                outcome = self.sink(row["event"])
            except Exception:  # noqa: BLE001 - the row stays pending; the next pass resumes it (F2)
                failed += 1
                continue
            with self.store.transaction() as tx:
                self.lease.require_current(tx, generation)
                self.inbox.mark_processed(tx, row["event_id"], outcome)
            processed += 1
        return processed, failed
