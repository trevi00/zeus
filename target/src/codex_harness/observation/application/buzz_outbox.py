"""The outbound transport state: signed, stored-before-send, reconciled, bounded (design §6.1 steps 1-6).

Layer: application
Context: observation
Owns: the `buzz_outbox`, `buzz_outbox_watermarks`, `buzz_outbox_acks` and `buzz_alerts` buckets; the delivery pass and the capacity rule
Does not own: what to publish (BuzzProjection plan, replan and regenerate sources: Batch B, injected), the relay
    protocol (the injected RelayClient), the keys (the injected EventSigner), the bridge lease (coordination, reached
    through the injected port)
Entry points: BuzzOutbox.enqueue, BuzzOutbox.deliver, BuzzOutbox.recover_deferred
Contracts: INV-OBSERVATION-001, INV-IDEMPOTENCY-001

A row is `{id = op_id, subject, version, cls, role, event (signed), unsigned, event_id, created_at, status, ...}`.
The event is signed and stored BEFORE any send (C3). Every state change commits under `lease.require_current`, so a
stale bridge commits nothing (§6.5). Relay calls run outside a transaction; the outcome commits afterwards.

Delivery (§6.1 steps 3-4). Within the drift window the SAME signed event is resent. After the window, or after a
timestamp rejection, nothing is assumed: an empty, erroring or non-EOSE answer proves nothing, so the op stays
`unknown` (P1). An append subject reconciles by its `zr-op` tag; a re-publication is a freshly signed copy of the same
unsigned event (same tag, new `created_at`, since the old one is outside the relay's window), throttled to one per 3
passes and 10 minutes. A state subject reconciles by `ids`; no positive match re-plans a NEW version, or the
plan answers `{"superseded": True}` and the op is retired. A relay `conflict:` rejection of a state row (a lost CAS)
ends its window like a timestamp rejection (§6.1.5).

Cooperative stop (D5 F1, DESIGN-D §2): `deliver` and `recover_deferred` take an optional `stop` and read it before each
row (and before a re-publication's send and before a state row's re-plan, the relay calls after its first query); once it is true no further relay call starts. The row in flight finishes, every
unstarted row stays `pending`/`unknown` (or the deferred watermark stays), so the next pass resumes it exactly once.

Capacity (§6.1 step 6, P6). `pending`, `in_flight` and `unknown` rows of every class count against `outbox_max`,
checked in the transaction that would add a row. Over the bound the work is DEFERRED, never dropped: no row, a
per-class watermark (the last op enqueued before the first deferral), and one coalesced `outbox_capacity` alert.
While a class has a deferral outstanding, its later enqueues defer too, so recovery stays oldest-first; the one
exception is the same-subject replacement of a resident state row by a strictly newer version (§6.1 step 4), which
never exceeds the bound and neither advances nor clears the watermark.
`acknowledged` and `superseded` rows keep only identity, status and times: the signed payload is reclaimed.

Acknowledgement order (B6 F2, DESIGN §4.1 P1). Every positive acknowledgement (resend, tag or `ids` reconciliation)
commits a strictly increasing `ack_seq` in the SAME transaction (`_commit`), from the counter row `seq` of
`buzz_outbox_acks`: the integer-second `last_attempt_at` cannot order two acknowledgements of one second. A row
acknowledged before this ordinal existed has no `ack_seq` (the projection orders it after every sequenced row).
"""

from __future__ import annotations

from collections.abc import Callable

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest

