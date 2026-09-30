"""The durable continuation intent writes.

Layer: application
Context: coordination
Owns: bucket continuation_intents. Its writers are this object, including the owner migration resume
    through `replace` (S7 carry), plus the joint units that grants and requalification commit themselves
    (S6-accepted, M7 bodies)
Does not own: what moves an intent (the other continuation objects)
Entry points: IntentStore (claim, create, move, apply, replace, note)
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.state import (
    BUCKET_INTENTS,
    EVENT_BLOCKED,
    EVENT_TRANSITION,
    IntentChanged,
)
from codex_harness.coordination.domain.continuation import (
    MAX_HISTORY,
    MAX_SLOTS,
    OPEN_STATES,
    PAUSED,
    RECOVERY_REQUIRED,
    REFUSED,
    RESEARCH_REQUIRED,
    ContinuationRefused,
    effect_free,
    intent_id,
    intent_slot,
    refuse,
    transition,
    view,
)
from codex_harness.kernel.ids import utcnow


class IntentStore:
    """The one writer of `continuation_intents`: slot claims, creation, compare-and-swap moves and
    field notes, each committed with its observer event (M7 `Continuation` intent writes)."""

    def __init__(self, store, *, clock=utcnow, observer=None):
        self.store = store
        self.clock = clock
        self.observer = observer

    # ----- durable intent writes ----------------------------------------------------------
    @staticmethod
    def claim(tx, key: str, policy_id: str) -> tuple:
        """The slot of one observation for this policy: its own row (a replay), else the first free
        slot past foreign refusals that never owned an effect. A foreign row that owns an effect is
        never reused, advanced or reported as this policy's progress: `intent_owned_elsewhere`."""
        for n in range(MAX_SLOTS):
            slot = intent_slot(key, n)
            old = tx.get(BUCKET_INTENTS, slot)
            if old is None or old.get("policy_id") == policy_id:
                return slot, old
            refuse(effect_free(old), "intent_owned_elsewhere", "operator", "policy_id")
        raise ContinuationRefused("intent_slots_exhausted", "operator", "intent_id")

    def create(self, fields: dict, attempt: dict, key: str | None = None) -> dict:
        """`key` is a slot `_claim` already resolved (the successor id is derived from it); it must
        still be free or this policy's own."""
        now = self.clock()
        transition(None, fields["state"])
        with self.store.transaction() as tx:
            if key is None:
                key, old = self.claim(tx, intent_id(fields["origin_job"], attempt, fields["evidence_sha256"],
                                                     fields["route"]), fields["policy_id"])
            else:
                old = tx.get(BUCKET_INTENTS, key)
                refuse(old is None or old.get("policy_id") == fields["policy_id"], "intent_owned_elsewhere",
                       "operator", "policy_id")
            if old is not None:
                return old  # the same observation again: a replay, never a second intent
            row = {"id": key, "successor_job": None, "evidence_refs": [], "session_mode": None, **fields,
                   **attempt, "version": 1, "created_at": now, "updated_at": now,
                   "history": [{"state": fields["state"], "reason_code": fields.get("reason_code"), "at": now}]}
            tx.put(BUCKET_INTENTS, key, row)
        self.emit(None, row)
        return row

    def move(self, intent: dict, target: str, **fields) -> dict:
        """Compare-and-swap on the intent version; a moved intent raises `IntentChanged`."""
        with self.store.transaction() as tx:
            previous, current = self.apply(tx, intent, target, fields)
        self.emit(previous, current)
        return current

    def apply(self, tx, intent: dict, target: str, fields: dict) -> tuple:
        """The compare-and-swap write inside an open control-store transaction (its own, or the
        Fleet's when the move commits together with an execution unit); the caller emits after."""
        current = tx.get(BUCKET_INTENTS, intent["id"])
        if current is None or current.get("version") != intent.get("version"):
            raise IntentChanged(intent["id"])
        previous = current["state"]
        current["state"] = transition(previous, target)
        now = self.clock()
        current.update({k: v for k, v in fields.items() if k != "error_type"}, version=current["version"] + 1,
                       updated_at=now)
        current["history"] = (current.get("history") or [])[-(MAX_HISTORY - 1):] + [
            {"state": target, "previous": previous, "reason_code": current.get("reason_code"),
             "error_type": fields.get("error_type"), "at": now}]
        tx.put(BUCKET_INTENTS, intent["id"], current)
        return previous, current

    @staticmethod
    def replace(tx, current: dict, row: dict) -> dict:
        """The compare-and-swap write of a row the caller computed from `current` inside the SAME open
        transaction (the owner migration resume, `migration_resume`). Unlike `apply` it reads no clock
        and rebuilds nothing, so the caller's unit writes exactly the row it computed; no event is
        emitted (M7 emits none at this write). A moved row or a row that is not `current`'s next version
        raises `IntentChanged` and writes nothing."""
        stored = tx.get(BUCKET_INTENTS, current["id"])
        if (stored is None or stored.get("version") != current.get("version") or row.get("id") != current["id"]
                or row.get("version") != current["version"] + 1):
            raise IntentChanged(current["id"])
        tx.put(BUCKET_INTENTS, row["id"], row)
        return row

    def note(self, intent: dict, *, emit: bool = False, **fields) -> dict:
        """The same compare-and-swap for a field of an unchanged state: launch evidence or a hold."""
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_INTENTS, intent["id"])
            if current is None or current.get("version") != intent.get("version"):
                raise IntentChanged(intent["id"])
            current.update(fields, version=current["version"] + 1, updated_at=self.clock())
            tx.put(BUCKET_INTENTS, intent["id"], current)
        if emit:
            self.emit(current["state"], current)
        return current

    def emit(self, previous, row) -> None:
        """After the commit, through the existing Observer port: identifiers and codes only."""
        if self.observer is None:
            return
        common = {"intent_id": row["id"], "family": row["family"], "route": row["route"], "state": row["state"],
                  "origin_job": row["origin_job"], "successor_job": row.get("successor_job"),
                  "next_owner": str(row.get("next_owner") or "none"), "next_action": view(row)["next_action"]}
        reason = row.get("reason_code") if isinstance(row.get("reason_code"), str) else None
        hold = row.get("hold") if row["state"] in OPEN_STATES and isinstance(row.get("hold"), dict) else None
        if row["state"] in {RESEARCH_REQUIRED, RECOVERY_REQUIRED, PAUSED, REFUSED} or hold is not None:
            if hold is not None:
                reason = hold.get("reason_code") if isinstance(hold.get("reason_code"), str) else None
            self.observer.emit(EVENT_BLOCKED, "unknown" if row["state"] == RECOVERY_REQUIRED else "blocked",
                               severity="warning", reason_code=_code(reason), attributes=common)
            return
        self.observer.emit(EVENT_TRANSITION, "observed", reason_code=_code(reason),
                           attributes={**common, "previous_state": previous})


def _code(reason):
    if not isinstance(reason, str):
        return None
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in reason)[:80]
    return cleaned if cleaned[:1].isalpha() else None
