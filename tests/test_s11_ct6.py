"""S11 unit CT-6: behavioural characterization of four contracts (DESIGN-s11 §5 G2, the D3/D4 pattern).

Each test names its contract ID in its own docstring (the R-L9 citation), quotes the first concrete rule of that
contract's section of docs/contracts.md, drives the PUBLIC use case on MemoryStore and takes its expected results from
the quoted contract text, not from the implementation. Injected rows (a fixture's active hook, a closed ticket without
a receipt) are labelled where they occur.
"""

from copy import deepcopy

import pytest

from codex_harness.coordination.application.outbox import Outbox
from codex_harness.intake.application.goal_progress import GoalProgress, compare_reports, definition_hash
from codex_harness.intake.application.tickets import Tickets, TicketSuperseded, ticket_binding
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.kernel.message import envelope
from codex_harness.research.application.dge import DebateSessions
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.research.domain.dge import DgeRefused, packet_digest, validate_packet
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

BASE = "a" * 40


# ----- INV-RECURRENCE-001 ---------------------------------------------------------------------------------------
def incident(occurrence, scope="ct6-scope", cause="ct6-cause"):
    return envelope("incident.report", "worker:implementation", "lead:improvement", "record_incident",
                    {"occurrence_id": occurrence, "root_cause": cause, "scope": scope,
                     "evidence_refs": ["fixture:" + occurrence]}, "ct6-recurrence")


def lifecycle_on_memory_store():
    store = MemoryStore()
    return HookLifecycle(packaged_organization(), outbox=Outbox(), events=_Events()), store


class _Events:
    """The coordination event journal's append port: a fixture that records the appended rows."""

    def append(self, tx, event_id, body):
        tx.put("events", event_id, body)


def record(lifecycle, store, message, independent=None):
    with store.transaction() as tx:
        return lifecycle.record_incident(message, independent_occurrence=independent, transaction=tx)


def test_s11_contract_recurrence_two_independent_occurrences_require_a_hook_and_redelivery_is_not_recurrence():
    """INV-RECURRENCE-001 (docs/contracts.md:6): "Two independent occurrences with the same confirmed cause/scope
    require a hook. Redelivery is not recurrence."

    One occurrence requires no hook; a redelivered message and a re-reported occurrence id do not count as a second
    occurrence; a retry of the same task (same independent occurrence) does not either; a different scope is a different
    group; a second independent occurrence of the same cause and scope requires one hook and queues one notification."""
    lifecycle, store = lifecycle_on_memory_store()
    first = incident("occ-1")
    assert record(lifecycle, store, first) == {"occurrences": 1, "duplicate_occurrence": False,
                                               "hook_id": None, "hook_created": False}
    # redelivery of the same message
    assert record(lifecycle, store, first)["occurrences"] == 1
    # the same occurrence id reported again in a new message
    again = record(lifecycle, store, incident("occ-1"))
    assert again["occurrences"] == 1 and again["duplicate_occurrence"] is True and again["hook_id"] is None
    # a different scope is a different group
    assert record(lifecycle, store, incident("occ-other-scope", scope="elsewhere"))["hook_id"] is None
    with store.transaction() as tx:
        assert tx.scan("hooks") == [] and tx.scan("outbox") == []
    # a retry of the same task keeps its evidence but is not an independent occurrence (own group, fresh cause)
    assert record(lifecycle, store, incident("occ-run", cause="retry-cause"), independent="task-1")["occurrences"] == 1
    retried = record(lifecycle, store, incident("occ-run-retry", cause="retry-cause"), independent="task-1")
    assert retried["occurrences"] == 1 and retried["hook_id"] is None
    with store.transaction() as tx:
        assert tx.scan("hooks") == []
    # a second independent occurrence of the same cause and scope requires one hook
    second = record(lifecycle, store, incident("occ-2"))
    assert second["occurrences"] == 2 and second["hook_created"] is True and second["hook_id"].startswith("hook-")
    with store.transaction() as tx:
        hooks = tx.scan("hooks")
        assert len(hooks) == 1 and hooks[0]["status"] == "required" and hooks[0]["version"] == 1
        assert len(tx.scan("outbox")) == 1


