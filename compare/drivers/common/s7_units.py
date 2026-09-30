"""Shared S7 scenario steps (`effects.delivery_units`): the §2.9 transaction units of M7 `application/host_delivery.py`,
observed through the S0 recorder (DESIGN-s7 §2 row `effects.delivery_units` and §3 step 5; TRACE-s7 §5.2 and §5.5;
REBUILD-DESIGN-v2 §2.9), over the MemoryStore only.

Units (M7 names; the target's V8 split keeps each one whole):
- `verification_attempt` / `verification_verdict`: `_commit_verification`, the attempt record and the evaluation result
  recorded in one unit with the claim's fence and the intent compare-and-swap;
- `record_publish`, `record_merge`, `record_switch`: `_record(effect, write)`, a stage's external effect recorded by the
  ownership check (`_enter` -> `_write`, and for the switch also the descriptor unit `_record_descriptor`);
- `promote`: `_promote`, `releases.promote` joined to the stage's unit with the fence check;
- `stage_write`: the owned stage write `_enter` -> `_write` of a stage with no external effect;
- `consume_descriptor`: `_consume`'s two descriptor records (`startup_observed`, `consumed`);
- `record_superseded`: `_record_release`'s superseded branch, review's `releases` row written in the caller's unit.

Discriminators:
- **(a)** a failure injected at the unit's LAST write (`FaultStore`, armed by the double that runs just before the unit)
  leaves nothing of the unit;
- **(b)** a stale writer commits nothing: the claim's lease moved between the reads and the unit (`s7_stages.supersede`), or
  the intent (the `_commit_verification` compare-and-swap), the release, or the active pointer moved;
- **(c)** a same-key replay adds no authority write (and no second effect);
- **(d)** the external effect (`github.publish`, `github.merge`, `host.switch`, `host.start`, `verifier.evaluate`, the
  canary, `host.receipt`) is entered at transaction depth 0 (the `effects` list of every result).
The ambiguous-effect sites (`_commit_verification`, `_record`, `_promote`) also report `controller_stale_after_effect` and
the effect they name when the fence is moved between the effect and its record (`ambiguous_effects`).

Layer: harness (never shipped)

`api` supplies `backend(name)` (`.store`, `.rows()`, `.drop()`), `reset()`, `recording(store)` (the S0 RecordingStore) and
the S7 delivery API of `s7_delivery` (the reference's `s7_registry` API or the target composition's `api()`). The store of
every world is the recorded, fault-injectable `s6_units.FaultStore`; a second controller (the lease or intent mover) acts
on the backend's own store, outside the recorder. The compared results are the unit outcomes, the durable writes (bucket
and status), the recorder violations, the effect depths and the durable rows that changed, read back from the backend.
"""

from __future__ import annotations

import s6_units as U
import s7_delivery as D
import s7_stages as S


class Case(U.Case):
    """One fresh recorded, fault-injectable store (`s6_units.Case` without the S6 world shim) and the one-shot hooks the
    doubles fire after their effect."""

    def __init__(self, api):
        api.reset()
        self.api, self.backend = api, api.backend("memory")
        self.recording = api.recording(self.backend.store)
        self.recorder = self.recording.recorder
        self.store = U.FaultStore(self.recording)
        self.mark, self.before, self.hooks, self.moved = 0, {}, {}, None

    def arm(self, bucket):
        """One failure at the next put into `bucket`, at the point `name` (a hook) is reached."""
        return lambda: self.store.arm(bucket)

    def mover(self, fn):
        """A second controller acts (outside the recorder); what the delivery does next is what the result shows."""
        def move():
            fn()
            self.moved = len(self.recorder.events)
        return move

    def result(self, outcome, **extra):
        if self.moved is not None:
            events = self.recorder.events[self.moved:]
            extra["after_move"] = {
                "durable_writes": sorted({(e["bucket"], e["status"] or "")
                                          for e in self.recorder.durable_writes(self.moved)}),
                "writes": len([e for e in events if e["kind"] == "write"])}
        return super().result(outcome, **extra)


