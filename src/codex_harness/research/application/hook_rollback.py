"""Research's hook rollback: a rolled-back release's active hook returns to its previous version (M7 inline in
`Releases.rollback`).

Layer: application
Context: research
Owns: the `hooks` row a release rollback restores (the hooks bucket is research's)
Does not own: the release rollback itself (review.application.releases), which calls this inside its unit
Entry points: HookRollback.roll_back
Contracts: INV-RELEASE-001, INV-RESEARCH-004

S7 named transcription (DESIGN-s7 V3 R6): the four lines are M7's, moved from review's rollback into research's owner
operation, which joins the caller's transaction.
"""
from __future__ import annotations


class HookRollback:
    """The hooks row a rollback restores, in the caller's transaction."""

    def roll_back(self, tx, record: dict) -> None:
        hook_id = record.get("candidate", {}).get("hook_id")
        hook = tx.get("hooks", hook_id) if hook_id else None
        if hook and hook["revision"] == record["candidate"]["revision"]:
            tx.put("hooks", hook_id, hook.get("previous_active") or {**hook, "status": "rolled_back"})
