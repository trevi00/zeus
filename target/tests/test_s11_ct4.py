"""S11 unit CT-4: behavioural tests for four execution contracts that no row-named passing target test cited
(DESIGN-s11 §5 R-L9, §5.4 G2).

Each test names its contract ID in its own docstring (the R-L9 citation), quotes the first concrete rule of that contract
in docs/contracts.md, drives the owner through its public API and takes its expected results from the contract text, not
from the implementation.
"""

from types import SimpleNamespace

import pytest

from codex_harness.coordination.application.workflow import Workflow
from codex_harness.execution.adapters.output_schema import preflight
from codex_harness.execution.application.run_task import RunTask
from codex_harness.execution.domain.invocation import parse_request
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
from codex_harness.kernel.message import envelope
from codex_harness.research.application.audit_gate import require_adoption
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

AGENT = "worker:implementation"
OTHER_AGENT = "worker:github"


def workflow(store):
    return Workflow(store, packaged_organization(), ticket_binding=tickets.ticket_binding,
                    TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption,
                    park_terminal=lambda tx, message: None, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def assignment(task_id, agent=AGENT, action="implement"):
    parent = packaged_organization().actor(agent).parent
    message = envelope("task.assign", parent, agent, action, {"objective": "fixture"}, "ct4")
    message["message_id"] = task_id
    return message


def test_s11_contract_invocation_refuses_unknown_and_unsupported_options_with_their_names():
    """INV-INVOCATION-001: "unknown options and options the transport does not support are refused before execution
    with their names, never silently dropped, and invalid types or values (empty model, non-finite or non-positive
    timeout, empty schema) are refused the same way." (docs/contracts.md:300-303)"""
    schema = {"type": "object"}
    accepted = parse_request("app_server", {"model": "gpt-5-codex", "timeout": 30, "output_schema": schema})
    assert accepted["options"] == {"model": "gpt-5-codex", "timeout": 30, "output_schema": schema}
    with pytest.raises(ContractError) as unknown:
        parse_request("app_server", {"model": "m", "top_p": 1, "frequency": 2})
    assert "frequency" in str(unknown.value) and "top_p" in str(unknown.value)
    with pytest.raises(ContractError) as unsupported:
        parse_request("app_server", {"model": "m", "temperature": 0.2, "max_output_tokens": 10})
    assert "max_output_tokens" in str(unsupported.value) and "temperature" in str(unsupported.value)
    for invalid in ({"model": ""}, {"model": "  "}, {"timeout": 0}, {"timeout": -1}, {"timeout": float("nan")},
                    {"timeout": float("inf")}, {"output_schema": {}}):
        with pytest.raises(ContractError):
            parse_request("app_server", invalid)


def test_s11_contract_output_preflight_refuses_unsupported_and_inconsistent_schemas_with_a_receipt():
    """INV-OUTPUT-001: "every keyword a schema uses must be in the supported subset, so a misspelled or unsupported
    keyword is refused at preflight as a configuration-owner error ...; enum and const require an explicit type; a
    closed object cannot require names it does not declare ... Preflight returns a receipt (schema hash, dialect,
    subset version, keywords seen, checks run)." (docs/contracts.md:643-648)"""
    valid = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["pass", "fail"]}},
             "required": ["verdict"], "additionalProperties": False}
    receipt = preflight(valid)
    assert receipt["schema_hash"].startswith("sha256:") and receipt["dialect"].endswith("2020-12/schema")
    assert "subset_version" in receipt and receipt["checks"]
    assert {"type", "properties", "enum", "required", "additionalProperties"} <= set(receipt["keywords"])
    misspelled = {"type": "object", "properties": {"verdict": {"type": "string", "enumm": ["pass"]}}}
    with pytest.raises(ContractError, match="unsupported keyword.*enumm"):
        preflight(misspelled)
    with pytest.raises(ContractError, match="enum requires explicit type"):
        preflight({"type": "object", "properties": {"verdict": {"enum": ["pass", "fail"]}}})
    with pytest.raises(ContractError, match="const requires explicit type"):
        preflight({"type": "object", "properties": {"verdict": {"const": "pass"}}})
    with pytest.raises(ContractError, match="required names not declared.*ghost"):
        preflight({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a", "ghost"],
                   "additionalProperties": False})


