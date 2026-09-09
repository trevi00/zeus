import json
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


@pytest.fixture(params=["memory", "postgres"])
def setup(request, tmp_path, monkeypatch):
    store = MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")
    tickets = Tickets(store, organization())
    ticket = tickets.create(content())
    github = GitHubTickets(tickets, FileArtifacts(tmp_path / "artifacts"))
    state = {"issue": None, "creates": 0, "edits": 0, "lose_ack": False, "indexed": True}
    def call(args):
        if args[:2] == ["issue", "list"]:
            fields = args[args.index("--json") + 1].split(",")
            return json.dumps([{k: state["issue"][k] for k in fields}]
                              if state["issue"] and state["indexed"] else [])
        if args[:2] == ["issue", "view"]:
            return json.dumps(state["issue"])
        if args[:2] in (["issue", "close"], ["issue", "reopen"]):
            state["issue"]["state"] = "CLOSED" if args[1] == "close" else "OPEN"
            state.setdefault("state_writes", []).append(args[1])
            if state["lose_ack"]:
                raise TimeoutError("fixture response lost after state change")
            return state["issue"]["url"]
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
    with tickets.store.transaction() as tx:
        before = tx.records()
    monkeypatch.setattr("codex_harness.adapters.github_tickets.run_process",
                        lambda *a, **kw: pytest.fail("Preview called network"))
    cli.ticket_command(SimpleNamespace(store=tickets.store, org=tickets.org),
        SimpleNamespace(ticket_command="sync", preview=True, ticket_id=ticket["id"]))
    assert capsys.readouterr().out == render_ticket(tickets.get(ticket["id"]))
    with tickets.store.transaction() as tx:
        assert tx.records() == before


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


def test_remote_manual_close_is_a_conflict_not_local_acceptance(setup):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"]["state"] = "CLOSED"
    result = github.sync(ticket["id"], "fixture/zeus")
    assert result["status"] == "state_conflict"
    assert result["observed_state"] == "CLOSED" and result["desired_state"] == "OPEN"
    assert tickets.get(ticket["id"])["status"] == "open"
    assert tickets.get(ticket["id"])["external_observations"][-1]["state"] == "CLOSED"
    assert state["edits"] == 0


def test_external_title_change_is_preserved_and_invalidates_synced_status(setup):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"]["title"] = "An external reviewer changed the topic"
    with pytest.raises(ContractError, match="title changed externally"):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["issue"]["title"] == "An external reviewer changed the topic"
    assert state["edits"] == 0
    assert tickets.get(ticket["id"])["github"][0]["status"] == "needs_attention"
    observation = tickets.get(ticket["id"])["external_observations"][-1]
    assert github.artifacts.document(observation["evidence_ref"])["title"] == state["issue"]["title"]


def test_successful_edit_response_requires_matching_remote_readback(setup, monkeypatch):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    tickets.update(ticket["id"], 1, content("New canonical title"), "Clarify")
    call = github._call
    def acknowledged_without_write(args):
        if args[:2] == ["issue", "edit"]:
            return state["issue"]["url"]
        return call(args)
    monkeypatch.setattr(github, "_call", acknowledged_without_write)
    with pytest.raises(ContractError, match="readback"):
        github.sync(ticket["id"], "fixture/zeus")
    assert tickets.get(ticket["id"])["github"][0]["status"] == "needs_attention"
    monkeypatch.setattr(github, "_call", call)
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"


def test_reconciliation_is_bound_to_observed_issue_and_current_revision(setup):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"].update(title="External proposal", body="External text")
    observation = github.pull(ticket["id"], "fixture/zeus")
    with pytest.raises(ContractError, match="current ticket revision"):
        github.sync(ticket["id"], "fixture/zeus", reconcile_observation=observation["id"])
    state["issue"]["body"] = "Another external edit"
    with pytest.raises(ContractError, match="changed since reconciliation"):
        github.sync(ticket["id"], "fixture/zeus", reconcile_observation=observation["id"], expected_revision=1)
    current = github.pull(ticket["id"], "fixture/zeus")
    result = github.sync(ticket["id"], "fixture/zeus", reconcile_observation=current["id"], expected_revision=1)
    assert result["status"] == "synced" and state["edits"] == 1
    assert state["issue"]["body"] == render_ticket(tickets.get(ticket["id"]))
    assert github.artifacts.document(observation["evidence_ref"])["body"] == "External text"
    assert tickets.get(ticket["id"])["status"] == "open"


