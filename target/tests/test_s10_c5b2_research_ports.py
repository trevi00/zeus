"""S10 C5b-2: the research and role ports of `composition.operation.Executor` (OWNER-DECISIONS-S10 #2, #9) and the
connections-inventory check of the objects it builds.

No provider is called (the root conftest's provider guard stays on): MemoryStore, a monkeypatched host settings."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import configuration, operation
from codex_harness.coordination.application import execution_notices
from codex_harness.coordination.application.decisions import DecisionOwnership
from codex_harness.research.adapters import autonomous_roles, correction_feedback
from codex_harness.research.adapters.audit_execution import AuditExecution
from codex_harness.research.adapters.audit_runner import AuditRunner
from codex_harness.research.adapters.council_composition import CouncilCompositionAdmission
from codex_harness.research.application.research import ResearchAudits
from codex_harness.review.application import decisions as review_decisions
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

FIXTURE = Path(__file__).parent / "fixtures" / "s10_connections_subset.json"

# (function, parameter) -> why the built object legitimately holds None here.
ALLOWED_NONE = {
    ("RunTask.__init__", "research_admission"): "S10 unit C5b-3 (the RF-RT research-first admission, an intended change)",
    ("RunTask.__init__", "worker_sessions"): "optional: only an entry point holding a trusted continuation binding passes one",
    ("RunTask.__init__", "isolation"): "optional: None is exact host execution; the isolated worker is S10 unit C5c",
    ("RunTask.__init__", "evidence_profile"): "optional: None when the host configured no project-evidence profile",
    ("RunTask.__init__", "knowledge"): "optional: build_executor(knowledge=False) builds no knowledge adapter",
    ("ReviewDecisions.__init__", "worker_sessions"): "optional, as RunTask's",
    ("Transports.__init__", "isolation"): "optional, as RunTask's",
    ("Transports.__init__", "evidence_profile"): "optional, as RunTask's",
    ("Transports.__init__", "hooks"): "container hooks serve only the isolated Codex role container (S10 unit C5c)",
}
# Parameters whose provider is absent at this head: the object holds its own refusing default, never a silent one.
ALLOWED_UNWIRED = {
    ("ReviewDecisions.__init__", "threshold_review"): review_decisions._threshold_review_unwired,  # S8 B6 (M7 review_threshold)
}
# parameter -> attribute, where the class stores it under another name.
ATTRIBUTE = {"Workflow.__init__": {"organization": "org"}, "ExecutionRecovery.__init__": {"organization": "org"},
             "Releases.__init__": {"organization": "org"}}


@pytest.fixture
def settings(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime")}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    return values


def _executor(tmp_path):
    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    git = SimpleNamespace(_git=lambda *a, **k: "revision", repository=tmp_path)
    research = SimpleNamespace(pressure=object())
    return operation.Executor(service, git, FileArtifacts(str(tmp_path / "artifacts")), knowledge=None, research=research)


def test_audit_execution_closes_cycle_one(tmp_path, settings):
    executor = _executor(tmp_path)
    audit = executor.run_task.audit_execution
    assert isinstance(audit, AuditExecution) and audit is executor.audit_execution
    assert audit.executor is executor
    assert isinstance(audit.audits, ResearchAudits) and isinstance(audit.runner, AuditRunner)
    assert audit.audits.runner is audit.runner
    assert audit.runner.root == configuration.runtime_dir() / "audit-sources"
    assert audit.runner.root == tmp_path / "runtime" / "audit-sources" and audit.runner.root.is_dir()
    assert audit.runner.host_execution is True
    assert audit.notices is execution_notices and isinstance(audit.decisions, DecisionOwnership)
    assert executor.decisions.audit_execution is audit


def test_roles_call_the_role_functions_with_the_executor_first(tmp_path, settings, monkeypatch):
    executor = _executor(tmp_path)
    calls = []
    monkeypatch.setattr(autonomous_roles, "execute_role", lambda *a: calls.append(("role", a)) or "role-result")
    from codex_harness.intake.adapters import frontdesk
    monkeypatch.setattr(frontdesk, "execute_frontdesk", lambda *a: calls.append(("desk", a)) or "desk-result")
    task, heartbeat = {"id": "t"}, object()
    assert executor.run_task.roles.execute_role(task, heartbeat) == "role-result"
    assert executor.run_task.roles.execute_frontdesk(task, heartbeat) == "desk-result"
    assert calls == [("role", (executor, task, heartbeat)), ("desk", (executor, task, heartbeat))]


def test_council_feedback_and_admission(tmp_path, settings, monkeypatch):
    executor = _executor(tmp_path)
    task = executor.run_task
    assert task.council is autonomous_roles
    assert isinstance(task.composition_admission, CouncilCompositionAdmission)
    assert task.research_admission is None
    seen = []
    monkeypatch.setattr(correction_feedback, "deliver", lambda *a, **k: seen.append((a, k)) or "delivered")
    assert task.feedback.deliver("store", "artifacts", "binding") == "delivered"
    assert seen == [(("store", "artifacts", "binding"), {"redact": operation.redact_text})]
    assert task.feedback.require_context(1, 10) is None
    with pytest.raises(Exception, match="feedback_context_insufficient"):
        task.feedback.require_context(11, 10)


def test_decision_side_ports(tmp_path, settings):
    executor = _executor(tmp_path)
    ownership = executor.decisions.ownership
    assert ownership.workflow is executor.workflow and ownership.recovery is executor.recovery
    assert ownership.organization is executor.service.org and ownership.clock is not None and ownership.ids is not None


def _objects(executor):
    task = executor.run_task
    return {"RunTask.__init__": task, "ReviewDecisions.__init__": executor.decisions,
            "ExecutionRecovery.__init__": executor.recovery, "Releases.__init__": executor.releases,
            "Transports.__init__": task.transports, "HookCandidates.__init__": task.hook_candidates,
            "Workflow.__init__": executor.workflow}


def test_every_inventory_row_is_wired(tmp_path, settings):
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    objects = _objects(_executor(tmp_path))
    assert set(rows) >= set(objects)
    assert rows["DecisionOwnership.__init__"] == {}  # the inventory has no rows for it: test_decision_side_ports covers it
    unwired = []
    for function, obj in objects.items():
        assert rows[function], function
        for parameter in rows[function]:
            value = getattr(obj, ATTRIBUTE.get(function, {}).get(parameter, parameter))
            key = (function, parameter)
            if key in ALLOWED_UNWIRED:
                assert value is ALLOWED_UNWIRED[key], key
            elif value is None and key not in ALLOWED_NONE:
                unwired.append(key)
    assert unwired == []


def test_allowed_none_names_only_inventory_rows_that_are_none(tmp_path, settings):
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    objects = _objects(_executor(tmp_path))
    for (function, parameter), reason in ALLOWED_NONE.items():
        assert parameter in rows[function] and reason, (function, parameter)
        assert getattr(objects[function], ATTRIBUTE.get(function, {}).get(parameter, parameter)) is None, (function, parameter)
