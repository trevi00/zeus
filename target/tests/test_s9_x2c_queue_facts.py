"""S9 X2c: queue depth and oldest-age facts as bounded state reads; truncated or unreadable is unavailable, never zero (DESIGN-s9-X §2.4)."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from codex_harness.observation.adapters.metrics_exposition import render
from codex_harness.observation.adapters.queue_facts import QueueFacts
from codex_harness.storage.adapters.memory_store import MemoryStore

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
FAMILIES = ["zeus_queue_depth", "zeus_queue_facts_available", "zeus_queue_oldest_age_seconds", "zeus_queue_scanned_rows",
            "zeus_queue_unparseable_rows"]


def ago(seconds):
    return (NOW - timedelta(seconds=seconds)).isoformat()


def message(name, seconds):
    return {"message_id": name, "when": {"created_at": ago(seconds)}}


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def fixture():
    store = MemoryStore()
    for key, seconds, sent in (("o1", 600, False), ("o2", 300, False), ("o3", 60, False), ("o4", 900, True), ("o5", 800, True)):
        put(store, "outbox", key, {"message": message("SECRET-" + key, seconds), "sent": sent})
    for key, seconds in (("d1", 120), ("d2", 30)):
        put(store, "decisions_pending", key, {"id": key, "status": "pending", "message": message(key, seconds)})
    put(store, "decisions_pending", "d3", {"id": "d3", "status": "succeeded", "message": message("d3", 5000)})
    put(store, "release_queue", "r1", {"id": "r1", "status": "queued", "at": ago(45)})
    put(store, "release_queue", "r2", {"id": "r2", "status": "done", "at": ago(4000)})
    for key, status, seconds in (("t1", "queued", 200), ("t2", "queued", 100), ("t3", "retry", 400), ("t4", "running", 3000),
                                 ("t5", "succeeded", 9000)):
        put(store, "tasks", key, {"id": key, "status": status, "created_at": ago(seconds)})
    return store


def series(rows, name):
    return {tuple(s["labels"]): s["value"] for row in rows if row["metric"] == name for s in row["series"]}


def facts(store, **kw):
    return QueueFacts(store, now=lambda: NOW, **kw).rows()


def test_exact_values():
    rows = facts(fixture())
    assert [r["metric"] for r in rows] == FAMILIES
    assert series(rows, "zeus_queue_depth") == {
        ("decisions_pending", "waiting"): 2, ("outbox", "waiting"): 3, ("release_queue", "waiting"): 1,
        ("tasks", "in_progress"): 1, ("tasks", "waiting"): 3}
    assert series(rows, "zeus_queue_oldest_age_seconds") == {
        ("decisions_pending",): 120.0, ("outbox",): 600.0, ("release_queue",): 45.0, ("tasks",): 400.0}
    assert series(rows, "zeus_queue_scanned_rows") == {("decisions_pending",): 3, ("outbox",): 5, ("release_queue",): 2, ("tasks",): 5}
    assert set(series(rows, "zeus_queue_facts_available").values()) == {1}
    assert set(series(rows, "zeus_queue_unparseable_rows").values()) == {0}


def test_empty_queues():
    rows = facts(MemoryStore())
    assert series(rows, "zeus_queue_depth")[("outbox", "waiting")] == 0
    assert series(rows, "zeus_queue_depth")[("tasks", "in_progress")] == 0
    assert series(rows, "zeus_queue_oldest_age_seconds") == {}
    assert series(rows, "zeus_queue_facts_available") == {(q,): 1 for q in ("decisions_pending", "outbox", "release_queue", "tasks")}


def test_truncation_is_unavailable_not_zero():
    rows = facts(fixture(), limit=4)
    available = series(rows, "zeus_queue_facts_available")
    assert available[("outbox",)] == 0 and available[("tasks",)] == 0
    assert available[("decisions_pending",)] == 1 and available[("release_queue",)] == 1
    for name in ("zeus_queue_depth", "zeus_queue_oldest_age_seconds", "zeus_queue_unparseable_rows"):
        assert not any(labels[0] in ("outbox", "tasks") for labels in series(rows, name))
    assert series(rows, "zeus_queue_depth")[("decisions_pending", "waiting")] == 2
    assert series(rows, "zeus_queue_oldest_age_seconds")[("release_queue",)] == 45.0


def test_read_error_makes_every_queue_unavailable():
    class Broken:
        @contextmanager
        def transaction(self):
            raise RuntimeError("SECRET-db-password")
            yield

    rows = facts(Broken())
    assert series(rows, "zeus_queue_facts_available") == {(q,): 0 for q in ("decisions_pending", "outbox", "release_queue", "tasks")}
    for row in rows:
        if row["metric"] != "zeus_queue_facts_available":
            assert row["series"] == []
    assert "SECRET" not in json.dumps(rows)


def test_unparseable_times_are_counted_and_excluded():
    store = MemoryStore()
    put(store, "outbox", "a", {"message": {"when": {}}, "sent": False})
    put(store, "outbox", "b", {"message": {"when": {"created_at": "2026-10-03T11:00:00"}}, "sent": False})
    put(store, "outbox", "c", {"message": {"when": {"created_at": (NOW + timedelta(seconds=10)).isoformat()}}, "sent": False})
    put(store, "outbox", "d", {"message": {"when": {"created_at": "garbage"}}, "sent": False})
    put(store, "outbox", "e", {"message": message("e", 30), "sent": False})
    rows = facts(store)
    assert series(rows, "zeus_queue_depth")[("outbox", "waiting")] == 5
    assert series(rows, "zeus_queue_unparseable_rows")[("outbox",)] == 4
    assert series(rows, "zeus_queue_oldest_age_seconds")[("outbox",)] == 30.0


def test_no_identifiers_in_output():
    rows = facts(fixture())
    assert "SECRET" not in json.dumps(rows)
    allowed = {"outbox", "decisions_pending", "release_queue", "tasks", "waiting", "in_progress"}
    for row in rows:
        for item in row["series"]:
            assert set(item["labels"]) <= allowed
            assert type(item["value"]) in (int, float)


def test_renderable():
    text = render(facts(fixture()))
    for family in FAMILIES:
        assert f"# TYPE {family} gauge" in text
    assert 'zeus_queue_depth{queue="outbox",state="waiting"} 3' in text
    assert 'zeus_queue_oldest_age_seconds{queue="outbox"} 600.0' in text


def test_read_only():
    store = fixture()
    before = repr(sorted(store.data.items()))
    facts(store)
    assert repr(sorted(store.data.items())) == before
