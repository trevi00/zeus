from copy import deepcopy

import pytest

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.releases import Releases
from codex_harness.application.tickets import Tickets, render_ticket, ticket_binding
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, digest


def content(title="검증 환경 격리"):
    return {"title": title, "problem": "Production and tests share endpoints", "impact": "Potential contention",
            "rollback": "Restore verified image", "evidence_refs": ["fixture:source-inspection"],
            "scope": ["deployment"], "acceptance_criteria": ["Independent services"],
            "verification": ["Run isolated service integration test"]}


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def tickets(request):
    store = MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")
    return Tickets(store, organization())


def test_ticket_revisions_are_immutable_and_reviews_bound_to_current_content(tickets):
    original = content()
    row = tickets.create(original)
    review = tickets.review(row["id"], 1, "Claude", "claude", "question", "How is rollback tested?", ["fixture:review"])
    assert review == tickets.review(row["id"], 1, "Claude", "claude", "question", "How is rollback tested?", ["fixture:review"])
    before = tickets.get(row["id"], 1)
    newer = tickets.update(row["id"], 1, content("Updated scope"), "Clarify acceptance")
    assert newer["revision"] == 2
    assert tickets.get(row["id"], 1)["content"] == original
    assert tickets.get(row["id"], 1)["reviews"] == before["reviews"]
    assert tickets.get(row["id"])["reviews"] == []
    with pytest.raises(ContractError, match="Stale"):
        tickets.review(row["id"], 1, "Codex", "codex", "support", "Old opinion", ["fixture:stale"])
    with pytest.raises(ContractError, match="Stale"):
        tickets.update(row["id"], 1, content("Another edit"), "Concurrent edit")
    assert tickets.get(row["id"])["content_hash"] == digest(content("Updated scope"))


def test_dispatch_is_durable_idempotent_and_stale_ticket_blocks_old_task(tickets):
    row = tickets.create(content())
    tickets.review(row["id"], 1, "Codex", "codex", "support", "Advisory only", ["fixture:review"])
    first = tickets.dispatch(row["id"], 1, "repository-commit")
    assert first == tickets.dispatch(row["id"], 1, "repository-commit")
    with tickets.store.transaction() as tx:
        outbox = tx.scan("outbox")
        assert len(outbox) == 1
        message = outbox[0]["message"]
        assert message["what"]["details"]["ticket_reviews"][0]["authority"] == "advisory_only"
        assert not tx.scan("releases") and not tx.scan("research_approvals")
    workflow = Workflow(tickets.store, tickets.org)
    task = workflow.submit(message)
    tickets.update(row["id"], 1, content("Changed topic"), "Needs new review")
    assert workflow.claim("lead:improvement", "worker") is None
    with tickets.store.transaction() as tx:
        assert tx.get("tasks", task["id"])["status"] == "blocked"
    with pytest.raises(ContractError, match="Stale"):
        tickets.dispatch(row["id"], 1, "repository-commit")


def test_topic_change_during_execution_cannot_complete_or_promote(tickets):
    ticket = tickets.create(content())
    tickets.dispatch(ticket["id"], 1, "base")
    with tickets.store.transaction() as tx:
        message = tx.scan("outbox")[0]["message"]
    workflow = Workflow(tickets.store, tickets.org)
    workflow.submit(message)
    task = workflow.claim("lead:improvement", "fixture")
    bound = message["what"]["details"]["zeus_ticket"]
    releases = Releases(tickets.store, tickets.org)
    release = releases.propose({"revision": "candidate", "base": "base", "tree": "tree",
        "author": "worker:implementation", "zeus_ticket": bound}, {"checks": ["tests"]})
    for actor in ("lead:improvement", "conductor"):
        releases.review(release["id"], actor, "candidate", True, "fixture:code-review")
    releases.verify(release["id"], "candidate", release["policy_hash"],
                    {"tests": {"passed": True, "evidence": "fixture:tests"}})
    tickets.update(ticket["id"], 1, content("Changed acceptance"), "Review again")
    finished = workflow.complete(task, {"plan": {"objective": "old"}})
    assert finished["status"] == "superseded" and finished["result"]["plan"]["objective"] == "old"
    with pytest.raises(ContractError, match="Ticket changed"):
        releases.promote(release["id"], None)
    with tickets.store.transaction() as tx:
        assert tx.get("tasks", task["id"])["status"] == "superseded"
        assert not tx.scan("deployment")


def test_nested_binding_and_export_do_not_change_authority(tickets):
    ticket = tickets.create(content())
    bound = {key: ticket[key] for key in ("id", "revision", "content_hash")}
    with tickets.store.transaction() as tx:
        assert ticket_binding(tx, {"origin": {"zeus_ticket": bound}, "candidate": {"zeus_ticket": bound}}) == bound
        with pytest.raises(ContractError, match="Conflicting"):
            ticket_binding(tx, {"zeus_ticket": bound, "other": {"zeus_ticket": {**bound, "revision": 2}}})
    before = tickets.get(ticket["id"])
    assert render_ticket(before) == render_ticket(deepcopy(before))
    assert "No review recorded" in render_ticket(before)
    assert tickets.get(ticket["id"]) == before
