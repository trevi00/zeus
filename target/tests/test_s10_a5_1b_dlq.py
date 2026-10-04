"""S10 A5-1b (DESIGN-s10 §17a; RSM G2): `zeus dlq list|replay` over the `DeadLetters` use case.

MemoryStore, a LABELLED fake bus (`dead_letters`, `publish`, `stream`, the real `RedisBus.decode`) and a fixed clock; no
network. One real-Redis end-to-end test is gated on `HARNESS_REDIS_URL` (the owner runs it at target-integration).
"""
import json
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from codex_harness.composition import cli_dlq
from codex_harness.coordination.application.dead_letters import BUCKET, DeadLetters, replay_key
from codex_harness.coordination.ports import OWNED_BUCKETS
from codex_harness.entry import cli
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.message import envelope
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.redis_bus import RedisBus
from codex_harness.storage.ports import MessageDeliveryError

NAMESPACE = "ns"
SOURCE = f"{NAMESPACE}:agent:dev"
SECRET = "body-text-that-must-never-be-printed"
REDIS_URL = os.environ.get("HARNESS_REDIS_URL")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="Set HARNESS_REDIS_URL (target-integration sets it)")


class FixedClock:
    def now(self):
        return datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


class FakeBus:
    """LABELLED FAKE of the dead-letter side of RedisBus: stream order records, an unbound publish, the real decode."""

    namespace = NAMESPACE
    decode = staticmethod(RedisBus.decode)

    def __init__(self, records, fail=None):
        self.records, self.fail, self.published = list(records), fail, []

    def stream(self, agent):
        return f"{self.namespace}:agent:{agent}"

    def dead_letters(self, limit):
        return self.records[:limit + 1]

    def publish(self, message):
        if self.fail is not None:
            raise self.fail
        self.published.append(message)
        return f"{len(self.published)}-0"


def message(recipient="dev", text=SECRET):
    return envelope("task.assign", "orchestrator", recipient, "implement", {"objective": text}, "a51b")


def body(msg):
    return json.dumps(msg, sort_keys=True)


def record(dead_id, entry_id, text, reason="Unknown agent", source=SOURCE):
    return (dead_id, {"source": source, "entry_id": entry_id, "body": text, "reason": reason})


def service(records, fail=None, limit=10000):
    store, bus = MemoryStore(), FakeBus(records, fail)
    return DeadLetters(store, bus, clock=FixedClock(), limit=limit), store, bus


def stored(store, source=SOURCE, entry_id="1-0"):
    with store.transaction() as tx:
        return tx.get(BUCKET, replay_key(source, entry_id))


def refusal(call):
    with pytest.raises(ContractError) as caught:
        call()
    return str(caught.value)


def replay(use, **over):
    return use.replay(SOURCE, "1-0", **{"reason": "agent registered after fix", "actor": "operator-lead", **over})


def test_the_bucket_is_declared_by_coordination():
    assert OWNED_BUCKETS.count("dead_letter_replays") == 1 and BUCKET == "dead_letter_replays"


def test_list_groups_duplicate_records_sorts_and_never_prints_a_body():
    msg = message()
    text = body(msg)
    use, _, _ = service([record("1-0", "9-0", text, "b reason"), record("2-0", "2-0", text, "x" * 300),
                         record("3-0", "9-0", text, "a reason"), record("4-0", "9-0", text, "a reason")])
    result = use.list()
    assert result["groups"] == 2 and result["records"] == 4
    assert [(g["source"], g["entry_id"]) for g in result["dead_letters"]] == [(SOURCE, "2-0"), (SOURCE, "9-0")]
    first, second = result["dead_letters"]
    assert second["records"] == 3 and second["dead_letter_ids"] == ["1-0", "3-0", "4-0"]
    assert second["reasons"] == ["a reason", "b reason"] and first["reasons"] == ["x" * 200]
    assert second["body_bytes"] == len(text.encode()) and len(second["body_sha256"]) == 64
    assert second["body_conflict"] is False and second["replay"] is None
    assert SECRET not in json.dumps(result)


