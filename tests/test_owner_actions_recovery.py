"""INV-OWNER-ACTIONS-001 policy v2 and INV-CONTINUATION-001 policy-triggered requalification (aibox
whole-goal adjudication C1-C3): `delivery_requalify`, `research_dispatch` and one owner process ticking two
disjoint policies against ONE harness lane store, controller and target.

Real: the MemoryStores (Fleet control store and one lane store), the Fleet, finite Operation, Workflow,
Portfolio, ResearchProgram with its ProgramRunner over a real temporary Git repository, the continuation
owner (`requalify_delivery`, `accept_research`, its tick), Releases, HostDelivery (register, stages,
`_publish`/`_merge` base checks, `withdraw` with its queue fence) and the Git plan publisher.

LABELLED fixtures, never evidence of a live run: the lane executor (`RebasingExecutor`, test_operation's
FakeExecutor with a per-job candidate revision cut on the assignment base), the conductor
(`ReleasingConductor`), the research council (`FakeCouncil`), the independent assessor (`FakeAssessor`),
the GitHub double (`FakeGitHub(fast_forward=True)`), the remote-main reader (`GitHubMainline`, it answers
from that double) and the research launch port (`InProcessResearch`: its `start` runs the real
ProgramRunner tick in-process under the launch id as the cycle owner token; a happy-path fixture only -
process liveness is tests/test_owner_actions_research_process.py). The host switch, startup and owner
canary after a merge are NOT re-run here: a merged delivery is moved to `active` by a LABELLED write, and
those stages are covered by tests/test_owner_delivery.py. No model, provider, network or production state
is touched.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from test_continuation import BASE, GOAL, World, only
from test_continuation_research import two_strikes
from test_host_delivery import CHECK, Clock, FakeGitHub, targets_document
from test_operation import FakeExecutor
from test_owner_actions import REPORT, FakeAssessor
from test_owner_delivery import ReleasingConductor, git_repository
from test_research_investigations import DEFINITIONS
from test_research_program import build
from test_research_program_fixtures import FakeBudget, FakeCouncil, config

from codex_harness.adapters.owner_actions import GitPlanPublisher, TargetFiles
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.continuation import BUCKET_INTENTS
from codex_harness.application.host_delivery import BUCKET_INTENTS as HD_INTENTS
from codex_harness.application.host_delivery import HostDelivery
from codex_harness.application.owner_actions import BUCKET_ACTIONS, OwnerActions
from codex_harness.application.portfolio import Portfolio, family_id
from codex_harness.application.research_program import (
    BUCKET_CYCLES,
    BUCKET_DISPATCHES,
    BUCKET_PROGRAMS,
)
from codex_harness.bootstrap import organization
from codex_harness.domain import continuation as dc
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import ACTIVE, BLOCKED, MERGED, WITHDRAWN
from codex_harness.domain.model import digest
from codex_harness.domain.research_program import CYCLE_DONE, cycle_id, validate_config

TARGET = "fleet-host"
REPO = "github:zeus-owner/zeus-harness"
PIN = {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"}
PROGRAM = "rp-b2"


# ---- LABELLED fixtures --------------------------------------------------------------------------------------
class RebasingExecutor(FakeExecutor):
    """LABELLED lane executor: FakeExecutor, but an accepted candidate gets its own revision (a digest of
    the task id) and is cut on the assignment's own base, as a real worker's commit would be; its evidence
    inspection binds that revision. Failing attempts keep FakeExecutor's exact shape."""

    def execute_one(self, agent, expected=None):
        task = super().execute_one(agent, expected)
        if self.worker != "succeeded" or self.inspection != "bound":
            return task
        with self.svc.store.transaction() as tx:
            row = tx.get("tasks", task["id"])
            base = ((row.get("message") or {}).get("where") or {}).get("revision") or BASE
            candidate = {**row["result"]["candidate"], "revision": digest(["rev", row["id"]])[:40], "base": base}
            row["result"] = {**row["result"], "candidate": candidate}
            tx.put("tasks", row["id"], row)
            inspection = tx.get("evidence_inspections", "insp-" + row["id"])
            inspection["binding"] = {**inspection["binding"], "source_revision": candidate["revision"]}
            tx.put("evidence_inspections", inspection["id"], inspection)
            for key in [r["message"]["message_id"] for r in tx.scan("outbox")
                        if r["message"]["type"] == "task.result"
                        and r["message"]["what"]["details"].get("task_id") == row["id"]]:
                entry = tx.get("outbox", key)
                entry["message"]["what"]["details"]["result"] = row["result"]
                tx.put("outbox", key, entry)
            return row


class GitHubMainline:
    """LABELLED remote-main reader answering from the GitHub double: `remote_main` is its main; every
    commit exists; the goal blob is GOAL's digest at every revision unless `goal_sha` says otherwise."""

    def __init__(self, github, goal_sha=GOAL["sha256"]):
        self.github, self.goal_sha, self.error = github, goal_sha, None

    def __call__(self, lane_id):
        assert lane_id == "a"
        return self

    def remote_main(self):
        if self.error is not None:
            raise self.error
        return self.github.main

    def commit_exists(self, revision):
        return True

    def goal(self, revision, path):
        return {"mode": "100644", "sha256": self.goal_sha, "bytes": 3}


class InProcessResearch:
    """LABELLED research launch port (happy-path fixture). `probe` answers `ok`; `start` runs the REAL
    ProgramRunner tick in this process with the launch id as the cycle owner token (what `research-program
    run --cycle-owner` does in the child) unless `hold` keeps it "running"; `poll` answers in the guardian's
    observation shapes. `starts` counts spawns per launch id."""

    def __init__(self, env, *, ok=True, hold=False, foreign=False):
        self.env, self.ok, self.hold, self.foreign = env, ok, hold, foreign
        self.starts, self.launches, self.probes = [], {}, 0

    def probe(self):
        self.probes += 1
        return {"ok": self.ok, "reason_code": None if self.ok else "codex_unresolved", "codex": None, "node": None}

    def start(self, launch, program_id, lane):
        if launch in self.launches:
            return {"cached": True}
        self.starts.append(launch)
        self.launches[launch] = "running"
        if not self.hold:
            self.run(launch, program_id)
        return {"cached": False, "pid": 4242}

    def run(self, launch, program_id):
        token = "f" * 64 if self.foreign else launch       # foreign: another owner reserves the same number
        self.env.programs.token = lambda: token
        self.env.runner.tick(program_id)
        self.launches[launch] = "exited"

    def poll(self, launch):
        state = self.launches.get(launch)
        if state is None:
            return {"state": "absent", "owned": False, "proof": {"kind": "fenced"}}
        if state == "running":
            return {"state": "running", "owned": True}
        if state == "unknown":
            return {"state": "unknown", "owned": False, "cleanup_confirmed": False}
        return {"state": "exited", "owned": False, "exit_code": 0, "cleanup_confirmed": True}


