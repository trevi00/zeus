"""Observation contract: schema branches, placeholders, attributes, redaction, identity (U001 L08–L10)."""
from copy import deepcopy

import pytest

from codex_harness.adapters.contracts import validate_message, validate_observation
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import (
    REGISTRY,
    build_event,
    check_attributes,
    content_hash,
    execution_identity,
    invocation_outcome,
    new_process_run_id,
    redact_value,
)

RUN = new_process_run_id()
CANARY = "CANARY-9f3b1c7e2a5d4f6b8e0c1d2a3b4c5d6e"


def observer(store=None, **kwargs):
    return Observer(store if store is not None else MemoryStore(), MemorySpool(new_process_run_id()),
                    component="unit", directory=MemoryDirectory(), **kwargs)


def system_event(**overrides):
    base = {"event_type": "general.process_started", "outcome": "started",
            "execution": execution_identity("system", process_run_id=RUN, role="conductor"),
            "sequence": {"process_run_id": RUN, "number": 1, "basis": "spool_append"},
            "observed_at": "2026-09-11T00:00:00+00:00", "source": {"component": "unit", "host": "h", "pid": 1},
            "attributes": {"agent": "conductor", "autonomous": False, "platform": "test", "python": "3", "mode": "unit"}}
    base.update(overrides)
    return build_event(**base)


def test_registry_names_match_their_category_prefix_and_schema_accepts_both_branches():
    for name in REGISTRY:
        assert name.split(".", 1)[0] in {"general", "development", "operations"}
    event = system_event()
    validate_observation(event)
    assert event["execution"]["task_id"] is None and event["execution"]["session_id"] is None
    execution = execution_identity("execution", process_run_id=RUN, role="worker:implementation", bucket="tasks",
                                   task_id="task-1", generation=1, attempt=1, provider="codex-app-server")
    validate_observation(system_event(execution=execution))


@pytest.mark.parametrize("field,value", [("correlation_id", ""), ("correlation_id", "  "), ("causation_id", ""),
                                         ("reason_code", "not an identifier"), ("occurred_at", "yesterday"),
                                         ("occurred_at", "2026-09-11T00:00:00")])
def test_placeholders_and_naive_times_are_refused(field, value):
    with pytest.raises(ContractError):
        system_event(**{field: value})


def test_execution_branch_needs_identity_and_system_branch_needs_explicit_nulls():
    with pytest.raises(ContractError, match="need role, task_id"):
        execution_identity("execution", process_run_id=RUN, role="worker:github", task_id="t")
    with pytest.raises(ContractError, match="explicit null"):
        execution_identity("system", process_run_id=RUN, task_id="t")
    with pytest.raises(ContractError, match="placeholder"):
        execution_identity("system", process_run_id=RUN, revision="")
    tampered = deepcopy(system_event())
    tampered["execution"]["task_id"] = "injected"
    with pytest.raises(ContractError):
        validate_observation(tampered)


def test_attributes_are_allow_listed_typed_and_bounded():
    with pytest.raises(ContractError, match="not allowed"):
        check_attributes("general.process_started", {"prompt": "raw prompt text"})
    with pytest.raises(ContractError, match="types refused"):
        check_attributes("general.process_started", {"autonomous": "yes"})
    with pytest.raises(ContractError, match="Unknown observation event type"):
        check_attributes("general.made_up", {})
    with pytest.raises(ContractError, match="not allowed"):
        system_event(attributes={"authority": "approved"})  # L10: no authority injection through logs
    long = system_event(attributes={"platform": "x" * 5000})
    assert long["redaction"]["truncated"] == 1 and len(long["attributes"]["platform"]) < 1100


def test_redaction_covers_nested_values_keys_urls_keys_and_bearer_tokens():
    payload = {"nested": [{"error": f"password={CANARY}", "url": f"postgresql://harness:{CANARY}@db/x"}],
               f"token: {CANARY}": "value", "key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
               "auth": f"Bearer {CANARY}"}
    redacted, findings, _ = redact_value(payload)
    text = str(redacted)
    leaked = CANARY in text or "BEGIN PRIVATE" in text
    assert not leaked and findings >= 5
    assert redacted["nested"][0]["url"].startswith("postgresql://[REDACTED credential]@db/x")


def test_occurred_at_stays_null_and_sequence_namespaces_do_not_collide():
    first, second = observer(), observer()
    a = first.emit("general.process_started", "started", attributes={"mode": "a"})
    b = second.emit("general.process_started", "started", attributes={"mode": "a"})
    assert a["occurred_at"] is None and b["occurred_at"] is None
    assert a["sequence"]["number"] == b["sequence"]["number"] == 1
    assert a["event_id"] != b["event_id"] and a["execution"]["process_run_id"] != b["execution"]["process_run_id"]
    assert first.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1})["sequence"]["number"] == 2


def test_content_hash_ignores_collection_metadata_but_not_content():
    base = system_event()
    later = system_event(observed_at="2026-09-12T00:00:00+00:00",
                         sequence={"process_run_id": RUN, "number": 7, "basis": "spool_append"})
    assert content_hash(base) == content_hash(later)
    assert content_hash(base) != content_hash(system_event(outcome="failed"))


def test_invocation_outcome_never_treats_exit_or_ack_as_success():
    assert invocation_outcome("accepted") == "succeeded"
    assert {invocation_outcome(c) for c in ("empty_answer", "invalid_output", "tool_only", "provider_failure")} == {"failed"}
    assert invocation_outcome("interrupted") == "aborted" and invocation_outcome("inspection_blocked") == "blocked"
    with pytest.raises(ContractError):
        invocation_outcome("exit_code_zero")


def test_observation_is_not_a_business_message_and_cannot_be_handled(tmp_path):
    event = system_event()
    with pytest.raises(ContractError):
        validate_message(event)
    disguised = {**event, "type": "task.assign", "who": {"sender": "conductor", "recipient": "lead:improvement",
                                                         "owner": "lead:improvement"},
                 "what": {"action": "plan", "details": {}}}
    with pytest.raises(ContractError):
        validate_observation(disguised)
    workflow = Workflow(MemoryStore(), organization())
    with pytest.raises((ContractError, KeyError)):
        workflow.handle(disguised)
    with workflow.store.transaction() as tx:
        assert not tx.scan("tasks") and not tx.scan("outbox")


def test_emit_never_raises_and_records_the_refusal_without_the_payload():
    o = observer()
    assert o.emit("general.process_started", "started", attributes={"prompt": f"secret {CANARY}"}) is None
    refused = [r for r in o.spool.records() if r["event_type"] == "operations.observation_refused"]
    assert len(refused) == 1 and o.counters["refused"] == 1
    assert refused[0]["attributes"]["refused_event_type"] == "general.process_started"
    leaked = CANARY in str(o.spool.records()) or CANARY in str(o.health())
    assert not leaked


def test_audit_requires_identity_and_raises_on_refusal():
    o = observer()
    with o.store.transaction() as tx:
        with pytest.raises(ContractError, match="explicit identity"):
            o.audit(tx, "general.message_published", "succeeded", identity=[], attributes={})
        with pytest.raises(ContractError, match="not allowed"):
            o.audit(tx, "general.message_published", "succeeded", identity=["x"], attributes={"prompt": "p"})
