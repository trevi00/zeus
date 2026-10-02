"""S8 pilot 90 (DESIGN-s8 §12.1 V17 P-b): the M7 `adapters/frontdesk.py` is split by owner: the execute side is
`intake.adapters.frontdesk`, the monitoring evidence is `observation.adapters.desk_monitoring`. Everything but the named rules is M7's
(A/evidence/rebuild/s8/frontdesk-adapter-move/transcribe.py).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the `intake.frontdesk_adapter` golden, whose two intended differences
(`snapshot=None` is refused, the default path is gone) are pinned here.
"""
import ast
import importlib
import inspect
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.kernel.errors import ContractError

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
M7_PATH = "src/codex_harness/adapters/frontdesk.py"
FRONT = "codex_harness.intake.adapters.frontdesk"
MON = "codex_harness.observation.adapters.desk_monitoring"
EXEC_NAMES = {("TEXT",), ("STRINGS",), ("DESK_PROPERTIES",), ("DESK_OUTPUT",), ("PROMPT",), ("clean_checkout",), ("execute_frontdesk",)}
NOW = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
REVISION = "0" * 39 + "a"
SUPPLIED = "desk monitoring evidence must be supplied"


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text(module):
    return Path(importlib.import_module(module).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def function(src, name):
    return next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)


def imported(module):
    return {n.module: sorted(a.name for a in n.names) for n in ast.walk(ast.parse(target_text(module))) if isinstance(n, ast.ImportFrom)
            and n.module.startswith(("codex_harness.", "datetime"))}


def dumped(nodes):
    return [ast.dump(n) for n in nodes]


def test_the_two_modules_partition_m7_in_order_and_everything_but_the_named_rules_is_m7():
    ref, front, mon = statements(m7_text()), statements(target_text(FRONT)), statements(target_text(MON))
    assert set(front) == EXEC_NAMES | {("__all__",)}
    assert set(ref) == set(front) | set(mon) | {("snapshot_path",)}
    assert not (set(front) & set(mon)) - {("__all__",)}
    assert [k for k in ref if k in front] == [k for k in front]  # M7 order is kept inside each module
    assert [k for k in ref if k in mon] == [k for k in mon]
    rewritten = {("__all__",), ("execute_frontdesk",), ("monitoring_evidence",)}
    for ours in (front, mon):
        for key, node in ours.items():
            if key not in rewritten:
                assert ast.dump(node) == ast.dump(ref[key]), key
    assert len(ref) == 30 and len(front) == 8 and len(mon) == 22  # 30 = 7 execute + 21 monitoring + snapshot_path + `__all__`; each module has its own `__all__`


def test_r_f1_only_the_self_read_statement_is_replaced_by_a_require_and_an_assignment():
    ref, ours = function(m7_text(), "execute_frontdesk"), function(target_text(FRONT), "execute_frontdesk")
    assert ast.dump(ref.args) == ast.dump(ours.args) and ast.dump(ref.returns) == ast.dump(ours.returns)
    index = next(i for i, n in enumerate(ref.body) if isinstance(n, ast.Assign) and n.targets[0].id == "facts")
    assert ast.unparse(ref.body[index]) == "facts = monitoring_evidence() if snapshot is None else snapshot"
    assert dumped(ours.body[:index]) == dumped(ref.body[:index]) and dumped(ours.body[index + 2:]) == dumped(ref.body[index + 1:])
    assert [ast.unparse(n) for n in ours.body[index:index + 2]] == [f"require(snapshot is not None, '{SUPPLIED}')", "facts = snapshot"]
    assert [a.arg for a in ours.args.args] == ["executor", "task", "heartbeat", "snapshot"] and [d.value for d in ours.args.defaults] == [None, None]


def test_r_m1_the_path_is_required_and_the_default_path_is_gone():
    ref, ours = function(m7_text(), "monitoring_evidence"), function(target_text(MON), "monitoring_evidence")
    assert [a.arg for a in ref.args.args] == ["path", "now"] and len(ref.args.defaults) == 2
    assert [a.arg for a in ours.args.args] == ["path", "now"] and [d.value for d in ours.args.defaults] == [None]  # `now` only
    outer_ref, outer_ours = ref.body[1], ours.body[1]
    assert ast.unparse(outer_ref.body[0]) == "path = path if path is not None else snapshot_path()"
    assert dumped(outer_ours.body) == dumped(outer_ref.body[1:]) and dumped(outer_ours.handlers) == dumped(outer_ref.handlers)
    assert dumped(ours.body[:1]) == dumped(ref.body[:1])
    mon = importlib.import_module(MON)
    assert not hasattr(mon, "snapshot_path") and not hasattr(importlib.import_module(FRONT), "snapshot_path")
    assert "snapshot_path" not in target_text(MON).split('"""', 2)[2].replace("snapshot_path()` is removed", "")
    assert "runtime_dir" not in target_text(MON).split('"""', 2)[2] and "runtime_dir" not in target_text(FRONT).split('"""', 2)[2]