# ---- the world: two disjoint continuation policies, two owner policies, one lane store/target -----------
def owner_policy(policy_id, continuation, *, research=None, max_per_family=1, requalify=True, schema=None):
    document = {"schema": schema or do.POLICY_SCHEMA_V2, "id": policy_id, "enabled": True,
                "continuation_policy": continuation, "assessment": {"model_label": "labelled-fixture-assessor"},
                "delivery": {"target_id": TARGET, "repository": REPO, "required_checks": [CHECK],
                             "canary_check_id": "startup_identity", "ci_timeout_seconds": 300,
                             "consumption_timeout_seconds": 120}, "canary": None}
    if document["schema"] == do.POLICY_SCHEMA_V2:
        document["requalification"] = {"enabled": True, "reasons": ["reviewed_base_moved"],
                                       "max_per_family": max_per_family} if requalify else None
        document["research"] = research
    return document


class Chain:
    """One Fleet control store and ONE harness lane store: continuation `policy-1` (b2, docs/a.md) and
    `policy-i1` (i1, docs/b.md), owner policies `owners-002` and `owners-i1`, ONE OwnerActions (one owner
    process) and ONE HostDelivery controller over the lane store and the one target."""

    def __init__(self, tmp_path, *, max_per_family=1, research=True, owner_schema=None):
        self.tmp = tmp_path
        world = World(tmp_path, conductor=False)
        world.conductor = ReleasingConductor(world.lane, repository=REPO)
        world.controller = world.build()
        world.document["allowed_paths"] = ["docs/a.md"]
        world.register()
        self.i1_document = {**world.document, "id": "policy-i1", "allowed_paths": ["docs/b.md"]}
        world.controller.register(self.i1_document, world.pin)
        self.world, self.org = world, organization()
        self.github = FakeGitHub(fast_forward=True)
        self.github.main = BASE                            # M0: the base every candidate was captured on
        self.github.merged_tree = "7" * 40                 # the fixture worker's candidate tree
        self.clock = Clock()
        self.host = HostDelivery(world.lane.store, self.org, github=self.github, clock=self.clock, enabled=True,
                                 resume_seconds=0)
        self.host.register_targets(targets_document(tmp_path, target_id=TARGET))
        self.publisher = GitPlanPublisher(git_repository(tmp_path))
        self.mainline = GitHubMainline(self.github)
        self.assessor = FakeAssessor(world)
        self.env = build(tmp_path / "research", store=world.control, council=FakeCouncil(world.control,
                                                                                        status="accepted"))
        self.research = InProcessResearch(self.env)
        self.requalify_calls = []
        self.owner = self.build_owner()
        research_block = {"enabled": True, "program_id": PROGRAM, "lane": "a"} if research else None
        self.owner.register(owner_policy("owners-002", "policy-1", research=research_block,
                                         max_per_family=max_per_family, schema=owner_schema), PIN)
        self.owner.register(owner_policy("owners-i1", "policy-i1", max_per_family=max_per_family,
                                         schema=owner_schema), PIN)

    def build_owner(self, **overrides):
        ports = {"continuation": self.world.controller, "org": self.org, "lanes": self.world.lanes,
                 "deliveries": lambda lane: self.host, "publisher": lambda lane: self.publisher,
                 "assessments": self.assessor, "targets": TargetFiles(),
                 "withdrawals": lambda lane: self.host, "mainline": self.mainline, "requalify": self.requalify,
                 "artifacts": self.world.artifacts, "research": self.research,
                 "ledger": lambda: FakeBudget().counts(), **overrides}
        return OwnerActions(self.world.control, **ports)

    def requalify(self, document):
        self.requalify_calls.append(deepcopy(document))
        return self.world.controller.requalify_delivery(document, pin_sha256=self.world.pin["sha256"],
                                                        runtime=self.world.runtime, mainline=self.mainline)

    # ---- the owners, each one bounded step at a time ----
    def owners(self, owner=None):
        """One owner-process wakeup: both policies ticked in turn (the adapter's `tick_policies`)."""
        owner = owner or self.owner
        return [owner.tick(policy_id) for policy_id in ("owners-002", "owners-i1")]

    def continuation(self):
        for policy in ("policy-1", "policy-i1"):
            self.world.controller.tick(policy, pin_sha256=self.world.pin["sha256"], runtime=self.world.runtime)

    def run_next(self, **executor):
        """The Fleet admits its oldest admissible job; the lane runs it through the REAL Operation."""
        from test_continuation import IDENTITY
        from test_operation import Bus, Collector
        from test_operation import FakeBudget as OperationBudget

        from codex_harness.application.operation import Operation
        from codex_harness.application.workflow import Workflow

        world = self.world
        job = world.fleet.admit_one()["job"]
        assert job is not None, "nothing admissible"
        operation = Operation(world.lane, RebasingExecutor(world.lane, **executor), Bus(),
                              Workflow(world.lane.store, world.lane.org), OperationBudget(), Collector())
        receipt = operation.run(job["manifest"], IDENTITY, job["goal"])
        world.fleet.finalize(job["id"], job["owner_token"], {
            "status": receipt["status"], "reason_code": receipt["reason_code"], "exit_code": receipt["exit_code"],
            "owner_handoff": receipt["owner_handoff"], "calls": receipt["calls"]})
        return job["id"], receipt

    def deliver(self, plan_id, until=MERGED, limit=8):
        """The one controller, ticked on exactly this plan until it merges or blocks."""
        results = []
        for _ in range(limit):
            results.append(self.host.tick(plan_id))
            self.clock.advance(1)
            if results[-1]["stage"] in {until, BLOCKED}:
                break
        return results

    def consumed(self, plan_id):
        """LABELLED: the merged delivery's switch, startup and owner canary (tests/test_owner_delivery.py)
        are represented by its terminal `active` stage; nothing here claims they ran."""
        with self.world.lane.store.transaction() as tx:
            row = tx.get(HD_INTENTS, plan_id)
            assert row["stage"] == MERGED
            tx.put(HD_INTENTS, plan_id, {**row, "stage": ACTIVE})

    # ---- reads ----
    def actions(self, kind=None):
        with self.world.control.transaction() as tx:
            rows = tx.scan(BUCKET_ACTIONS)
        return [row for row in rows if kind is None or row["kind"] == kind]

    def plan_action(self, intent_id):
        return only({r["id"]: r for r in self.actions(do.DELIVERY_PLAN)}, **{"subject": {"intent_id": intent_id,
                                                                                         "lane": "a"}})

    def hd(self, plan_id):
        with self.world.lane.store.transaction() as tx:
            return tx.get(HD_INTENTS, plan_id)

    def delivery_intent(self, policy, origin=None):
        rows = {k: v for k, v in self.world.intents().items() if v["policy_id"] == policy
                and v["route"] == dc.DELIVERY and v["state"] in dc.REQUALIFICATION_REQUALIFIABLE}
        if origin is not None:
            rows = {k: v for k, v in rows.items() if v["origin_job"] == origin}
        return only(rows)


