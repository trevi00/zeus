"""S11 unit XC-10 (TQ-XCUT-PLAN §1 C follow-up U9): the retryability table's `contract-fixed` rows.

Behavioural tests only (TQ-XCUT-RESEARCH T1). Expected results come from `docs/contracts.md` (the line is cited in each
docstring) or, for a bound the contract defers to the unchanged M7 value ("the queue's unchanged retry budget and
backoff"), from the M7 SOURCE package (`codex_harness` 0.x reference, read only, never imported here): the number is
asserted as a literal with its M7 file:line, never derived from the target's `POLICY`.

One test per distinct decision point; the decision points with no contract text (outbox delivery `retry`/`error`/
`quarantined`, attempt-budget exhaustion in `Workflow.claim`, dead-letter reasons) are measured in the unit's report and
deliberately not asserted here. Each test drives the public use case on `MemoryStore` or a recording fake and asserts
the outcome, the durable trace (row status, attempt count) and the absence of a second effect.
"""

import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# The shim wires the use cases as composition does (outbox health, workflow ports, the guardian's leak/ownership types).
sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from m7_coordination import Workflow, guard, launch_directory, observe, pin_route, relay  # noqa: E402

from codex_harness.coordination.adapters import guarded_launch as cp
from codex_harness.coordination.adapters.guarded_launch import EXIT_UNRESOLVED
from codex_harness.coordination.domain import continuation as dc
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.kernel.errors import ExecutionFailure
from codex_harness.kernel.message import envelope
from codex_harness.observation.domain.observation import redact_text, redact_value
from codex_harness.research.domain.council_input import CouncilInputOverflow
from codex_harness.review.adapters.release_suite import REPORT_ENV, ReleaseSuite
from codex_harness.review.application.release_queue import ReleaseQueue
from codex_harness.review.domain.check_results import nodes_digest
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.message_schema import validate_message

POSIX = pytest.mark.skipif(os.name == "nt", reason="POSIX process-group containment only")


# --- outbox relay: route hold (INV-MESSAGE-001, contracts.md:2163-2167) ----------------------------------------

class Bus:
    validate = staticmethod(validate_message)

    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)
        return f"{len(self.messages)}-0"


class RunBus(Bus):
    def __init__(self, run_id):
        super().__init__()
        self.namespace = "ns:run:" + run_id
        self.route = {"scope": "run", "run_id": run_id, "namespace": self.namespace}


def test_a_global_relay_holds_a_pinned_record_with_no_intent_attempt_quarantine_or_sent_flag():
    """contracts.md:2163-2167 (Correlation-scoped route pin): "the unscoped relay leaves the record pending
    (`route_held`) ... Held records get no intent, attempt, quarantine or sent flag"; only the run's own route
    publishes it (once)."""
    store, org = MemoryStore(), packaged_organization()
    correlation = "autonomous:run-A"
    message = envelope("task.assign", "conductor", "lead:improvement", "plan", {"objective": "route hold"}, correlation)
    identity = message["message_id"]
    with store.transaction() as tx:
        pin_route(tx, correlation, RunBus("run-A").route, "at")
        tx.put("outbox", identity, {"message": message, "sent": False})
    global_bus = Bus()
    result = relay(store, org, global_bus)
    assert result["route_held"] == 1 and result["published"] == 0 and global_bus.messages == []
    with store.transaction() as tx:
        assert tx.get("outbox", identity)["sent"] is False
        assert tx.get("outbox_delivery", identity) is None
        assert tx.scan("outbox_attempts") == [] and tx.scan("outbox_quarantine") == []
    own = RunBus("run-A")
    assert relay(store, org, own, correlation_id=correlation)["published"] == 1
    assert [m["message_id"] for m in own.messages] == [identity]
    assert relay(store, org, own, correlation_id=correlation)["examined"] == 0, "published once"


# --- Workflow.fail_execution (contracts.md:1245-1246 council pre-entry; :876 read-only violation) ----------------

def _claimed(workflow, agent="worker:implementation"):
    parent = workflow.org.actor(agent).parent
    workflow.submit(envelope("task.assign", parent, agent, "implement", {"objective": "fixture"}, "xc10"))
    return workflow.claim(agent, "owner-1")


