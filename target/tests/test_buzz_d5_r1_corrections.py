"""Buzz D5: the batch-d round-1 corrections F1 (a real stop bound) and F2 (a restricted AUTH answer is final).

The REAL `BuzzRelayClient`, `InboundPass`, `BuzzOutbox` and `BridgeRuntime`, composed over MemoryStore with an in-memory
socket and a fake clock (`recv` advances it): no wall-clock sleep, signal, network or Docker.
Contracts: Buzz DESIGN-D section 2 (stop, relay-loss/auth policy), section 5 (stop timeout), section 6 rows 1 and 7;
DESIGN section 6.2 step 4 (an end other than EOSE is an observation, never proof).
"""
import base64
import hashlib
import json
import re
import socket
import threading
import time

import pytest
from test_buzz_a3b_outbox import World
from test_buzz_b3_remote_control import NOW
from test_buzz_d1_bridge_process import Env, document, runtime
from test_buzz_d4_templates import CONFIG, UNIT, expect_violation, lint, plant

from codex_harness.composition.buzz_bridge import BridgeConfig
from codex_harness.coordination.application.remote_inbox import RemoteInbox
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters.buzz_relay import BuzzRelayClient, reconnect_delay
from codex_harness.observation.application.buzz_inbound import InboundPass

RECV, OP = 10, 20


class Signer:
    def sign(self, role, event):
        return dict(event, id="a" * 64, pubkey="b" * 64, sig="c" * 128)


class Verify:
    def verify(self, event):
        return True


def stranger(i=0):
    return {"id": f"{900 + i:064x}", "pubkey": "11" * 32, "created_at": NOW - 5, "kind": 9, "tags": [["h", "zz"]],
            "content": "", "sig": "22" * 64}


class Socket:
    """In-memory websocket. `on_send(frame)` returns the frames the relay answers; `recv` costs fake time: a delivered
    frame `frame_cost`, a silent wait the `timeout` it was given (then `TimeoutError`, as websockets raises it)."""

    def __init__(self, env, on_send=None, *, frame_cost=0.0, filler=None):
        self.env, self.on_send, self.frame_cost, self.filler = env, on_send or (lambda frame: []), frame_cost, filler
        self.queue, self.sent, self.on_recv = [], [], None

    def send(self, text):
        frame = json.loads(text)
        self.sent.append(frame)
        self.queue.extend(self.on_send(frame))

    def recv(self, timeout):
        if self.on_recv:
            self.on_recv()
        frame = self.queue[0] if self.queue else self.filler() if self.filler else None
        if frame is None or self.frame_cost > timeout:  # nothing arrives within the wait
            self.env.t += timeout
            raise TimeoutError
        if self.queue:
            self.queue.pop(0)
        self.env.t += self.frame_cost
        return json.dumps(frame)

    def close(self):
        pass

    def kinds(self, kind):
        return [frame for frame in self.sent if frame[0] == kind]


def client(env, sockets, **kwargs):
    """The real adapter over `sockets` (one, or a list handed out per connection)."""
    pool = list(sockets) if isinstance(sockets, list) else None
    options = {"clock": env.clock, "recv_timeout": RECV, "max_size": 1 << 20, "op_deadline": OP}
    options.update(kwargs)
    return BuzzRelayClient("ws://fixture.invalid", auth_signer=Signer(), auth_role="conductor", verifier=Verify(),
                           connect=lambda *a, **k: pool.pop(0) if pool is not None else sockets, **options)


def compose(env, relay, channels, *, store=None, owner="owner-1", **config):
    """The real client + the real `InboundPass` under the real runtime (planning and delivery are recording fakes)."""
    config = {"max_seconds": 100, "recv_timeout": RECV, "op_deadline_seconds": OP, "channels": list(channels),
              "commander_channel": channels[0], "team_channels": {"core": channels[-1]}, **config}
    rt, calls = runtime(env, store, owner, **config)
    rt.relay = relay
    rt.inbound = InboundPass(rt.store, relay, RemoteInbox(), rt.lease, lambda *a: "done", [], channels, env.clock)
    return rt, calls


def inbox_ids(store):
    with store.transaction() as tx:
        return sorted(row["id"] for row in tx.scan("remote_inbox"))


def passes(store, channel):
    with store.transaction() as tx:
        return sorted((row for row in tx.scan("buzz_passes") if row["channel"] == channel), key=lambda row: row["id"])


def channel_event(channel, index):
    return {"id": f"{(ord(channel[0]) << 8) + index:064x}", "pubkey": "11" * 32, "created_at": NOW - 100 - index,
            "kind": 9, "tags": [["h", channel]], "content": "", "sig": "22" * 64}


def relay_of(events):
    """A relay holding `events`: a REQ is answered by the relay's composite keyset (created_at desc, id asc)."""
    def on_send(frame):
        if frame[0] != "REQ":
            return []
        flt = frame[2]
        rows = sorted((e for e in events if e["tags"] == [["h", flt["#h"][0]]]), key=lambda e: (-e["created_at"], e["id"]))
        if "until" in flt:
            rows = [e for e in rows if e["created_at"] < flt["until"]
                    or (e["created_at"] == flt["until"] and e["id"] > flt["before_id"])]
        return [["EVENT", frame[1], e] for e in rows[:flt["limit"]]] + [["EOSE", frame[1]]]
    return on_send


