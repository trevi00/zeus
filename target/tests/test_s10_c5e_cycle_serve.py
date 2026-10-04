"""S10 unit C5e: the cycle and serve roots behind `entry.cli.main` (DESIGN-s10 §3 C5, R-c22).

Parity with M7 is the `entry.cli_cycle_serve.pgredis` compare family; these tests cover what it cannot with a MemoryStore and a fake
bus: the builders' wiring, `serve` acknowledging one message and dead-lettering a bad one, `cycle step` refusing without a composition
profile (E-c21) and the dispatch table.
"""

import ast
import json
import sys
from pathlib import Path

import pytest

from codex_harness import composition
from codex_harness.composition import cli_bus, cli_cycle
from codex_harness.composition import observation as observation_composition
from codex_harness.coordination.application.local_cycle import LocalCycle
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.entry import cli
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.redis_bus import RedisBus

MESSAGE = {
    "schema_version": "1.0", "message_id": "00000000-0000-4000-8000-0000000000e5", "type": "task.assign",
    "correlation_id": "c-1", "causation_id": None,
    "who": {"sender": "conductor", "recipient": "lead:improvement", "owner": "lead:improvement"},
    "what": {"action": "plan", "details": {"objective": "cycle and serve roots"}},
    "why": {"objective": "Improve harness reliability from verified evidence", "evidence_refs": []},
    "when": {"created_at": "2026-01-01T00:00:00+00:00", "deadline": None, "after": []},
    "where": {"repository": "codex-harness", "revision": "bootstrap", "environment": "local", "allowed_paths": []},
    "how": {"constraints": [], "acceptance_criteria": ["Preserve normal behavior"],
            "context_ref": None, "result_schema": "six-w.v1"},
}


class FakeBus:
    """One scripted receive turn, then silence; records what `serve` did with it."""

    decode = staticmethod(RedisBus.decode)

    def __init__(self, rows):
        self.rows, self.acked, self.dead, self.published = list(rows), [], [], []

    def receive(self, agent, consumer):
        return self.rows.pop(0) if self.rows else None

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)

    def dead_letter(self, agent, entry_id, fields, reason):
        self.dead.append((entry_id, reason))

    def publish(self, message):
        self.published.append(message["message_id"])
        return "1-0"


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["zeus", *argv])
    try:
        cli.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def memory_service(monkeypatch, tmp_path, bus=None):
    store = MemoryStore()
    monkeypatch.setattr(composition, "build", lambda: composition.ServiceHandle(store, packaged_organization()))
    monkeypatch.setattr(observation_composition, "observation_root", lambda: tmp_path / "observations")
    if bus is not None:
        monkeypatch.setattr(cli_bus, "bus", lambda: bus)
    return store


def documents(text):
    decoder, position, found = json.JSONDecoder(), 0, []
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        document, position = decoder.raw_decode(text, position)
        found.append(document)
    return found


def test_the_dispatch_table_composes_cycle_and_serve():
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    tables = [{k.value for k in node.keys if isinstance(k, ast.Constant)}
              for node in ast.walk(tree) if isinstance(node, ast.Dict)]
    assert any({"cycle", "serve"} <= table for table in tables)


def test_the_builders_wire_the_cycle_the_handler_and_the_incident_recorder():
    store = MemoryStore()
    service = composition.ServiceHandle(store, packaged_organization())
    handler = cli_cycle.serve_handler(service)
    assert isinstance(handler, MessageHandler)
    assert handler.store is store
    cycle = cli_cycle.local_cycle(service)
    assert isinstance(cycle, LocalCycle)
    assert cycle.store is store and cycle.org is service.org
    assert cycle.executor is None and cycle.bus is None and cycle.workflow is None and cycle.observer is None
    assert cycle.flusher.store is store
    assert callable(cycle.incidents) and cycle.incidents.__self__.store is store
    wired = cli_cycle.local_cycle(service, "executor", "bus", handler, observer="observer")
    assert (wired.executor, wired.bus, wired.workflow, wired.observer) == ("executor", "bus", handler, "observer")


