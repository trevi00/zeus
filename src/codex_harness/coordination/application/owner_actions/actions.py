"""The durable owner-action rows.

Layer: application
Context: coordination
Owns: bucket owner_actions (sole writer)
Does not own: what moves an action (the families)
Entry points: ActionStore
Contracts: INV-OWNER-ACTIONS-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.owner_actions.state import BUCKET_ACTIONS, ActionChanged
from codex_harness.coordination.domain.owner_actions import action_id, moved, new_action
from codex_harness.kernel.ids import utcnow


class ActionStore:
    """The one writer of `owner_actions` rows: creation once per identity and compare-and-swap moves
    (M7 `OwnerActions` action writes)."""

    def __init__(self, store, *, clock=utcnow):
        self.store = store
        self.clock = clock

    def create(self, row: dict, kind: str, binding: dict, subject: dict) -> list:
        identity = action_id(kind, binding)
        with self.store.transaction() as tx:
            if tx.get(BUCKET_ACTIONS, identity) is not None:
                return []
            tx.put(BUCKET_ACTIONS, identity, new_action(kind, binding, row, subject, self.clock()))
        return [identity]

    # ----- durable moves ------------------------------------------------------------------------------
    def move(self, action: dict, target: str, reason_code: str | None = None, *, extra=None, **fields) -> dict:
        """Compare-and-swap on the version; `extra(tx)` writes in the same transaction (a decision row)."""
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_ACTIONS, action["id"])
            if not (isinstance(current, dict) and current.get("version") == action.get("version")):
                raise ActionChanged(action["id"])
            row = moved(current, target, self.clock(), reason_code, **fields)
            if extra is not None:
                extra(tx)
            tx.put(BUCKET_ACTIONS, row["id"], row)
        return row

    @staticmethod
    def effect(row: dict) -> dict:
        return {"action": row["id"], "kind": row["kind"], "state": row["state"], "reason_code": row["reason_code"]}