def test_imports_are_only_the_v17_homes_and_each_name_is_bound_once():
    assert imported(FRONT) == {"codex_harness.intake.application.frontdesk": ["FrontDesk"],
                               "codex_harness.intake.domain.frontdesk": ["DeskRefused", "revision", "validate_answer"],
                               "codex_harness.kernel.errors": ["require"]}
    assert imported(MON) == {"datetime": ["datetime", "timezone"], "codex_harness.intake.domain.frontdesk": ["safe_code"],
                             "codex_harness.observation.adapters": ["monitoring_readiness"]}
    for module in (FRONT, MON):
        text = target_text(module)
        assert "codex_harness.domain" not in text.replace("codex_harness.intake.domain", "") and "codex_harness.adapters" not in text


def test_headers_name_context_layer_the_split_and_the_rules():
    for module, context, entry, rules in ((FRONT, "intake", "execute_frontdesk, clean_checkout, PROMPT, DESK_OUTPUT", "R-f0"),
                                          (MON, "observation", "monitoring_evidence, monitoring_facts", "R-m0")):
        head = target_text(module).split('"""')[1]
        assert f"Layer: adapters\nContext: {context}\n" in head and "Contracts: local-operations-desk-001" in head
        assert "SOURCE e38aa722" in head and "V17" in head and "frontdesk-adapter-move/transcribe.py" in head and rules in head
        assert f"Entry points: {entry}" in head
    assert "R-m1" in target_text(MON).split('"""')[1] and "R-f1" in target_text(FRONT).split('"""')[1]


def test_all_lists_what_each_module_defines_and_no_module_lists_the_removed_path():
    for module, names in ((FRONT, ["DESK_OUTPUT", "PROMPT", "clean_checkout", "execute_frontdesk"]),
                          (MON, ["ACCOUNTING_NOTE", "FRESH_SECONDS", "MONITORING_SCHEMA", "monitoring_evidence", "monitoring_facts"])):
        loaded = importlib.import_module(module)
        assert loaded.__all__ == names and all(hasattr(loaded, n) for n in names)


def test_the_monitoring_side_reuses_the_readiness_constants_and_has_one_bounded_read_and_no_write():
    mon = importlib.import_module(MON)
    readiness = importlib.import_module("codex_harness.observation.adapters.monitoring_readiness")
    assert mon.readiness is readiness
    assert (mon.MONITORING_MAX_BYTES, mon.FRESH_SECONDS, mon.FUTURE_TOLERANCE_SECONDS) == (readiness.MAX_SNAPSHOT_BYTES, 20, 5) == (5_000_000, 20, 5)
    assert (mon.MONITORING_SCHEMA, mon.MONITORING_FILE, mon.JOB_LIMIT, mon.LANE_LIMIT) == ("urn:zeus:desk-monitoring:1", "monitoring.json", 200, 64)
    body = target_text(MON).split('"""', 2)[2]
    assert body.count("open(") == 1 and '"rb"' in body and body.count(".read(") == 1
    for word in (".write", "subprocess", "socket", "psycopg", "os.", "Path", "environ"):
        assert word not in body, word


def test_the_execute_side_has_no_monitoring_names_and_the_prompt_and_schema_are_m7_s():
    front = importlib.import_module(FRONT)
    names = {n.id for n in ast.walk(ast.parse(target_text(FRONT))) if isinstance(n, ast.Name)}
    forbidden = {"monitoring_evidence", "monitoring_facts", "readiness", "safe_code", "datetime", "timezone", "FRESH_SECONDS", "ACCOUNTING_NOTE",
                 "MONITORING_SCHEMA", "MONITORING_FILE", "MONITORING_MAX_BYTES", "snapshot_path", "runtime_dir"}
    assert not names & forbidden
    assert front.DESK_OUTPUT["required"] == list(front.DESK_OUTPUT["properties"]) == ["answer", "objective", "acceptance_criteria", "questions"]
    assert front.DESK_OUTPUT["additionalProperties"] is False and front.DESK_OUTPUT["properties"]["objective"]["type"] == ["string", "null"]
    assert front.PROMPT.startswith("You are the local operations desk of this Zeus checkout.")


# ---- behaviour over literals ------------------------------------------------------------------------------------------
class FakeGit:
    def __init__(self, revision=REVISION, dirty=False):
        self.revision, self.dirty, self.workspaces = revision, dirty, []

    def review_workspace(self, revision, review_id):
        self.workspaces.append((revision, review_id))
        return "/tmp/review-" + review_id

    def _git(self, *args, cwd=None, strip=True):
        if args[:2] == ("rev-parse", "HEAD"):
            return self.revision
        assert args[0] == "status", args
        return "M file.py" if self.dirty else ""


