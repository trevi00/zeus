"""GAP #20 (G20-1a): the research package record, store and admission policy (DESIGN-s10 §14 G20-D1..D5).

A declared target addition (RF-RT has no M7 counterpart), so the proof is fixture-based: MemoryStore, a fixed clock and
a dict-backed `ResearchPins`. Each test names the representative path it proves.

| step | reason code                   | test                                         |
|------|-------------------------------|----------------------------------------------|
| 1    | exempt:<class>                | test_each_explicit_class_is_exempt, derived  |
| 1    | exemption_conflict / _unknown | test_exemption_refusals_block                |
| 2    | package_missing               | test_missing_evidence_*                      |
| 3    | package_not_accepted          | test_missing_evidence_draft_*, withdrawn     |
| 4    | package_supersession_*        | test_supersession_*                          |
| 5    | source_unavailable            | test_source_unavailable_blocks               |
| 6    | insufficient_sources          | test_source_gap_*                            |
| 6    | admit_with_source_gap         | test_source_gap_*                            |
| 7    | stale_version / pin_unavailable | test_version_change_*                      |
| 8    | stale_age                     | test_age_*                                   |
| 9    | material_contradiction        | test_counterexample_*                        |
| 10   | admitted                      | test_normal_*                                |
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from codex_harness.coordination.application.research_admission import PersistedResearchAdmission
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest
from codex_harness.research.application.research_package_policy import ResearchPackagePolicy
from codex_harness.research.application.research_packages import PackageRefused, ResearchPackages, row_key
from codex_harness.research.domain.research_package import (
    EXEMPTION_CLASSES,
    RESEARCH_PACKAGE_MAX_AGE_DAYS,
    ResearchExemptionRefused,
    exemption,
    research_key,
    validate_package,
)
from codex_harness.storage.adapters.memory_store import MemoryStore

START = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
DECISION = "sha256:" + "a" * 64
CLAIM = "sha256:" + "c" * 64
EVIDENCE = "sha256:" + "d" * 64
KEY = "ticket:t-1"


class Clock:
    def __init__(self):
        self.at = START

    def now(self):
        return self.at

    def advance(self, **delta):
        self.at += timedelta(**delta)


class Pins:
    def __init__(self, **pins):
        self.pins = dict(pins)

    def current(self, pin_ref):
        return self.pins.get(pin_ref)


def source(n=0, **fields):
    row = {"ref": f"https://example.test/{n}", "title": f"source {n}", "retrieved_at": START.isoformat(),
           "kind": "primary", "applicable_version": None, "pin_ref": None, "claim_digest": CLAIM,
           "opened": True, "available": True}
    row.update(fields)
    return row


def draft(key=KEY, sources=None, **fields):
    document = {"key": key, "supersedes": None, "question": "Is the change safe?",
                "sources": [source(n) for n in range(3)] if sources is None else sources, "source_gap": None,
                "contradictions": [], "recorded_by": "lead:research"}
    document.update(fields)
    return document


def ticket_lease(ticket="t-1", nested=False, **details):
    binding = {"id": ticket, "revision": 1, "content_hash": "h"}
    body = {"plan": {"origin": {"zeus_ticket": binding}}} if nested else {"zeus_ticket": binding}
    body.update(details)
    return {"id": "task-" + ("impl" if nested else "plan"),
            "message": {"correlation_id": f"ticket:{ticket}:1", "what": {"details": body}}}


def lease_of(details, correlation="corr-1"):
    return {"id": "task-x", "message": {"correlation_id": correlation, "what": {"details": details}}}


class World:
    def __init__(self, pins=None, max_age_days=RESEARCH_PACKAGE_MAX_AGE_DAYS):
        self.store, self.clock = MemoryStore(), Clock()
        self.packages = ResearchPackages(clock=self.clock)
        self.pins = pins if pins is not None else Pins()
        self.policy = ResearchPackagePolicy(self.packages, self.pins, clock=self.clock, max_age_days=max_age_days)

    def record(self, document=None, accept=True):
        with self.store.transaction() as tx:
            row = self.packages.record(tx, document or draft())
            if accept:
                row = self.packages.accept(tx, row["key"], row["version"], DECISION)
        return row

    def admit(self, lease=None, action="plan"):
        with self.store.transaction() as tx:
            return self.policy.admit(tx, lease or ticket_lease(), action)


def answer(disposition, reason):
    return {"disposition": disposition, "reason": reason}


# ---- normal ----------------------------------------------------------------------------------------------------

def test_normal_accepted_fresh_package_with_three_sources_admits_plan_and_implement():
    world = World()
    world.record()
    assert world.admit(ticket_lease()) == answer("admit", "admitted")
    # Example 2: the implement lease carries the binding under plan.origin and gets the same key and disposition.
    assert world.admit(ticket_lease(nested=True), "implement") == answer("admit", "admitted")


# ---- missing evidence -----------------------------------------------------------------------------------------

def test_missing_evidence_no_package_is_research():
    assert World().admit() == answer("research", "package_missing")


def test_missing_evidence_draft_withdrawn_and_other_keys_are_research():
    world = World()
    world.record(accept=False)
    assert world.admit() == answer("research", "package_not_accepted")
    world.record(draft(key="ticket:other"))
    assert world.admit(ticket_lease("t-2")) == answer("research", "package_missing")
    withdrawn = World()
    row = withdrawn.record()
    with withdrawn.store.transaction() as tx:
        withdrawn.packages.withdraw(tx, KEY, row["version"], "obsolete")
    assert withdrawn.admit() == answer("research", "package_not_accepted")


# ---- relevant version change ---------------------------------------------------------------------------------

def test_version_change_pin_differs_is_research_and_unknown_pin_is_blocked():
    world = World(Pins(**{"uv.lock:httpx": "1.0"}))
    pinned = [source(0, pin_ref="uv.lock:httpx", applicable_version="1.0"), source(1), source(2)]
    world.record(draft(sources=pinned))
    assert world.admit() == answer("admit", "admitted")
    world.pins.pins["uv.lock:httpx"] = "2.0"
    assert world.admit() == answer("research", "stale_version")
    del world.pins.pins["uv.lock:httpx"]
    assert world.admit() == answer("blocked", "pin_unavailable")


# ---- source unavailable ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("flag", ["available", "opened"])
def test_source_unavailable_blocks(flag):
    world = World()
    world.record(draft(sources=[source(0, **{flag: False}), source(1), source(2)]))
    assert world.admit() == answer("blocked", "source_unavailable")


# ---- counterexample -------------------------------------------------------------------------------------------

def test_counterexample_material_unresolved_blocks_irrelevant_and_resolved_admit():
    contradiction = {"material": True, "summary_digest": CLAIM, "resolved_ref": None}
    for contradictions, expected in [
            ([contradiction], answer("blocked", "material_contradiction")),
            ([{**contradiction, "material": False}], answer("admit", "admitted")),
            ([{**contradiction, "resolved_ref": EVIDENCE}], answer("admit", "admitted"))]:
        world = World()
        world.record(draft(contradictions=contradictions))
        assert world.admit() == expected


# ---- source gap -----------------------------------------------------------------------------------------------

def test_source_gap_two_sources_with_recorded_gap_admit_without_gap_blocked():
    gap = {"searches": ["site:example.test foo"], "reason": "no third primary source exists"}
    world = World()
    world.record(draft(sources=[source(0), source(1)]))
    assert world.admit() == answer("blocked", "insufficient_sources")
    with_gap = World()
    with_gap.record(draft(sources=[source(0), source(1)], source_gap=gap))
    assert with_gap.admit() == answer("admit", "admit_with_source_gap")
    # The gap excuses a missing source, not a stale package or a material contradiction.
    with_gap.clock.advance(days=31)
    assert with_gap.admit() == answer("research", "stale_age")


# ---- age ------------------------------------------------------------------------------------------------------

def test_age_accepted_thirty_one_days_ago_is_stale_and_thirty_is_fresh():
    world = World()
    world.record()
    world.clock.advance(days=30)
    assert world.admit() == answer("admit", "admitted")
    world.clock.advance(days=1)
    assert world.admit() == answer("research", "stale_age")
    assert World(max_age_days=1).policy.max_age_days == 1


# ---- supersession ---------------------------------------------------------------------------------------------

def test_supersession_follows_to_the_head_and_keeps_the_old_row():
    world = World()
    first = world.record()
    second = world.record(draft(supersedes=1))
    assert (first["version"], second["version"]) == (1, 2)
    with world.store.transaction() as tx:
        current = world.packages.current(tx, KEY)
        old = world.packages.get(tx, KEY, 1)
    assert current["version"] == 2 and current["status"] == "accepted"
    assert old["status"] == "superseded" and old["superseded_by"] == {"key": KEY, "version": 2}
    assert [event["event"] for event in old["history"]] == ["recorded", "accepted", "superseded"]
    assert world.admit() == answer("admit", "admitted")


def test_supersession_cycle_and_missing_target_are_typed_refusals_and_block():
    world = World()
    world.record()
    world.record(draft(supersedes=1))
    with world.store.transaction() as tx:
        head = world.packages.get(tx, KEY, 2)
        head.update(status="superseded", superseded_by={"key": KEY, "version": 1})
        tx.put("research_packages", row_key(KEY, 2), head)
    with world.store.transaction() as tx, pytest.raises(PackageRefused) as cycle:
        world.packages.current(tx, KEY)
    assert cycle.value.reason_code == "package_supersession_cycle"
    assert world.admit() == answer("blocked", "package_supersession_cycle")
    with world.store.transaction() as tx:
        head = world.packages.get(tx, KEY, 2)
        head["superseded_by"] = {"key": KEY, "version": 9}
        tx.put("research_packages", row_key(KEY, 2), head)
        tx.put("research_packages", row_key(KEY, 1), {**world.packages.get(tx, KEY, 1), "superseded_by": None})
    with world.store.transaction() as tx, pytest.raises(PackageRefused) as missing:
        world.packages.current(tx, KEY)
    assert missing.value.reason_code == "package_supersession_missing"
    assert world.admit() == answer("blocked", "package_supersession_missing")


def test_supersedes_needs_a_prior_recorded_version():
    world = World()
    world.record(accept=False)
    with world.store.transaction() as tx:
        with pytest.raises(ContractError, match="prior version"):
            world.packages.record(tx, draft(supersedes=2))  # not below the new version 2
        del tx.data[("research_packages", row_key(KEY, 1))]
        tx.put("research_packages", row_key(KEY, 5), {"key": KEY, "version": 5})  # the next version is 6
        with pytest.raises(PackageRefused) as missing:
            world.packages.record(tx, draft(supersedes=4))
    assert missing.value.reason_code == "package_supersession_missing"


# ---- exemptions -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", EXEMPTION_CLASSES)
def test_each_explicit_class_is_exempt(name):
    declared = {"class": name, "reason": "declared at intake"}
    world = World()
    for details in ({"research_exemption": declared},
                    {"plan": {"origin": {"research_exemption": declared}}},
                    {"operation": {"id": "op-1", "research_exemption": declared}}):
        assert world.admit(lease_of(details)) == answer("exempt", "exempt:" + name)


def test_derived_hook_origin_is_bugfix_with_failing_test_at_top_and_under_plan_origin():
    hook = {"id": "hook-abc", "status": "required"}
    top = {"objective": "Implement mandatory recurrence hook", "hook": hook, "importance": "important"}
    for details in (top, {"plan": {"origin": top}}):
        assert exemption(lease_of(details)) == {"class": "bugfix-with-failing-test", "reason": "hook:hook-abc"}
        assert World().admit(lease_of(details)) == answer("exempt", "exempt:bugfix-with-failing-test")


def test_derived_audit_adoption_is_research_approved_audit_at_top_and_under_plan_origin():
    top = {"audit_id": "audit-1", "audit_approval": "bind-9", "proposal": {}, "importance": "important"}
    for details in (top, {"plan": {"origin": top}}):
        assert exemption(lease_of(details)) == {"class": "research-approved-audit", "reason": "adopt:bind-9"}
        assert World().admit(lease_of(details)) == answer("exempt", "exempt:research-approved-audit")


def test_an_explicit_class_that_equals_the_derived_one_is_accepted():
    details = {"audit_id": "a", "audit_approval": "b", "research_exemption": {
        "class": "research-approved-audit", "reason": "approved"}}
    assert exemption(lease_of(details)) == {"class": "research-approved-audit", "reason": "approved"}


def test_exemption_refusals_block():
    one = {"class": "docs-only", "reason": "docs"}
    cases = [
        ({"research_exemption": one, "plan": {"origin": {"research_exemption": {**one, "class": "objective-quality"}}}},
         "exemption_conflict"),
        ({"research_exemption": one, "audit_id": "a", "audit_approval": "b"}, "exemption_conflict"),
        ({"research_exemption": {"class": "whatever", "reason": "x"}}, "exemption_class_unknown"),
        ({"research_exemption": "docs-only"}, "exemption_class_unknown"),
    ]
    for details, code in cases:
        with pytest.raises(ResearchExemptionRefused) as refused:
            exemption(lease_of(details))
        assert refused.value.code == code
        assert World().admit(lease_of(details)) == answer("blocked", code)


def test_absent_exemption_is_substantial():
    assert exemption(ticket_lease()) is None


# ---- keys -----------------------------------------------------------------------------------------------------

def test_keys_ticket_binding_nested_under_plan_origin_matches_the_plan_lease():
    assert research_key(ticket_lease()) == research_key(ticket_lease(nested=True)) == KEY


def test_keys_operation_then_correlation_fallback_and_ticket_precedence():
    assert research_key(lease_of({"operation": {"id": "op-1"}})) == "operation:op-1"
    assert research_key(lease_of({"plan": {"origin": {"operation": {"id": "op-2"}}}})) == "operation:op-2"
    assert research_key(lease_of({}, "adopt:x")) == "correlation:adopt:x"
    both = ticket_lease(operation={"id": "op-1"})
    assert research_key(both) == KEY
    with pytest.raises(ContractError):
        research_key({"id": "task-x"})


def test_keys_conflicting_ticket_copies_refuse_and_block():
    lease = ticket_lease()
    lease["message"]["what"]["details"]["plan"] = {"origin": {"zeus_ticket": {"id": "t-2", "revision": 1,
                                                                              "content_hash": "h"}}}
    with pytest.raises(ContractError, match="Conflicting ticket revisions"):
        research_key(lease)
    assert World().admit(lease) == answer("blocked", "research_key_conflict")


# ---- restart through the real PersistedResearchAdmission ---------------------------------------------------------

def test_restart_hold_persists_across_a_new_instance_then_resolve_and_accept_admit():
    world = World()

    class Counting:
        calls = 0

        def admit(self, tx, lease, action):
            Counting.calls += 1
            return world.policy.admit(tx, lease, action)

    lease = {**ticket_lease(), "id": "task-plan"}

    def consult(instance, at=None):
        with world.store.transaction() as tx:
            return instance.admit(tx, lease, "plan")

    first = PersistedResearchAdmission(Counting(), clock=world.clock)
    assert consult(first)["disposition"] == "research" and Counting.calls == 1
    world.record()  # an accepted package now exists, but the hold stands until it is resolved
    restarted = PersistedResearchAdmission(Counting(), clock=world.clock)
    held = consult(restarted)
    assert held == {"disposition": "research", "reason": "package_missing", "persisted": True}
    assert Counting.calls == 1
    with world.store.transaction() as tx:
        restarted.resolve(tx, "task-plan", "plan", resolution_ref=DECISION, actor="lead:research")
    assert consult(PersistedResearchAdmission(Counting(), clock=world.clock)) == {
        "disposition": "admit", "reason": "admitted", "persisted": False}
    assert Counting.calls == 2


# ---- store and record -----------------------------------------------------------------------------------------

def test_store_is_append_only_per_key_version_and_row_key_is_the_digest():
    world = World()
    one = world.record(accept=False)
    with world.store.transaction() as tx:
        stored = tx.get("research_packages", digest({"key": KEY, "version": 1}))
    assert stored == one and stored["status"] == "draft"
    two = world.record(draft(question="A revised question?"), accept=False)
    assert two["version"] == 2
    with world.store.transaction() as tx:
        assert tx.get("research_packages", row_key(KEY, 1)) == one
        assert len(tx.scan("research_packages")) == 2
        # An explicit version that is not latest + 1 cannot overwrite a recorded (key, version) row.
        with pytest.raises(ContractError):
            world.packages.record(tx, {**draft(), "version": 1})
        assert tx.get("research_packages", row_key(KEY, 1)) == one
        # Transitions are limited: a draft cannot be accepted twice and an unknown version is refused.
        world.packages.accept(tx, KEY, 1, DECISION)
        with pytest.raises(ContractError):
            world.packages.accept(tx, KEY, 1, DECISION)
        with pytest.raises(PackageRefused):
            world.packages.accept(tx, KEY, 7, DECISION)


# ---- validate_package -----------------------------------------------------------------------------------------

def full(**fields):
    document = {**draft(), "version": 1, "status": "draft", "superseded_by": None, "decision_ref": None,
                "recorded_at": START.isoformat()}
    document.update(fields)
    return document


def test_validate_package_accepts_the_closed_shape_and_returns_a_copy():
    document = full()
    checked = validate_package(document)
    assert checked == document and checked is not document


@pytest.mark.parametrize("bad", [
    {"extra": 1}, {"status": "proposed"}, {"version": 0}, {"version": True}, {"decision_ref": "sha256:xyz"},
    {"decision_ref": "a" * 64}, {"supersedes": 1}, {"supersedes": 2, "version": 2},
    {"sources": [source(opened="yes")]}, {"sources": [source(available=1)]}, {"sources": [source(kind="blog")]},
    {"sources": [source(claim_digest="sha256:short")]}, {"sources": [{**source(), "extra": 1}]},
    {"source_gap": {"searches": [], "reason": "x"}}, {"source_gap": {"reason": "x"}},
    {"contradictions": [{"material": "yes", "summary_digest": CLAIM, "resolved_ref": None}]},
    {"contradictions": [{"material": True, "summary_digest": "nope", "resolved_ref": None}]},
    {"superseded_by": {"key": KEY}}, {"recorded_at": "yesterday"}, {"recorded_by": ""}])
def test_validate_package_refuses_each_malformed_field(bad):
    with pytest.raises(ContractError):
        validate_package(full(**bad))


def test_validate_package_refuses_a_missing_key():
    document = full()
    del document["question"]
    with pytest.raises(ContractError, match="Missing"):
        validate_package(document)
    assert deepcopy(document) is not document
