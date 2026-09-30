"""Shared S6 scenario steps (`coordination.continuation_routes`): the per-route effects of ONE observation and of each
intent's RESUME actions in M7 `Continuation` (DESIGN-s6 §7; TRACE-s6 §8), in the sequences of the M7 tests
(tests/test_continuation.py).

- **refusals.** `lane_evidence_missing`, `review_unproven`, `handoff_incomplete` and a scope refusal (`image_changed`):
  each is one REFUSED intent with its named owner and starts nothing.
- **recovery.** A job `unknown`, a pending termination marker on a rejection and a failed `exception:` operation:
  `recovery_required`, never retried, no successor.
- **successor.** A lead rejection (CORRECTION) through published -> admitted with the second tick idempotent; an
  `evidence_gate_refused` failure with a complete owner handoff (EVIDENCE_REPAIR); a refusing `validate`
  (`successor_manifest_refused`); `max_corrections=1` (`correction_budget_exhausted`, after a LABELLED completed
  research row resets the two-strike count); a second distinct rejection (RESEARCH, that family only).
- **conductor.** Dispatch, running owned launch, exited launch with a proof; a restart with a new conductor that never
  saw the launch (fence, `conductor_not_launched`); a running launch not owned (`conductor_owner_unknown`); a
  timeout with a proof (`conductor_timeout`); an exited launch with a still-running row; a start exception
  (`launch_unconfirmed`, reconciled under the same identity); `conductor=None`; an unclaimed row redispatched under
  new launch identities up to MAX_LAUNCHES.
- **delivery.** After a conductor acceptance, the `host_delivery_intents` rows of the policy target and the exact
  release: absent, `active`, `rolled_back`, `withdrawn`, foreign only, two exact rows.
- **authorize drift.** With an intent left INTENDED by a lane binding outage, the runtime image changes: the hold is
  written once and no effect happens; restoring the image clears the hold and the effect proceeds.

Layer: harness (never shipped)

`api` is the `s6_tick` API plus `ContractError` (a refusing `validate` fixture raises it). Every case builds a fresh
World from `s6_tick` (extended here only by subclassing). Fixture rows are LABELLED: lane rows of the shapes
`LaneEvidence.read` and `classify` consume, a conductor decision row, `host_delivery_intents` rows (the fields
`bind_delivery` reads) and, for the budget case only, one completed research intent row of the shape
`prior_failures` reads. The compared results are the tick/drain receipts, a compact intent projection, the final
records of both stores by body digest, the conductor calls and the lane reads.
"""

from __future__ import annotations

from s6_tick import (
    CANDIDATE,
    GOAL,
    Conductor,
    Lanes,
    World,
    call,
    cleanup_proof,
    launch_of,
    manifest,
    records,
)

FIELDS = ("route", "state", "reason_code", "next_owner", "family", "origin_job", "successor_job", "session_mode",
          "hold", "ownership", "delivery_plan", "delivery_binding", "decision", "predecessor_intent")


class RConductor(Conductor):
    """The s6_tick conductor fixture plus: a lost start response, a spawn that fails before any child, an unowned
    running launch, an exit without a decision row and a timeout with the guardian's proof."""

    def __init__(self, lane_store, pending=True):
        super().__init__(lane_store, pending=pending)
        self.owned, self.lost, self.raise_before = True, False, False

    def start(self, lane_id, job, launch, token):
        if self.raise_before:
            raise ConnectionError("spawn failed before any child (injected)")
        self.calls.append(job["id"])
        self.jobs[launch], self.tokens[launch] = job, token
        self.launches[launch] = "running"
        if not self.pending:
            self.finish(launch)
        if self.lost:
            raise TimeoutError("start response lost (injected)")
        return {"pid": 4242}

    def exit_undecided(self, launch):
        self.launches[launch] = "exited"

    def time_out(self, launch):
        self.launches[launch] = "timeout"

    def poll(self, lane_id, launch):
        state = self.launches.get(launch)
        if state == "running" and not self.owned:
            return {"state": "running", "owned": False, "exit_code": None}
        if state == "timeout":
            return {"state": "timeout", "owned": True, "exit_code": None, "cleanup_confirmed": True,
                    "proof": {**cleanup_proof(launch, self.tokens[launch]), "exit_code": None, "timed_out": True}}
        return super().poll(lane_id, launch)