def accepted(chain, op_id, path, policy):
    """One item of `policy` through worker, lead and conductor to an `awaiting_owner` delivery intent."""
    world = chain.world
    world.enqueue(op_id, path)
    chain.continuation()
    job, receipt = chain.run_next(verdict=True)
    assert job == op_id and receipt["status"] == "accepted", receipt
    chain.continuation()
    chain.continuation()
    return chain.delivery_intent(policy, job)


def registered_plan(chain, intent, limit=4):
    """owner-actions publishes the exact plan to Git and registers it (one step per wakeup)."""
    for _ in range(limit):
        chain.owners()
        plans = [r for r in chain.actions(do.DELIVERY_PLAN) if r["subject"]["intent_id"] == intent["id"]]
        if plans and plans[0]["state"] == do.COMPLETED:
            return plans[0]
    raise AssertionError([(r["state"], r["reason_code"]) for r in plans])


def planned_and_merged(chain, intent):
    """owner-actions publishes and registers the plan; the one controller merges it."""
    plan = registered_plan(chain, intent)
    return plan, chain.deliver(plan["plan_id"])


def released(chain, research_intent):
    """Portfolio groups the two failures and the owner binds them (the existing portfolio owner's step,
    run here as in test_continuation_research); the policy's program is registered PAUSED with an
    investigation source scoped to the family's reason code."""
    jobs = chain.world.jobs()
    attempts = sorted({a["job"] for a in dc.research_attempts(list(chain.world.intents().values()), research_intent)})
    portfolio = Portfolio(chain.world.control, DEFINITIONS)
    for job in attempts:
        portfolio.bind(job, "ops", "c1")
    portfolio.reconcile()
    cfg = validate_config(config(chain.env.head, id=PROGRAM, investigation_source={
        "topic": "storage", "project_ids": ["ops"], "reason_codes": [jobs[attempts[0]]["reason_code"]]}),
        packaged_policy())
    chain.env.programs.register(cfg, chain.env.identity, [])
    return attempts, family_id(jobs[attempts[0]]["status"], jobs[attempts[0]]["reason_code"])


# ===== T1-9 + C2 + C3: the whole two-family chain, no human relay ==========================================
def test_b2_held_at_f4_while_i1_delivers_then_b2_is_researched_requalified_on_i1s_merge_and_delivered(tmp_path):
    chain = Chain(tmp_path)
    world = chain.world
    # b2 fails twice (F0-F4): held for research. i1 (the other policy, other paths) is accepted.
    root, successor, research = two_strikes(world, "op-b2", "docs/a.md")
    attempts, investigation = released(chain, research)
    assert attempts == sorted([root, successor])
    i1 = accepted(chain, "op-i1", "docs/b.md", "policy-i1")
    # ONE owner wakeup ticks both policies: owners-002 dispatches the research tick for b2 while owners-i1
    # publishes i1's plan. The research child is polled, never waited on.
    chain.owners()
    [dispatch] = chain.actions(do.RESEARCH_DISPATCH)
    assert dispatch["policy_id"] == "owners-002" and dispatch["binding"]["investigation"] == investigation
    assert dispatch["binding"]["attempts"] == attempts and chain.research.probes == 1
    plan_i1, merged = planned_and_merged(chain, i1)
    assert merged[-1]["stage"] == MERGED and chain.github.main == plan_i1["plan"]["revision"]
    m1 = chain.github.main
    chain.consumed(plan_i1["plan_id"])
    # The research child reserved exactly the expected cycle under its launch id and the council accepted.
    [dispatch] = chain.actions(do.RESEARCH_DISPATCH)
    assert dispatch["state"] == do.COMPLETED and dispatch["reason_code"] == "research_dispatch_accepted"
    with world.control.transaction() as tx:
        cycle = tx.get(BUCKET_CYCLES, cycle_id(PROGRAM, dispatch["binding"]["expected_cycle"]))
        claim = tx.get(BUCKET_DISPATCHES, investigation)
    assert cycle["owner"] == dispatch["launch_id"] and claim["cycle"] == cycle["id"]
    assert chain.research.starts == [dispatch["launch_id"]]
    # The existing research_receipt action (independent assessment) and continuation release the hold.
    for _ in range(3):
        chain.owners()
    assert research["id"] in {r["subject"]["intent_id"] for r in chain.actions(do.RESEARCH_RECEIPT)
                              if r["state"] == do.COMPLETED}
    chain.continuation()
    repair = only(world.intents(), origin_job=successor, route=dc.EVIDENCE_REPAIR)
    assert repair["state"] == dc.ADMITTED
    # The repair successor inherits b2's ORIGINAL base M0; its accepted candidate is therefore stale.
    job3, receipt = chain.run_next(verdict=True)
    assert job3 == repair["successor_job"] and receipt["status"] == "accepted"
    assert world.jobs()[job3]["manifest"]["base_revision"] == BASE != m1
    chain.continuation()
    chain.continuation()
    b2 = chain.delivery_intent("policy-1", job3)
    plan_b2 = registered_plan(chain, b2)
    blocked = chain.deliver(plan_b2["plan_id"])
    assert blocked[-1]["stage"] == BLOCKED and blocked[-1]["reason_code"] == "reviewed_base_moved", [
        (r.get("outcome"), r.get("stage"), r.get("reason_code")) for r in blocked]
    assert chain.github.publishes == 1 and chain.github.merges == 1, "zero PR and zero merge for the stale one"
    # owners-002 withdraws it (observed stale now, host untouched) and requalifies it on i1's merge.
    chain.continuation()
    chain.owners()
    [requalify] = chain.actions(do.DELIVERY_REQUALIFY)
    assert requalify["state"] == do.COMPLETED and requalify["cap_slot"] == 1, requalify["reason_code"]
    assert chain.hd(plan_b2["plan_id"])["stage"] == WITHDRAWN
    [document] = chain.requalify_calls
    assert document["main_revision"] == m1 and "goal_migration" not in document
    assert requalify["document"] == document and requalify["document_sha256"] == digest(document)
    new = world.intents()[dc.requalification_id(b2["id"])]
    assert new["route"] == dc.REQUALIFICATION and world.intents()[b2["id"]]["state"] == dc.SUPERSEDED
    # The existing path admits a FRESH job on M1; it is reviewed again and delivered on M1.
    chain.continuation()
    job4, receipt = chain.run_next(verdict=True)
    assert job4 == new["successor_job"] and receipt["status"] == "accepted"
    assert world.jobs()[job4]["manifest"]["base_revision"] == m1
    chain.continuation()
    chain.continuation()
    final = chain.delivery_intent("policy-1", job4)
    plan4, merged = planned_and_merged(chain, final)
    assert merged[-1]["stage"] == MERGED and chain.github.main == plan4["plan"]["revision"]
    assert chain.github.mainline == [plan_i1["plan"]["revision"], plan4["plan"]["revision"]]
    assert chain.github.merges == 2 and chain.github.publishes == 2, "no stale merge ever happened"
    # Every step was an owner, never the test: one requalification, one dispatch, idle afterwards.
    chain.consumed(plan4["plan_id"])
    snapshot = deepcopy(world.control.data)
    chain.owners()
    chain.owners(chain.build_owner())                      # a restarted owner process: nothing more
    assert world.control.data == snapshot
    assert len(chain.requalify_calls) == 1 and len(chain.research.starts) == 1


