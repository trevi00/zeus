"""INV-CONTINUATION-001: durable conductor continuation against the fixed acceptance matrix.

Real MemoryStores (one Fleet control store, one lane store), the real `Fleet`, `Operation`,
`LocalCycle`, `Workflow`, operation finalization, `WorkerSessions` with real archive files, real
`Portfolio` and real temporary Git repositories. The lane's worker/lead executor is the LABELLED
`FakeExecutor` fixture of test_operation and the conductor port is a labelled fixture that writes
the decision row the real guarded `decide_one` would write: no model, provider, Docker, network or
production store is touched, and nothing here is evidence of a real model session or a live host.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_fleet import config as fleet_config
from test_git_workspace import repository
from test_operation import Bus, Collector, FakeBudget, FakeExecutor
from test_worker_sessions import IMAGE, identity, write_session

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.executor import Executor
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.portfolio import packaged_definitions
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.adapters.worker_sessions import SessionArchives, export_session
from codex_harness.application.continuation import (
    BUCKET_INTENTS,
    LANE_BINDINGS,
    Continuation,
    IntentChanged,
    LaneEvidence,
)
from codex_harness.application.fleet import Fleet, FleetRunner
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.operation import Operation, OperationRefused
from codex_harness.application.portfolio import Portfolio, reconcile
from codex_harness.application.service import Harness
from codex_harness.application.worker_sessions import WorkerSessions
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain import continuation as dc
from codex_harness.domain.fleet import repository_identity
from codex_harness.domain.model import ContractError, envelope
from codex_harness.domain.observation import new_process_run_id
from codex_harness.domain.operation import validate_manifest

CANARY = "CANARY-continuation-objective-never-projected"
BASE = "a" * 40
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit", "base_revision": BASE, "bytes": 3}
IDENTITY = {"repository": "r", "runtime": "d", "runtime_policy": "p", "provider": {"policy_digest": "x", "config_digest": "y"}}
ARCHIVE = "d" * 64
MODEL = "claude-fixture-model"


def manifest(op_id, path="docs/a.md", model=MODEL, objective=None):
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit", "rationale": "fixture goal"},
        "plan": {"objective": objective or ("Implement " + CANARY), "acceptance_criteria": ["ok"],
                 "allowed_paths": [path]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": model, "timeout_seconds": 120, "max_budget_usd": 1.0}}, packaged_policy())


class ConductorFixture:
    """LABELLED fixture of the owned-child conductor port (no process, no model): `start` does what
    the child's guarded decision would - it writes the succeeded review_conductor row, the queued
    release id and the Releases record of the exact candidate, as the executor's `_commit_decision`
    shapes them - and `poll` reports the launch as the real port would observe it.

    `pending=True` leaves the launch running with nothing decided until `finish()`; `lost=True`
    starts (and decides) but loses the start response; `raise_error` fails before any child exists."""

    def __init__(self, lane, accepted=True, raise_error=None, pending=False, lost=False):
        self.lane, self.accepted, self.raise_error = lane, accepted, raise_error
        self.pending, self.lost, self.calls, self.launches, self.jobs = pending, lost, [], {}, {}
        self.slots = 1

    def available(self):
        return sum(1 for state in self.launches.values() if state == "running") < self.slots

    def start(self, lane_id, job, launch):
        if self.raise_error is not None:
            raise self.raise_error
        self.calls.append(job["id"])
        self.jobs[launch] = job
        self.launches[launch] = "running"
        if not self.pending:
            self.finish(launch)
        if self.lost:
            raise TimeoutError("start response lost after the child started (injected)")
        return {"pid": 4242}

    def finish(self, launch, decide=True):
        if decide:
            self.decide(self.jobs[launch])
        self.launches[launch] = "exited"

    def decide(self, job):
        with self.lane.store.transaction() as tx:
            operation = tx.get("operations", job["id"])
            lead = tx.get("decisions_pending", operation["decision_id"])
            candidate = tx.get("tasks", operation["task_id"])["result"]["candidate"]
            decision_id = "cond-" + job["id"]
            tx.put("decisions_pending", decision_id, {
                "id": decision_id, "actor": "conductor", "phase": "review_conductor", "status": "succeeded",
                "attempt": 1, "input": lead["input"],
                "message": {"correlation_id": operation["correlation_id"],
                            "what": {"details": {"decision_id": lead["id"]}}},
                "result": {"accepted": self.accepted, "reason": CANARY, "execution_ref": "sha256:" + "9" * 64,
                           **({"deployment": {"status": "queued", "release_id": "rel-" + job["id"]}}
                              if self.accepted else {})}})
            if self.accepted:
                tx.put("releases", "rel-" + job["id"], {"id": "rel-" + job["id"], "candidate": dict(candidate)})

    def active(self):
        return sorted(launch for launch, state in self.launches.items() if state == "running")

    def poll(self, lane_id, launch):
        state = self.launches.get(launch)
        if state is None:  # nothing was ever spawned under this identity: the fence proves it
            return {"state": "absent", "owned": False, "exit_code": None}
        return {"state": state, "owned": True, "exit_code": 0 if state == "exited" else None}


class World:
    """One Fleet (control store), one lane store, the lane's session owner and one controller."""

    def __init__(self, tmp_path, *, conductor=True, accepted=True, runtime=None, max_corrections=3,
                 enabled=True):
        self.tmp = tmp_path
        self.control = MemoryStore()
        self.fleet = Fleet(self.control)
        self.fleet.register(fleet_config(tmp_path))
        self.repository = repository_identity(str(tmp_path / "repo-a"))
        self.lane = Harness(MemoryStore(), organization())
        self.sessions = WorkerSessions(self.lane.store, SessionArchives(tmp_path / "archives"))
        self.spool = MemorySpool(new_process_run_id())
        self.observer = Observer(MemoryStore(), self.spool, component="test-continuation", directory=MemoryDirectory())
        self.conductor = ConductorFixture(self.lane, accepted=accepted) if conductor else None
        self.lane_reads = 0
        self.runtime = runtime or (lambda lane: {"image": IMAGE, "profile": "worker-v1", "session_archive_sha256": ARCHIVE})
        self.controller = self.build()
        self.document = {"schema": dc.POLICY_SCHEMA, "id": "policy-1", "enabled": enabled,
                         "repository": self.repository, "lanes": ["a"],
                         "goals": [{"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit"}],
                         "allowed_paths": ["docs/a.md", "docs/b.md", "docs/c.md"], "acceptance_criteria": ["ok"],
                         "session_archive_sha256": ARCHIVE,
                         "qualified": {"model": MODEL, "image": IMAGE, "profile": "worker-v1"},
                         "delivery_target": "fleet-host", "max_corrections": max_corrections}
        self.pin = {"revision": "e" * 40, "path": "ops/continuation.json", "sha256": "f" * 64, "lane": "a"}

    def lanes(self, lane_id):
        assert lane_id == "a"
        self.lane_reads += 1
        return LaneEvidence(self.lane.store, self.sessions)

    def build(self, cls=Continuation, **overrides):
        ports = {"fleet": self.fleet, "lanes": self.lanes, "conductor": self.conductor,
                 "validate": lambda m: validate_manifest(m, packaged_policy()), "observer": self.observer, **overrides}
        return cls(self.control, **ports)

    def register(self):
        return self.controller.register(self.document, self.pin)

    def tick(self, controller=None, **kwargs):
        return (controller or self.controller).tick("policy-1", pin_sha256=self.pin["sha256"], runtime=self.runtime,
                                                    **kwargs)

    def enqueue(self, op_id, path="docs/a.md", **kwargs):
        return self.fleet.enqueue("a", manifest(op_id, path, **kwargs), GOAL, [])

    def run_next(self, **executor):
        """The Fleet admits the next job and the lane runs it through the REAL finite Operation
        (fixture executor only), then the Fleet finalizes it as the launcher would."""
        job = self.fleet.admit_one()["job"]
        assert job is not None, "nothing admissible"
        operation = Operation(self.lane, FakeExecutor(self.lane, **executor), Bus(),
                              Workflow(self.lane.store, self.lane.org), FakeBudget(), Collector())
        receipt = operation.run(job["manifest"], IDENTITY, GOAL)
        self.fleet.finalize(job["id"], job["owner_token"], {
            "status": receipt["status"], "reason_code": receipt["reason_code"], "exit_code": receipt["exit_code"],
            "owner_handoff": receipt["owner_handoff"], "calls": receipt["calls"]})
        return job["id"], receipt

    def await_review(self, task_id, n=1):
        """The session the real executor would have left: one adopted turn, candidate frozen."""
        plan = self.sessions.begin(task_id, identity(task_id=task_id), {"execution": "exec-" + task_id,
                                                                         "generation": 1, "attempt": 1})
        home, export = self.tmp / ("home-" + task_id), self.tmp / ("export-" + task_id)
        write_session(home, "/workspace", plan["session_id"], [b"turn " + str(n).encode()])
        export_session(home, "/workspace", plan["session_id"], export)
        self.sessions.checkpoint(task_id, {"execution": "exec-" + task_id, "generation": 1, "attempt": 1}, export,
                                 usage=None)
        self.sessions.submit(task_id, {"revision": "c" * 40, "tree": "7" * 40, "base": BASE})

    def intents(self):
        with self.control.transaction() as tx:
            return {row["id"]: row for row in tx.scan(BUCKET_INTENTS)}

    def jobs(self):
        with self.control.transaction() as tx:
            return {row["id"]: row for row in tx.scan("fleet_jobs")}

    def binding(self, op_id):
        with self.lane.store.transaction() as tx:
            return tx.get(LANE_BINDINGS, op_id)

    def events(self):
        return [record for record in self.spool.records()
                if str(record.get("event_type", "")).startswith("operations.continuation")]


