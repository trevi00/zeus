from types import SimpleNamespace

import pytest
from test_tickets import content

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.store import MemoryStore, MemoryTransaction
from codex_harness.application.service import Harness
from codex_harness.application.tickets import Tickets, ticket_binding
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError


@pytest.fixture
def execution(tmp_path, monkeypatch):
    service = Harness(MemoryStore(), organization())
    tickets = Tickets(service.store, service.org)
    ticket = tickets.create(content())
    git = SimpleNamespace(repository=tmp_path, remote=None,
        is_ancestor=lambda *a: False,
        _git=lambda *a, **k: "" if a[0] == "status" else "candidate",
        prepare=lambda *a: {"path": str(tmp_path)},
        capture=lambda *a: {"revision": "candidate", "base": "base", "tree": "tree", "author": "worker:implementation"},
        inspect=lambda *a: {}, review_workspace=lambda *a: str(tmp_path))
    executor = Executor(service, git, FileArtifacts(tmp_path / "artifacts"))
    monkeypatch.setattr(executor, "_run", lambda *a, **k:
        {"objective": "fixture plan", "accepted": True, "reason": "fixture", "execution_ref": "fixture:model"})
    tickets.dispatch(ticket["id"], 1, "base")
    with service.store.transaction() as tx:
        message = tx.scan("outbox")[0]["message"]
    executor.workflow.submit(message)
    plan = executor.execute_one("lead:improvement")
    assert plan["status"] == "succeeded"
    with service.store.transaction() as tx:
        assignment = next(r["message"] for r in tx.scan("outbox")
                          if r["message"]["what"]["action"] == "implement")
    executor.workflow.submit(assignment)
    implementation = executor.execute_one("worker:implementation")
    assert implementation["status"] == "succeeded"
    with service.store.transaction() as tx:
        report = next(r["message"] for r in tx.scan("outbox")
            if r["message"]["type"] == "task.result" and r["message"]["what"]["action"] == "implement")
    executor.workflow.handle(report)
    return tickets, ticket, executor, implementation


@pytest.mark.parametrize("accepted", [True, False])
def test_real_plan_implementation_and_review_transitions_keep_ticket(execution, monkeypatch, accepted):
    tickets, ticket, executor, implementation = execution
    bound = {k: ticket[k] for k in ("id", "revision", "content_hash")}
    assert implementation["result"]["candidate"]["zeus_ticket"] == bound
    monkeypatch.setattr(executor, "_run", lambda *a, **k:
        {"accepted": accepted, "reason": "fixture", "execution_ref": "fixture:review"})
    result = executor.decide_one("lead:improvement")
    assert result["status"] == "succeeded"
    with tickets.store.transaction() as tx:
        downstream = next(r["message"] for r in tx.scan("outbox")
            if (r["message"]["type"] == "review.result" if accepted
                else r["message"]["what"]["details"].get("rework") == 1))
        assert ticket_binding(tx, downstream) == bound
        assert tx.scan("releases")[0]["candidate"]["zeus_ticket"] == bound
    if accepted:
        executor.workflow.handle(downstream)
        assert executor.decide_one("conductor")["status"] == "succeeded"
        with tickets.store.transaction() as tx:
            assert len(tx.scan("release_queue")) == 1


@pytest.mark.parametrize("during", [False, True])
def test_stale_decision_preserves_results_without_model_retry(execution, monkeypatch, during):
    tickets, ticket, executor, _ = execution
    calls = []
    def edit():
        tickets.update(ticket["id"], 1, content("Changed criteria"), "New requirement")
    def review(*args, **kwargs):
        calls.append(1)
        edit()
        return {"accepted": True, "reason": "old topic", "execution_ref": "fixture:old-review"}
    monkeypatch.setattr(executor, "_run", review)
    if not during:
        edit()
    executor.decide_one("lead:improvement")
    assert executor.decide_one("lead:improvement") is None
    with tickets.store.transaction() as tx:
        decision = tx.scan("decisions_pending")[0]
        assert decision["status"] == "superseded"
        if during:
            assert decision["result"]["execution_ref"] == "fixture:old-review"
        assert not tx.scan("releases") and not tx.scan("release_queue")
    assert len(calls) == int(during)


def test_dispatch_and_outbox_roll_back_together(tmp_path, monkeypatch):
    tickets = Tickets(MemoryStore(), organization())
    ticket = tickets.create(content())
    put = MemoryTransaction.put
    def fail(tx, bucket, key, value):
        if bucket == "ticket_dispatches":
            raise OSError("fixture commit failure")
        put(tx, bucket, key, value)
    monkeypatch.setattr(MemoryTransaction, "put", fail)
    with pytest.raises(OSError):
        tickets.dispatch(ticket["id"], 1, "base")
    with tickets.store.transaction() as tx:
        assert not tx.scan("outbox") and not tx.scan("ticket_dispatches")
        assert tx.get("tickets", ticket["id"])["status"] == "open"


def test_canary_results_are_retained_when_topic_changes(execution):
    tickets, ticket, executor, implementation = execution
    releases = executor.releases
    candidate = implementation["result"]["candidate"]
    release = releases.propose(candidate, {"checks": ["tests"]})
    for actor in ("lead:improvement", "conductor"):
        releases.review(release["id"], actor, "candidate", True, "fixture:review")
    tickets.update(ticket["id"], 1, content("Changed during canary"), "New requirement")
    checks = {"tests": {"passed": True, "evidence": "fixture:executed"}}
    result = releases.verify(release["id"], "candidate", release["policy_hash"], checks)
    assert result["status"] == "superseded_by_ticket_revision" and result["checks"] == checks
    with pytest.raises(ContractError, match="not verified"):
        releases.promote(release["id"], None)


@pytest.mark.parametrize("abandon", [False, True])
def test_promotion_freezes_ticket_until_recovered_or_safely_abandoned(execution, monkeypatch, abandon):
    tickets, ticket, executor, implementation = execution
    release = executor.releases.propose(implementation["result"]["candidate"], {"checks": ["tests"]})
    for actor in ("lead:improvement", "conductor"):
        executor.releases.review(release["id"], actor, "candidate", True, "fixture:review")
    executor.releases.verify(release["id"], "candidate", release["policy_hash"],
                            {"tests": {"passed": True, "evidence": "fixture:tests"}})
    with tickets.store.transaction() as tx:
        tx.put("images", release["id"], {"image": "sha256:fixture"})
    monkeypatch.setattr(executor.git, "_git", lambda *a: "" if a[0] == "status" else "base")
    runner = ReleaseRunner(executor.service, executor.git, executor.artifacts, "unused")
    def merge(candidate):
        with pytest.raises(ContractError, match="promotion unresolved"):
            tickets.update(ticket["id"], 1, content("Edit during merge"), "Race")
        if abandon:
            raise ConnectionError("fixture stopped before merge")
        return {"merged": True, "revision": "candidate", "transport": "local"}
    executor.git.merge = merge
    if abandon:
        with pytest.raises(ConnectionError):
            runner.run(release["id"])
        assert runner.abandon(release["id"], "Revise request")["status"] == "abandoned"
    else:
        assert runner.run(release["id"])["status"] == "active"
    assert tickets.update(ticket["id"], 1, content("Next topic"), "After recovery")["revision"] == 2
