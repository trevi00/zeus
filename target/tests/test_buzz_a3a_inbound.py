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

    def __call__(self, row, generation):
        if self.fail:
            raise RuntimeError("sink down")
        self.seen.append(row["event"]["id"])
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


def _processed_world():
    """One no-command row (non-owner), one command row (owner, sunk) and one pending row (sink down)."""
    w = World([ev(20, NOW - 10, author=ROLE), ev(21, NOW - 20)])
    w.pass_.run(w.generation)
    with w.store.transaction() as tx:
        w.inbox.insert_pending(tx, {"event_id": "p" * 64, "author": OWNER, "created_at": NOW, "received_at": NOW,
                                    "channel": CHANNEL, "event": ev(22, NOW)})
    return w


def test_10_compaction_keeps_the_identity_and_drops_the_body():
    w = _processed_world()
    with w.store.transaction() as tx:  # a no-command row that still carries a body, as an older writer left it
        row = tx.get("remote_inbox", ev(20, 0)["id"])
        row["event"] = ev(20, NOW - 10)
        tx.put("remote_inbox", row["id"], row)
    w.now += 800 + 86400 + 100
    assert w.pass_.compact(w.generation) == 1
    row = next(r for r in w.rows("remote_inbox") if r["event_id"] == ev(20, 0)["id"])
    assert "event" not in row and row["compacted"] is True
    assert (row["author"], row["created_at"], row["channel"], row["outcome"], row["state"]) == (
        ROLE, NOW - 10, CHANNEL, "ignored_not_owner", "processed") and row["received_at"] == NOW
    assert w.pass_.compact(w.generation) == 0  # idempotent


def test_10b_a_duplicate_of_a_compacted_event_is_still_a_duplicate():
    w = _processed_world()
    w.now += 800 + 86400 + 100
    w.pass_.compact(w.generation)
    with w.store.transaction() as tx:
        assert w.inbox.insert_pending(tx, {"event_id": ev(20, 0)["id"], "author": ROLE, "created_at": 1,
                                           "received_at": 2, "channel": "x"}) == "duplicate"
        assert tx.get("remote_inbox", ev(20, 0)["id"])["compacted"] is True


def test_10c_pending_command_and_young_rows_are_untouched():
    w = _processed_world()
    before = {r["event_id"]: r for r in w.rows("remote_inbox")}
    w.now += 800 + 86400 + 100
    w.pass_.compact(w.generation)
    after = {r["event_id"]: r for r in w.rows("remote_inbox")}
    command, pending = ev(21, 0)["id"], "p" * 64
    assert after[command] == before[command] and "event" in after[command]  # stub_recorded keeps its event
    assert after[pending] == before[pending] and after[pending]["state"] == "pending" and "event" in after[pending]
    w2 = _processed_world()  # received less than lookback + 24 h ago: nothing compacts
    w2.now += 86400
    assert w2.pass_.compact(w2.generation) == 0


def test_10d_compaction_under_a_stale_generation_commits_nothing():
    w = _processed_world()
    w.now += 800 + 86400 + 100
    with w.store.transaction() as tx:
        w.lease.acquire(tx, "bridge-1", w.now, 60)  # gen 2
    before = w.digest()
    with pytest.raises(ContractError, match="bridge_lease_lost"):
        w.pass_.compact(w.generation)
    assert w.digest() == before


@pytest.mark.skip(reason="the labelled disposable-PG fixture is not provided to this worker; the owner runs integration")
def test_pg_inbox_and_lease_idempotency():
    raise AssertionError("runs against the labelled disposable PostgreSQL only")


# -- A3c F2: a re-queried unresolved interval keeps its own bounds, so it retires on schedule ----------------------

def _oracle_lower(intervals, cursor_time, now):
    """§6.2.1/§6.2.4 from first principles: this pass's horizon, lowered only by LIVE (upper not older than the
    admission horizon) earlier intervals' own bounds."""
    own = now - 780
    if cursor_time is not None:
        own = min(own, cursor_time - 780)
    return min([own] + [lo for lo, upper in intervals if upper >= now - 780]), own