# ---- F1: a cooperative stop reaches the composed passes ------------------------------------------------------------
def test_f1a_a_stop_in_the_first_of_four_timeout_channels_starts_no_further_query_and_restart_resumes():
    env, channels = Env(), ["a", "b", "c", "d"]
    flag = []
    sock = Socket(env)
    sock.on_recv = lambda: flag.append(True)  # SIGTERM arrives while the first channel waits
    rt, calls = compose(env, client(env, sock), channels)
    started = env.t
    assert rt.run(lambda: bool(flag)) == 0
    assert len(sock.kinds("REQ")) == 1 and calls == []  # example 1: exactly one REQ, no plan, no delivery
    assert env.t - started <= OP  # within the declared bound: op_deadline_seconds (+ a store transaction)
    assert len(passes(rt.store, "a")) == 1 and passes(rt.store, "b") == []
    assert passes(rt.store, "a")[0]["ended"] == "timeout" and passes(rt.store, "a")[0]["coverage"] == "gap_unknown"
    # restart: the unfinished channels run, once each, and every event enters the inbox once
    events = [channel_event(channel, 0) for channel in channels]
    restarted = Socket(env, relay_of(events))
    rt2, _ = compose(env, client(env, restarted), channels, store=rt.store, max_seconds=0)
    assert rt2.run(lambda: False) == 0
    assert [frame[2]["#h"][0] for frame in restarted.kinds("REQ")] == channels
    assert inbox_ids(rt.store) == sorted(event["id"] for event in events)


def test_f1b_a_stop_during_paginated_inbound_reads_starts_no_further_page_and_restart_resumes_the_keyset():
    env, channels = Env(), ["a", "b"]
    events = [channel_event("a", i) for i in range(5)] + [channel_event("b", 0)]
    flag = []
    sock = Socket(env, relay_of(events), frame_cost=1)
    sock.on_recv = lambda: flag.append(True)  # SIGTERM arrives during the first page
    rt, calls = compose(env, client(env, sock, page=2), channels)
    started = env.t
    assert rt.run(lambda: bool(flag)) == 0
    assert len(sock.kinds("REQ")) == 1 and calls == [] and env.t - started <= OP  # page 2 and channel b never start
    assert inbox_ids(rt.store) == []  # the stop was already set: the page read is not committed, nothing is half done
    assert passes(rt.store, "a")[0]["state"] == "running" and passes(rt.store, "b") == []
    restarted = Socket(env, relay_of(events))
    rt2, _ = compose(env, client(env, restarted, page=2), channels, store=rt.store, max_seconds=0)
    assert rt2.run(lambda: False) == 0
    flts = [frame[2] for frame in restarted.kinds("REQ")]
    assert [f["#h"][0] for f in flts] == ["a", "a", "a", "b"]  # a's three pages (2 + 2 + 1), then b
    assert inbox_ids(rt.store) == sorted(event["id"] for event in events)  # each exactly once, nothing lost
    assert all(row["state"] != "running" for row in passes(rt.store, "a"))


def outbox_runtime(env, w, relay, *, owner="bridge-1", **config):
    config = {"max_seconds": 0, "recv_timeout": RECV, "op_deadline_seconds": OP, **config}
    rt, calls = runtime(env, w.store, owner, **config)
    rt.outbox, rt.relay = w.outbox, relay
    return rt, calls


def test_f1c_a_stop_during_a_multi_row_outbox_delivery_sends_no_further_row_and_restart_resumes_once(tmp_path):
    env, w = Env(), World(tmp_path)
    for index in range(3):
        w.enqueue(f"s{index}", 1)
    flag = []
    publish = w.relay.publish

    def publishing(event):
        flag.append(True)  # SIGTERM arrives during the first row's publish, which takes as long as a request may
        env.t += OP
        return publish(event)

    w.relay.publish = publishing
    rt, calls = outbox_runtime(env, w, w.relay)
    started = env.t
    assert rt.run(lambda: bool(flag)) == 0
    assert len(w.relay.published) == 1 and "recover" not in calls and "compact" not in calls
    assert env.t - started <= OP  # the in-flight row used the whole allowance; no other row added to it
    assert sorted(row["status"] for row in w.rows()) == ["acknowledged", "pending", "pending"]
    w.relay.publish = publish
    rt2, _ = outbox_runtime(env, w, w.relay)
    assert rt2.run(lambda: False) == 0
    ids = [event["id"] for event in w.relay.published]
    assert len(ids) == 3 and len(set(ids)) == 3  # the unfinished rows went out once; the sent one was not resent
    assert {row["status"] for row in w.rows()} == {"acknowledged"}