def test_a_pre_entry_refusal_leaves_the_row_retry_and_a_contained_provider_cause_fails_it_without_replay():
    """contracts.md:1245-1246: "`retry` when the executor's own pre-entry gate refused (the provider never started),
    `failed` when the workflow settled it as not retryable"; contracts.md:875-877: the read-only violation cause "is
    contained like a refusal of the execution's own credential: the task fails without replay rather than spending
    another real call". A replay of the same failure commits no second receipt."""
    workflow = Workflow(MemoryStore(), packaged_organization())
    refused = _claimed(workflow)
    refusal = CouncilInputOverflow("packet", 20000, 16384)
    first = workflow.fail_execution(refused, refusal)
    assert (first["status"], first["attempt"]) == ("retry", 1)
    assert first["error"] == "CouncilInputOverflow: " + refusal.reason_code
    assert workflow.fail_execution(refused, refusal) == first, "the replay returns the committed row"
    again = workflow.claim("worker:implementation", "owner-2")
    assert again["id"] == refused["id"] and again["attempt"] == 2, "a retry row is claimable again"
    # A separate execution: the provider ran and breached its read-only profile.
    other = Workflow(MemoryStore(), packaged_organization())
    breached = _claimed(other)
    breach = ExecutionFailure("claude-provider-read-only-violation", {"execution_ref": "fixture"})
    contained = other.fail_execution(breached, breach)
    assert (contained["status"], contained["attempt"]) == ("failed", 1)
    assert other.fail_execution(breached, breach) == contained, "the replay returns the committed row"
    assert other.claim("worker:implementation", "owner-4") is None, "a contained failure is never replayed"
    for flow in (workflow, other):
        with flow.store.transaction() as tx:
            assert len(tx.scan("execution_failures")) == 1, "one receipt per failure, none for the replays"


# --- test-evidence runner: observation_error (contracts.md:398-399) ---------------------------------------------

PLAN = ["tests/test_a.py::test_a"]


def _event(**fields):
    return json.dumps(fields, sort_keys=True) + "\n"


def _dir(root, name):
    (root / name).mkdir()
    return root / name


def _suite(tmp_path, process):
    artifacts = FileArtifacts(tmp_path / "artifacts")
    suite = ReleaseSuite(artifacts, lambda: None, run_logged_process=process, redact=redact_text,
                         redact_value=redact_value)
    return suite.check(["pytest", "-q"], cwd=str(tmp_path), timeout=5, env={REPORT_ENV: "unused"}, binding={})


def _collected(env, nodeids=PLAN):
    Path(env[REPORT_ENV]).write_text(_event(event="collected", count=len(nodeids), sha256=nodes_digest(nodeids),
                                            nodeids=list(nodeids)), encoding="utf-8")


def _passing_batch(env, finish):
    report = Path(env[REPORT_ENV])
    body = _event(event="collected", count=1, sha256=nodes_digest(PLAN))
    body += _event(event="selected", nodeids=PLAN)
    for phase in ("setup", "call", "teardown"):
        body += _event(event="phase", nodeid=PLAN[0], when=phase, outcome="passed", xfail=False, duration=0.0)
    body += _event(event="finish", nodeid=PLAN[0])
    if finish:
        body += _event(event="sessionfinish", exitstatus=0)
    report.write_text(body, encoding="utf-8")


def test_a_timeout_a_spawn_error_and_a_process_without_a_session_finish_are_observation_errors_never_a_pass(tmp_path):
    """contracts.md:398-399: "A timeout, a spawn error or a process that ends without a session finish is
    `observation_error` (retry), never a pass." The control (a batch that DID report its session finish) passes, so
    the three refusals are not vacuous."""
    calls = []

    def timed_out(argv, *, stdout_path, stderr_path, cwd, timeout, env):
        calls.append("timeout")
        return {"exit_code": None, "timed_out": True}

    def spawn_error(argv, *, stdout_path, stderr_path, cwd, timeout, env):
        calls.append("spawn")
        raise FileNotFoundError("no such executable")

    def no_session_finish(finish):
        def run(argv, *, stdout_path, stderr_path, cwd, timeout, env):
            calls.append("collect" if "--collect-only" in argv else "batch")
            (_collected if "--collect-only" in argv else lambda e: _passing_batch(e, finish))(env)
            return {"exit_code": 0, "timed_out": False}
        return run

    for index, process in enumerate((timed_out, spawn_error, no_session_finish(False))):
        result = _suite(_dir(tmp_path, str(index)), process)
        assert result["passed"] is False and result["outcome"] == "observation_error", (index, result)
    assert calls == ["timeout", "spawn", "collect", "batch"], "each refusal stopped at its own process, no retry inside"
    control = _suite(_dir(tmp_path, "control"), no_session_finish(True))
    assert control["passed"] is True and control["outcome"] == "executed", control


# --- release queue: retry budget and backoff (contracts.md:2743; the bound is M7's) ---------------------------------

