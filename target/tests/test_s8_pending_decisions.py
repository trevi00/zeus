"""PendingDecisions.queue (S8 pilot 70, R-r4): put iff absent, in the caller's unit; True when put."""

from codex_harness.coordination.application.decisions import PendingDecisions
from codex_harness.storage.adapters.memory_store import MemoryStore


def test_queue_puts_once_and_leaves_an_existing_row_untouched():
    store, queue = MemoryStore(), PendingDecisions()
    first, second = {"id": "k", "status": "pending"}, {"id": "k", "status": "other"}
    with store.transaction() as tx:
        assert queue.queue(tx, first) is True
    with store.transaction() as tx:
        assert queue.queue(tx, second) is False
        assert tx.get("decisions_pending", "k") == first