# ===== T1-1 / T1-4 / T1-5 / T1-6 / T1-7 / T1-8: one stale candidate, then the matrix ===========================
def stale(tmp_path, **kwargs):
    """The critique's counterexample: two candidates of two families both captured on M0 before any delivery
    intent exists; the first (i1) is merged, the second (b2) is blocked at `_publish` with no PR."""
    chain = Chain(tmp_path, research=False, **kwargs)
    first = accepted(chain, "op-i1", "docs/b.md", "policy-i1")
    second = accepted(chain, "op-b2", "docs/a.md", "policy-1")
    plan1, _ = planned_and_merged(chain, first)
    chain.consumed(plan1["plan_id"])
    plan2 = registered_plan(chain, second)
    blocked = chain.deliver(plan2["plan_id"])
    assert blocked[-1]["reason_code"] == "reviewed_base_moved" and chain.github.publishes == 1
    chain.continuation()
    return chain, second, plan2, plan1


def requalified(chain):
    [row] = chain.actions(do.DELIVERY_REQUALIFY)
    return row


def test_the_second_candidate_on_the_stale_base_is_requalified_on_the_first_merge_and_delivered(tmp_path):
    chain, second, plan2, plan1 = stale(tmp_path)
    chain.owners()
    row = requalified(chain)
    assert row["state"] == do.COMPLETED and row["policy_id"] == "owners-002"
    assert row["binding"]["reason"] == "reviewed_base_moved" and row["binding"]["plan_id"] == plan2["plan_id"]
    chain.continuation()
    job, _ = chain.run_next(verdict=True)
    assert chain.world.jobs()[job]["manifest"]["base_revision"] == plan1["plan"]["revision"]
    chain.continuation()
    chain.continuation()
    plan, merged = planned_and_merged(chain, chain.delivery_intent("policy-1", job))
    assert merged[-1]["stage"] == MERGED and chain.github.publishes == 2 and chain.github.merges == 2


def test_a_version1_policy_never_withdraws_requalifies_or_dispatches(tmp_path):
    chain, second, plan2, _ = stale(tmp_path, owner_schema=do.POLICY_SCHEMA)
    snapshot = deepcopy(chain.world.control.data)
    chain.owners()
    assert chain.actions(do.DELIVERY_REQUALIFY) == [] and chain.hd(plan2["plan_id"])["stage"] == BLOCKED
    assert chain.world.control.data == snapshot and chain.requalify_calls == []


class Lossy:
    """LABELLED injected loss of ONE response AFTER the wrapped owner's effect happened."""

    def __init__(self, inner, method):
        self.inner, self.method, self.lost, self.calls = inner, method, 1, 0

    def __getattr__(self, name):
        attribute = getattr(self.inner, name)
        if name != self.method:
            return attribute

        def call(*args, **kwargs):
            self.calls += 1
            result = attribute(*args, **kwargs)
            if self.lost:
                self.lost -= 1
                raise TimeoutError("response lost after the effect (labelled injected fault)")
            return result
        return call


@pytest.mark.parametrize("crash", ["before_slot", "withdraw_response_lost", "before_document",
                                   "requalify_response_lost"])
def test_a_restart_at_any_persisted_state_replays_to_one_withdrawal_and_one_requalification(tmp_path, crash):
    """Control matrix, restart axis (T1-4): each row is persisted before its effect and replays."""
    chain, second, plan2, plan1 = stale(tmp_path)
    if crash == "before_slot":
        failing = chain.build_owner(withdrawals=lambda lane: (_ for _ in ()).throw(RuntimeError("crash")))
        failing.tick("owners-002")
        assert requalified(chain)["state"] == do.WITHDRAWING   # slot and rationale persisted, no withdrawal
    elif crash == "withdraw_response_lost":
        lossy = Lossy(chain.host, "withdraw")
        chain.build_owner(withdrawals=lambda lane: lossy).tick("owners-002")
        assert requalified(chain)["state"] == do.WITHDRAWING and chain.hd(plan2["plan_id"])["stage"] == WITHDRAWN
    elif crash == "before_document":
        broken = GitHubMainline(chain.github)
        broken.error = OSError("ls-remote unavailable (labelled)")
        chain.build_owner(mainline=broken).tick("owners-002")
        row = requalified(chain)
        assert row["state"] == do.REQUALIFYING and row.get("document") is None
    else:
        lossy = Lossy(chain, "requalify")
        chain.build_owner(requalify=lossy.requalify).tick("owners-002")
        row = requalified(chain)
        assert row["state"] == do.REQUALIFYING and row["document"] is not None
        assert dc.requalification_id(second["id"]) in chain.world.intents(), "the effect happened"
    restarted = chain.build_owner()
    for _ in range(3):
        restarted.tick("owners-002")
    row = requalified(chain)
    assert row["state"] == do.COMPLETED and row["cap_slot"] == 1, row["reason_code"]
    requalifications = [r for r in chain.world.intents().values() if r["route"] == dc.REQUALIFICATION]
    assert len(requalifications) == 1 and chain.hd(plan2["plan_id"])["withdrawal"]["evidence_ref"] == \
        row["rationale_ref"]
    # Every document handed to the owner API is the persisted one, byte for byte.
    assert all(document == row["document"] for document in chain.requalify_calls)
    assert chain.github.publishes == 1 and chain.github.merges == 1


