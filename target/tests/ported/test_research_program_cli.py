# Ported from SOURCE M7 tests/test_research_program_cli.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""`zeus research-program` CLI glue (INV-RESEARCH-PROGRAM-001): parser, register through real git in
a temporary repository, store-only status/pause/resume, run with LABELLED feed/ledger/council
stand-ins and redacted refusals. No provider, bus, observer or real ledger is ever built."""
import json
from types import SimpleNamespace

import pytest
from m7_research import Harness, organization
from test_research_program_fixtures import (
    CANARY,
    FakeBudget,
    FakeCouncil,
    FakeSources,
    config,
    git,
    repository,
)

from codex_harness import composition

# S11 M B4: `cli` is entry.cli.output (M7 `cli.emit`); `execute` is the private `_execute` of entry.cli.research_program.
from codex_harness.entry.cli import output as cli
from codex_harness.entry.cli import parser
from codex_harness.entry.cli import research_program as research_program_cli
from codex_harness.research.application.research_program import ResearchProgram
from codex_harness.research.domain.research_program import ProgramRefused
from codex_harness.storage.adapters.memory_store import MemoryStore


def guarded(monkeypatch, root):
    monkeypatch.setenv("ZEUS_REPOSITORY", str(root))
    # S11 M B4: the must-not-be-built guards are on the target homes (composition builders, RedisBus).
    for name in ("operation.build_executor", "observation.build_observer", "observation.build_collector"):
        monkeypatch.setattr("codex_harness.composition." + name, lambda *a, **k: pytest.fail(name + " built by research-program"))
    monkeypatch.setattr("codex_harness.storage.adapters.redis_bus.RedisBus", lambda url: pytest.fail("bus built by research-program"))
    return Harness(MemoryStore(), organization())


def test_parser_wires_the_five_subcommands():
    args = parser().parse_args(["research-program", "register", "--file", "p.json"])
    assert args.command == "research-program" and args.research_program_command == "register" and args.file.name == "p.json"
    run = parser().parse_args(["research-program", "run", "rp-001", "--ticks", "2", "--intent", "incident"])
    assert run.program_id == "rp-001" and run.ticks == 2
    for name in ("status", "pause", "resume"):
        assert parser().parse_args(["research-program", name, "rp-001"]).program_id == "rp-001"
    assert parser().parse_args(["autonomous", "status", "r"]).run_id == "r", "autonomous is untouched"


def test_register_status_pause_resume_touch_git_and_the_store_only(tmp_path, monkeypatch):
    root, head = repository(tmp_path)
    svc = guarded(monkeypatch, root)
    monkeypatch.setattr("codex_harness.execution.adapters.call_budget.CallBudget", lambda *a, **k: pytest.fail("ledger touched by register"))
    path = tmp_path / "program.json"
    path.write_text(json.dumps(config(head)), encoding="utf-8")
    first = research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))
    assert first["registered"] is True and first["cached"] is False and first["state"] == "paused" and first["exit_code"] == 0
    assert CANARY not in json.dumps(first)
    assert research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))["cached"] is True
    path.write_text(json.dumps(config(head, max_cycles=3)), encoding="utf-8")
    conflict = research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))
    assert conflict == {"status": "refused", "reason_code": "registration_conflict", "error_type": "ProgramRefused", "exit_code": 1}
    bad_local = dict(config(head)["local_candidates"][0], sha256="0" * 64)
    path.write_text(json.dumps(config(head, id="rp-bad", local_candidates=[bad_local])), encoding="utf-8")
    refused = research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))
    assert refused["reason_code"] == "local_source_digest_mismatch" and refused["exit_code"] == 1
    goal = config(head, id="rp-goal")
    goal["template"]["goal"]["sha256"] = "1" * 64
    path.write_text(json.dumps(goal), encoding="utf-8")
    assert research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))["reason_code"] == "contract_refused"
    path.write_text(json.dumps({"schema": "x"}), encoding="utf-8")
    assert research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))["reason_code"] == "config_schema"
    with svc.store.transaction() as tx:
        assert [r["id"] for r in tx.scan("research_programs")] == ["rp-001"], "refusals wrote nothing"
    view = research_program_cli._execute(svc, SimpleNamespace(research_program_command="status", program_id="rp-001"))
    assert view["schema"] == "urn:zeus:research-program-status:1" and view["state"] == "paused" and view["exit_code"] == 0
    assert view["cycles"] == {"completed": 0, "max": 2, "remaining": 2, "active": None} and CANARY not in json.dumps(view)
    assert research_program_cli._execute(svc, SimpleNamespace(research_program_command="resume", program_id="rp-001"))["state"] == "active"
    assert research_program_cli._execute(svc, SimpleNamespace(research_program_command="pause", program_id="rp-001"))["state"] == "paused"
    missing = research_program_cli._execute(svc, SimpleNamespace(research_program_command="status", program_id="nope"))
    assert missing["reason_code"] == "unknown_program" and missing["exit_code"] == 1


def test_run_uses_labelled_stand_ins_and_reports_exit_codes(tmp_path, monkeypatch):
    root, head = repository(tmp_path)
    svc = guarded(monkeypatch, root)
    council = FakeCouncil(svc.store, status="rejected")
    monkeypatch.setattr("codex_harness.research.adapters.research.ResearchSources", FakeSources)
    monkeypatch.setattr("codex_harness.execution.adapters.call_budget.CallBudget", lambda *a, **k: FakeBudget(this_host=1, all_hosts=1))
    monkeypatch.setattr("codex_harness.entry.cli.autonomous._run", council)
    path = tmp_path / "program.json"
    path.write_text(json.dumps(config(head)), encoding="utf-8")
    research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))
    paused = research_program_cli._execute(svc, SimpleNamespace(research_program_command="run", program_id="rp-001", ticks=1, intent="incident"))
    assert paused["ticks"] == [{"reserved": False, "reason": "paused", "state": "paused"}] and paused["exit_code"] == 0
    research_program_cli._execute(svc, SimpleNamespace(research_program_command="resume", program_id="rp-001"))
    result = research_program_cli._execute(svc, SimpleNamespace(research_program_command="run", program_id="rp-001", ticks=2, intent="incident"))
    assert result["exit_code"] == 0 and len(result["ticks"]) == 2
    assert result["ticks"][0]["selected"] == "local-note" and result["ticks"][0]["result"] == "rejected"
    assert result["ticks"][1] == {"reserved": False, "reason": "not_due", "state": "active"}
    assert len(council.manifests) == 1 and council.manifests[0]["id"] == "rp-001.c001"
    assert (root / ".runtime" / "research-program" / "rp-001" / "report.md").is_file()
    assert CANARY not in json.dumps(result)
    for ticks in (0, 101):
        out = research_program_cli._execute(svc, SimpleNamespace(research_program_command="run", program_id="rp-001", ticks=ticks, intent="incident"))
        assert out["reason_code"] == "ticks_invalid" and out["exit_code"] == 1
    unknown = FakeCouncil(svc.store, status="unknown")
    monkeypatch.setattr("codex_harness.entry.cli.autonomous._run", unknown)
    path.write_text(json.dumps(config(head, id="rp-002")), encoding="utf-8")
    research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))
    research_program_cli._execute(svc, SimpleNamespace(research_program_command="resume", program_id="rp-002"))
    blocked = research_program_cli._execute(svc, SimpleNamespace(research_program_command="run", program_id="rp-002", ticks=1, intent="incident"))
    assert blocked["exit_code"] == 1 and blocked["ticks"][0]["result"] == "unknown" and blocked["ticks"][0]["state"] == "blocked"


def test_cli_command_emits_redacted_refusals_and_exit_codes(monkeypatch):
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)
    args = parser().parse_args(["research-program", "status", "rp-001"])
    # S11 M B4: M7 `cli.research_program_command(service, args)` is `entry.cli.research_program.run(args)`, which builds its own
    # service first; `composition.build` is patched to return the test's service stand-in. `ResearchProgram` is the class of
    # research.application.research_program (the composition builder constructs it), `autonomous_cli.run` is entry.cli.autonomous._run.
    monkeypatch.setattr(composition, "build", lambda: SimpleNamespace(store=MemoryStore()))
    monkeypatch.setattr(ResearchProgram, "status", lambda self, program_id: (_ for _ in ()).throw(RuntimeError("dsn=" + CANARY)))
    with pytest.raises(SystemExit) as info:
        research_program_cli.run(args)
    assert info.value.code == 1 and outputs[-1] == {"status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}
    monkeypatch.setattr(ResearchProgram, "status", lambda self, program_id: (_ for _ in ()).throw(ProgramRefused("unknown_program")))
    with pytest.raises(SystemExit):
        research_program_cli.run(args)
    assert outputs[-1]["reason_code"] == "unknown_program"
    monkeypatch.setattr(ResearchProgram, "status", lambda self, program_id: {"state": "paused"})
    research_program_cli.run(args)
    assert outputs[-1] == {"state": "paused", "exit_code": 0} and CANARY not in json.dumps(outputs)


def test_run_in_another_real_clone_is_refused_before_any_effect(tmp_path, monkeypatch):
    """review001 R1 through the production CLI wiring: register in A, run the same id from a real
    Git clone B on the same store; nothing is reserved, fetched, captured or dispatched."""
    root, head = repository(tmp_path)
    svc = guarded(monkeypatch, root)
    council = FakeCouncil(svc.store, status="rejected")
    calls = []

    class Sources(FakeSources):
        def collect(self, source, *, intent):
            calls.append(source)
            return super().collect(source)
    monkeypatch.setattr("codex_harness.research.adapters.research.ResearchSources", Sources)
    monkeypatch.setattr("codex_harness.execution.adapters.call_budget.CallBudget", lambda *a, **k: FakeBudget())
    monkeypatch.setattr("codex_harness.entry.cli.autonomous._run", council)
    path = tmp_path / "program.json"
    path.write_text(json.dumps(config(head)), encoding="utf-8")
    assert research_program_cli._execute(svc, SimpleNamespace(research_program_command="register", file=path))["exit_code"] == 0
    research_program_cli._execute(svc, SimpleNamespace(research_program_command="resume", program_id="rp-001"))
    other = tmp_path / "clone"
    git(root, "clone", "-q", str(root), str(other))
    monkeypatch.setenv("ZEUS_REPOSITORY", str(other))
    refused = research_program_cli._execute(svc, SimpleNamespace(research_program_command="run", program_id="rp-001", ticks=2, intent="incident"))
    assert refused == {"status": "refused", "reason_code": "repository_mismatch", "error_type": "ProgramRefused", "exit_code": 1}
    assert calls == [] and council.manifests == []
    assert git(other, "for-each-ref", "refs/zeus/").stdout == "" and git(root, "for-each-ref", "refs/zeus/").stdout == ""
    assert not (other / ".runtime" / "research-program").exists()
    view = research_program_cli._execute(svc, SimpleNamespace(research_program_command="status", program_id="rp-001"))
    assert view["cycles"] == {"completed": 0, "max": 2, "remaining": 2, "active": None} and view["state"] == "active"
    monkeypatch.setenv("ZEUS_REPOSITORY", str(root))
    result = research_program_cli._execute(svc, SimpleNamespace(research_program_command="run", program_id="rp-001", ticks=1, intent="incident"))
    assert result["exit_code"] == 0 and result["ticks"][0]["selected"] == "local-note" and len(council.manifests) == 1