def test_f1c_recover_deferred_checks_stop_before_each_row_and_keeps_the_watermark(tmp_path):
    w = World(tmp_path, outbox_max=1)
    w.enqueue("s0", 1)
    w.enqueue("s1", 1)  # deferred: capacity
    w.outbox.deliver(w.generation)  # s0 goes out and is acknowledged: capacity frees
    seen = []
    items = [{"subject": f"r{i}", "version": 1, "unsigned": w.unsigned(f"r{i}")} for i in range(3)]

    def regenerate(cls, after):
        seen.append(cls)
        return items

    assert w.outbox.recover_deferred(w.generation, regenerate, stop=lambda: True) == {"state": 0}
    assert w.rows("buzz_outbox_watermarks")[0]["deferred"] is True  # nothing was dropped: the work is still deferred
    assert w.outbox.recover_deferred(w.generation, regenerate)["state"] >= 1


def test_f1c_a_stop_during_a_state_rows_reconciliation_query_does_not_replan(tmp_path):
    w = World(tmp_path)
    w.enqueue("s0", 1)
    w.now += 700  # past the drift window: the row is reconciled (query, then re-plan), not resent
    flag = []
    query = w.relay.query

    def querying(filters):
        flag.append(True)
        return query(filters)

    w.relay.query = querying
    w.plan = {"version": 2, "unsigned": w.unsigned("s0@2")}
    w.outbox.deliver(w.generation, stop=lambda: bool(flag))
    assert w.replans == [] and w.row("s0", 1)["status"] == "pending"  # the second relay call never started
    w.relay.query = query
    counts = w.outbox.deliver(w.generation)  # restart: reconciled once, re-planned once
    assert w.replans == ["s0"] and counts["replanned"] == 1


def test_f1b_a_stop_between_event_commits_leaves_the_pass_running_and_resumes_the_rest():
    env, events = Env(), [channel_event("a", i) for i in range(3)]
    rt, _ = compose(env, client(env, Socket(env)), ["a"], max_seconds=0)  # only its store and lease are used
    sock = Socket(env, relay_of(events))
    inbound = InboundPass(rt.store, client(env, sock), RemoteInbox(), rt.lease, lambda *a: "done", [], ["a"], env.clock)
    with rt.store.transaction() as tx:
        generation = rt.lease.acquire(tx, "owner-1", env.t, 30)
    report = inbound.run(generation, stop=lambda: len(inbox_ids(rt.store)) >= 1)
    assert report["a"]["ended"] == "stopped" and len(inbox_ids(rt.store)) == 1
    assert passes(rt.store, "a")[0]["state"] == "running"
    resumed = Socket(env, relay_of(events))
    InboundPass(rt.store, client(env, resumed), RemoteInbox(), rt.lease, lambda *a: "done", [], ["a"],
                env.clock).run(generation)
    assert inbox_ids(rt.store) == sorted(event["id"] for event in events)
    assert resumed.kinds("REQ")[0][2]["until"] == events[0]["created_at"]  # from the committed keyset, not from scratch


def test_f1_planning_and_regeneration_start_no_head_query_after_a_stop(tmp_path):
    from test_buzz_b4_projection import P
    p = P(tmp_path)
    with p.w.store.transaction() as tx:  # three subjects recorded unverified_foreign_revision
        for name in ("t1", "t2", "t3"):
            tx.put("buzz_heads", f"task:{name}", {"subject": f"task:{name}", "condition": "unverified_foreign_revision"})
    flag = []
    query = p.relay.query

    def querying(filters):
        flag.append(True)  # the stop arrives during the first head query
        return query(filters)

    p.relay.query = querying
    p.proj.plan(p.gen, stop=lambda: bool(flag))
    assert len(p.relay.d_queries) == 1  # exactly one relay query, not three
    flag.clear()
    p.relay.d_queries.clear()
    assert p.proj.regenerate("state", None, stop=lambda: bool(flag)) is not None and len(p.relay.d_queries) == 1
    flag.clear()
    p.relay.d_queries.clear()
    p.proj.plan(p.gen)  # no stop: every unverified subject is probed, as today
    assert len(p.relay.d_queries) == 3


def test_f1_the_runtime_hands_its_stop_to_planning_and_recovery():
    env, seen = Env(), []
    rt, calls = runtime(env, max_seconds=0, recover_every=1)
    rt.projection.plan = lambda generation, *, stop=None: seen.append(("plan", stop)) or {}
    rt.projection.regenerate = lambda cls, after, *, stop=None: seen.append(("regenerate", stop)) or []
    rt.outbox.recover_deferred = lambda generation, regenerate, *, stop=None: regenerate("state", None) and 0 or {}
    flag = lambda: False  # noqa: E731
    assert rt.run(flag) == 0
    assert [name for name, _ in seen] == ["plan", "regenerate"] and all(callable(stop) for _, stop in seen)


