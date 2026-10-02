"""One inbound reconciliation pass per bound channel: relay events into the remote inbox (design §6.2 steps 1-6).

Layer: application
Context: observation
Owns: the `buzz_cursors` and `buzz_passes` buckets; the pass order (lower bound, query, inbox commit, owner sink,
    cursor, pass record)
Does not own: `remote_inbox` and `bridge_owner` rows (coordination, reached through the injected ports), command
    semantics (the injected sink; Batch B), the relay protocol (the injected RelayClient)
Entry points: InboundPass.run, InboundPass.compact
Contracts: INV-OBSERVATION-001, INV-IDEMPOTENCY-001

Every transaction re-reads the bridge lease generation first (buzz DESIGN §6.5), so a stale bridge commits nothing.
Each event commits alone: lease check, idempotent `insert_pending` and, for a non-owner author, `ignored_not_owner`,
together with the pass keyset. The owner sink runs AFTER that commit (`sink(row, generation)`: the inbox row and the lease generation, R1); a sink exception leaves the row `pending`
and the next pass resumes it (F2). The cursor is written after the inbox commit and never moves backwards.

The query lower bound is `min(cursor_time - LOOKBACK, now - LOOKBACK, every unretired pass's own_lower)` (§6.2.1, P1):
a pass records its own horizon (`own_lower`, with `upper` its retirement identity) apart from the `lower` it queried, so
an older interval that a later query re-covers retires on its own schedule and then stops lowering queries (§6.2.4).
EOSE and short pages are observations, never proof (§6.2 step 4): a finished pass is always recorded
`gap_unknown`, with the `ended` reason, and stays an unresolved checkpoint until its upper bound is older than
`now - LOOKBACK`; it then retires from the operational view but stays recorded. A crash leaves the pass
`running` with its keyset, and the next run resumes it with `until` + `before_id` (the relay's composite keyset).

A cooperative stop (D5 F1, DESIGN-D §2): `run(generation, stop=...)` reads `stop` before each channel and hands it to
the relay's pager, which reads it before each page. Once it is true no further network work starts; the current atomic
unit finishes (the event commit in flight completes, then the pending owner rows are sunk). A pass the pager ended with
`stopped`, or that stopped between event commits, is NOT finished: it stays `running` with its keyset, so the next run resumes it from the first unread page.
"""

from __future__ import annotations

from collections.abc import Callable

LOOKBACK = 780  # COMMAND_TTL 600 + MAX_SKEW 60 + DELIVERY_SLACK 120 (§6.2.1)
PASSES = "buzz_passes"
CURSORS = "buzz_cursors"


class InboundPass:
    def __init__(self, store, relay, inbox, lease, sink, owners, channels, clock, lookback: int = LOOKBACK):
        self.store, self.relay, self.inbox, self.lease, self.sink = store, relay, inbox, lease, sink
        self.owners, self.channels, self.clock, self.lookback = frozenset(owners), tuple(channels), clock, lookback

    def run(self, generation: int, *, stop: Callable[[], bool] | None = None) -> dict:
        """Run every bound channel once under `generation`; the per-channel result.

        With `stop`, the channels after the one in flight when it became true are not started (absent from the result).
        """
        report = {}
        for channel in self.channels:
            if stop is not None and stop():
                break
            report[channel] = self._channel(channel, generation, stop)
        return report

    def compact(self, generation: int) -> int:
        """Reclaim processed no-command inbox bodies older than `lookback + 24 h` (§6.2 F6; DA-R1)."""
        older_than = int(self.clock()) - self.lookback - 86400
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            return self.inbox.compact(tx, older_than)

    # -- one channel ------------------------------------------------------------------------------------

    def _channel(self, channel: str, generation: int, stop: Callable[[], bool] | None = None) -> dict:
        now = int(self.clock())
        key, record = self._open_pass(channel, generation, now)
        self._advance_cursor(channel, generation, record["high"])  # a crashed run's cursor catches up first
        query = {"kinds": [9], "#h": [channel], "since": record["lower"]}
        if record["keyset"] is not None:
            query["until"], query["before_id"] = record["keyset"]
        result = self.relay.query_all(query, stop=stop) if stop is not None else self.relay.query_all(query)
        events = sorted(result["events"], key=lambda event: (-event["created_at"], event["id"]))
        inserted = 0
        halted = result["ended"] == "stopped"
        for event in events:
            if stop is not None and stop():
                halted = True  # the rest of the page is read again from the committed keyset
                break
            inserted += self._commit_event(channel, generation, key, event, now) == "inserted"
            self._advance_cursor(channel, generation, self._read_pass(key)["high"])
        processed, failed = self._sink_pending(channel, generation)
        if halted:  # D5 F1: unfinished, not a gap observation; the next run resumes the keyset
            return {"ended": "stopped", "events": len(events), "inserted": inserted, "sunk": processed,
                    "sink_failed": failed, "lower": record["lower"], "pass": key}
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
            horizon = now - self.lookback  # this pass's own horizon: what its interval itself covers
            if cursor is not None:
                horizon = min(horizon, cursor["created_at"] - self.lookback)
            # A live interval lowers the query by its ORIGINAL bound; the query's inherited lower never becomes the
            # next interval's own bound, so carrying an old bound cannot refresh its lifetime (§6.2.4).
            lower = min([horizon] + [row.get("own_lower", row["lower"]) for row in rows if row["retired_at"] is None])
            key = f"{channel}:{len(rows) + 1:08d}"
            record = {"id": key, "channel": channel, "lower": lower, "own_lower": horizon, "upper": now,
                      "keyset": None, "high": None,
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
                outcome = self.sink(row, generation)
            except Exception:  # noqa: BLE001 - the row stays pending; the next pass resumes it (F2)
                failed += 1
                continue
            with self.store.transaction() as tx:
                self.lease.require_current(tx, generation)
                self.inbox.mark_processed(tx, row["event_id"], outcome)
            processed += 1
        return processed, failed