OUTBOX = "buzz_outbox"
WATERMARKS = "buzz_outbox_watermarks"
ALERTS = "buzz_alerts"
ACKS = "buzz_outbox_acks"  # one row, key `seq`: the last acknowledgement ordinal (B6 F2); never a `buzz_outbox` row
ALERT_ID = "outbox_capacity"
CLASSES = ("state", "append")
NONTERMINAL = ("pending", "in_flight", "unknown")
OUTBOX_MAX = 2000
DRIFT_WINDOW = 600  # a margin under the relay's 900 s (§6.1 step 3)
REPUBLISH_PASSES = 3
REPUBLISH_GAP = 600
OP_TAG = "zr-op"
PAYLOAD = ("event", "unsigned")
CAS_CONFLICT = "conflict:"  # the relay's 45010 CAS rejection, `conflict: artifact head changed` (A4 run 5, step 8)
TIMESTAMP_MARKS = ("timestamp", "creation date", "created_at", "too far")  # the relay's wording of F1


class BuzzOutbox:
    def __init__(self, store, relay, signer, lease, clock, *, role: str, replan: Callable[[str], dict | None],
                 outbox_max: int = OUTBOX_MAX, drift_window: int = DRIFT_WINDOW):
        self.store, self.relay, self.signer, self.lease, self.clock = store, relay, signer, lease, clock
        self.role, self.replan, self.outbox_max, self.drift_window = role, replan, outbox_max, drift_window

    # -- enqueue ----------------------------------------------------------------------------------------

    def enqueue(self, tx, generation: int, subject: str, version: int, unsigned: dict, cls: str, *,
                role: str | None = None) -> dict:
        """Sign and store one op in the caller's transaction: `{"status", "op_id"}`.

        Status is `enqueued`, `duplicate` (the op exists), `stale` (a newer version of a state subject exists) or
        `deferred` (capacity: no row was created).
        """
        self.lease.require_current(tx, generation)
        return self._enqueue(tx, subject, version, unsigned, cls, role or self.role, recovering=False)

    def _enqueue(self, tx, subject, version, unsigned, cls, role, *, recovering, retire: str | None = None) -> dict:
        require(cls in CLASSES, "Outbox class is state or append")
        require(type(version) is int and version >= 0 and bool(subject), "Outbox op needs a subject and a version")
        op_id = digest([subject, version])
        if tx.get(OUTBOX, op_id) is not None:
            return {"status": "duplicate", "op_id": op_id}
        if cls == "append":
            require(any(tag[:1] == [OP_TAG] and len(tag) > 1 for tag in unsigned.get("tags", [])),
                    "An append subject carries a zr-op tag")
        rows = tx.scan(OUTBOX)
        mine = [row for row in rows if row["subject"] == subject and row["cls"] == cls]
        if cls == "state":
            if any(row["version"] > version and row["status"] != "superseded" for row in mine):
                return {"status": "stale", "op_id": op_id}
            older = [row for row in mine if row["version"] < version and (
                row["status"] == "pending" or row["id"] == retire)]
        else:
            older = []
        retiring = {row["id"] for row in older}
        resident = sum(1 for row in rows if row["status"] in NONTERMINAL and row["id"] not in retiring)
        mark = tx.get(WATERMARKS, cls)
        # §6.1 step 6: oldest-first holds for NEW work. A strictly newer version of the same subject that retires a
        # resident row is a capacity-neutral replacement: it passes a standing deferral (the numeric bound below
        # still applies) and leaves the watermark untouched.
        blocked = mark is not None and mark["deferred"] and not recovering and not older
        if resident + 1 > self.outbox_max or blocked:
            self._defer(tx, cls, mark, subject, version)
            return {"status": "deferred", "op_id": op_id}
        signed = self.signer.sign(role, unsigned)  # signed and stored BEFORE any send (C3)
        for row in older:
            self._reclaim(row, "superseded")
            tx.put(OUTBOX, row["id"], row)
        tx.put(OUTBOX, op_id, {"id": op_id, "subject": subject, "version": version, "cls": cls, "role": role,
                               "event": signed, "unsigned": unsigned, "event_id": signed["id"],
                               "created_at": signed["created_at"], "enqueued_at": int(self.clock()),
                               "status": "pending", "first_sent_at": None, "last_attempt_at": None,
                               "relay_message": None, "attempts": 0, "stalled_passes": 0,
                               "last_republish_at": None, "reconcile": False, "reclaimed": False})
        if not (mark and mark["deferred"]):
            self._put_mark(tx, cls, mark, deferred=False, last=[subject, version])
        elif recovering:
            self._put_mark(tx, cls, mark, deferred=True, last=[subject, version])
        return {"status": "enqueued", "op_id": op_id}

    def _defer(self, tx, cls: str, mark: dict | None, subject: str, version: int) -> None:
        now = int(self.clock())
        if mark is None or not mark["deferred"]:
            self._put_mark(tx, cls, mark, deferred=True, last=mark["last"] if mark else None, since=now)
        alert = tx.get(ALERTS, ALERT_ID)
        if alert is None or alert["state"] != "open":  # one coalesced alert, reopened rather than duplicated
            alert = {"id": ALERT_ID, "kind": "outbox_capacity", "state": "open", "opened_at": now, "deferrals": 0,
                     "classes": []}
        alert["deferrals"] += 1
        alert["last_at"] = now
        alert["classes"] = sorted({*alert["classes"], cls})
        tx.put(ALERTS, ALERT_ID, alert)

    @staticmethod
    def _put_mark(tx, cls: str, mark: dict | None, *, deferred: bool, last, since=None) -> None:
        body = dict(mark or {"id": cls, "cls": cls, "deferred": False, "last": None, "deferred_since": None})
        body.update(deferred=deferred, last=last)
        if since is not None:
            body["deferred_since"] = since
        if not deferred:
            body["deferred_since"] = None
        tx.put(WATERMARKS, cls, body)

    @staticmethod
    def _reclaim(row: dict, status: str) -> None:
        row["status"] = status
        row["reclaimed"] = True
        for name in PAYLOAD:
            row.pop(name, None)

    # -- delivery ---------------------------------------------------------------------------------------

    def deliver(self, generation: int, *, stop: Callable[[], bool] | None = None) -> dict:
        """One pass over the pending and unknown rows, oldest first; the per-outcome counts."""
        counts = dict.fromkeys(("sent", "acknowledged", "unknown", "reconciled", "republished", "replanned",
                                "superseded"), 0)
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            ids = [row["id"] for row in sorted(
                (row for row in tx.scan(OUTBOX) if row["status"] in ("pending", "unknown")),
                key=lambda row: (row["created_at"], row["subject"], row["version"]))]
        for op_id in ids:
            if stop is not None and stop():
                break  # D5 F1: the rest stays pending or unknown for the next pass
            with self.store.transaction() as tx:
                self.lease.require_current(tx, generation)
                row = tx.get(OUTBOX, op_id)
            if row is None or row["status"] not in ("pending", "unknown"):
                continue  # superseded or finished since the listing
            now = int(self.clock())
            if not row["reconcile"] and now - row["created_at"] < self.drift_window:
                self._resend(generation, row, now, counts)
            elif row["cls"] == "append":
                self._reconcile_append(generation, row, now, counts, stop)
            else:
                self._reconcile_state(generation, row, now, counts, stop)
        return counts

    def _resend(self, generation: int, row: dict, now: int, counts: dict) -> None:
        """§6.1 step 3: the SAME signed event again."""
        counts["sent"] += 1
        result = self._publish(row["event"])
        accepted = result.get("accepted")
        message = result.get("message")

        def apply(body: dict) -> None:
            body.update(last_attempt_at=now, relay_message=message, attempts=body["attempts"] + 1)
            if body["first_sent_at"] is None:
                body["first_sent_at"] = now
            if accepted is True:  # OK true or `duplicate:`
                self._reclaim(body, "acknowledged")
            elif accepted is None:
                body["status"] = "unknown"
            elif any(mark in str(message).lower() for mark in TIMESTAMP_MARKS):  # F1: a timestamp rejection ends the window for this event
                body.update(status="unknown", reconcile=True)
            elif row["cls"] == "state" and str(message).startswith(CAS_CONFLICT):  # §6.1.5 (DESIGN-B Q1): the CAS lost
                body.update(status="unknown", reconcile=True)

        self._commit(generation, row["id"], apply)
        counts["acknowledged"] += accepted is True
        counts["unknown"] += accepted is None

    def _reconcile_append(self, generation: int, row: dict, now: int, counts: dict,
                          stop: Callable[[], bool] | None = None) -> None:
        """§6.1 step 4, append-only: by the `zr-op` tag; absence is never concluded; re-publication is throttled."""
        tag = next(tag[1] for tag in row["event"]["tags"] if tag[:1] == [OP_TAG])
        found = self._match(
            [{"kinds": [row["event"]["kind"]], "authors": [row["event"]["pubkey"]], "#" + OP_TAG: [tag]}],
            lambda event: any(t[:2] == [OP_TAG, tag] for t in event["tags"])
            and event["pubkey"] == row["event"]["pubkey"] and event["content"] == row["event"]["content"])
        if found is not None:
            def acknowledge(body: dict) -> None:
                body.update(last_attempt_at=now, canonical_event_id=found["id"])
                self._reclaim(body, "acknowledged")

            self._commit(generation, row["id"], acknowledge)
            counts["reconciled"] += 1
            counts["acknowledged"] += 1
            return
        stalled = row["stalled_passes"] + 1
        since = row["last_republish_at"] if row["last_republish_at"] is not None else row["created_at"]
        if stalled < REPUBLISH_PASSES or now - since < REPUBLISH_GAP:
            self._commit(generation, row["id"], lambda body: body.update(status="unknown", stalled_passes=stalled))
            counts["unknown"] += 1
            return
        # At-least-once: a NEW signed copy of the same logical op, stored before it is sent (C3).
        fresh = self.signer.sign(row["role"], {**row["unsigned"], "created_at": now})
        self._commit(generation, row["id"], lambda body: body.update(
            status="unknown", event=fresh, event_id=fresh["id"], created_at=now, stalled_passes=0,
            last_republish_at=now, reconcile=False))
        counts["republished"] += 1
        if stop is not None and stop():
            return  # D5 F1: the fresh copy is stored; the next pass resends it within its drift window
        self._resend(generation, {**row, "event": fresh}, now, counts)

    def _reconcile_state(self, generation: int, row: dict, now: int, counts: dict,
                         stop: Callable[[], bool] | None = None) -> None:
        """§6.1 step 4, state: a positive `ids` match, else re-plan a NEW version regardless of the unknown."""
        ident = row["event_id"]
        found = self._match([{"ids": [ident]}], lambda event: event["id"] == ident
                            and event["pubkey"] == row["event"]["pubkey"])
        if found is not None:
            def acknowledge(body: dict) -> None:
                body["last_attempt_at"] = now
                self._reclaim(body, "acknowledged")

            self._commit(generation, row["id"], acknowledge)
            counts["reconciled"] += 1
            counts["acknowledged"] += 1
            return
        if stop is not None and stop():
            return  # D5 F1: replan queries the relay once more; the row stays as it is and the next pass reconciles it
        plan = self.replan(row["subject"])
        if plan and plan.get("superseded") is True:  # §6.1.5: the relay head already carries newer state (or nothing is
            self._commit(generation, row["id"], lambda body: self._reclaim(body, "superseded"))  # to say over it)
            counts["superseded"] += 1
            return
        if not plan:  # nothing new to say: the op stays unknown
            self._commit(generation, row["id"], lambda body: body.update(status="unknown"))
            counts["unknown"] += 1
            return
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            current = tx.get(OUTBOX, row["id"])
            outcome = self._enqueue(tx, row["subject"], plan["version"], plan["unsigned"], "state", row["role"],
                                    recovering=False, retire=row["id"])
            if outcome["status"] == "stale" and current["status"] != "superseded":
                self._reclaim(current, "superseded")  # a newer version already exists: this one is moot
                tx.put(OUTBOX, current["id"], current)
        counts["replanned"] += outcome["status"] == "enqueued"
        counts["superseded"] += 1 if outcome["status"] in ("enqueued", "stale") else 0

    # -- relay (never raises: an error is an unknown outcome, §6.1 step 4) -------------------------------

    def _publish(self, event: dict) -> dict:
        try:
            return self.relay.publish(event)
        except Exception as error:  # noqa: BLE001 - an unreachable relay proves nothing
            return {"accepted": None, "prefix": "unknown", "message": f"error:{type(error).__name__}"}

    def _match(self, filters: list[dict], accept: Callable[[dict], bool]) -> dict | None:
        """The first VERIFIED matching event, else None. An empty, erroring or non-EOSE answer proves nothing."""
        try:
            result = self.relay.query(filters)
        except Exception:  # noqa: BLE001
            return None
        return next((event for event in result.get("events", []) if accept(event)), None)

    def _commit(self, generation: int, op_id: str, apply: Callable[[dict], None]) -> None:
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            body = tx.get(OUTBOX, op_id)
            if body is None or body["status"] not in ("pending", "unknown", "in_flight"):
                return  # superseded meanwhile
            apply(body)
            if body["status"] == "acknowledged" and "ack_seq" not in body:  # B6 F2: the order, in this transaction
                counter = tx.get(ACKS, "seq") or {"id": "seq", "seq": 0}
                counter["seq"] += 1
                tx.put(ACKS, "seq", counter)
                body["ack_seq"] = counter["seq"]
            tx.put(OUTBOX, op_id, body)

    # -- recovery ---------------------------------------------------------------------------------------

    def recover_deferred(self, generation: int, regenerate: Callable[[str, list | None], list[dict]], *,
                         stop: Callable[[], bool] | None = None) -> dict:
        """Regenerate deferred work oldest-first once capacity frees; `{cls: count enqueued}`.

        `regenerate(cls, after_watermark)` stands in for the audit records (Batch B): it returns
        `{"subject", "version", "unsigned"}` items after the watermark, oldest first.
        """
        recovered = {}
        with self.store.transaction() as tx:
            self.lease.require_current(tx, generation)
            classes = [row["cls"] for row in sorted(tx.scan(WATERMARKS), key=lambda row: row["cls"])
                       if row["deferred"]]
        for cls in classes:
            with self.store.transaction() as tx:
                self.lease.require_current(tx, generation)
                last = tx.get(WATERMARKS, cls)["last"]
            recovered[cls] = 0
            complete = True
            for item in regenerate(cls, last):
                if stop is not None and stop():
                    complete = False  # D5 F1: the watermark stays at the last op that fit; the next pass resumes
                    break
                with self.store.transaction() as tx:
                    self.lease.require_current(tx, generation)
                    outcome = self._enqueue(tx, item["subject"], item["version"], item["unsigned"], cls, self.role,
                                            recovering=True)
                if outcome["status"] == "deferred":
                    complete = False  # still full: the watermark stays at the last op that fit
                    break
                recovered[cls] += outcome["status"] == "enqueued"
            if complete:
                with self.store.transaction() as tx:
                    self.lease.require_current(tx, generation)
                    mark = tx.get(WATERMARKS, cls)
                    self._put_mark(tx, cls, mark, deferred=False, last=mark["last"])
                    if not any(row["deferred"] for row in tx.scan(WATERMARKS)):
                        alert = tx.get(ALERTS, ALERT_ID)
                        if alert is not None and alert["state"] == "open":
                            alert.update(state="resolved", resolved_at=int(self.clock()))
                            tx.put(ALERTS, ALERT_ID, alert)
        return recovered