# ---- F1: one operation deadline ------------------------------------------------------------------------------------
def test_the_operation_deadline_bounds_a_query_whose_irrelevant_frames_keep_arriving():
    env = Env()
    sock = Socket(env, frame_cost=3, filler=lambda: ["EVENT", "q999", stranger()])  # every frame is for another sub
    relay = client(env, sock)
    started = env.t
    result = relay.query([{"kinds": [9]}])
    assert result["ended"] == "timeout" and OP - 3 <= env.t - started <= OP
    assert not sock.kinds("CLOSE")  # D6: the budget is spent, so no cleanup send starts (no fresh allowance)


def test_the_operation_deadline_bounds_a_publish_and_it_is_unknown_not_rejected():
    env = Env()
    sock = Socket(env, frame_cost=3, filler=lambda: ["OK", "e" * 64, True, ""])  # an OK for another event
    relay = client(env, sock)
    started = env.t
    result = relay.publish(dict(stranger(), id="d" * 64, kind=1))
    assert result["accepted"] is None and result["prefix"] == "unknown" and env.t - started <= OP


def test_the_operation_deadline_covers_the_auth_retry_not_each_leg():
    env = Env()

    def on_send(frame):  # each leg is fine on its own (15 s and 12.5 s of noise, each below op_deadline) but together exceed it
        if frame[0] == "REQ":
            return [["AUTH", "chal"]] + [["EVENT", "q999", stranger(i)] for i in range(4)] + [
                ["CLOSED", frame[1], "auth-required: sign in"]]
        if frame[0] == "AUTH":
            return [["EVENT", "q999", stranger(i)] for i in range(4)] + [["OK", frame[1]["id"], True, ""]]
        return []

    sock = Socket(env, on_send, frame_cost=2.5)
    relay = client(env, sock)
    started = env.t
    assert relay.query([{"kinds": [9]}])["ended"] == "timeout"
    assert env.t - started <= OP and len(sock.kinds("REQ")) == 1  # the retry never began


def test_a_receive_timeout_is_not_the_total_deadline_and_no_deadline_keeps_todays_behaviour():
    env = Env()
    sock = Socket(env)
    assert client(env, sock).query([{}])["ended"] == "timeout" and env.t - NOW == RECV  # one receive wait, as today
    env = Env()
    sock = Socket(env, lambda frame: [["EVENT", "q1", stranger(i)] for i in range(10)] + [["EOSE", "q1"]] if frame[0] == "REQ" else [],
                  frame_cost=3)
    result = client(env, sock, op_deadline=None).query([{}])  # no op_deadline: 33 s of frames end by EOSE, as today
    assert result["ended"] == "eose" and env.t - NOW == 33


def test_config_op_deadline_seconds_defaults_to_twenty_and_must_exceed_recv_timeout():
    assert BridgeConfig.parse(document()).op_deadline_seconds == 20
    assert BridgeConfig.parse(document(recv_timeout=5, op_deadline_seconds=5.5)).op_deadline_seconds == 5.5
    for bad in ({"recv_timeout": 10, "op_deadline_seconds": 10}, {"op_deadline_seconds": 5}, {"op_deadline_seconds": "x"},
                {"op_deadline_seconds": True}, {"recv_timeout": 25}):
        with pytest.raises(ContractError):
            BridgeConfig.parse(document(**bad))


def test_the_default_relay_receives_the_configured_deadline():
    from codex_harness.composition.buzz_bridge import default_relay
    config = BridgeConfig.parse(document(op_deadline_seconds=33))
    assert default_relay(config, Signer())._op_deadline == 33


# ---- F1: the unit's stop budget is tied to that bound ---------------------------------------------------------------
def test_the_template_discriminator_rejects_a_stop_budget_below_op_deadline_plus_five(tmp_path):
    expect_violation(tmp_path, UNIT, "TimeoutStopSec=30", "TimeoutStopSec=24", "stop-timeout", "TimeoutStopSec=24")
    code, out = lint(plant(tmp_path, UNIT, "TimeoutStopSec=30", "TimeoutStopSec=25"))
    assert code == 0, out  # exactly op_deadline_seconds + 5 is enough


def test_the_stop_budget_follows_the_config_templates_op_deadline_not_recv_timeout_plus_a_tick(tmp_path):
    code, out = lint(plant(tmp_path, CONFIG, '"op_deadline_seconds": 20', '"op_deadline_seconds": 40'))
    assert code == 1 and "stop-timeout" in out, out
    code, out = lint(plant(tmp_path, CONFIG, '"recv_timeout": 10', '"recv_timeout": 12'))  # recv + tick is 17 < 25: fine
    assert code == 0, out


# ---- F2: restricted AUTH is final ----------------------------------------------------------------------------------
def restricted_relay(env):
    def on_send(frame):
        if frame[0] == "REQ":
            return [["AUTH", "challenge"], ["CLOSED", frame[1], "auth-required: login"]]
        if frame[0] == "AUTH":
            return [["OK", frame[1]["id"], False, "restricted: not a relay member"]]
        return []
    return Socket(env, on_send)


