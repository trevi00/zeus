"""REDIS-STREAMS-RELIABILITY-20261003 rows 2-3 (map G1, G2): discriminating tests over the EXISTING bus and
workflow behaviour. No product module changes; these characterize, they do not prescribe.

- G1 (real Redis): a reclaim (`XAUTOCLAIM` by idle time) racing a consumer that is still handling the entry.
  Idle is not proof the effect stopped, so both consumers may run `workflow.handle`; business idempotency is by
  message identity (never entry id) in the workflow/store, so the second handle must be a no-op.
- G2 (real Redis) and G2b (fake client, runs everywhere): `RedisBus.dead_letter` is ONE Lua script (XADD
  `<ns>:dead-letter` then XACK). Declared intended change, S10 A5-1a (DESIGN-s10 §17a); the S9 window (a crash
  between two commands leaving a pending entry behind a record) no longer exists. A fault before the script
  leaves no record and the entry pending; the redelivery writes exactly one record.

Real-Redis tests are integration-gated: they skip unless `HARNESS_REDIS_URL` is set (target-integration sets it).
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

sys.path.insert(0, str(Path(__file__).parent / "ported"))
from m7_coordination import Workflow, organization  # noqa: E402

from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.redis_bus import RedisBus  # noqa: E402

REDIS_URL = os.environ.get("HARNESS_REDIS_URL")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="Set HARNESS_REDIS_URL (target-integration sets it)")
AGENT = "worker:implementation"


def assignment():
    parent = organization().actor(AGENT).parent
    return envelope("task.assign", parent, AGENT, "implement", {"objective": "fixture"}, "s9-redis")


def delete_namespace(bus):
    for key in list(bus.client.scan_iter(match=bus.namespace + ":*")):
        bus.client.delete(key)


def pending_rows(bus, agent):
    return bus.client.xpending_range(bus.stream(agent), "workers", min="-", max="+", count=10)


@needs_redis
def test_a_reclaim_while_the_first_consumer_still_handles_yields_one_business_effect():
    """Matrix row G1. Consumer A receives and does not ack (still handling); after the idle threshold B reclaims
    the SAME entry id (XAUTOCLAIM, delivery count 2) and both run `workflow.handle` on one store, then both ack.
    PROVES: one business effect: a single `tasks` row and no outbox row (a task.assign queues no next message);
    the second handle is the idempotent path `Workflow.submit` defines: the existing task row for the message id
    is found (`old`), its `input_hash` equals the message digest (else "Conflicting task identity"), no terminal
    parking applies, and `return old` hands back the stored row unchanged. Both ACKs leave XPENDING empty.
    REFUTES: that a reclaim racing a live handler can double the effect (it cannot: identity is the message id)."""
    bus = RedisBus(REDIS_URL, "zeus-s9-g1-" + uuid4().hex)
    workflow = Workflow(MemoryStore(), organization())
    message = assignment()
    try:
        bus.publish(message)
        first = bus.receive(AGENT, "consumer-a")
        assert first is not None
        time.sleep(0.05)
        second = bus.receive(AGENT, "consumer-b", idle_ms=10)
        assert second is not None and second[0] == first[0], "B reclaimed the SAME entry id"
        rows = pending_rows(bus, AGENT)
        assert [(r["message_id"], r["consumer"], r["times_delivered"]) for r in rows] == [(first[0], "consumer-b", 2)]

        decoded_a, decoded_b = bus.decode(first[1]), bus.decode(second[1])
        assert decoded_a == decoded_b and decoded_a["message_id"] == message["message_id"]
        stored_first = workflow.handle(decoded_a)
        stored_second = workflow.handle(decoded_b)
        assert stored_first["status"] == "queued" and stored_second == stored_first, \
            "the second handle returns the existing task row (Workflow.submit `return old`)"

        with workflow.store.transaction() as tx:
            assert [t["id"] for t in tx.scan("tasks")] == [message["message_id"]]
            assert tx.scan("outbox") == []
        bus.ack(AGENT, first[0])
        bus.ack(AGENT, second[0])
        assert pending_rows(bus, AGENT) == []
        assert bus.client.xpending(bus.stream(AGENT), "workers")["pending"] == 0
    finally:
        delete_namespace(bus)


def poison_fields():
    return {"body": "this is not json"}


def consume_one(bus, workflow, consumer, idle_ms):
    """The decode-failure branch of the consumers (local_cycle._deliver, autonomous): decode, on a decode error
    dead-letter, otherwise `workflow.handle`. Returns the entry id."""
    entry_id, fields = bus.receive(AGENT, consumer, idle_ms=idle_ms)
    try:
        message = bus.decode(fields)
    except ValueError as exc:
        bus.dead_letter(AGENT, entry_id, fields, str(exc))
    else:
        workflow.handle(message)
    return entry_id


@needs_redis
def test_the_dead_letter_is_atomic_a_fault_before_the_script_leaves_no_record_and_the_redelivery_writes_one():
    """Matrix row G2 (real Redis), declared intended change, S10 A5-1a (DESIGN-s10 §17a); the S9 window no longer
    exists. `dead_letter` is one `EVAL` (XADD then XACK). The first call fails BEFORE the script (patched
    `client.eval` raises once for the dead-letter script only). PROVES: 0 records and the entry still pending; the
    redelivery (`receive(idle_ms=0)`) writes exactly 1 record with that `source` and `entry_id`, 0 entries are
    pending, and no workflow effect ever ran for the poison entry."""
    bus = RedisBus(REDIS_URL, "zeus-s9-g2-" + uuid4().hex)
    workflow = Workflow(MemoryStore(), organization())
    dead_stream = bus.namespace + ":dead-letter"
    try:
        entry_id = bus.client.xadd(bus.stream(AGENT), poison_fields())
        real_eval, calls = bus.client.eval, []

        def fault_once(script, *args):
            if script == RedisBus._DEAD_LETTER_SCRIPT:
                calls.append(args)
                if len(calls) == 1:
                    raise RedisConnectionError("fixture: fault before the dead-letter script")
            return real_eval(script, *args)

        with patch.object(bus.client, "eval", side_effect=fault_once):
            with pytest.raises(RedisConnectionError):
                consume_one(bus, workflow, "consumer-a", 60000)
            assert [r["message_id"] for r in pending_rows(bus, AGENT)] == [entry_id]
            assert bus.client.xlen(dead_stream) == 0
            assert consume_one(bus, workflow, "consumer-b", 0) == entry_id

        records = bus.client.xrange(dead_stream)
        assert len(records) == 1
        assert {(f["source"], f["entry_id"]) for _, f in records} == {(bus.stream(AGENT), entry_id)}
        assert pending_rows(bus, AGENT) == []
        with workflow.store.transaction() as tx:
            assert tx.scan("tasks") == [] and tx.scan("outbox") == []
    finally:
        delete_namespace(bus)


class FakeStreamClient:
    """LABELLED in-memory stand-in that emulates the dead-letter script (XADD to KEYS[1] then XACK on KEYS[2]) as
    one step, with a pending set; `fail_before_eval_once` is an injected fault raised before the script runs. It
    is not a Redis observation."""

    def __init__(self):
        self.streams, self.pending, self.fail_before_eval_once = {}, {"e-1"}, False

    def eval(self, script, numkeys, *args):
        assert script == RedisBus._DEAD_LETTER_SCRIPT and numkeys == 2
        if self.fail_before_eval_once:
            self.fail_before_eval_once = False
            raise RedisConnectionError("fixture: fault before the dead-letter script")
        dead, source, src, entry_id, body, reason = args
        self.streams.setdefault(dead, []).append(
            {"source": src, "entry_id": entry_id, "body": body, "reason": reason})
        self.pending.discard(entry_id)
        return 1


def test_g2b_dead_letter_is_atomic_a_fault_before_the_script_leaves_no_record_and_the_redelivery_writes_one():
    """Matrix row G2b (fake client, runs everywhere), declared intended change, S10 A5-1a (DESIGN-s10 §17a); the
    S9 window no longer exists. Over a LABELLED fake that emulates the script: a fault before it leaves 0 records
    and the entry pending; the redelivery writes exactly 1 record with that `source` and `entry_id` and 0 entries
    are pending."""
    bus = RedisBus("redis://localhost:6379", "ns")
    bus.client = FakeStreamClient()
    fields = poison_fields()
    bus.client.fail_before_eval_once = True
    with pytest.raises(RedisConnectionError):
        bus.dead_letter(AGENT, "e-1", fields, "bad body")
    assert bus.client.pending == {"e-1"}
    assert bus.client.streams.get("ns:dead-letter", []) == []
    bus.dead_letter(AGENT, "e-1", fields, "bad body")
    records = bus.client.streams["ns:dead-letter"]
    assert len(records) == 1
    assert {(r["source"], r["entry_id"]) for r in records} == {("ns:agent:" + AGENT, "e-1")}
    assert bus.client.pending == set()