class Fences:
    """The execution-fence port the queue is injected with; this fake only accepts."""

    def advance(self, tx, bucket, key, generation, owner, clock=None):
        return None

    def require_current(self, tx, bucket, key, generation, owner):
        return None


def test_a_definite_failure_retries_with_doubling_backoff_and_fails_when_the_attempt_budget_is_spent():
    """contracts.md:2742-2743: "Definite failures still go through `finish` with the queue's unchanged retry budget
    and backoff" - unchanged from M7 `application/release_queue.py:161-166` with `domain/policy.py:31-32`:
    `release_retry_seconds` 30 and `release_max_attempts` 3, retry_at = 30 s * 2**(attempt-1), then `failed` with no
    further `retry` scheduled. The numbers are literals here, not read from the target's POLICY."""
    store = MemoryStore()
    queue = ReleaseQueue(store, fences=Fences())
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with store.transaction() as tx:
        tx.put("release_queue", "r1", {"id": "r1", "status": "queued", "at": start.isoformat(), "attempt": 0})
    now, trace = start, []
    for attempt, backoff in ((1, 30), (2, 60)):
        claim = queue.claim(now)
        assert claim["attempt"] == attempt
        row = queue.finish(claim, {"status": "retry", "reason": "observation"}, now)
        trace.append((row["status"], row["attempt"], row["retry_at"]))
        assert row["retry_at"] == (now + timedelta(seconds=backoff)).isoformat() and row["owner"] is None
        assert queue.claim(now + timedelta(seconds=backoff - 1)) is None, "not claimable inside its backoff"
        now += timedelta(seconds=backoff)
    claim = queue.claim(now)
    row = queue.finish(claim, {"status": "retry", "reason": "observation"}, now)
    assert (row["status"], row["attempt"], row["retry_at"]) == ("failed", 3, None)
    assert row["reason"] == "release attempt budget exhausted" and len(row["attempts"]) == 3
    assert queue.claim(now + timedelta(days=1)) is None, "no further retry is scheduled"
    assert [t[:2] for t in trace] == [("retry", 1), ("retry", 2)]


# --- guardian: unconfirmed cleanup keeps the debt (contracts.md:3531-3534) ------------------------------------------

def _kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


@POSIX
def test_a_terminate_that_cannot_be_confirmed_is_retried_a_bounded_number_of_times_then_keeps_the_debt(tmp_path):
    """contracts.md:3531-3534: "`terminate` False/raising, a parent that exited with the tree unknown, or a proof
    that cannot be persisted leave no proof, keep the debt (`debt.json: cleanup_unknown`) and record
    `unresolved.json`"; the bound is "bounded `terminate` attempts" (:3529), M7 `adapters/continuation_process.py:82`
    `CLEANUP_ATTEMPTS` = 3 (a literal here). No cleanup.json proof is written and the handle is not closed."""
    launch = "9" * 64
    directory = launch_directory(tmp_path / "rt-a", launch)
    directory.mkdir(parents=True)
    (directory / "launch.json").write_text(json.dumps({"schema": cp.GUARDIAN_SCHEMA, "launch": launch,
                                                       "token": "tok", "seconds": 1}), encoding="utf-8")
    trees, closed, terminates = [], [], []

    def spawn(argv, **kwargs):
        tree = ProcessTree.spawn(argv, **kwargs)
        trees.append(tree)
        tree.close = lambda: closed.append(True)

        def terminate(reason, **k):
            terminates.append(reason)
            return {"confirmed": False, "parent": {"confirmed": False}, "tree": {"confirmed": False}}
        tree.terminate = terminate
        return tree
    try:
        code = guard(directory, [sys.executable, "-c", "import time; time.sleep(60)"], seconds=0.3, spawn=spawn,
                     sleep=lambda s: time.sleep(min(s, 0.05)))
        assert code == EXIT_UNRESOLVED and closed == [] and not (directory / "cleanup.json").exists()
        assert json.loads((directory / "debt.json").read_text(encoding="utf-8"))["state"] == "cleanup_unknown"
        unresolved = json.loads((directory / "unresolved.json").read_text(encoding="utf-8"))
        assert unresolved["reason_code"] == "cleanup_unconfirmed" and unresolved["attempts"] == 3
        assert len(terminates) == 3, "bounded: exactly the M7 attempt budget, no unbounded retry"
        assert observe(directory)["state"] == dc.LAUNCH_UNKNOWN
    finally:
        for tree in trees:
            _kill_group(tree.process.pid)
            tree.process.wait(timeout=30)