def test_main_moving_between_the_persisted_document_and_the_call_refuses_and_the_cap_holds(tmp_path):
    """T1-5: the persisted document names M1; main moves to M2 before `requalify_delivery` reads it."""
    chain, second, plan2, _ = stale(tmp_path)

    def moving(document):
        chain.github.main = "8" * 40               # LABELLED: another writer merges meanwhile
        return chain.requalify(document)
    chain.build_owner(requalify=moving).tick("owners-002")
    row = requalified(chain)
    assert row["state"] == do.REFUSED and row["reason_code"] == "requalification_main_changed"
    assert dc.requalification_id(second["id"]) not in chain.world.intents()
    snapshot = deepcopy(chain.world.control.data)
    for _ in range(3):
        chain.owners()
    assert chain.world.control.data == snapshot, "no second action without a new blocked plan"


def test_a_goal_changed_at_the_new_main_is_a_named_refusal_and_no_migration_is_written(tmp_path):
    """T1-6."""
    chain, second, _, _ = stale(tmp_path)
    chain.mainline.goal_sha = "3" * 64                 # LABELLED: the goal blob differs at M1
    chain.owners()
    row = requalified(chain)
    assert row["state"] == do.REFUSED and row["reason_code"] == "requalification_goal_changed"
    assert "goal_migration" not in row["document"]
    with chain.world.control.transaction() as tx:
        assert tx.scan("continuation_requalifications") == []
    assert chain.world.intents()[second["id"]]["state"] in dc.REQUALIFICATION_REQUALIFIABLE


def test_an_unobservable_github_keeps_the_row_and_the_target_busy_until_it_can_be_observed(tmp_path):
    """T1-7: unknown is not stale; nothing is withdrawn or released, then the same row proceeds."""
    chain, _, plan2, _ = stale(tmp_path)
    chain.github.observe_error = OSError("GitHub unavailable (labelled)")
    before = deepcopy(chain.world.lane.store.data)
    results = [chain.owner.tick("owners-002") for _ in range(3)]
    row = requalified(chain)
    assert row["state"] == do.WITHDRAWING and "withdraw_unobservable" in results[-1]["waits"].values()
    assert chain.world.lane.store.data == before and chain.hd(plan2["plan_id"])["stage"] == BLOCKED
    chain.github.observe_error = None
    chain.owners()
    assert requalified(chain)["state"] == do.COMPLETED


def second_blocked_family(chain):
    """LABELLED: another completed plan of owners-002 whose delivery the controller blocked as stale,
    for ANOTHER delivery intent of the SAME b2 family (e.g. a second candidate of it)."""
    [plan] = [r for r in chain.actions(do.DELIVERY_PLAN) if r["policy_id"] == "owners-002"]
    twin_intent = {**chain.world.intents()[plan["subject"]["intent_id"]], "id": "7" * 64,
                   "state": dc.AWAITING_OWNER}
    twin = {**plan, "id": "8" * 64, "plan_id": "own-twin", "plan_sha256": "9" * 64,
            "subject": {"intent_id": twin_intent["id"], "lane": "a"}}
    with chain.world.control.transaction() as tx:
        tx.put(BUCKET_INTENTS, twin_intent["id"], twin_intent)
        tx.put(BUCKET_ACTIONS, twin["id"], twin)
    with chain.world.lane.store.transaction() as tx:
        tx.put(HD_INTENTS, "own-twin", {"id": "own-twin", "plan_id": "own-twin", "plan_sha256": "9" * 64,
                                        "target_id": TARGET, "stage": BLOCKED, "reason_code": "reviewed_base_moved"})
    return twin


def test_max_per_family_one_allows_the_first_requalification_and_refuses_the_next(tmp_path):
    """T1-8 and the adjudicated cap clarification: the first is allowed (no self count), the next exhausts."""
    chain, second, _, _ = stale(tmp_path)
    twin = second_blocked_family(chain)
    chain.owner.tick("owners-002")
    rows = {r["binding"]["plan_id"]: r for r in chain.actions(do.DELIVERY_REQUALIFY)}
    slotted = [r for r in rows.values() if r.get("cap_slot") == 1]
    exhausted = [r for r in rows.values() if r["reason_code"] == "requalification_exhausted"]
    assert len(rows) == 2 and len(slotted) == 1 and len(exhausted) == 1
    assert exhausted[0]["state"] == do.REFUSED and exhausted[0]["slots_taken"] == 1
    # The independent family (i1) is unaffected by b2's exhausted cap.
    assert all(r["binding"]["family"] == second["family"] for r in rows.values())
    assert twin["plan_id"] in rows


def test_two_owner_processes_racing_the_cap_never_overshoot_it(tmp_path):
    """Control matrix, concurrency axis: two coordinators over the same store, interleaved at the slot."""
    chain, _, _, _ = stale(tmp_path)
    second_blocked_family(chain)
    first, other = chain.build_owner(), chain.build_owner()
    policy_row = chain.world.control.data["owner_action_policies", "owners-002"]
    continuation = chain.world.controller.policy("policy-1")
    first._discover(policy_row, continuation, {})             # both owed actions exist, nothing advanced
    rows = sorted(chain.actions(do.DELIVERY_REQUALIFY), key=lambda r: r["id"])
    assert len(rows) == 2 and all(r["state"] == do.INTENDED for r in rows)
    # Both read their row at version 1, then each takes its slot in its own transaction.
    first._take_slot(policy_row, continuation, rows[0])
    other._take_slot(policy_row, continuation, rows[1])
    after = chain.actions(do.DELIVERY_REQUALIFY)
    assert sorted(r.get("cap_slot") or 0 for r in after) == [0, 1]
    assert sorted(r["reason_code"] for r in after if r.get("cap_slot") is None) == ["requalification_exhausted"]
    # Whichever won the slot is the only one that may reach the owner API (the labelled twin's plan is not
    # registered with HostDelivery, so if it won, its withdrawal is refused by name instead).
    assert len(chain.requalify_calls) <= 1


