"""Buzz D5: the batch-d round-1 corrections F1 (a real stop bound) and F2 (a restricted AUTH answer is final).

The REAL `BuzzRelayClient`, `InboundPass`, `BuzzOutbox` and `BridgeRuntime`, composed over MemoryStore with an in-memory
socket and a fake clock (`recv` advances it): no wall-clock sleep, signal, network or Docker.
Contracts: Buzz DESIGN-D section 2 (stop, relay-loss/auth policy), section 5 (stop timeout), section 6 rows 1 and 7;
DESIGN section 6.2 step 4 (an end other than EOSE is an observation, never proof).
"""
import json

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
    sock = Socket(env, relay_of(events))
    sock.on_recv = lambda: flag.append(True)  # SIGTERM arrives during the first page
    rt, calls = compose(env, client(env, sock, page=2), channels)
    assert rt.run(lambda: bool(flag)) == 0
    assert len(sock.kinds("REQ")) == 1 and calls == []  # page 2 and channel b never start
    first = inbox_ids(rt.store)
    assert len(first) == 2  # the page that was in flight is committed; the pass is left to resume
    keyset = tuple(passes(rt.store, "a")[0]["keyset"])
    assert passes(rt.store, "a")[0]["state"] == "running" and keyset[1] in first
    restarted = Socket(env, relay_of(events))
    rt2, _ = compose(env, client(env, restarted, page=2), channels, store=rt.store, max_seconds=0)
    assert rt2.run(lambda: False) == 0
    flts = [frame[2] for frame in restarted.kinds("REQ")]
    assert flts[0]["#h"] == ["a"] and (flts[0]["until"], flts[0]["before_id"]) == keyset
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
        flag.append(True)  # SIGTERM arrives during the first row's publish
        return publish(event)

    w.relay.publish = publishing
    rt, calls = outbox_runtime(env, w, w.relay)
    assert rt.run(lambda: bool(flag)) == 0
    assert len(w.relay.published) == 1 and "recover" not in calls and "compact" not in calls
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


# ---- F1: one operation deadline ------------------------------------------------------------------------------------
def test_the_operation_deadline_bounds_a_query_whose_irrelevant_frames_keep_arriving():
    env = Env()
    sock = Socket(env, frame_cost=3, filler=lambda: ["EVENT", "q999", stranger()])  # every frame is for another sub
    relay = client(env, sock)
    started = env.t
    result = relay.query([{"kinds": [9]}])
    assert result["ended"] == "timeout" and OP - 3 <= env.t - started <= OP
    assert sock.kinds("CLOSE")  # as for any timeout; the connection stays usable


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