def test_f2_a_restricted_auth_answer_exits_four_with_one_auth_and_no_planning_delivery_or_sleep():
    env = Env()
    sock = restricted_relay(env)
    rt, calls = compose(env, client(env, sock), ["a"], tick_seconds=1, max_seconds=30)
    assert rt.run(lambda: False) == 4  # example 2
    assert len(sock.kinds("AUTH")) == 1 and len(sock.kinds("REQ")) == 1
    assert calls == [] and env.slices == [] and env.lines[-1]["exit"] == 4  # no plan/deliver/compact, no retry sleep


def test_f2_the_refusal_is_sticky_the_client_never_authenticates_or_sends_again():
    env = Env()
    sock = restricted_relay(env)
    relay = client(env, sock)
    assert relay.query([{}])["ended"] == "closed:restricted" and relay.auth_refused == "restricted"
    sent = len(sock.sent)
    assert relay.query([{}])["ended"] == "closed:restricted"
    assert relay.query_all({"kinds": [9]})["ended"] == "closed:restricted"
    result = relay.publish(dict(stranger(), id="d" * 64, kind=1))
    assert result["accepted"] is False and result["message"].startswith("restricted:")
    assert len(sock.sent) == sent and len(sock.kinds("AUTH")) == 1  # nothing was sent after the refusal


def test_f2_a_refusal_in_the_first_of_several_channels_opens_no_further_pass():
    env = Env()
    sock = restricted_relay(env)
    rt, calls = compose(env, client(env, sock), ["a", "b", "c"], tick_seconds=1)
    assert rt.run(lambda: False) == 4
    assert len(sock.kinds("REQ")) == 1 and passes(rt.store, "b") == [] and passes(rt.store, "c") == []
    assert len(passes(rt.store, "a")) == 1 and env.lines[-1]["steps"]["inbound"]["channels"] == 1


def test_f2_a_direct_closed_restricted_is_not_a_sticky_auth_refusal():
    env = Env()
    sock = Socket(env, lambda frame: [["CLOSED", frame[1], "restricted: no"]] if frame[0] == "REQ" else [])
    relay = client(env, sock)
    assert relay.query([{}])["ended"] == "closed:restricted" and relay.auth_refused is None  # accepted A2 behaviour


def test_f2_a_positive_auth_still_retries_the_original_request_once():
    env = Env()

    def on_send(frame):
        if frame[0] == "REQ" and len(sock.kinds("REQ")) == 1:
            return [["AUTH", "challenge"], ["CLOSED", frame[1], "auth-required: login"]]
        if frame[0] == "REQ":
            return [["EOSE", frame[1]]]
        if frame[0] == "AUTH":
            return [["OK", frame[1]["id"], True, ""]]
        return []

    sock = Socket(env, on_send)
    rt, calls = compose(env, client(env, sock), ["a"], max_seconds=0)
    assert rt.run(lambda: False) == 0
    assert len(sock.kinds("AUTH")) == 1 and len(sock.kinds("REQ")) == 2 and calls.count("plan") == 1
    assert getattr(rt.relay, "auth_refused", None) is None


def test_f2_an_ordinary_lost_connection_still_follows_reconnect_pacing_and_infers_no_restriction():
    env, connects = Env(), []

    class Dead:
        def send(self, text):
            pass

        def recv(self, timeout):
            raise OSError("reset")

        def close(self):
            pass

    def connect(*a, **k):
        connects.append(env.t)
        return Dead()

    relay = BuzzRelayClient("ws://fixture.invalid", auth_signer=Signer(), auth_role="conductor", verifier=Verify(),
                            connect=connect, max_size=1 << 20, clock=env.clock, recv_timeout=RECV, op_deadline=OP)
    rt, calls = compose(env, relay, ["a"], tick_seconds=1, lease_ttl_seconds=30, max_seconds=1000)
    assert rt.run(lambda: len(connects) >= 3) == 0
    gaps = [b - a for a, b in zip(connects, connects[1:])]
    assert gaps == [pytest.approx(reconnect_delay(1006, 0)), pytest.approx(reconnect_delay(1006, 1))]
    assert calls == [] and relay.auth_refused is None


def test_f2_a_timeout_does_not_make_the_client_think_it_is_restricted():
    env = Env()
    relay = client(env, Socket(env))
    assert relay.query([{}])["ended"] == "timeout" and relay.auth_refused is None


def test_f2_the_equivalent_refusal_during_publication_exits_four_before_housekeeping(tmp_path):
    env, w = Env(), World(tmp_path)
    w.enqueue("s0", 1)
    w.enqueue("s1", 1)

    def on_send(frame):
        if frame[0] == "EVENT":
            return [["AUTH", "challenge"], ["OK", frame[1]["id"], False, "auth-required: sign in"]]
        if frame[0] == "AUTH":
            return [["OK", frame[1]["id"], False, "restricted: not a relay member"]]
        return []

    sock = Socket(env, on_send)
    relay = client(env, sock)
    w.outbox.relay = relay
    rt, calls = outbox_runtime(env, w, relay, max_seconds=100, tick_seconds=1, recover_every=1)
    assert rt.run(lambda: False) == 4
    assert len(sock.kinds("AUTH")) == 1 and len(sock.kinds("EVENT")) == 1  # the second row is never sent
    assert "recover" not in calls and "compact" not in calls and env.slices == []
    assert {row["status"] for row in w.rows()} == {"pending"}  # nothing was lost or acknowledged
    first, second = sorted(w.rows(), key=lambda row: row["subject"])
    assert (first["attempts"], second["attempts"]) == (1, 0) and second["first_sent_at"] is None  # no later delivery
    assert env.lines[-1]["steps"]["deliver"]["sent"] == 1


