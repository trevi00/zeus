"""S7 carry (FLEET-REBUILD-S6-ACCEPT, DESIGN-s7 §4 item 5): `IntentStore.replace`, the compare-and-swap write the owner
migration resume routes through. The end-to-end unit is characterized by the `coordination.owner_actions_migration`
golden (group `complete`); these cases pin the write's own refusals, with nothing written on any of them.
"""

from __future__ import annotations

import copy

import pytest

from codex_harness.coordination.application.continuation.intents import IntentStore
from codex_harness.coordination.application.continuation.state import BUCKET_INTENTS, IntentChanged
from codex_harness.storage.adapters.memory_store import MemoryStore

ROW = {"id": "intent-1", "state": "paused", "version": 3, "reason_code": "held", "history": []}


def world():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put(BUCKET_INTENTS, ROW["id"], copy.deepcopy(ROW))
    return store


def stored(store):
    with store.transaction() as tx:
        return tx.get(BUCKET_INTENTS, ROW["id"])


def test_the_next_version_computed_in_the_same_transaction_is_written_exactly():
    store = world()
    resumed = {**ROW, "state": "awaiting_owner", "version": 4, "reason_code": "migration_resumed"}
    with store.transaction() as tx:
        current = tx.get(BUCKET_INTENTS, ROW["id"])
        assert IntentStore.replace(tx, current, copy.deepcopy(resumed)) == resumed
    assert stored(store) == resumed


@pytest.mark.parametrize("current_version,row_changes", [
    (2, {"version": 3}),                       # the caller read a moved row: the stored version differs
    (3, {"version": 5}),                       # not the next version
    (3, {"version": 3}),                       # the same version again
    (3, {"version": 4, "id": "intent-2"}),     # another id
])
def test_a_moved_or_out_of_sequence_row_is_refused_and_nothing_is_written(current_version, row_changes):
    store = world()
    before = stored(store)
    with pytest.raises(IntentChanged):
        with store.transaction() as tx:
            IntentStore.replace(tx, {**ROW, "version": current_version}, {**ROW, "state": "awaiting_owner",
                                                                            **row_changes})
    assert stored(store) == before


def test_a_missing_row_is_refused():
    store = MemoryStore()
    with pytest.raises(IntentChanged):
        with store.transaction() as tx:
            IntentStore.replace(tx, ROW, {**ROW, "version": 4})
    with store.transaction() as tx:
        assert tx.get(BUCKET_INTENTS, ROW["id"]) is None
