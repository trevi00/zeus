"""S11 unit XC-1 (TQ-XCUT-PLAN §1 A1-A4): four boundary defects, each pinned through its public boundary.

Intended differences from M7 (SOURCE e38aa722), all "documented bug, not a compatibility requirement"
(REBUILD-DESIGN-v2 rule, owner 2026-10-05): A1 `RedisBus.decode` of a too-deeply nested body no longer lets
`RecursionError` escape (M7's `decode` is the identical one-liner and raises it); A2 a schema-validation error no
longer echoes the offending value (the `kernel.values` compare family declares the changed texts).

Behavioural tests only (TQ-XCUT-RESEARCH T1): the consumer loop's dead letter and ack, the DLQ list and `serve`
output. The real-Redis variant of A1 belongs to the owner's target-integration run.
"""

import json
import sys

import pytest
from test_s10_a5_1b_dlq import FixedClock
from test_s10_c5e_cycle_serve import MESSAGE, documents

from codex_harness import composition
from codex_harness.composition import cli_bus, cli_dlq
from codex_harness.composition import observation as observation_composition
from codex_harness.coordination.application.dead_letters import DeadLetters
from codex_harness.entry import cli
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.redis_bus import RedisBus

AGENT = "lead:improvement"
TOKEN = "Bearer-TOKEN-ABCDEFGH12345678"


class ConsumerBus:
    """A scripted consumer bus: the real `RedisBus.decode`, and a dead letter that also acknowledges, as the
    server-side step of `RedisBus.dead_letter` does (DESIGN-s10 §17a)."""

    decode = staticmethod(RedisBus.decode)

    def __init__(self, rows):
        self.rows, self.acked, self.dead = list(rows), [], []

    def receive(self, agent, consumer):
        return self.rows.pop(0) if self.rows else None

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)

    def dead_letter(self, agent, entry_id, fields, reason):
        self.dead.append((entry_id, reason))
        self.acked.append(entry_id)

    def publish(self, message):
        return "1-0"


def serve_once(monkeypatch, capsys, tmp_path, bus):
    store = MemoryStore()
    monkeypatch.setattr(composition, "build", lambda: composition.ServiceHandle(store, packaged_organization()))
    monkeypatch.setattr(observation_composition, "observation_root", lambda: tmp_path / "observations")
    monkeypatch.setattr(cli_bus, "bus", lambda: bus)
    monkeypatch.setattr(sys, "argv", ["zeus", "serve", "--agent", AGENT, "--once"])
    cli.main()  # an exception escaping the consumer loop fails the test here
    return documents(capsys.readouterr().out)


def test_a_body_nested_beyond_the_parser_is_dead_lettered_once_acked_and_the_next_message_is_served(
        monkeypatch, capsys, tmp_path):
    deep = "[" * 100000 + "]" * 100000
    bus = ConsumerBus([("1-0", {"body": deep}), ("2-0", {"body": json.dumps(MESSAGE)})])
    first = serve_once(monkeypatch, capsys, tmp_path, bus)
    assert first[-1]["rejected"] == "1-0"
    assert [entry for entry, _ in bus.dead] == ["1-0"] and bus.acked == ["1-0"]
    assert bus.dead[0][1].startswith("body_invalid")
    second = serve_once(monkeypatch, capsys, tmp_path, bus)
    assert second[-1]["message_id"] == MESSAGE["message_id"]
    assert [entry for entry, _ in bus.dead] == ["1-0"] and bus.acked == ["1-0", "2-0"]


def test_a_validation_failure_names_the_field_path_and_the_rule_but_never_the_offending_value(
        monkeypatch, capsys, tmp_path):
    bus = ConsumerBus([("1-0", {"body": json.dumps({**MESSAGE, "type": TOKEN})})])
    out = serve_once(monkeypatch, capsys, tmp_path, bus)
    (entry_id, reason), = bus.dead
    printed = out[-1]
    assert printed["rejected"] == entry_id and printed["reason"] == reason
    assert TOKEN not in reason and TOKEN not in json.dumps(out)
    assert "['type']" in reason and "enum" in reason
    # `zeus dlq list` over a dead-letter record carrying that reason
    record = ("1-0", {"source": f"ns:agent:{AGENT}", "entry_id": entry_id,
                      "body": json.dumps({**MESSAGE, "type": TOKEN}), "reason": reason})

    class ListBus:
        namespace = "ns"
        decode = staticmethod(RedisBus.decode)

        @staticmethod
        def dead_letters(limit):
            return [record]

    monkeypatch.setattr(cli_dlq, "dead_letters",
                        lambda: DeadLetters(MemoryStore(), ListBus(), clock=FixedClock()))
    monkeypatch.setattr(sys, "argv", ["zeus", "dlq", "list"])
    cli.main()
    listed = capsys.readouterr().out
    assert TOKEN not in listed and "['type']" in listed and "enum" in listed


def test_a_reason_that_names_no_value_is_unchanged():
    with pytest.raises(Exception, match=r"^\[\]: 'who' is a required property$"):
        RedisBus.decode({"body": json.dumps({k: v for k, v in MESSAGE.items() if k != "who"})})


def test_a_failing_codex_exec_prints_its_error_without_the_provider_stderr_token(monkeypatch, capsys):
    """A3: the COMPOSED runtime (`composition.cli.codex_runtime`, what `zeus canary --live` builds) runs a fake
    `codex` that exits 1 with a credential-shaped stderr. The printed error keeps its shape and exit code
    (`{"error": "Codex execution failed (exit=1): ..."}`, exit 1) but not the token. M7 printed the raw tail:
    a documented bug, not a compatibility requirement (REBUILD-DESIGN-v2 rule)."""
    from types import SimpleNamespace

    from codex_harness.composition import cli as composition_cli
    from codex_harness.execution.adapters.providers import codex_exec

    secret = "sk-ant-api03-" + "A1b2C3d4" * 6
    stderr = f"auth failed for Authorization: Bearer {secret} please retry"

    def fake_codex(argv, **kwargs):
        if argv[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="codex 0.0\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr=stderr)

    monkeypatch.setattr(codex_exec, "resolve_codex", lambda: "fake-codex")
    monkeypatch.setattr(composition_cli, "run_process", fake_codex)
    monkeypatch.setattr(sys, "argv", ["zeus", "canary", "--live"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    captured = capsys.readouterr()
    assert caught.value.code == 1
    error = json.loads(captured.err)["error"]
    assert error.startswith("Codex execution failed (exit=1): ")
    assert secret not in captured.err + captured.out
    assert "auth failed" in error