def test_f2_the_refusal_during_recovery_exits_four_before_compaction(tmp_path):
    env, w = Env(), World(tmp_path)

    class Refused:
        auth_refused = None

    relay = Refused()

    class Outbox:
        def deliver(self, generation, **kwargs):
            return {"sent": 0}

        def recover_deferred(self, generation, regenerate, **kwargs):
            relay.auth_refused = "restricted"
            return {}

    rt, calls = outbox_runtime(env, w, relay, max_seconds=100, recover_every=1)
    rt.outbox = Outbox()
    assert rt.run(lambda: False) == 4 and "compact" not in calls and env.slices == []


# ---- D6 (round-2 closure) item 1: pending owner rows start no sink after a stop ------------------------------------------
OWNER = "1" * 64


def seed_pending(env, store, count):
    """`count` crash-left pending owner rows on channel `a` (what an earlier run committed before its sink)."""
    ids = [f"{index + 1:064x}" for index in range(count)]
    with store.transaction() as tx:
        for ident in ids:
            RemoteInbox().insert_pending(tx, {"event_id": ident, "author": OWNER, "created_at": int(env.t) - 5,
                                              "received_at": int(env.t) - 1, "channel": "a"})
    return ids


def pending_ids(store):
    with store.transaction() as tx:
        return sorted(row["event_id"] for row in RemoteInbox().pending(tx))


def owner_runtime(env, relay, sink, *, store=None, **config):
    rt, calls = compose(env, relay, ["a"], store=store, **config)
    rt.inbound.owners, rt.inbound.sink = frozenset([OWNER]), sink
    return rt, calls


def test_d6_a_stop_during_the_first_query_starts_no_pending_sink_and_restart_settles_each_row_once():
    env, flag, sunk = Env(), [], []
    sock = Socket(env)
    sock.on_recv = lambda: flag.append(True)  # SIGTERM arrives while the first query waits
    rt, _ = owner_runtime(env, client(env, sock), lambda row, generation: sunk.append(row["event_id"]) or "command_admitted")
    ids = seed_pending(env, rt.store, 4)
    started = env.t
    assert rt.run(lambda: bool(flag)) == 0
    assert sunk == [] and pending_ids(rt.store) == ids and env.t - started <= OP  # no new unit began; rows stay pending
    assert passes(rt.store, "a")[0]["state"] == "running"  # an unfinished pass, not a gap observation
    rt2, _ = owner_runtime(env, client(env, Socket(env, relay_of([]))),
                           lambda row, generation: sunk.append(row["event_id"]) or "command_admitted",
                           store=rt.store, max_seconds=0)
    assert rt2.run(lambda: False) == 0
    assert sorted(sunk) == ids and pending_ids(rt.store) == []  # each exactly once
    assert rt2.run(lambda: False) == 0 and sorted(sunk) == ids  # nothing replays once settled


def test_d6_a_stop_during_the_first_started_sink_finishes_it_begins_no_second_and_restart_has_no_duplicate_effect():
    env, flag, sunk = Env(), [], []

    def sink(row, generation):
        sunk.append(row["event_id"])
        flag.append(True)  # SIGTERM arrives while the first unit runs
        env.t += 8
        return "command_admitted"

    rt, _ = owner_runtime(env, client(env, Socket(env, relay_of([]))), sink)
    ids = seed_pending(env, rt.store, 4)
    assert rt.run(lambda: bool(flag)) == 0
    assert sunk == ids[:1] and pending_ids(rt.store) == ids[1:]  # the started unit settled; none began after it
    rt2, _ = owner_runtime(env, client(env, Socket(env, relay_of([]))),
                           lambda row, generation: sunk.append(row["event_id"]) or "command_admitted",
                           store=rt.store, max_seconds=0)
    assert rt2.run(lambda: False) == 0
    assert sunk == ids and pending_ids(rt.store) == []  # the settled row was not sunk again: one effect per row