def test_the_same_blocked_plan_is_one_action_for_restarts_and_second_coordinators_and_never_another_policys(
        tmp_path):
    """The action id binds the plan, intent and family, never the owner policy id; discovery reads only the
    policy's OWN completed plans, so the other policy of the same process never acts on it."""
    chain, _, plan2, _ = stale(tmp_path)
    policy_row = chain.world.control.data["owner_action_policies", "owners-002"]
    continuation = chain.world.controller.policy("policy-1")
    for owner in (chain.owner, chain.build_owner(), chain.build_owner()):
        owner._discover(policy_row, continuation, {})
    other = chain.world.control.data["owner_action_policies", "owners-i1"]
    assert chain.owner._discover(other, chain.world.controller.policy("policy-i1"), {}) == []
    [row] = chain.actions(do.DELIVERY_REQUALIFY)
    assert row["id"] == do.action_id(do.DELIVERY_REQUALIFY, do.requalify_binding(
        plan2, chain.world.intents()[plan2["subject"]["intent_id"]], chain.hd(plan2["plan_id"])))
    chain.owners()
    chain.owners(chain.build_owner())
    assert len(chain.actions(do.DELIVERY_REQUALIFY)) == 1 and len(chain.requalify_calls) == 1


def test_a_plan_blocked_for_another_reason_or_a_touched_host_is_never_requalified(tmp_path):
    chain, _, plan2, _ = stale(tmp_path)
    with chain.world.lane.store.transaction() as tx:
        row = tx.get(HD_INTENTS, plan2["plan_id"])
        tx.put(HD_INTENTS, row["id"], {**row, "reason_code": "descriptor_predecessor_moved"})
    chain.owners()
    assert chain.actions(do.DELIVERY_REQUALIFY) == []
    with chain.world.lane.store.transaction() as tx:     # LABELLED: blocked stale, but the host was touched
        tx.put(HD_INTENTS, row["id"], {**row, "descriptor": {"schema": "fixture"}})
    chain.owners()
    refused = requalified(chain)
    assert refused["state"] == do.REFUSED and refused["reason_code"] == "withdraw_host_touched"
    assert chain.requalify_calls == []


# ===== T1-2 / T1-3: one delivery authority =====================================================================
def test_a_plan_whose_lane_store_has_no_target_row_is_a_named_wait(tmp_path):
    """T1-3: the same target named from a lane whose store never registered it: nothing is published."""
    chain = Chain(tmp_path, research=False)
    other = HostDelivery(chain.world.lane.store.__class__(), chain.org)
    owner = chain.build_owner(deliveries=lambda lane: other)
    intent = accepted(chain, "op-i1", "docs/b.md", "policy-i1")
    result = owner.tick("owners-i1")
    assert result["waits"].get(intent["id"]) in {"target_unregistered", "release_missing"}
    assert chain.actions(do.DELIVERY_PLAN) == [] and chain.github.publishes == 0


def test_two_targets_of_one_repository_main_are_each_bound_to_their_reviewed_base(tmp_path):
    """T1-2: another target id does not escape the base check; `_publish` refuses the stale candidate."""
    from test_host_delivery import SerialStore, candidate, pin, plan_document, reviewed_release

    store, org, github = SerialStore(), organization(), FakeGitHub(fast_forward=True)
    delivery = HostDelivery(store, org, github=github, clock=Clock(), enabled=True, resume_seconds=0)
    registry = targets_document(tmp_path, target_id="t-one")
    registry["targets"] += targets_document(tmp_path / "two", target_id="t-two")["targets"]
    delivery.register_targets(registry)
    first = plan_document(reviewed_release(store, org), plan_id="p-one", target_id="t-one")
    delivery.register(first, pin(path="docs/zeus/operations/p-one.json"))
    for _ in range(6):
        if delivery.tick("p-one")["stage"] == MERGED:
            break
    assert github.main == first["revision"]
    stale_candidate = {**candidate(), "revision": "5" * 40, "branch": "harness/two", "task_id": "two"}
    second = plan_document(reviewed_release(store, org, record_candidate=stale_candidate), plan_id="p-two",
                           target_id="t-two")
    delivery.register(second, pin(path="docs/zeus/operations/p-two.json"))
    blocked = [delivery.tick("p-two") for _ in range(2)][-1]
    assert blocked["reason_code"] == "reviewed_base_moved" and github.publishes == 1 and github.merges == 1


# ===== policy v2 schema ================================================================================
def test_version1_keeps_its_exact_canonical_form_and_version2_blocks_are_strict():
    v1 = owner_policy("owners-1", "policy-1", schema=do.POLICY_SCHEMA)
    canonical = do.validate_policy(v1)
    assert set(canonical) == do.POLICY_FIELDS and canonical["schema"] == do.POLICY_SCHEMA
    assert do.requalification_policy(canonical) is None and do.research_policy(canonical) is None
    v2 = owner_policy("owners-2", "policy-1", research={"enabled": True, "program_id": PROGRAM, "lane": "a"})
    valid = do.validate_policy(v2)
    assert valid["requalification"] == {"enabled": True, "reasons": ["reviewed_base_moved"], "max_per_family": 1}
    assert do.research_policy(valid) == {"enabled": True, "program_id": PROGRAM, "lane": "a"}
    bad = [{"requalification": {"enabled": True, "reasons": ["merged_tree_mismatch"], "max_per_family": 1}},
           {"requalification": {"enabled": True, "reasons": ["descriptor_predecessor_moved"], "max_per_family": 1}},
           {"requalification": {"enabled": True, "reasons": [], "max_per_family": 1}},
           {"requalification": {"enabled": True, "reasons": ["reviewed_base_moved"], "max_per_family": 0}},
           {"requalification": {"enabled": True, "reasons": ["reviewed_base_moved"], "max_per_family": 4}},
           {"requalification": {"enabled": 1, "reasons": ["reviewed_base_moved"], "max_per_family": 1}},
           {"requalification": {"enabled": True, "reasons": ["reviewed_base_moved"], "max_per_family": 1,
                                "goal_migration": True}},
           {"research": {"enabled": True, "program_id": "../x", "lane": "a"}},
           {"research": {"enabled": True, "program_id": PROGRAM}}]
    for change in bad:
        with pytest.raises(do.OwnerActionRefused, match="policy_invalid"):
            do.validate_policy({**v2, **change})
    with pytest.raises(do.OwnerActionRefused, match="policy_invalid"):
        do.validate_policy({**v1, "research": None})           # v1 never carries a v2 block
    disabled = do.validate_policy({**v2, "requalification": {**v2["requalification"], "enabled": False}})
    assert do.requalification_policy(disabled) is None