def turn():
    """A real desk (the moved FrontDesk with the real outbox owner) over a memory store, one submitted request and its assignment."""
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.intake.application.frontdesk import FrontDesk, message_id_of
    from codex_harness.routing.adapters.organization_source import packaged_organization
    from codex_harness.storage.adapters.memory_store import MemoryStore

    service = SimpleNamespace(store=MemoryStore(), org=packaged_organization())
    desk = FrontDesk(service, REVISION, outbox=Outbox())
    session_id = "123e4567-e89b-42d3-a456-426614174000"
    desk.create_session({"session_id": session_id, "title": "t"})
    request_id = "223e4567-e89b-42d3-a456-426614174000"
    desk.submit({"session_id": session_id, "request_id": request_id, "intent": "consult", "text": "hello"})
    with service.store.transaction() as tx:
        message = tx.get("outbox", message_id_of(request_id))["message"]
    return service, request_id, {"id": message["message_id"], "message": message}


def executor(service, calls, git=None):
    def run(agent, key, objective, evidence, cwd, schema, read_only=False, heartbeat=None, lease=None, stage=None, workload="final_validation",
            importance=None, action=None, max_handoffs=4, delivery=None):
        calls.append({"agent": agent, "evidence": evidence, "cwd": cwd, "read_only": read_only, "action": action, "max_handoffs": max_handoffs})
        return {"answer": "ok", "objective": None, "acceptance_criteria": [], "questions": [], "execution_ref": "sha256:" + "b" * 64}

    return SimpleNamespace(service=service, git=git or FakeGit(), _run=run)


@pytest.mark.parametrize("kwargs", [{}, {"snapshot": None}])
def test_r_f1_a_missing_snapshot_is_refused_before_any_workspace_run_or_write_and_never_self_read(kwargs):
    from codex_harness.intake.adapters.frontdesk import execute_frontdesk

    service, _request_id, task = turn()
    with service.store.transaction() as tx:
        before = tx.records()
    calls, git = [], FakeGit()
    with pytest.raises(ContractError, match=SUPPLIED):
        execute_frontdesk(executor(service, calls, git), task, None, **kwargs)
    assert calls == [] and git.workspaces == []
    with service.store.transaction() as tx:
        assert tx.records() == before


def test_the_supplied_evidence_is_the_snapshot_and_the_turn_runs_read_only_in_a_clean_checkout(tmp_path):
    from codex_harness.intake.adapters.frontdesk import execute_frontdesk
    from codex_harness.observation.adapters.desk_monitoring import monitoring_evidence

    service, request_id, task = turn()
    path = tmp_path / "monitoring.json"
    path.write_text(json.dumps(document(NOW - timedelta(seconds=10))), "utf-8")
    facts = monitoring_evidence(path, now=NOW)
    calls, git = [], FakeGit()
    result = execute_frontdesk(executor(service, calls, git), task, "beat", snapshot=facts)
    assert git.workspaces == [(REVISION, "desk-" + request_id)] and len(calls) == 1
    call = calls[0]
    assert call["evidence"]["fleet_snapshot"] is facts and call["read_only"] is True and call["action"] == "frontdesk" and call["max_handoffs"] == 1
    assert call["agent"] == "lead:frontdesk" and call["cwd"] == "/tmp/review-desk-" + request_id
    assert result["frontdesk"] == {"request_id": request_id, "session_id": "123e4567-e89b-42d3-a456-426614174000", "intent": "consult",
                                   "base_revision": REVISION}
    assert facts["availability"] == "observed" and facts["freshness"] == "current" and facts["age_seconds"] == 10
    # a falsy but supplied snapshot is the evidence too (`is not None`, never truthiness)
    service, _request_id, task = turn()
    calls = []
    execute_frontdesk(executor(service, calls), task, None, snapshot={})
    assert calls[0]["evidence"]["fleet_snapshot"] == {}


@pytest.mark.parametrize("git, message", [(FakeGit(dirty=True), "dirty"), (FakeGit(revision="b" * 40), "revision changed")])
def test_clean_checkout_refuses_a_dirty_or_moved_tree(git, message):
    from codex_harness.intake.adapters.frontdesk import clean_checkout, execute_frontdesk

    with pytest.raises(ContractError, match=message):
        clean_checkout(git, "/tmp/w", REVISION)
    service, _request_id, task = turn()
    calls = []
    with pytest.raises(ContractError, match=message):
        execute_frontdesk(executor(service, calls, git), task, None, snapshot={"marker": 1})
    assert calls == []


def document(collected, **sources):
    stamp = collected.isoformat()
    envelope = {"status": "ok", "observed_at": stamp, "data": {}}
    return {"schema": "harness-monitor.v1", "collected_at": stamp, "scope": {"label": "repository zeus"},
            "sources": {"database": envelope, "docker": envelope, "redis": envelope, **sources}}


