from copy import deepcopy
from uuid import uuid4

import pytest

from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import (
    ContextItem,
    ContractError,
    compile_context,
    digest,
    envelope,
    session_action,
)


def incident(occurrence=None, scope="test", cause="powershell-codex-ps1-policy"):
    return envelope("incident.report", "worker:implementation", "lead:improvement", "record_incident",
                    {"occurrence_id": occurrence or str(uuid4()), "root_cause": cause,
                     "scope": scope, "evidence_refs": ["fixture:error"]}, "improvement-test")


@pytest.fixture
def service():
    return Harness(MemoryStore(), organization())


def candidate(service):
    service.record_incident(incident())
    hook_id = service.record_incident(incident())["hook_id"]
    spec = {"kind": "executable_alias", "platform": "windows", "match": "codex.ps1",
            "replacement": "codex.cmd"}
    service.propose(hook_id, "worker:implementation", spec, "revision-a")
    return hook_id, spec


def reviewed(service):
    hook_id, spec = candidate(service)
    for actor in ("lead:improvement", "conductor"):
        service.review(hook_id, actor, "revision-a", digest(spec), True, "test:evidence")
    return hook_id, spec


def test_second_distinct_occurrence_and_duplicate_delivery(service):
    msg = incident("one")
    assert service.record_incident(msg)["hook_id"] is None
    assert service.record_incident(msg)["occurrences"] == 1
    assert service.record_incident(incident("one"))["occurrences"] == 1
    second = service.record_incident(incident("two"))
    assert second["hook_created"] and second["occurrences"] == 2
    assert not service.record_incident(incident("three"))["hook_created"]
    with service.store.transaction() as tx:
        assert len(tx.scan("outbox")) == 1


def test_same_symptom_different_scope_does_not_count(service):
    service.record_incident(incident(scope="repo-a"))
    assert service.record_incident(incident(scope="repo-b"))["hook_id"] is None


def test_retry_evidence_does_not_trigger_independent_recurrence(service):
    first = incident("task-a-attempt-1")
    assert service.record_incident(first, independent_occurrence="task-a")["occurrences"] == 1
    for attempt in (2, 3):
        result = service.record_incident(incident(f"task-a-attempt-{attempt}"),
                                         independent_occurrence="task-a")
        assert result["occurrences"] == 1 and result["hook_id"] is None
    result = service.record_incident(incident("task-b-attempt-1"), independent_occurrence="task-b")
    assert result["hook_created"] and result["occurrences"] == 2
    with service.store.transaction() as tx:
        assert len(tx.scan("incidents")) == 4
        assert len(tx.scan("outbox")) == 1
    with pytest.raises(ContractError, match="occurrence authority"):
        service.record_incident(first, independent_occurrence="changed")


def test_message_id_reuse_and_occurrence_conflicts_rejected(service):
    msg = incident("one")
    service.record_incident(msg)
    modified = deepcopy(msg)
    modified["why"]["objective"] = "changed"
    with pytest.raises(ContractError, match="Message ID"):
        service.record_incident(modified)
    with pytest.raises(ContractError, match="Occurrence ID"):
        service.record_incident(incident("one", scope="other"))


def test_invalid_who_and_missing_six_w_rejected():
    msg = incident()
    del msg["why"]
    with pytest.raises(ContractError):
        validate_message(msg)
    msg = incident()
    msg["who"]["recipient"] = "conductor"
    with pytest.raises(ContractError, match="direct parent"):
        organization().authorize(msg)


def test_unknown_fields_and_naive_timestamp_rejected():
    msg = incident()
    msg["injected"] = True
    with pytest.raises(ContractError):
        validate_message(msg)
    del msg["injected"]
    msg["when"]["created_at"] = "2026-09-07T10:00:00"
    with pytest.raises(ContractError):
        validate_message(msg)


def test_worker_or_wrong_lead_cannot_review(service):
    hook_id, spec = candidate(service)
    for actor in ("worker:implementation", "lead:research", "conductor"):
        with pytest.raises(ContractError):
            service.review(hook_id, actor, "revision-a", digest(spec), True, "proof")


def test_stale_review_and_canary_cannot_promote(service):
    hook_id, spec = reviewed(service)
    with pytest.raises(ContractError, match="Stale canary"):
        service.record_canary(hook_id, "revision-b", digest(spec),
                              {"reproduction": True, "normal_case": True, "cli_start": True})
    with pytest.raises(ContractError):
        service.activate(hook_id)


