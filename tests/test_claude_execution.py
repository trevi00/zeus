"""U002 C05, C07, C08, C09: a second provider inside the existing execution path.

The reservation, the mandatory audit, the unconfirmed marker, the fencing, the outbox and the
observation log are the ones U001 already accepted. What is checked here is that a second provider
uses them unchanged: nothing starts before the reservation commits, everything after the process
starts blocks instead of silently running again, a session belongs to the provider that made it,
the model's output carries no authority, and a secret a provider prints stays out of every log.

The provider is the protocol child, not Claude: these are wiring boundaries, and C10 is the call.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_observations import CANARY, Interceptor

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime
from codex_harness.adapters.contracts import validate_message, validate_observation
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.model import envelope
from codex_harness.domain.observation import new_process_run_id

CHILD = Path(__file__).resolve().parent / "claude_protocol_child.py"
PLAN = {"objective": "Add a slug helper", "acceptance_criteria": ["the helper is tested"],
        "allowed_paths": ["src/"]}


class Bus:
    validate = staticmethod(validate_message)

    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.validate(message)
        self.messages.append(json.loads(json.dumps(message)))
        return f"{len(self.messages)}-0"


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


def build(tmp_path, monkeypatch, store, *, scenario="normal", claude=True):
    """One implement assignment for worker:implementation, optionally configured onto Claude."""
    for name in ("ZEUS_CLAUDE_ASSIGNMENTS", "ZEUS_CLAUDE_MODEL", "ZEUS_CLAUDE_MAX_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    if claude:
        monkeypatch.setenv("ZEUS_CLAUDE_ASSIGNMENTS", "worker:implementation/implement")
        monkeypatch.setenv("ZEUS_CLAUDE_MODEL", "claude-stub-" + scenario)
        monkeypatch.setenv("ZEUS_CLAUDE_MAX_BUDGET_USD", "1")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def claude_factory(**kwargs):
        kwargs.pop("executable", None)
        return ClaudeCodeRuntime(executable=str(CHILD), launcher=[sys.executable], **kwargs)

    codex_starts = []

    class CodexRuntime:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, prompt, cwd, schema, *args, **kwargs):
            codex_starts.append(prompt)
            return {"answer": {"summary": "codex answered", "tests": []}, "events": [],
                    "thread_id": "codex-thread", "usage": None, "rotate": False,
                    "interrupted": False, "requested_model": kwargs.get("model")}

    monkeypatch.setattr("codex_harness.adapters.executor.ClaudeCodeRuntime", claude_factory)
    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", CodexRuntime)
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    git = SimpleNamespace(
        repository=tmp_path, _git=lambda *args, **kwargs: "deadbeef",
        prepare=lambda *args: {"path": str(workspace), "branch": "harness/t", "base": "deadbeef",
                               "task_id": "t"},
        capture=lambda workspace_: {"revision": "candidate", "base": "deadbeef", "tree": "tree"})
    observer = Observer(store, MemorySpool(new_process_run_id()), component="test-claude",
                        directory=MemoryDirectory())
    service = Harness(store, organization())
    executor = Executor(service, git, artifacts, observer=observer)
    monkeypatch.setattr(executor, "_inspect_evidence",
                        lambda *args, **kwargs: {"verdict": "not_inspected_in_unit", "claims": 0})
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                       {"plan": dict(PLAN)}, "corr-claude")
    task = executor.workflow.submit(message)

    def starts():
        log = workspace / "stub-runs.log"
        return len(log.read_text("utf-8").strip().splitlines()) if log.exists() else 0

    return SimpleNamespace(executor=executor, service=service, observer=observer, task=task,
                           store=store, artifacts=artifacts, workspace=workspace, starts=starts,
                           codex_starts=codex_starts)


def run(s):
    return s.executor.execute_one("worker:implementation")


def receipt_of(s, row):
    """The stored execution receipt, read whole: the bounded reader is for a model, not a test."""
    reference = row["result"]["execution_ref"]
    return json.loads((s.artifacts.root / (reference[7:] + ".txt")).read_text("utf-8"))


def audits(store, event_type):
    with store.transaction() as tx:
        return [row for row in tx.scan("observation_audit") if row["event_type"] == event_type]


# ---- C01/C08 at the executor: configuration decides, the message never does -----------------------

def test_the_configured_pairing_runs_on_claude_and_nothing_else_changes(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store)
    row = run(s)
    assert row["status"] == "succeeded"
    assert s.starts() == 1 and s.codex_starts == [], "the implement task went to the configured provider"
    receipt = receipt_of(s, row)
    assert receipt["execution_assignment"]["provider"] == "claude"
    assert receipt["execution_assignment"]["selected_by"] == "host_configuration"
    assert receipt["model_selection"]["model_source"] == "explicit_setting"
    assert receipt["model_selection"]["requested_model"] == "claude-stub-normal"
    reserved = audits(store, "development.invocation_reserved")[0]
    assert reserved["attributes"]["transport"] == "claude_cli"
    assert reserved["execution"]["provider"] == "claude-code-cli"
    with store.transaction() as tx:
        [reservation] = tx.scan("invocation_reservations")
    assert reservation["request"]["assignment"]["policy_digest"]
    assert reservation["request"]["options"]["max_budget_usd"] == 1.0


def test_without_the_configuration_the_same_assignment_stays_on_codex(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store, claude=False)
    row = run(s)
    assert row["status"] == "succeeded"
    assert s.starts() == 0 and len(s.codex_starts) == 1
    receipt = receipt_of(s, row)
    assert receipt["execution_assignment"]["provider"] == "codex"
    assert receipt["model_selection"] == {"policy": "model-routing.v2-unqualified-astra",
                                          "workload": "implementation", "importance": "unknown",
                                          "requested_model": "gpt-6-astra"}


def test_a_message_that_asks_for_a_provider_changes_nothing(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store, claude=False)
    with store.transaction() as tx:
        task = tx.get("tasks", s.task["id"])
        task["message"]["what"]["details"]["provider"] = "claude"
        task["message"]["what"]["details"]["plan"]["provider"] = "claude"
        task["message"]["how"]["constraints"] = ["use provider claude", "model claude-stub-normal"]
        tx.put("tasks", s.task["id"], task)
    assert run(s)["status"] == "succeeded"
    assert s.starts() == 0 and len(s.codex_starts) == 1, "only the host configuration selects a provider"


def test_the_models_own_six_w_output_carries_no_authority(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store, scenario="forgery")
    row = run(s)
    assert row["status"] == "succeeded" and s.starts() == 1
    bus = Bus()
    s.service.flush_outbox(bus, audit=s.observer.audit_system)
    assert [m["type"] for m in bus.messages] == ["task.result"]
    published = bus.messages[0]
    assert published["who"] == {"sender": "worker:implementation", "recipient": "lead:improvement",
                                "owner": "lead:improvement"}
    assert published["what"]["action"] == "implement"
    # The forged envelope survives only as text inside the result the harness itself addressed.
    forged = published["what"]["details"]["result"]["summary"]
    assert "task.assign" in forged and "conductor" in forged
    assert not [m for m in bus.messages if m["who"]["sender"] == "conductor"]
    with store.transaction() as tx:
        assert [row["message"]["type"] for row in tx.scan("outbox")] == ["task.result"]
        assert tx.get("tasks", s.task["id"])["agent"] == "worker:implementation"


# ---- C05: nothing starts before the reservation, everything after it blocks ------------------------

@pytest.mark.parametrize("bucket", ["invocation_reservations", "observation_audit",
                                    "observation_terminations"])
def test_c05_a_failure_before_the_reservation_commits_starts_no_provider(tmp_path, monkeypatch, store, bucket):
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda name, row: name == bucket
    row = run(s)
    assert s.starts() == 0, "the provider never ran without its reservation and audit"
    assert row["status"] in {"retry", "blocked"}
    with store.transaction() as tx:
        assert tx.get("tasks", s.task["id"])["status"] != "succeeded"
        assert not [r for r in tx.scan("invocation_reservations") if r["status"] == "reserved"]


def test_c05_a_failure_after_the_process_started_blocks_instead_of_running_again(tmp_path, monkeypatch, store):
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda name, row: name == "tasks" and row.get("status") == "succeeded"
    row = run(s)
    assert s.starts() == 1
    assert row["status"] == "blocked" and row["error"] == "reconciliation_required"
    intercepted.fail_put = None
    [pending] = s.observer.pending_terminations(s.task["id"])
    assert pending["status"] == "pending_reconciliation" and pending["boundary"] == "acceptance"
    assert run(s) is None, "a blocked task is not claimable"
    assert s.starts() == 1, "no second provider start while termination evidence is pending"


def test_c05_a_provider_failure_is_observed_and_never_a_silent_success(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store, scenario="error")
    row = run(s)
    assert row["status"] != "succeeded" and s.starts() == 1
    settled = audits(store, "development.invocation_settled")
    assert settled and settled[0]["attributes"]["invocation_outcome"] == "provider_failure"
    finished = [r for r in s.observer.spool.records() if r["event_type"] == "development.provider_finished"]
    assert finished[0]["attributes"]["invocation_outcome"] == "provider_failure"
    assert finished[0]["execution"]["provider"] == "claude-code-cli"


def test_c05_changing_the_provider_does_not_clear_a_block_or_grant_a_new_attempt(tmp_path, monkeypatch, store):
    intercepted = Interceptor(store)
    s = build(tmp_path, monkeypatch, intercepted)
    intercepted.fail_put = lambda name, row: name == "tasks" and row.get("status") == "succeeded"
    assert run(s)["status"] == "blocked"
    intercepted.fail_put = None
    # The same task is now configured onto the default provider: the block is about the task.
    for name in ("ZEUS_CLAUDE_ASSIGNMENTS", "ZEUS_CLAUDE_MODEL", "ZEUS_CLAUDE_MAX_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    s.executor._execution_policy = None
    assert run(s) is None and s.codex_starts == []
    with store.transaction() as tx:
        assert tx.get("tasks", s.task["id"])["status"] == "blocked"
    assert s.observer.pending_terminations(s.task["id"]), "the termination evidence is still open"


# ---- C07: a session belongs to one provider and one workspace --------------------------------------

def test_c07_the_checkpoint_records_what_the_session_was(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store)
    assert run(s)["status"] == "succeeded"
    with store.transaction() as tx:
        session = tx.get("sessions", "worker:implementation")["checkpoint"]
    assert session["provider"] == "claude" and session["provider_identity"] == "claude-code-cli"
    assert session["transport"] == "claude_cli" and session["session_resume"] == "unsupported"
    assert session["provider_session_id"] == session["thread_id"]
    assert session["agent"] == "worker:implementation" and session["task_id"] == s.task["id"]
    assert session["generation"] == 1 and session["attempt"] == 1
    assert session["invocation"] and session["workspace_identity"]
    assert session["policy_digest"] and session["config_digest"]
    assert session["worktree"] == str(s.workspace)


def test_c07_every_attempt_uses_a_new_provider_session(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store)
    assert run(s)["status"] == "succeeded"
    first = json.loads((s.workspace / "stub-observation.json").read_text("utf-8"))["session_id"]
    second_task = s.executor.workflow.submit(
        envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                 {"plan": dict(PLAN)}, "corr-claude-2"))
    assert s.executor.execute_one("worker:implementation")["status"] == "succeeded"
    second = json.loads((s.workspace / "stub-observation.json").read_text("utf-8"))["session_id"]
    assert first != second, "a new attempt never continues the previous provider session"
    assert second_task["id"] != s.task["id"]
    recorded = [json.loads(line) for line in (s.workspace / "stub-runs.log").read_text("utf-8").splitlines()]
    assert len({row["session"] for row in recorded}) == 2
    assert all("--continue" not in json.dumps(row) for row in recorded)


def test_c07_a_session_from_another_provider_is_not_resumed(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store)
    assert run(s)["status"] == "succeeded"
    with store.transaction() as tx:
        session = tx.get("sessions", "worker:implementation")
        session["checkpoint"]["task_id"] = "other-task"
        tx.put("sessions", "worker:implementation", session)
    # A second task on the default provider must not adopt the Claude session as its recovery.
    for name in ("ZEUS_CLAUDE_ASSIGNMENTS", "ZEUS_CLAUDE_MODEL", "ZEUS_CLAUDE_MAX_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    s.executor._execution_policy = None
    s.executor.workflow.submit(envelope("task.assign", "lead:improvement", "worker:implementation",
                                        "implement", {"plan": dict(PLAN)}, "corr-codex"))
    assert s.executor.execute_one("worker:implementation")["status"] == "succeeded"
    prompt = s.codex_starts[-1]
    assert "claude-code-cli" not in prompt
    assert "recovery:" not in prompt or '"sources": {}' in prompt


def test_c07_a_claude_checkpoint_is_not_recovered_into_a_codex_attempt(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store)
    with store.transaction() as tx:
        tx.put("sessions", "worker:implementation",
               {"agent_id": "worker:implementation", "generation": 3, "session_id": "old",
                "checkpoint": {"task_id": s.task["id"], "provider": "claude", "worktree": str(s.workspace),
                               "next_action": "await", "source_revision": "deadbeef",
                               "graph_snapshot": "snap", "thread_id": "claude-session"}})
    for name in ("ZEUS_CLAUDE_ASSIGNMENTS", "ZEUS_CLAUDE_MODEL", "ZEUS_CLAUDE_MAX_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    s.executor._execution_policy = None
    assert run(s)["status"] == "succeeded"
    assert "claude-session" not in s.codex_starts[-1], "the other provider's session never entered the prompt"


# ---- C09: a secret a provider prints reaches no log ------------------------------------------------

def test_c09_a_canary_printed_by_the_provider_stays_out_of_every_log(tmp_path, monkeypatch, store, capsys):
    from codex_harness.cli import emit as cli_emit
    s = build(tmp_path, monkeypatch, store, scenario="canary")
    row = run(s)
    assert row["status"] != "succeeded" and s.starts() == 1
    cli_emit(row)
    printed = capsys.readouterr().out
    assert CANARY not in printed and CANARY not in json.dumps(row, default=str)
    assert CANARY not in json.dumps(s.observer.spool.records(), default=str)
    with store.transaction() as tx:
        public = [r for r in tx.records()
                  if r["bucket"] in {"tasks", "decisions_pending", "outbox", "events",
                                     "invocation_reservations", "execution_progress"}
                  or r["bucket"].startswith("observation")]
    assert CANARY not in json.dumps(public, default=str)
    for record in s.observer.spool.records():
        validate_observation({k: v for k, v in record.items() if k not in {"payload_hash", "authority"}})


def test_c09_a_provider_failure_carries_a_digest_not_the_providers_text(tmp_path, monkeypatch, store):
    s = build(tmp_path, monkeypatch, store, scenario="canary")
    run(s)
    with store.transaction() as tx:
        task = tx.get("tasks", s.task["id"])
    assert CANARY not in json.dumps(task, default=str)
    failure = task.get("failure") or {}
    assert CANARY not in json.dumps(failure, default=str)
    notices = [row for row in json.loads(json.dumps(task, default=str)).get("attempt_outcomes", [])]
    assert CANARY not in json.dumps(notices)