def only(rows, **match):
    found = [row for row in rows.values() if all(row.get(k) == v for k, v in match.items())]
    assert len(found) == 1, found
    return found[0]


# ---- policy -------------------------------------------------------------------------------------
def test_policy_is_strict_and_a_changed_policy_or_pin_refuses(tmp_path):
    world = World(tmp_path)
    assert dc.validate_policy(world.document)["lanes"] == ["a"]
    for key, value in (("enabled", 1), ("repository", "x"), ("lanes", []), ("allowed_paths", ["../x"]),
                       ("max_corrections", 0), ("max_corrections", 99), ("qualified", {"model": MODEL}),
                       ("extra", True), ("goals", [{"path": "GOAL.txt", "sha256": "b" * 64, "criterion": "c"}])):
        with pytest.raises(dc.ContinuationRefused) as info:
            dc.validate_policy({**world.document, key: value})
        assert info.value.reason_code == "policy_invalid" and info.value.owner == "operator"
    first = world.register()
    assert first["cached"] is False and world.register()["cached"] is True
    with pytest.raises(dc.ContinuationRefused, match="policy_conflict"):
        world.controller.register({**world.document, "max_corrections": 1}, world.pin)
    before = deepcopy(world.control.data)
    refused = world.controller.tick("policy-1", pin_sha256="0" * 64, runtime=world.runtime)
    assert refused["outcome"] == "refused" and refused["reason_code"] == "policy_changed"
    assert refused["next_owner"] == "operator" and world.control.data == before and world.lane_reads == 0


@pytest.mark.parametrize("registered, enabled", [(False, True), (True, False)])
def test_absent_or_disabled_policy_produces_zero_actions(tmp_path, registered, enabled):
    world = World(tmp_path, enabled=enabled)
    if registered:
        world.register()
    world.enqueue("op-1")
    before, lane_before = deepcopy(world.control.data), deepcopy(world.lane.store.data)
    result = world.tick()
    assert result["outcome"] == "disabled" and result["actions"] == []
    assert result["reason_code"] == ("policy_disabled" if registered else "policy_unregistered")
    assert world.control.data == before and world.lane.store.data == lane_before
    assert world.lane_reads == 0 and world.conductor.calls == []