def watch(case, obj, method, name, *, effect=True):
    """Record `obj.method` as the external effect `name` (at the depth it is entered) and fire the one-shot hook
    `case.hooks[name]` AFTER it returns (the fence moved between the effect and its record)."""
    inner = getattr(obj, method)

    def wrapped(*args, **kwargs):
        if effect:
            case.recorder.effect(name)
        out = inner(*args, **kwargs)
        hook = case.hooks.pop(name, None)
        if hook is not None:
            hook()
        return out
    setattr(obj, method, wrapped)


class Canary:
    """LABELLED. The canary port with its call recorded as an external effect (`canary.startup`)."""

    def __init__(self, case, inner):
        self.case, self.inner = case, inner

    def __call__(self, target, descriptor, startup, **kwargs):
        self.case.recorder.effect("canary.startup")
        out = self.inner(target, descriptor, startup, **kwargs)
        hook = self.case.hooks.pop("canary.startup", None)
        if hook is not None:
            hook()
        return out


class World:
    """One wired delivery (`s7_delivery.build`) over the case's recorded store. `store` is the backend's own store: the
    other controller's access, and every read the result makes, is outside the recorder."""

    def __init__(self, case, *, receipt=False, **kwargs):
        api = case.api
        self.case, self.api, self.store = case, api, case.backend.store
        host = kwargs.pop("host", None) or D.MemoryHost(api)
        canaries = {api.CANARY_STARTUP: Canary(case, D.StartupCanary(host)), api.CANARY_FLEET: D.OwnerCanary(host)}
        self.system = D.build(api, store=case.store, host=host, canaries=canaries, **kwargs)
        self.delivery, self.github, self.host = self.system["delivery"], self.system["github"], host
        watch(case, self.github, "publish", "github.publish")
        watch(case, self.github, "merge", "github.merge")
        watch(case, self.github, "qualify", "github.qualify", effect=False)
        watch(case, host, "switch", "host.switch")
        watch(case, host, "start", "host.start")
        if receipt:
            watch(case, host, "receipt", "host.receipt")
        verifier = self.system["verifier"]
        if verifier is not None:
            watch(case, verifier, "new_attempt", "verifier.new_attempt", effect=False)
            watch(case, verifier, "evaluate", "verifier.evaluate")

    def release_id(self):
        return self.system["release"]["id"]

    def plan_id(self):
        return self.system["plan"]["plan_id"]

    def tick(self):
        out = U.attempt(self.delivery.tick)
        value = out.pop("value", None) or {}
        self.api.advance(1)
        return {**out, **{key: value.get(key) for key in S.TICK_KEYS if key in value}}

    def until(self, stage, limit=12):
        for _ in range(limit):
            result = self.tick()
            if result.get("stage") == stage or result.get("outcome") in {"blocked", "refused", "conflict"}:
                return result
        return result

    def steal(self):
        """The claim's lease moves to another controller (LABELLED, `s7_stages.supersede`)."""
        return self.case.mover(lambda: S.supersede(self))

    def bump(self):
        """Another controller rewrites the intent (a field no stage reads): the compare-and-swap probe."""
        def move():
            with self.store.transaction() as tx:
                intent = tx.get(D.BUCKET_INTENTS, self.plan_id())
                tx.put(D.BUCKET_INTENTS, intent["id"], {**intent, "updated_at": "moved-by-another-controller"})
        return self.case.mover(move)

    def put(self, bucket, key, fields):
        def move():
            with self.store.transaction() as tx:
                tx.put(bucket, key, {**(tx.get(bucket, key) or {}), **fields})
        return self.case.mover(move)

    def free(self):
        """A second controller finished: its lease is released, the row re-armed and the timeline moves past the
        queue's backoff (`s7_stages.reconcile`'s steps without the ticks)."""
        S.free_queue(self)
        self.api.advance(120)

    def wait(self, seconds=120):
        self.api.advance(seconds)

    def view(self):
        with self.store.transaction() as tx:
            intent = tx.get(D.BUCKET_INTENTS, self.plan_id()) or {}
            release = tx.get("releases", self.release_id()) or {}
            pointer = tx.get("deployment", "active") or {}
            descriptor = tx.get(D.BUCKET_DESCRIPTORS, "canary-service") or {}
            queue = tx.get("release_queue", self.release_id()) or {}
        return {"intent": {key: intent.get(key) for key in ("stage", "outcome", "reason_code", "attempts")},
                "attempts": [[a.get("state"), bool(a.get("outcome"))]
                             for a in (intent.get("verification") or {}).get("attempts", [])],
                "release": release.get("status"), "pointer": pointer.get("release_id"),
                "descriptor": {key: descriptor.get(key) for key in ("consumed", "startup_observed")},
                "queue": queue.get("status")}

    def done(self):
        D.stop_target(self.system)


