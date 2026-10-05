"""S11 unit XC-2a (TQ-XCUT-PLAN §1 B1 and B5): bounded dead-letter retention and the local-trust boundary.

B1 (REDIS-STREAMS-RELIABILITY safe retention): `zeus dlq trim` deletes a dead-letter group's stream entries only when
its replay completed longer ago than the retention; an unreplayed, in-doubt, legacy-failed, body-conflict or young
group is never touched. The expected sets come from that owner-fixed rule, not from the implementation.
MemoryStore, a LABELLED fake bus (the dead-letter side of RedisBus: `dead_letters`, `publish`, `trim_dead_letters`,
the real decode) and a mutable clock; one real-Redis variant is gated on `HARNESS_REDIS_URL` (target-integration).

B5: the bus and the CLI trust the local OS user, like the desk (`entry/http/desk.py`); authority for a review or report
comes from durable rows, never from the sender a message asserts. A forged `review.result` is driven through the public
`MessageHandler.handle` and refused with no state change.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from test_s10_a5_1b_dlq import (
    NAMESPACE,
    REDIS_URL,
    SECRET,
    SOURCE,
    FakeBus,
    body,
    message,
    needs_redis,
    record,
    refusal,
    stored,
)

from codex_harness.composition import cli_dlq
from codex_harness.coordination.application.dead_letters import BUCKET, FAILED, DeadLetters, replay_key
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.entry import cli
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
from codex_harness.kernel.message import envelope
from codex_harness.kernel.policy import POLICY
from codex_harness.research.application.audit_gate import require_adoption
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.redis_bus import RedisBus
from codex_harness.storage.ports import MessageDeliveryError

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


class MovingClock:
    def __init__(self, at):
        self.at = at

    def now(self):
        return self.at


class TrimBus(FakeBus):
    """LABELLED FAKE: FakeBus plus the by-id delete of the dead-letter stream (XDEL semantics: absent ids count 0)."""

    def __init__(self, records, fail=None):
        super().__init__(records, fail)
        self.trim_calls = []

    def trim_dead_letters(self, ids):
        self.trim_calls.append(list(ids))
        before = len(self.records)
        self.records = [r for r in self.records if r[0] not in ids]
        return before - len(self.records)


def scene():
    """Eight groups: each entry id `N-0` carries one dead-letter record `dN`. Returns (use, store, bus, clock)."""
    clock = MovingClock(NOW - 8 * DAY)
    recs = [record(f"d{n}", f"{n}-0", body(message())) for n in range(1, 8)]
    recs.append(record("d8", "8-0", body(message("dev", "one"))))
    recs.append(record("d8b", "8-0", body(message("dev", "two"))))
    store, bus = MemoryStore(), TrimBus(recs)
    use = DeadLetters(store, bus, clock=clock)
    # 1-0 completed 8 d ago (eligible); 2-0 completed 1 d ago (young); 3-0 ambiguous publish -> intent, 8 d old;
    # 4-0 a predecessor `failed` record, 8 d old; 5-0 never replayed; 6-0 completed 8 d ago but its record then
    # gains a second, different body (conflict); 7-0 completed exactly at the retention boundary - 1 s (young).
    use.replay(SOURCE, "1-0", reason="fixed", actor="operator-lead")
    clock.at = NOW - 1 * DAY
    use.replay(SOURCE, "2-0", reason="fixed", actor="operator-lead")
    clock.at = NOW - 8 * DAY
    bus.fail = MessageDeliveryError("TimeoutError")
    with pytest.raises(ContractError):
        use.replay(SOURCE, "3-0", reason="fixed", actor="operator-lead")
    bus.fail = None
    with store.transaction() as tx:
        tx.put(BUCKET, replay_key(SOURCE, "4-0"), {"id": replay_key(SOURCE, "4-0"), "status": FAILED, "source": SOURCE,
                                                   "entry_id": "4-0", "attempts": 1,
                                                   "updated_at": (NOW - 8 * DAY).isoformat()})
    use.replay(SOURCE, "6-0", reason="fixed", actor="operator-lead")
    bus.records.append(record("d6b", "6-0", body(message("dev", "other"))))
    clock.at = NOW - timedelta(seconds=POLICY.observation_retention_seconds) + timedelta(seconds=1)
    use.replay(SOURCE, "7-0", reason="fixed", actor="operator-lead")
    clock.at = NOW
    return use, store, bus, clock


def test_trim_removes_only_completed_replays_older_than_the_retention_and_prints_ids_only():
    use, store, bus, _ = scene()
    out = use.trim()
    assert out == {"trimmed": 1, "groups": [[SOURCE, "1-0"]]}
    assert SECRET not in json.dumps(out) and "body" not in json.dumps(out)
    assert [rid for rid, _ in bus.records] == ["d2", "d3", "d4", "d5", "d6", "d7", "d8", "d8b", "d6b"]
    record_1 = stored(store, entry_id="1-0")
    assert record_1["trimmed_entries"] == ["d1"] and record_1["trimmed_at"] == NOW.isoformat()
    assert record_1["status"] == "completed"
    for kept in ("2-0", "3-0", "4-0", "5-0", "6-0", "7-0", "8-0"):
        assert "trimmed_at" not in (stored(store, entry_id=kept) or {}), kept


def test_a_second_trim_trims_nothing_more_and_a_listed_group_is_untouched():
    use, store, bus, _ = scene()
    use.trim()
    after_first = [row for row in bus.records]
    with store.transaction() as tx:
        snapshot = tx.records()
    assert use.trim() == {"trimmed": 0, "groups": []}
    assert bus.records == after_first
    with store.transaction() as tx:
        assert tx.records() == snapshot
    assert use.list()["groups"] == 7


def test_a_shorter_retention_reaches_the_young_completed_group_but_never_an_in_doubt_one():
    use, store, bus, _ = scene()
    out = use.trim(retention_seconds=0)
    assert [g[1] for g in out["groups"]] == ["1-0", "2-0", "7-0"] and out["trimmed"] == 3
    left = {fields["entry_id"] for _, fields in bus.records}
    assert left == {"3-0", "4-0", "5-0", "6-0", "8-0"}  # intent, legacy failed, unreplayed, conflict, unreplayed conflict


def test_the_default_retention_is_the_observation_retention_and_a_bad_one_is_refused():
    use, _, bus, _ = scene()
    assert POLICY.observation_retention_seconds == 7 * 86400
    for bad in (-1, True, "7", 1.5):
        assert refusal(lambda bad=bad: use.trim(retention_seconds=bad)) == "trim_retention_invalid"
    assert bus.trim_calls == []


def test_a_failed_delete_is_refused_and_the_next_run_trims_and_records_again():
    use, store, bus, _ = scene()
    real = bus.trim_dead_letters

    def down(ids):
        raise MessageDeliveryError("ConnectionError")

    bus.trim_dead_letters = down
    assert refusal(use.trim) == "dead_letter_trim_failed"
    assert [rid for rid, _ in bus.records][0] == "d1"  # nothing was deleted
    bus.trim_dead_letters = real
    assert use.trim() == {"trimmed": 1, "groups": [[SOURCE, "1-0"]]}
    assert use.trim()["trimmed"] == 0


def test_dlq_trim_is_dispatched_by_main_and_prints_ids_never_a_body(monkeypatch, capsys):
    use, _, bus, _ = scene()
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

    code, out, _ = main("dlq", "trim")
    assert code == 0 and json.loads(out) == {"trimmed": 1, "groups": [[SOURCE, "1-0"]]} and SECRET not in out
    code, out, _ = main("dlq", "trim")
    assert code == 0 and json.loads(out)["trimmed"] == 0
    code, out, _ = main("dlq", "trim", "--retention-seconds", "0")
    assert code == 0 and [g[1] for g in json.loads(out)["groups"]] == ["2-0", "7-0"]
    assert main("dlq", "trim", "--retention-seconds", "soon")[0] == 2


def test_redis_bus_deletes_only_the_named_dead_letter_records_and_wraps_a_redis_error():
    from redis.exceptions import ConnectionError as RedisConnectionError

    class Client:
        def __init__(self):
            self.calls = []

        def xdel(self, name, *ids):
            self.calls.append((name, ids))
            if ids == ("boom",):
                raise RedisConnectionError("down")
            return len(ids)

    bus = RedisBus.__new__(RedisBus)
    bus.namespace, bus.client = NAMESPACE, Client()
    assert bus.trim_dead_letters(["1-0", "2-0"]) == 2 and bus.trim_dead_letters([]) == 0
    assert bus.client.calls == [(f"{NAMESPACE}:dead-letter", ("1-0", "2-0"))]
    for bad in ("1-0", [""], [1], None):
        with pytest.raises(ValueError):
            bus.trim_dead_letters(bad)
    with pytest.raises(MessageDeliveryError) as caught:
        bus.trim_dead_letters(["boom"])
    assert str(caught.value) == "ConnectionError"


@needs_redis
def test_end_to_end_trim_against_a_real_redis_keeps_the_unreplayed_entry():
    bus = RedisBus(REDIS_URL, f"xc2a-{uuid4().hex[:12]}")
    clock = MovingClock(NOW - 8 * DAY)
    try:
        for text in ("done", "kept"):
            bus.publish(message("dev", text))
        for _ in range(2):
            entry_id, fields = bus.receive("dev", "c1")
            bus.dead_letter("dev", entry_id, fields, "Unknown agent")
        use = DeadLetters(MemoryStore(), bus, clock=clock)
        first, second = [row["entry_id"] for row in use.list()["dead_letters"]]
        use.replay(bus.stream("dev"), first, reason="registered", actor="operator-lead")
        clock.at = NOW
        assert use.trim() == {"trimmed": 1, "groups": [[bus.stream("dev"), first]]}
        left = bus.client.xrange(f"{bus.namespace}:dead-letter", "-", "+")
        assert [f["entry_id"] for _, f in left] == [second]
        assert use.trim()["trimmed"] == 0
    finally:
        for key in list(bus.client.scan_iter(match=bus.namespace + ":*")):
            bus.client.delete(key)


# ---- B5: the local-trust boundary -------------------------------------------------------------------------------

def handler():
    org = packaged_organization()
    workflow = Workflow(MemoryStore(), org, ticket_binding=tickets.ticket_binding,
                        TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption,
                        park_terminal=lambda tx, msg: None, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
    return MessageHandler(workflow), workflow.store


def review_result(decision_id, result, sender="lead:improvement"):
    return envelope("review.result", sender, "conductor", "review", {"decision_id": decision_id, "result": result},
                    "review-loop")


def state(store):
    with store.transaction() as tx:
        return tx.records()


def test_a_forged_review_result_with_no_durable_row_is_refused_with_no_state_change():
    handle, store = handler()
    result = {"candidate": {"revision": "forged"}}
    forged = review_result("never-issued", result)  # a valid envelope from an authorised sender, but no durable row
    before = state(store)
    assert refusal(lambda: handle.handle(forged)) == "Unproven decision result"
    assert state(store) == before and before == []


def test_a_review_result_is_refused_unless_the_durable_row_binds_this_sender_and_this_result():
    handle, store = handler()
    result = {"candidate": {"revision": "abc"}}
    rows = {"other-actor": {"actor": "conductor", "status": "succeeded", "result": result},
            "other-result": {"actor": "lead:improvement", "status": "succeeded", "result": {"candidate": {"revision": "x"}}},
            "not-succeeded": {"actor": "lead:improvement", "status": "pending", "result": result}}
    with store.transaction() as tx:
        for key, row in rows.items():
            tx.put("decisions_pending", key, {"id": key, **row})
    before = state(store)
    for key in rows:
        assert refusal(lambda key=key: handle.handle(review_result(key, result))) == "Unproven decision result", key
    assert state(store) == before


def test_the_same_review_result_is_accepted_once_a_durable_row_binds_the_sender_and_result():
    """Control: the refusals above are for the missing binding, not for the envelope."""
    handle, store = handler()
    result = {"candidate": {"revision": "abc"}}
    with store.transaction() as tx:
        tx.put("decisions_pending", "bound", {"id": "bound", "actor": "lead:improvement", "status": "succeeded",
                                              "result": result})
    handle.handle(review_result("bound", result))
    assert [r["bucket"] for r in state(store)].count("workflow_inbox") == 1