def _sustained(passes, *, restart_at=None, crash_at=None, keyset_crash=False):
    """`passes` reconciliations 300 s apart, one event each, the cursor advancing with the receiver clock."""
    w = World()
    intervals, cursor_time, resuming, lowers = [], None, None, []
    for i in range(passes):
        w.now = NOW + i * 300
        newest = ev(i + 1, w.now)
        w.relay.events.append(newest)
        if restart_at == i:
            w.pass_ = w.make()  # a restarted bridge: only the store survives
        if resuming is None:
            lower, own = _oracle_lower(intervals, cursor_time, w.now)
            opened = (own, w.now)
        else:
            lower = resuming["lower"]  # a resumed pass keeps its recorded bounds
        crash = crash_at == i
        if crash:
            real, calls = w.inbox.insert_pending, []

            def crashing(tx, meta, real=real, calls=calls):
                calls.append(meta["event_id"])
                if len(calls) == (2 if keyset_crash else 1):
                    raise RuntimeError("crash mid-pass")
                return real(tx, meta)

            w.inbox.insert_pending = crashing
            if keyset_crash:  # a second, older event so one commits (keyset set) before the crash
                w.relay.events.append(ev(100 + i, w.now - 1))
            with pytest.raises(RuntimeError):
                w.pass_.run(w.generation)
            w.inbox.insert_pending = real
            [running] = [r for r in w.rows("buzz_passes") if r["state"] == "running"]
            assert w.relay.queries[-1]["since"] == lower == running["lower"]
            resuming = running
            if resuming["keyset"] is not None:
                cursor_time = w.rows("buzz_cursors")[0]["created_at"]
            lowers.append(lower)
            continue
        w.pass_.run(w.generation)
        query = w.relay.queries[-1]
        assert query["since"] == lower, (i, query["since"], lower)
        if resuming is not None:
            assert ("until" in query) == (resuming["keyset"] is not None)  # the crash-resume keyset is kept
            intervals.append((resuming["own_lower"], resuming["upper"]))
            if resuming["keyset"] is None:
                cursor_time = newest["created_at"]
            resuming = None  # with a keyset the resumed query (until) cannot see this pass's newer event
        else:
            intervals.append(opened)
            cursor_time = newest["created_at"]
        lowers.append(lower)
    return w, lowers


def test_a3c_f2_1_an_expired_interval_stops_lowering_queries_but_stays_audited_unknown():
    w, lowers = _sustained(14)  # 3900 s: well beyond twice LOOKBACK
    passes = w.rows("buzz_passes")
    assert lowers[0] == NOW - 780 and lowers[-1] > lowers[0] and lowers[-1] == NOW + 10 * 300 - 780  # the live horizon: three passes back
    first = passes[0]
    assert first["state"] == "gap_unknown" and first["coverage"] == "gap_unknown" and first["lower"] == NOW - 780
    assert first["retired_at"] is not None and first["upper"] == NOW  # the original identity is never refreshed
    assert all(p["upper"] == NOW + n * 300 for n, p in enumerate(passes))
    assert all(p["state"] == "gap_unknown" for p in passes)
    assert NOW - 780 not in lowers[4:]  # once the initial and its cursor-bound successor expired, it never reappears
    assert all(NOW + n * 300 - lowers[n] <= 2 * 780 + 300 for n in range(14))  # bounded work per pass


def test_a3c_f2_2_active_unresolved_intervals_still_constrain_the_query():
    w, lowers = _sustained(3)  # nothing is old enough to retire yet
    assert lowers == [NOW - 780] * 3  # the initial interval is live, so it lowers every query
    assert all(p["retired_at"] is None for p in w.rows("buzz_passes"))
    w.now = NOW + 3 * 300
    w.relay.events.append(ev(50, w.now))
    w.pass_.run(w.generation)
    first, second, third, fourth = w.rows("buzz_passes")
    assert first["retired_at"] is not None and second["retired_at"] is None  # 900 s: only the first expired
    assert w.relay.queries[-1]["since"] == min(second["own_lower"], third["own_lower"]) < fourth["own_lower"] + 1
    assert w.relay.queries[-1]["since"] == second["own_lower"] and second["upper"] >= w.now - 780


def test_a3c_f2_3_the_bound_repeats_across_a_restart():
    w, lowers = _sustained(14, restart_at=7)
    assert lowers[-1] > lowers[0] and NOW - 780 not in lowers[4:]


def test_a3c_f2_4_an_interrupted_pass_resumes_with_its_bounds_and_the_bound_still_rises():
    w, lowers = _sustained(14, crash_at=5)
    assert lowers[-1] > lowers[0] and len(w.rows("buzz_passes")) == 13  # the crashed pass was resumed, not duplicated
    assert all(p["state"] == "gap_unknown" for p in w.rows("buzz_passes"))


def test_a3c_f2_5_a_crash_resume_keyset_survives_with_a_restart():
    w, lowers = _sustained(14, restart_at=6, crash_at=5, keyset_crash=True)
    assert lowers[-1] > lowers[0] and len(w.rows("buzz_passes")) == 13
    assert len(w.rows("remote_inbox")) == 14 + 1  # every event, including the interrupted pass's second one