def test_s11_contract_recurrence_active_hook_recurrence_requires_a_version_update_keeping_the_previous_version():
    """INV-RECURRENCE-001 (docs/contracts.md:6): "Active-hook recurrence requires a version update while preserving
    the previous verified version."

    With an active hook for the group (an injected fixture row), a new independent occurrence reopens the hook as
    `required` at the same version and retains the previous active row; a redelivery of that occurrence does not."""
    lifecycle, store = lifecycle_on_memory_store()
    record(lifecycle, store, incident("occ-a"))
    created = record(lifecycle, store, incident("occ-b"))
    hook_id = created["hook_id"]
    with store.transaction() as tx:
        active = {**tx.get("hooks", hook_id), "status": "active", "version": 3}  # fixture: an activated hook
        tx.put("hooks", hook_id, active)
    record(lifecycle, store, incident("occ-b"))  # redelivery of an existing occurrence
    with store.transaction() as tx:
        assert tx.get("hooks", hook_id) == active
    updated = record(lifecycle, store, incident("occ-c"))
    assert updated["hook_created"] is True
    with store.transaction() as tx:
        hook = tx.get("hooks", hook_id)
    assert hook["status"] == "required" and hook["version"] == 3
    assert hook["previous_active"]["status"] == "active" and hook["previous_active"]["version"] == 3
    assert "occ-c" in hook["occurrences"]


# ----- INV-TICKET-001 -------------------------------------------------------------------------------------------
def content(title="ct6 ticket"):
    return {"title": title, "problem": "Production and tests share endpoints", "impact": "Potential contention",
            "rollback": "Restore verified image", "evidence_refs": ["fixture:source-inspection"],
            "scope": ["deployment"], "acceptance_criteria": ["Independent services"],
            "verification": ["Run isolated service integration test"]}


def make_tickets():
    return Tickets(MemoryStore(), packaged_organization(), outbox=Outbox())


def test_s11_contract_ticket_revisions_retain_hashes_dispatch_is_one_atomic_message_and_stale_binding_is_refused():
    """INV-TICKET-001 (docs/contracts.md:155-160): "Revisions retain immutable content hashes. Advisory findings bind
    one revision and record claimed reviewer/provider identity; they never impersonate authenticated model execution
    ... Dispatch writes one planning outbox message per revision atomically. ... Stale ticket bindings cannot complete
    tasks, commit reviews or promote candidates."

    A new revision leaves revision 1's content and hash readable; a review binds the revision, carries the claimed
    identity and `advisory_only` authority and a stale review is refused; dispatching twice queues exactly one outbox
    message; after an update the old binding raises `TicketSuperseded` and a corrupted revision is refused."""
    tickets = make_tickets()
    original = content()
    row = tickets.create(original)
    review = tickets.review(row["id"], 1, "Claude", "claude", "support", "Advisory only", ["fixture:review"])
    assert (review["revision"], review["claimed_reviewer"], review["claimed_provider"], review["authority"]) == (
        1, "Claude", "claude", "advisory_only")
    first = tickets.dispatch(row["id"], 1, "repository-commit")
    assert first["status"] == "queued_for_planning" and tickets.dispatch(row["id"], 1, "repository-commit") == first
    with tickets.store.transaction() as tx:
        assert [m["message"]["message_id"] for m in tx.scan("outbox")] == [first["message_id"]]
        bound = {k: tx.get("tickets", row["id"])[k] for k in ("id", "revision", "content_hash")}
        assert ticket_binding(tx, {"zeus_ticket": bound}) == bound
    newer = tickets.update(row["id"], 1, content("Updated scope"), "Clarify acceptance")
    assert newer["revision"] == 2 and newer["content_hash"] != row["content_hash"]
    old = tickets.get(row["id"], 1)
    assert old["content"] == original and old["content_hash"] == row["content_hash"] == digest(original)
    with pytest.raises(ContractError, match="Stale"):
        tickets.review(row["id"], 1, "Codex", "codex", "support", "Old opinion", ["fixture:stale"])
    with tickets.store.transaction() as tx:
        with pytest.raises(TicketSuperseded):
            ticket_binding(tx, {"zeus_ticket": bound})
        # fixture: corrupt revision 2's stored content behind the ledger's back
        stored = tx.get("ticket_revisions", row["id"] + ":2")
        tx.put("ticket_revisions", row["id"] + ":2", {**stored, "content": content("Tampered")})
        current = {k: tx.get("tickets", row["id"])[k] for k in ("id", "revision", "content_hash")}
        with pytest.raises(ContractError, match="corrupted"):
            ticket_binding(tx, {"zeus_ticket": current})


