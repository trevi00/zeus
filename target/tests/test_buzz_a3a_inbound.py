"""Buzz A3a: the inbound pass (remote inbox, bridge lease, cursors, pass records) over MemoryStore and fakes.

Design §6.2 steps 1-6 and §6.5. No network, no relay: the relay is a scripted fake with the `query_all` signature.
"""

import pytest

from codex_harness.coordination.application.bridge_lease import BridgeLease
from codex_harness.coordination.application.remote_inbox import RemoteInbox
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical
from codex_harness.observation.application.buzz_inbound import InboundPass
from codex_harness.observation.ports import BridgeLeasePort, RemoteInboxPort
from codex_harness.storage.adapters.memory_store import MemoryStore

NOW = 1_700_000_000
OWNER, ROLE = "a" * 64, "b" * 64
CHANNEL = "c1"


def ev(n, created_at, author=OWNER):
    return {"id": f"{n:064x}", "pubkey": author, "created_at": created_at, "kind": 9, "content": f"m{n}",
            "tags": [["h", CHANNEL]]}


class FakeRelay:
    """`query_all` over a fixed event list: honours since/until/before_id; `ended` and `fail_after` are scripted."""

    def __init__(self, events, ended="eose"):
        self.events, self.ended, self.queries, self.fail_after = list(events), ended, [], None

    def query_all(self, filter, *, until=None):  # noqa: A002 - port signature
        self.queries.append(dict(filter))
        found = [e for e in self.events if e["created_at"] >= filter["since"]]
        if "until" in filter:
            found = [e for e in found if e["created_at"] < filter["until"]
                     or (e["created_at"] == filter["until"] and e["id"] > filter["before_id"])]
        found.sort(key=lambda e: (-e["created_at"], e["id"]))
        return {"events": found, "ended": self.ended, "pages": 1, "unverified": 0}

    def publish(self, event): raise AssertionError("inbound never publishes")
    def query(self, filters): raise AssertionError("inbound pages through query_all")
    def subscribe(self, sub_id, filters): raise AssertionError("not used")
    def close(self): pass


class Sink:
    def __init__(self):
        self.seen, self.fail = [], False

    def __call__(self, event):
        if self.fail:
            raise RuntimeError("sink down")
        self.seen.append(event["id"])
        return "stub_recorded"


class World:
    def __init__(self, events=(), ended="eose", cursor_ahead=None):
        self.now = NOW
        self.store, self.relay, self.sink = MemoryStore(), FakeRelay(events, ended), Sink()
        self.inbox, self.lease = RemoteInbox(), BridgeLease()
        with self.store.transaction() as tx:
            self.generation = self.lease.acquire(tx, "bridge-1", self.now, 60)
        self.pass_ = self.make()

    def make(self):
        return InboundPass(self.store, self.relay, self.inbox, self.lease, self.sink, [OWNER], [CHANNEL],
                           lambda: self.now)

    def rows(self, bucket):
        with self.store.transaction() as tx:
            return tx.scan(bucket)

    def digest(self):
        return canonical(sorted(self.store.data.items(), key=str))


def test_the_coordination_classes_satisfy_the_observation_ports():
    inbox: RemoteInboxPort = RemoteInbox()
    lease: BridgeLeasePort = BridgeLease()
    assert inbox and lease


def test_1_duplicate_delivery_is_one_inbox_row_and_one_sink_call():
    e = ev(1, NOW - 10)
    w = World([e, dict(e)])  # twice in one page's worth of events
    w.pass_.run(w.generation)
    w.now += 300
    w.pass_.run(w.generation)  # and again next pass
    assert [r["event_id"] for r in w.rows("remote_inbox")] == [e["id"]]
    assert w.sink.seen == [e["id"]]
    with w.store.transaction() as tx:
        assert w.inbox.insert_pending(tx, {"event_id": e["id"], "author": ROLE, "created_at": 1, "received_at": 2,
                                           "channel": "x"}) == "duplicate"
        assert tx.get("remote_inbox", e["id"])["author"] == OWNER  # a duplicate never changes the row


