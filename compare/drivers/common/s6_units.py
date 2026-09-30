"""Shared S6 scenario steps (`effects.continuation_units`): the §2.9 transaction units of the continuation and
owner-action coordinators, observed through the S0 recorder (DESIGN-s6 §3 "The §2.9 units" and §7; REBUILD-DESIGN-v2
§2.9), over the MemoryStore only.

Units: `Continuation._publish` (the admitted-confirmation read, the Portfolio inheritance and the move to ADMITTED in one
control-store unit after `fleet.enqueue`), `Continuation._dispatch` (the Fleet `reserve_unit(... within=)` unit that
moves the intent to DISPATCHED with the unit token, before `conductor.start`), `Continuation._settle` (the Fleet
`settle_unit(... within=)` unit that releases the unit and moves the intent), `Continuation._commit_requalification`
(the requalifications row, the superseded intent and the new intent), `Continuation.accept_research` (the receipt row),
`Continuation.grant_capacity` (the grant row and the intent) and `OwnerActions._begin_assessment` (the action move and
the `decisions_pending` assessor row, before `assessments.start`). Discriminators:
- **(a)** a failure injected at the unit's LAST write (`FaultStore`) leaves nothing of the unit;
- **(b)** a stale writer commits nothing: the intent/action version moved by another writer between the reads and the
  unit, or the Fleet unit already settled;
- **(c)** a same-key replay adds no authority write;
- **(d)** the external effect (`fleet.enqueue`, `conductor.start`, `assessments.start`) is entered at depth 0.

Layer: harness (never shipped)

`api` supplies `backend(name)` (`.store`, `.rows()`, `.drop()`), `reset()`, `recording(store)` (the S0 RecordingStore),
`MemoryStore`, and the S6 entries of the worlds it reuses (`Fleet`, `LaneEvidence`, `Continuation(..., evidence=)`,
`OwnerActions`, `organization`, `validate_manifest`, `repository_identity`, `canonical`, `domain`, `owner_domain`). The
control store of every world is the recorded, fault-injectable store (the worlds build it through `api.MemoryStore`);
the lane store and the labelled doubles are the ones of the reused S6 worlds. The compared results are the unit
outcomes, the durable writes (bucket and status), the recorder violations, the effect depths and the durable rows that
changed, read back from the backend.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import s6_owner_actions_research as OA
import s6_owner_paths as OP
import s6_research as R
from s6_tick import Conductor, World


class Injected(RuntimeError):
    pass


class FaultTransaction:
    def __init__(self, inner, plan):
        self._inner, self._plan = inner, plan

    def put(self, bucket, key, body):
        plan = self._plan
        if plan.get("armed") and plan.get("bucket") == bucket and (
                plan.get("state") is None or (isinstance(body, dict) and body.get("state") == plan["state"])):
            plan["armed"] = False
            raise Injected("injected failure at " + bucket)
        return self._inner.put(bucket, key, body)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class FaultStore:
    """Arms one failure at the next put into `plan["bucket"]` (whose body has `state`, when named); everything else
    passes through."""

    def __init__(self, inner):
        self._inner, self.plan = inner, {}

    def arm(self, bucket, state=None):
        self.plan = {"bucket": bucket, "state": state, "armed": True}

    def disarm(self):
        self.plan = {}

    def transaction(self, *args, **kwargs):
        store = self

        class Unit:
            def __enter__(self):
                self._context = store._inner.transaction(*args, **kwargs)
                return FaultTransaction(self._context.__enter__(), store.plan)

            def __exit__(self, *exc):
                return self._context.__exit__(*exc)
        return Unit()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def attempt(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None),
                "message": str(exc)[:160]}
    return {"ok": True, "value": value}


class Case:
    """One fresh recorded, fault-injectable control store, and the `api` shim that hands it to the reused S6 worlds
    (they build the control store first and the lane store second, both through `api.MemoryStore`)."""

    def __init__(self, api):
        api.reset()
        self.api, self.backend = api, api.backend("memory")
        self.recording = api.recording(self.backend.store)
        self.recorder = self.recording.recorder
        self.store = FaultStore(self.recording)
        stores = iter([self.store, api.MemoryStore()])
        self.shim = SimpleNamespace(**vars(api))
        self.shim.MemoryStore = lambda: next(stores)
        self.mark, self.before = 0, {}

    def since(self):
        self.mark = len(self.recorder.events)
        self.before = {(b, k): d for b, k, _, d in self.backend.rows()}

    def result(self, outcome, **extra):
        recorder = self.recorder
        events = recorder.events[self.mark:]
        outcomes = recorder.unit_outcomes()
        units = [outcomes.get(u, "OPEN") for u in sorted({e["unit"] for e in events if e["kind"] == "BEGIN"},
                                                         key=lambda u: int(u[1:]))]
        durable = recorder.durable_writes(self.mark)
        commit_at = {e["unit"]: e["seq"] for e in events if e["kind"] == "COMMIT"}
        writes = [e for e in events if e["kind"] == "write"]
        rows = self.backend.rows()
        out = {"outcome": outcome,
               "units": {kind: units.count(kind) for kind in ("COMMIT", "ROLLBACK", "OPEN") if units.count(kind)},
               "durable_writes": sorted({(e["bucket"], e["status"] or "") for e in durable}),
               "durable_units": len({e["unit"] for e in durable}),
               "discarded_writes": sorted({(e["bucket"], e["status"] or "") for e in writes
                                           if outcomes.get(e["unit"]) == "ROLLBACK"}),
               "violations": sorted({v["kind"] for v in recorder.violations}),
               "effects": [[e["name"], e["depth"]] for e in events if e["kind"] == "effect"],
               # what was already committed when each effect was entered (the write-ahead record)
               "committed_before_effect": [
                   [e["name"], sorted({(w["bucket"], w["status"] or "") for w in writes
                                       if commit_at.get(w["unit"], 1 << 60) < e["seq"]})]
                   for e in events if e["kind"] == "effect"],
               "rows_changed": [[b, k, status] for b, k, status, d in rows if self.before.get((b, k)) != d],
               "rows_before": len(self.before), "rows_after": len(rows), **extra}
        self.backend.drop()
        return json.loads(json.dumps(out))


# ---- the tick worlds (s6_tick.World over the recorded control store) ---------------------------------------
class EffectFleet:
    """The Fleet with each external effect recorded at the depth it is entered; `hooks` name one-shot callables run
    around a call (a second writer moving the intent between the reads and the unit)."""

    def __init__(self, inner, recorder):
        self._inner, self._recorder, self.hooks = inner, recorder, {}

    def _hook(self, name):
        hook = self.hooks.pop(name, None)
        if hook is not None:
            hook()

    def enqueue(self, *args, **kwargs):
        self._recorder.effect("fleet.enqueue")
        out = self._inner.enqueue(*args, **kwargs)
        self._hook("after_enqueue")
        return out

    def reserve_unit(self, *args, **kwargs):
        self._hook("before_reserve")
        return self._inner.reserve_unit(*args, **kwargs)

    def settle_unit(self, *args, **kwargs):
        self._hook("before_settle")
        return self._inner.settle_unit(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class RecordedConductor(Conductor):
    def __init__(self, lane_store, recorder, pending=True):
        super().__init__(lane_store, pending=pending)
        self.recorder = recorder

    def start(self, lane_id, job, launch, token):
        self.recorder.effect("conductor.start")
        return super().start(lane_id, job, launch, token)


def tick_world(case, *, pending=True):
    world = World(case.shim, pending=pending)
    world.fleet = EffectFleet(world.fleet, case.recorder)
    world.conductor = RecordedConductor(world.lane_store, case.recorder, pending=pending)
    world.controller = world.build()
    return world


def intents_of(world):
    with world.control.transaction() as tx:
        return {row["id"]: row for row in tx.scan("continuation_intents")}


def bump(world, intent):
    """A second controller moves the intent's version (a note with no field): the stale-writer probe."""
    world.build()._note(intent)