# ----- INV-GOAL-PROGRESS-001 ------------------------------------------------------------------------------------
def goal(*tickets, goal_id="goal-ct6"):
    return {"version": 1, "id": goal_id, "objective": "Resolve the fixture residual", "non_goals": ["Deploy"],
            "criteria": [{"id": f"c{n}", "acceptance": "Ticket closed with local evidence", "ticket_id": t["id"],
                          "revision": t["revision"], "content_hash": t["content_hash"]}
                         for n, t in enumerate(tickets, 1)]}


def test_s11_contract_goal_progress_manifest_pins_one_ticket_per_criterion_and_report_is_read_only():
    """INV-GOAL-PROGRESS-001 (docs/contracts.md:980-989): "duplicate criterion ids or ticket bindings are rejected so
    one ticket cannot inflate the denominator. The definition hash is the digest of the whole validated manifest; ...
    `GoalProgress.report` reads every needed row in one store transaction and writes nothing. A criterion is `missing`
    without its ticket or revision row, `stale` when the current ticket revision or hash differs, `pending` for a valid
    open ticket ... `unverified`, never resolved [for a purported closure without its receipt]. ... remaining (total
    minus resolved)".

    Duplicate ids or tickets are refused; any manifest change is a new definition hash; the report of an open,
    an edited, an absent and a closed-without-receipt ticket shows pending, stale, missing and unverified, none
    resolved, remaining = total, and the store is unchanged by reporting."""
    tickets = make_tickets()
    open_one, edited, absent_ticket, receiptless = (tickets.create(content(f"t{n}")) for n in range(4))
    edited_rev1 = deepcopy(edited)
    tickets.update(edited["id"], 1, content("edited"), "change after the goal pinned it")
    definition = goal(open_one, edited_rev1, receiptless)
    definition["criteria"].append({**definition["criteria"][0], "id": "c-absent", "ticket_id": "ZEUS-absent"})
    with tickets.store.transaction() as tx:  # fixture: a closed row with no lifecycle event or closure receipt
        tx.put("tickets", receiptless["id"], {**tx.get("tickets", receiptless["id"]), "status": "closed"})
    before = deepcopy(tickets.store.data) if hasattr(tickets.store, "data") else None
    report = GoalProgress(tickets.store).report(definition)
    if before is not None:
        assert tickets.store.data == before
    assert report["authority"] == "observation_only" and report["definition_hash"] == definition_hash(definition)
    assert [c["status"] for c in report["criteria"]] == ["pending", "stale", "unverified", "missing"]
    assert report["metrics"] == {"total": 4, "resolved": 0, "remaining": 4, "reopened": 0, "missing": 1,
                                 "stale": 1, "unverified": 1, "completion_ratio": 0.0}
    changed = deepcopy(definition)
    changed["objective"] = "A different objective"
    assert definition_hash(changed) != definition_hash(definition)
    for broken in ({"criteria": [definition["criteria"][0], {**definition["criteria"][1], "id": "c1"}]},
                   {"criteria": [definition["criteria"][0], {**definition["criteria"][1], "ticket_id": open_one["id"]}]}):
        with pytest.raises(ContractError, match="Duplicate goal criterion"):
            GoalProgress(tickets.store).report({**definition, **broken})
    # reports of different definitions are never compared
    other = GoalProgress(tickets.store).report(changed)
    with pytest.raises(ContractError, match="not comparable"):
        compare_reports(report, other)
    same = compare_reports(report, report)
    assert same["gained"] == [] and same["regressed"] == [] and same["net_resolved"] == 0


