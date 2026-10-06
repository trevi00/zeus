# Ported from SOURCE M7 tests/test_operation_cli.py (REBUILD-DESIGN-v2 §3.1 target tests): only the import paths
# are rewritten to the target tree; assertions are unchanged unless a comment below names the adaptation.
"""`zeus operate` adapter and CLI glue (INV-OPERATION-001); git is real, providers are never built."""
import hashlib
import json
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest
from m7_research import Harness, Operation, organization, packaged_policy

from codex_harness import composition
from codex_harness.composition import cli_operation
from codex_harness.composition import operation as composition_operation
from codex_harness.coordination.application.operation import OperationRefused
from codex_harness.coordination.domain.operation import validate_manifest
from codex_harness.entry.cli import dge as dge_cli
from codex_harness.entry.cli import operate, parser

# S11 M B4: M7 `operation_cli` is split: `read_manifest`, `read_document`, `refusal`, `MAX_MANIFEST_BYTES` are entry.cli.operation's
# (`operation_cli` here); `bind_goal`, `execution_policy`, `identity` are composition.cli_operation's; `GitSource` is host_os's;
# `run`/`status` are the private `_run`/`_status` of entry.cli.operate; `cli` is entry.cli.output (M7 `cli.emit`).
from codex_harness.entry.cli import operation as operation_cli
from codex_harness.entry.cli import output as cli
from codex_harness.host_os.adapters.git_source import GitSource
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.storage.adapters.memory_store import MemoryStore

CANARY = "CANARY-must-never-be-emitted"


def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "GOAL.md").write_bytes(b"# goal\n")
    for argv in (["init", "-q", "-b", "main"], ["add", "--all"],
                 ["-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "goal"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    return root, head


def manifest(head):
    return {"schema": "urn:zeus:operation:1", "id": "op-cli", "base_revision": head,
            "goal": {"path": "docs/GOAL.md", "sha256": hashlib.sha256(b"# goal\n").hexdigest(),
                     "criterion": "entry point", "rationale": CANARY},
            "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": ["docs/RUNBOOK.md"]},
            "budget": {"per_host": 2, "total": 4},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.5}}


def test_git_source_binds_goal_bytes_at_base_and_refuses_mismatch(tmp_path):
    root, head = repository(tmp_path)
    valid = validate_manifest(manifest(head), packaged_policy())
    bound = cli_operation.bind_goal(valid, GitSource(root))
    assert bound == {"path": "docs/GOAL.md", "sha256": valid["goal"]["sha256"], "base_revision": head,
                     "criterion": "entry point", "bytes": 7}
    (root / "docs" / "GOAL.md").write_bytes(b"# changed after base\n")  # the working tree may move on
    assert cli_operation.bind_goal(valid, GitSource(root))["sha256"] == valid["goal"]["sha256"]
    with pytest.raises(OperationRefused, match="goal_missing_at_base"):
        cli_operation.bind_goal({**valid, "goal": {**valid["goal"], "path": "docs/OTHER.md"}}, GitSource(root))
    with pytest.raises(OperationRefused, match="base_revision_missing"):
        cli_operation.bind_goal({**valid, "base_revision": "0" * 40}, GitSource(root))
    wrong = validate_manifest({**manifest(head), "goal": {**manifest(head)["goal"], "sha256": "0" * 64}}, packaged_policy())
    with pytest.raises(ContractError, match="do not match"):
        cli_operation.bind_goal(wrong, GitSource(root))


