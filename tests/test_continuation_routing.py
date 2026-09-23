"""INV-CONTINUATION-001 recovery routing: policy membership before fairness, effect ownership across
policies sharing one control store, and bounded progress past unavailable lanes.

The same labelled fixtures as test_continuation (real MemoryStores, the real `Fleet`, `Operation`
and `Continuation.tick`; the lane executor is the labelled `FakeExecutor`). Historical rows of an
older policy are written by the real tick of that policy, never synthesized. Injected faults are
named as such. Nothing here is evidence of a live host, a model session or the managed Fleet.
"""
from __future__ import annotations

from copy import deepcopy

from test_continuation import ARCHIVE, GOAL, IDENTITY, World, manifest, only
from test_fleet import config as fleet_config
from test_operation import Bus, Collector, FakeBudget, FakeExecutor
from test_worker_sessions import IMAGE

from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.worker_sessions import SessionArchives
from codex_harness.application.continuation import LaneEvidence
from codex_harness.application.fleet import Fleet
from codex_harness.application.operation import Operation
from codex_harness.application.service import Harness
from codex_harness.application.worker_sessions import WorkerSessions
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain import continuation as dc


def other_policy(world, policy_id, **changes):
    document = {**deepcopy(world.document), "id": policy_id, **changes}
    world.controller.register(document, world.pin)
    return policy_id


def tick(world, policy_id, controller=None):
    return (controller or world.controller).tick(policy_id, pin_sha256=world.pin["sha256"], runtime=world.runtime)


def rows_of(world, policy_id):
    return {key: row for key, row in world.intents().items() if row["policy_id"] == policy_id}


# ---- membership before fairness; historical foreign refusals stay unchanged -----------------------
def test_an_actual_tick_repairs_in_scope_evidence_past_more_old_history_than_its_fairness_limit(tmp_path):
    world = World(tmp_path)
    world.register()
    # The OLD policy shares the store: it covered an older path and ran under another image, so the
    # real tick of that policy refused every job it saw (`image_changed`) - including the target.
    old = other_policy(world, "policy-old", allowed_paths=["docs/old.md", "docs/a.md"],
                       qualified={**world.document["qualified"], "image": "old/image:1"})
    history = []
    for n in range(dc.MAX_ACTIONS_PER_TICK + 1):
        world.enqueue(f"h{n}", "docs/old.md")
        history.append(world.run_next(verdict=False)[0])
    world.enqueue("t1", "docs/a.md")
    target, receipt = world.run_next(inspection="incomplete")
    assert receipt["reason_code"] == "evidence_gate_refused"
    tick(world, old)
    tick(world, old)
    historical = deepcopy(rows_of(world, old))
    assert sorted(row["origin_job"] for row in historical.values()) == sorted([*history, target])
    assert all(row["state"] == dc.REFUSED and row["reason_code"] == "image_changed" for row in historical.values())
    squatted = only(historical, origin_job=target)
    assert squatted["route"] == dc.EVIDENCE_REPAIR, "the old refusal sits on the target's global effect key"

    result = world.tick()
    repair = only(rows_of(world, "policy-1"), route=dc.EVIDENCE_REPAIR)
    assert repair["origin_job"] == target and repair["state"] == dc.ADMITTED
    assert repair["id"] == dc.intent_slot(squatted["id"], 1) and repair["successor_job"] in world.jobs()
    assert result["outcome"] == "progressed"
    assert [action["subject"] for action in result["actions"]] == [repair["id"]], "no foreign row is progress"
    assert set(rows_of(world, "policy-1")) == {repair["id"]}, "unrelated history is never recorded here"
    assert rows_of(world, old) == historical, "old policy records are unchanged"

    # Replay, a reconstructed controller and the old policy again: one owner, one successor.
    snapshot = deepcopy(world.control.data)
    world.tick()
    world.tick(controller=world.build())
    tick(world, old, controller=world.build())
    assert world.control.data == snapshot and len(world.jobs()) == len(history) + 2


# ---- overlapping policies: one effect, its original owner, no foreign progress -------------------
def test_overlapping_policies_converge_on_one_owner_through_race_replay_and_restart(tmp_path):
    world = World(tmp_path)
    world.register()
    second = other_policy(world, "policy-2")
    world.enqueue("op-1")
    world.tick()
    job_id, _ = world.run_next(verdict=False)
    world.await_review(job_id)
    raced = []

    def racing_lanes(lane_id):
        # The other controller wins between this controller's selection and its intent write.
        if not raced:
            raced.append(world.tick())
        return world.lanes(lane_id)
    result = tick(world, second, controller=world.build(lanes=racing_lanes))
    correction = only(world.intents(), route=dc.CORRECTION)
    assert correction["policy_id"] == "policy-1" and correction["state"] == dc.ADMITTED
    assert raced[0]["outcome"] == "progressed"
    assert result["actions"] == [], "the foreign row is never returned as this policy's progress"
    assert result["skipped"] == [{"subject": job_id, "reason_code": "intent_owned_elsewhere",
                                  "next_owner": "operator"}]
    assert len(world.jobs()) == 2 and rows_of(world, second) == {}

    # The next pass excludes the foreign lineage before selection and reports it; a restart agrees.
    snapshot = deepcopy(world.control.data)
    later = tick(world, second)
    assert later["outcome"] == "idle" and later["actions"] == [] and later["skipped"] == []
    assert later["owned_elsewhere"] == {"count": 1, "jobs": [{"job": job_id, "policy_id": "policy-1"}]}
    tick(world, second, controller=world.build())
    world.tick(controller=world.build())
    assert world.control.data == snapshot

    # The successor belongs to the same lineage: only its owner conducts it, exactly once.
    successor = correction["successor_job"]
    assert world.run_next()[0] == successor
    assert tick(world, second)["owned_elsewhere"]["count"] == 2 and world.conductor.calls == []
    world.tick()
    tick(world, second)
    tick(world, second, controller=world.build())
    world.tick(controller=world.build())
    assert world.conductor.calls == [successor]
    assert rows_of(world, second) == {} and only(world.intents(), route=dc.CONDUCTOR)["policy_id"] == "policy-1"


