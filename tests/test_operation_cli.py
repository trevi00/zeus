"""`zeus operate` adapter and CLI glue (INV-OPERATION-001); git is real, providers are never built."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from codex_harness import cli
from codex_harness.adapters import operation_cli
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.operation import Operation, OperationRefused
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
from codex_harness.domain.operation import validate_manifest

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
    bound = operation_cli.bind_goal(valid, operation_cli.GitSource(root))
    assert bound == {"path": "docs/GOAL.md", "sha256": valid["goal"]["sha256"], "base_revision": head,
                     "criterion": "entry point", "bytes": 7}
    (root / "docs" / "GOAL.md").write_bytes(b"# changed after base\n")  # the working tree may move on
    assert operation_cli.bind_goal(valid, operation_cli.GitSource(root))["sha256"] == valid["goal"]["sha256"]
    with pytest.raises(OperationRefused, match="goal_missing_at_base"):
        operation_cli.bind_goal({**valid, "goal": {**valid["goal"], "path": "docs/OTHER.md"}}, operation_cli.GitSource(root))
    with pytest.raises(OperationRefused, match="base_revision_missing"):
        operation_cli.bind_goal({**valid, "base_revision": "0" * 40}, operation_cli.GitSource(root))
    wrong = validate_manifest({**manifest(head), "goal": {**manifest(head)["goal"], "sha256": "0" * 64}}, packaged_policy())
    with pytest.raises(ContractError, match="do not match"):
        operation_cli.bind_goal(wrong, operation_cli.GitSource(root))


def test_execution_policy_fixes_worker_profile_restricted_and_manifest_controls(tmp_path):
    root, head = repository(tmp_path)
    valid = validate_manifest(manifest(head), packaged_policy())
    policy = operation_cli.execution_policy(valid, {"ZEUS_CLAUDE_EXECUTABLE": "C:/tools/claude.cmd",
                                                    "ZEUS_CLAUDE_MODEL": "claude-host-model", "HARNESS_DATABASE_URL": CANARY})
    assignment = policy.select(role="worker:implementation", action="implement", workload="implementation", read_only=False)
    assert assignment.provider == "claude" and assignment.configured_model == "claude-fixture-model"
    assert assignment.runtime["worker_profile"] == "worker-v1" and assignment.runtime["restricted"] is True
    assert assignment.controls == {"executable": "C:/tools/claude.cmd", "max_budget_usd": 1.5, "timeout_seconds": 120}
    assert packaged_policy().provider("claude").runtime["restricted"] is False, "the packaged default is untouched"
    bound = operation_cli.identity(valid, root, policy, {"HARNESS_DATABASE_URL": CANARY, "HARNESS_REDIS_URL": "redis://x"})
    assert CANARY not in json.dumps(bound) and bound["provider"]["config_digest"] == policy.summary()["config_digest"]
    assert bound["endpoints"]["database"] != bound["endpoints"]["redis"]
    assert operation_cli.identity(valid, root, policy, {"HARNESS_DATABASE_URL": "other"})["endpoints"]["database"] != bound["endpoints"]["database"]


def test_parser_and_dispatch_exit_nonzero_with_redacted_output(monkeypatch):
    args = cli.parser().parse_args(["operate", "run", "--file", "op.json"])
    assert args.command == "operate" and args.operate_command == "run" and args.file.name == "op.json"
    assert cli.parser().parse_args(["operate", "status", "op-1"]).operation_id == "op-1"
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)
    monkeypatch.setattr(operation_cli, "run", lambda service, args: (_ for _ in ()).throw(RuntimeError("dsn=" + CANARY)))
    with pytest.raises(SystemExit) as info:
        cli.operate_command(None, args)
    assert info.value.code == 1 and outputs[-1] == {"status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}
    monkeypatch.setattr(operation_cli, "run", lambda service, args: (_ for _ in ()).throw(OperationRefused("running_residue")))
    with pytest.raises(SystemExit):
        cli.operate_command(None, args)
    assert outputs[-1]["reason_code"] == "running_residue"
    monkeypatch.setattr(operation_cli, "run", lambda service, args: {"status": "rejected", "exit_code": 1})
    with pytest.raises(SystemExit):
        cli.operate_command(None, args)
    monkeypatch.setattr(operation_cli, "run", lambda service, args: {"status": "accepted", "exit_code": 0})
    cli.operate_command(None, args)
    assert outputs[-1]["status"] == "accepted" and CANARY not in json.dumps(outputs)


def test_status_uses_the_store_only(monkeypatch):
    svc = Harness(MemoryStore(), organization())
    with svc.store.transaction() as tx:
        tx.put("operations", "op-1", {"id": "op-1", "status": "failed", "reason_code": "idle", "plan": CANARY,
                                      "manifest_sha256": "m" * 64, "calls": {"reserved": 0}})
    for name in ("build_executor", "build_observer"):
        monkeypatch.setattr("codex_harness.bootstrap." + name, lambda *a, **k: pytest.fail(name + " built for status"))
    view = operation_cli.status(svc, SimpleNamespace(operation_id="op-1"))
    assert view["status"] == "failed" and view["reason_code"] == "idle" and CANARY not in json.dumps(view)
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)
    cli.operate_command(svc, cli.parser().parse_args(["operate", "status", "op-1"]))
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