def test_legacy_link_uses_its_original_revision_title(setup):
    tickets, ticket, github, state = setup
    link = github.sync(ticket["id"], "fixture/zeus")
    with tickets.store.transaction() as tx:
        old = tx.get("ticket_github", link["id"])
        old.pop("title_hash")
        tx.put("ticket_github", link["id"], old)
        sync = tx.get("ticket_syncs", link["id"])
        sync.pop("observed_title_hash")
        tx.put("ticket_syncs", link["id"], sync)
    tickets.update(ticket["id"], 1, content("Updated legacy topic"), "Clarify")
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    assert state["issue"]["title"] == "Updated legacy topic"


def test_created_number_survives_readback_failure_without_search_index(setup, monkeypatch):
    tickets, ticket, github, state = setup
    call = github._call
    def unavailable_readback(args):
        if args[:2] == ["issue", "view"]:
            raise TimeoutError("Readback unavailable after a successful create")
        return call(args)
    monkeypatch.setattr(github, "_call", unavailable_readback)
    with pytest.raises(TimeoutError):
        github.sync(ticket["id"], "fixture/zeus")
    state["indexed"] = False
    monkeypatch.setattr(github, "_call", call)
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    assert state["creates"] == 1


def test_local_status_change_during_readback_cannot_be_synced(setup, monkeypatch):
    tickets, ticket, github, state = setup
    call = github._call
    def change_local_status(args):
        result = call(args)
        if args[:2] == ["issue", "view"]:
            with tickets.store.transaction() as tx:
                row = tx.get("tickets", ticket["id"])
                tx.put("tickets", ticket["id"], {**row, "status": "dispatched"})
        return result
    monkeypatch.setattr(github, "_call", change_local_status)
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "outdated"


def test_expired_lease_after_remote_write_cannot_record_success(setup, monkeypatch):
    tickets, ticket, github, state = setup
    from codex_harness.domain.model import digest
    key = digest({"ticket_id": ticket["id"], "repository": "fixture/zeus"})
    call = github._call
    def expire_on_readback(args):
        result = call(args)
        if args[:2] == ["issue", "view"]:
            with tickets.store.transaction() as tx:
                claim = tx.get("ticket_syncs", key)
                tx.put("ticket_syncs", key, {**claim, "lease_until": "2000-01-01T00:00:00+00:00"})
        return result
    monkeypatch.setattr(github, "_call", expire_on_readback)
    with pytest.raises(ContractError, match="Stale ticket sync"):
        github.sync(ticket["id"], "fixture/zeus")
    assert tickets.get(ticket["id"])["github"] == []
    assert tickets.get(ticket["id"])["external_observations"]
    monkeypatch.setattr(github, "_call", call)
    state["indexed"] = False
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    assert state["creates"] == 1


def test_identical_sync_observations_are_bounded_and_plain_revision_is_checked(setup):
    tickets, ticket, github, state = setup
    for _ in range(4):
        github.sync(ticket["id"], "fixture/zeus")
    assert len(tickets.get(ticket["id"])["external_observations"]) == 2
    with pytest.raises(ContractError, match="Stale ticket sync revision"):
        github.sync(ticket["id"], "fixture/zeus", expected_revision=2)
    assert state["creates"] == 1 and state["edits"] == 0


def test_legacy_link_does_not_trust_an_arbitrary_observed_title(setup):
    tickets, ticket, github, state = setup
    link = github.sync(ticket["id"], "fixture/zeus")
    with tickets.store.transaction() as tx:
        row = tx.get("ticket_github", link["id"])
        row.pop("title_hash")
        tx.put("ticket_github", link["id"], row)
    state["issue"]["title"] = "Unknown legacy title"
    with pytest.raises(ContractError, match="title changed externally"):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["edits"] == 0


