"""S10 unit A5-1a (R-a51a, DESIGN-s10 §17, §17a): the atomic dead-letter script and the signal drain of
`zeus serve`. No real Redis, provider or network: a recording fake client and a scripted fake bus."""
import json
import signal
import threading

import pytest
from test_s10_c5e_cycle_serve import MESSAGE, documents, run_main

from codex_harness import composition
from codex_harness.composition import cli_bus
from codex_harness.composition import observation as observation_composition
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.redis_bus import RedisBus

AGENT = "lead:improvement"


class RecordingClient:
    def __init__(self):
        self.calls = []

    def eval(self, *args):
        self.calls.append(("eval", args))
        return 1

    def xadd(self, *args, **kwargs):
        self.calls.append(("xadd", args))

    def xack(self, *args, **kwargs):
        self.calls.append(("xack", args))


def test_dead_letter_is_one_eval_with_the_script_keys_and_argv_in_order():
    bus = RedisBus("redis://localhost:6379", "ns")
    bus.client = RecordingClient()
    bus.dead_letter("worker:x", "5-0", {"body": "b"}, "why")
    assert bus.client.calls == [("eval", (RedisBus._DEAD_LETTER_SCRIPT, 2, "ns:dead-letter", "ns:agent:worker:x",
                                          "ns:agent:worker:x", "5-0", "b", "why"))]
    bus.client.calls.clear()
    bus.dead_letter("worker:x", "5-0", {}, "why")
    assert bus.client.calls[0][1][6] == ""


def test_the_script_xadds_before_it_xacks_and_keeps_the_four_fields_in_order():
    """Structural: the packaged Lua text orders XADD before XACK and its four fields, a source-text pin of the atomic
    script (the S10 A5-1a script rule, R-a51a); the behaviour is covered by
    test_s10_a5_1b_dlq.py::test_end_to_end_dead_letter_list_replay_against_a_real_redis (needs HARNESS_REDIS_URL) and
    the `storage.redis` compare family (compare/drivers/common/s1_redis.py), and the eval argv by
    test_dead_letter_is_one_eval_with_the_script_keys_and_argv_in_order above."""
    text = RedisBus._DEAD_LETTER_SCRIPT
    assert text.index("XADD") < text.index("XACK")
    fields = [text.index(f"'{name}'") for name in ("source", "entry_id", "body", "reason")]
    assert fields == sorted(fields)
    assert "KEYS[1]" in text and "KEYS[2]" in text and "'workers'" in text


class SignalBus:
    """Returns scripted rows; the first receive sends this process `signum` while returning its row."""

    decode = staticmethod(RedisBus.decode)

    def __init__(self, rows, signum=None):
        self.rows, self.signum = list(rows), signum
        self.receives, self.acked, self.dead = 0, [], []

    def receive(self, agent, consumer):
        self.receives += 1
        if self.receives > 1 and self.signum is not None:
            raise AssertionError("receive after the stop signal")
        row = self.rows.pop(0) if self.rows else None
        if self.signum is not None:
            import os
            os.kill(os.getpid(), self.signum)
        return row

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)

    def dead_letter(self, agent, entry_id, fields, reason):
        self.dead.append((entry_id, reason))

    def publish(self, message):
        return "1-0"


class CountingObserver:
    def __init__(self, inner):
        self.inner, self.closed = inner, 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def close(self):
        self.closed += 1
        return self.inner.close()


def wire(monkeypatch, tmp_path, bus):
    store = MemoryStore()
    monkeypatch.setattr(composition, "build", lambda: composition.ServiceHandle(store, packaged_organization()))
    monkeypatch.setattr(observation_composition, "observation_root", lambda: tmp_path / "observations")
    monkeypatch.setattr(cli_bus, "bus", lambda: bus)
    holder = []
    real = observation_composition.build_observer

    def build(*args, **kwargs):
        holder.append(CountingObserver(real(*args, **kwargs)))
        return holder[-1]

    monkeypatch.setattr(observation_composition, "build_observer", build)
    return store, holder


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_a_stop_signal_settles_the_row_in_hand_then_stops_without_another_receive(monkeypatch, capsys, tmp_path, signum):
    bus = SignalBus([("1-0", {"body": json.dumps(MESSAGE)})], signum)
    store, observers = wire(monkeypatch, tmp_path, bus)
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    code, out, _ = run_main(monkeypatch, capsys, "serve", "--agent", AGENT)
    assert code == 0
    docs = documents(out)
    assert docs[0]["status"] == "listening" and docs[1]["message_id"] == MESSAGE["message_id"]
    assert docs[-1]["status"] == "stopped" and docs[-1]["agent"] == AGENT and docs[-1]["at"]
    assert bus.acked == ["1-0"] and bus.dead == [] and bus.receives == 1
    assert len(observers) == 1 and observers[0].closed == 1
    with store.transaction() as tx:
        assert tx.get("tasks", MESSAGE["message_id"]) is not None
    assert {s: signal.getsignal(s) for s in before} == before


def test_serve_from_a_non_main_thread_installs_no_handler_and_runs_as_before(monkeypatch, capsys, tmp_path):
    bus = SignalBus([("1-0", {"body": json.dumps(MESSAGE)})])
    wire(monkeypatch, tmp_path, bus)
    seen = {}

    def target():
        real = signal.signal
        monkeypatch.setattr(signal, "signal", lambda *a: pytest.fail("a handler was installed"))
        try:
            seen["code"], seen["out"], _ = run_main(monkeypatch, capsys, "serve", "--agent", AGENT, "--once")
        finally:
            monkeypatch.setattr(signal, "signal", real)

    before = signal.getsignal(signal.SIGTERM)
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    assert seen["code"] == 0 and bus.acked == ["1-0"]
    assert [d.get("status") for d in documents(seen["out"])] == ["listening", None]
    assert signal.getsignal(signal.SIGTERM) == before


def test_once_without_a_signal_prints_no_stopped_line_and_closes_once(monkeypatch, capsys, tmp_path):
    bus = SignalBus([("1-0", {"body": json.dumps(MESSAGE)})])
    _, observers = wire(monkeypatch, tmp_path, bus)
    before = signal.getsignal(signal.SIGTERM)
    code, out, _ = run_main(monkeypatch, capsys, "serve", "--agent", AGENT, "--once")
    assert code == 0
    assert [d.get("status") for d in documents(out)] == ["listening", None]
    assert observers[0].closed == 1 and bus.acked == ["1-0"]
    assert signal.getsignal(signal.SIGTERM) == before