def test_list_flags_a_body_conflict_and_refuses_a_backlog_over_the_limit():
    use, _, _ = service([record("1-0", "1-0", body(message("dev", "one"))), record("2-0", "1-0", body(message("dev", "two")))])
    assert use.list()["dead_letters"][0]["body_conflict"] is True
    over, _, _ = service([record(f"{i}-0", f"{i}-0", "{}") for i in range(4)], limit=3)
    assert refusal(over.list) == "dead_letter_backlog_exceeds_limit"
    exact, _, _ = service([record(f"{i}-0", f"{i}-0", "{}") for i in range(3)], limit=3)
    assert exact.list()["records"] == 3


def test_replay_publishes_the_decoded_message_once_and_records_every_field():
    msg = message()
    use, store, bus = service([record("1-0", "1-0", body(msg), "boom"), record("2-0", "1-0", body(msg), "boom")])
    done = replay(use)
    assert bus.published == [msg]  # a duplicate-record group publishes once
    assert stored(store) == done
    assert done == {"id": replay_key(SOURCE, "1-0"), "status": "completed", "source": SOURCE, "entry_id": "1-0",
                    "dead_letter_ids": ["1-0", "2-0"], "reasons": ["boom"],
                    "body_sha256": use.list()["dead_letters"][0]["body_sha256"],
                    "operator_reason": "agent registered after fix", "actor": "operator-lead", "attempts": 1,
                    "created_at": "2026-10-04T12:00:00+00:00", "updated_at": "2026-10-04T12:00:00+00:00",
                    "replayed_entry_id": "1-0"}
    assert use.list()["dead_letters"][0]["replay"] == {"status": "completed", "attempts": 1, "replayed_entry_id": "1-0"}


def test_a_second_replay_is_already_replayed_and_publishes_nothing():
    use, _, bus = service([record("1-0", "1-0", body(message()))])
    replay(use)
    assert refusal(lambda: replay(use)) == "already_replayed"
    assert len(bus.published) == 1


def test_each_refusal_in_order_leaves_no_publish_and_no_record():
    good = body(message())
    cases = [
        ({"reason": ""}, [record("1-0", "1-0", good)], "replay_reason_invalid"),
        ({"reason": "x" * 501}, [record("1-0", "1-0", good)], "replay_reason_invalid"),
        ({"reason": "bad\nreason"}, [record("1-0", "1-0", good)], "replay_reason_invalid"),
        ({"reason": 5}, [record("1-0", "1-0", good)], "replay_reason_invalid"),
        ({"actor": "not an id"}, [record("1-0", "1-0", good)], "replay_actor_invalid"),
        ({"actor": "ok\n"}, [record("1-0", "1-0", good)], "replay_actor_invalid"),
        ({"reason": "", "actor": "bad actor"}, [], "replay_reason_invalid"),
        ({}, [], "dead_letter_missing"),
        ({}, [record("1-0", "1-0", good), record("2-0", "1-0", body(message("dev", "other")))], "dead_letter_body_conflict"),
        ({}, [record("1-0", "1-0", "not json")], "body_invalid"),
        ({}, [record("1-0", "1-0", json.dumps({"schema_version": 1}))], "body_invalid"),
        ({}, [record("1-0", "1-0", body(message("other")))], "route_mismatch"),
    ]
    for over, records, code in cases:
        use, store, bus = service(records)
        assert refusal(lambda: replay(use, **over)) == code, (over, code)
        assert bus.published == [] and stored(store) is None, code


class AcceptThenTimeoutClient:
    """LABELLED in-memory fake of the redis client: `xadd` records the acceptance, then the response is lost."""

    def __init__(self):
        self.accepted = []

    def xadd(self, stream, fields):
        from redis.exceptions import TimeoutError as RedisTimeoutError

        self.accepted.append((stream, dict(fields)))
        raise RedisTimeoutError("response lost")