def brief(world):
    return sorted([r["route"], r["state"], r.get("version"), r.get("reason_code")]
                  for r in intents_of(world).values())


def only_intent(world, **match):
    found = [r for r in intents_of(world).values() if all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, found
    return found[0]


def unit_states(world):
    return sorted([u["kind"], u["state"]] for u in world.fleet.units())


def tick(world):
    """The tick receipt, without the fields every case shares."""
    out = attempt(world.tick)
    value = out.pop("value", None) or {}
    return {**out, "outcome": value.get("outcome"), "actions": value.get("actions"), "skipped": value.get("skipped")}


# ---- unit 1: Continuation._publish -----------------------------------------------------------------------------
def publish(api, variant):
    case = Case(api)
    world = tick_world(case)
    world.register()
    world.terminal("op-a", "rejected")
    if variant in ("c_replay_after_failure",):
        case.store.arm("continuation_intents", "admitted")
        tick(world)   # the enqueue happened, the unit failed at its last write: `published` stays
        case.store.disarm()
    case.since()
    if variant == "a_failure_at_admitted":
        case.store.arm("continuation_intents", "admitted")
    elif variant == "b_intent_moved":
        # after fleet.enqueue, before the admitted-confirmation unit: another controller moves the intent
        world.fleet.hooks["after_enqueue"] = lambda: bump(world, only_intent(world, route="correction"))
    elif variant == "c_again_after_success":
        tick(world)
        case.since()
    return case.result(tick(world), intents=brief(world))


# ---- units 2 and 3: Continuation._dispatch and _settle ---------------------------------------------------------
def dispatched_world(case):
    world = tick_world(case)
    world.register()
    world.terminal("op-a", "accepted")
    return world


def dispatch(api, variant):
    case = Case(api)
    world = dispatched_world(case)
    case.since()
    if variant == "a_failure_at_unit_reservation":
        case.store.arm("fleet_units", "reserved")
    elif variant == "b_intent_moved":
        # before the Fleet reservation unit: another controller moves the intent
        world.fleet.hooks["before_reserve"] = lambda: bump(world, only_intent(world))
    out = tick(world)
    extra = {"intents": brief(world), "fleet_units": unit_states(world),
             "conductor_calls": list(world.conductor.calls)}
    if variant == "c_reserve_replay":
        # the same unit id again (a lost response): the reservation replays cached, nothing is written
        intent = only_intent(world)
        case.since()
        replay = attempt(world.fleet.reserve_unit, intent["launch"]["id"], "conductor", intent["lane"], intent["id"])
        return case.result({**replay, "value": {"cached": (replay.get("value") or {}).get("cached")}},
                           first_tick=out, **extra)
    return case.result(out, **extra)


def settle(api, variant):
    case = Case(api)
    world = dispatched_world(case)
    tick(world)
    launch = next(iter(world.conductor.launches))
    intent = only_intent(world)
    world.conductor.finish(launch)
    case.since()
    if variant == "a_failure_at_unit_release":
        case.store.arm("fleet_units", "released")
    elif variant == "b_intent_moved":
        world.fleet.hooks["before_settle"] = lambda: bump(world, only_intent(world))
    elif variant == "b_unit_already_settled":
        # another writer already released the unit on the same proof: the intent's unit refuses to commit again
        proof = world.conductor.poll("a", launch)["proof"]
        world.fleet.hooks["before_settle"] = lambda: world.fleet._inner.settle_unit(launch, intent["launch"]["token"],
                                                                                    proof)
    out = tick(world)
    extra = {"intents": brief(world), "fleet_units": unit_states(world)}
    if variant == "c_settle_replay":
        proof = world.conductor.poll("a", launch)["proof"]
        case.since()
        replay = attempt(world.fleet.settle_unit, launch, intent["launch"]["token"], proof)
        return case.result({**replay, "value": {"cached": (replay.get("value") or {}).get("cached")}},
                           first_tick=out, **extra)
    return case.result(out, **extra)


# ---- unit 4: Continuation._commit_requalification -----------------------------------------------------------------
def requalification(api, variant):
    case = Case(api)
    world, delivery, rationale = OP.withdrawn_world(case.shim)
    doc = OP.document(delivery, rationale)
    mainline = None
    if variant == "c_replay":
        assert "ok" in attempt(OP.requalify, world, doc)
    if variant == "b_intent_moved":
        class Racing(OP.Mainline):
            def remote_main(self):   # another controller moves the intent between the reads and the unit
                bump(world, OP.only(world, id=delivery["id"]))
                return super().remote_main()
        mainline = Racing()
    case.since()
    if variant == "a_failure_at_new_intent":
        case.store.arm("continuation_intents", "intended")
    out = attempt(OP.requalify, world, doc, mainline)
    value = out.pop("value", None) or {}
    out["cached"] = value.get("cached")
    return case.result(out, intents=brief(world), requalifications=sorted(
        r["id"] for r in _scan(world, "continuation_requalifications")))


def _scan(world, bucket):
    with world.control.transaction() as tx:
        return tx.scan(bucket)


# ---- units 5 and 6: Continuation.accept_research and grant_capacity -------------------------------------------------
def first_verify(world, hook):
    """Run `hook` once, at the first evidence verification (after the reads, before the unit)."""
    inner = world.evidence.verify
    state = {"armed": True}

    def verify(ref):
        if state["armed"]:
            state["armed"] = False
            hook()
        return inner(ref)
    world.evidence.verify = verify


def receipt(api, variant):
    case = Case(api)
    world = R.load(case.shim, "held")
    document = R.receipt_for(world)
    if variant == "c_replay":
        assert "ok" in attempt(world.controller.accept_research, document)
    case.since()
    if variant == "a_failure_at_receipt_row":
        case.store.arm(R.RECEIPTS)
    elif variant == "b_intent_moved":
        first_verify(world, lambda: bump(world, R.research_of(world)))
    out = attempt(world.controller.accept_research, document)
    value = out.pop("value", None) or {}
    out["cached"] = value.get("cached")
    return case.result(out, receipts=sorted(R.scan(world.control, R.RECEIPTS)),
                       research_intent=R.research_of(world)["state"])


def capacity(api, variant):
    case = Case(api)
    world = R.load(case.shim, "budget_refused")
    document = R.grant_for(world)
    if variant == "c_replay":
        assert "ok" in attempt(R.grant, world, document)
    case.since()
    if variant == "a_failure_at_intent":
        case.store.arm("continuation_intents", "intended")
    elif variant == "b_intent_moved":
        first_verify(world, lambda: bump(world, R.intents(world)[world.ids["refused_intent"]]))
    out = attempt(R.grant, world, document)
    value = out.pop("value", None) or {}
    out["cached"] = value.get("cached")
    return case.result(out, grants=sorted(R.scan(world.control, R.GRANTS)),
                       refused_intent=R.intents(world)[world.ids["refused_intent"]]["state"])


# ---- unit 7: OwnerActions._begin_assessment ------------------------------------------------------------------------
def assessment(api, variant):
    case = Case(api)
    world = OA.load(case.shim, "held")
    owner = OA.registered(world)
    start = world.assessor.start

    def recorded_start(*args):
        case.recorder.effect("assessments.start")
        return start(*args)
    world.assessor.start = recorded_start
    if variant == "c_replay_after_failure":
        case.store.arm(OA.ACTIONS, "assessing")
        owner.tick("owners-1")   # the action was created; the unit failed at its last write
        case.store.disarm()
    case.since()
    if variant == "a_failure_at_action_move":
        case.store.arm(OA.ACTIONS, "assessing")
    elif variant == "b_action_moved":
        context = world.assessor.context

        def moved(binding, found):
            # another writer moves the action between the reads and the unit
            action = OA.only_action(world)
            with world.control.transaction() as tx:
                tx.put(OA.ACTIONS, action["id"], {**action, "version": action["version"] + 1})
            return context(binding, found)
        world.assessor.context = moved
    out = attempt(owner.tick, "owners-1")
    if variant == "c_again_after_success":
        case.since()
        out = attempt(owner.tick, "owners-1")
    return case.result(out, actions=[OA.brief(r) for r in OA.owner_rows(world)],
                       decisions=[[d["id"], d["status"]] for d in OA.decisions(world)],
                       starts=world.assessor.seen()["starts"])


def run(api) -> dict:
    return {
        "publish": {v: publish(api, v) for v in ("success", "a_failure_at_admitted", "b_intent_moved",
                                                 "c_replay_after_failure", "c_again_after_success")},
        "dispatch": {v: dispatch(api, v) for v in ("success", "a_failure_at_unit_reservation", "b_intent_moved",
                                                   "c_reserve_replay")},
        "settle": {v: settle(api, v) for v in ("success", "a_failure_at_unit_release", "b_intent_moved",
                                               "b_unit_already_settled", "c_settle_replay")},
        "requalification": {v: requalification(api, v) for v in ("success", "a_failure_at_new_intent",
                                                                 "b_intent_moved", "c_replay")},
        "accept_research": {v: receipt(api, v) for v in ("success", "a_failure_at_receipt_row", "b_intent_moved",
                                                         "c_replay")},
        "grant_capacity": {v: capacity(api, v) for v in ("success", "a_failure_at_intent", "b_intent_moved",
                                                         "c_replay")},
        "begin_assessment": {v: assessment(api, v) for v in ("success", "a_failure_at_action_move", "b_action_moved",
                                                             "c_replay_after_failure", "c_again_after_success")},
    }