def test_execution_policy_fixes_worker_profile_restricted_and_manifest_controls(tmp_path):
    root, head = repository(tmp_path)
    valid = validate_manifest(manifest(head), packaged_policy())
    policy = cli_operation.execution_policy(valid, {"ZEUS_CLAUDE_EXECUTABLE": "C:/tools/claude.cmd",
                                                    "ZEUS_CLAUDE_MODEL": "claude-host-model", "HARNESS_DATABASE_URL": CANARY})
    assignment = policy.select(role="worker:implementation", action="implement", workload="implementation", read_only=False)
    assert assignment.provider == "claude" and assignment.configured_model == "claude-fixture-model"
    assert assignment.runtime["worker_profile"] == "worker-v1" and assignment.runtime["restricted"] is True
    assert assignment.controls == {"executable": "C:/tools/claude.cmd", "max_budget_usd": 1.5, "timeout_seconds": 120}
    assert packaged_policy().provider("claude").runtime["restricted"] is False, "the packaged default is untouched"
    host = {"HARNESS_DATABASE_URL": CANARY, "HARNESS_REDIS_URL": "redis://x"}
    bound = cli_operation.identity(valid, root, policy, host, tmp_path / "runtime-a")
    assert CANARY not in json.dumps(bound) and bound["provider"]["config_digest"] == policy.summary()["config_digest"]
    assert bound["endpoints"]["database"] != bound["endpoints"]["redis"]
    assert cli_operation.identity(valid, root, policy, {"HARNESS_DATABASE_URL": "other"}, tmp_path / "runtime-a")["endpoints"]["database"] != bound["endpoints"]["database"]
    # R3: the effective resolved runtime directory is part of the identity; the path itself is not stored.
    moved = cli_operation.identity(valid, root, policy, host, tmp_path / "runtime-b")
    assert moved["runtime"] != bound["runtime"] and {k: v for k, v in moved.items() if k != "runtime"} == {k: v for k, v in bound.items() if k != "runtime"}
    assert cli_operation.identity(valid, root, policy, host, tmp_path / "x" / ".." / "runtime-a")["runtime"] == bound["runtime"]
    assert str(tmp_path) not in json.dumps(bound)
    svc = Harness(MemoryStore(), organization())
    goal = cli_operation.bind_goal(valid, GitSource(root))
    assert Operation(svc).claim(valid, bound, goal)["cached"] is False
    with pytest.raises(OperationRefused, match="configuration_mismatch"):
        Operation(svc).claim(valid, moved, goal)


def test_build_executor_opt_out_wires_no_knowledge_adapter_and_default_is_unchanged(tmp_path, monkeypatch):
    from codex_harness.knowledge.adapters import postgres_knowledge as knowledge_module
    root, _ = repository(tmp_path)
    monkeypatch.setenv("ZEUS_REPOSITORY", str(root))
    # S11 M B4 (R-M2, OWNER-DECISIONS-S10 #10): the target refuses an absent composition profile (no default); the test names one.
    monkeypatch.setenv("ZEUS_COMPOSITION_PROFILE", "development")
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", ".runtime-test")
    monkeypatch.delenv("HARNESS_DATABASE_URL", raising=False)
    svc = Harness(MemoryStore(), organization())
    assert callable(getattr(knowledge_module.PostgresKnowledge, "index_python")) and callable(
        getattr(knowledge_module.PostgresKnowledge, "project_runtime")), "the default adapter is writable"
    built = []
    monkeypatch.setattr(knowledge_module, "PostgresKnowledge", lambda dsn: built.append(dsn) or SimpleNamespace(dsn=dsn))
    executor = composition_operation.build_executor(svc, knowledge=False)
    assert isinstance(executor, composition_operation.Executor) and executor.knowledge is None and built == []
    assert not hasattr(executor.knowledge, "index_python") and not hasattr(executor.knowledge, "project_runtime")
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql://fixture")
    assert composition_operation.build_executor(svc).knowledge.dsn == "postgresql://fixture" and built == ["postgresql://fixture"]