def real_bus(client):
    bus = RedisBus.__new__(RedisBus)
    bus.namespace, bus.client = NAMESPACE, client
    return bus


def test_an_ambiguous_publish_stays_in_doubt_across_a_fresh_instance_and_publishes_once():
    """F1: the REAL RedisBus maps a lost XADD response to MessageDeliveryError; the write may have happened."""
    client = AcceptThenTimeoutClient()
    bus = real_bus(client)
    bus.records = [record("1-0", "1-0", body(message()))]
    bus.dead_letters = lambda limit: bus.records[:limit + 1]
    store = MemoryStore()
    assert refusal(lambda: replay(DeadLetters(store, bus, clock=FixedClock()))) == "replay_in_doubt"
    held = stored(store)
    assert held["status"] == "intent" and held["error_type"] == "TimeoutError" and held["attempts"] == 1
    assert held["operator_reason"] == "agent registered after fix" and held["actor"] == "operator-lead"
    assert refusal(lambda: replay(DeadLetters(store, bus, clock=FixedClock()))) == "replay_in_doubt"
    assert len(client.accepted) == 1 and stored(store)["attempts"] == 1


def test_an_error_before_any_accepted_write_is_also_held():
    use, store, bus = service([record("1-0", "1-0", body(message()))], fail=MessageDeliveryError("ConnectionError"))
    assert refusal(lambda: replay(use)) == "replay_in_doubt"
    held = stored(store)
    assert held["status"] == "intent" and held["error_type"] == "MessageDeliveryError" and held["attempts"] == 1
    bus.fail = None
    assert refusal(lambda: replay(use)) == "replay_in_doubt"
    assert bus.published == []
    assert use.list()["dead_letters"][0]["replay"] == {"status": "intent", "attempts": 1, "replayed_entry_id": None}


def test_an_error_type_never_carries_the_exception_text():
    use, store, _ = service([record("1-0", "1-0", body(message()))], fail=MessageDeliveryError("secret-detail"))
    refusal(lambda: replay(use))
    assert stored(store)["error_type"] == "MessageDeliveryError" and "secret-detail" not in json.dumps(stored(store))


def test_a_persistence_failure_after_a_successful_publish_leaves_intent_and_a_retry_is_in_doubt():
    use, store, bus = service([record("1-0", "1-0", body(message()))])
    original = use._finish

    def broken(key, outcome):
        raise RuntimeError("store down")

    use._finish = broken
    with pytest.raises(RuntimeError):
        replay(use)
    use._finish = original
    assert len(bus.published) == 1 and stored(store)["status"] == "intent"
    assert refusal(lambda: replay(use)) == "replay_in_doubt"
    assert len(bus.published) == 1


def test_an_unfinished_intent_is_replay_in_doubt():
    use, store, bus = service([record("1-0", "1-0", body(message()))])
    with store.transaction() as tx:
        tx.put(BUCKET, replay_key(SOURCE, "1-0"), {"id": replay_key(SOURCE, "1-0"), "status": "intent", "attempts": 1})
    assert refusal(lambda: replay(use)) == "replay_in_doubt"
    assert bus.published == [] and stored(store)["status"] == "intent"