# ===== T3: the research dispatch (fixtures) ============================================================
def held_chain(tmp_path, **research):
    chain = Chain(tmp_path)
    chain.research = InProcessResearch(chain.env, **research)
    chain.owner = chain.build_owner()
    root, successor, intent = two_strikes(chain.world, "op-b2", "docs/a.md")
    attempts, investigation = released(chain, intent)
    return chain, intent, attempts, investigation


def program_row(chain):
    with chain.world.control.transaction() as tx:
        return tx.get(BUCKET_PROGRAMS, PROGRAM)


def test_the_provider_unavailable_refuses_before_any_resume_reservation_or_spawn(tmp_path):
    """T3-5."""
    chain, intent, _, _ = held_chain(tmp_path, ok=False)
    before = program_row(chain)
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    assert row["state"] == do.REFUSED and row["reason_code"] == "research_provider_unavailable"
    assert program_row(chain) == before and before["state"] == "paused" and chain.research.starts == []
    with chain.world.control.transaction() as tx:
        assert tx.scan(BUCKET_CYCLES) == []
    for _ in range(3):
        chain.owner.tick("owners-002")
    assert len(chain.actions(do.RESEARCH_DISPATCH)) == 1 and chain.research.probes == 1, "no spin"


def test_a_collection_only_cycle_is_a_named_outcome_and_never_a_second_tick(tmp_path):
    """T3-6: the child's own cycle collected and selected nothing (LABELLED complete_cycle shape)."""
    chain, _, _, _ = held_chain(tmp_path, hold=True)
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    launch = row["launch_id"]
    programs = chain.env.programs
    programs.token = lambda: launch
    reserved = programs.reserve_cycle(PROGRAM, chain.env.identity)["cycle"]
    with chain.world.control.transaction() as tx:     # LABELLED: what complete_cycle leaves for no selection
        cycle = tx.get(BUCKET_CYCLES, reserved["id"])
        program = tx.get(BUCKET_PROGRAMS, PROGRAM)
        tx.put(BUCKET_CYCLES, cycle["id"], {**cycle, "status": CYCLE_DONE,
                                            "selection": {"candidate": None, "reason": "no_eligible_candidate"}})
        tx.put(BUCKET_PROGRAMS, PROGRAM, {**program, "active_cycle": None, "cycles": 1})
    chain.research.launches[launch] = "exited"
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    assert row["state"] == do.REFUSED and row["reason_code"] == "research_cycle_empty"
    for _ in range(3):
        chain.owner.tick("owners-002")
    assert len(chain.actions(do.RESEARCH_DISPATCH)) == 1 and chain.research.starts == [launch]


def test_a_cycle_reserved_under_that_number_by_another_owner_is_foreign_never_ours(tmp_path):
    """T3-7: exact cycle-owner evidence, not the number alone."""
    chain, _, _, _ = held_chain(tmp_path, foreign=True)
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    assert row["state"] == do.UNKNOWN and row["reason_code"] == "research_cycle_foreign"
    assert len(chain.research.starts) == 1


def test_a_launch_that_never_entered_is_relaunched_once_and_then_unknown(tmp_path):
    chain, _, _, _ = held_chain(tmp_path, hold=True)
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    del chain.research.launches[row["launch_id"]]           # LABELLED: fenced, never entered
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    assert row["state"] == do.RUNNING and row["launches"] == 2 and len(chain.research.starts) == 2
    del chain.research.launches[row["launch_id"]]
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    assert row["state"] == do.UNKNOWN and row["reason_code"] == "research_launch_unknown"
    assert len(chain.research.starts) == 2


def test_an_owned_crashed_cycle_keeps_the_program_busy_and_is_never_relaunched(tmp_path):
    """T3-4 (fixture half): the child reserved our cycle and died; its guardian proved cleanup."""
    chain, _, _, _ = held_chain(tmp_path, hold=True)
    chain.owner.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    chain.env.programs.token = lambda: row["launch_id"]
    chain.env.programs.reserve_cycle(PROGRAM, chain.env.identity)     # LABELLED: reserved, then crashed
    chain.research.launches[row["launch_id"]] = "exited"
    restarted = chain.build_owner()
    restarted.tick("owners-002")
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    assert row["state"] == do.UNKNOWN and row["reason_code"] == "research_cycle_unfinished"
    assert program_row(chain)["active_cycle"] is not None, "the debt stays owned"
    assert len(chain.research.starts) == 1


def test_other_policies_advance_while_the_research_child_is_pending(tmp_path):
    """T3-1 (fixture half): the child stays running across ticks; i1's plan is published and registered."""
    chain, _, _, _ = held_chain(tmp_path, hold=True)
    i1 = accepted(chain, "op-i1", "docs/b.md", "policy-i1")
    states = []
    for _ in range(3):
        chain.owners()
        states.append(chain.plan_action(i1["id"])["state"])
    assert states == [do.PUBLISHING, do.COMPLETED, do.COMPLETED] or states[-1] == do.COMPLETED, states
    [dispatch] = chain.actions(do.RESEARCH_DISPATCH)
    assert dispatch["state"] == do.RUNNING and len(chain.research.starts) == 1


# ===== T3-8: the ported RO-1 decision table ============================================================
def decision_rows(chain):
    with chain.world.control.transaction() as tx:
        return {name: tx.scan(name) for name in (
            "research_programs", "research_investigation_dispatches", "research_dispatch_recoveries",
            "research_dispatch_heads", "portfolio_investigations", "fleet_jobs", "portfolio_bindings")}