def test_operate_run_builds_the_real_executor_without_knowledge_and_binds_the_runtime(tmp_path, monkeypatch):
    from codex_harness.execution.adapters import call_budget as budget_module
    from codex_harness.knowledge.adapters import postgres_knowledge as knowledge_module
    from codex_harness.storage.adapters import redis_bus as bus_module
    root, head = repository(tmp_path)
    monkeypatch.setenv("ZEUS_REPOSITORY", str(root))
    # S11 M B4 (R-M2, OWNER-DECISIONS-S10 #10): the target refuses an absent composition profile (no default); the test names one.
    monkeypatch.setenv("ZEUS_COMPOSITION_PROFILE", "development")
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", ".runtime-test")
    monkeypatch.setenv("ZEUS_CLAUDE_EXECUTABLE", "C:/tools/claude.cmd")
    monkeypatch.delenv("HARNESS_DATABASE_URL", raising=False)
    monkeypatch.setattr(knowledge_module, "PostgresKnowledge", lambda dsn: pytest.fail("operate wired a writable knowledge adapter"))
    # S11 M B4: the target bus is `RedisBus(url, namespace)` (composition.cli_bus.bus).
    monkeypatch.setattr(bus_module, "RedisBus", lambda url, *args, **kwargs: SimpleNamespace(url=url))
    monkeypatch.setattr(budget_module, "CallBudget", lambda: SimpleNamespace(kind="budget"))
    wired = {}

    class Recorder:
        # S11 M B4: the target `Operation` is built by composition.cli_operation.operation as `Operation(store, org, flusher=...,
        # executor=, bus=, workflow=, budget=, collector=, observer=, ...)`; the recorder takes those keywords.
        def __init__(self, store, org, *, executor, bus, workflow, budget, collector, observer=None, **ports):
            wired.update(executor=executor, bus=bus, budget=budget, collector=collector, observer=observer)

        def run(self, manifest, identity, goal):
            wired.update(identity=identity, goal=goal)
            return {"status": "failed", "reason_code": "fixture", "exit_code": 1}
    # S11 M B4: `Operation` is looked up by composition.cli_operation.operation in coordination.application.operation.
    monkeypatch.setattr("codex_harness.coordination.application.operation.Operation", Recorder)
    path = tmp_path / "op.json"
    path.write_text(json.dumps(manifest(head)), encoding="utf-8")
    receipt = operate._run(Harness(MemoryStore(), organization()), SimpleNamespace(file=path))
    assert receipt["exit_code"] == 1 and isinstance(wired["executor"], composition_operation.Executor) and wired["executor"].knowledge is None
    assert wired["identity"]["runtime"] == digest(str((root / ".runtime-test").resolve())) and wired["goal"]["base_revision"] == head
    assert wired["bus"].url and wired["budget"].kind == "budget"
    assert wired["observer"] is wired["executor"].observer is wired["collector"].observer


def test_parser_and_dispatch_exit_nonzero_with_redacted_output(monkeypatch):
    args = parser().parse_args(["operate", "run", "--file", "op.json"])
    assert args.command == "operate" and args.operate_command == "run" and args.file.name == "op.json"
    assert parser().parse_args(["operate", "status", "op-1"]).operation_id == "op-1"
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)
    # S11 M B4: M7 `operate.run(args)` is `entry.cli.operate.run(args)`, which builds its own service first;
    # `composition.build` is patched to return None (the patched `_run` never reads it).
    monkeypatch.setattr(composition, "build", lambda: None)
    monkeypatch.setattr(operate, "_run", lambda service, args: (_ for _ in ()).throw(RuntimeError("dsn=" + CANARY)))
    with pytest.raises(SystemExit) as info:
        operate.run(args)
    assert info.value.code == 1 and outputs[-1] == {"status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}
    monkeypatch.setattr(operate, "_run", lambda service, args: (_ for _ in ()).throw(OperationRefused("running_residue")))
    with pytest.raises(SystemExit):
        operate.run(args)
    assert outputs[-1]["reason_code"] == "running_residue"
    monkeypatch.setattr(operate, "_run", lambda service, args: {"status": "rejected", "exit_code": 1})
    with pytest.raises(SystemExit):
        operate.run(args)
    monkeypatch.setattr(operate, "_run", lambda service, args: {"status": "accepted", "exit_code": 0})
    operate.run(args)
    assert outputs[-1]["status"] == "accepted" and CANARY not in json.dumps(outputs)


def test_status_uses_the_store_only(monkeypatch):
    svc = Harness(MemoryStore(), organization())
    with svc.store.transaction() as tx:
        tx.put("operations", "op-1", {"id": "op-1", "status": "failed", "reason_code": "idle", "plan": CANARY,
                                      "manifest_sha256": "m" * 64, "calls": {"reserved": 0}})
    # S11 M B4: the must-not-be-built guards are on the target homes (composition builders).
    for name in ("operation.build_executor", "observation.build_observer"):
        monkeypatch.setattr("codex_harness.composition." + name, lambda *a, **k: pytest.fail(name + " built for status"))
    view = operate._status(svc, SimpleNamespace(operation_id="op-1"))
    assert view["status"] == "failed" and view["reason_code"] == "idle" and CANARY not in json.dumps(view)
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)
    monkeypatch.setattr(composition, "build", lambda: svc)  # S11 M B4: `operate.run` builds its own service
    operate.run(parser().parse_args(["operate", "status", "op-1"]))
    assert outputs[-1]["id"] == "op-1"
    assert operation_cli.refusal(ContractError(CANARY)) == {"status": "refused", "reason_code": "contract_refused",
                                                             "error_type": "ContractError", "exit_code": 1}