def test_a_predecessor_failed_record_after_an_accepted_publish_is_in_doubt_and_publishes_once():
    """F1 round 2: the e0dc49c4 replay wrote `failed` (with the exception text) after an accepted XADD whose response was
    lost. That record carries no proof that nothing was written, so a fresh instance refuses it like an `intent`."""
    client = AcceptThenTimeoutClient()
    bus = real_bus(client)
    bus.records = [record("1-0", "1-0", body(message()))]
    bus.dead_letters = lambda limit: bus.records[:limit + 1]
    with pytest.raises(MessageDeliveryError):
        bus.publish(message())  # the predecessor's accepted publish, response lost
    key, at = replay_key(SOURCE, "1-0"), "2026-10-03T09:00:00+00:00"
    predecessor = {"id": key, "status": "failed", "source": SOURCE, "entry_id": "1-0", "dead_letter_ids": ["1-0"],
                   "reasons": ["Unknown agent"], "body_sha256": "0" * 64, "operator_reason": "first operator reason",
                   "actor": "operator-first", "attempts": 1, "created_at": at, "updated_at": at,
                   "error_type": "Timeout reading from socket"}
    store = MemoryStore()
    with store.transaction() as tx:
        tx.put(BUCKET, key, dict(predecessor))
    assert refusal(lambda: replay(DeadLetters(store, bus, clock=FixedClock()))) == "replay_in_doubt"
    assert len(client.accepted) == 1, "a second accepted XADD: the predecessor's ambiguous replay was published again"
    assert stored(store) == predecessor  # the original audit and attempt count are unchanged


def test_the_root_is_composed_and_main_dispatches_list_and_replay(monkeypatch, capsys):
    import ast
    from pathlib import Path

    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    assert any("dlq" in {k.value for k in node.keys if isinstance(k, ast.Constant)}
               for node in ast.walk(tree) if isinstance(node, ast.Dict))
    use, store, bus = service([record("1-0", "1-0", body(message()))])
    monkeypatch.setattr(cli_dlq, "dead_letters", lambda: use)

    def main(*argv):
        monkeypatch.setattr(sys, "argv", ["zeus", *argv])
        try:
            cli.main()
            code = 0
        except SystemExit as exc:
            code = exc.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    code, out, _ = main("dlq", "list")
    assert code == 0 and json.loads(out)["groups"] == 1 and SECRET not in out
    replay_args = ("dlq", "replay", "--source", SOURCE, "--entry-id", "1-0", "--reason", "fixed", "--actor", "operator-lead")
    code, out, _ = main(*replay_args)
    assert code == 0 and json.loads(out)["status"] == "completed" and len(bus.published) == 1
    code, out, err = main(*replay_args)
    assert code == 1 and "already_replayed" in out + err and len(bus.published) == 1
    assert main("dlq", "replay", "--source", SOURCE)[0] == 2  # argparse: the other options are required


def test_dead_letters_rejects_a_bad_limit_and_wraps_a_redis_error():
    from redis.exceptions import ConnectionError as RedisConnectionError

    class Client:
        def xrange(self, name, lo, hi, count):
            assert (name, lo, hi, count) == (f"{NAMESPACE}:dead-letter", "-", "+", 4)
            raise RedisConnectionError("down")

    bus = RedisBus.__new__(RedisBus)
    bus.namespace, bus.client = NAMESPACE, Client()
    for bad in (-1, True, "3", 1.5):
        with pytest.raises(ValueError):
            bus.dead_letters(bad)
    with pytest.raises(MessageDeliveryError) as caught:
        bus.dead_letters(3)
    assert str(caught.value) == "ConnectionError"


@needs_redis
def test_end_to_end_dead_letter_list_replay_against_a_real_redis():
    bus = RedisBus(REDIS_URL, f"a51b-{uuid4().hex[:12]}")
    msg = message("dev", "e2e")
    try:
        bus.publish(msg)
        entry_id, fields = bus.receive("dev", "c1")
        bus.dead_letter("dev", entry_id, fields, "Unknown agent")
        use = DeadLetters(MemoryStore(), bus, clock=FixedClock())
        listed = use.list()
        assert listed["groups"] == 1 and listed["dead_letters"][0]["entry_id"] == entry_id
        done = use.replay(bus.stream("dev"), entry_id, reason="registered", actor="operator-lead")
        assert done["status"] == "completed"
        entries = bus.client.xrange(bus.stream("dev"), "-", "+")
        assert [RedisBus.decode(f)["message_id"] for _, f in entries] == [msg["message_id"]] * 2
        assert entries[-1][0] == done["replayed_entry_id"]
    finally:
        for key in list(bus.client.scan_iter(match=bus.namespace + ":*")):
            bus.client.delete(key)