class RLanes(Lanes):
    """The s6_tick lane port; `bind_down` makes every binding write fail (a lane store outage at the binding)."""

    def __init__(self, api, store):
        super().__init__(api, store)
        self.bind_down = False

    def __call__(self, lane_id):
        lane = super().__call__(lane_id)
        if self.bind_down:
            def down(document):
                raise ConnectionError("lane store outage before the binding (injected)")
            lane.bind = down
        return lane


class RWorld(World):
    """`World` with the routes' knobs: the conductor fixture (or None), the runtime image, a refusing validator and
    `max_corrections`."""

    def __init__(self, api, *, conductor=True, pending=True, max_corrections=3):
        self.image, self.validate = "zeus-worker:fixture", api.validate_manifest
        super().__init__(api, pending=pending)
        self.document = {**self.document, "max_corrections": max_corrections}
        self.conductor = RConductor(self.lane_store, pending=pending) if conductor else None
        self.lanes = RLanes(api, self.lane_store)
        self.controller = self.build()

    def runtime(self, lane_id):
        return {**super().runtime(lane_id), "image": self.image}

    def build(self):
        return self.api.Continuation(self.control, fleet=self.fleet, lanes=self.lanes, conductor=self.conductor,
                                     validate=self.validate, clock=self.clock)

    def state(self):
        state = super().state() if self.conductor is not None else {
            "control": records(self.control), "lane": records(self.lane_store),
            "conductor": {"calls": [], "running": []}, "reads": list(self.lanes.reads)}
        return state


# ---- labelled fixture rows ------------------------------------------------------------------------
def bare(world, op_id, status="rejected", path="docs/a.md"):
    """A finalized Fleet job with NO lane rows at all."""
    world.fleet.enqueue("a", manifest(world.api, op_id, path), GOAL, [])
    job = world.fleet.admit_one()["job"]
    assert job is not None and job["id"] == op_id, job
    world.fleet.finalize(job["id"], job["owner_token"], {"status": status, "reason_code": "lead_rejected",
                                                         "exit_code": 0, "owner_handoff": None, "calls": {}})
    return op_id


def lane_row(world, bucket, row_id, **changes):
    with world.lane_store.transaction() as tx:
        row = tx.get(bucket, row_id)
        tx.put(bucket, row_id, {**row, **changes})


def seal(world, job_id, status, reason_code=None):
    """Admit the queued job (a successor), finalize it and seed its lane rows as `World.terminal` does."""
    job = world.fleet.admit_one()["job"]
    assert job is not None and job["id"] == job_id, job
    code = reason_code or {"accepted": "accepted", "rejected": "lead_rejected"}.get(status, "operation_failed")
    world.fleet.finalize(job_id, job["owner_token"], {"status": status, "reason_code": code, "exit_code": 0,
                                                       "owner_handoff": None, "calls": {}})
    task_id, decision_id = "task-" + job_id, "dec-" + job_id
    with world.lane_store.transaction() as tx:
        tx.put("operations", job_id, {"id": job_id, "status": status, "reason_code": code, "task_id": task_id,
                                      "decision_id": decision_id, "correlation_id": "corr-" + job_id})
        tx.put("tasks", task_id, {"id": task_id, "status": "succeeded", "generation": 1, "attempt": 1,
                                  "result": {"candidate": dict(CANDIDATE)}})
        tx.put("decisions_pending", decision_id, {
            "id": decision_id, "actor": "lead:improvement", "phase": "review_lead", "status": "succeeded",
            "input": {"candidate": dict(CANDIDATE)},
            "result": {"accepted": status == "accepted", "execution_ref": "sha256:" + "8" * 64}})
    return job_id


def conductor_row(world, op_id, status, attempt):
    """A conductor decision row that exists but did not succeed (M7 test: a child exited with its row running)."""
    with world.lane_store.transaction() as tx:
        lead = tx.get("decisions_pending", tx.get("operations", op_id)["decision_id"])
        tx.put("decisions_pending", "cond-x", {"id": "cond-x", "actor": "conductor", "phase": "review_conductor",
                                               "status": status, "attempt": attempt,
                                               "message": {"what": {"details": {"decision_id": lead["id"]}}}})