def test_read_manifest_refuses_missing_oversized_and_invalid_json(tmp_path):
    with pytest.raises(ContractError, match="unavailable"):
        operation_cli.read_manifest(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ContractError, match="not valid JSON"):
        operation_cli.read_manifest(bad)
    big = tmp_path / "big.json"
    big.write_bytes(b"[" + b"1," * 200000 + b"1]")
    with pytest.raises(ContractError, match="exceeds budget"):
        operation_cli.read_manifest(big)
    assert Operation(Harness(MemoryStore(), organization())).__class__ is Operation


def test_read_manifest_refuses_malformed_encodings_and_duplicate_keys_as_contract_errors(tmp_path):
    """Operator bytes never escape read_manifest as UnicodeDecodeError: one strict shared reader."""
    bom = b"\xef\xbb\xbf"
    path = tmp_path / "manifest.json"
    for content, label in ((b'{"a": "\xff"}', "not valid JSON"),
                           (b'{"id": "\xff\xfe"}', "not valid JSON"),
                           ('{"id": "a"}'.encode("utf-16"), "not valid JSON"),
                           ('{"id": "a"}'.encode("utf-16-be"), "not valid JSON"),
                           (bom + bom + b'{"id": "a"}', "not valid JSON"),
                           (b'{"id": "a", "id": "b"}', "Operation manifest has a duplicate JSON key"),
                           (bom + b'{"id": "a", "id": "b"}', "duplicate JSON key")):
        path.write_bytes(content)
        with pytest.raises(ContractError, match=label):
            operation_cli.read_manifest(path)
    path.write_bytes(bom + b'{"note": "a' + bom + b'b"}')  # interior U+FEFF is data
    assert operation_cli.read_manifest(path) == {"note": "a\N{ZERO WIDTH NO-BREAK SPACE}b"}
    body = b'["' + b"a" * (operation_cli.MAX_MANIFEST_BYTES - 4) + b'"]'
    path.write_bytes(body)
    assert operation_cli.read_manifest(path) == ["a" * (operation_cli.MAX_MANIFEST_BYTES - 4)]
    path.write_bytes(bom + body)  # the raw byte budget counts the BOM
    with pytest.raises(ContractError, match="Operation manifest exceeds budget"):
        operation_cli.read_manifest(path)
    with pytest.raises(ContractError, match="Operation manifest unavailable"):
        operation_cli.read_manifest(tmp_path / "absent.json")


def test_read_manifest_accepts_one_leading_bom_and_keeps_the_validated_manifest(tmp_path):
    """BOM/no BOM x LF/CRLF x non-ASCII text parse to the same document and validated manifest."""
    document = manifest("a" * 40)
    document["goal"]["rationale"] = "운영자 매니페스트"
    text = json.dumps(document, ensure_ascii=False, indent=2)
    baseline = validate_manifest(document, packaged_policy())
    for bom in (False, True):
        for crlf in (False, True):
            path = tmp_path / ("m-%d%d.json" % (bom, crlf))
            path.write_bytes((b"\xef\xbb\xbf" if bom else b"")
                             + (text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            parsed = operation_cli.read_manifest(path)
            assert parsed == document
            assert validate_manifest(parsed, packaged_policy()) == baseline


def test_dge_read_document_is_the_shared_operation_reader():
    # S11 M B4: entry.cli.dge has no `read_document`/`MAX_DOCUMENT_BYTES` names (it imports the reader from entry.cli.operation
    # when it runs), so M7's attribute identity is asserted by behaviour: replacing entry.cli.operation.read_document is seen by
    # the `register` and `submit` bodies of dge, and the budget is entry.cli.operation's 256 KiB.
    seen = []

    def shared(path, label):
        seen.append(label)
        raise ContractError("shared reader reached")
    with mock.patch.object(operation_cli, "read_document", shared):
        for body, args in ((dge_cli._register, SimpleNamespace(file="p.json")),
                           (dge_cli._submit, SimpleNamespace(file="e.json", session_id="s"))):
            with pytest.raises(ContractError, match="shared reader reached"):
                body(None, args)
    assert seen == ["Research packet", "Debate event"]
    assert operation_cli.MAX_MANIFEST_BYTES == 256 * 1024
