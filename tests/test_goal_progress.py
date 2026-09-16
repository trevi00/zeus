"""INV-GOAL-PROGRESS-001 fixed acceptance matrix (docs/zeus/operations/goal-progress-001/SPEC.md).

The lifecycle fixture signs with a test-only key; its closures show the compatible record shape and
are not human or product acceptance evidence. Injected corruptions are labelled as such.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_ticket_lifecycle import github_setup, lifecycle  # noqa: F401
from test_tickets import content

from codex_harness import cli
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.goal_progress import (
    SCHEMA,
    GoalProgress,
    compare_reports,
    definition_hash,
    validate_manifest,
)
from codex_harness.application.service import Harness
from codex_harness.application.tickets import TicketClosed, Tickets
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.model import ContractError, canonical


def manifest(ticket, goal_id="goal-1", criterion_id="c1", **override):
    return {"version": 1, "id": goal_id, "objective": "Resolve the fixture residual", "non_goals": ["Deploy"],
            "criteria": [{"id": criterion_id, "acceptance": "Ticket closed with local evidence",
                          "ticket_id": ticket["id"], "revision": ticket["revision"],
                          "content_hash": ticket["content_hash"], **override}]}


def report(store, definition):
    before = deepcopy(getattr(store, "data", None))
    result = GoalProgress(store).report(definition)
    assert getattr(store, "data", None) == before  # observation writes nothing
    assert result["schema"] == SCHEMA and result["authority"] == "observation_only"
    assert result["definition_hash"] == definition_hash(definition)
    return result


def counts(store):
    with store.transaction() as tx:
        return {bucket: len(tx.scan(bucket)) for bucket in
                ("outbox", "ticket_dispatches", "tasks", "ticket_lifecycle_events")}


def close(life, prepare, sign):
    packet = prepare()
    return life.close(packet["packet_ref"], sign(packet["packet_ref"]))["decision"]


# ----- 1. pending -> valid close -> resolved; repeat unchanged, no writes ------------------------
def test_row1_pending_then_local_close_resolves_exact_denominator(lifecycle):  # noqa: F811
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    store, definition = life.store, manifest(ticket)
    first = report(store, definition)
    assert first["criteria"][0]["status"] == "pending" and "closure" not in first["criteria"][0]
    assert first["metrics"] == {"total": 1, "resolved": 0, "remaining": 1, "reopened": 0, "missing": 0,
                                "stale": 0, "unverified": 0, "completion_ratio": 0.0}
    assert report(store, definition) == first
    event = close(life, prepare, sign)
    second = report(store, definition)
    assert second["criteria"][0]["status"] == "resolved"
    assert second["criteria"][0]["closure"] == {"event_id": event["id"], "packet_ref": event["packet_ref"],
                                                "proof_ref": event["proof_ref"]}
    assert second["metrics"]["resolved"] == 1 and second["metrics"]["remaining"] == 0
    assert second["metrics"]["completion_ratio"] == 1.0 and second["goal_id"] == "goal-1"
    assert report(store, definition) == second and second["definition_hash"] == first["definition_hash"]


# ----- 2. activity is not progress; missing/stale/corrupt are explicit non-resolved ------------
def test_row2_remote_close_review_vote_and_task_success_do_not_count(lifecycle):  # noqa: F811
    life, ticket, github, state, prepare, sign, _, _ = lifecycle
    tickets, store, definition = life.tickets, life.store, manifest(ticket)
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"]["state"] = "CLOSED"  # remote issue closed without local acceptance
    tickets.review(ticket["id"], 1, "Codex", "codex", "support", "Looks done", ["fixture:review"])
    dispatched = tickets.dispatch(ticket["id"], 1, "repository")
    with store.transaction() as tx:
        message = tx.get("outbox", dispatched["message_id"])["message"]
    task = Workflow(store, tickets.org).submit(message)
    with store.transaction() as tx:
        tx.put("tasks", task["id"], {**tx.get("tasks", task["id"]), "status": "succeeded"})
    observed = report(store, definition)
    assert observed["criteria"][0]["status"] == "pending" and observed["metrics"]["resolved"] == 0
    assert report(store, manifest({**ticket, "id": "ZEUS-absent00000"}))["criteria"][0]["status"] == "missing"
    assert report(store, manifest(ticket, revision=2))["criteria"][0]["status"] == "missing"
    event = close(life, prepare, sign)
    assert report(store, definition)["criteria"][0]["status"] == "resolved"
    packet_ref = event["packet_ref"]
    with store.transaction() as tx:  # injected fault: closure receipt names another event
        tx.put("ticket_closures", packet_ref, {"packet_ref": packet_ref, "event_id": "0" * 64})
    assert report(store, definition)["criteria"][0]["status"] == "unverified"
    with store.transaction() as tx:  # injected fault: tampered lifecycle event breaks the chain
        tx.put("ticket_closures", packet_ref, {"packet_ref": packet_ref, "event_id": event["id"]})
        tx.put("ticket_lifecycle_events", event["id"], {**event, "reason": "Tampered"})
    assert report(store, definition)["criteria"][0]["status"] == "unverified"
    with store.transaction() as tx:  # injected fault: closed status without any closure decision
        tx.put("ticket_lifecycle_events", event["id"], event)
        current = tx.get("tickets", ticket["id"])
        tx.put("tickets", ticket["id"], {**current, "lifecycle_sequence": 0, "lifecycle_event": None})
    assert report(store, definition)["criteria"][0]["status"] == "unverified"
    with store.transaction() as tx:
        tx.put("tickets", ticket["id"], current)
    assert report(store, definition)["criteria"][0]["status"] == "resolved"


def test_row2_stale_revision_and_corrupted_revision_content_are_not_resolved():
    store = MemoryStore()
    tickets = Tickets(store, organization())
    ticket = tickets.create(content())
    definition = manifest(ticket)
    tickets.update(ticket["id"], 1, content("Changed topic"), "Revise")
    assert report(store, definition)["criteria"][0]["status"] == "stale"
    current = tickets.get(ticket["id"])
    definition = manifest({**ticket, "revision": 2, "content_hash": current["content_hash"]})
    assert report(store, definition)["criteria"][0]["status"] == "pending"
    with store.transaction() as tx:  # injected fault: revision content no longer matches its hash
        row = tx.get("ticket_revisions", ticket["id"] + ":2")
        tx.put("ticket_revisions", ticket["id"] + ":2", {**row, "content": {**row["content"], "title": "x"}})
    assert report(store, definition)["criteria"][0]["status"] == "unverified"
    with store.transaction() as tx:  # injected fault: closed status with a fabricated event reference
        tx.put("ticket_revisions", ticket["id"] + ":2", row)
        tx.put("tickets", ticket["id"], {**tx.get("tickets", ticket["id"]), "status": "closed",
                                         "lifecycle_sequence": 1, "lifecycle_event": "f" * 64})
    assert report(store, definition)["criteria"][0]["status"] == "unverified"
    assert report(store, definition)["metrics"]["remaining"] == 1


# ----- 3. reopen regresses; definition change is a new denominator ------------------------------
def test_row3_reopen_regresses_and_changed_definition_is_not_comparable(lifecycle):  # noqa: F811
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    store, definition = life.store, manifest(ticket)
    close(life, prepare, sign)
    resolved = report(store, definition)
    life.reopen(ticket["id"], 1, 1, "Recurrence")
    reopened = report(store, definition)
    assert reopened["criteria"][0]["status"] == "reopened" and reopened["metrics"]["reopened"] == 1
    assert reopened["metrics"]["resolved"] == 0 and reopened["metrics"]["remaining"] == 1
    comparison = compare_reports(resolved, reopened)
    assert comparison == {"authority": "observation_only", "goal_id": "goal-1",
                          "definition_hash": resolved["definition_hash"], "gained": [], "regressed": ["c1"],
                          "net_resolved": -1}
    assert compare_reports(reopened, resolved)["gained"] == ["c1"]
    assert compare_reports(resolved, resolved)["net_resolved"] == 0
    dispatched = life.tickets.dispatch(ticket["id"], 1, "repository", goal_manifest=definition, criterion_id="c1")
    assert dispatched["goal_binding"]["criterion_id"] == "c1"
    close(life, prepare, sign)
    again = report(store, definition)
    assert again["criteria"][0]["status"] == "resolved" and compare_reports(reopened, again)["gained"] == ["c1"]
    changed = manifest(ticket, revision=2)
    assert definition_hash(changed) != definition_hash(definition)
    with pytest.raises(ContractError, match="not comparable"):
        compare_reports(resolved, {**reopened, "definition_hash": definition_hash(changed)})
    with pytest.raises(ContractError, match="not comparable"):
        compare_reports(resolved, report(store, manifest(ticket, goal_id="goal-2")))
    with pytest.raises(ContractError, match="bindings differ"):
        compare_reports(resolved, {**reopened, "criteria": [{**reopened["criteria"][0], "revision": 2}]})
    inflated = {**reopened, "metrics": {**reopened["metrics"], "resolved": 1}}
    assert compare_reports(resolved, inflated)["regressed"] == ["c1"]  # statuses decide, not metrics


# ----- 4. goal-bound dispatch ---------------------------------------------------------------------
def test_row4_goal_bound_dispatch_is_atomic_idempotent_and_distinct():
    store = MemoryStore()
    tickets = Tickets(store, organization())
    first, other = tickets.create(content()), tickets.create(content("Other topic"))
    definition = manifest(first)
    unbound = tickets.dispatch(first["id"], 1, "repository")
    assert "goal_binding" not in unbound
    assert unbound == tickets.dispatch(first["id"], 1, "repository")
    bound = tickets.dispatch(first["id"], 1, "repository", goal_manifest=definition, criterion_id="c1")
    assert bound["id"] != unbound["id"]
    assert bound["goal_binding"] == {"id": "goal-1", "definition_hash": definition_hash(definition),
                                     "criterion_id": "c1"}
    assert bound == tickets.dispatch(first["id"], 1, "repository", goal_manifest=definition, criterion_id="c1")
    with store.transaction() as tx:
        details = tx.get("outbox", bound["message_id"])["message"]["what"]["details"]
        assert details["goal_binding"] == bound["goal_binding"] and details["zeus_ticket"]["id"] == first["id"]
        assert "goal_binding" not in tx.get("outbox", unbound["message_id"])["message"]["what"]["details"]
    other_goal = tickets.dispatch(first["id"], 1, "repository", goal_manifest=manifest(first, goal_id="goal-2"),
                                  criterion_id="c1")
    assert other_goal["id"] not in {bound["id"], unbound["id"]} and other_goal["goal_binding"]["id"] == "goal-2"
    before = counts(store)
    refusals = [
        ("not in manifest", dict(goal_manifest=definition, criterion_id="c9")),
        ("required together", dict(goal_manifest=definition)),
        ("required together", dict(criterion_id="c1")),
        ("does not match", dict(goal_manifest=manifest(first, revision=1, content_hash="a" * 64), criterion_id="c1")),
        ("Duplicate", dict(goal_manifest={**definition, "criteria": definition["criteria"] * 2}, criterion_id="c1")),
    ]
    for match, kwargs in refusals:
        with pytest.raises(ContractError, match=match):
            tickets.dispatch(first["id"], 1, "repository", **kwargs)
    with pytest.raises(ContractError, match="does not match"):  # unmapped ticket for a mapped criterion
        tickets.dispatch(other["id"], 1, "repository", goal_manifest=definition, criterion_id="c1")
    tickets.update(other["id"], 1, content("Revised other"), "Revise")
    stale = manifest(other, goal_id="goal-3")  # binding still names revision 1
    with pytest.raises(ContractError, match="Stale"):
        tickets.dispatch(other["id"], 1, "repository", goal_manifest=stale, criterion_id="c1")
    with pytest.raises(ContractError, match="does not match"):
        tickets.dispatch(other["id"], 2, "repository", goal_manifest=stale, criterion_id="c1")
    assert counts(store) == before
    with store.transaction() as tx:
        assert tx.get("tickets", other["id"])["status"] == "open"
        assert len(tx.scan("ticket_dispatches")) == 3


def test_row4_resolved_and_unverified_criteria_refuse_dispatch_before_writes(lifecycle):  # noqa: F811
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    tickets, store, definition = life.tickets, life.store, manifest(ticket)
    event = close(life, prepare, sign)
    before = counts(store)
    with pytest.raises(TicketClosed):
        tickets.dispatch(ticket["id"], 1, "repository", goal_manifest=definition, criterion_id="c1")
    assert counts(store) == before
    life.reopen(ticket["id"], 1, 1, "Recurrence")
    with store.transaction() as tx:  # injected fault: tampered history makes the chain unverifiable
        tx.put("ticket_lifecycle_events", event["id"], {**event, "reason": "Tampered"})
    before = counts(store)
    with pytest.raises(ContractError):
        tickets.dispatch(ticket["id"], 1, "repository", goal_manifest=definition, criterion_id="c1")
    assert counts(store) == before
    with store.transaction() as tx:
        tx.put("ticket_lifecycle_events", event["id"], event)
    assert tickets.dispatch(ticket["id"], 1, "repository", goal_manifest=definition,
                            criterion_id="c1")["goal_binding"]["criterion_id"] == "c1"


# ----- 5. invalid inputs, unknown shapes, store failures -----------------------------------------
def valid_manifest():
    return manifest({"id": "ZEUS-000000000001", "revision": 1, "content_hash": "0" * 64})


@pytest.mark.parametrize("mutate", [
    lambda m: m.pop("non_goals"),
    lambda m: m.update(extra=1),
    lambda m: m.update(version="1"),
    lambda m: m.update(version=True),
    lambda m: m.update(id=" "),
    lambda m: m.update(objective=""),
    lambda m: m.update(non_goals="none"),
    lambda m: m.update(non_goals=[1]),
    lambda m: m.update(criteria=[]),
    lambda m: m.update(criteria="c1"),
    lambda m: m.update(criteria=[dict(m["criteria"][0], id="c" + str(i)) for i in range(51)]),
    lambda m: m["criteria"][0].pop("acceptance"),
    lambda m: m["criteria"][0].update(note="x"),
    lambda m: m["criteria"][0].update(acceptance=" "),
    lambda m: m["criteria"][0].update(revision=0),
    lambda m: m["criteria"][0].update(revision=True),
    lambda m: m["criteria"][0].update(revision="1"),
    lambda m: m["criteria"][0].update(content_hash="A" * 64),
    lambda m: m["criteria"][0].update(content_hash="0" * 63),
    lambda m: m["criteria"].append(dict(m["criteria"][0], ticket_id="ZEUS-000000000002")),
    lambda m: m["criteria"].append(dict(m["criteria"][0], id="c2")),
])
def test_row5_invalid_duplicate_or_empty_manifests_are_rejected(mutate):
    definition = valid_manifest()
    assert validate_manifest(definition) == definition
    mutate(definition)
    with pytest.raises(ContractError):
        validate_manifest(definition)
    with pytest.raises(ContractError):
        GoalProgress(MemoryStore()).report(definition)


def test_row5_unknown_compare_shapes_and_store_failures():
    store = MemoryStore()
    ticket = Tickets(store, organization()).create(content())
    good = report(store, manifest(ticket))
    bad_shapes = [None, {}, {**good, "schema": "urn:zeus:cycle-handoff:1"}, {**good, "authority": "approved"},
                  {**good, "extra": 1}, {**good, "criteria": []},
                  {**good, "criteria": [{**good["criteria"][0], "status": "done"}]},
                  {**good, "criteria": good["criteria"] * 2},
                  {**good, "criteria": [{**good["criteria"][0], "raw": {}}]},
                  {**good, "definition_hash": "x"}]
    for shape in bad_shapes:
        with pytest.raises(ContractError):
            compare_reports(good, shape)
        with pytest.raises(ContractError):
            compare_reports(shape, good)

    class BrokenStore:
        def transaction(self):
            raise RuntimeError("store unavailable")
    with pytest.raises(RuntimeError, match="store unavailable"):
        GoalProgress(BrokenStore()).report(manifest(ticket))
    with pytest.raises(RuntimeError, match="store unavailable"):
        Tickets(BrokenStore(), organization()).dispatch(ticket["id"], 1, "repository",
                                                        goal_manifest=manifest(ticket), criterion_id="c1")


# ----- 6. CLI wiring without provider side effects ------------------------------------------------
def test_row6_cli_report_compare_and_dispatch_options(tmp_path, monkeypatch):
    svc = Harness(MemoryStore(), organization())
    tickets = Tickets(svc.store, svc.org)
    ticket = tickets.create(content())
    definition = manifest(ticket)
    manifest_path = tmp_path / "goal.json"
    manifest_path.write_text(canonical(definition), encoding="utf-8")
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)

    def forbidden(*args, **kwargs):
        raise AssertionError("goal command built infrastructure")
    for name in ("build_executor", "build_observer", "RedisBus", "redis_url", "Workflow", "build"):
        monkeypatch.setattr(cli, name, forbidden)
    cli.goal_command(svc, cli.parser().parse_args(["goal", "report", str(manifest_path)]))
    first = outputs[-1]
    assert first == GoalProgress(svc.store).report(definition) and first["criteria"][0]["status"] == "pending"
    (tmp_path / "before.json").write_text(canonical(first), encoding="utf-8")
    (tmp_path / "after.json").write_text(canonical(first), encoding="utf-8")
    cli.goal_command(None, cli.parser().parse_args(["goal", "compare", str(tmp_path / "before.json"),
                                                    str(tmp_path / "after.json")]))
    assert outputs[-1]["net_resolved"] == 0 and outputs[-1]["authority"] == "observation_only"
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ContractError, match="not valid JSON"):
        cli.goal_command(svc, cli.parser().parse_args(["goal", "report", str(tmp_path / "broken.json")]))
    with pytest.raises(ContractError, match="unavailable"):
        cli.goal_command(svc, cli.parser().parse_args(["goal", "report", str(tmp_path / "absent.json")]))
    monkeypatch.setattr(cli, "build_executor",
                        lambda service: SimpleNamespace(git=SimpleNamespace(_git=lambda *a: "head-sha")))
    args = cli.parser().parse_args(["ticket", "dispatch", ticket["id"], "--revision", "1",
                                    "--goal-manifest", str(manifest_path), "--criterion", "c1"])
    cli.ticket_command(svc, args)
    dispatched = outputs[-1]
    assert dispatched["goal_binding"] == {"id": "goal-1", "definition_hash": definition_hash(definition),
                                          "criterion_id": "c1"}
    cli.ticket_command(svc, cli.parser().parse_args(["ticket", "dispatch", ticket["id"], "--revision", "1"]))
    assert "goal_binding" not in outputs[-1] and outputs[-1]["id"] != dispatched["id"]
    with pytest.raises(ContractError, match="required together"):
        cli.ticket_command(svc, cli.parser().parse_args(["ticket", "dispatch", ticket["id"], "--revision", "1",
                                                         "--criterion", "c1"]))
    with svc.store.transaction() as tx:
        assert len(tx.scan("outbox")) == 2 and len(tx.scan("ticket_dispatches")) == 2