def deliver(world, plan_id, release_id, stage, target="fleet-host", revision=CANDIDATE["revision"]):
    """A HostDelivery intent row of the fields `bind_delivery` reads (`domain.host_delivery.new_intent`)."""
    with world.lane_store.transaction() as tx:
        tx.put("host_delivery_intents", plan_id, {"id": plan_id, "plan_id": plan_id, "release_id": release_id,
                                                  "target_id": target, "revision": revision, "stage": stage,
                                                  "plan_sha256": "5" * 64, "updated_at": "t"})


# ---- projections ----------------------------------------------------------------------------------
def intents(world):
    with world.control.transaction() as tx:
        rows = tx.scan("continuation_intents")
    out = []
    for row in sorted(rows, key=lambda r: (str(r.get("created_at")), r["id"])):
        launch = row.get("launch") or {}
        out.append({"id": row["id"], **{k: row.get(k) for k in FIELDS},
                    "launch": {k: launch.get(k) for k in ("id", "sequence", "state", "exit_code", "error_type")}
                    if launch else None,
                    "version": row.get("version"), "history": [[e.get("state"), e.get("reason_code")]
                                                                 for e in row.get("history") or []]})
    return out


def jobs(world):
    with world.control.transaction() as tx:
        return sorted([[j["id"], j["status"], j["lane"]] for j in tx.scan("fleet_jobs")])


def bindings(world):
    with world.lane_store.transaction() as tx:
        rows = tx.scan("continuation_bindings")
    return sorted([{k: row.get(k) for k in ("operation_id", "intent_id", "family", "route", "session", "workspace",
                                            "predecessor")} for row in rows], key=lambda r: r["operation_id"])


def units(world):
    return world.fleet.units()


def snap(world):
    return {"intents": intents(world), "jobs": jobs(world), "bindings": bindings(world), "units": units(world),
            "state": world.state()}


def settled(world, times=2):
    """`times` further ticks: the receipts, and whether the records moved."""
    first = records(world.control), records(world.lane_store)
    receipts = [call(world.tick) for _ in range(times)]
    return {"receipts": receipts, "records_unchanged": first == (records(world.control), records(world.lane_store))}


