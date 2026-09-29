"""§2.9 recorder controls on a toy store (S0 exit check 5); the M7 unit runs in compare/.

The recorder must distinguish atomic from partial commits, stale from accepted ownership and
intent-before-effect from fabricated completion. These controls use a tiny in-memory store with the
same commit-on-success semantics as M7 `MemoryStore`, so they run in the target environment.
"""

from contextlib import contextmanager
from copy import deepcopy

import pytest
import recorder as rec


class ToyStore:
    def __init__(self):
        self.data = {}

    @contextmanager
    def transaction(self):
        draft = deepcopy(self.data)

        class Tx:
            def put(self, bucket, key, body):
                draft[bucket, key] = deepcopy(body)

            def get(self, bucket, key):
                return deepcopy(draft.get((bucket, key)))

        yield Tx()
        self.data = draft


AUTHORITY = {"releases", "release_queue"}


def completion(e):
    return e["kind"] == "write" and e["bucket"] == "decisions" and e["status"] == "succeeded"


def intent(e):
    return e["kind"] == "write" and e["bucket"] == "decisions" and e["status"] == "running"


def claim(store):
    with store.transaction() as tx:
        tx.put("decisions", "d", {"status": "running", "generation": 1})


def test_atomic_commit_and_clean_protocol():
    store = rec.RecordingStore(ToyStore())
    claim(store)
    store.recorder.effect("provider_call")
    with store.transaction() as tx:
        store.recorder.fence("lease", True)
        tx.put("releases", "r", {"status": "candidate"})
        tx.put("decisions", "d", {"status": "succeeded"})
    r = store.recorder
    assert r.classify(AUTHORITY, completion) == "atomic_commit"
    assert r.violations == [] and r.effect_protocol(intent, completion) == []


def test_failure_inside_the_unit_rolls_everything_back():
    store = rec.RecordingStore(ToyStore())
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.put("releases", "r", {"status": "candidate"})
            raise RuntimeError("injected before decision/outbox")
    assert store.recorder.classify(AUTHORITY, completion) == "atomic_rollback"
    assert store._inner.data == {}


def test_split_commit_is_reported_partial():
    store = rec.RecordingStore(ToyStore())
    with store.transaction() as tx:
        tx.put("releases", "r", {"status": "candidate"})
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            raise RuntimeError("decision/outbox never written")
    assert store.recorder.classify(AUTHORITY, completion) == "partial_commit"


def test_authority_and_completion_in_different_units_is_partial():
    store = rec.RecordingStore(ToyStore())
    with store.transaction() as tx:
        tx.put("releases", "r", {"status": "candidate"})
    with store.transaction() as tx:
        tx.put("decisions", "d", {"status": "succeeded"})
    assert store.recorder.classify(AUTHORITY, completion) == "partial_commit"


def test_nested_begin_is_a_violation():
    store = rec.RecordingStore(ToyStore())
    with store.transaction():
        with store.transaction():
            pass
    assert [v["kind"] for v in store.recorder.violations] == ["nested_begin"]


def test_stale_fence_refused_versus_ignored():
    refused = rec.RecordingStore(ToyStore())
    with pytest.raises(PermissionError):
        with refused.transaction():
            refused.recorder.fence("lease", False)
            raise PermissionError("stale lease")
    assert refused.recorder.violations == []
    assert refused.recorder.classify(AUTHORITY, completion) == "atomic_rollback"
    ignored = rec.RecordingStore(ToyStore())
    with ignored.transaction() as tx:
        ignored.recorder.fence("lease", False)
        tx.put("releases", "r", {"status": "candidate"})
    assert {v["kind"] for v in ignored.recorder.violations} == {
        "write_after_failed_fence", "commit_after_failed_fence"}


def test_effect_inside_a_unit_is_a_violation():
    store = rec.RecordingStore(ToyStore())
    with store.transaction():
        store.recorder.effect("provider_call")
    assert [v["kind"] for v in store.recorder.violations] == ["effect_inside_unit"]


def test_fabricated_completion_and_missing_intent_are_detected():
    store = rec.RecordingStore(ToyStore())
    claim(store)
    with store.transaction() as tx:
        tx.put("decisions", "d", {"status": "succeeded"})
    assert store.recorder.effect_protocol(intent, completion) == ["completion_without_effect"]
    early = rec.RecordingStore(ToyStore())
    early.recorder.effect("provider_call")
    claim(early)
    assert early.recorder.effect_protocol(intent, completion) == ["effect_without_committed_intent"]


def test_uncommitted_intent_does_not_count():
    store = rec.RecordingStore(ToyStore())
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.put("decisions", "d", {"status": "running"})
            raise RuntimeError("claim failed")
    store.recorder.effect("provider_call")
    assert store.recorder.effect_protocol(intent, completion) == ["effect_without_committed_intent"]


def test_write_outside_any_unit_is_a_violation():
    r = rec.Recorder()
    r.write("outbox", "k", {"status": "x"})
    assert [v["kind"] for v in r.violations] == ["write_outside_unit"]


def test_trace_holds_digests_not_bodies():
    store = rec.RecordingStore(ToyStore())
    with store.transaction() as tx:
        tx.put("releases", "r", {"status": "candidate", "secret_shaped": "payload-bytes"})
    text = repr(store.recorder.trace())
    assert "payload-bytes" not in text and "digest" in text
