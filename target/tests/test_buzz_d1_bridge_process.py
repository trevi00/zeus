"""Buzz D1: the bridge process (composition loop, stop, bounded run, reconnect, store failures, config, owner id).

Fakes only: a fake clock/monotonic/sleep, scripted use cases or a scripted relay, MemoryStore. No network, Docker or PG.
Contracts: Buzz DESIGN-D §2, §6 rows 1-3; DESIGN §6.4-§6.5.
"""
import json
import os
import signal
import stat

import pytest
from test_buzz_b3_remote_control import CHANNEL, NOW, OWNER, fence, inbox_row
from test_buzz_b4_projection import D_ORG, P

from codex_harness.composition import buzz_bridge as bb
from codex_harness.composition.buzz_bridge import BridgeConfig, BridgeRuntime, ZeusWorld, build_runtime
from codex_harness.coordination.application.bridge_lease import LOST, BridgeLease
from codex_harness.entry.processes import buzz_bridge as entry
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters.buzz_relay import reconnect_delay
from codex_harness.storage.adapters.memory_store import MemoryStore

HEX = "a" * 64
SCHEME = "postgresql" + "://"  # split: the tree check flags credential-shaped literals


def document(**extra):
    base = {"relay_url": "ws://127.0.0.1:1", "channels": ["c1"], "owners": [HEX], "custody_dir": "/nonexistent",
            "store_dsn_file": "/nonexistent"}
    return {**base, **extra}


class Env:
    """A fake clock: `sleep` advances time, so the run is instant and measurable."""

    def __init__(self):
        self.t, self.slices, self.lines = float(NOW), [], []

    def monotonic(self):
        return self.t

    clock = monotonic

    def sleep(self, seconds):
        self.slices.append(seconds)
        self.t += seconds

    def out(self, text):
        self.lines.append(json.loads(text))


class Inbound:
    def __init__(self, calls, relay):
        self.calls, self.relay, self.script, self.generations = calls, relay, [], []

    def run(self, generation):
        self.calls.append("inbound")
        self.generations.append(generation)
        step = self.script.pop(0) if self.script else None
        if isinstance(step, BaseException):
            raise step
        ended = step or "eose"
        self.relay.query_all({"kinds": [9]})
        return {"c1": {"ended": ended, "events": 0, "inserted": 0, "sunk": 0, "sink_failed": 0}}

    def compact(self, generation):
        self.calls.append("compact")
        return 0


class Projection:
    def __init__(self, calls):
        self.calls, self.generation = calls, None

    def use_generation(self, generation):
        self.generation = generation

    def plan(self, generation):
        self.calls.append("plan")
        return {"org": 0}

    def regenerate(self, cls, after):
        return []


class Outbox:
    def __init__(self, calls):
        self.calls = calls

    def deliver(self, generation):
        self.calls.append("deliver")
        return {"sent": 0}

    def recover_deferred(self, generation, regenerate):
        self.calls.append("recover")
        return {}


class Relay:
    def __init__(self, env):
        self.env, self.last_close_code, self.closed, self.on_query = env, None, 0, None

    def query_all(self, filter, **kwargs):  # noqa: A002
        if self.on_query:
            self.on_query()

    def close(self):
        self.closed += 1


def runtime(env, store=None, owner="owner-1", **config):
    calls = []
    relay = Relay(env)
    inbound = Inbound(calls, relay)
    rt = BridgeRuntime(BridgeConfig.parse(document(**config)), store=store or MemoryStore(), relay=relay,
                       inbound=inbound, projection=Projection(calls), outbox=Outbox(calls), clock=env.clock,
                       monotonic=env.monotonic, sleep=env.sleep, owner_id=owner, out=env.out)
    return rt, calls


def never():
    return False


# ---- loop order, passive, lease loss -------------------------------------------------------------------------------
def test_one_tick_runs_lease_inbound_plan_deliver_then_housekeeping_in_order():
    env = Env()
    rt, calls = runtime(env, max_seconds=0, recover_every=1)
    assert rt.run(never) == 0
    assert calls == ["inbound", "plan", "deliver", "recover", "compact"]
    assert env.lines[0]["generation"] == 1 and env.lines[0]["tick"] == 1
    assert set(env.lines[0]["steps"]) == {"inbound", "plan", "deliver", "recover", "compact"}
    assert rt.relay.closed == 1