def test_s11_contract_worker_session_is_opt_in_twice_and_otherwise_the_fresh_path():
    """INV-WORKER-SESSION-001: "It is opt-in twice: the host constructs `Executor(worker_sessions=...)`, and a caller
    passes an explicit `task_session={"task_id", "repository"}` with `max_handoffs=1`. Without both, execution is the
    unchanged fresh path." (docs/contracts.md:3015-3018)"""
    claude = SimpleNamespace(transport="claude_cli")
    lease = {"id": "exec-a", "generation": 2, "attempt": 1}
    binding = {"task_id": "task-1", "repository": "zeus"}
    isolated = SimpleNamespace(worker_sessions=object(), isolation=SimpleNamespace(config={"image": "img"}))
    unconfigured = SimpleNamespace(worker_sessions=None, isolation=isolated.isolation)
    # No caller task_session: the unchanged fresh path, whether or not the host opted in.
    assert RunTask._task_session_owner(isolated, None, claude, False, lease, 4) is None
    assert RunTask._task_session_owner(unconfigured, None, claude, False, lease, 4) is None
    # A caller binding without the host's worker_sessions is refused before any provider entry.
    with pytest.raises(ContractError, match="not configured"):
        RunTask._task_session_owner(unconfigured, binding, claude, False, lease, 1)
    # Both opted in with max_handoffs=1: the leased execution owns the session.
    assert RunTask._task_session_owner(isolated, binding, claude, False, lease, 1) == {
        "execution": "exec-a", "generation": 2, "attempt": 1}
    # The binding is exactly task_id and repository, and the turn is one provider call (max_handoffs=1).
    with pytest.raises(ContractError, match="exactly task_id and repository"):
        RunTask._task_session_owner(isolated, {"task_id": "task-1"}, claude, False, lease, 1)
    with pytest.raises(ContractError, match="one provider call"):
        RunTask._task_session_owner(isolated, binding, claude, False, lease, 2)


def test_s11_contract_execution_identity_selects_by_agent_then_creation_time_then_task_id():
    """INV-EXECUTION-IDENTITY-001: "Task selection uses agent and explicit task identity, with UTC creation time and
    task id as a deterministic tie-break ... Malformed scheduling metadata is contained per row."
    (docs/contracts.md:206-208)"""
    store = MemoryStore()
    flow = workflow(store)
    for task_id, agent in (("task-b", AGENT), ("task-a", AGENT), ("task-c", AGENT), ("task-0", OTHER_AGENT)):
        flow.submit(assignment(task_id, agent))
    with store.transaction() as tx:
        stamps = {"task-0": "2026-01-01T00:00:00+00:00", "task-b": "2026-01-02T00:00:00+00:00",
                  "task-a": "2026-01-02T00:00:00+00:00", "task-c": "2026-01-01T12:00:00+00:00"}
        for task_id, created in stamps.items():
            row = tx.get("tasks", task_id)
            row["created_at"] = created
            tx.put("tasks", task_id, row)
    # The oldest row of ANOTHER agent (task-0) is never selected for this agent; then creation time, then task id.
    selected = []
    for round_number in range(3):
        task = flow.claim(AGENT, f"owner-{round_number}", lease_seconds=3600)
        selected.append(task["id"])
        flow.complete(task, {"summary": "fixture"})
    assert selected == ["task-c", "task-a", "task-b"]
    assert flow.claim(AGENT, "owner-3", lease_seconds=3600) is None
    assert flow.claim(OTHER_AGENT, "other-owner", lease_seconds=3600)["id"] == "task-0"


def test_s11_contract_execution_identity_contains_malformed_scheduling_metadata_per_row():
    """INV-EXECUTION-IDENTITY-001: "Malformed scheduling metadata is contained per row." (docs/contracts.md:208)
    A row with an unreadable creation time is blocked; the agent's well-formed task is still selected."""
    store = MemoryStore()
    flow = workflow(store)
    flow.submit(assignment("task-bad"))
    flow.submit(assignment("task-good"))
    with store.transaction() as tx:
        row = tx.get("tasks", "task-bad")
        row["created_at"] = "not-a-time"
        tx.put("tasks", "task-bad", row)
    claimed = flow.claim(AGENT, "owner-1", lease_seconds=3600)
    assert claimed["id"] == "task-good"
    with store.transaction() as tx:
        assert tx.get("tasks", "task-bad")["status"] == "blocked"
