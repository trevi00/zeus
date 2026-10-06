# Ported from SOURCE M7 tests/test_dge_cli.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""`zeus dge` adapter and CLI glue (INV-DGE-001); git is real in a temporary repository, providers,
bus, budget and knowledge are never built."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest
from m7_research import Harness, organization, packaged_policy
from test_research_program_fixtures import config as program_config
from test_research_program_fixtures import repository as program_repository

from codex_harness import composition
from codex_harness.composition import cli_operation as operation_cli
from codex_harness.composition import cli_research  # S11 XC-9 DUP-1
from codex_harness.coordination.domain.operation import validate_manifest
from codex_harness.entry.cli import dge as dge_cli
from codex_harness.entry.cli import operation as operation_documents

# S11 M B4: `cli` is entry.cli.output (M7 `cli.emit`); `operation_documents.read_document`/`MAX_DOCUMENT_BYTES` are entry.cli.operation's
# `read_document`/`MAX_MANIFEST_BYTES`; `repository_identity`, `register`, `status` and `execute` are the private
# `_repository_identity`, `_register`, `_status` and `_execute` of entry.cli.dge (same signatures); `verify_sources` is `composition.cli_research.verify_sources` (S11 XC-9).
from codex_harness.entry.cli import output as cli
from codex_harness.entry.cli import parser
from codex_harness.host_os.adapters.git_source import GitSource
from codex_harness.kernel.errors import ContractError
from codex_harness.research.application.dge import DebateSessions, DgeRefused
from codex_harness.research.domain.dge import PacketError, packet_digest, validate_packet
from codex_harness.research.domain.research_program import config_digest, validate_config
from codex_harness.storage.adapters.memory_store import MemoryStore

CANARY = "CANARY-must-never-be-emitted"
NOTE = b"# research note\nPG store serializes writers with one advisory lock.\n"
BOM = b"\xef\xbb\xbf"


def git(root, *argv, **kwargs):
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True, text=True, **kwargs)