def test_d6_a_stop_during_recovery_starts_no_compaction_and_keeps_the_deferred_work(tmp_path):
    env, w, flag = Env(), World(tmp_path, outbox_max=1), []
    w.enqueue("s0", 1)
    w.enqueue("s1", 1)  # deferred: capacity
    w.outbox.deliver(w.generation)  # s0 is acknowledged: capacity frees, the class stays deferred until recovered
    items = [{"subject": f"r{i}", "version": 1, "unsigned": w.unsigned(f"r{i}")} for i in range(3)]
    rt, calls = outbox_runtime(env, w, w.relay, max_seconds=100, recover_every=1)
    rt.projection.regenerate = lambda cls, after, *, stop=None: flag.append(True) or items  # the stop lands in recovery
    before = len(w.rows())
    assert rt.run(lambda: bool(flag)) == 0
    assert flag and "compact" not in calls  # recovery ran (its regeneration set the stop); no compaction followed
    assert w.rows("buzz_outbox_watermarks")[0]["deferred"] is True and len(w.rows()) == before  # nothing dropped
    flag.clear()
    rt2, calls2 = outbox_runtime(env, w, w.relay, recover_every=1)
    rt2.projection.regenerate = lambda cls, after, *, stop=None: items[:1]  # one fits the freed capacity
    assert rt2.run(lambda: False) == 0
    assert "compact" in calls2 and w.rows("buzz_outbox_watermarks")[0]["deferred"] is False  # resumed and settled


# ---- D6 item 2: the operation deadline covers a blocked send, the AUTH retry and the cleanup ------------------------------
class FakeTimer:
    """A `threading.Timer` stand-in: it never fires by itself. A stalled send fires the armed watchdog on a real thread
    (as the real Timer would), advancing the fake clock by the delay it was armed with."""

    def __init__(self, owner, delay, fn):
        self.owner, self.delay, self.fn = owner, delay, fn
        self.started = self.cancelled = self.fired = False
        self.thread = None

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def join(self, timeout=None):
        if self.thread is not None:
            self.thread.join(timeout)

    def fire(self):
        self.fired = True
        self.thread = threading.Thread(target=self._run)
        self.thread.start()

    def _run(self):
        self.owner.env.t += self.delay
        self.fn()


class Timers:
    def __init__(self, env):
        self.env, self.made = env, []

    def __call__(self, delay, fn):
        timer = FakeTimer(self, delay, fn)
        self.made.append(timer)
        return timer

    def fire_armed(self):
        armed = [t for t in self.made if t.started and not t.cancelled and not t.fired]
        assert armed, "a send blocked with no watchdog armed"
        armed[-1].fire()


class StallSock:
    def __init__(self):
        self.shutdowns, self.released = [], threading.Event()

    def shutdown(self, how):
        self.shutdowns.append(how)
        self.released.set()


class StallWs(Socket):
    """A websockets-like connection whose send of the `stall` frame kinds cannot complete until its socket is shut down."""

    def __init__(self, env, timers, stall, on_send=None, **kwargs):
        super().__init__(env, on_send, **kwargs)
        self.timers, self.stall, self.socket, self.closed = timers, set(stall), StallSock(), 0

    def send(self, text):
        frame = json.loads(text)
        if frame[0] not in self.stall:
            return super().send(text)
        self.sent.append(frame)  # attempted, never completed
        self.timers.fire_armed()
        assert self.socket.released.wait(5), "the watchdog never shut the socket down"
        raise OSError("socket shut down")

    def close(self):
        self.closed += 1


def live_threads():
    return {t for t in threading.enumerate() if t.is_alive()}


def eose_on_req(frame):
    return [["EOSE", frame[1]]] if frame[0] == "REQ" else []


def test_d6_a_blocked_query_send_ends_timeout_in_the_budget_and_the_connection_is_discarded():
    env, before = Env(), live_threads()
    timers = Timers(env)
    first, second = StallWs(env, timers, {"REQ"}), Socket(env, eose_on_req)
    relay = client(env, [first, second], timer=timers)
    started = env.t
    result = relay.query([{"kinds": [9]}])
    assert result["ended"] == "timeout" and env.t - started <= OP  # the same total budget
    assert first.socket.shutdowns == [socket.SHUT_RDWR]  # the watchdog shut the socket down, once
    assert [frame[0] for frame in first.sent] == ["REQ"]  # the attempted sends: no CLOSE followed
    assert [t.delay for t in timers.made] == [OP] and first.closed == 1  # armed with the remaining budget; discarded
    assert relay.query([{"kinds": [9]}])["ended"] == "eose" and second.kinds("REQ")  # a new connection, never the old one
    assert live_threads() <= before  # no leaked watchdog thread


def test_d6_a_blocked_publish_send_ends_unknown_not_rejected_in_the_budget():
    env, before = Env(), live_threads()
    timers = Timers(env)
    ws = StallWs(env, timers, {"EVENT"})
    relay = client(env, ws, timer=timers)
    started = env.t
    result = relay.publish(dict(stranger(), id="d" * 64, kind=1))
    assert result["accepted"] is None and result["prefix"] == "unknown" and env.t - started <= OP  # a partial send is no negative fact
    assert ws.socket.shutdowns == [socket.SHUT_RDWR] and [frame[0] for frame in ws.sent] == ["EVENT"]
    assert live_threads() <= before