def finish(case, world, outcome, **extra):
    out = case.result(outcome, **world.view(), **extra)
    world.done()
    return out


# ---- units 1a and 1b: _commit_verification (the attempt record, the verdict) --------------------------------------
def verification_world(case, **verifier):
    verifier = D.Verifier(case.api, **verifier)
    world = World(case, verified=False, verifier=verifier)
    world.tick()   # registered enters verifying
    return world


def verification_attempt(api, variant):
    case = Case(api)
    world = verification_world(case)
    case.since()
    if variant == "a_failure_at_intent":
        case.hooks["verifier.new_attempt"] = case.arm(D.BUCKET_INTENTS)
    elif variant == "b_lease_moved":
        case.hooks["verifier.new_attempt"] = world.steal()
    elif variant == "b_intent_moved":
        case.hooks["verifier.new_attempt"] = world.bump()
    return finish(case, world, world.tick())


def verification_verdict(api, variant):
    case = Case(api)
    unconfirmed = variant == "c_replay_cleanup_unconfirmed"
    world = verification_world(case, **({"outcome": S.UNCONFIRMED} if unconfirmed else {}))
    case.since()
    if variant == "a_failure_at_intent":
        case.hooks["verifier.evaluate"] = case.arm(D.BUCKET_INTENTS)
    elif variant == "b_lease_moved":
        case.hooks["verifier.evaluate"] = world.steal()
    elif variant == "b_intent_moved":
        case.hooks["verifier.evaluate"] = world.bump()
    out = world.tick()
    if unconfirmed:
        # the verdict is recorded and the stage waits for the cleanup; the same stage again evaluates nothing new
        case.since()
        return finish(case, world, world.tick(), first_tick=out)
    return finish(case, world, out)


# ---- units 2: _record(effect, write) at the publish, merge and switch sites -----------------------------------------
def record_publish(api, variant):
    case = Case(api)
    world = World(case)
    world.tick()   # registered enters publishing
    case.since()
    if variant == "a_failure_at_stage_write" or variant == "c_replay_after_failure":
        case.hooks["github.publish"] = case.arm(D.BUCKET_INTENTS)
    elif variant == "b_lease_moved":
        case.hooks["github.publish"] = world.steal()
    out = world.tick()
    if variant == "c_replay_after_failure":
        # the publication happened, its record did not: the next tick adopts it, publishing nothing again
        world.wait()
        case.since()
        return finish(case, world, world.tick(), first_tick=out, publishes=world.github.publishes)
    return finish(case, world, out, publishes=world.github.publishes)


def record_merge(api, variant):
    case = Case(api)
    world = World(case, github=D.FakeGitHub(api, fast_forward=True))
    world.until(api.MERGE_INTENDED, limit=4)
    case.since()
    if variant == "a_failure_at_stage_write" or variant == "c_replay_after_failure":
        case.hooks["github.qualify"] = case.arm(D.BUCKET_INTENTS)
    elif variant == "b_lease_moved":
        case.hooks["github.qualify"] = world.steal()
    out = world.tick()
    if variant == "c_replay_after_failure":
        world.wait()
        case.since()
        return finish(case, world, world.tick(), first_tick=out, merges=world.github.merges)
    return finish(case, world, out, merges=world.github.merges)