def test_create_ack_after_lease_expiry_is_retained_for_recovery(setup, monkeypatch):
    tickets, ticket, github, state = setup
    from codex_harness.domain.model import digest
    key = digest({"ticket_id": ticket["id"], "repository": "fixture/zeus"})
    call = github._call
    def expire_before_ack(args):
        result = call(args)
        if args[:2] == ["issue", "create"]:
            with tickets.store.transaction() as tx:
                claim = tx.get("ticket_syncs", key)
                tx.put("ticket_syncs", key, {**claim, "lease_until": "2000-01-01T00:00:00+00:00"})
        return result
    monkeypatch.setattr(github, "_call", expire_before_ack)
    with pytest.raises(ContractError, match="Stale ticket sync"):
        github.sync(ticket["id"], "fixture/zeus")
    with tickets.store.transaction() as tx:
        assert tx.scan("ticket_remote_creations")[0]["number"] == 7
        assert tx.get("ticket_github", key) is None
    state["indexed"] = False
    monkeypatch.setattr(github, "_call", call)
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    assert state["creates"] == 1


def test_dispatch_bounds_external_observations_without_deleting_evidence(setup):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    for n in range(15):
        state["issue"]["title"] = f"External observation {n}"
        github.pull(ticket["id"], "fixture/zeus")
    result = tickets.dispatch(ticket["id"], 1, "repository-revision")
    with tickets.store.transaction() as tx:
        details = tx.get("outbox", result["message_id"])["message"]["what"]["details"]
        assert len(tx.scan("ticket_remote_observations")) == 16
    assert len(details["external_ticket_observations"]) == 10
    assert details["external_ticket_observations_total"] == 16
    assert details["external_ticket_observations_omitted"] == 6


@pytest.mark.parametrize("field", ["body", "title"])
def test_failed_reconcile_does_not_authorize_plain_retry_after_revision_change(setup, monkeypatch, field):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"][field] = "External content requiring explicit reconciliation"
    observation = github.pull(ticket["id"], "fixture/zeus")
    call = github._call
    def unavailable(args):
        if args[:2] == ["issue", "edit"]:
            raise TimeoutError("Edit never reached GitHub")
        return call(args)
    monkeypatch.setattr(github, "_call", unavailable)
    with pytest.raises(TimeoutError):
        github.sync(ticket["id"], "fixture/zeus", expected_revision=1,
                    reconcile_observation=observation["id"])
    monkeypatch.setattr(github, "_call", call)
    with pytest.raises(ContractError, match="changed externally"):
        github.sync(ticket["id"], "fixture/zeus")
    tickets.update(ticket["id"], 1, content("New local revision"), "Revise after failed reconciliation")
    with pytest.raises(ContractError, match="changed externally"):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["edits"] == 0
    assert state["issue"][field] == "External content requiring explicit reconciliation"
    assert github.sync(ticket["id"], "fixture/zeus", expected_revision=2,
                       reconcile_observation=observation["id"])["status"] == "synced"


def test_closed_issue_reconciliation_does_not_trust_unwritten_foreign_content(setup):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"].update(body="External content", title="External topic", state="CLOSED")
    observation = github.pull(ticket["id"], "fixture/zeus")
    assert github.sync(ticket["id"], "fixture/zeus", expected_revision=1,
                       reconcile_observation=observation["id"])["status"] == "state_conflict"
    state["issue"]["state"] = "OPEN"
    with pytest.raises(ContractError, match="changed externally"):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["edits"] == 0


def test_closed_issue_readback_does_not_promote_new_external_content_to_trusted(setup, monkeypatch):
    tickets, ticket, github, state = setup
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"]["state"] = "CLOSED"
    call = github._call
    reads = 0
    def change_on_readback(args):
        nonlocal reads
        if args[:2] == ["issue", "view"]:
            reads += 1
            if reads == 2:
                state["issue"]["body"] = "Changed during conflict readback"
        return call(args)
    monkeypatch.setattr(github, "_call", change_on_readback)
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "state_conflict"
    monkeypatch.setattr(github, "_call", call)
    state["issue"]["state"] = "OPEN"
    with pytest.raises(ContractError, match="changed externally"):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["edits"] == 0
