"""S8 pilot 73 (V13 R4): coordination's `ResearchLaunchFacts` over owner-action rows built by the owner's own constructors.

Rows are the shape `coordination.domain.owner_actions` writes for a `research_dispatch` launch; the expected results are the
M7 `ResearchProgram._scope_target` predicate read as literals (state in {launching, running}, id, binding digest, int launches,
launch id equal to the owner token).
"""
from codex_harness.coordination.application.owner_actions.state import BUCKET_ACTIONS
from codex_harness.coordination.application.research_launch_facts import ResearchLaunchFacts
from codex_harness.coordination.domain import owner_actions as do
from codex_harness.kernel.ids import digest
from codex_harness.storage.adapters.memory_store import MemoryStore

NOW = "2026-09-22T00:00:00+00:00"
BINDING = {"program_id": "rp-1", "expected_cycle": 1, "intent_id": "i-1"}


def action(state=do.RUNNING, binding=None):
    row = do.new_action(do.RESEARCH_DISPATCH, binding or BINDING, {"id": "owners-1", "policy_sha256": "3" * 64},
                        {"intent_id": "i-1"}, NOW)
    if state != do.INTENDED:
        row = do.moved(row, do.LAUNCHING, NOW, "research_launch_intended", launches=1,
                       launch_id=do.research_launch_id(row["id"], 1))
    if state == do.RUNNING:
        row = do.moved(row, do.RUNNING, NOW, "research_launched")
    return row


def test_bucket_is_the_owner_actions_bucket():
    assert BUCKET_ACTIONS == "owner_actions"


def test_launches_select_only_research_dispatch_rows_of_the_owner():
    store, facts = MemoryStore(), ResearchLaunchFacts()
    row = action()
    other = action(binding={**BINDING, "program_id": "rp-2"})
    with store.transaction() as tx:
        tx.put(BUCKET_ACTIONS, row["id"], row)
        tx.put(BUCKET_ACTIONS, other["id"], other)
        tx.put(BUCKET_ACTIONS, "plan", {**row, "id": "plan", "kind": do.DELIVERY_PLAN})
        tx.put(BUCKET_ACTIONS, "junk", "not a row")
        assert facts.launches(tx, row["launch_id"]) == [row]
        assert facts.launches(tx, other["launch_id"]) == [other]
        assert facts.launches(tx, "0" * 32) == []


def test_authentic_for_a_launching_or_running_action_that_recomputes():
    facts = ResearchLaunchFacts()
    for state in (do.LAUNCHING, do.RUNNING):
        row = action(state)
        assert facts.authentic(row, row["launch_id"]) is True


def test_wrong_state_is_not_authentic():
    facts = ResearchLaunchFacts()
    row = do.moved(action(), do.COMPLETED, NOW, "research_dispatch_accepted")
    assert facts.authentic(row, row["launch_id"]) is False


def test_wrong_id_is_not_authentic():
    facts = ResearchLaunchFacts()
    row = action()
    assert facts.authentic({**row, "id": "x" * 64}, row["launch_id"]) is False


def test_binding_digest_mismatch_is_not_authentic():
    facts = ResearchLaunchFacts()
    row = action()
    assert facts.authentic({**row, "binding_sha256": digest({"other": 1})}, row["launch_id"]) is False


def test_wrong_launch_id_or_launch_count_is_not_authentic():
    facts = ResearchLaunchFacts()
    row = action()
    assert facts.authentic(row, "0" * 32) is False
    assert facts.authentic({**row, "launches": 2}, row["launch_id"]) is False
    assert facts.authentic({**row, "launches": True}, row["launch_id"]) is False