def record_switch(api, variant):
    case = Case(api)
    world = World(case)
    world.until(api.SWITCHING, limit=8)
    case.since()
    if variant == "a_failure_at_descriptor_record":
        case.hooks["host.start"] = case.arm(D.BUCKET_DESCRIPTORS)
    elif variant in ("a_failure_at_stage_write", "c_replay_after_failure"):
        case.hooks["host.start"] = case.arm(D.BUCKET_INTENTS)
    elif variant == "b_lease_moved":
        case.hooks["host.start"] = world.steal()
    out = world.tick()
    if variant == "c_replay_after_failure":
        # the descriptor unit committed and the service started, the stage write did not: the next tick recognizes both
        world.wait()
        case.since()
        return finish(case, world, world.tick(), first_tick=out, calls=list(world.host.calls))
    return finish(case, world, out, calls=list(world.host.calls))


# ---- unit 3: _promote -------------------------------------------------------------------------------------------------
def promote(api, variant):
    case = Case(api)
    world = World(case)
    world.until(api.AWAITING_CONSUMPTION, limit=8)
    case.since()
    emit = world.delivery._emit

    def racing(event_type, outcome, plan, **fields):
        emit(event_type, outcome, plan, **fields)
        if event_type == api.EVENT_SWITCHED and outcome == "succeeded":
            hook = case.hooks.pop("promote", None)
            if hook is not None:
                hook()
    world.delivery._emit = racing
    if variant == "a_failure_at_last_write":
        case.hooks["promote"] = case.arm("events")   # `releases.promote`'s last put
    elif variant == "b_lease_moved":
        case.hooks["promote"] = world.steal()
    elif variant == "b_pointer_moved":
        case.hooks["promote"] = world.put("deployment", "active", {"release_id": "release-other",
                                                                   "revision": "2" * 40})
    elif variant == "c_replay_after_stage_write_failure":
        case.hooks["promote"] = case.arm(D.BUCKET_INTENTS)   # the promotion commits, the ACTIVE stage write does not
    out = world.tick()
    if variant == "c_replay_after_stage_write_failure":
        world.wait()
        case.since()
        return finish(case, world, world.tick(), first_tick=out)
    return finish(case, world, out)


# ---- unit 4: the owned stage write (_enter -> _write) --------------------------------------------------------------
def stage_write(api, variant):
    """`registered -> publishing`: the stage write with no external effect. The tick creates the intent first (`_select`), so
    the failure and the stale claim are armed by a hook on the claim, after the intent exists."""
    case = Case(api)
    world = World(case)
    case.since()
    queue = world.delivery.queue
    claim = queue.claim

    def claimed(*args, **kwargs):
        out = claim(*args, **kwargs)
        hook = case.hooks.pop("queue.claim", None)
        if hook is not None:
            hook()
        return out
    queue.claim = claimed
    if variant in ("a_failure_at_stage_write", "c_replay_after_failure"):
        case.hooks["queue.claim"] = case.arm(D.BUCKET_INTENTS)
    elif variant == "b_lease_moved":
        case.hooks["queue.claim"] = world.steal()
    out = world.tick()
    if variant == "c_replay_after_failure":
        world.wait()
        case.since()
        return finish(case, world, world.tick(), first_tick=out)
    return finish(case, world, out)


# ---- unit 5: _consume's descriptor records ---------------------------------------------------------------------------
def consume_descriptor(api, variant):
    case = Case(api)
    world = World(case, receipt=True)
    world.until(api.AWAITING_CONSUMPTION, limit=8)
    case.since()
    if variant == "a_failure_at_startup_observed":
        case.store.arm(D.BUCKET_DESCRIPTORS)
    elif variant in ("a_failure_at_consumed", "c_replay_after_failure"):
        case.hooks["canary.startup"] = case.arm(D.BUCKET_DESCRIPTORS)   # the `consumed` record is the next descriptor put
    elif variant == "b_lease_moved_at_startup_observed":
        case.hooks["host.receipt"] = world.steal()
    elif variant == "b_lease_moved_at_consumed":
        case.hooks["canary.startup"] = world.steal()
    out = world.tick()
    if variant == "c_replay_after_failure":
        world.wait()
        case.since()
        return finish(case, world, world.tick(), first_tick=out)
    return finish(case, world, out)