def test_2_a_non_owner_is_ignored_and_never_reaches_the_sink():
    e = ev(2, NOW - 10, author=ROLE)
    w = World([e])
    w.pass_.run(w.generation)
    [row] = w.rows("remote_inbox")
    assert (row["state"], row["outcome"]) == ("processed", "ignored_not_owner") and "event" not in row
    assert w.sink.seen == []


def test_3_a_raising_sink_leaves_the_row_pending_and_the_next_run_processes_it_once():
    e = ev(3, NOW - 10)
    w = World([e])
    w.sink.fail = True
    first = w.pass_.run(w.generation)
    assert first[CHANNEL]["sink_failed"] == 1
    assert [r["state"] for r in w.rows("remote_inbox")] == ["pending"]
    w.sink.fail = False
    w.now += 300
    w.pass_.run(w.generation)
    w.now += 300
    w.pass_.run(w.generation)
    assert w.sink.seen == [e["id"]]
    assert [(r["state"], r["outcome"]) for r in w.rows("remote_inbox")] == [("processed", "stub_recorded")]


def test_3b_a_pending_row_resumes_without_the_relay_resending_it():
    e = ev(4, NOW - 10)
    w = World([e])
    w.sink.fail = True
    w.pass_.run(w.generation)
    w.sink.fail = False
    w.relay.events = []
    w.now += 5000
    w.pass_.run(w.generation)
    assert w.sink.seen == [e["id"]]


def test_4_a_stale_generation_commits_nothing():
    w = World([ev(5, NOW - 10)])
    with w.store.transaction() as tx:
        w.lease.acquire(tx, "bridge-1", w.now + 100, 60)  # the same owner restarting fences its predecessor: gen 2
    before = w.digest()
    with pytest.raises(ContractError) as err:
        w.pass_.run(w.generation)
    assert err.value.args == ("bridge_lease_lost",)
    assert w.digest() == before and w.relay.queries == []
    with pytest.raises(ContractError, match="bridge_lease_lost"), w.store.transaction() as tx:
        w.inbox.insert_pending(tx, {"event_id": "z", "author": OWNER, "created_at": 1, "received_at": 1,
                                    "channel": CHANNEL})
        w.lease.require_current(tx, w.generation)
    assert w.digest() == before


def test_5_a_second_instance_waits_for_expiry_and_the_old_generation_is_refused():
    w = World([ev(6, NOW - 10)])
    with w.store.transaction() as tx:
        assert w.lease.acquire(tx, "bridge-2", NOW + 30, 60) is None  # first still live (expires NOW + 60)
        assert w.lease.renew(tx, "bridge-1", w.generation, NOW + 30, 60) == NOW + 90
    with w.store.transaction() as tx:
        assert w.lease.acquire(tx, "bridge-2", NOW + 90, 60) == w.generation + 1  # expired
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        w.pass_.run(w.generation)
    with pytest.raises(ContractError, match="bridge_lease_lost"), w.store.transaction() as tx:
        w.lease.renew(tx, "bridge-1", w.generation, NOW + 100, 60)
    with w.store.transaction() as tx:
        w.lease.require_current(tx, w.generation + 1)


def test_the_lease_fails_closed_without_a_row():
    with pytest.raises(ContractError, match="bridge_lease_lost"), MemoryStore().transaction() as tx:
        BridgeLease().require_current(tx, 1)


def test_6_the_lower_bound_follows_the_receiver_clock_when_the_cursor_is_ahead():
    w = World()
    with w.store.transaction() as tx:
        tx.put("buzz_cursors", CHANNEL, {"id": CHANNEL, "channel": CHANNEL, "created_at": NOW + 500, "event_id": "f"})
    e = ev(7, NOW - 500)
    w.relay.events = [e]
    w.pass_.run(w.generation)
    assert w.relay.queries[0]["since"] == NOW - 780 and w.sink.seen == [e["id"]]