def test_d6_a_blocked_cleanup_close_gets_only_the_remaining_budget():
    env, before = Env(), live_threads()
    timers = Timers(env)
    ws = StallWs(env, timers, {"CLOSE"})  # the REQ is sent, nothing answers: a receive timeout leaves 10 s of budget
    relay = client(env, ws, timer=timers)
    started = env.t
    assert relay.query([{"kinds": [9]}])["ended"] == "timeout"
    assert env.t - started <= OP and [frame[0] for frame in ws.sent] == ["REQ", "CLOSE"]
    assert [t.delay for t in timers.made] == [OP, pytest.approx(OP - RECV)]  # never a fresh allowance for the CLOSE
    assert ws.socket.shutdowns == [socket.SHUT_RDWR]
    assert live_threads() <= before


def test_d6_a_blocked_auth_send_ends_timeout_and_the_request_is_not_retried():
    env, before = Env(), live_threads()
    timers = Timers(env)

    def on_send(frame):
        return [["AUTH", "chal"], ["CLOSED", frame[1], "auth-required: sign in"]] if frame[0] == "REQ" else []

    ws = StallWs(env, timers, {"AUTH"}, on_send)
    relay = client(env, ws, timer=timers)
    started = env.t
    assert relay.query([{"kinds": [9]}])["ended"] == "timeout" and env.t - started <= OP
    assert [frame[0] for frame in ws.sent] == ["REQ", "AUTH"] and ws.socket.shutdowns == [socket.SHUT_RDWR]
    assert relay.auth_refused is None and live_threads() <= before


def test_d6_a_receive_timeout_with_budget_left_still_sends_one_close_and_cancels_every_watchdog():
    env, before = Env(), live_threads()
    timers = Timers(env)
    sock = Socket(env)
    sock.socket = StallSock()
    relay = client(env, sock, timer=timers)
    assert relay.query([{}])["ended"] == "timeout" and len(sock.kinds("CLOSE")) == 1  # the control: cleanup within budget
    assert timers.made and all(t.cancelled and not t.fired for t in timers.made) and sock.socket.shutdowns == []
    assert live_threads() <= before


def test_d6_without_an_operation_deadline_no_watchdog_is_armed_and_the_a_b_behaviour_is_unchanged():
    env = Env()
    timers = Timers(env)
    sock = Socket(env, eose_on_req)
    sock.socket = StallSock()
    relay = client(env, sock, op_deadline=None, timer=timers)
    assert relay.query([{}])["ended"] == "eose" and timers.made == []


class SilentRelay:
    """A TCP server that completes the WebSocket handshake by hand and then never reads: a send into it backs up."""

    GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self):
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.url = f"ws://127.0.0.1:{self.listener.getsockname()[1]}"
        self.release = threading.Event()
        self.thread = threading.Thread(target=self._run)
        self.thread.start()

    def _run(self):
        conn, _ = self.listener.accept()
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(4096)
        key = re.search(rb"Sec-WebSocket-Key: (\S+)", data, re.I).group(1)
        accept = base64.b64encode(hashlib.sha1(key + self.GUID).digest())
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        self.release.wait(20)
        conn.close()

    def stop(self):
        self.release.set()
        self.thread.join(5)
        self.listener.close()


def wait_for_no_new_threads(before, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not live_threads() <= before:
        time.sleep(0.02)
    return live_threads() <= before


def test_d6_the_real_connect_path_aborts_a_send_that_backs_up_within_the_budget():
    from codex_harness.observation.adapters.buzz_relay import _Timeout
    before, server = live_threads(), SilentRelay()
    try:
        relay = BuzzRelayClient(server.url, auth_signer=Signer(), auth_role="conductor", verifier=Verify(),
                                max_size=1 << 20, recv_timeout=0.5, op_deadline=1.0)  # the real connect and Timer
        started = time.monotonic()
        with relay._operation(), pytest.raises(_Timeout):
            relay._send("x" * (96 << 20))  # far more than the socket buffers hold: sendall blocks
        assert 0.8 <= time.monotonic() - started <= 4  # the watchdog shut the socket down at the deadline
        assert relay._ws is None  # the connection was discarded
    finally:
        server.stop()
    assert wait_for_no_new_threads(before)


def test_d6_a_requested_stop_aborts_the_socket_instead_of_waiting_for_the_close_handshake():
    before, server = live_threads(), SilentRelay()  # it never answers a close frame
    try:
        relay = BuzzRelayClient(server.url, auth_signer=Signer(), auth_role="conductor", verifier=Verify(),
                                max_size=1 << 20, recv_timeout=0.5, op_deadline=2.0)
        relay._open()
        started = time.monotonic()
        relay.abort()
        assert time.monotonic() - started < 3 and relay._ws is None  # not websockets' default 10 s close_timeout
        relay.abort()  # idempotent
    finally:
        server.stop()
    assert wait_for_no_new_threads(before)


def test_d6_the_runtime_aborts_the_relay_on_a_requested_stop_and_closes_it_gracefully_otherwise():
    for stopped, expected in ((True, "abort"), (False, "close")):
        env, seen = Env(), []
        rt, _ = runtime(env, max_seconds=0)
        rt.relay.abort = lambda: seen.append("abort")
        rt.relay.close = lambda: seen.append("close")
        assert rt.run(lambda: stopped) == 0 and seen == [expected]
