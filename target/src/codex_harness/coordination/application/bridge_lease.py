"""The single active bridge's generation-fenced lease (design §6.5).

Layer: application
Context: coordination
Owns: the `bridge_owner` bucket: acquire, renew, require_current (and the `bridge_owner` rows in `execution_fences`)
Does not own: the bridge loop that holds the lease (composition), the transactions it fences (inbox, outbox)
Entry points: BridgeLease.acquire, BridgeLease.renew, BridgeLease.require_current
Contracts: INV-EXECUTION-IDENTITY-001

A free or expired lease is taken at generation + 1; a lease held live by another owner is not (the second bridge
stays passive). EVERY bridge transaction calls `require_current` INSIDE its own unit, so a stale bridge commits
nothing (buzz DESIGN §6.5, §6.2 step 3 iv). The generation also advances the shared durable fence ledger
(`execution_fence`, RESEARCH-S4 R1/R2), so a deleted or restored lease row never re-issues an old generation.
The lease fails closed: a missing row is `bridge_lease_lost`, unlike the legacy-tolerant fence read.
"""

from __future__ import annotations

from datetime import datetime, timezone

from codex_harness.coordination.application import execution_fence
from codex_harness.kernel.errors import ContractError, require

BUCKET = "bridge_owner"
FENCE_ROW = "bridge"
LOST = "bridge_lease_lost"


class _At:
    """The fence ledger's clock port, fixed at the caller's receiver time."""

    def __init__(self, now: float):
        self._now = now

    def now(self) -> datetime:
        return datetime.fromtimestamp(self._now, timezone.utc)


class BridgeLease:
    def acquire(self, tx, owner_id: str, now: float, ttl_seconds: float) -> int | None:
        """The new generation, or None while another owner holds an unexpired lease.

        The same owner re-acquiring a live lease also advances the generation: a restarted process must fence
        its own predecessor.
        """
        require(bool(owner_id) and ttl_seconds > 0, "Lease needs an owner and a positive ttl")
        row = tx.get(BUCKET, FENCE_ROW)
        if row is not None and row["owner"] != owner_id and now < row["expires_at"]:
            return None
        fence = execution_fence.current(tx, BUCKET, FENCE_ROW)
        generation = max(row["generation"] if row else 0, fence["generation"] if fence else 0) + 1
        execution_fence.advance(tx, BUCKET, FENCE_ROW, generation, owner_id, clock=_At(now))
        tx.put(BUCKET, FENCE_ROW, {"id": FENCE_ROW, "owner": owner_id, "generation": generation,
                                   "expires_at": now + ttl_seconds})
        return generation

    def renew(self, tx, owner_id: str, generation: int, now: float, ttl_seconds: float) -> float:
        """The new expiry; a stale generation or another owner's lease is `bridge_lease_lost`."""
        require(ttl_seconds > 0, "Lease needs a positive ttl")
        row = self._row(tx, generation)
        if row["owner"] != owner_id:
            raise ContractError(LOST)
        row["expires_at"] = now + ttl_seconds
        tx.put(BUCKET, FENCE_ROW, row)
        return row["expires_at"]

    def require_current(self, tx, generation: int) -> None:
        self._row(tx, generation)

    @staticmethod
    def _row(tx, generation: int) -> dict:
        row = tx.get(BUCKET, FENCE_ROW)
        if row is None or type(generation) is not int or row["generation"] != generation:
            raise ContractError(LOST)
        try:
            execution_fence.require_current(tx, BUCKET, FENCE_ROW, generation, row["owner"])
        except ContractError:
            raise ContractError(LOST) from None
        return row