def test_failure_never_activates_and_pass_survives_new_service(service):
    hook_id, spec = reviewed(service)
    service.record_canary(hook_id, "revision-a", digest(spec),
                          {"reproduction": True, "normal_case": False, "cli_start": True})
    with pytest.raises(ContractError):
        service.activate(hook_id)
    assert service.prepare_command(["codex.ps1"], "windows") == ["codex.ps1"]
    service.propose(hook_id, "worker:implementation", spec, "revision-b")
    for actor in ("lead:improvement", "conductor"):
        service.review(hook_id, actor, "revision-b", digest(spec), True, "proof")
    service.record_canary(hook_id, "revision-b", digest(spec),
                          {"reproduction": True, "normal_case": True, "cli_start": True})
    service.activate(hook_id)
    restarted = Harness(service.store, organization())
    assert restarted.prepare_command(["codex.ps1", "--version"], "windows") == ["codex.cmd", "--version"]
    assert restarted.prepare_command(["git", "status"], "windows") == ["git", "status"]
    restarted.rollback(hook_id, "regression")
    assert restarted.prepare_command(["codex.ps1"], "windows") == ["codex.ps1"]


def test_checkpoint_generation_fences_old_session(service):
    state = {"next_action": "verify", "source_revision": "abc", "graph_snapshot": "123"}
    assert service.checkpoint("worker:implementation", 0, state)["generation"] == 1
    with pytest.raises(ContractError, match="Stale session"):
        service.checkpoint("worker:implementation", 0, state)


def test_recurrence_updates_same_hook_without_disabling_previous_verified_version(service):
    hook_id, spec = reviewed(service)
    checks = {"reproduction": True, "normal_case": True, "cli_start": True}
    service.record_canary(hook_id, "revision-a", digest(spec), checks)
    service.activate(hook_id)
    recurrence = incident("after-activation")
    result = service.record_incident(recurrence)
    assert result["hook_created"] and result["hook_id"] == hook_id
    assert service.get_hook(hook_id)["status"] == "required"
    service.record_incident(incident("after-activation"))
    with service.store.transaction() as tx:
        assert len(tx.scan("outbox")) == 2
    changed = {**spec, "replacement": "codex.exe"}
    service.propose(hook_id, "worker:implementation", changed, "revision-b")
    assert service.prepare_command(["codex.ps1"], "windows") == ["codex.cmd"]
    for actor in ("lead:improvement", "conductor"):
        service.review(hook_id, actor, "revision-b", digest(changed), True, "fixture:review")
    service.record_canary(hook_id, "revision-b", digest(changed), checks)
    service.activate(hook_id)
    assert service.prepare_command(["codex.ps1"], "windows") == ["codex.exe"]
    service.rollback(hook_id, "new version regression")
    assert service.prepare_command(["codex.ps1"], "windows") == ["codex.cmd"]


@pytest.mark.parametrize("used,idle,busy,action", [
    (70, 0, False, "rotate"), (70, 0, True, "checkpoint_when_safe"),
    (20, 3600, False, "hibernate"), (20, 3600, True, "continue"),
])
def test_session_lifecycle(used, idle, busy, action):
    assert session_action(used, 100, idle, busy) == action


def test_context_keeps_contract_drops_optional_and_is_reproducible():
    required = {"role": "worker", "objective": "fix", "acceptance_criteria": ["pass"], "policy": "v1"}
    items = [ContextItem("large", "x" * 5000, "src/a.py", "abc"),
             ContextItem("small", "useful fact", "src/b.py", "abc", 10)]
    packet = compile_context("worker", "task", "snapshot", required, items, 1000, 300)
    assert [v["id"] for v in packet.evidence] == ["small"]
    assert packet.omitted[0]["id"] == "large"
    assert packet.manifest_hash == compile_context("worker", "task", "snapshot", required,
                                                   list(reversed(items)), 1000, 300).manifest_hash
    with pytest.raises(ContractError, match="Required contract exceeds"):
        compile_context("worker", "task", "snapshot", required, [], 100, 10)


def test_context_rejects_conflicting_evidence_ids():
    required = {"role": "worker", "objective": "fix", "acceptance_criteria": ["pass"], "policy": "v1"}
    with pytest.raises(ContractError, match="Conflicting evidence"):
        compile_context("w", "t", "s", required, [ContextItem("a", "one", "f", "r"),
                                                    ContextItem("a", "two", "f", "r")], 2000, 200)


def test_transaction_rolls_back():
    store = MemoryStore()
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.put("events", "x", {"test": True})
            raise RuntimeError("crash")
    with store.transaction() as tx:
        assert tx.get("events", "x") is None