# ---- unit 6: _record_release, the superseded branch -------------------------------------------------------------------
SUPERSEDED = {"verdict": "superseded", "reason": "ticket superseded", "passed": False, "image": None, "receipt": None,
              "state": "evaluated", "evaluation": "fixture-evaluation-receipt", "cleanup": {"state": "confirmed"},
              "checks": {}}


def record_superseded(api, variant):
    case = Case(api)
    world = verification_world(case, outcome=SUPERSEDED)
    case.since()
    if variant == "a_failure_at_last_write":
        case.hooks["verifier.evaluate"] = case.arm(D.BUCKET_INTENTS)   # after review's `releases` row
    elif variant == "b_lease_moved":
        case.hooks["verifier.evaluate"] = world.steal()
    elif variant == "b_intent_moved":
        case.hooks["verifier.evaluate"] = world.bump()
    elif variant == "b_release_moved":
        case.hooks["verifier.evaluate"] = world.put("releases", world.release_id(), {"status": "verified"})
    out = world.tick()
    if variant == "c_replay":
        case.since()
        return finish(case, world, world.tick(), first_tick=out)
    return finish(case, world, out)


# ---- the run -----------------------------------------------------------------------------------------------------------
def ambiguous(groups):
    """Every case whose fence moved between an effect and its record: the tick receipt that says so."""
    out = {}
    for unit, cases in groups.items():
        for variant, case in cases.items():
            tick = case["outcome"]
            if tick.get("reason_code") == "controller_stale_after_effect":
                out[unit + "." + variant] = {"outcome": tick.get("outcome"), "effect": tick.get("ambiguous_effect"),
                                             "controller": tick.get("controller")}
    return out


def run(api) -> dict:
    groups = {
        "verification_attempt": {v: verification_attempt(api, v) for v in (
            "success", "a_failure_at_intent", "b_lease_moved", "b_intent_moved")},
        "verification_verdict": {v: verification_verdict(api, v) for v in (
            "success", "a_failure_at_intent", "b_lease_moved", "b_intent_moved", "c_replay_cleanup_unconfirmed")},
        "record_publish": {v: record_publish(api, v) for v in (
            "success", "a_failure_at_stage_write", "b_lease_moved", "c_replay_after_failure")},
        "record_merge": {v: record_merge(api, v) for v in (
            "success", "a_failure_at_stage_write", "b_lease_moved", "c_replay_after_failure")},
        "record_switch": {v: record_switch(api, v) for v in (
            "success", "a_failure_at_descriptor_record", "a_failure_at_stage_write", "b_lease_moved",
            "c_replay_after_failure")},
        "promote": {v: promote(api, v) for v in (
            "success", "a_failure_at_last_write", "b_lease_moved", "b_pointer_moved",
            "c_replay_after_stage_write_failure")},
        "stage_write": {v: stage_write(api, v) for v in (
            "success", "a_failure_at_stage_write", "b_lease_moved", "c_replay_after_failure")},
        "consume_descriptor": {v: consume_descriptor(api, v) for v in (
            "success", "a_failure_at_startup_observed", "a_failure_at_consumed", "b_lease_moved_at_startup_observed",
            "b_lease_moved_at_consumed", "c_replay_after_failure")},
        "record_superseded": {v: record_superseded(api, v) for v in (
            "success", "a_failure_at_last_write", "b_lease_moved", "b_intent_moved", "b_release_moved", "c_replay")},
    }
    return {**groups, "ambiguous_effects": ambiguous(groups)}
