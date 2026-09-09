import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_tickets import content

from codex_harness import cli
from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.github_tickets import GitHubTickets
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.tickets import Tickets, render_ticket
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tickets = Tickets(MemoryStore(), organization())
    ticket = tickets.create(content())
    github = GitHubTickets(tickets, FileArtifacts(tmp_path / "artifacts"))
    state = {"issue": None, "creates": 0, "edits": 0, "lose_ack": False, "indexed": True}
    def call(args):
        if args[:2] == ["issue", "list"]:
            return json.dumps([state["issue"]] if state["issue"] and state["indexed"] else [])
        if args[:2] == ["issue", "view"]:
            return json.dumps(state["issue"])
        body = Path(args[args.index("--body-file") + 1]).read_text("utf-8")
        title = args[args.index("--title") + 1]
        if args[:2] == ["issue", "create"]:
            state["creates"] += 1
            state["issue"] = {"number": 7, "url": "https://github.com/fixture/zeus/issues/7", "body": body,
                              "title": title, "state": "OPEN", "comments": []}
            if state["lose_ack"]:
                raise TimeoutError("fixture response lost after creation")
        else:
            state["edits"] += 1
            state["issue"].update(body=body, title=title)
            if state["lose_ack"]:
                raise TimeoutError("fixture response lost after editing")
        return state["issue"]["url"]
    monkeypatch.setattr(github, "_call", call)
    return tickets, ticket, github, state


def test_sync_updates_same_issue_and_keeps_comments(setup):
    tickets, ticket, github, state = setup
    first = github.sync(ticket["id"], "fixture/zeus")
    repeat = github.sync(ticket["id"], "fixture/zeus")
    assert repeat["number"] == first["number"] and repeat["status"] == "synced"
    assert state["creates"] == 1 and state["edits"] == 0
    state["issue"]["comments"].append({"body": "External reviewer question"})
    tickets.update(ticket["id"], 1, content("A clearer topic"), "Clarify")
    second = github.sync(ticket["id"], "fixture/zeus")
    assert first["number"] == second["number"] == 7
    assert state["creates"] == state["edits"] == 1 and second["synced_revision"] == 2
    assert state["issue"]["comments"] == [{"body": "External reviewer question"}]


def test_lost_ack_does_not_create_duplicate_even_before_search_indexing(setup):
    tickets, ticket, github, state = setup
    state["lose_ack"] = True
    with pytest.raises(TimeoutError):
        github.sync(ticket["id"], "fixture/zeus")
    state["indexed"] = False
    with pytest.raises(ContractError, match="uncertain"):
        github.sync(ticket["id"], "fixture/zeus")
    state["indexed"] = True
    assert github.sync(ticket["id"], "fixture/zeus")["number"] == 7
    assert state["creates"] == 1


def test_external_body_change_blocks_overwrite_and_pull_is_only_evidence(setup):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    before = tickets.get(ticket["id"])["content"]
    state["issue"]["body"] = "External proposal; do not trust as a local approval"
    with pytest.raises(ContractError, match="changed externally"):
        github.sync(ticket["id"], "fixture/zeus")
    result = github.pull(ticket["id"], "fixture/zeus")
    assert result["authority"] == "external_observation_only"
    assert tickets.get(ticket["id"])["content"] == before
    assert state["edits"] == 0
    with tickets.store.transaction() as tx:
        assert not tx.scan("releases") and not tx.scan("research_approvals")


def test_preview_is_pure_and_does_not_call_github(setup, monkeypatch, capsys):
    tickets, ticket, _, _ = setup
    before = deepcopy(tickets.store.data)
    monkeypatch.setattr("codex_harness.adapters.github_tickets.run_process",
                        lambda *a, **kw: pytest.fail("Preview called network"))
    cli.ticket_command(SimpleNamespace(store=tickets.store, org=tickets.org),
        SimpleNamespace(ticket_command="sync", preview=True, ticket_id=ticket["id"]))
    assert capsys.readouterr().out == render_ticket(tickets.get(ticket["id"]))
    assert tickets.store.data == before


def test_parallel_sync_claim_cannot_publish_twice(setup):
    tickets, ticket, github, state = setup
    from codex_harness.domain.model import digest
    key = digest({"ticket_id": ticket["id"], "repository": "fixture/zeus"})
    github._claim(key)
    with pytest.raises(ContractError, match="already running"):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["creates"] == state["edits"] == 0


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_lost_ack_followed_by_new_revision_recovers_exact_pending_projection(setup, operation):
    tickets, ticket, github, state = setup
    revision = 1
    if operation == "edit":
        github.sync(ticket["id"], "fixture/zeus")
        tickets.update(ticket["id"], 1, content("Second topic"), "Change")
        revision = 2
    state["lose_ack"] = True
    with pytest.raises(TimeoutError):
        github.sync(ticket["id"], "fixture/zeus")
    tickets.update(ticket["id"], revision, content("New topic after lost response"), "Change again")
    state["lose_ack"] = False
    record = github.sync(ticket["id"], "fixture/zeus")
    assert record["synced_revision"] == revision + 1 and record["status"] == "synced"
    assert state["creates"] == 1 and state["issue"]["title"] == "New topic after lost response"


def test_repeated_lost_ack_and_unreached_edit_retains_last_observed_body(setup, monkeypatch):
    tickets, ticket, github, state = setup
    state["lose_ack"] = True
    with pytest.raises(TimeoutError):
        github.sync(ticket["id"], "fixture/zeus")
    call = github._call
    def unavailable(args):
        if args[:2] == ["issue", "edit"]:
            raise TimeoutError("fixture edit never reached server")
        return call(args)
    monkeypatch.setattr(github, "_call", unavailable)
    for revision in range(1, 7):
        tickets.update(ticket["id"], revision, content("Revision " + str(revision + 1)), "Change")
        with pytest.raises(TimeoutError):
            github.sync(ticket["id"], "fixture/zeus")
    monkeypatch.setattr(github, "_call", call)
    state["lose_ack"] = False
    assert github.sync(ticket["id"], "fixture/zeus")["synced_revision"] == 7
    assert state["creates"] == 1