@pytest.mark.parametrize("ended", ["closed:error", "timeout", "stalled", "eose"])
def test_7_nothing_but_the_relays_word_ends_a_pass_so_the_interval_stays_gap_unknown(ended):
    w = World([ev(8, NOW - 10)], ended=ended)
    w.pass_.run(w.generation)
    [record] = w.rows("buzz_passes")
    assert (record["state"], record["coverage"], record["ended"]) == ("gap_unknown", "gap_unknown", ended)
    first_lower = record["lower"]
    w.now += 300  # next pass: the checkpoint is kept and re-queried, the bound does not advance past it
    w.pass_.run(w.generation)
    assert w.relay.queries[1]["since"] <= first_lower
    assert all(r["retired_at"] is None for r in w.rows("buzz_passes"))
    w.now += 900  # older than now - lookback: retired from the operational view, still recorded
    w.pass_.run(w.generation)
    rows = w.rows("buzz_passes")
    assert len(rows) == 3 and [r["retired_at"] is not None for r in rows[:2]] == [True, True]
    assert w.relay.queries[2]["since"] == NOW - 10 - 780  # now only the cursor bound (no unretired checkpoint)


def test_8_a_crash_mid_pass_resumes_from_the_persisted_keyset():
    events = [ev(n, NOW - 10 * n) for n in range(1, 5)]
    w = World(events)
    real = w.inbox.insert_pending
    calls = []

    def crashing(tx, meta):
        calls.append(meta["event_id"])
        if len(calls) == 3:
            raise RuntimeError("crash after two committed events")
        return real(tx, meta)

    w.inbox.insert_pending = crashing
    with pytest.raises(RuntimeError):
        w.pass_.run(w.generation)
    [record] = w.rows("buzz_passes")
    assert record["state"] == "running" and record["keyset"] == [events[1]["created_at"], events[1]["id"]]
    assert len(w.rows("remote_inbox")) == 2
    w.inbox.insert_pending = real
    w.now += 1
    w.pass_.run(w.generation)
    resume = w.relay.queries[1]
    assert (resume["until"], resume["before_id"]) == (events[1]["created_at"], events[1]["id"])
    assert resume["since"] == record["lower"] and len(w.rows("buzz_passes")) == 1
    assert len(w.rows("remote_inbox")) == 4 and sorted(w.sink.seen) == sorted(e["id"] for e in events)
    assert w.rows("buzz_passes")[0]["state"] == "gap_unknown"


def test_9_the_cursor_never_moves_backwards():
    w = World([ev(9, NOW - 10), ev(10, NOW - 20)])
    w.pass_.run(w.generation)
    [cursor] = w.rows("buzz_cursors")
    assert (cursor["created_at"], cursor["event_id"]) == (NOW - 10, ev(9, 0)["id"])
    w.relay.events = [ev(11, NOW - 400)]  # only an older event arrives next
    w.now += 300
    w.pass_.run(w.generation)
    assert [(c["created_at"], c["event_id"]) for c in w.rows("buzz_cursors")] == [(NOW - 10, ev(9, 0)["id"])]
    w.relay.events = [ev(9, NOW - 10, author=OWNER), {**ev(12, NOW - 10), "id": f"{99:064x}"}]  # tie: larger id wins
    w.pass_.run(w.generation)
    assert w.rows("buzz_cursors")[0]["event_id"] == f"{99:064x}"


def test_10_prune_is_not_provided_because_the_storage_port_cannot_delete():
    # Escalated to the owner: Transaction has get/put/scan/records/entries only (storage/ports.py:33), so F6 pruning
    # cannot delete rows. Until then a pending row, like every row, is never removed.
    assert not hasattr(RemoteInbox(), "prune") and not hasattr(InboundPass, "prune")


@pytest.mark.skip(reason="the labelled disposable-PG fixture is not provided to this worker; the owner runs integration")
def test_pg_inbox_and_lease_idempotency():
    raise AssertionError("runs against the labelled disposable PostgreSQL only")
