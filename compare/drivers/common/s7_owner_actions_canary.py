"""Shared S7 scenario steps (`coordination.owner_actions_canary`): the owner canary family of M7 `OwnerActions`
(`application/owner_actions.py`): `_canary_binding`, `_advance_canary`, `_canary_still_bound`, `recover_canary` for both kinds
(`CANARY_RECOVERY_KIND`, `CANARY_REARM_KIND`) with its `_recovery_*` checks, and the M7 `domain.owner_actions` names they call
(`canary_binding`, `canary_job_id`, `canary_manifest`, `canary_outcome`, `canary_receipt`, `linked_restart`,
`restart_owed_canary`, `rearm_owed_canary`, `validate_canary_recovery`), over the REAL M7 `HostDelivery` of a lane store
(DESIGN-s7 §2 row `coordination.owner_actions_delivery`, the 11:50Z split: `owner_actions_canary`; §3 step 4; the S6 carry of
DESIGN-s6 §14).

Groups (each labelled in the result; the M7 test each case mirrors is named at its function):

1. **advance** (`_advance_canary`, which M7 exercises only end-to-end): when the binding is owed (a REAL lane delivery
   awaiting consumption, with LABELLED variations of its rows), INTENDED -> REQUESTED once on the policy's canary lane,
   `canary_ports_unconfigured`, a lost admission response, the plan/delivery/descriptor/instance moving, every outcome
   (running/absent, unknown, accepted, rejected) and a tick after each terminal state.
2. **recovery** (`tests/test_owner_actions_canary_recovery.py`, memory store only): from
   `test_the_document_grammar_is_exact` to `test_a_concurrent_move_between_preflight_and_write_is_refused`, and
   `test_a_retry_observing_another_instance_without_a_linked_restart_is_refused`; the lane rows are the LABELLED shapes of that
   module's `world()` (`lab_*` cases) or produced by the REAL lane HostDelivery (`chain_*` cases: `resume_consumption_retry`
   over the `s7_owner_commands` doubles).
3. **re-arm** (`tests/test_owner_actions_canary_rearm.py`): `test_the_rearm_document_grammar_is_exact` and the store-level
   core of its end-to-end test (the SAME halted canary recovered once more by the re-arm kind, paired only with the lane's ONE
   `first_activation_consumption_rearm` and its window), a second re-arm, an over-long window and a re-arm without the
   lane's.
4. **scheduler**: `OwnerActions.tick` discovering the owed canary after its plan completes and advancing it next to an idle
   research family, and `status` projecting it.

Layer: harness (never shipped). This module never imports `codex_harness`: everything from the product arrives through
`api`, the object a reference (later a target) driver builds: the `s7_owner_actions_delivery` API and the
`delivery.owner_commands` names, plus `advance_canary(owner, policy_row, continuation, action)`,
`canary_binding_of(owner, plan_action)` and `canary_still_bound(owner, plan_action, action)` (the M7 private
`_advance_canary`, `_canary_binding` and `_canary_still_bound`, at their split homes on the target).

**Doubles** (each docstring names its source; none runs Git, a process, a host, GitHub or a model): `Fleet` (the Fleet
`enqueue` port and its job rows, M7 `tests/test_owner_actions_canary_recovery.py::Fleet` and `world()`'s job/admission
rows), `Lanes` (`lanes(lane).read(job)`, M7 `LaneRun`), `Files` (`TargetFiles`: `startup`, `receipt`, `write_receipt`, M7
`Files`), `Clock` (M7 `Clock`), `Delivery` (M7 `Delivery`) and, over the REAL lane, `Targets` (the `s7_owner_actions_delivery`
double with `startup`/`receipt`/`write_receipt` answering from the lane's memory host and owner canary). The rows written by
hand are LABELLED fixtures of M7: the control rows of `world()` and the lane rows the LABELLED variations change.

The compared results are the calls' outcomes, the rows they wrote, what each double saw and the digests of both stores. The
PostgreSQL parameter, the real-process end-to-end tests, the CLI test and the file-adapter test are out of scope.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import s6_tick as T
import s7_delivery as D
import s7_owner_actions_delivery as OD
import s7_owner_commands as OC
import s7_stages as S

TARGET = "aibox-canary"
PLAN_ID = "plan-1"
PLAN_SHA = "1" * 64
DESCRIPTOR = "2" * 64
INSTANCE = "inst-1"
RELEASE = "release-1"
LANE_RETRY = "sha256:" + "e" * 64
LANE_REARM = "sha256:" + "d" * 64
T0 = datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)
ACTIONS, POLICIES, JOBS, FLEET_CONTROL = "owner_actions", "owner_action_policies", "fleet_jobs", "fleet_control"
LANE_INTENTS, LANE_TARGETS, LANE_RELEASES = "host_delivery_intents", "host_delivery_targets", "releases"
UNREACHABLE = {}


def call(fn, *args, **kwargs):
    return D.call(fn, *args, **kwargs)


def rows(store, bucket):
    with store.transaction() as tx:
        return {row["id"]: row for row in tx.scan(bucket)}


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


# ---- labelled doubles ---------------------------------------------------------------------------------------
class Clock:
    """LABELLED. M7 `tests/test_owner_actions_canary_recovery.py::Clock`: a fixed clock in ISO strings, advanced only by
    the case."""

    def __init__(self, at=T0):
        self.at = at

    def __call__(self):
        return self.at.isoformat()


class Files:
    """LABELLED. M7 `Files` (the target-file port `TargetFiles` fills): the candidate's startup receipt and the plan's owner
    canary receipt. `on_receipt`, when set, runs once inside the first `receipt` read (the last read `_recovery_lane` makes,
    after the lane read and before the compare-and-swap transaction): the labelled seam of the concurrent-move case."""

    def __init__(self, instance=INSTANCE, descriptor=DESCRIPTOR):
        self.startup_receipt = {"instance_id": instance, "descriptor_sha256": descriptor}
        self.receipts, self.on_receipt, self.written, self.source = {}, None, [], None

    def startup(self, target):
        if self.source is not None:
            return copy.deepcopy(self.source(target))
        return copy.deepcopy(self.startup_receipt)

    def receipt(self, target, plan_id):
        action, self.on_receipt = self.on_receipt, None
        if action is not None:
            action()
        return copy.deepcopy(self.receipts.get(plan_id))

    def write_receipt(self, target, plan_id, document):
        self.written.append(plan_id)
        self.receipts[plan_id] = copy.deepcopy(document)


class Lanes:
    """LABELLED. M7 `LaneRun` behind `lanes(lane_id)`: `read(job)` answers the finished operation and its independent lead
    review of the M7 test (`answer` replaces it; `error` raises); every read is recorded by lane and job."""

    def __init__(self):
        self.reads, self.answer, self.error = [], None, None

    def __call__(self, lane_id):
        self.reads.append(("lane", lane_id))
        return self

    def read(self, job):
        self.reads.append(("read", job["id"], job.get("status")))
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return copy.deepcopy(self.answer)
        return {"operation": {"status": "accepted"}, "markers": [],
                "lead": {"id": "decision-1", "phase": "review_lead", "status": "succeeded",
                         "result": {"accepted": True, "execution_ref": "sha256:" + "c" * 64}}}


def job_row(lane, manifest, goal, dependencies, at):
    """The Fleet job row in the exact shape of M7 `world()` (a queued job admitted under a paused Fleet)."""
    return {"id": manifest["id"], "operation_id": manifest["id"], "lane": lane, "team": "improvement", "repository": "r",
            "status": "queued", "reason_code": "paused", "manifest": copy.deepcopy(manifest),
            "manifest_sha256": D.canonical_digest(manifest), "goal": copy.deepcopy(goal),
            "dependencies": list(dependencies), "owner_token": None, "exit_code": None,
            "calls": {"reserved": None, "settled": None}, "receipt": None, "error_type": None, "created_at": at,
            "updated_at": at, "dispatched_at": None, "finished_at": None}


class Fleet:
    """LABELLED. The Fleet `enqueue` port (M7 `Fleet`): every admission is recorded (lane, manifest, goal, dependencies);
    with a `store` it also writes the queued job row of `world()` (`job_row`) and a paused admission row, as the real Fleet's
    admission does. `lose` raises `RuntimeError` AFTER recording and BEFORE any row (a lost admission response: the
    REQUESTED action then has no job row); `error` raises before recording."""

    def __init__(self, store=None, clock=None):
        self.store, self.clock, self.calls, self.lose, self.error = store, clock or Clock(), [], 0, None

    def enqueue(self, lane, manifest, goal, dependencies):
        if self.error is not None:
            raise self.error
        self.calls.append({"lane": lane, "manifest": copy.deepcopy(manifest), "goal": copy.deepcopy(goal),
                           "dependencies": list(dependencies)})
        if self.lose:
            self.lose -= 1
            raise RuntimeError("admission response lost (labelled injected fault)")
        if self.store is not None:
            with self.store.transaction() as tx:
                if tx.get(JOBS, manifest["id"]) is None:
                    tx.put(JOBS, manifest["id"], job_row(lane, manifest, goal, dependencies, self.clock()))
                if tx.get(FLEET_CONTROL, "admission") is None:
                    tx.put(FLEET_CONTROL, "admission", {"paused": True, "updated_at": self.clock()})
        return {"job": {"id": manifest["id"]}, "cached": True}


class Delivery:
    """LABELLED. M7 `Delivery`: the lane `deliveries(lane)` port of which only the store is read."""

    def __init__(self, store):
        self.store = store


# ---- the LABELLED M7 world() ---------------------------------------------------------------------------------
class Lab:
    """LABELLED. M7 `tests/test_owner_actions_canary_recovery.py::world()`: two SEPARATE memory stores; one halted canary
    (REQUESTED -> UNKNOWN `canary_delivery_moved`) whose job is queued under a paused Fleet, and the lane after its consumption
    retry of the SAME instance. The rows are written by hand in the shapes the real owners write them (as M7 writes them).

    With a `chain` (`Chain`, the REAL lane after its owner commands) the control rows are the same LABELLED shapes but name the
    real plan, target, descriptor, instance and release of that lane, whose store is READ as the lane; the owner's clock is the
    lane's timeline and its `startup` answers the lane host's own receipt."""

    def __init__(self, api, *, author="worker:improvement-1", chain=None):
        self.api, self.chain = api, chain
        do = self.do = api.owner_domain
        ids = chain.ids if chain else {"plan_id": PLAN_ID, "plan_sha": PLAN_SHA, "target": TARGET,
                                       "descriptor": DESCRIPTOR, "instance": INSTANCE, "release": RELEASE,
                                       "retry": LANE_RETRY}
        self.ids = ids
        self.clock = chain.clock if chain else Clock()
        self.control = api.MemoryStore()
        self.lane = chain.store if chain else api.MemoryStore()
        binding = {"plan_id": ids["plan_id"], "plan_sha256": ids["plan_sha"], "target_id": ids["target"],
                   "descriptor_sha256": ids["descriptor"], "instance_id": ids["instance"]}
        policy = {"enabled": True, "canary": {"lane": "a", "manifest": {"id": "template"}, "goal": {}}}
        self.policy_row = {"id": "owners-1", "policy": policy, "policy_sha256": "3" * 64, "pin": {"sha256": "4" * 64},
                           "registered_at": "2026-09-27T04:00:00+00:00"}
        identity = do.action_id(do.DELIVERY_CANARY, binding)
        job_id = do.canary_job_id(identity)
        history = [{"state": do.INTENDED, "at": "2026-09-27T03:00:00+00:00", "reason_code": None},
                   {"state": do.REQUESTED, "at": "2026-09-27T03:01:00+00:00", "reason_code": "canary_requested"},
                   {"state": do.UNKNOWN, "at": "2026-09-27T03:20:00+00:00", "reason_code": "canary_delivery_moved"}]
        self.action = {"id": identity, "kind": do.DELIVERY_CANARY, "state": do.UNKNOWN, "binding": binding,
                       "binding_sha256": api.digest(binding), "policy_id": "owners-1", "policy_sha256": "3" * 64,
                       "subject": {"intent_id": "s" * 64, "lane": "a"}, "reason_code": "canary_delivery_moved",
                       "created_at": "2026-09-27T03:00:00+00:00", "updated_at": "2026-09-27T03:20:00+00:00", "version": 3,
                       "history": history, "job_id": job_id}
        self.plan_action = {"id": "p" * 64, "kind": do.DELIVERY_PLAN, "state": do.COMPLETED, "plan_id": ids["plan_id"],
                            "plan_sha256": ids["plan_sha"], "plan": {"plan_id": ids["plan_id"],
                                                                     "target_id": ids["target"],
                                                                     "release_id": ids["release"]},
                            "subject": {"intent_id": "s" * 64, "lane": "a"}, "policy_id": "owners-1",
                            "created_at": "2026-09-27T02:00:00+00:00", "version": 4, "history": []}
        self.job = {"id": job_id, "operation_id": job_id, "lane": "a", "team": "improvement", "repository": "r",
                    "status": "queued", "reason_code": "paused", "manifest": {"id": job_id}, "manifest_sha256": "5" * 64,
                    "goal": {}, "dependencies": [], "owner_token": None, "exit_code": None,
                    "calls": {"reserved": None, "settled": None}, "receipt": None, "error_type": None,
                    "created_at": "2026-09-27T03:01:00+00:00", "updated_at": "2026-09-27T03:01:00+00:00",
                    "dispatched_at": None, "finished_at": None}
        put(self.control, POLICIES, self.policy_row["id"], self.policy_row)
        put(self.control, ACTIONS, self.plan_action["id"], self.plan_action)
        put(self.control, ACTIONS, identity, self.action)
        put(self.control, JOBS, job_id, self.job)
        put(self.control, FLEET_CONTROL, "admission", {"paused": True, "updated_at": "2026-09-27T03:00:00+00:00"})
        if chain is None:
            intent = {"plan_id": PLAN_ID, "plan_sha256": PLAN_SHA, "target_id": TARGET, "stage": api.AWAITING_CONSUMPTION,
                      "previous_stage": "blocked", "descriptor_sha256": DESCRIPTOR,
                      "stage_deadline": (T0 + timedelta(seconds=3600)).isoformat(),
                      "recoveries": [{"kind": api.RECOVERY_FIRST_ACTIVATION, "evidence_ref": "sha256:" + "f" * 64},
                                     {"kind": api.RECOVERY_CONSUMPTION_RETRY, "evidence_ref": LANE_RETRY,
                                      "observed": {"observed_instance_id": INSTANCE, "descriptor_sha256": DESCRIPTOR}}]}
            put(self.lane, LANE_INTENTS, PLAN_ID, intent)
            put(self.lane, LANE_TARGETS, TARGET, {"id": TARGET})
            put(self.lane, LANE_RELEASES, RELEASE, {"id": RELEASE, "candidate": {"author": author}})
        self.files, self.fleet, self.lanes = Files(), Fleet(), Lanes()
        if chain is not None:
            self.files.source = chain.startup
        self.owner = api.OwnerActions(self.control, org=api.organization(), lanes=self.lanes, fleet=self.fleet,
                                      deliveries=lambda lane_id: Delivery(self.lane), targets=self.files,
                                      clock=self.clock)

    # ---- reads and writes ----
    def row(self, bucket=ACTIONS, key=None, store="control"):
        return get(getattr(self, store), bucket, key or self.action["id"])

    def put(self, bucket, key, value, store="control"):
        put(getattr(self, store), bucket, key, value)

    def intent(self):
        return self.row(LANE_INTENTS, self.ids["plan_id"], "lane")

    def set_intent(self, **changes):
        self.put(LANE_INTENTS, self.ids["plan_id"], {**self.intent(), **changes}, "lane")

    def snapshot(self):
        """M7 `snapshot`: both stores, the receipts and the Fleet admissions."""
        return {"control": D.store_digest(self.control), "lane": D.store_digest(self.lane),
                "receipts": D.canonical_digest(self.files.receipts), "fleet": len(self.fleet.calls)}

    def document(self, **overrides):
        """M7 `document(w)`."""
        do, action = self.do, self.action
        body = {"schema": do.CANARY_RECOVERY_SCHEMA, "kind": do.CANARY_RECOVERY_KIND, "action_id": action["id"],
                "action_version": action["version"], "binding_sha256": action["binding_sha256"],
                "binding": dict(action["binding"]), "policy_id": action["policy_id"],
                "policy_sha256": action["policy_sha256"], "job_id": action["job_id"],
                "halt": {"state": action["state"], "reason_code": action["reason_code"],
                         "updated_at": action["updated_at"]},
                "lane_retry_evidence": self.ids["retry"], "margin_seconds": 600, "approved_by": "conductor"}
        body.update(overrides)
        return body, "sha256:" + self.api.digest(body)

    def rearm_document(self, halted=None, **overrides):
        """M7 `test_owner_actions_canary_rearm._recovery`, made a re-arm document over the CURRENT halted action."""
        do, action = self.do, halted or self.row()
        body = {"schema": do.CANARY_RECOVERY_SCHEMA, "kind": do.CANARY_REARM_KIND, "action_id": action["id"],
                "action_version": action["version"], "binding_sha256": action["binding_sha256"],
                "binding": dict(action["binding"]), "policy_id": action["policy_id"],
                "policy_sha256": action["policy_sha256"], "job_id": action["job_id"],
                "halt": {"state": action["state"], "reason_code": action["reason_code"],
                         "updated_at": action["updated_at"]},
                "margin_seconds": 600, "approved_by": "conductor", "lane_rearm_evidence": LANE_REARM,
                "lane_window_seconds": 3600}
        body.update(overrides)
        return body, "sha256:" + self.api.digest(body)

    def attempt(self, body=None, evidence=None, expect=None):
        """One recovery call: its outcome or named refusal and whether it wrote ANYTHING (store, receipts, Fleet)."""
        if body is None:
            body, evidence = self.document()
        before = self.snapshot()
        out = call(self.owner.recover_canary, body, evidence or "sha256:" + self.api.digest(body))
        entry = {"outcome": out, "wrote": self.snapshot() != before}
        if expect is not None:
            entry["expect"] = expect
            entry["as_expected"] = out.get("reason_code") == expect and not entry["wrote"]
        return entry

    def refused(self, expect, body=None, evidence=None):
        """M7 `refused`: the named refusal and NOTHING written in either store, the receipts or the Fleet."""
        return self.attempt(body, evidence, expect)


# ---- the owner over the REAL lane -----------------------------------------------------------------------------
class Targets(OD.Targets):
    """LABELLED. M7 `adapters/owner_actions.TargetFiles` over the REAL lane's memory host and owner canary
    (`s7_delivery.MemoryHost`, `OwnerCanary`): `startup` answers the host's own startup receipt (what
    `consumption_verdict` compares), `receipt` and `write_receipt` the owner's canary receipt the lane's fleet canary reads,
    and `write_request` also files the plan id as a pending request (the lane's canary then waits for the owner's actual
    canary instead of failing as missing). `startup_override`, when set, replaces the startup answer (a labelled variation)."""

    def __init__(self, world):
        super().__init__(world.log)
        self.world, self.startup_override, self.written = world, None, []

    def startup(self, target):
        if self.startup_override is not None:
            return copy.deepcopy(self.startup_override[0])
        return copy.deepcopy(self.world.system["host"].receipt(target))

    def receipt(self, target, plan_id):
        return copy.deepcopy(self.world.system["owner_canary"].receipts.get(plan_id))

    def write_request(self, target, plan_id, document):
        super().write_request(target, plan_id, document)
        self.world.system["owner_canary"].requests.add(plan_id)

    def write_receipt(self, target, plan_id, document):
        self.log.append(("receipt", plan_id))
        self.written.append(plan_id)
        self.world.system["owner_canary"].receipts[plan_id] = copy.deepcopy(document)


class Owned(OD.World):
    """The `s7_owner_actions_delivery` World (one control store, ONE lane store with the REAL lane HostDelivery, the plan the
    owner published and registered) whose owner also holds the canary ports: a `Fleet` writing the job rows into the
    control store, the `Lanes` reader, the trusted organization, the real `validate_manifest` and the lane's timeline as its
    clock (the recovery margin compares the lane's deadline with it). The canary policy's manifest is a LABELLED template
    that passes the real `validate_manifest` (`s6_tick.manifest`)."""

    def __init__(self, api, *, policy_options=None, **options):
        options = {"fleet": True, **options}
        policy = OD.owner_policy(api, **{k: v for k, v in options.items() if k in ("fleet", "v2", "research")},
                                 **(policy_options or {}))
        policy["canary"]["manifest"] = T.manifest(api, "canary-template")
        super().__init__(api, policy=policy, **{k: v for k, v in options.items() if k not in ("research",)})
        self.clock = D.clock(api)
        self.fleet, self.lanes = Fleet(self.control, self.clock), Lanes()
        self.targets = self.ports["targets"] = Targets(self)
        self.owner = self.build_owner()

    def build_owner(self, **overrides):
        if not hasattr(self, "fleet"):    # the base World builds its registering owner before the canary ports exist
            return super().build_owner(**overrides)
        ports = {**self.ports, **self.v2_ports, "org": self.api.organization(), "fleet": self.fleet,
                 "lanes": self.lanes, "validate": self.api.validate_manifest, **overrides}
        return self.api.OwnerActions(self.control, clock=self.clock, **ports)

    def to_awaiting_consumption(self):
        """The plan published and registered by the owner, then the REAL lane driven to `awaiting_consumption`."""
        planned = [OD.receipt_view(r) for r in self.ticks(3)]
        lane = D.drive(self.system, until=self.api.AWAITING_CONSUMPTION, limit=20)
        return {"plan_ticks": planned, "lane_stages": [r["stage"] for r in lane]}

    def plan(self):
        [plan] = OD.plan_actions(self)
        return plan

    def canaries(self):
        return self.actions(self.api.owner_domain.DELIVERY_CANARY)

    def lane_intent(self):
        return self.lane_row(D.BUCKET_INTENTS, self.plan()["plan_id"])

    def set_lane(self, **changes):
        """LABELLED: a lane-store write by someone else (the M7 tests write the same rows by hand)."""
        self.put(self.lane_store, D.BUCKET_INTENTS, self.plan()["plan_id"], {**self.lane_intent(), **changes})

    def stores_and_effects(self):
        return {**self.stores(), "fleet": len(self.fleet.calls), "receipts": len(self.targets.written),
                "reads": len(self.lanes.reads)}


def action_view(action):
    """The fields of an owner canary action that a case compares."""
    keys = ("id", "state", "reason_code", "version", "job_id", "binding", "binding_sha256", "outcome", "recoveries")
    return None if action is None else {k: action.get(k) for k in keys if k in action}


def effects(receipt):
    """A tick's receipt: outcome, created, actions, waits, open."""
    return OD.receipt_view(receipt)


def fresh(api, **options):
    """An `Owned` world whose REAL lane delivery awaits consumption (the plan published, registered and switched)."""
    w = Owned(api, **options)
    w.started = w.to_awaiting_consumption()
    return w


def policy_row_of(w):
    return rows(w.control, POLICIES)[w.policy["id"]]


def intended(w):
    """LABELLED: the INTENDED canary, persisted and not advanced: the same owner without the Fleet port creates it and then
    waits `canary_ports_unconfigured` (the tick discovers before it advances)."""
    return effects(w.tick(owner=w.build_owner(fleet=None)))


# ---- 1. advance -------------------------------------------------------------------------------------------------------
def owed(api):
    """`_canary_binding`: owed only while the delivery of exactly this plan awaits consumption and its candidate instance
    reported the switched descriptor. The rows are the REAL lane's; each variation is a LABELLED write (or port) that is
    undone afterwards."""
    w = fresh(api)
    plan, pid = w.plan(), w.plan()["plan_id"]
    intent = w.lane_intent()
    reporting = w.system["host"].receipt(w.system["target"])

    def binding(owner=None):
        return call(api.canary_binding_of, owner or w.owner, w.plan())

    def vary(name, change, owner=None):
        w.put(w.lane_store, D.BUCKET_INTENTS, pid, change(copy.deepcopy(intent)))
        out[name] = binding(owner)
        w.put(w.lane_store, D.BUCKET_INTENTS, pid, intent)

    out = {"base": binding()}
    out["domain_binding"] = api.owner_domain.canary_binding(plan, intent, reporting["instance_id"])
    out["base_is_domain_binding"] = out["base"].get("value") == out["domain_binding"]
    vary("other_stage", lambda i: {**i, "stage": api.MERGED})
    vary("other_plan_digest", lambda i: {**i, "plan_sha256": "0" * 64})
    vary("no_descriptor", lambda i: {k: v for k, v in i.items() if k != "descriptor"})
    vary("descriptor_not_a_mapping", lambda i: {**i, "descriptor": "labelled"})
    vary("previous_instance_is_the_reporting_one", lambda i: {**i, "previous_instance_id": reporting["instance_id"]})
    vary("other_previous_instance", lambda i: {**i, "previous_instance_id": "0" * 32})
    other = api.MemoryStore()
    put(other, D.BUCKET_INTENTS, pid, intent)
    out["no_target_row"] = binding(w.build_owner(deliveries=lambda lane_id: Delivery(other)))
    for name, receipt in (("no_startup_receipt", None), ("other_revision", {**reporting, "revision": "0" * 40}),
                          ("malformed_receipt", {"schema": "labelled"})):
        w.targets.startup_override = (receipt,)
        out["not_consumed_" + name] = binding()
    w.targets.startup_override = None
    out["deliveries_unconfigured"] = binding(w.build_owner(deliveries=None))
    out["targets_unconfigured"] = binding(w.build_owner(targets=None))
    out["restored"] = binding()
    out["canary_actions_written"] = w.canaries()
    return out


def request_once(api):
    """INTENDED -> REQUESTED (`canary_requested`): the validated manifest is enqueued ONCE on the policy's canary lane;
    `canary_ports_unconfigured` applies without the Fleet or the lanes port."""
    w = fresh(api)
    unconfigured = [intended(w), effects(w.tick(owner=w.build_owner(lanes=None)))]
    [action] = w.canaries()
    direct = {name: call(api.advance_canary, w.build_owner(**{name: None}), policy_row_of(w), {}, action)
              for name in ("fleet", "lanes")}
    before = w.stores_and_effects()
    first = effects(w.tick())
    [requested] = w.canaries()
    job_id = api.owner_domain.canary_job_id(action["id"])
    policy = policy_row_of(w)["policy"]
    expected = api.validate_manifest(api.owner_domain.canary_manifest(policy, job_id))
    rest = [effects(w.tick()) for _ in range(3)]
    settled = w.stores_and_effects()
    idle = [effects(w.tick()), effects(w.tick(owner=w.build_owner()))]
    return {"unconfigured": unconfigured, "intended": action_view(action), "direct_unconfigured": direct,
            "nothing_enqueued_before": before["fleet"] == 0, "first": first, "requested": action_view(requested),
            "enqueued": w.fleet.calls, "enqueued_manifest_is_validated": w.fleet.calls[0]["manifest"] == expected,
            "job": get(w.control, JOBS, job_id), "rest": rest, "enqueued_once": len(w.fleet.calls) == 1,
            "idle": idle, "idle_wrote_nothing": w.stores_and_effects() == settled,
            "requests": sorted(w.targets.requests), "lane_reads": w.lanes.reads, **w.stores()}


def lost_admission(api):
    """REQUESTED with no job row (the admission response was lost after the move): the same job id is enqueued again."""
    w = fresh(api)
    w.fleet.lose = 1
    first = effects(w.tick())
    [after_first] = w.canaries()
    job_id = after_first["job_id"]
    no_row = get(w.control, JOBS, job_id) is None
    second = effects(w.tick())
    [after_second] = w.canaries()
    third = effects(w.tick())
    return {"first": first, "after_first": action_view(after_first), "no_job_row": no_row, "second": second,
            "after_second": action_view(after_second), "enqueued": w.fleet.calls,
            "same_job_id": len({c["manifest"]["id"] for c in w.fleet.calls}) == 1, "job": get(w.control, JOBS, job_id),
            "third": third, "stores": w.stores_and_effects()}


def moved_by(api, name):
    """LABELLED moves of the delivery, the descriptor, the candidate instance or the plan (an M7 test would write the same
    rows by hand); the delivery move is the REAL lane blocked at its consumption deadline."""
    def delivery(w):
        api.advance(200)
        return [r["stage"] for r in D.drive(w.system, until=api.ACTIVE, limit=4)]

    def descriptor(w):
        w.set_lane(descriptor_sha256="9" * 64)

    def instance(w):
        w.targets.startup_override = ({**w.system["host"].receipt(w.system["target"]), "instance_id": "1" * 32},)

    def plan(w):
        row = w.plan()
        w.put(w.control, OD.ACTIONS, row["id"], {**row, "plan_sha256": "0" * 64})

    return {"delivery": delivery, "descriptor": descriptor, "instance": instance, "plan": plan}[name]


def moved(api):
    """The plan, delivery, descriptor or instance moving: INTENDED -> REFUSED `canary_delivery_moved` (nothing enqueued),
    REQUESTED -> UNKNOWN `canary_delivery_moved`, and REQUESTED without a job row -> REFUSED (the R2 gate before any replay)."""
    out = {}
    for name in ("delivery", "descriptor", "instance", "plan"):
        for start in ("intended", "requested", "requested_without_job"):
            w = fresh(api)
            if start == "intended":
                intended(w)
            else:
                if start == "requested_without_job":
                    w.fleet.lose = 1
                w.tick()
            [before] = w.canaries()
            move = moved_by(api, name)(w)
            tick = effects(w.tick())
            [after] = w.canaries()
            out[name + "/" + start] = {"before": action_view(before), "move": move, "tick": tick,
                                       "after": action_view(after), "enqueued": len(w.fleet.calls),
                                       "receipts": w.targets.written, "reads": w.lanes.reads,
                                       "then": [effects(w.tick()) for _ in range(2)], "stores": w.stores_and_effects()}
    return out


def set_job(w, **changes):
    """LABELLED: the Fleet job as the dispatcher and the lane leave it (M7 writes the same rows by hand)."""
    [action] = w.canaries()
    job = get(w.control, JOBS, action["job_id"])
    w.put(w.control, JOBS, job["id"], {**job, "reason_code": None, **changes})


def outcomes(api):
    """running or absent: nothing written; unknown: UNKNOWN with its reason; accepted: one canary receipt written, then
    COMPLETED; rejected: one receipt written, then REJECTED; and a tick after each terminal state writes nothing."""
    cases = [("queued", {}, None), ("dispatching", {"status": "dispatching"}, None),
             ("running", {"status": "running"}, None), ("admitted", {"status": "admitted"}, None),
             ("reserved", {"status": "reserved"}, None),
             ("unknown", {"status": "unknown"}, None),
             ("markers", {"status": "accepted"}, {"operation": {"status": "accepted"}, "markers": ["m"], "lead": {}}),
             ("unproven_review", {"status": "accepted"},
              {"operation": {"status": "accepted"}, "markers": [], "lead": {"phase": "review_lead",
                                                                            "status": "succeeded", "result": {
                                                                                "accepted": False}}}),
             ("accepted", {"status": "accepted"}, None), ("rejected", {"status": "rejected"}, None),
             ("failed", {"status": "failed"}, None), ("exhausted", {"status": "exhausted"}, None)]
    out = {}
    for name, job, answer in cases:
        w = fresh(api)
        w.tick()
        set_job(w, **job)
        w.lanes.answer = answer
        before = w.stores()
        tick = effects(w.tick())
        [action] = w.canaries()
        receipt = w.system["owner_canary"].receipts.get(action["binding"]["plan_id"])
        wrote_nothing = w.stores() == before
        settled, receipts = w.stores(), list(w.targets.written)
        later = [effects(w.tick()) for _ in range(2)]
        out[name] = {"tick": tick, "action": action_view(action), "wrote_nothing": wrote_nothing,
                     "receipts_written": receipts, "receipt": receipt, "lane_reads": w.lanes.reads,
                     "later": later, "later_wrote_nothing": w.stores() == settled and w.targets.written == receipts,
                     "lane": [r["stage"] for r in D.drive(w.system, until=api.ACTIVE, limit=6)]}
    return out


def outcome_table(api):
    """The pure domain names `_advance_canary` calls: `canary_outcome` over every job status and evidence shape,
    `canary_receipt`, `canary_manifest` (and its refusal without a canary policy), `canary_job_id`, `canary_binding`."""
    od = api.owner_domain
    accepted = {"operation": {"status": "accepted"}, "markers": [],
                "lead": {"id": "decision-1", "phase": "review_lead", "status": "succeeded",
                         "result": {"accepted": True, "execution_ref": "sha256:" + "c" * 64}}}
    job = {"id": "canary-x", "operation_id": "canary-x", "status": "accepted"}
    table = {"absent": od.canary_outcome(None, None), "not_a_mapping": od.canary_outcome("job", accepted)}
    for status in ("queued", "dispatching", "running", "admitted", "reserved", "unknown", "accepted", "rejected", "failed",
                   "exhausted", "cancelled"):
        table[status] = od.canary_outcome({**job, "status": status}, accepted)
    table["accepted_without_evidence"] = od.canary_outcome(job, None)
    table["accepted_with_markers"] = od.canary_outcome(job, {**accepted, "markers": ["m"]})
    table["operation_not_accepted"] = od.canary_outcome(job, {**accepted, "operation": {"status": "failed"}})
    table["lead_not_accepted"] = od.canary_outcome(job, {**accepted, "lead": {**accepted["lead"], "result": {
        "accepted": False}}})
    table["no_execution_ref"] = od.canary_outcome(job, {**accepted, "lead": {**accepted["lead"], "result": {
        "accepted": True}}})
    table["rejected_carries_the_decision"] = od.canary_outcome({**job, "status": "rejected"}, accepted)
    action = {"id": "a" * 64, "binding": {"plan_id": "p", "plan_sha256": "1" * 64, "target_id": "t",
                                          "descriptor_sha256": "2" * 64, "instance_id": "i"}}
    return {"outcomes": table, "job_id": od.canary_job_id("a" * 64), "binding": od.canary_binding(
        {"plan_id": "p", "plan_sha256": "1" * 64}, {"target_id": "t", "descriptor_sha256": "2" * 64}, "i"),
            "manifest": od.canary_manifest({"canary": {"manifest": {"x": 1, "id": "template"}}}, "canary-y"),
            "manifest_unconfigured": call(od.canary_manifest, {"canary": None}, "canary-y"),
            "receipts": {name: od.canary_receipt(action, od.canary_outcome({**job, "status": status}, accepted), NOW)
                         for name, status in (("accepted", "accepted"), ("rejected", "rejected"),
                                              ("unknown", "unknown"))}}


def advance(api):
    return {"owed": owed(api), "request_once": request_once(api), "lost_admission": lost_admission(api),
            "moved": moved(api), "outcomes": outcomes(api), "domain": outcome_table(api)}


NOW = OD.NOW


# ---- 2. recovery (the LABELLED world() of the M7 module) ----------------------------------------------------------
GRAMMAR = [("schema", "urn:zeus:other:1"), ("kind", "delivery_canary"), ("action_version", 0), ("action_version", "3"),
           ("binding", {"plan_id": "p"}),
           ("halt", {"state": "unknown", "reason_code": "canary_job_unknown", "updated_at": "t"}),
           ("lane_retry_evidence", "sha256:xyz"), ("margin_seconds", 599), ("approved_by", "Robert'); drop"),
           ("job_id", "")]


def grammar(api):
    """M7 `test_the_document_grammar_is_exact` and `test_the_global_transition_table_is_not_weakened` (pure)."""
    do = api.owner_domain
    body, _ = Lab(api).document()
    out = {"valid": call(do.validate_canary_recovery, body), "extra": call(do.validate_canary_recovery, {**body,
                                                                                                        "extra": 1})}
    for field, value in GRAMMAR:
        out["%s=%r" % (field, value)] = call(do.validate_canary_recovery, {**body, field: value})
    out["transition_unknown_to_requested"] = call(do.transition, do.DELIVERY_CANARY, do.UNKNOWN, do.REQUESTED)
    out["unknown_is_terminal"] = do.UNKNOWN in do.TERMINAL
    return out


def recovers(api):
    """M7 `test_the_recovery_returns_the_same_action_to_requested_with_the_same_queued_job_and_then_a_receipt`: the lane rows
    are the LABELLED shapes of `world()`."""
    w = Lab(api)
    before = w.snapshot()
    body, evidence = w.document()
    receipt = w.attempt(body, evidence)
    after = w.row()
    lane_after = D.store_digest(w.lane)
    out = {"receipt": receipt, "row": after, "fleet_calls": w.fleet.calls, "lane_unchanged": lane_after == before["lane"],
           "job_unchanged": w.row(JOBS, w.job["id"]) == w.job,
           "fleet_paused": w.row(FLEET_CONTROL, "admission")["paused"] is True,
           "status": [a for a in w.owner.status()["actions"] if a["id"] == w.action["id"]]}
    out["queued_advance"] = {"effect": call(api.advance_canary, w.owner, w.policy_row, {}, w.row()),
                             "receipts": w.files.receipts}
    # LABELLED unpause + dispatch + accepted lane result: the existing path writes the receipt.
    w.put(JOBS, w.job["id"], {**w.job, "status": "accepted", "reason_code": None, "calls": {"reserved": 1,
                                                                                            "settled": 1}})
    out["accepted_advance"] = call(api.advance_canary, w.owner, w.policy_row, {}, w.row())
    out["receipt_written"] = w.files.receipts
    out["completed"] = w.row()
    out["replay"] = w.attempt(body, evidence)
    out["fleet_calls_after"] = w.fleet.calls
    return out


def held_again(api):
    """M7 `test_a_lane_change_after_the_recovery_is_held_again_by_the_existing_result_gate`."""
    w = Lab(api)
    body, evidence = w.document()
    first = w.attempt(body, evidence)
    w.files.startup_receipt = {"instance_id": "inst-replaced", "descriptor_sha256": DESCRIPTOR}
    w.put(JOBS, w.job["id"], {**w.job, "status": "accepted", "reason_code": None})
    effect = call(api.advance_canary, w.owner, w.policy_row, {}, w.row())
    other, other_ref = w.document(margin_seconds=900)
    return {"first": first, "effect": effect, "row": w.row(), "receipts": w.files.receipts, "fleet": w.fleet.calls,
            "other_evidence": w.refused("canary_recovery_conflict", other, other_ref),
            "same_evidence": w.attempt(body, evidence)}


def replay_and_conflict(api):
    """M7 `test_the_same_replay_is_cached_and_other_evidence_conflicts`."""
    w = Lab(api)
    body, evidence = w.document()
    first = w.attempt(body, evidence)
    before = w.snapshot()
    again = w.attempt(body, evidence)
    other, other_ref = w.document(margin_seconds=700)
    return {"first": first, "again": again, "snapshot_unchanged": w.snapshot() == before,
            "same_version": first["outcome"]["value"]["version"] == again["outcome"]["value"]["version"],
            "conflict": w.refused("canary_recovery_conflict", other, other_ref)}


BINDING_OTHER = {"plan_id": PLAN_ID, "plan_sha256": PLAN_SHA, "target_id": TARGET, "descriptor_sha256": "9" * 64,
                 "instance_id": INSTANCE}
DOCUMENT_NEGATIVES = [
    ({"action_version": 2}, "canary_recovery_version_mismatch"),
    ({"binding": BINDING_OTHER}, "canary_recovery_binding_mismatch"),
    ({"binding_sha256": "9" * 64}, "canary_recovery_binding_mismatch"),
    ({"policy_sha256": "9" * 64}, "canary_recovery_policy_mismatch"),
    ({"job_id": "canary-other"}, "canary_recovery_job_mismatch"),
    ({"halt": {"state": "unknown", "reason_code": "canary_delivery_moved", "updated_at": "2026-09-27T03:21:00+00:00"}},
     "canary_recovery_halt_mismatch"),
    ({"lane_retry_evidence": "sha256:" + "d" * 64}, "canary_recovery_lane_not_retried"),
    ({"margin_seconds": 3601}, "canary_recovery_margin"),
    ({"approved_by": "lead:research"}, "canary_recovery_approver_invalid"),
    ({"approved_by": "nobody"}, "canary_recovery_approver_invalid")]
JOB_NEGATIVES = [
    ({"status": "dispatching"}, "canary_recovery_job_dispatching"), ({"status": "running"}, "canary_recovery_job_running"),
    ({"status": "accepted"}, "canary_recovery_job_accepted"), ({"status": "failed"}, "canary_recovery_job_failed"),
    ({"calls": {"reserved": 1, "settled": None}}, "canary_recovery_job_calls"),
    ({"dispatched_at": "2026-09-27T03:30:00+00:00"}, "canary_recovery_job_started"),
    ({"owner_token": "tok"}, "canary_recovery_job_started"), ({"lane": "b"}, "canary_recovery_job_mismatch"),
    ({"reason_code": "budget_stale"}, "canary_recovery_job_reason")]


def lane_negatives(api):
    first = {"kind": api.RECOVERY_FIRST_ACTIVATION, "evidence_ref": "sha256:" + "f" * 64}
    retry = {"kind": api.RECOVERY_CONSUMPTION_RETRY, "evidence_ref": LANE_RETRY}
    return [
        ({"stage": "blocked"}, "canary_recovery_lane_not_awaiting"),
        ({"recoveries": [first]}, "canary_recovery_lane_not_retried"),
        ({"recoveries": [{**retry, "observed": {"observed_instance_id": "inst-2", "descriptor_sha256": DESCRIPTOR}}]},
         "canary_recovery_instance_mismatch"),
        ({"recoveries": [{**retry, "observed": {"observed_instance_id": INSTANCE, "descriptor_sha256": "7" * 64}}]},
         "canary_recovery_descriptor_mismatch"),
        ({"descriptor_sha256": "7" * 64}, "canary_recovery_delivery_moved"),
        ({"stage_deadline": (T0 + timedelta(seconds=599)).isoformat()}, "canary_recovery_margin")]


def negatives(api):
    """Each a named refusal with zero writes (M7 `test_a_document_that_does_not_name_the_stored_facts_writes_nothing`,
    `test_evidence_must_be_the_digest_of_the_document`, `test_a_started_moved_or_foreign_job_writes_nothing`,
    `test_a_missing_job_or_a_running_fleet_writes_nothing`, `test_a_missing_job_writes_nothing`,
    `test_a_foreign_state_or_reason_writes_nothing`, `test_an_unknown_that_never_came_from_requested_writes_nothing`,
    `test_a_changed_policy_row_writes_nothing`, `test_a_lane_that_was_not_retried_for_this_instance_writes_nothing`,
    `test_a_replaced_instance_or_an_existing_receipt_writes_nothing` and
    `test_the_candidate_author_cannot_approve_its_own_recovery`); the rows are the LABELLED shapes of `world()`."""
    do = api.owner_domain
    out = {"document": {}, "job": {}, "foreign": {}, "lane": {}}
    for i, (override, code) in enumerate(DOCUMENT_NEGATIVES):
        w = Lab(api)
        body, evidence = w.document(**override)
        out["document"]["%d %s" % (i, ",".join(sorted(override)))] = w.refused(code, body, evidence)
    w = Lab(api)
    body, _ = w.document()
    out["evidence_mismatch"] = w.refused("canary_recovery_evidence_mismatch", body, "sha256:" + "0" * 64)
    out["evidence_invalid"] = w.refused("canary_recovery_evidence_invalid", body, "sha1:abc")
    out["evidence_not_a_string"] = w.refused("canary_recovery_evidence_invalid", body, 7)
    out["document_not_a_mapping"] = w.refused("canary_recovery_invalid", [], "sha256:" + "0" * 64)
    for i, (change, code) in enumerate(JOB_NEGATIVES):
        w = Lab(api)
        w.put(JOBS, w.job["id"], {**w.job, **change})
        out["job"]["%d %s" % (i, ",".join(sorted(change)))] = w.refused(code)
    w = Lab(api)
    w.put(FLEET_CONTROL, "admission", {"paused": False})
    out["fleet_running"] = w.refused("canary_recovery_fleet_not_paused")
    w = Lab(api)
    w.put(FLEET_CONTROL, "admission", {"updated_at": "labelled"})
    out["fleet_flag_absent"] = w.refused("canary_recovery_fleet_not_paused")
    w = Lab(api)
    missing = {**w.action, "id": "9" * 64, "job_id": do.canary_job_id("9" * 64)}
    w.put(ACTIONS, missing["id"], missing)
    w.action = missing
    body, evidence = w.document()
    out["job_missing"] = w.refused("canary_recovery_job_missing", body, evidence)
    w = Lab(api)
    body, evidence = w.document(action_id="8" * 64)
    out["action_missing"] = w.refused("canary_recovery_action_missing", body, evidence)
    w = Lab(api)
    w.put(ACTIONS, "c" * 64, {**w.plan_action, "id": "c" * 64})
    body, evidence = w.document(action_id="c" * 64)
    out["action_is_not_a_canary"] = w.refused("canary_recovery_action_missing", body, evidence)
    for state, reason, code in ((do.UNKNOWN, "canary_job_unknown", "canary_recovery_not_applicable"),
                                (do.REQUESTED, "canary_requested", "canary_recovery_not_applicable"),
                                (do.REFUSED, "canary_delivery_moved", "canary_recovery_not_applicable")):
        w = Lab(api)
        w.put(ACTIONS, w.action["id"], {**w.action, "state": state, "reason_code": reason})
        out["foreign"][state + "/" + reason] = w.refused(code)
    w = Lab(api)
    history = [w.action["history"][0], w.action["history"][2]]
    w.put(ACTIONS, w.action["id"], {**w.action, "history": history})
    out["never_from_requested"] = w.refused("canary_recovery_not_from_requested")
    w = Lab(api)
    w.put(POLICIES, "owners-1", {**w.policy_row, "policy_sha256": "8" * 64})
    out["policy_row_changed"] = w.refused("canary_recovery_policy_mismatch")
    w = Lab(api)
    w.put(POLICIES, "owners-1", {**w.policy_row, "policy": {"enabled": True, "canary": {"lane": "b"}}})
    out["policy_lane_changed"] = w.refused("canary_recovery_job_mismatch")
    for i, (change, code) in enumerate(lane_negatives(api)):
        w = Lab(api)
        w.set_intent(**change)
        out["lane"]["%d %s" % (i, ",".join(sorted(change)))] = w.refused(code)
    w = Lab(api)
    w.files.startup_receipt = {"instance_id": "inst-replaced", "descriptor_sha256": DESCRIPTOR}
    out["instance_replaced"] = w.refused("canary_recovery_delivery_moved")
    w.files.startup_receipt = {"instance_id": INSTANCE, "descriptor_sha256": DESCRIPTOR}
    w.files.receipts[PLAN_ID] = {"passed": False}
    out["receipt_exists"] = w.refused("canary_recovery_receipt_exists")
    w = Lab(api)
    w.put(ACTIONS, w.plan_action["id"], {**w.plan_action, "plan_sha256": "6" * 64})
    out["plan_digest_changed"] = w.refused("canary_recovery_plan_missing")
    w = Lab(api)
    w.set_intent(stage_deadline="not a time")
    out["deadline_unobservable"] = w.refused("canary_recovery_deadline_unobservable")
    w = Lab(api)
    w.set_intent(stage_deadline=None)
    out["deadline_absent"] = w.refused("canary_recovery_deadline_unobservable")
    w = Lab(api, author="conductor")
    out["author_cannot_approve"] = w.refused("canary_recovery_approver_author")
    w = Lab(api)
    unconfigured = {}
    for name in ("deliveries", "targets"):
        w = Lab(api)
        owner = api.OwnerActions(w.control, org=api.organization(), lanes=w.lanes, fleet=w.fleet,
                                 deliveries=None if name == "deliveries" else (lambda lane_id: Delivery(w.lane)),
                                 targets=None if name == "targets" else w.files, clock=w.clock)
        w.owner = owner
        unconfigured[name] = w.refused("canary_recovery_ports_unconfigured")
    out["ports_unconfigured"] = unconfigured
    w = Lab(api)
    owner = api.OwnerActions(w.control, lanes=w.lanes, fleet=w.fleet, deliveries=lambda lane_id: Delivery(w.lane),
                             targets=w.files, clock=w.clock)
    w.owner = owner
    out["approver_unavailable"] = w.refused("canary_recovery_approver_unavailable")
    return out


def concurrent_move(api):
    """M7 `test_a_concurrent_move_between_preflight_and_write_is_refused`. M7 swaps the private `_recovery_lane` for a
    wrapper that writes the Fleet job after the lane read; the same write is made here from the last read `_recovery_lane`
    performs (the `Files.receipt` seam, LABELLED), so the compare-and-swap transaction sees it as it does in M7. The same
    seam moves the action, the Fleet control row and the policy row. `wrote` includes the seam's own write; the refusal leaves
    the action UNKNOWN without a recovery."""
    out = {}
    moves = {"job": lambda w: w.put(JOBS, w.job["id"], {**w.job, "updated_at": "2026-09-27T04:00:01+00:00"}),
             "action": lambda w: w.put(ACTIONS, w.action["id"], {**w.action, "updated_at": "2026-09-27T04:00:01+00:00"}),
             "fleet": lambda w: w.put(FLEET_CONTROL, "admission", {"paused": True, "updated_at": "later"}),
             "policy": lambda w: w.put(POLICIES, "owners-1", {**w.policy_row, "registered_at": "later"})}
    for name, move in moves.items():
        w = Lab(api)
        body, evidence = w.document()
        w.files.on_receipt = lambda w=w, move=move: move(w)
        entry = w.attempt(body, evidence)
        row = w.row()
        out[name] = {**entry, "state": row["state"], "no_recoveries": "recoveries" not in row,
                     "fleet_calls": w.fleet.calls}
    return out


def restart_pure(api):
    """M7 `test_a_retry_observing_another_instance_without_a_linked_restart_is_refused` (pure): the explicit two-sided link,
    and `restart_owed_canary`; `rearm_owed_canary` (INV-HOST-DELIVERY-FIRST-ACTIVATION-001, extended)."""
    od = api.owner_domain
    link = "sha256:" + "a" * 64
    intent = {"recoveries": [{"kind": "first_activation_binding"},
                             {"kind": od.LANE_RESTART_KIND, "state": "started", "evidence_ref": link,
                              "stopped": {"instance_id": "old"}, "started": {"instance_id": "new"}},
                             {"kind": od.LANE_RETRY_KIND, "observed": {"observed_instance_id": "new",
                                                                       od.LANE_RESTART_LINK: link}}]}
    out = {"linked": od.linked_restart(intent), "kinds": [od.LANE_RESTART_KIND, od.LANE_RETRY_KIND, od.LANE_REARM_KIND,
                                                          od.LANE_RESTART_LINK, od.CANARY_RECOVERY_KIND,
                                                          od.CANARY_REARM_KIND, od.MAX_REARM_WINDOW,
                                                          od.CANARY_RECOVERY_HALT_REASON],
           "lane_kinds_are_the_lane_names": [od.LANE_RETRY_KIND == api.RECOVERY_CONSUMPTION_RETRY,
                                             od.LANE_REARM_KIND == api.RECOVERY_CONSUMPTION_REARM,
                                             od.LANE_RESTART_KIND == api.RECOVERY_GENERATION_RESTART]}
    broken = {}
    for name, change in (("launched", {"state": "launched"}), ("other_evidence", {"evidence_ref": "sha256:" + "b" * 64}),
                         ("started_is_stopped", {"started": {"instance_id": "old"}})):
        variant = copy.deepcopy(intent)
        variant["recoveries"][1].update(change)
        broken[name] = od.linked_restart(variant)
    unlinked = copy.deepcopy(intent)
    del unlinked["recoveries"][2]["observed"][od.LANE_RESTART_LINK]
    other = copy.deepcopy(intent)
    other["recoveries"][2]["observed"]["observed_instance_id"] = "third"
    two = copy.deepcopy(intent)
    two["recoveries"].insert(2, copy.deepcopy(intent["recoveries"][1]))
    not_last = copy.deepcopy(intent)
    not_last["recoveries"].append({"kind": "other"})
    out["broken"] = broken
    out["unlinked"] = od.linked_restart(unlinked)
    out["other_instance"] = od.linked_restart(other)
    out["two_restarts"] = od.linked_restart(two)
    out["retry_not_last"] = od.linked_restart(not_last)
    out["not_an_intent"] = [od.linked_restart(None), od.linked_restart("x"), od.linked_restart({})]
    owed_action = {"kind": od.DELIVERY_CANARY, "state": od.UNKNOWN, "reason_code": od.CANARY_RECOVERY_HALT_REASON,
                   "binding": {"instance_id": "old"}}
    restart = od.linked_restart(intent)
    out["restart_owed"] = {
        "owed": od.restart_owed_canary(owed_action, restart),
        "bound_to_the_restarted": od.restart_owed_canary({**owed_action, "binding": {"instance_id": "new"}}, restart),
        "already_recovered": od.restart_owed_canary({**owed_action, "recoveries": [{}]}, restart),
        "no_restart": od.restart_owed_canary(owed_action, None),
        "requested": od.restart_owed_canary({**owed_action, "state": od.REQUESTED}, restart),
        "other_reason": od.restart_owed_canary({**owed_action, "reason_code": "canary_job_unknown"}, restart),
        "other_kind": od.restart_owed_canary({**owed_action, "kind": od.DELIVERY_PLAN}, restart)}
    rearm = {"kind": od.LANE_REARM_KIND, "observed": {"observed_instance_id": "old"}}
    lane = {"recoveries": [{"kind": od.LANE_RETRY_KIND}, rearm]}
    once = {**owed_action, "recoveries": [{"kind": od.CANARY_RECOVERY_KIND}]}
    out["rearm_owed"] = {
        "owed": od.rearm_owed_canary(once, lane), "no_prior_recovery": od.rearm_owed_canary(owed_action, lane),
        "already_rearmed": od.rearm_owed_canary({**once, "recoveries": [{"kind": od.CANARY_RECOVERY_KIND},
                                                                         {"kind": od.CANARY_REARM_KIND}]}, lane),
        "other_instance": od.rearm_owed_canary({**once, "binding": {"instance_id": "new"}}, lane),
        "no_observed_instance": od.rearm_owed_canary(once, {"recoveries": [{"kind": od.LANE_REARM_KIND}]}),
        "lane_latest_is_retry": od.rearm_owed_canary(once, {"recoveries": [rearm, {"kind": od.LANE_RETRY_KIND}]}),
        "not_unknown": od.rearm_owed_canary({**once, "state": od.REQUESTED}, lane),
        "not_an_intent": [od.rearm_owed_canary(once, None), od.rearm_owed_canary(None, lane)]}
    return out


def rebound(api):
    """The linked lane restart at the store level (LABELLED lane rows of the shapes `HostDelivery` records: a `started`
    generation restart of the stopped instance, then the ONE retry observing the restarted instance and naming the restart
    by its evidence): the recovery re-binds the SAME action and job to the restarted instance (the case M7 proves end to end
    in `test_after_a_host_restart_the_real_owner_rebinds_the_same_canary_to_the_restarted_generation`, which is out of scope);
    the unlinked retry is `canary_recovery_instance_mismatch`."""
    od = api.owner_domain
    link = "sha256:" + "a" * 64

    def lane_rows(w, **retry_extra):
        first = {"kind": api.RECOVERY_FIRST_ACTIVATION, "evidence_ref": "sha256:" + "f" * 64}
        restart = {"kind": od.LANE_RESTART_KIND, "state": "started", "evidence_ref": link,
                   "stopped": {"instance_id": INSTANCE}, "started": {"instance_id": "inst-2"}}
        retry = {"kind": od.LANE_RETRY_KIND, "evidence_ref": LANE_RETRY,
                 "observed": {"observed_instance_id": "inst-2", "descriptor_sha256": DESCRIPTOR, **retry_extra}}
        w.set_intent(recoveries=[first, restart, retry])
        w.files.startup_receipt = {"instance_id": "inst-2", "descriptor_sha256": DESCRIPTOR}

    w = Lab(api)
    lane_rows(w, **{od.LANE_RESTART_LINK: link})
    body, evidence = w.document()
    receipt = w.attempt(body, evidence)
    row = w.row()
    w.put(JOBS, w.job["id"], {**w.job, "status": "accepted", "reason_code": None})
    effect = call(api.advance_canary, w.owner, w.policy_row, {}, row)
    out = {"receipt": receipt, "row": row, "rebound": row["recoveries"][-1].get("rebound"),
           "binding_sha256_is_digest": row["binding_sha256"] == api.digest(row["binding"]),
           "binding_moved": row["binding_sha256"] != w.action["binding_sha256"], "advance": effect,
           "receipt_written": w.files.receipts, "replay": w.attempt(body, evidence)}
    w = Lab(api)
    lane_rows(w)
    out["unlinked_retry"] = w.refused("canary_recovery_instance_mismatch")
    w = Lab(api)
    lane_rows(w, **{od.LANE_RESTART_LINK: "sha256:" + "b" * 64})
    out["wrongly_linked_retry"] = w.refused("canary_recovery_instance_mismatch")
    return out


def lab_recovery(api):
    return {"grammar": grammar(api), "recovers": recovers(api), "held_again": held_again(api),
            "replay_and_conflict": replay_and_conflict(api), "negatives": negatives(api),
            "concurrent_move": concurrent_move(api), "restart_pure": restart_pure(api), "rebound": rebound(api)}


# ---- 3. re-arm --------------------------------------------------------------------------------------------------------
def rearm_grammar(api):
    """M7 `test_the_rearm_document_grammar_is_exact` (pure)."""
    do = api.owner_domain
    w = Lab(api)
    base, _ = w.rearm_document()
    out = {"valid": call(do.validate_canary_recovery, base), "max_window": do.MAX_REARM_WINDOW}
    for field, value in (("lane_window_seconds", 3601), ("lane_window_seconds", 0), ("lane_window_seconds", True),
                         ("lane_rearm_evidence", "sha256:x"), ("margin_seconds", 3600), ("kind", "other")):
        out["%s=%r" % (field, value)] = call(do.validate_canary_recovery, {**base, field: value})
    out["with_lane_retry_evidence"] = call(do.validate_canary_recovery, {**base, "lane_retry_evidence": LANE_REARM})
    retry_kind = {k: v for k, v in base.items() if k not in ("lane_rearm_evidence", "lane_window_seconds")}
    out["retry_kind_without_its_evidence"] = call(do.validate_canary_recovery, {**retry_kind,
                                                                                 "kind": do.CANARY_RECOVERY_KIND})
    return out


def rearmed_lab(api):
    """The store-level core of M7 `test_after_the_retry_expires_again_the_same_canary_is_rearmed_once_and_the_delivery_is_
    consumed` over the LABELLED `world()` rows: the retry-kind recovery, the window expiring AGAIN (the ordinary result gate:
    UNKNOWN once more), then the lane's ONE re-arm (a LABELLED lane row of the shape `HostDelivery.resume_consumption_rearm`
    records)."""
    od = api.owner_domain
    w = Lab(api)
    body, evidence = w.document()
    first = w.attempt(body, evidence)
    intent = w.intent()
    w.set_intent(stage=api.BLOCKED, reason_code="no_known_good_predecessor")
    halted_effect = call(api.advance_canary, w.owner, w.policy_row, {}, w.row())
    halted = w.row()
    w.set_intent(**{k: v for k, v in intent.items() if k in ("stage", "reason_code")}, reason_code=None)
    out = {"first": first, "blocked_again": halted_effect, "halted": halted, "not_yet_owed": od.rearm_owed_canary(
        halted, w.intent())}
    # a re-arm without the lane's re-arm: the lane's latest recovery is still the retry
    early, early_ref = w.rearm_document(halted)
    out["without_the_lane_rearm"] = w.refused("canary_recovery_lane_not_rearmed", early, early_ref)
    # the lane is blocked again: the owner's re-arm before the lane's is refused, nothing written
    w.set_intent(stage=api.BLOCKED)
    out["lane_blocked"] = w.refused("canary_recovery_lane_not_awaiting", early, early_ref)
    rearm = {"kind": od.LANE_REARM_KIND, "evidence_ref": LANE_REARM, "window_seconds": 3600,
             "observed": {"observed_instance_id": INSTANCE, "descriptor_sha256": DESCRIPTOR}}
    w.set_intent(stage=api.AWAITING_CONSUMPTION, recoveries=[*intent["recoveries"], rearm],
                 stage_deadline=(T0 + timedelta(seconds=3600)).isoformat())
    out["owed_after_the_lane_rearm"] = od.rearm_owed_canary(halted, w.intent())
    again, again_ref = w.document(action_version=halted["version"], halt={
        "state": halted["state"], "reason_code": halted["reason_code"], "updated_at": halted["updated_at"]})
    out["second_retry_kind"] = w.refused("canary_recovery_conflict", again, again_ref)
    short, short_ref = w.rearm_document(halted, lane_window_seconds=900)
    out["other_window"] = w.refused("canary_recovery_lane_window_mismatch", short, short_ref)
    over, over_ref = w.rearm_document(halted, lane_window_seconds=3601)
    out["over_long_window"] = w.refused("canary_recovery_invalid", over, over_ref)
    wrong, wrong_ref = w.rearm_document(halted, lane_rearm_evidence="sha256:" + "9" * 64)
    out["other_rearm_evidence"] = w.refused("canary_recovery_lane_not_rearmed", wrong, wrong_ref)
    before_rows = w.snapshot()
    rearmed, rearmed_ref = w.rearm_document(halted)
    done = w.attempt(rearmed, rearmed_ref)
    row = w.row()
    out["rearmed"] = done
    out["row"] = {k: row.get(k) for k in ("id", "state", "reason_code", "version", "job_id", "binding", "binding_sha256",
                                          "history")}
    out["recoveries"] = row["recoveries"]
    out["same_action_same_binding_same_job"] = [row["id"], row["binding"], row["job_id"]] == [
        halted["id"], halted["binding"], halted["job_id"]]
    out["kinds"] = [r["kind"] for r in row["recoveries"]]
    out["job_untouched"] = w.row(JOBS, w.job["id"]) == w.job and w.fleet.calls == []
    out["second_rearm"] = w.refused("canary_recovery_conflict", *w.rearm_document(
        halted, lane_rearm_evidence="sha256:" + "8" * 64))
    out["same_rearm_cached"] = w.attempt(rearmed, rearmed_ref)
    out["first_recovery_still_cached"] = w.attempt(body, evidence)
    # LABELLED: the independent gates resume the Fleet; the canary runs and the delivery is consumed
    w.put(JOBS, w.job["id"], {**w.job, "status": "accepted", "reason_code": None, "calls": {"reserved": 1,
                                                                                            "settled": 1}})
    out["accepted"] = call(api.advance_canary, w.owner, w.policy_row, {}, w.row())
    out["receipt_written"] = w.files.receipts
    out["cached_at_completed"] = [w.attempt(rearmed, rearmed_ref), w.attempt(body, evidence)]
    out["snapshot_moved_by_the_rearm"] = before_rows != w.snapshot()
    only_rearm = Lab(api)
    once, once_ref = only_rearm.rearm_document()
    out["rearm_without_any_recovery"] = only_rearm.refused("canary_recovery_not_applicable", once, once_ref)
    return out


class Chain:
    """The REAL lane after its owner commands (`s7_owner_commands`): a historical unbound first activation bound by
    `resume_first_activation`, an owner canary still PENDING at the consumption deadline (`no_known_good_predecessor`, the
    stage BLOCKED), then the lane's ONE `resume_consumption_retry` and, on request, its ONE `resume_consumption_rearm`. It is
    the `retry_halt` of M7's retry file with M7's end-to-end 900 s consumption window (`first_halt` fixes 10 s, which leaves
    no room for the recovery margin). The owner's control rows are the LABELLED `Lab` rows naming this lane's plan, instance
    and descriptor."""

    def __init__(self, api, label):
        self.api = api
        overrides = {"image": api.UNCHANGED, "profile": api.UNCHANGED, "canary": api.CANARY_FLEET,
                     "consumption_timeout": 900}
        switch = OC.SwitchCanary()
        run = self.run = OC.Case(api, label, plan_overrides=overrides, register_plan=False,
                                 canaries={api.CANARY_FLEET: switch})
        S.register_historical(run)
        run.until(api.MERGED, limit=8)
        run.tick(note="the historical unbound plan halts: unchanged_without_predecessor")
        run.facts, run.counting, run.canary = OC.FixedFacts(), OC.CountingVerifier(), switch
        run.delivery.first_activation = run.facts
        run.delivery.verifier = run.counting
        body, evidence = OC.first_doc(run)
        OC.first_command(run, body, evidence, note="the owner binds the first activation")
        run.first_evidence = evidence
        run.until(api.AWAITING_CONSUMPTION, limit=20)
        self.expire()
        self.store, self.clock = run.store, D.clock(api)

    def expire(self):
        """The consumption window passes with the owner canary still pending."""
        self.run.wait(900)
        results = self.run.until(self.api.ACTIVE, limit=10)
        self.halt = {"stage": results[-1]["stage"], "reason_code": results[-1]["reason_code"]}
        return self.halt

    def retry(self):
        return OC.retry_command(self.run, note="the one retry")

    def rearm(self):
        return OC.rearm_command(self.run, note="the one re-arm")

    def startup(self, target):
        return self.run.host.receipt(target)

    @property
    def ids(self):
        run, intent = self.run, self.run.intent()
        recoveries = [r for r in intent["recoveries"] if r["kind"] == self.api.RECOVERY_CONSUMPTION_RETRY]
        return {"plan_id": run.system["plan"]["plan_id"], "plan_sha": run.plan_sha(),
                "target": run.system["target"]["target_id"], "descriptor": intent["descriptor_sha256"],
                "instance": intent["candidate_instance_id"], "release": run.release_id(),
                "retry": recoveries[-1]["evidence_ref"] if recoveries else None}

    def lane_view(self):
        return self.run.owner_view()


def command_view(out):
    """A lane owner command's outcome without the whole intent: the stage, outcome and reason it reports."""
    value = out.get("value") or {}
    return {**{k: out[k] for k in ("refused", "reason_code") if k in out},
            **{k: value.get(k) for k in ("stage", "outcome", "reason_code") if k in value}, "wrote": out.get("wrote")}


def chain_retry(api):
    """The owner recovery over the REAL lane's retry (M7 `test_the_real_owner_and_real_lane_recover_the_halted_canary_end_to_
    end`, steps 3 to 5; the real process target, Fleet and lane are out of scope): the lane rows are produced by
    `resume_consumption_retry` over the `s7_delivery` doubles, the control rows are the LABELLED shapes of `world()`."""
    chain = Chain(api, "owner_recovery_after_the_real_retry")
    halt = chain.halt
    retried = chain.retry()
    w = Lab(api, chain=chain)
    lane = chain.lane_view()
    body, evidence = w.document()
    receipt = w.attempt(body, evidence)
    row = w.row()
    lane_unchanged = chain.lane_view() == lane
    w.put(JOBS, w.job["id"], {**w.job, "status": "accepted", "reason_code": None, "calls": {"reserved": 1,
                                                                                            "settled": 1}})
    advanced = call(api.advance_canary, w.owner, w.policy_row, {}, row)
    completed = w.row()
    replay = w.attempt(body, evidence)
    chain.run.canary.passes()
    active = [r["stage"] for r in chain.run.until(api.ACTIVE, limit=10)]
    return {"halt": halt, "retried": command_view(retried),
            "lane": lane, "receipt": receipt, "row": row, "lane_unchanged_by_the_recovery": lane_unchanged,
            "advance": advanced, "completed": completed, "receipt_written": w.files.receipts, "replay": replay,
            "lane_then": active, "fleet": w.fleet.calls,
            "retry_ids": {k: v for k, v in chain.ids.items() if k != "retry"}}


def chain_rearm(api):
    """The store-level core of the re-arm end-to-end over the REAL lane: the retry, the window expiring AGAIN, the lane's ONE
    re-arm (`resume_consumption_rearm`, the explicit 3600 s window) and the owner's re-arm recovery paired only with it."""
    chain = Chain(api, "owner_rearm_after_the_real_rearm")
    chain.retry()
    w = Lab(api, chain=chain)
    body, evidence = w.document()
    first = w.attempt(body, evidence)
    second_expiry = chain.expire()
    blocked = call(api.advance_canary, w.owner, w.policy_row, {}, w.row())
    halted = w.row()
    early, early_ref = w.rearm_document(halted)
    early_refusal = w.refused("canary_recovery_lane_not_awaiting", early, early_ref)
    rearm = chain.rearm()
    lane_record = chain.run.intent()["recoveries"][-1]
    evidence_ref = lane_record["evidence_ref"]
    owed = api.owner_domain.rearm_owed_canary(halted, chain.run.intent())
    out = {"first": first, "second_expiry": second_expiry, "blocked_again": blocked, "halted": halted,
           "early": early_refusal, "lane_rearm": {k: lane_record.get(k) for k in ("kind", "window_seconds")},
           "lane_rearm_observed": lane_record.get("observed"), "owed": owed}
    again = w.document(action_version=halted["version"], halt={"state": halted["state"],
                                                              "reason_code": halted["reason_code"],
                                                              "updated_at": halted["updated_at"]})
    out["second_retry_kind"] = w.refused("canary_recovery_conflict", *again)
    short, short_ref = w.rearm_document(halted, lane_rearm_evidence=evidence_ref, lane_window_seconds=900)
    out["other_window"] = w.refused("canary_recovery_lane_window_mismatch", short, short_ref)
    wrong, wrong_ref = w.rearm_document(halted, lane_rearm_evidence=LANE_REARM)
    out["not_the_lanes_rearm"] = w.refused("canary_recovery_lane_not_rearmed", wrong, wrong_ref)
    rearmed, rearmed_ref = w.rearm_document(halted, lane_rearm_evidence=evidence_ref)
    done = w.attempt(rearmed, rearmed_ref)
    row = w.row()
    out.update({"rearmed": done, "row": row, "kinds": [r["kind"] for r in row["recoveries"]],
                "same_action_same_binding": row["id"] == halted["id"] and row["binding"] == halted["binding"],
                "second_rearm": w.refused("canary_recovery_conflict", *w.rearm_document(
                    halted, lane_rearm_evidence=evidence_ref, margin_seconds=700)),
                "same_rearm_cached": w.attempt(rearmed, rearmed_ref),
                "lane_after": chain.lane_view()})
    w.put(JOBS, w.job["id"], {**w.job, "status": "accepted", "reason_code": None, "calls": {"reserved": 1,
                                                                                            "settled": 1}})
    out["accepted"] = call(api.advance_canary, w.owner, w.policy_row, {}, w.row())
    out["receipt_written"] = w.files.receipts
    chain.run.canary.passes()
    out["lane_then"] = [r["stage"] for r in chain.run.until(api.ACTIVE, limit=10)]
    out["cached_at_completed"] = [w.attempt(rearmed, rearmed_ref), w.attempt(body, evidence)]
    out["rearm_command"] = command_view(rearm)
    return out


# ---- 4. scheduler ---------------------------------------------------------------------------------------------------
def scheduler(api):
    """`OwnerActions.tick` discovering the owed canary after its plan completes and advancing it next to an idle research
    family (a policy v2 with the research block and a research-route intent that is not held: nothing is owed and no
    research port exists), and `status` projecting it at every phase."""
    block = {"enabled": True, "program_id": "rp-b2", "lane": "a"}
    w = Owned(api, fleet=True, v2=True, research=block)
    w.put(w.control, OD.INTENTS, "research-1", {"id": "research-1", "policy_id": "policy-1", "route": api.dc.RESEARCH,
                                                 "state": api.dc.ADMITTED, "lane": "a", "created_at": NOW, "version": 1})
    statuses = {"registered": w.owner.status(w.policy["id"])}
    plan_ticks = [effects(r) for r in w.ticks(3)]
    statuses["plan_registered"] = w.owner.status(w.policy["id"])
    early = effects(w.tick())
    lane = [r["stage"] for r in D.drive(w.system, until=api.AWAITING_CONSUMPTION, limit=20)]
    discovered = effects(w.tick())
    statuses["canary_requested"] = w.owner.status(w.policy["id"])
    queued = [effects(w.tick()) for _ in range(2)]
    set_job(w, status="accepted")
    completed = effects(w.tick())
    statuses["canary_completed"] = w.owner.status()
    before = w.stores_and_effects()
    idle = [effects(w.tick()), effects(w.tick(owner=w.build_owner()))]
    idle_moved = sorted(k for k, v in w.stores_and_effects().items() if v != before[k])
    lane_after = [r["stage"] for r in D.drive(w.system, until=api.ACTIVE, limit=6)]
    final = [effects(w.tick()) for _ in range(2)]
    return {"statuses": statuses, "plan_ticks": plan_ticks, "before_the_lane_consumes": early, "lane": lane,
            "discovered_and_requested": discovered, "queued": queued, "completed": completed, "idle": idle,
            "idle_moved": idle_moved, "lane_after": lane_after, "final": final,
            "actions": [{"kind": a["kind"], "state": a["state"], "reason_code": a["reason_code"]} for a in w.actions()],
            "research_rows": [a for a in w.actions() if a["kind"] in (api.owner_domain.RESEARCH_RECEIPT,
                                                                       api.owner_domain.RESEARCH_DISPATCH)],
            "enqueued": [c["manifest"]["id"] for c in w.fleet.calls], "receipts_written": w.targets.written,
            "unknown_policy": call(w.owner.status, "owners-none")}


def owed_recovery(api):
    """A halted canary whose instance a linked lane restart stopped, or whose lane holds its ONE re-arm, is owed its typed
    recovery: discovery waits `canary_recovery_owed` and never creates a second canary (INV-HOST-DELIVERY-FIRST-ACTIVATION-001,
    extended). The lane rows are the REAL lane's with LABELLED rewrites of the shapes `HostDelivery` records."""
    od = api.owner_domain
    out = {}
    for name in ("restart", "rearm", "neither"):
        w = fresh(api)
        w.tick()
        [requested] = w.canaries()
        moved_by(api, "delivery")(w)
        halted = effects(w.tick())
        [unknown] = w.canaries()
        intent = w.lane_intent()
        reporting = w.system["host"].receipt(w.system["target"])
        link = "sha256:" + "a" * 64
        binding = unknown["binding"]
        if name == "restart":
            new = "1" * 32
            recoveries = [{"kind": od.LANE_RESTART_KIND, "state": "started", "evidence_ref": link,
                           "stopped": {"instance_id": binding["instance_id"]}, "started": {"instance_id": new}},
                          {"kind": od.LANE_RETRY_KIND, "evidence_ref": LANE_RETRY, "observed": {
                              "observed_instance_id": new, od.LANE_RESTART_LINK: link}}]
            w.targets.startup_override = ({**reporting, "instance_id": new},)
        elif name == "rearm":
            recoveries = [{"kind": od.LANE_REARM_KIND, "evidence_ref": LANE_REARM, "window_seconds": 3600,
                           "observed": {"observed_instance_id": binding["instance_id"]}}]
            w.put(w.control, OD.ACTIONS, unknown["id"], {**unknown, "recoveries": [{"kind": od.CANARY_RECOVERY_KIND,
                                                                                    "evidence_ref": LANE_RETRY}]})
        else:
            recoveries = []
        w.put(w.lane_store, D.BUCKET_INTENTS, intent["plan_id"], {**intent, "stage": api.AWAITING_CONSUMPTION,
                                                                     "recoveries": recoveries})
        ticks = [effects(w.tick()) for _ in range(2)]
        out[name] = {"halted": halted, "ticks": ticks, "canaries": [action_view(a) for a in w.canaries()],
                     "enqueued": len(w.fleet.calls), "owed": [od.restart_owed_canary(unknown, od.linked_restart(
                         w.lane_intent())), od.rearm_owed_canary(w.canaries()[0], w.lane_intent())]}
    return out


def recovery(api):
    return {"lab": lab_recovery(api), "chain_retry": chain_retry(api)}


def rearm(api):
    return {"grammar": rearm_grammar(api), "lab": rearmed_lab(api), "chain": chain_rearm(api)}


def run(api) -> dict:
    UNREACHABLE.clear()
    UNREACHABLE.update({
        "outcome_absent_through_advance": "`canary_outcome` answers `absent` only for a job that is not a mapping, and "
        "`_advance_canary` reads the job first: a missing job is the lost-admission branch (lost_admission), so the absent "
        "outcome is characterized through the pure domain function only (advance.domain.outcomes.absent)",
        "postgres_parameter": "the `postgres` parameter of the M7 `stores` fixture needs two isolated PostgreSQL schemas "
        "(HARNESS_INTEGRATION=1); every case here runs the memory parameter",
        "real_owner_and_real_lane_end_to_end": "test_the_real_owner_and_real_lane_recover_the_halted_canary_end_to_end needs a "
        "real process target, the real Fleet and `owner_qualified_canary`: chain_retry runs its lane and recovery steps over "
        "the s7_delivery doubles instead",
        "host_restart_end_to_end": "test_after_a_host_restart_the_real_owner_rebinds_the_same_canary_to_the_restarted_"
        "generation needs a real process target and the real Fleet: the re-binding is characterized at the store level "
        "(lab_recovery.rebound) over LABELLED restart and retry rows",
        "rearm_end_to_end": "test_after_the_retry_expires_again_the_same_canary_is_rearmed_once_and_the_delivery_is_consumed "
        "needs a real process target and the real Fleet: chain_rearm runs its lane and recovery steps over the s7_delivery "
        "doubles instead",
        "cli": "test_the_cli_drives_the_real_recovery_and_refuses_an_unreadable_document drives the real CLI (monkeypatched "
        "Fleet registration and coordinator factory): the CLI is not this family",
        "file_adapter": "test_an_unreadable_existing_canary_receipt_is_unknown_never_absent reads real files through "
        "TargetFiles and HostTargetBase (a host adapter test; `delivery.host_targets`)"})
    return {"advance": advance(api), "recovery": recovery(api), "rearm": rearm(api), "scheduler": {
        "ticks": scheduler(api), "owed_recovery": owed_recovery(api)}, "unreachable": UNREACHABLE}
