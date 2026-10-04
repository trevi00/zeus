"""S10 unit C7a: the `entry.cli.operation` helpers, the audit-repair and worker-session roots (DESIGN-s10 §3 C7, R-c11).

Parity with M7 on a disposable PostgreSQL is the `entry.cli_governance.pg` compare family; these tests cover the helpers
(`read_document` against M7's own function when the SOURCE checkout is readable) and the roots' injected seams.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.composition import audit_repair as composition_repair
from codex_harness.composition import cli_sessions
from codex_harness.entry import cli
from codex_harness.entry.cli import audit_repair, operation, worker_session
from codex_harness.kernel.errors import ContractError

CLI_DIR = Path(cli.__file__).resolve().parent
SOURCE = Path("/home/trevi/workspaces/zeus/scratch/m7-source-e38aa722/src")


def dispatch_keys() -> list[str]:
    tree = ast.parse((CLI_DIR / "__init__.py").read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    return [key.value for key in tables[0].value.keys]


def fixtures(tmp_path: Path) -> dict[str, Path]:
    files = {"ok": b'{"a": 1}', "duplicate": b'{"a": 1, "a": 2}', "bom": b'\xef\xbb\xbf{"a": 1}',
             "invalid": b"{not json", "utf16": '{"a": 1}'.encode("utf-16"), "latin": b'{"a": "\xe9"}',
             "budget": b'{"a": "' + b"x" * operation.MAX_MANIFEST_BYTES + b'"}',
             "at_budget": b'{"a": "' + b"x" * (operation.MAX_MANIFEST_BYTES - 9) + b'"}'}
    paths = {}
    for name, body in files.items():
        paths[name] = tmp_path / (name + ".json")
        paths[name].write_bytes(body)
    paths["missing"] = tmp_path / "missing.json"
    return paths


def observed(function, path: Path):
    try:
        return {"value": function(path, "Operation manifest")}
    except ContractError as exc:
        return {"error": str(exc)}


MESSAGES = {"ok": None, "bom": None, "at_budget": None, "duplicate": "Operation manifest has a duplicate JSON key",
            "invalid": "Operation manifest is not valid JSON", "utf16": "Operation manifest is not valid JSON",
            "latin": "Operation manifest is not valid JSON", "budget": "Operation manifest exceeds budget",
            "missing": "Operation manifest unavailable"}


@pytest.mark.parametrize("name", sorted(MESSAGES))
def test_read_document_documented_behaviour(tmp_path, name):
    result = observed(operation.read_document, fixtures(tmp_path)[name])
    if MESSAGES[name] is None:
        assert result["value"]["a"] is not None
    else:
        assert result == {"error": MESSAGES[name]}


def test_read_manifest_names_the_operation_manifest(tmp_path):
    with pytest.raises(ContractError, match=r"^Operation manifest has a duplicate JSON key$"):
        operation.read_manifest(fixtures(tmp_path)["duplicate"])
    assert operation.read_manifest(fixtures(tmp_path)["bom"]) == {"a": 1}
    assert operation.MAX_MANIFEST_BYTES == 256 * 1024


@pytest.mark.skipif(not (SOURCE / "codex_harness" / "adapters" / "operation_cli.py").is_file(), reason="SOURCE checkout not readable")
def test_read_document_equals_m7_on_the_same_files(tmp_path):
    paths = fixtures(tmp_path)
    program = ("import json, sys\n"
               "from pathlib import Path\n"
               "from codex_harness.adapters.operation_cli import read_document\n"
               "from codex_harness.domain.model import ContractError\n"
               "out = {}\n"
               "for name, raw in json.loads(sys.argv[1]).items():\n"
               "    try:\n"
               "        out[name] = {'value': read_document(Path(raw), 'Operation manifest')}\n"
               "    except ContractError as exc:\n"
               "        out[name] = {'error': str(exc), 'cause': type(exc.__cause__).__name__}\n"
               "print(json.dumps(out))\n")
    done = subprocess.run([sys.executable, "-c", program, json.dumps({k: str(v) for k, v in paths.items()})],
                          capture_output=True, text=True, env={"PYTHONPATH": str(SOURCE), "PATH": "/usr/bin:/bin"}, timeout=120)
    assert done.returncode == 0, done.stderr[-400:]
    reference = json.loads(done.stdout)
    assert set(reference) == set(paths)
    for name, path in paths.items():
        mine = observed(operation.read_document, path)
        theirs = {k: v for k, v in reference[name].items() if k != "cause"}
        assert mine == theirs, name


def test_refusal_shapes():
    class Coded(Exception):
        reason_code = "unknown_audit"

    assert operation.refusal(Coded("raw text")) == {"status": "refused", "reason_code": "unknown_audit",
                                                    "error_type": "Coded", "exit_code": 1}
    assert operation.refusal(ContractError("raw text")) == {"status": "refused", "reason_code": "contract_refused",
                                                            "error_type": "ContractError", "exit_code": 1}
    assert operation.refusal(KeyError("raw")) == {"status": "refused", "reason_code": "error", "error_type": "KeyError", "exit_code": 1}


def test_the_dispatch_table_holds_the_two_roots():
    assert {"audit-repair", "worker-session"} <= set(dispatch_keys())


def args(**fields):
    return SimpleNamespace(**fields)


def test_audit_repair_execute_routes_each_command_and_refuses_with_a_code():
    class Owner:
        def enable(self, audit, task, *, operator):
            return {"enabled": [audit, task, operator]}

        def disable(self, audit, *, operator):
            return {"disabled": [audit, operator]}

        def inspect(self, audit, task):
            return {"inspected": [audit, task]}

        def status(self, audit):
            return {"status_of": audit}

    owner = Owner()
    base = {"audit_id": "a", "task_id": "t", "operator": "op"}
    assert audit_repair._execute(None, args(audit_repair_command="enable", **base), repair=owner) == {
        "audit_repair": "enable", "enabled": ["a", "t", "op"], "exit_code": 0}
    assert audit_repair._execute(None, args(audit_repair_command="disable", **base), repair=owner)["disabled"] == ["a", "op"]
    assert audit_repair._execute(None, args(audit_repair_command="inspect", **base), repair=owner)["inspected"] == ["a", "t"]
    assert audit_repair._execute(None, args(audit_repair_command="status", **base), repair=owner)["status_of"] == "a"
    refused = audit_repair._execute(None, args(audit_repair_command="status", **base), repair=SimpleNamespace(status=None))
    assert refused == {"status": "refused", "reason_code": "error", "error_type": "TypeError", "exit_code": 1}


def test_audit_repair_run_exits_one_on_a_refusal_and_prints_a_code(monkeypatch, capsys):
    monkeypatch.setattr("codex_harness.composition.build", lambda: SimpleNamespace(store=None, org=None))

    def fail(service, namespace, repair=None):
        raise RuntimeError("raw message must not leak")

    monkeypatch.setattr(audit_repair, "_execute", fail)
    with pytest.raises(SystemExit) as caught:
        audit_repair.run(args(audit_repair_command="status", audit_id="a"))
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out) == {"status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}
    monkeypatch.setattr(audit_repair, "_execute", lambda service, namespace, repair=None: {"exit_code": 1})
    with pytest.raises(SystemExit):
        audit_repair.run(args(audit_repair_command="status", audit_id="a"))


def test_build_repair_wires_the_target_ports(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path))
    marker = object()
    service = SimpleNamespace(store=marker, org="org")
    owner = composition_repair.build_repair(service, artifacts="art")
    assert (owner.store, owner.org, owner.artifacts) == (marker, "org", "art")
    assert owner.replay.__module__ == "codex_harness.research.adapters.audit_repair" and owner.replay.__name__ == "replay_decode"
    assert owner.outbox is not None and owner.events is not None
    assert owner.notices.__name__ == "codex_harness.coordination.application.execution_notices"
    assert composition_repair.build_repair(service, "art", replay=len).replay is len


def test_worker_session_refusal_is_a_code_and_a_type():
    class Refused(Exception):
        reason = "session_missing"

    assert worker_session._refusal(Refused("a/path/leak")) == {"refused": True, "reason": "session_missing",
                                                               "error_type": "Refused", "exit_code": 1}
    assert worker_session._refusal(ValueError("x"))["reason"] == "error"


def test_worker_session_execute_status_opens_no_evidence_store(monkeypatch):
    seen = {}

    class Sessions:
        def __init__(self, store, archives, evidence=None):
            seen["evidence"] = evidence

        def status(self, task_id):
            return {"task": task_id}

        def close(self, task_id):
            return {"state": "closed", "cleanup": {"archive_retained": True}}

    monkeypatch.setattr(cli_sessions, "worker_sessions", lambda service, archives, evidence=None: Sessions(None, archives, evidence))
    monkeypatch.setattr(cli_sessions, "evidence_store", lambda: pytest.fail("status must not open the evidence store"))
    assert worker_session._execute(None, args(worker_session_command="status", task_id="t"), archives="arch") == {"task": "t", "exit_code": 0}
    assert seen["evidence"] is None
    monkeypatch.setattr(cli_sessions, "evidence_store", lambda: "evidence")
    closed = worker_session._execute(None, args(worker_session_command="close", task_id="t"), archives="arch")
    assert closed == {"closed": True, "task_id": "t", "state": "closed", "archive_retained": True, "exit_code": 0}
    assert seen["evidence"] == "evidence"


def test_the_session_roots_are_under_the_runtime_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path))
    from codex_harness.composition.configuration import runtime_dir
    assert runtime_dir() == tmp_path.resolve()
    assert cli_sessions.archive_root() == tmp_path.resolve() / "worker-sessions"
    assert Path(cli_sessions.evidence_store().root) == runtime_dir() / "artifacts"
    assert Path(cli_sessions.session_archives().root) == runtime_dir() / "worker-sessions"