# ---- first item: the initial execution is already a task session ---------------------------------
def test_initial_item_is_bound_to_its_session_before_admission_and_the_claim_attaches_it(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.fleet.enqueue("b", manifest("op-other"), GOAL, [])  # another lane: outside this policy
    assert world.tick()["actions"] == [{"subject": "op-1", "effect": "session_bound"}]
    binding = world.binding("op-1")
    assert binding["session"] == {"task_id": "op-1", "repository": world.repository}
    assert binding["workspace"] is None and binding["route"] is None and binding["family"] == "op-1"
    assert world.binding("op-other") is None
    assert world.tick()["actions"] == [], "a bound job is not bound again"
    job_id, receipt = world.run_next(verdict=True)
    with world.lane.store.transaction() as tx:
        row = tx.get("operations", job_id)
        task = tx.get("tasks", row["assignment_message_id"])
    # The real Operation claim attached the lane's own binding to the row AND the assignment.
    assert row["continuation"] == binding and task["message"]["what"]["details"]["continuation"] == binding
    assert receipt["status"] == "accepted"


def test_legacy_operation_without_binding_keeps_its_exact_shape_and_a_changed_binding_refuses(tmp_path):
    world = World(tmp_path)
    operation = Operation(world.lane, FakeExecutor(world.lane), Bus(), Workflow(world.lane.store, world.lane.org),
                          FakeBudget(), Collector())
    operation.run(manifest("legacy"), IDENTITY, GOAL)
    with world.lane.store.transaction() as tx:
        row = tx.get("operations", "legacy")
        task = tx.get("tasks", row["assignment_message_id"])
    assert "continuation" not in row and "continuation" not in task["message"]["what"]["details"]
    with world.lane.store.transaction() as tx:
        tx.put(LANE_BINDINGS, "legacy", {"schema": dc.BINDING_SCHEMA, "operation_id": "legacy", "policy_sha256": "a" * 64,
                                         "intent_id": None, "family": "legacy", "route": None, "session": None,
                                         "workspace": None, "predecessor": None})
    with pytest.raises(OperationRefused, match="configuration_mismatch"):
        operation.run(manifest("legacy"), IDENTITY, GOAL)
    lane = LaneEvidence(world.lane.store)
    with pytest.raises(ContractError, match="binding_conflict"):
        lane.bind({**world.binding("legacy"), "family": "changed"})
    late = {**world.binding("legacy"), "operation_id": "late"}
    Operation(world.lane, FakeExecutor(world.lane), Bus(), Workflow(world.lane.store, world.lane.org), FakeBudget(),
              Collector()).run(manifest("late", "docs/b.md"), IDENTITY, GOAL)
    with pytest.raises(ContractError, match="operation_already_claimed"):
        lane.bind(late)


# ---- rejection -> one pinned correction successor with session lineage ---------------------------
def test_rejection_derives_one_pinned_successor_with_session_lineage_idempotently(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    job_id, receipt = world.run_next(verdict=False)
    assert receipt["status"] == "rejected"
    world.await_review(job_id)
    result = world.tick()
    intent = only(world.intents(), route=dc.CORRECTION)
    successor = intent["successor_job"]
    assert result["outcome"] == "progressed" and intent["state"] == dc.ADMITTED
    assert successor == dc.successor_id(intent["id"]) and intent["session_mode"] == "native_resume_eligible"
    job, origin = world.jobs()[successor], world.jobs()[job_id]
    # Same frame byte for byte: goal, base, allowed paths, criteria, budget and model.
    for key in ("goal", "base_revision", "budget", "claude"):
        assert job["manifest"][key] == origin["manifest"][key]
    assert job["manifest"]["plan"]["allowed_paths"] == origin["manifest"]["plan"]["allowed_paths"]
    assert job["manifest"]["plan"]["acceptance_criteria"] == origin["manifest"]["plan"]["acceptance_criteria"]
    assert job["goal"] == origin["goal"] and job["status"] == "queued"
    assert "review_decision=" in job["manifest"]["plan"]["objective"] and "c" * 40 in job["manifest"]["plan"]["objective"]
    binding = world.binding(successor)
    with world.lane.store.transaction() as tx:
        task_id = tx.get("operations", job_id)["task_id"]
        session = tx.get("worker_sessions", job_id)
        rejected = tx.get("operations", job_id)
    assert binding["session"] == {"task_id": job_id, "repository": world.repository}
    assert binding["workspace"] == {"origin_task_id": task_id, "head": "c" * 40, "base": BASE}
    assert binding["predecessor"]["decision_id"] == rejected["decision_id"] and binding["intent_id"] == intent["id"]
    assert session["state"] == "correction_ready" and session["candidates"][-1]["outcome"] == "rejected"
    assert rejected["status"] == "rejected", "the rejected finite operation is never rewritten"
    # Duplicate notification, a second controller and a restart: the same intent, no second successor.
    snapshot = deepcopy(world.control.data)
    world.tick()
    world.tick(controller=world.build())
    assert world.control.data == snapshot and len(world.jobs()) == 2
    events = world.events()
    assert [e["attributes"]["state"] for e in events if e["attributes"]["route"] == dc.CORRECTION] == [
        "intended", "published", "admitted"]
    status = world.controller.status("policy-1")
    projected = only({row["id"]: row for row in status["intents"]}, route=dc.CORRECTION)
    assert projected["origin_job"] == job_id and projected["successor_job"] == successor
    assert projected["next_owner"] == "fleet" and "terminal outcome" in projected["next_action"]
    assert projected["evidence_refs"] == ["sha256:" + "f" * 64] and projected["completion"]
    assert status["counts"] == {"admitted": 1} and status["held_families"] == {}
    assert CANARY not in json.dumps(status) and CANARY not in json.dumps(events)
    assert "manifest" not in json.dumps(status) and str(tmp_path) not in json.dumps(status)


def test_lost_responses_around_each_effect_reconcile_to_one_successor(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    job_id, _ = world.run_next(verdict=False)
    world.await_review(job_id)

    class DownBeforeRead(LaneEvidence):
        def read(self, job, target=None):
            raise ConnectionError("lane store unavailable before any effect (injected fault)")

    before = world.tick(controller=world.build(lanes=lambda lane: DownBeforeRead(world.lane.store, world.sessions)))
    assert before["outcome"] == "blocked" and before["skipped"][0]["error_type"] == "ConnectionError"
    assert world.intents() == {} and len(world.jobs()) == 1, "nothing is intended from unread evidence"

    class LostAfterBind(LaneEvidence):
        def bind(self, document):
            super().bind(document)
            raise TimeoutError("response lost after the lane write (injected fault)")

    lossy = world.build(lanes=lambda lane: LostAfterBind(world.lane.store, world.sessions))
    first = world.tick(controller=lossy)
    assert first["skipped"][0]["reason_code"] == "unavailable" and first["skipped"][0]["error_type"] == "TimeoutError"
    assert only(world.intents(), route=dc.CORRECTION)["state"] == dc.INTENDED

    class LostAfterEnqueue(Fleet):
        def enqueue(self, *args):
            super().enqueue(*args)
            raise ConnectionError("response lost after the Fleet commit (injected fault)")

    second = world.tick(controller=world.build(fleet=LostAfterEnqueue(world.control)))
    assert second["skipped"][0]["error_type"] == "ConnectionError"
    intent = only(world.intents(), route=dc.CORRECTION)
    assert intent["state"] == dc.PUBLISHED and intent["successor_job"] in world.jobs()
    world.tick()
    intent = only(world.intents(), route=dc.CORRECTION)
    assert intent["state"] == dc.ADMITTED and len(world.jobs()) == 2, "the replay reused the same successor"
    stale = {**intent, "version": intent["version"] - 1}
    with pytest.raises(IntentChanged):  # a second controller holding an older read cannot move it
        world.controller._move(stale, dc.RETURNED)


# ---- two-strike research, fairness and hold of one family only ----------------------------------
def test_second_distinct_failure_invokes_research_once_and_holds_only_that_family(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-x", "docs/a.md")
    world.tick()
    x, _ = world.run_next(verdict=False)
    world.await_review(x)
    world.tick()
    successor = only(world.intents(), route=dc.CORRECTION)["successor_job"]
    world.tick()  # binds nothing new: the successor is bound by its own intent
    assert world.run_next(verdict=False)[0] == successor
    # An unrelated family fails at the same time; one tick serves both families.
    world.enqueue("op-y", "docs/b.md")
    world.tick()
    y, _ = world.run_next(verdict=False)
    world.tick()
    intents = world.intents()
    research = only(intents, route=dc.RESEARCH)
    assert research["state"] == dc.RESEARCH_REQUIRED and research["family"] == x
    assert research["origin_job"] == successor and research["next_owner"] == "portfolio_research"
    assert only(intents, family=y, route=dc.CORRECTION)["state"] == dc.ADMITTED, "family y not starved"
    assert world.controller.status()["held_families"] == {x: "two_distinct_failures"}
    held = deepcopy(world.control.data)
    world.tick()
    world.tick()
    assert world.control.data == held, "the research candidate is raised once; replays count nothing"
    # The existing Portfolio groups the failures; the owner records a researched disposition.
    reconcile(world.control)
    portfolio = Portfolio(world.control, packaged_definitions())
    with world.control.transaction() as tx:
        candidate = next(row for row in tx.scan("portfolio_investigations") if successor in row["job_ids"])
    portfolio.disposition(candidate["id"], "researched", ["sha256:" + "1" * 64])
    world.tick()
    intents = world.intents()
    assert only(intents, route=dc.RESEARCH)["state"] == dc.COMPLETED
    follow = only(intents, origin_job=successor, route=dc.CORRECTION)
    assert follow["state"] == dc.ADMITTED and follow["family"] == x
    assert follow["session_mode"].startswith("fresh_evidence_handoff"), "the session was not reviewed again"


def test_correction_budget_of_the_policy_is_a_named_refusal(tmp_path):
    world = World(tmp_path, max_corrections=1)
    world.register()
    world.enqueue("op-1")
    world.tick()
    first, _ = world.run_next(verdict=False)
    world.tick()
    world.run_next(verdict=False)
    world.tick()
    research = only(world.intents(), route=dc.RESEARCH)
    reconcile(world.control)
    with world.control.transaction() as tx:
        candidate = next(row for row in tx.scan("portfolio_investigations") if first in row["job_ids"])
    Portfolio(world.control, packaged_definitions()).disposition(candidate["id"], "researched", ["sha256:" + "2" * 64])
    world.tick()
    refused = only(world.intents(), origin_job=research["origin_job"], route=dc.CORRECTION)
    assert refused["state"] == dc.REFUSED and refused["reason_code"] == "correction_budget_exhausted"
    assert refused["next_owner"] == "operator" and len(world.jobs()) == 2


# ---- evidence repair, unknown effects -----------------------------------------------------------
def test_evidence_refusal_routes_a_scoped_repair_that_preserves_the_candidate(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    job_id, receipt = world.run_next(inspection="incomplete")
    assert receipt["reason_code"] == "evidence_gate_refused"
    world.tick()
    intent = only(world.intents(), route=dc.EVIDENCE_REPAIR)
    binding = world.binding(intent["successor_job"])
    assert intent["state"] == dc.ADMITTED and intent["session_mode"] == "fresh_evidence_handoff"
    assert binding["session"] is None, "an unreviewed session is never relabelled as resumable"
    assert binding["workspace"]["head"] == "c" * 40 and binding["predecessor"]["inspection_id"].startswith("insp-")
    assert "Evidence repair" in world.jobs()[intent["successor_job"]]["manifest"]["plan"]["objective"]


def test_unknown_effects_go_to_recovery_and_are_never_retried(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    job_id, receipt = world.run_next(raise_error=RuntimeError("provider state unknown (injected)"))
    assert receipt["status"] == "failed"
    world.tick()
    intent = only(world.intents(), origin_job=job_id)
    assert intent["route"] == dc.RECOVERY and intent["state"] == dc.RECOVERY_REQUIRED
    assert intent["next_owner"] == "execution_recovery" and len(world.jobs()) == 1
    blocked = [e for e in world.events() if e["event_type"] == "operations.continuation_blocked"]
    assert blocked and blocked[-1]["outcome"] == "unknown"
    snapshot = deepcopy(world.control.data)
    world.tick()
    assert world.control.data == snapshot and world.conductor.calls == []


def test_a_pending_termination_marker_is_an_unknown_effect_even_for_a_rejection(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    job_id, _ = world.run_next(verdict=False)
    with world.lane.store.transaction() as tx:
        task_id = tx.get("operations", job_id)["task_id"]
        tx.put("observation_terminations", "rec-1", {"record_id": "rec-1", "task_id": task_id,
                                                     "status": "pending_reconciliation"})
    world.tick()
    assert only(world.intents(), origin_job=job_id)["route"] == dc.RECOVERY and len(world.jobs()) == 1


# ---- accepted lead -> conductor -> release -> delivery -> next item ------------------------------
CANDIDATE = "c" * 40  # the fixture worker's candidate revision (test_operation.FakeExecutor)


def deliver(world, plan_id, release_id, stage, target="fleet-host", revision=CANDIDATE):
    """A HostDelivery intent row as `domain.host_delivery.new_intent` shapes it (the fields read)."""
    with world.lane.store.transaction() as tx:
        tx.put("host_delivery_intents", plan_id, {"id": plan_id, "plan_id": plan_id, "release_id": release_id,
                                                  "target_id": target, "revision": revision, "stage": stage,
                                                  "plan_sha256": "5" * 64, "updated_at": "t"})


def accepted_item(world, op_id="op-1", path="docs/a.md"):
    world.enqueue(op_id, path)
    world.tick()
    job_id, receipt = world.run_next(verdict=True)
    assert receipt["status"] == "accepted"
    return job_id


def test_accepted_lead_is_conducted_once_then_delivered_then_the_next_item(tmp_path):
    world = World(tmp_path)
    world.register()
    job_id = accepted_item(world)
    world.tick()
    assert world.conductor.calls == [job_id]
    assert only(world.intents(), route=dc.CONDUCTOR)["state"] == dc.COMPLETED
    world.tick()
    delivery = only(world.intents(), route=dc.DELIVERY)
    assert delivery["state"] == dc.AWAITING_OWNER and delivery["release_id"] == "rel-" + job_id
    assert delivery["next_owner"] == "host_delivery" and delivery["delivery_target"] == "fleet-host"
    assert "delivery plan" in dc.view(delivery)["next_action"]
    idle = deepcopy(world.control.data)
    world.tick()
    assert world.control.data == idle and world.conductor.calls == [job_id], "waiting holds no call"
    deliver(world, "plan-1", "rel-" + job_id, "active")
    world.tick()
    intents = world.intents()
    assert only(intents, route=dc.DELIVERY)["state"] == dc.COMPLETED
    nxt = only(intents, route=dc.NEXT_ITEM)
    assert nxt["state"] == dc.AWAITING_OWNER and nxt["next_owner"] == "fleet_backlog"
    assert nxt["predecessor_intent"] == only(intents, route=dc.DELIVERY)["id"]
    settled = deepcopy(world.control.data)
    for _ in range(3):
        world.tick()
    assert world.control.data == settled and world.conductor.calls == [job_id]


def test_rollback_holds_only_the_family_and_preserves_the_acceptance(tmp_path):
    world = World(tmp_path)
    world.register()
    job_id = accepted_item(world)
    world.tick()
    world.tick()
    deliver(world, "plan-1", "rel-" + job_id, "rolled_back")
    world.tick()
    paused = only(world.intents(), route=dc.DELIVERY)
    assert paused["state"] == dc.PAUSED and paused["reason_code"] == "delivery_rolled_back"
    with world.lane.store.transaction() as tx:
        conductor = tx.get("decisions_pending", "cond-" + job_id)
    assert conductor["result"]["accepted"] is True, "a rollback never rewrites the acceptance"
    other, _ = world.enqueue("op-2", "docs/b.md")["job"]["id"], None
    world.tick()
    world.run_next(verdict=False)
    world.tick()
    assert only(world.intents(), origin_job=other, route=dc.CORRECTION)["state"] == dc.ADMITTED


def test_conductor_rejection_is_a_correction_and_an_unknown_dispatch_is_never_relaunched(tmp_path):
    world = World(tmp_path, accepted=False)
    world.register()
    job_id = accepted_item(world)
    world.tick()
    world.tick()
    correction = only(world.intents(), origin_job=job_id, route=dc.CORRECTION)
    assert correction["reason_code"] == "conductor_rejected" and correction["state"] == dc.ADMITTED
    assert world.binding(correction["successor_job"])["predecessor"]["decision_id"] == "cond-" + job_id

    # A lost start response of a child that DID start and decide: reconciled from its launch
    # evidence and the committed decision row, never started again.
    lost = World(tmp_path / "lost")
    lost.conductor.lost = True
    lost.register()
    lost_job = accepted_item(lost)
    first = lost.tick()
    assert {"subject": only(lost.intents(), route=dc.CONDUCTOR)["id"], "effect": "launch_unconfirmed",
            "route": dc.CONDUCTOR, "error_type": "TimeoutError"} in first["actions"]
    for _ in range(3):
        lost.tick()
    intent = only(lost.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.COMPLETED and intent["decision"]["id"] == "cond-" + lost_job
    assert lost.conductor.calls == [lost_job] and intent["launch"]["sequence"] == 1

    # A child that exited with its row still `running` is an unknown effect: recovery, never a relaunch.
    unknown = World(tmp_path / "unknown")
    unknown.conductor.pending = True
    unknown.register()
    unknown_job = accepted_item(unknown)
    unknown.tick()
    with unknown.lane.store.transaction() as tx:
        operation = tx.get("operations", unknown_job)
        lead = tx.get("decisions_pending", operation["decision_id"])
        tx.put("decisions_pending", "cond-x", {"id": "cond-x", "actor": "conductor", "phase": "review_conductor",
                                               "status": "running", "attempt": 1,
                                               "message": {"what": {"details": {"decision_id": lead["id"]}}}})
    unknown.conductor.finish(next(iter(unknown.conductor.launches)), decide=False)
    for _ in range(3):
        unknown.tick()
    intent = only(unknown.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.RECOVERY_REQUIRED and intent["reason_code"] == "conductor_running"
    assert intent["next_owner"] == "execution_recovery" and unknown.conductor.calls == [unknown_job]


def test_without_a_conductor_port_the_route_waits_for_its_owner_with_no_call(tmp_path):
    world = World(tmp_path, conductor=False)
    world.register()
    accepted_item(world)
    world.tick()
    intent = only(world.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.AWAITING_OWNER and intent["reason_code"] == "conductor_port_unconfigured"


# ---- refusals with a named next owner ----------------------------------------------------------
@pytest.mark.parametrize("change, reason", [
    ({"image": "other/image:1"}, "image_changed"), ({"profile": "worker-v2"}, "profile_changed"),
    ({"session_archive_sha256": "0" * 64}, "session_archive_changed")])
def test_changed_runtime_identity_refuses_with_a_named_owner_and_never_widens(tmp_path, change, reason):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    world.run_next(verdict=False)
    world.runtime = lambda lane: {"image": IMAGE, "profile": "worker-v1", "session_archive_sha256": ARCHIVE, **change}
    world.tick()
    refused = only(world.intents(), state=dc.REFUSED)
    assert refused["reason_code"] == reason and refused["next_owner"] == "operator" and len(world.jobs()) == 1


def test_changed_goal_scope_or_model_of_a_job_refuses(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-model", "docs/a.md", model="claude-other-model")
    world.enqueue("op-scope", "docs/outside.md")
    assert world.tick()["actions"] == [], "jobs outside the policy are never bound"
    world.run_next(verdict=False)
    world.run_next(verdict=False)
    world.tick()
    reasons = sorted(row["reason_code"] for row in world.intents().values())
    assert reasons == ["model_changed", "scope_changed"] and len(world.jobs()) == 2
    assert all(row["state"] == dc.REFUSED and row["next_owner"] == "operator" for row in world.intents().values())


def test_missing_lane_evidence_refuses_with_the_owner_who_can_supply_it(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    job = world.fleet.admit_one()["job"]
    world.fleet.finalize(job["id"], job["owner_token"], {"status": "rejected", "reason_code": "lead_rejected"})
    world.tick()
    refused = only(world.intents(), origin_job="op-1")
    assert refused["state"] == dc.REFUSED and refused["reason_code"] == "lane_evidence_missing"
    assert refused["next_owner"] == "operator"


# ---- the real FleetRunner composition ------------------------------------------------------------
class LaneLauncher:
    """LABELLED fixture launcher: runs the REAL finite Operation in the lane store with the fixture
    worker/lead, synchronously, exactly where the production launcher runs `zeus operate run`."""

    def __init__(self, world, verdicts):
        self.world, self.verdicts, self.launched = world, list(verdicts), []

    def budget_exhausted(self, budget):
        return False

    def launch(self, job):
        self.launched.append(job["id"])
        operation = Operation(self.world.lane, FakeExecutor(self.world.lane, verdict=self.verdicts.pop(0)), Bus(),
                              Workflow(self.world.lane.store, self.world.lane.org), FakeBudget(), Collector())
        return {"job_id": job["id"], "receipt": operation.run(job["manifest"], IDENTITY, GOAL)}

    @staticmethod
    def wait(handles, seconds):
        return handles

    @staticmethod
    def outcome(handle, job):
        receipt = handle["receipt"]
        return {"status": receipt["status"], "reason_code": receipt["reason_code"], "exit_code": receipt["exit_code"],
                "owner_handoff": receipt["owner_handoff"], "calls": receipt["calls"]}


def test_fleet_runner_drives_first_item_rejection_correction_and_acceptance_without_relay(tmp_path):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    launcher = LaneLauncher(world, [False, True])
    runner = FleetRunner(world.fleet, launcher, sleep=lambda _: None, continuation=lambda: world.tick())
    summary = runner.run(once=True)
    correction = only(world.intents(), route=dc.CORRECTION)
    assert launcher.launched == ["op-1", correction["successor_job"]]
    assert summary["continuation"]["state"] == "ok"
    assert world.jobs()["op-1"]["status"] == "rejected" and world.jobs()[correction["successor_job"]]["status"] == "accepted"
    with world.lane.store.transaction() as tx:
        successor = tx.get("operations", correction["successor_job"])
        origin_task = tx.get("operations", "op-1")["task_id"]
    assert successor["continuation"]["intent_id"] == correction["id"]
    assert successor["continuation"]["workspace"]["origin_task_id"] == origin_task
    runner.run(once=True)
    intents = world.intents()
    assert only(intents, route=dc.CORRECTION)["state"] == dc.COMPLETED
    assert only(intents, route=dc.CONDUCTOR)["state"] == dc.COMPLETED
    assert world.conductor.calls == [correction["successor_job"]]


def test_runner_without_continuation_is_unchanged_and_an_outage_never_blocks_admission(tmp_path):
    world = World(tmp_path)
    world.enqueue("op-1")
    plain = FleetRunner(world.fleet, LaneLauncher(world, [True]), sleep=lambda _: None).run(once=True)
    assert "continuation" not in plain and world.jobs()["op-1"]["status"] == "accepted"
    other = World(tmp_path / "outage")
    other.enqueue("op-1")

    def broken():
        raise ConnectionError("lane store outage (injected)")
    summary = FleetRunner(other.fleet, LaneLauncher(other, [True]), sleep=lambda _: None,
                          continuation=broken).run(once=True)
    assert summary["continuation"] == {"state": "unavailable", "outcome": None, "reason_code": None,
                                       "error_type": "ConnectionError"}
    assert other.jobs()["op-1"]["status"] == "accepted"


# ---- the executor consumes only the lane's own binding --------------------------------------------
class RecordingSessions:
    """LABELLED fixture session owner: records the candidate the executor freezes."""

    def __init__(self):
        self.submitted, self.reviews = [], []

    def submit(self, task_id, candidate):
        self.submitted.append((task_id, candidate))

    def record_review(self, task_id, decision_id):
        self.reviews.append((task_id, decision_id))


def continuation_executor(tmp_path, monkeypatch, *, origin_status="succeeded", stored=True, adopted=True):
    root = repository(tmp_path)
    git = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    origin = git.prepare("origin-task", "HEAD")
    (Path(origin["path"]) / "change.txt").write_text("rejected attempt", encoding="utf-8")
    rejected = git.capture(origin)
    service = Harness(MemoryStore(), organization())
    sessions = RecordingSessions()
    executor = Executor(service, git, FileArtifacts(str(tmp_path / "artifacts")), worker_sessions=sessions)
    binding = {"schema": dc.BINDING_SCHEMA, "operation_id": "cont-1", "policy_sha256": "a" * 64,
               "intent_id": "b" * 64, "family": "op-1", "route": dc.CORRECTION,
               "session": {"task_id": "op-1", "repository": "r" * 64},
               "workspace": {"origin_task_id": "origin-task", "head": rejected["revision"], "base": rejected["base"]},
               "predecessor": {"job_id": "op-1"}}
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                       {"plan": {"objective": "fix", "acceptance_criteria": ["ok"], "allowed_paths": ["change.txt"]},
                        "operation": {"id": "cont-1"}, "continuation": binding}, "operation:cont-1")
    message["where"]["revision"] = rejected["base"]
    with service.store.transaction() as tx:
        tx.put("tasks", "origin-task", {"id": "origin-task", "status": origin_status, "agent": "worker:implementation"})
        if stored:
            tx.put(LANE_BINDINGS, "cont-1", binding)
    Workflow(service.store, service.org).submit(message)
    calls = []

    def run(agent, key, objective, evidence, cwd, schema, read_only=False, heartbeat=None, lease=None, **kwargs):
        calls.append({"cwd": cwd, **kwargs})
        (Path(cwd) / "change.txt").write_text("corrected", encoding="utf-8")
        return {"summary": "fixture", "tests": [], "execution_ref": "sha256:" + "e" * 64,
                "task_session": {"adopted": adopted, "mode": "native_resume"}}
    monkeypatch.setattr(executor, "_run", run)
    monkeypatch.setattr(executor, "_inspect_evidence", lambda *a, **k: {"verdict": "all_checked"})
    return executor, service, sessions, calls, origin, rejected


def test_executor_continues_the_workspace_and_passes_the_task_session_as_one_call(tmp_path, monkeypatch):
    executor, service, sessions, calls, origin, rejected = continuation_executor(tmp_path, monkeypatch)
    task = executor.execute_one("worker:implementation")
    assert task["status"] == "succeeded", task.get("error")
    assert calls == [{"cwd": origin["path"], "workload": "implementation", "action": "implement",
                      "importance": None, "task_session": {"task_id": "op-1", "repository": "r" * 64},
                      "max_handoffs": 1}]
    candidate = task["result"]["candidate"]
    assert candidate["base"] == rejected["base"] and candidate["origin_task_id"] == "origin-task"
    assert sessions.submitted == [("op-1", {k: candidate[k] for k in ("revision", "tree", "base")})]


@pytest.mark.parametrize("kwargs, message", [({"stored": False}, "lane's own record"),
                                             ({"origin_status": "running"}, "unresolved owner"),
                                             ({"origin_status": "blocked"}, "unresolved owner")])
def test_executor_refuses_a_forged_binding_or_a_live_origin_before_any_provider(tmp_path, monkeypatch, kwargs, message):
    executor, service, sessions, calls, _, _ = continuation_executor(tmp_path, monkeypatch, **kwargs)
    task = executor.execute_one("worker:implementation")
    assert calls == [] and sessions.submitted == [] and task["status"] in {"retry", "failed"}
    assert message in str(task["error"])


def test_the_committed_lead_review_is_recorded_on_the_session_after_the_commit_only(tmp_path):
    sessions = RecordingSessions()
    executor = Executor(Harness(MemoryStore(), organization()), None, None, worker_sessions=sessions)
    data = {"origin": {"continuation": {"session": {"task_id": "op-1", "repository": "r"}}}}
    executor._session_review("review_lead", data, {"id": "d-1", "status": "succeeded"})
    executor._session_review("review_lead", data, {"id": "d-2", "status": "blocked"})
    executor._session_review("review_conductor", data, {"id": "d-3", "status": "succeeded"})
    executor._session_review("review_lead", {"origin": {}}, {"id": "d-4", "status": "succeeded"})
    assert sessions.reviews == [("op-1", "d-1")]


def test_an_unadopted_turn_freezes_nothing_on_the_session(tmp_path, monkeypatch):
    executor, _, sessions, calls, _, _ = continuation_executor(tmp_path, monkeypatch, adopted=False)
    assert executor.execute_one("worker:implementation")["status"] == "succeeded"
    assert len(calls) == 1 and sessions.submitted == []


# ---- pure routing ------------------------------------------------------------------------------
def test_routing_table_classification_is_fixed_and_never_guesses():
    job = {"id": "j", "status": "rejected"}
    lead = {"status": "succeeded", "phase": "review_lead", "result": {"accepted": False}}
    assert dc.classify(job, {"operation": {"reason_code": "lead_rejected"}, "lead": lead})["route"] == dc.CORRECTION
    assert dc.classify(job, {"operation": {}, "lead": {**lead, "status": "running"}})["reason_code"] == "review_unproven"
    assert dc.classify({**job, "status": "unknown"}, {})["route"] == dc.RECOVERY
    assert dc.classify({**job, "status": "failed"}, {"operation": {"reason_code": "settlement_failed"}})["route"] == dc.RECOVERY
    assert dc.classify({**job, "status": "failed"}, {"operation": {"reason_code": "idle"}})["route"] is None
    accepted = {**job, "status": "accepted"}
    assert dc.classify(accepted, {"operation": {}})["route"] == dc.CONDUCTOR
    assert dc.classify(accepted, {"operation": {}, "conductor": {"status": "running"}})["route"] is None
    assert dc.classify(accepted, {"operation": {}, "conductor": {"status": "failed"}})["route"] == dc.RECOVERY
    assert dc.classify(accepted, {"operation": {}, "conductor": {"status": "succeeded",
                                                                 "result": {"accepted": True}}})["route"] == dc.DELIVERY
    for state in dc.STATES:
        for target in set(dc.STATES) - set(dc.TRANSITIONS[state]):
            with pytest.raises(dc.ContinuationRefused):
                dc.transition(state, target)


def test_fair_order_serves_each_unheld_family_once_least_recent_first():
    intents = [{"family": "x", "state": dc.RESEARCH_REQUIRED, "reason_code": "two", "updated_at": "3"},
               {"family": "y", "state": dc.COMPLETED, "updated_at": "2"},
               {"family": "z", "state": dc.COMPLETED, "updated_at": "1"}]
    candidates = [{"job_id": "x1", "family": "x"}, {"job_id": "y1", "family": "y", "finished_at": "1"},
                  {"job_id": "y2", "family": "y", "finished_at": "2"}, {"job_id": "z1", "family": "z"},
                  {"job_id": "n1", "family": "n"}]
    assert [c["job_id"] for c in dc.fair_order(candidates, intents)] == ["n1", "z1", "y1"]
    held = [{"family": "h", "state": dc.INTENDED, "hold": {"reason_code": "image_changed"}, "updated_at": "0"}]
    assert dc.blocked_families(held) == {"h": "image_changed"}
    assert [c["job_id"] for c in dc.fair_order([{"job_id": "h1", "family": "h"}, *candidates[:1]], held)] == ["x1"]


# ---- R1: route x state restart table ------------------------------------------------------------
def test_every_open_route_state_has_exactly_one_resume_action_and_terminal_states_have_none():
    for route, states in dc.ROUTE_STATES.items():
        for state in states:
            key = (route, state)
            if state in dc.OPEN_STATES:
                assert key in dc.RESUME, key
                assert callable(getattr(Continuation, "_resume_" + dc.RESUME[key])), key
            else:
                assert key not in dc.RESUME, key
    assert set(dc.RESUME) <= {(r, s) for r, states in dc.ROUTE_STATES.items() for s in states}
    new_effects = {dc.PUBLISH, dc.DISPATCH, dc.REDISPATCH}
    assert {action for action in dc.RESUME.values()} - new_effects == {
        dc.AWAIT_SUCCESSOR, dc.COMPLETE, dc.RECONCILE_LAUNCH, dc.OBSERVE_DELIVERY, dc.OBSERVE_RESEARCH,
        dc.AWAIT_BACKLOG}


class Crash(BaseException):
    """LABELLED injected process death at an exact commit boundary: it escapes every handler, so
    nothing after it runs - exactly what a killed controller leaves behind."""


class CrashingPort:
    """The fixture conductor port with a process death injected at one boundary of the start."""

    def __init__(self, inner, at):
        self.inner, self.at = inner, at

    def available(self):
        if self.at == "intended":
            raise Crash("after the intended commit")
        return self.inner.available()

    def start(self, lane_id, job, launch):
        if self.at == "dispatched":
            raise Crash("after the dispatched commit, before any child")
        self.inner.start(lane_id, job, launch)
        raise Crash("after the child started, before its launch evidence was recorded")

    def poll(self, lane_id, launch):
        return self.inner.poll(lane_id, launch)


class CrashAtComplete(Continuation):
    def _move(self, intent, target, **fields):
        if target == dc.COMPLETED and intent["state"] == dc.RETURNED:
            raise Crash("after the returned commit")
        return super()._move(intent, target, **fields)


@pytest.mark.parametrize("boundary, left", [("intended", dc.INTENDED), ("dispatched", dc.DISPATCHED),
                                            ("started", dc.DISPATCHED), ("returned", dc.RETURNED)])
def test_conductor_restart_after_each_commit_invokes_at_most_once_and_completes(tmp_path, boundary, left):
    world = World(tmp_path)
    world.register()
    job_id = accepted_item(world)
    crashing = (world.build(cls=CrashAtComplete) if boundary == "returned"
                else world.build(conductor=CrashingPort(world.conductor, boundary)))
    with pytest.raises(Crash):
        world.tick(controller=crashing)
    assert only(world.intents(), route=dc.CONDUCTOR)["state"] == left
    for _ in range(3):  # the process is recreated: fresh controllers over the same durable stores
        world.tick(controller=world.build())
    intent = only(world.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.COMPLETED and intent["decision"]["id"] == "cond-" + job_id
    assert intent["decision"]["accepted"] is True
    assert world.conductor.calls == [job_id], "at most one invocation across the crash"
    # Only a launch proven never started (fenced) is followed by a NEW launch identity.
    assert intent["launch"]["sequence"] == (2 if boundary == "dispatched" else 1)
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER, "and the item moves on"


@pytest.mark.parametrize("boundary", ["intended", "published", "enqueued", "returned"])
def test_successor_restart_after_each_commit_admits_one_successor_and_completes(tmp_path, boundary):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    job_id, _ = world.run_next(verdict=False)

    class CrashBind(LaneEvidence):
        def bind(self, document):
            raise Crash("after the intended commit, before the lane binding")

    class CrashEnqueue(Fleet):
        def enqueue(self, *args):
            if boundary == "enqueued":
                super().enqueue(*args)
            raise Crash("around the Fleet admission")
    if boundary == "intended":
        crashing = world.build(lanes=lambda lane: CrashBind(world.lane.store, world.sessions))
    elif boundary in {"published", "enqueued"}:
        crashing = world.build(fleet=CrashEnqueue(world.control))
    else:
        world.tick()
        world.run_next(verdict=True)
        crashing = world.build(cls=CrashAtComplete)
    with pytest.raises(Crash):
        world.tick(controller=crashing)
    expected = {"intended": dc.INTENDED, "published": dc.PUBLISHED, "enqueued": dc.PUBLISHED,
                "returned": dc.RETURNED}[boundary]
    assert only(world.intents(), route=dc.CORRECTION)["state"] == expected
    world.tick(controller=world.build())
    intent = only(world.intents(), route=dc.CORRECTION)
    assert len([job for job in world.jobs() if job.startswith("cont-")]) == 1
    if boundary != "returned":
        assert intent["state"] == dc.ADMITTED
        world.run_next(verdict=True)
        world.tick(controller=world.build())
        intent = only(world.intents(), route=dc.CORRECTION)
    assert intent["state"] == dc.COMPLETED and intent["reason_code"] == "successor_accepted"
    assert world.jobs()[job_id]["status"] == "rejected", "the origin stays rejected"


# ---- R2: delivery bound to the policy target and exact candidate ----------------------------------
def test_delivery_is_bound_to_the_policy_target_and_the_exact_release_candidate(tmp_path):
    world = World(tmp_path)
    world.register()
    job_id = accepted_item(world)
    world.tick()
    release = "rel-" + job_id
    deliver(world, "plan-other", release, "active", target="other-host")
    world.tick()
    intent = only(world.intents(), route=dc.DELIVERY)
    assert intent["state"] == dc.AWAITING_OWNER, "another target's active plan completes nothing here"
    assert intent["delivery_binding"] == {"target_id": "fleet-host", "release_id": release, "revision": CANDIDATE}
    # One release, two targets: the other one is rolled back, the intended one is still pending.
    deliver(world, "plan-other", release, "rolled_back", target="other-host")
    deliver(world, "plan-mine", release, "awaiting_ci")
    quiet = deepcopy(world.control.data)
    for _ in range(2):
        world.tick()
    assert world.control.data == quiet, "a foreign rollback neither pauses nor completes this family"

    def skipped_reason():
        result = world.tick()
        return [row["reason_code"] for row in result["skipped"] if row["subject"] == intent["id"]]
    deliver(world, "plan-mine", release, "active", revision="0" * 40)
    assert skipped_reason() == ["delivery_stale"] and world.control.data == quiet
    deliver(world, "plan-mine", release, "active")
    deliver(world, "plan-dup", release, "rolled_back")
    assert skipped_reason() == ["delivery_ambiguous"] and world.control.data == quiet
    deliver(world, "plan-dup", release, "rolled_back", target="other-host")
    with world.lane.store.transaction() as tx:
        record = tx.get("releases", release)
        tx.put("releases", release, {**record, "candidate": {**record["candidate"], "revision": "1" * 40}})
    assert skipped_reason() == ["delivery_release_candidate_mismatch"] and world.control.data == quiet
    with world.lane.store.transaction() as tx:
        tx.put("releases", release, record)
    world.tick()
    done = only(world.intents(), route=dc.DELIVERY)
    assert done["state"] == dc.COMPLETED and done["delivery_plan"] == {"plan_id": "plan-mine", "plan_sha256": "5" * 64,
                                                                      "stage": "active"}
    assert only(world.intents(), route=dc.NEXT_ITEM)["state"] == dc.AWAITING_OWNER


def test_bind_delivery_selects_only_the_exact_target_and_candidate():
    rows = [{"plan_id": "p1", "target_id": "t", "revision": "c" * 40, "stage": "active"},
            {"plan_id": "p2", "target_id": "u", "revision": "c" * 40, "stage": "rolled_back"}]
    release = {"candidate": {"revision": "c" * 40}}
    bound = dc.bind_delivery(rows, "t", "r", "c" * 40, release)
    assert bound["binding"] == dc.DELIVERY_BOUND and bound["plan_id"] == "p1" and bound["foreign"] == 1
    assert dc.bind_delivery(rows[1:], "t", "r", "c" * 40, release)["binding"] == dc.DELIVERY_ABSENT
    assert dc.bind_delivery(rows, "t", "r", None, release)["binding"] == dc.DELIVERY_UNKNOWN
    assert dc.bind_delivery(rows, "t", "r", "c" * 40, {"candidate": {"revision": "d" * 40}})["binding"] == \
        dc.DELIVERY_MISMATCH


# ---- R4: one eligibility guard before every new effect --------------------------------------------
RUNTIME = {"image": IMAGE, "profile": "worker-v1", "session_archive_sha256": ARCHIVE}
DRIFT = [({"image": "other/image:1"}, "image_changed"), ({"profile": "worker-v2"}, "profile_changed"),
         ({"session_archive_sha256": "0" * 64}, "session_archive_changed")]


@pytest.mark.parametrize("change, reason", DRIFT)
def test_drift_during_an_outage_refuses_new_effects_and_preserves_the_original_rows(tmp_path, change, reason):
    world = World(tmp_path)
    world.register()
    world.enqueue("op-1")
    world.tick()
    job_id, _ = world.run_next(verdict=False)
    world.await_review(job_id)

    class DownAtBind(LaneEvidence):
        def bind(self, document):
            raise ConnectionError("lane store outage before the binding (injected)")
    world.tick(controller=world.build(lanes=lambda lane: DownAtBind(world.lane.store, world.sessions)))
    intent = only(world.intents(), route=dc.CORRECTION)
    assert intent["state"] == dc.INTENDED
    stored, lane_before = deepcopy(intent["authorization"]), deepcopy(world.lane.store.data)
    world.runtime = lambda lane: {**RUNTIME, **change}
    result = world.tick(controller=world.build())  # restart after the outage, under drift
    held = only(world.intents(), route=dc.CORRECTION)
    assert held["state"] == dc.INTENDED and held["authorization"] == stored and held["manifest"] == intent["manifest"]
    assert held["hold"]["reason_code"] == reason and held["hold"]["next_owner"] == "operator"
    assert {"subject": held["id"], "reason_code": reason, "next_owner": "operator"} in result["skipped"]
    assert world.binding(held["successor_job"]) is None and len(world.jobs()) == 1, "zero successor"
    assert world.lane.store.data == lane_before
    status = world.controller.status("policy-1")
    assert status["held_families"] == {job_id: reason}
    assert "changed authorization" in only({r["id"]: r for r in status["intents"]}, route=dc.CORRECTION)["next_action"]
    blocked = [e for e in world.events() if e["event_type"] == "operations.continuation_blocked"]
    assert blocked[-1]["reason_code"] == reason and blocked[-1]["attributes"]["state"] == dc.INTENDED
    quiet = deepcopy(world.control.data)
    world.tick()
    assert world.control.data == quiet, "a held intent writes nothing on idle ticks"
    world.runtime = lambda lane: dict(RUNTIME)  # the authorized binding is restored by its owner
    world.tick()
    resumed = only(world.intents(), route=dc.CORRECTION)
    assert resumed["state"] == dc.ADMITTED and resumed["hold"] is None and len(world.jobs()) == 2


def test_conductor_drift_after_an_outage_starts_nothing_and_a_changed_pin_only_drains(tmp_path):
    world = World(tmp_path)
    world.register()
    accepted_item(world)

    class Down(ConductorFixture):
        def available(self):
            raise ConnectionError("slot probe unavailable (injected)")
    world.tick(controller=world.build(conductor=Down(world.lane)))
    assert only(world.intents(), route=dc.CONDUCTOR)["state"] == dc.INTENDED
    world.runtime = lambda lane: {**RUNTIME, "image": "other/image:1"}
    for _ in range(2):
        world.tick(controller=world.build())
    intent = only(world.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.INTENDED and intent["hold"]["reason_code"] == "image_changed"
    assert world.conductor.calls == [], "zero provider start under drift"
    world.runtime = lambda lane: dict(RUNTIME)
    before = deepcopy(world.control.data)
    refused = world.controller.tick("policy-1", pin_sha256="0" * 64, runtime=world.runtime)
    assert refused["outcome"] == "refused" and refused["reason_code"] == "policy_changed"
    assert world.control.data == before and world.conductor.calls == []


def test_drift_while_the_child_runs_retains_its_outcome_under_the_original_binding(tmp_path):
    world = World(tmp_path)
    world.conductor.pending = True
    world.register()
    job_id = accepted_item(world)
    world.tick()
    intent = only(world.intents(), route=dc.CONDUCTOR)
    launch = intent["launch"]["id"]
    assert intent["state"] == dc.DISPATCHED and intent["launch"]["state"] == "started"
    assert world.controller.unresolved("policy-1", owned=[launch]) == []
    assert world.controller.unresolved("policy-1") == [launch], "not owned here: unresolved, never idle"
    world.runtime = lambda lane: {**RUNTIME, "image": "other/image:1"}
    running = deepcopy(world.control.data)
    world.tick()
    assert world.control.data == running, "a running child is observed, not replaced"
    world.conductor.finish(launch)
    world.tick()
    world.tick()
    intents = world.intents()
    settled = only(intents, route=dc.CONDUCTOR)
    assert settled["state"] == dc.COMPLETED and settled["decision"]["accepted"] is True
    assert settled["authorization"] == intent["authorization"], "retained under the original binding"
    refused = only(intents, route=dc.DELIVERY)
    assert refused["state"] == dc.REFUSED and refused["reason_code"] == "image_changed", "never adopted"
    assert world.conductor.calls == [job_id]


def test_changed_runtime_after_a_lost_dispatch_response_reconciles_the_old_child_but_never_replaces_it(tmp_path):
    # (a) the child DID start before the response was lost: it is reconciled to its outcome.
    world = World(tmp_path)
    world.conductor.pending = world.conductor.lost = True
    world.register()
    job_id = accepted_item(world)
    world.tick()
    intent = only(world.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.DISPATCHED and intent["launch"]["state"] == "start_unconfirmed"
    world.runtime = lambda lane: {**RUNTIME, "image": "other/image:1"}
    world.tick()
    world.conductor.finish(intent["launch"]["id"])
    world.tick()
    assert only(world.intents(), route=dc.CONDUCTOR)["state"] == dc.COMPLETED
    assert world.conductor.calls == [job_id]
    # (b) no child ever started: it is proven absent, and the guard refuses the replacement.
    other = World(tmp_path / "b")
    other.conductor.raise_error = ConnectionError("spawn response lost before any child (injected)")
    other.register()
    accepted_item(other)
    other.tick()
    other.conductor.raise_error = None
    other.runtime = lambda lane: {**RUNTIME, "image": "other/image:1"}
    for _ in range(3):
        other.tick()
    intent = only(other.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.AWAITING_OWNER and intent["reason_code"] == "conductor_not_launched"
    assert intent["launch"]["state"] == dc.LAUNCH_ABSENT and intent["hold"]["reason_code"] == "image_changed"
    assert other.conductor.calls == [], "no replacement under the changed runtime"


def test_an_unclaimed_row_is_relaunched_only_under_new_identities_and_boundedly(tmp_path):
    world = World(tmp_path)
    world.conductor.pending = True
    world.register()
    job_id = accepted_item(world)
    for _ in range(dc.MAX_LAUNCHES + 2):
        world.tick()
        for launch, state in list(world.conductor.launches.items()):
            if state == "running":
                world.conductor.finish(launch, decide=False)  # the child exited having claimed nothing
        world.tick()
    intent = only(world.intents(), route=dc.CONDUCTOR)
    assert intent["state"] == dc.REFUSED and intent["reason_code"] == "conductor_launch_exhausted"
    assert len(set(world.conductor.launches)) == dc.MAX_LAUNCHES and world.conductor.calls == [job_id] * dc.MAX_LAUNCHES


# ---- R3: the runner accounts a pending conductor and keeps serving another family ----------------
class FixturePass:
    """The `ContinuationPass` surface over the fixture world (the real one is exercised with a real
    child process in test_continuation_process.py)."""

    def __init__(self, world):
        self.world = world

    def __call__(self):
        return self.world.tick()

    def drain(self):
        return self.world.controller.drain("policy-1")

    def owned(self):
        return [launch for launch, state in self.world.conductor.launches.items() if state == "running"]

    def unresolved(self):
        return self.world.controller.unresolved("policy-1", self.owned())


def test_runner_counts_a_pending_conductor_as_owned_work_takes_a_slot_and_drains_it_on_stop(tmp_path):
    world = World(tmp_path)
    world.conductor.pending = True
    world.register()
    job_id = accepted_item(world)
    world.enqueue("op-2", "docs/b.md")
    heartbeats, sleeps, flags = [], [], {"stop": False}

    class Control:  # LABELLED fixture of the managed runtime control
        def admission_open(self):
            return True

        def stop_requested(self):
            return flags["stop"]

        def heartbeat(self, state):
            heartbeats.append(dict(state, op2=world.jobs()["op-2"]["status"]))

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            flags["stop"] = True
        elif len(sleeps) == 2:
            world.conductor.finish(next(iter(world.conductor.launches)))
    passes = FixturePass(world)
    runner = FleetRunner(world.fleet, LaneLauncher(world, [True]), sleep=sleep, interval=0, control=Control(),
                         continuation=passes)
    summary = runner.run(once=False)
    assert summary["stopped"] is True and world.jobs()["op-2"]["status"] == "accepted"
    assert {"admission": "open", "active": 1, "unresolved": 0, "op2": "accepted"} in heartbeats, \
        "the other family was admitted and reaped while the conductor was pending"
    assert {"admission": "stopping", "active": 1, "unresolved": 0, "op2": "accepted"} in heartbeats
    assert only(world.intents(), origin_job=job_id, route=dc.CONDUCTOR)["state"] == dc.COMPLETED
    assert world.conductor.calls == [job_id], "the second conductor waited for the bounded slot"
    assert summary["continuation"]["state"] == "draining" and passes.owned() == []