def repository(tmp_path):
    """Real git repository with a regular note, a symlink blob and a nested directory (fixtures)."""
    root = tmp_path / "repo"
    (root / "docs" / "research").mkdir(parents=True)
    (root / "docs" / "research" / "note.md").write_bytes(NOTE)
    (root / "docs" / "GOAL.md").write_bytes(b"# goal\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "--all")
    blob = git(root, "hash-object", "-w", "--stdin", input="docs/research/note.md").stdout.strip()
    git(root, "update-index", "--add", "--cacheinfo", "120000," + blob + ",docs/link.md")  # symlink object, portable
    git(root, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "research")
    return root, git(root, "rev-parse", "HEAD").stdout.strip()


def packet(head, **overrides):
    document = {"schema": "urn:zeus:research-packet:1", "id": "sess-cli", "base_revision": head,
                "topic": "cli wiring", "objective": "register through git " + CANARY, "exclusions": [],
                "plan": {"objective": CANARY, "acceptance_criteria": ["focused tests pass"], "allowed_paths": ["docs/RUNBOOK.md"]},
                "questions": [{"id": "q1", "question": "Is the lock global?", "blocking": True, "status": "answered", "claim_ids": ["c1"]}],
                "sources": [{"id": "s1", "path": "docs/research/note.md", "sha256": hashlib.sha256(NOTE).hexdigest(),
                             "locator": "git:docs/research/note.md", "revision": head, "read_scope": "whole note"}],
                "claims": [{"id": "c1", "kind": "fact", "text": "one advisory lock", "source_ids": ["s1"]}],
                "limits": {"max_rounds": 1, "deadline": "2030-01-01T00:00:00+00:00"},
                "supersedes": None, "research_reason": None}
    document.update(overrides)
    return document


def event(digest_value, role, version, payload):
    return {"schema": "urn:zeus:debate-event:1", "id": role + "-1", "expected_version": version,
            "packet_digest": digest_value, "round": 1, "role": role, "payload": payload}


def written(path, document, *, bom: bool, crlf: bool):
    """Exact operator bytes on disk: optional leading UTF-8 BOM, LF or CRLF, non-ASCII left as UTF-8."""
    text = json.dumps(document, ensure_ascii=False, indent=2)
    path.write_bytes((BOM if bom else b"") + (text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return path


def test_read_document_accepts_one_leading_bom_and_keeps_packet_and_config_identities(tmp_path):
    """Windows-authored operator JSON: BOM/no BOM x LF/CRLF x Korean text parse to the same validated
    documents and the same canonical digests; no schema, shape or digest input changes."""
    root, head = repository(tmp_path)
    document = packet(head, topic="저장소 잠금 연구", objective="한국어 목표 " + CANARY)
    expected = validate_packet(document)
    program_root, program_head = program_repository(tmp_path / "program")
    candidate = dict(program_config(program_head)["local_candidates"][0], rationale="한국어 채택 근거 " + CANARY)
    program = program_config(program_head, local_candidates=[candidate])  # keywords are ASCII by contract
    expected_config = validate_config(program, packaged_policy())
    identity = dge_cli._repository_identity(program_root)
    for bom in (False, True):
        for crlf in (False, True):
            suffix = str(bom) + str(crlf) + ".json"
            parsed = operation_documents.read_document(written(tmp_path / ("packet" + suffix), document, bom=bom, crlf=crlf),
                                           "Research packet")
            assert parsed == document, "the BOM is transport, not data"
            assert validate_packet(parsed) == expected
            assert packet_digest(validate_packet(parsed)) == packet_digest(expected)
            read = operation_documents.read_document(written(tmp_path / ("program" + suffix), program, bom=bom, crlf=crlf),
                                         "Research program config")
            assert read == program
            assert validate_config(read, packaged_policy()) == expected_config
            assert config_digest(validate_config(read, packaged_policy()), identity) == config_digest(expected_config, identity)


def test_read_document_refuses_malformed_bytes_and_counts_the_bom_against_the_budget(tmp_path):
    """Only one leading BOM is dropped: malformed encodings, UTF-16, duplicates, oversize and missing
    files still refuse with their existing labels, and interior U+FEFF stays part of the data."""
    path = tmp_path / "document.json"
    for content, label in ((BOM + b'{"id": "a", "id": "b"}', "duplicate JSON key"),
                           (BOM + b'{"id": ', "not valid JSON"),
                           (BOM + BOM + b'{"id": "a"}', "not valid JSON"),
                           (b'{"id": "\xff\xfe"}', "not valid JSON"),
                           ('{"id": "a"}'.encode("utf-16"), "not valid JSON"),
                           ('{"id": "a"}'.encode("utf-16-be"), "not valid JSON")):
        path.write_bytes(content)
        with pytest.raises(ContractError, match=label):
            operation_documents.read_document(path, "Research packet")
    path.write_bytes(BOM + b'{"note": "a' + BOM + b'b", "' + BOM + b'key": 1}')  # interior U+FEFF is data
    assert operation_documents.read_document(path, "Debate event") == {"note": "a\N{ZERO WIDTH NO-BREAK SPACE}b",
                                                           "\N{ZERO WIDTH NO-BREAK SPACE}key": 1}
    body = b'["' + b"a" * (operation_documents.MAX_MANIFEST_BYTES - 4) + b'"]'
    path.write_bytes(body)
    assert operation_documents.read_document(path, "Debate event") == ["a" * (operation_documents.MAX_MANIFEST_BYTES - 4)]
    path.write_bytes(BOM + body)  # the raw byte budget counts the BOM; acceptance does not widen
    with pytest.raises(ContractError, match="exceeds budget"):
        operation_documents.read_document(path, "Debate event")
    with pytest.raises(ContractError, match="unavailable"):
        operation_documents.read_document(tmp_path / "absent.json", "Debate event")


def test_verify_sources_binds_regular_blobs_and_refuses_missing_symlink_tree_and_corrupt_bytes(tmp_path):
    root, head = repository(tmp_path)
    valid = validate_packet(packet(head))
    assert cli_research.verify_sources(valid, GitSource(root)) == [
        {"id": "s1", "path": "docs/research/note.md", "sha256": valid["sources"][0]["sha256"], "bytes": len(NOTE)}]
    (root / "docs" / "research" / "note.md").write_bytes(b"changed after base\n")  # the working tree may move on
    assert cli_research.verify_sources(valid, GitSource(root))[0]["sha256"] == valid["sources"][0]["sha256"]
    source = valid["sources"][0]
    for path, code in (("docs/absent.md", "source_missing_at_base"), ("docs/link.md", "source_not_regular"),
                       ("docs/research", "source_not_regular")):
        with pytest.raises(DgeRefused, match=code):
            cli_research.verify_sources({**valid, "sources": [{**source, "path": path}]}, GitSource(root))
    with pytest.raises(DgeRefused, match="source_digest_mismatch"):
        cli_research.verify_sources({**valid, "sources": [{**source, "sha256": "0" * 64}]}, GitSource(root))
    with pytest.raises(DgeRefused, match="base_revision_missing"):
        cli_research.verify_sources({**valid, "base_revision": "0" * 40}, GitSource(root))


def test_repository_identity_matches_the_operate_identity_digest(tmp_path):
    root, head = repository(tmp_path)
    manifest = validate_manifest({"schema": "urn:zeus:operation:1", "id": "op", "base_revision": head,
                                  "goal": {"path": "docs/GOAL.md", "sha256": hashlib.sha256(b"# goal\n").hexdigest(),
                                           "criterion": "c", "rationale": "r"},
                                  "plan": {"objective": "o", "acceptance_criteria": ["a"], "allowed_paths": ["docs/RUNBOOK.md"]},
                                  "budget": {"per_host": 2, "total": 4},
                                  "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1}}, packaged_policy())
    policy = operation_cli.execution_policy(manifest, {"ZEUS_CLAUDE_EXECUTABLE": "C:/tools/claude.cmd"})
    bound = operation_cli.identity(manifest, root, policy, {}, tmp_path / "runtime")
    assert dge_cli._repository_identity(root) == bound["repository"] == dge_cli._repository_identity(tmp_path / "x" / ".." / "repo")
    assert str(root) not in dge_cli._repository_identity(root)


def test_register_submit_status_round_trip_through_real_git_and_the_store_only(tmp_path, monkeypatch):
    root, head = repository(tmp_path)
    monkeypatch.setenv("ZEUS_REPOSITORY", str(root))
    # S11 M B4: the must-not-be-built guards are on the target homes (composition builders, RedisBus, CallBudget).
    for name in ("operation.build_executor", "observation.build_observer", "observation.build_collector"):
        monkeypatch.setattr("codex_harness.composition." + name, lambda *a, **k: pytest.fail(name + " built by dge"))
    monkeypatch.setattr("codex_harness.storage.adapters.redis_bus.RedisBus", lambda url: pytest.fail("bus built by dge"))
    monkeypatch.setattr("codex_harness.execution.adapters.call_budget.CallBudget", lambda: pytest.fail("budget built by dge"))
    svc = Harness(MemoryStore(), organization())
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(packet(head)), encoding="utf-8")
    first = dge_cli._execute(svc, SimpleNamespace(dge_command="register", file=path))
    digest_value = packet_digest(validate_packet(packet(head)))
    assert first["status"] == "registered" and first["cached"] is False and first["exit_code"] == 0
    assert first["session"]["packet_digest"] == digest_value and first["session"]["repository"] == dge_cli._repository_identity(root)
    assert CANARY not in json.dumps(first) and "packet" not in first["session"]
    assert dge_cli._execute(svc, SimpleNamespace(dge_command="register", file=path))["cached"] is True
    path.write_text(json.dumps(packet(head, topic="changed")), encoding="utf-8")
    conflict = dge_cli._execute(svc, SimpleNamespace(dge_command="register", file=path))
    assert conflict == {"status": "refused", "reason_code": "packet_conflict", "error_type": "DgeRefused", "exit_code": 1}
    path.write_text(json.dumps(packet(head, id="sess-bad", questions=[
        {"id": "q1", "question": "unknown", "blocking": True, "status": "unknown", "claim_ids": []}])), encoding="utf-8")
    refused = dge_cli._execute(svc, SimpleNamespace(dge_command="register", file=path))
    assert refused["reason_code"] == "contract_refused" and refused["error_type"] == "PacketError" and CANARY not in json.dumps(refused)
    with svc.store.transaction() as tx:
        assert [s["id"] for s in tx.scan("dge_sessions")] == ["sess-cli"], "refusals wrote nothing"
    event_path = tmp_path / "event.json"
    steps = [("proposer", 0, {"summary": "bind the plan " + CANARY, "claim_ids": ["c1"]}),
             ("attacker", 1, {"findings": []}),
             ("arbiter", 2, {"verdict": "accept", "rationale": CANARY, "dispositions": [], "research_question": None})]
    for role, version, payload in steps:
        event_path.write_text(json.dumps(event(digest_value, role, version, payload)), encoding="utf-8")
        out = dge_cli._execute(svc, SimpleNamespace(dge_command="submit", session_id="sess-cli", file=event_path))
        assert out["status"] == "recorded" and out["exit_code"] == 0 and CANARY not in json.dumps(out)
    again = dge_cli._execute(svc, SimpleNamespace(dge_command="submit", session_id="sess-cli", file=event_path))
    assert again["status"] == "duplicate" and again["exit_code"] == 0
    view = dge_cli._execute(svc, SimpleNamespace(dge_command="status", session_id="sess-cli"))
    assert view["state"] == "design_approved" and view["counts"]["events"] == 3 and CANARY not in json.dumps(view)
    assert view["exit_code"] == 0 and DebateSessions(svc.store).status("sess-cli")["version"] == 3
    missing = dge_cli._execute(svc, SimpleNamespace(dge_command="status", session_id="nope"))
    assert missing["reason_code"] == "unknown_session" and missing["exit_code"] == 1


def test_parser_and_dispatch_exit_nonzero_with_redacted_output(monkeypatch, tmp_path):
    args = parser().parse_args(["dge", "register", "--file", "p.json"])
    assert args.command == "dge" and args.dge_command == "register" and args.file.name == "p.json"
    submit = parser().parse_args(["dge", "submit", "sess-1", "--file", "e.json"])
    assert submit.session_id == "sess-1" and submit.file.name == "e.json"
    assert parser().parse_args(["dge", "status", "sess-1"]).session_id == "sess-1"
    assert parser().parse_args(["operate", "status", "op-1"]).operation_id == "op-1", "operate is untouched"
    outputs = []
    # S11 M B4: M7 `dge_cli.run(args)` is `entry.cli.dge.run(args)`, which builds its own service first;
    # `composition.build` is patched to return None (the patched `_register`/`_status` never read it).
    monkeypatch.setattr(composition, "build", lambda: None)
    monkeypatch.setattr(cli, "emit", outputs.append)
    monkeypatch.setattr(dge_cli, "_register", lambda service, args: (_ for _ in ()).throw(RuntimeError("dsn=" + CANARY)))
    with pytest.raises(SystemExit) as info:
        dge_cli.run(args)
    assert info.value.code == 1 and outputs[-1] == {"status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}
    monkeypatch.setattr(dge_cli, "_register", lambda service, args: (_ for _ in ()).throw(DgeRefused("packet_conflict")))
    with pytest.raises(SystemExit):
        dge_cli.run(args)
    assert outputs[-1]["reason_code"] == "packet_conflict"
    monkeypatch.setattr(dge_cli, "_status", lambda service, args: {"state": "proposal", "exit_code": 0})
    dge_cli.run(parser().parse_args(["dge", "status", "sess-1"]))
    assert outputs[-1]["state"] == "proposal" and CANARY not in json.dumps(outputs)
    with pytest.raises(ContractError, match="unavailable"):
        operation_documents.read_document(tmp_path / "absent.json", "Research packet")
    bad = tmp_path / "bad.json"
    bad.write_text('{"id": "a", "id": "b"}', encoding="utf-8")
    with pytest.raises(ContractError, match="duplicate JSON key"):
        operation_documents.read_document(bad, "Research packet")
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ContractError, match="not valid JSON"):
        operation_documents.read_document(bad, "Research packet")
    big = tmp_path / "big.json"
    big.write_bytes(b"[" + b"1," * 200000 + b"1]")
    with pytest.raises(ContractError, match="exceeds budget"):
        operation_documents.read_document(big, "Debate event")
    with pytest.raises(PacketError):
        validate_packet({"schema": "x"})