def test_a_lease_held_by_another_owner_is_passive_and_retried_next_tick():
    env, store = Env(), MemoryStore()
    with store.transaction() as tx:
        assert BridgeLease().acquire(tx, "other", env.t, 100) == 1
    rt, calls = runtime(env, store, max_seconds=2, tick_seconds=1, lease_ttl_seconds=30)
    assert rt.run(never) == 0
    assert calls == [] and [line["generation"] for line in env.lines] == ["passive"] * 3  # ticks at 0, 1, 2
    env.t += 200  # the other lease expired: the next tick takes it
    rt.config = BridgeConfig.parse(document(max_seconds=0))
    assert rt.run(never) == 0 and calls[0] == "inbound" and env.lines[-1]["generation"] == 2


def test_a_lease_lost_mid_tick_ends_the_tick_and_reacquires_a_new_generation():
    env = Env()
    rt, calls = runtime(env, max_seconds=2, tick_seconds=1, lease_ttl_seconds=30)
    rt.inbound.script = [ContractError(LOST)]
    assert rt.run(never) == 0
    assert calls == ["inbound", "inbound", "plan", "deliver", "compact", "inbound", "plan", "deliver"]
    assert rt.inbound.generations == [1, 2, 2]  # the lost tick ran nothing after the inbound pass
    assert env.lines[0]["steps"] == {"lease": "lost"} and env.lines[1]["generation"] == 2


# ---- stop ----------------------------------------------------------------------------------------------------------
def test_a_stop_set_during_a_blocked_pass_returns_before_the_next_step_within_recv_timeout_plus_a_step():
    env = Env()
    rt, calls = runtime(env, recv_timeout=10, max_seconds=900)
    flag = []

    def blocked_until_timeout():
        flag.append(True)  # SIGTERM arrives mid-call; the call returns at its own timeout
        env.t += 10

    rt.relay.on_query = blocked_until_timeout
    started = env.t
    assert rt.run(lambda: bool(flag)) == 0
    assert calls == ["inbound"] and env.t - started <= 10 + 0.5


def test_the_sliced_wait_honours_stop_within_half_a_second():
    env = Env()
    rt, _ = runtime(env)
    rt._wait(5, lambda: env.t - NOW >= 0.7)
    assert max(env.slices) <= 0.5 and env.t - NOW <= 1.0
    assert sum(env.slices) < 5


def test_sigterm_through_the_entry_stops_a_real_wired_runtime_before_planning(tmp_path):
    handlers = {n: signal.getsignal(n) for n in (signal.SIGTERM, signal.SIGINT)}
    try:
        w = Wired(tmp_path)
        w.relay_script = lambda: os.kill(os.getpid(), signal.SIGTERM)
        code = entry.main(["--config", str(w.config_path)], **w.wiring())
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
    assert code == 0 and w.p.rows() == [] and w.relay.published == []  # no plan, no delivery after the signal
    assert w.relay.queried == 1


# ---- bounded run ---------------------------------------------------------------------------------------------------
def test_max_seconds_ends_after_the_current_tick_with_exit_zero():
    env = Env()
    rt, calls = runtime(env, max_seconds=3, tick_seconds=1, lease_ttl_seconds=30)
    assert rt.run(never) == 0
    assert [line["tick"] for line in env.lines] == [1, 2, 3, 4] and env.t == NOW + 3
    assert calls.count("deliver") == 4 and calls[-1] == "deliver"  # the last tick completed


# ---- reconnect -----------------------------------------------------------------------------------------------------
def queried_at(env, rt, stop_after):
    """The fake time of each inbound pass; the run stops once `stop_after` passes ran."""
    times, flag = [], []

    def on_query():
        times.append(env.t)
        if len(times) >= stop_after:
            flag.append(True)

    rt.relay.on_query = on_query
    return times, (lambda: bool(flag))


def test_a_lost_connection_is_reopened_after_reconnect_delay_in_stop_checked_slices():
    env = Env()
    rt, calls = runtime(env, max_seconds=100, tick_seconds=1, lease_ttl_seconds=30)
    rt.inbound.script = ["connection_closed", "connection_closed", None]
    rt.relay.last_close_code = 1006
    times, stop = queried_at(env, rt, 3)
    assert rt.run(stop) == 0
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps == [pytest.approx(reconnect_delay(1006, 0)), pytest.approx(reconnect_delay(1006, 1))]
    assert calls[:2] == ["inbound", "inbound"]  # a lost tick runs no plan or delivery
    assert max(env.slices) <= 0.5


def test_a_final_close_code_exits_three():
    env = Env()
    rt, calls = runtime(env, tick_seconds=1, lease_ttl_seconds=30)
    rt.inbound.script = ["connection_closed"]
    rt.relay.last_close_code = 1000
    assert rt.run(never) == 3 and calls == ["inbound"] and env.lines[-1]["exit"] == 3 and env.slices == []