def test_a_foreign_row_that_owns_an_effect_is_never_reused_by_the_create_path(tmp_path):
    world = World(tmp_path)
    world.register()
    second = other_policy(world, "policy-2")
    world.enqueue("op-1")
    world.tick()
    job_id, _ = world.run_next(verdict=False)
    world.tick()
    owned = only(world.intents(), route=dc.CORRECTION)
    fields = {key: owned[key] for key in ("origin_job", "lane", "family", "route", "evidence_sha256")}
    attempt = {"generation": owned["generation"], "attempt": owned["attempt"]}
    for key in (None, owned["id"]):
        try:
            world.controller._create({**fields, "policy_id": second, "state": dc.INTENDED}, attempt, key=key)
        except dc.ContinuationRefused as exc:
            assert exc.reason_code == "intent_owned_elsewhere"
        else:
            raise AssertionError("a foreign effect owner was reused")
    assert rows_of(world, second) == {}


# ---- runtime unavailable or mismatched: visible, no new effect, no starvation --------------------
class TwoLanes(World):
    """Lanes `a` and `b` of ONE repository under one policy, each with its own lane store."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.control = MemoryStore()
        self.fleet = Fleet(self.control)
        lanes = fleet_config(tmp_path)["lanes"]
        lanes[1]["repository"] = lanes[0]["repository"]
        self.fleet.register(fleet_config(tmp_path, lanes=lanes))
        self.harness = {"a": self.lane, "b": Harness(MemoryStore(), organization())}
        self.lane_sessions = {"a": self.sessions,
                              "b": WorkerSessions(self.harness["b"].store, SessionArchives(tmp_path / "archives-b"))}
        self.document["lanes"] = ["a", "b"]
        self.controller = self.build()

    def lanes(self, lane_id):
        self.lane_reads += 1
        return LaneEvidence(self.harness[lane_id].store, self.lane_sessions[lane_id])

    def run_in(self, lane_id, op_id, path, **executor):
        self.fleet.enqueue(lane_id, manifest(op_id, path), GOAL, [])
        job = self.fleet.admit_one()["job"]
        assert job["id"] == op_id
        harness = self.harness[lane_id]
        receipt = Operation(harness, FakeExecutor(harness, **executor), Bus(), Workflow(harness.store, harness.org),
                            FakeBudget(), Collector()).run(job["manifest"], IDENTITY, GOAL)
        self.fleet.finalize(job["id"], job["owner_token"], {
            "status": receipt["status"], "reason_code": receipt["reason_code"], "exit_code": receipt["exit_code"],
            "owner_handoff": receipt["owner_handoff"], "calls": receipt["calls"]})
        return job["id"]


def test_an_unavailable_or_mismatched_runtime_blocks_its_lane_visibly_and_never_starves_another(tmp_path):
    world = TwoLanes(tmp_path)
    world.register()
    blocked = [world.run_in("a", f"a{n}", "docs/a.md", verdict=False) for n in range(dc.MAX_ACTIONS_PER_TICK + 1)]
    independent = world.run_in("b", "b1", "docs/b.md", verdict=False)
    good = {"image": IMAGE, "profile": "worker-v1", "session_archive_sha256": ARCHIVE}

    def unavailable(lane_id):
        if lane_id == "a":
            raise ConnectionError("lane a runtime identity unreadable (injected fault)")
        return good
    world.runtime = unavailable
    result = world.tick()
    correction = only(world.intents(), route=dc.CORRECTION)
    assert correction["origin_job"] == independent and correction["state"] == dc.ADMITTED
    assert result["outcome"] == "progressed"
    assert result["skipped"] == [{"subject": blocked[0], "reason_code": "unavailable", "error_type": "ConnectionError"}]
    assert len(world.intents()) == 1 and len(world.jobs()) == len(blocked) + 2, "lane a started nothing"

    # A readable but mismatched identity: each lane-a family is a named refusal, still no effect.
    world.runtime = lambda lane_id: {**good, "image": "other/image:1"} if lane_id == "a" else good
    world.tick()
    world.tick()
    refused = [row for row in world.intents().values() if row["lane"] == "a"]
    assert sorted(row["origin_job"] for row in refused) == sorted(blocked)
    assert all(row["state"] == dc.REFUSED and row["reason_code"] == "image_changed" for row in refused)
    assert len(world.jobs()) == len(blocked) + 2 and world.conductor.calls == []