def test_s11_contract_goal_progress_goal_bound_dispatch_must_equal_the_criterion_binding_and_refuses_before_any_write():
    """INV-GOAL-PROGRESS-001 (docs/contracts.md:997-1000): "Goal-bound `Tickets.dispatch` (optional `goal_manifest`
    with `criterion_id`, required together) ... the dispatched ticket binding must equal the criterion binding and the
    criterion must be pending or reopened; a missing, stale, unverified, resolved or unmapped selection refuses".

    The pair is required together; a pending criterion dispatches with its goal binding; a criterion whose ticket moved
    on (stale), an unmapped criterion id, a criterion bound to another ticket and an unverified criterion (broken lifecycle chain)
    refuse and leave the outbox, the ticket row and the dispatch rows as they were."""
    tickets = make_tickets()
    one, two = tickets.create(content("one")), tickets.create(content("two"))
    definition = goal(one, two)
    with pytest.raises(ContractError, match="required together"):
        tickets.dispatch(one["id"], 1, "repo", goal_manifest=definition)
    with pytest.raises(ContractError, match="required together"):
        tickets.dispatch(one["id"], 1, "repo", criterion_id="c1")
    ok = tickets.dispatch(one["id"], 1, "repo", goal_manifest=definition, criterion_id="c1")
    assert ok["goal_binding"] == {"id": "goal-ct6", "definition_hash": digest(definition), "criterion_id": "c1"}

    def state():
        with tickets.store.transaction() as tx:
            return len(tx.scan("outbox")), tx.get("tickets", two["id"])

    before = state()
    with pytest.raises(ContractError, match="Dispatch ticket does not match"):
        tickets.dispatch(two["id"], 1, "repo", goal_manifest=definition, criterion_id="c1")
    with pytest.raises(ContractError, match="not in manifest"):
        tickets.dispatch(two["id"], 1, "repo", goal_manifest=definition, criterion_id="c-none")
    tickets.update(two["id"], 1, content("two changed"), "moves the ticket past the pinned revision")
    stale = state()
    with pytest.raises(ContractError):
        tickets.dispatch(two["id"], 2, "repo", goal_manifest=definition, criterion_id="c2")
    assert state() == stale and before[0] == stale[0]
    # the binding equals the criterion's but its lifecycle chain is broken (fixture row): unverified, never dispatched
    three = tickets.create(content("three"))
    with tickets.store.transaction() as tx:
        tx.put("tickets", three["id"], {**tx.get("tickets", three["id"]), "lifecycle_sequence": 1,
                                        "lifecycle_event": "missing-event"})
    broken = goal(three, goal_id="goal-broken")
    outbox_before = state()[0]
    with pytest.raises(ContractError, match="unverified; dispatch refused"):
        tickets.dispatch(three["id"], 1, "repo", goal_manifest=broken, criterion_id="c1")
    with tickets.store.transaction() as tx:
        assert tx.get("tickets", three["id"])["status"] == "open"
        assert all(r["ticket_id"] != three["id"] for r in tx.scan("ticket_dispatches"))
    assert state()[0] == outbox_before


# ----- INV-DGE-001 ----------------------------------------------------------------------------------------------
PLAN = {"objective": "Implement the gate", "acceptance_criteria": ["focused tests pass", "ruff passes"],
        "allowed_paths": ["src/codex_harness/domain/dge.py"]}
SOURCES = [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "bytes": 10}]  # fixture: Git-verified shape