# ---- 1. refusals ----------------------------------------------------------------------------------
def refusals(api) -> dict:
    out = {}
    world = RWorld(api)
    world.register()
    bare(world, "op-missing")
    out["lane_evidence_missing"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api)
    world.register()
    world.terminal("op-unproven", "rejected")
    lane_row(world, "decisions_pending", "dec-op-unproven", status="running")
    out["review_unproven"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api)
    world.register()
    world.terminal("op-handoff", "failed", reason_code="evidence_gate_refused")
    out["handoff_incomplete"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api)
    world.register()
    world.terminal("op-scope", "rejected")
    world.image = "other/image:1"
    out["scope_image_changed"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    return out


# ---- 2. recovery ----------------------------------------------------------------------------------
def recovery(api) -> dict:
    out = {}
    world = RWorld(api)
    world.register()
    world.terminal("op-unknown", "unknown")
    out["job_unknown"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api)
    world.register()
    world.terminal("op-marker", "rejected")
    with world.lane_store.transaction() as tx:
        tx.put("observation_terminations", "rec-1", {"record_id": "rec-1", "task_id": "task-op-marker",
                                                     "status": "pending_reconciliation"})
    out["pending_marker"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api)
    world.register()
    world.terminal("op-exception", "failed", reason_code="exception:RuntimeError")
    out["exception_reason"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    return out


# ---- 3. successor ---------------------------------------------------------------------------------
def rejected_family(world, root="op-x"):
    """A rejected root job, its correction successor admitted and the successor itself rejected (distinct evidence)."""
    world.register()
    world.terminal(root, "rejected")
    first = call(world.tick)
    successor = next(i["successor_job"] for i in intents(world) if i["route"] == "correction")
    seal(world, successor, "rejected")
    return first, successor


def successor(api) -> dict:
    out = {}
    world = RWorld(api)
    world.register()
    world.terminal("op-1", "rejected")
    first = call(world.tick)
    mid = snap(world)
    again = settled(world, 2)
    out["correction"] = {"first": first, "after_first": mid, "again": again, "snap": snap(world)}
    world = RWorld(api)
    world.register()
    world.terminal("op-repair", "failed", reason_code="evidence_gate_refused")
    with world.lane_store.transaction() as tx:
        operation = tx.get("operations", "op-repair")
        tx.put("operations", "op-repair", {
            "id": "op-repair", "status": "failed", "reason_code": "evidence_gate_refused",
            "correlation_id": operation["correlation_id"],
            "owner_handoff": {"id": "handoff-op-repair", "task_id": "task-op-repair",
                              "candidate": {"revision": CANDIDATE["revision"]}, "inspection": {"id": "insp-op-repair"}}})
    first = call(world.tick)
    out["evidence_repair"] = {"first": first, "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api)

    def refusing(document):
        raise api.ContractError("successor manifest refused (fixture validator)")
    world.validate, world.controller = refusing, None
    world.controller = world.build()
    world.register()
    world.terminal("op-refused", "rejected")
    out["successor_manifest_refused"] = {"first": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    # max_corrections=1: one correction already charged, the two-strike count reset by a completed research intent
    # (LABELLED row; the M7 test reaches the same state through an owner receipt), then a further rejection.
    world = RWorld(api, max_corrections=1)
    world.register()
    world.terminal("op-b", "rejected")
    first = call(world.tick)
    child = next(i["successor_job"] for i in intents(world) if i["route"] == "correction")
    seal(world, child, "rejected")
    origin = next(i for i in intents(world) if i["route"] == "correction")
    with world.control.transaction() as tx:
        tx.put("continuation_intents", "research-seeded", {
            "id": "research-seeded", "policy_id": "policy-1", "origin_job": child, "family": origin["family"],
            "route": "research", "state": "completed", "reason_code": "research_receipt_accepted",
            "evidence_sha256": "1" * 64, "successor_job": None, "job_updated_at": None, "version": 1,
            "created_at": world.clock(), "updated_at": world.clock(), "history": [{"state": "completed"}]})
    budget = call(world.tick)
    out["correction_budget_exhausted"] = {"first": first, "budget": budget, "again": settled(world, 1),
                                          "snap": snap(world)}
    # Two-strike: the successor is rejected as a second distinct failure of the family; another family is served.
    world = RWorld(api)
    first, child = rejected_family(world)
    world.terminal("op-y", "rejected", path="docs/b.md")
    second = call(world.tick)
    held = call(world.controller.status, "policy-1")
    out["research"] = {"first": first, "second": second, "held": (held.get("value") or {}).get("held_families"),
                       "again": settled(world, 2), "snap": snap(world)}
    return out


# ---- 4. conductor ---------------------------------------------------------------------------------
def accepted(world, op_id="op-a"):
    world.register()
    world.terminal(op_id, "accepted")
    return op_id


def conductor(api) -> dict:
    out = {}
    world = RWorld(api)
    accepted(world)
    dispatched = call(world.tick)
    launch = launch_of(world, "op-a")
    running = call(world.tick)
    world.conductor.finish(launch)
    exited = call(world.tick)
    out["dispatch_running_exited"] = {"dispatched": dispatched, "running": running, "exited": exited,
                                      "after": settled(world, 1), "snap": snap(world)}
    # A restart with a NEW conductor that never saw the launch: absent with the fence.
    world = RWorld(api)
    accepted(world)
    dispatched = call(world.tick)
    world.conductor = RConductor(world.lane_store)
    world.controller = world.build()
    fenced = call(world.tick)
    mid = snap(world)
    out["restart_new_conductor"] = {"dispatched": dispatched, "fenced": fenced, "after_fence": mid,
                                    "redispatch": call(world.tick), "snap": snap(world)}
    world = RWorld(api)
    accepted(world)
    dispatched = call(world.tick)
    world.conductor.owned = False
    first = call(world.tick)
    out["running_not_owned"] = {"dispatched": dispatched, "first": first, "again": settled(world, 1),
                                "unresolved": call(world.controller.unresolved, "policy-1"), "snap": snap(world)}
    world = RWorld(api)
    accepted(world)
    dispatched = call(world.tick)
    conductor_row(world, "op-a", "running", 1)
    world.conductor.time_out(launch_of(world, "op-a"))
    out["timeout_with_proof"] = {"dispatched": dispatched, "timeout": call(world.tick),
                                 "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api)
    accepted(world)
    dispatched = call(world.tick)
    conductor_row(world, "op-a", "running", 1)
    world.conductor.exit_undecided(launch_of(world, "op-a"))
    out["exited_with_running_row"] = {"dispatched": dispatched, "exit": call(world.tick),
                                      "again": settled(world, 1), "snap": snap(world)}
    world = RWorld(api, pending=False)
    world.conductor.lost = True
    accepted(world)
    unconfirmed = call(world.tick)
    out["start_lost_child_decided"] = {"unconfirmed": unconfirmed, "mid": snap(world), "after": settled(world, 2),
                                       "snap": snap(world)}
    world = RWorld(api)
    world.conductor.raise_before = True
    accepted(world)
    unconfirmed = call(world.tick)
    world.conductor.raise_before = False
    out["start_failed_no_child"] = {"unconfirmed": unconfirmed, "mid": snap(world), "absent": call(world.tick),
                                    "redispatch": call(world.tick), "snap": snap(world)}
    world = RWorld(api, conductor=False)
    accepted(world)
    out["conductor_none"] = {"first": call(world.tick), "again": settled(world, 2), "snap": snap(world)}
    world = RWorld(api)
    accepted(world)
    steps = []
    for _ in range(3 + 2):
        steps.append(call(world.tick))
        for launch, state in sorted(world.conductor.launches.items()):
            if state == "running":
                world.conductor.exit_undecided(launch)
        steps.append(call(world.tick))
    out["unclaimed_exhausted"] = {"steps": steps, "launches": len(world.conductor.launches), "snap": snap(world)}
    return out


# ---- 5. delivery ----------------------------------------------------------------------------------
def delivering(api):
    world = RWorld(api, pending=False)
    accepted(world)
    call(world.tick)
    second = call(world.tick)
    return world, "rel-op-a", second


def delivery(api) -> dict:
    out = {}
    world, release, second = delivering(api)
    out["awaiting"] = {"second": second, "wait": settled(world, 1), "snap": snap(world)}
    world, release, _ = delivering(api)
    deliver(world, "plan-1", release, "active")
    out["active"] = {"tick": call(world.tick), "again": settled(world, 2), "snap": snap(world)}
    world, release, _ = delivering(api)
    deliver(world, "plan-1", release, "rolled_back")
    out["rolled_back"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world, release, _ = delivering(api)
    deliver(world, "plan-1", release, "withdrawn")
    out["withdrawn"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world, release, _ = delivering(api)
    deliver(world, "plan-other", release, "active", target="other-host")
    out["foreign_only"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    world, release, _ = delivering(api)
    deliver(world, "plan-1", release, "active")
    deliver(world, "plan-2", release, "rolled_back")
    out["ambiguous"] = {"tick": call(world.tick), "again": settled(world, 1), "snap": snap(world)}
    return out


# ---- 6. authorize drift ---------------------------------------------------------------------------
def authorize_drift(api) -> dict:
    world = RWorld(api)
    world.register()
    world.terminal("op-1", "rejected")
    world.lanes.bind_down = True
    outage = call(world.tick)
    intended = snap(world)
    world.lanes.bind_down = False
    world.image = "other/image:1"
    world.controller = world.build()
    held = call(world.tick)
    mid = snap(world)
    again = settled(world, 1)
    world.image = "zeus-worker:fixture"
    cleared = call(world.tick)
    return {"outage": outage, "intended": intended, "held": held, "held_snap": mid, "held_again": again,
            "cleared": cleared, "snap": snap(world)}


def run(api) -> dict:
    return {"refusals": refusals(api), "recovery": recovery(api), "successor": successor(api),
            "conductor": conductor(api), "delivery": delivery(api), "authorize_drift": authorize_drift(api)}