def test_cycle_start_status_and_handoff_are_store_only(monkeypatch, capsys, tmp_path):
    memory_service(monkeypatch, tmp_path)
    code, out, _ = run_main(monkeypatch, capsys, "cycle", "start", "c1", "--correlation", "c", "--max-executions", "2")
    assert code == 0 and json.loads(out)["max_executions"] == 2
    code, out, _ = run_main(monkeypatch, capsys, "cycle", "status", "c1")
    assert code == 0 and json.loads(out)["remaining_executions"] == 2
    code, out, _ = run_main(monkeypatch, capsys, "cycle", "handoff", "c1")
    assert code == 0 and json.loads(out)["remaining_executions"] == 2
    code, _, err = run_main(monkeypatch, capsys, "cycle", "status", "nope")
    assert code == 1 and json.loads(err) == {"error": "Unknown cycle"}


def test_cycle_step_refuses_without_a_composition_profile(monkeypatch, capsys, tmp_path):
    memory_service(monkeypatch, tmp_path, FakeBus([]))
    monkeypatch.delenv("ZEUS_COMPOSITION_PROFILE", raising=False)
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path))
    run_main(monkeypatch, capsys, "cycle", "start", "c1", "--correlation", "c", "--max-executions", "1")
    code, out, err = run_main(monkeypatch, capsys, "cycle", "step", "c1")
    assert code == 1 and out == "" and json.loads(err) == {"error": "composition_profile_unknown"}


def test_serve_acknowledges_one_message(monkeypatch, capsys, tmp_path):
    bus = FakeBus([("1-0", {"body": json.dumps(MESSAGE)})])
    store = memory_service(monkeypatch, tmp_path, bus)
    code, out, _ = run_main(monkeypatch, capsys, "serve", "--agent", "lead:improvement", "--once")
    assert code == 0
    first, second = documents(out)
    assert first["status"] == "listening" and first["autonomous"] is False
    assert second["message_id"] == MESSAGE["message_id"]
    assert bus.acked == ["1-0"] and bus.dead == []
    with store.transaction() as tx:
        assert tx.get("tasks", MESSAGE["message_id"]) is not None


def test_serve_dead_letters_a_message_for_another_agent_and_a_malformed_body(monkeypatch, capsys, tmp_path):
    misrouted = {**MESSAGE, "who": {"sender": "conductor", "recipient": "worker:implementation",
                                    "owner": "lead:improvement"}}
    for entry_id, body in (("2-0", json.dumps(misrouted)), ("3-0", "{not json")):
        bus = FakeBus([(entry_id, {"body": body})])
        memory_service(monkeypatch, tmp_path, bus)
        code, out, _ = run_main(monkeypatch, capsys, "serve", "--agent", "lead:improvement", "--once")
        assert code == 0
        assert documents(out)[-1]["rejected"] == entry_id
        assert [e for e, _ in bus.dead] == [entry_id] and bus.acked == []


def test_serve_refuses_an_unknown_agent(monkeypatch, capsys, tmp_path):
    memory_service(monkeypatch, tmp_path, FakeBus([]))
    code, _, err = run_main(monkeypatch, capsys, "serve", "--agent", "nobody", "--once")
    assert code == 1 and "error" in json.loads(err)


def test_serve_with_execute_needs_a_profile(monkeypatch, capsys, tmp_path):
    memory_service(monkeypatch, tmp_path, FakeBus([]))
    monkeypatch.delenv("ZEUS_COMPOSITION_PROFILE", raising=False)
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path))
    code, _, err = run_main(monkeypatch, capsys, "serve", "--agent", "lead:improvement", "--once", "--execute")
    assert code == 1 and json.loads(err) == {"error": "composition_profile_unknown"}


@pytest.mark.parametrize("name", ["cycle", "serve"])
def test_the_entry_modules_import_no_adapter(name):
    tree = ast.parse((Path(cli.__file__).parent / (name + ".py")).read_text(encoding="utf-8"))
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    assert not [m for m in imported if ".adapters" in m]