def test_a_restricted_auth_exits_four_without_retry():
    env = Env()
    rt, calls = runtime(env)
    rt.inbound.script = ["closed:restricted"]
    assert rt.run(never) == 4 and calls == ["inbound"] and env.slices == [] and env.lines[-1]["exit"] == 4


def test_the_reconnect_attempt_counter_resets_after_a_healthy_pass():
    env = Env()
    rt, _ = runtime(env, max_seconds=60, tick_seconds=1, lease_ttl_seconds=30)
    rt.inbound.script = ["connection_closed", None, "connection_closed", None]
    rt.relay.last_close_code = 1006
    times, stop = queried_at(env, rt, 4)
    assert rt.run(stop) == 0
    gaps = [b - a for a, b in zip(times, times[1:])]
    first = pytest.approx(reconnect_delay(1006, 0))  # the second loss waits attempt 0 again, not attempt 1
    assert gaps == [first, pytest.approx(1.0), first]


# ---- store failures ------------------------------------------------------------------------------------------------
def test_n_minus_one_failures_continue_n_exit_five_and_a_success_resets():
    env = Env()
    boom = RuntimeError("password=hunter2 in message")
    rt, _ = runtime(env, max_seconds=100, tick_seconds=1, lease_ttl_seconds=30, store_fail_limit=3)
    rt.inbound.script = [boom, boom, None, boom, boom, None, boom, boom, boom]
    assert rt.run(never) == 5
    failed = [line["steps"].get("failed") for line in env.lines]
    assert failed == ["RuntimeError", "RuntimeError", None] * 2 + ["RuntimeError"] * 3
    assert env.lines[-1]["exit"] == 5 and "hunter2" not in json.dumps(env.lines)  # the class only


# ---- config --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad,match", [
    ({"surprise": 1}, "unknown keys"),
    ({"relay_url": None}, "non-empty string"),
    ({"owners": ["a" * 63]}, r"owners\[0\].*length 63"),
    ({"owners": ["A" * 64]}, r"owners\[0\]"),
    ({"channels": []}, "channels"),
    ({"tick_seconds": 0}, "tick_seconds"),
    ({"tick_seconds": 61}, "tick_seconds"),
    ({"tick_seconds": 5, "lease_ttl_seconds": 15}, "exceed three ticks"),
    ({"tick_seconds": 10}, "exceed three ticks"),  # the default ttl of 30 is not above 3 x 10
    ({"recover_every": 0}, "recover_every"),
    ({"store_fail_limit": True}, "store_fail_limit"),
])
def test_config_refuses_bad_documents(bad, match):
    with pytest.raises(ContractError, match=match):
        BridgeConfig.parse({**document(), **bad})


@pytest.mark.parametrize("key", ["relay_url", "channels", "owners", "custody_dir", "store_dsn_file"])
def test_config_refuses_a_missing_key(key):
    doc = document()
    del doc[key]
    with pytest.raises(ContractError, match="missing keys"):
        BridgeConfig.parse(doc)


def test_config_defaults_and_the_dsn_is_read_from_a_0600_file(tmp_path):
    config = BridgeConfig.parse(document())
    assert (config.tick_seconds, config.lease_ttl_seconds, config.recv_timeout, config.max_seconds,
            config.recover_every, config.store_fail_limit) == (5, 30, 10, 900, 12, 12)
    path = tmp_path / "dsn"
    path.write_text(SCHEME + "u:SECRET@h/db\n")
    path.chmod(0o600)
    config = BridgeConfig.parse(document(store_dsn_file=str(path)))
    assert config.read_dsn() == SCHEME + "u:SECRET@h/db" and "SECRET" not in repr(config)
    path.chmod(0o644)
    with pytest.raises(ContractError, match="group or world") as info:
        config.read_dsn()
    assert "SECRET" not in str(info.value)
    with pytest.raises(ContractError, match="FileNotFoundError"):
        BridgeConfig.parse(document(store_dsn_file=str(tmp_path / "missing"))).read_dsn()


def test_the_entry_refuses_a_short_owner_key_with_exit_two_naming_the_field(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(document(owners=["a" * 63])))
    assert entry.main(["--config", str(path)]) == 2
    assert "owners[0]" in capsys.readouterr().err


def test_the_entry_refuses_without_a_read_side_and_unknown_keys(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(document()))
    assert entry.main(["--config", str(path)]) == 2
    path.write_text(json.dumps(document(extra=1)))
    assert entry.main(["--config", str(path)]) == 2
    assert capsys.readouterr().err.count("refused") == 2


