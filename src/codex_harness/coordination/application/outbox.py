"""Coordination's outbox append: the one writer of the `outbox` bucket bodies (REBUILD-DESIGN-v2 §2.7, §2.9).

Layer: application
Context: coordination
Owns: Outbox.append, the body `{"message": m, "sent": False}` that M7 writes inline at every outbox site
    (`adapters/executor.py:1959`, `application/service.py:87`, ...). S4 names it, so that a non-owner unit (review's
    decision commit, research's incident record) joins with its own transaction.
Does not own: authorization (the caller authorizes with routing's Organization first, in M7 order); the flusher
    and delivery (M7 `application/outbox.py`, S5)
Entry points: Outbox.append
Contracts: INV-MESSAGE-001
"""

from __future__ import annotations


class Outbox:
    """Stateless owner operation; its constructor takes nothing."""

    def append(self, tx, message: dict) -> None:
        # §2.9 rule 2: it joins the caller's unit and never opens, commits or nests a transaction.
        tx.put("outbox", message["message_id"], {"message": message, "sent": False})