def test_r_m1_monitoring_evidence_requires_the_path_and_never_falls_back_to_a_runtime_file(tmp_path, monkeypatch):
    from codex_harness.observation.adapters.desk_monitoring import monitoring_evidence

    assert [p.name for p in inspect.signature(monitoring_evidence).parameters.values()] == ["path", "now"]
    assert inspect.signature(monitoring_evidence).parameters["path"].default is inspect.Parameter.empty
    with pytest.raises(TypeError, match="path"):
        monitoring_evidence()
    # an explicit None is an unusable path: explicit unknown evidence, never a default file read
    monkeypatch.chdir(tmp_path)
    (tmp_path / "monitoring.json").write_text(json.dumps(document(NOW)), "utf-8")
    unknown = monitoring_evidence(None, now=NOW)
    assert unknown["availability"] == "unknown" and unknown["reason_code"] == "snapshot_unavailable"


def test_monitoring_evidence_over_files_is_the_m7_rule(tmp_path, monkeypatch):
    from codex_harness.observation.adapters import desk_monitoring as mon

    def read(body, now=NOW):
        path = tmp_path / "monitoring.json"
        path.write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode())
        return mon.monitoring_evidence(path, now=now)

    fresh = read(document(NOW - timedelta(seconds=19)))
    assert (fresh["freshness"], fresh["basis"], fresh["age_seconds"], fresh["freshness_bound_seconds"]) == ("current", "current_capture", 19, 20)
    stale = read(document(NOW - timedelta(seconds=30)))
    assert (stale["freshness"], stale["basis"], stale["freshness_reason"], stale["age_seconds"]) == ("stale", "historical_capture", "older_than_window", 30)
    assert stale["collected_at"] == (NOW - timedelta(seconds=30)).isoformat() and stale["fleet"] is not None
    ahead = read(document(NOW + timedelta(seconds=60)))
    assert (ahead["freshness"], ahead["freshness_reason"]) == ("unknown", "timestamp_in_future")
    assert mon.monitoring_evidence(tmp_path / "none.json", now=NOW)["reason_code"] == "snapshot_missing"
    assert mon.monitoring_evidence(tmp_path, now=NOW)["reason_code"] == "snapshot_unreadable"
    for body, code in ((b"{not json", "snapshot_unreadable"), (b'{"a": 1, "a": 2}', "snapshot_unreadable"), (b'{"a": NaN}', "snapshot_unreadable"),
                       (b"[]", "snapshot_invalid"), (b'{"schema": "x", "sources": {}}', "schema_unexpected"),
                       (b'{"schema": "harness-monitor.v1"}', "sources_unexpected")):
        unknown = read(body)
        assert (unknown["availability"], unknown["reason_code"], unknown["freshness"], unknown["basis"]) == ("unknown", code, "unknown", "capture_time_unknown")
    monkeypatch.setattr(mon, "MONITORING_MAX_BYTES", 10)
    assert read(document(NOW))["reason_code"] == "snapshot_too_large"
    # a naive `now` is a caller error that surfaces as unknown evidence, never as a raised turn failure
    monkeypatch.undo()
    assert read(document(NOW), now=datetime(2026, 9, 19, 12))["reason_code"] == "snapshot_unavailable"


def test_monitoring_facts_are_sanitized_and_state_the_accounting_modes():
    from codex_harness.observation.adapters.desk_monitoring import ACCOUNTING_NOTE, monitoring_facts

    fleet = {"status": "ok", "observed_at": NOW.isoformat(), "data": {
        "registered": True, "paused": False, "max_parallel": 2, "accounting_mode": "subscription", "budget": {"per_host": 192, "mode": "subscription"},
        "lanes": [{"id": "a", "active_job": "j"}, {"id": "b", "active_job": None}],
        "jobs": [{"status": "running", "operation_id": "op-1", "goal": {"path": "docs/zeus/operations/secret-plan/SPEC.md"}}]}}
    facts = monitoring_facts(document(NOW - timedelta(seconds=10), fleet=fleet), now=NOW)
    assert facts["fleet"] == {"availability": "observed", "registered": True, "paused": False, "accounting_mode": "subscription",
                              "accounting_note": ACCOUNTING_NOTE["subscription"], "max_parallel": 2, "lanes": 2, "active_lanes": 1, "sampled_jobs": 1,
                              "sampled_jobs_by_status": {"running": 1}, "jobs_truncated": None}
    flat = json.dumps(facts)
    assert not any(word in flat for word in ("secret-plan", "op-1", "per_host", "192"))
    assert facts["sources"]["docker"]["freshness"] == "current" and facts["observations"]["availability"] == "unknown"
    assert monitoring_facts("not a snapshot", now=NOW)["reason_code"] == "snapshot_invalid"