@pytest.mark.parametrize("case, reason, act", [
    ("exact", "research_ready_resume_then_tick", True),
    ("active", "research_ready_tick", True),
    ("mixed", "research_scope_mixed", False),
    ("competing", "research_competing_program", False),
    ("headroom", "research_headroom_insufficient", False),
    ("unreadable", "research_headroom_unreadable", False),
    ("claimed", "research_dispatch_claimed", False),
    ("busy", "research_program_busy", False),
    ("paused_by_owner", "research_program_paused_by_owner", False),
    ("completed", "research_program_completed", False),
    ("unregistered", "research_program_unregistered", False),
])
def test_the_ported_ro1_decision_table(tmp_path, case, reason, act):
    chain, intent, attempts, investigation = held_chain(tmp_path)
    rows = decision_rows(chain)
    room = {"ok": True, "remaining": 5}
    program = next(r for r in rows["research_programs"] if r["id"] == PROGRAM)
    if case == "active":
        program["state"] = "active"
    elif case == "mixed":
        attempts = attempts[:1]
    elif case == "competing":
        rows["research_programs"].append({**program, "id": "rp-rival", "state": "active"})
    elif case == "headroom":
        room = {"ok": False, "remaining": 0}
    elif case == "unreadable":
        room = None
    elif case == "claimed":
        rows["research_investigation_dispatches"].append({"investigation": investigation, "program": "rp-rival"})
    elif case == "busy":
        program["active_cycle"] = "rp-b2:1"
    elif case == "paused_by_owner":
        program["cycles"] = 1
    elif case == "completed":
        program["state"] = "completed"
    elif case == "unregistered":
        rows["research_programs"] = []
    decision = do.research_decision(program_id=PROGRAM, investigation=investigation, attempts=attempts, rows=rows,
                                    room=room, now="2026-09-26T00:00:00+00:00")
    assert (decision["act"], decision["reason"]) == (act, reason)


def test_discovery_is_idempotent_across_restarts_and_a_second_coordinator(tmp_path):
    chain, _, _, _ = held_chain(tmp_path, hold=True)
    chain.owner.tick("owners-002")
    chain.build_owner().tick("owners-002")
    chain.build_owner().tick("owners-002")
    assert len(chain.actions(do.RESEARCH_DISPATCH)) == 1 and len(chain.research.starts) == 1


def test_the_happy_path_fixture_chain_accepts_the_research_through_the_existing_receipt(tmp_path):
    """T3-9 - LABELLED happy-path fixture only: research_required -> research_dispatch -> (child records the
    dispatch) -> research_receipt -> accept_research. It does not establish process liveness."""
    chain, intent, _, _ = held_chain(tmp_path)
    for _ in range(4):
        chain.owner.tick("owners-002")
    [dispatch] = chain.actions(do.RESEARCH_DISPATCH)
    [receipt] = chain.actions(do.RESEARCH_RECEIPT)
    assert dispatch["state"] == do.COMPLETED and receipt["state"] == do.COMPLETED
    assert receipt["binding"]["dispatch"]["program"] == PROGRAM
    chain.continuation()
    assert chain.world.intents()[intent["id"]]["state"] == dc.COMPLETED
    assert REPORT and chain.assessor.starts


# ===== the cap across concurrent PostgreSQL writers (control matrix, concurrency axis) =====================
class HoldingStore:
    """LABELLED wrapper of a real store: the first owner-action write of the ARMED holder signals and keeps
    its transaction (and so the advisory lock) open until released."""

    def __init__(self, store):
        import threading
        self.store, self.inside, self.release, self.armed = store, threading.Event(), threading.Event(), True

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def held():
            with self.store.transaction() as tx:
                yield HoldingTransaction(tx, self)
        return held()


class HoldingTransaction:
    def __init__(self, tx, owner):
        self.tx, self.owner = tx, owner

    def __getattr__(self, name):
        return getattr(self.tx, name)

    def put(self, bucket, key, body):
        if bucket == BUCKET_ACTIONS and body.get("cap_slot") is not None and self.owner.armed:
            self.owner.armed = False
            self.owner.inside.set()
            assert self.owner.release.wait(20)
        self.tx.put(bucket, key, body)


@pytest.mark.integration
def test_the_family_cap_holds_across_concurrent_postgresql_owner_processes(isolated_pgstore):
    """Two coordinators take a slot for two blocked plans of ONE family at the same time: the second blocks
    on the first's open transaction, then counts its committed slot and is refused `requalification_exhausted`."""
    import threading

    lane = {"plan-a": "1" * 64, "plan-b": "2" * 64}
    rows = {}
    for plan_id, sha in lane.items():
        binding = {"plan_id": plan_id, "plan_sha256": sha, "intent_id": plan_id + "-intent",
                   "continuation_policy": "policy-1", "family": "fam-1", "release_id": "rel-" + plan_id,
                   "origin_job": "job-" + plan_id, "reason": "reviewed_base_moved"}
        policy_row = {"id": "owners-002", "policy_sha256": "3" * 64}
        rows[plan_id] = do.new_action(do.DELIVERY_REQUALIFY, binding, policy_row,
                                      {"intent_id": binding["intent_id"], "lane": "a"}, "2026-09-26T00:00:00+00:00")
    with isolated_pgstore.transaction() as tx:
        for row in rows.values():
            tx.put(BUCKET_ACTIONS, row["id"], row)

    class Lane:
        """LABELLED lane store view: both plans are blocked as stale; withdrawal is never reached here."""

        class store:
            @staticmethod
            def transaction():
                from contextlib import contextmanager

                @contextmanager
                def tx():
                    yield type("T", (), {"get": staticmethod(lambda bucket, key: {
                        "plan_id": key, "plan_sha256": lane[key], "stage": BLOCKED,
                        "reason_code": "reviewed_base_moved"})})()
                return tx()

    class Artifacts:
        @staticmethod
        def put(text, kind):
            return {"ref": "sha256:" + digest(text)}

    def owner(store):
        def withdrawals(lane_id):
            raise RuntimeError("stop after the slot (labelled): the withdrawal is not under test here")
        return OwnerActions(store, deliveries=lambda lane_id: Lane, withdrawals=withdrawals, mainline=object(),
                            requalify=object(), artifacts=Artifacts)

    policy = {"id": "owners-002", "policy": do.validate_policy(owner_policy("owners-002", "policy-1"))}
    continuation = {"id": "policy-1"}
    holding = HoldingStore(isolated_pgstore)
    first, second = owner(holding), owner(isolated_pgstore)
    errors = []

    def take(coordinator, row):
        try:
            coordinator._take_slot(policy, continuation, row)
        except RuntimeError:
            pass
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    thread = threading.Thread(target=take, args=(first, rows["plan-a"]))
    thread.start()
    assert holding.inside.wait(20), "the first slot transaction never opened"
    other = threading.Thread(target=take, args=(second, rows["plan-b"]))
    other.start()
    threading.Timer(0.5, holding.release.set).start()
    thread.join(30)
    other.join(30)
    assert errors == []
    with isolated_pgstore.transaction() as tx:
        after = {row["binding"]["plan_id"]: row for row in tx.scan(BUCKET_ACTIONS)}
    assert after["plan-a"]["cap_slot"] == 1 and after["plan-a"]["state"] == do.WITHDRAWING
    assert after["plan-b"]["state"] == do.REFUSED and after["plan-b"]["reason_code"] == "requalification_exhausted"