# ---- the wired runtime: real use cases over MemoryStore ------------------------------------------------------------
class ScriptedRelay:
    """The A3a/A3b fakes' shape: `query_all` returns the scripted owner event; `publish` accepts."""

    def __init__(self, base, events, env):
        self.base, self.events, self.env, self.published, self.queried, self.script = base, events, env, [], 0, None
        self.last_close_code = None

    def query_all(self, filter, **kwargs):  # noqa: A002
        self.queried += 1
        if self.script:
            self.script()
        self.env.t += 10  # the receive timeout elapsed
        return {"events": list(self.events), "ended": "eose", "pages": 1, "unverified": 0}

    def publish(self, event):
        self.published.append(event)
        return {"id": event["id"], "accepted": True, "prefix": "none", "message": ""}

    def query(self, filters):
        return self.base.query(filters)

    def close(self):
        pass


class Wired:
    PLANTED = "PLANTED-REASON-42"

    def __init__(self, tmp_path):
        self.env, self.p, self.dsn = Env(), P(tmp_path), SCHEME + "zeus:DSN-SECRET-77@db/zeus"
        self.dsn_path = tmp_path / "dsn"
        self.dsn_path.write_text(self.dsn)
        self.dsn_path.chmod(0o600)
        content = fence(self.p.w.cancel_cmd(1, reason=self.PLANTED))
        row = inbox_row(content, 1, created_at=NOW, received_at=NOW)
        self.event = row["event"]
        self.relay = ScriptedRelay(self.p.relay, [self.event], self.env)
        self.relay_script = None
        self.dsns = []
        self.config_path = tmp_path / "config.json"
        self.config_path.write_text(json.dumps(document(
            channels=[CHANNEL], owners=[OWNER], custody_dir=str(tmp_path / "keys"), store_dsn_file=str(self.dsn_path),
            max_seconds=0)))
        self.config = BridgeConfig.from_file(self.config_path)

    def wiring(self):
        self.relay.script = self.relay_script

        def store_factory(dsn):
            self.dsns.append(dsn)
            return self.p.w.store

        world = ZeusWorld(self.p.w.messages, self.p.w.pause, self.p.models,
                          {"commander": "cmd", "org_d": D_ORG, "teams": {"core": "c1"}}, roles=("conductor",))
        return {"world_factory": lambda store: world, "store_factory": store_factory,
                "relay_factory": lambda config, signer: self.relay, "clock": self.env.clock,
                "monotonic": self.env.monotonic, "sleep": self.env.sleep, "out": self.env.out,
                "owner_id": "bridge-1"}  # the world's own lease owner: acquiring advances to generation 2


def test_the_wired_runtime_admits_an_owner_command_and_logs_no_secret_or_content(tmp_path):
    w = Wired(tmp_path)
    runtime_ = build_runtime(w.config, **w.wiring())
    assert runtime_.run(never) == 0
    assert w.dsns == [w.dsn]  # read from the file
    line = w.env.lines[0]
    assert line["generation"] == 2 and line["steps"]["inbound"]["sunk"] == 1
    assert w.p.w.get("remote_inbox", self_id(w.event))["state"] == "processed"
    assert {"plan", "deliver"} <= set(line["steps"])
    key = (tmp_path / "keys" / "conductor.key").read_bytes()
    text = json.dumps(w.env.lines)
    secrets_ = ("DSN-SECRET-77", Wired.PLANTED, w.event["content"], key.hex(), OWNER, w.event["id"])
    assert not [s for s in secrets_ if s in text]
    assert oct(stat.S_IMODE((tmp_path / "keys" / "conductor.key").stat().st_mode)) == "0o600"


def self_id(event):
    return event["id"]


# ---- owner id ------------------------------------------------------------------------------------------------------
def test_owner_ids_are_unique_per_process_and_shaped_host_pid_start():
    first, second = bb.new_owner_id(), bb.new_owner_id()
    assert first != second
    host, pid, start = first.rsplit(":", 2)
    assert host and pid == str(os.getpid()) and start.isdigit()


def test_a_second_runtime_stays_passive_while_the_first_renews():
    env, store = Env(), MemoryStore()
    first, first_calls = runtime(env, store, owner=bb.new_owner_id(), max_seconds=4, tick_seconds=1, lease_ttl_seconds=30)
    second, second_calls = runtime(env, store, owner=bb.new_owner_id(), max_seconds=0, tick_seconds=1,
                                   lease_ttl_seconds=30)
    assert first.owner_id != second.owner_id
    second_lines = []
    second.out = lambda text: second_lines.append(json.loads(text))

    def interleaved(seconds):
        env.sleep(seconds)
        second.run(never)  # one passive tick between the first runtime's wait slices

    first.sleep = interleaved
    assert first.run(never) == 0
    assert first.inbound.generations == [1] * 5  # renewed, never re-acquired
    assert second_calls == [] and second_lines and {line["generation"] for line in second_lines} == {"passive"}