def packet(**overrides):
    document = {"schema": "urn:zeus:research-packet:1", "id": "sess-ct6", "base_revision": BASE, "topic": "gate design",
                "objective": "decide the gate design", "exclusions": ["no merge"], "plan": deepcopy(PLAN),
                "questions": [{"id": "q1", "question": "Is PG authoritative?", "blocking": True, "status": "answered",
                               "claim_ids": ["c1"]}],
                "sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "locator": "git:docs/contracts.md",
                             "revision": BASE, "read_scope": "INV-OPERATION-001 section"}],
                "claims": [{"id": "c1", "kind": "fact", "text": "PG is authoritative", "source_ids": ["s1"]}],
                "limits": {"max_rounds": 2, "deadline": "2030-01-01T09:00:00+09:00"},
                "supersedes": None, "research_reason": None}
    document.update(overrides)
    return document


def test_s11_contract_dge_register_records_a_proposal_replays_exact_packets_and_refuses_expiry_and_conflicts():
    """INV-DGE-001 (docs/contracts.md:1105-1110): "The `dge_sessions` row records the canonical packet digest, the
    resolved repository digest, the normalized packet, `version` 0, `round` 1, state `proposal` and origin
    `operator_submitted`; the same id with the same digest and repository replays the saved row without mutation even
    after the deadline ..., any other same-id packet is `packet_conflict`. The registration clock is read inside the
    store transaction ... so a deadline that passes during the wait refuses with nothing written."

    Registration stores the proposal row; the same packet replays it (cached) even after the deadline; a changed
    packet or repository under the same id is `packet_conflict`; a blocking unknown question is refused before any
    store access; an expired deadline refuses with nothing written; a source whose bytes were not Git-verified refuses."""
    store = MemoryStore()
    now = {"t": "2026-09-16T10:00:00+00:00"}
    sessions = DebateSessions(store, lambda: now["t"])
    valid = validate_packet(packet())
    first = sessions.register(valid, "repo", SOURCES)
    row = first["session"]
    assert first["cached"] is False
    assert (row["packet_digest"], row["repository"], row["version"], row["round"], row["state"], row["origin"]) == (
        packet_digest(valid), "repo", 0, 1, "proposal", "operator_submitted")
    assert row["packet"] == valid and row["deadline"] == "2030-01-01T00:00:00+00:00"
    now["t"] = "2031-01-01T00:00:00+00:00"  # past the deadline: a replay reauthorizes nothing but still returns the row
    with store.transaction() as tx:
        saved = deepcopy(tx.get("dge_sessions", "sess-ct6"))
    assert sessions.register(valid, "repo", SOURCES) == {"session": saved, "cached": True}
    for changed, repository in ((validate_packet(packet(topic="another topic")), "repo"), (valid, "other-repo")):
        with pytest.raises(DgeRefused) as conflict:
            sessions.register(changed, repository, SOURCES)
        assert conflict.value.reason_code == "packet_conflict"
    with store.transaction() as tx:
        assert tx.get("dge_sessions", "sess-ct6") == saved and len(tx.scan("dge_sessions")) == 1
    # a new id after the deadline refuses and writes nothing
    with pytest.raises(DgeRefused) as expired:
        sessions.register(validate_packet(packet(id="sess-late")), "repo", SOURCES)
    assert expired.value.reason_code == "packet_expired"
    with pytest.raises(DgeRefused) as unverified:
        DebateSessions(store, lambda: "2026-09-16T10:00:00+00:00").register(
            validate_packet(packet(id="sess-bytes")), "repo", [{**SOURCES[0], "sha256": "c" * 64}])
    assert unverified.value.reason_code == "source_verification_incomplete"
    with store.transaction() as tx:
        assert [r["id"] for r in tx.scan("dge_sessions")] == ["sess-ct6"]
    # validation precedes any store access: a blocking unknown question never reaches register
    blocked = packet(id="sess-block", questions=[{"id": "q1", "question": "x", "blocking": True, "status": "unknown",
                                                  "claim_ids": []}])
    with pytest.raises(ContractError):
        validate_packet(blocked)
    with pytest.raises(ContractError):
        validate_packet(packet(id="sess-int", questions=[{"id": "q1", "question": "x", "blocking": 1,
                                                          "status": "answered", "claim_ids": ["c1"]}]))
