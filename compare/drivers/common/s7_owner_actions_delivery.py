"""Shared S7 scenario steps (`coordination.owner_actions_delivery`): the delivery-plan and requalify families of M7
`OwnerActions` (`application/owner_actions.py`) over the REAL M7 `HostDelivery` of a lane store, in the sequences of the M7
tests (DESIGN-s7 §2 row `coordination.owner_actions_delivery`, §3 step 4; the S6 carry of DESIGN-s6 §14).

Groups (each labelled in the result; the M7 test each case mirrors is named at its function):

1. **g2** (`tests/test_owner_actions_first_activation.py`): the domain plan builder (a first-activation tuple against an
   upgrade's `unchanged`, every malformed fact, the provenance-only image source revision), the ordinary discovery callsite
   (publish, pinned read, registration on the lane's HostDelivery, the tuple resolved once), an upgrade never consulting the
   first-activation port, the missing/failing/malformed port as a named wait writing nothing, a recovered port, a recorded
   intended row without bound facts refused before publication, and the migration successor of a first activation, of an
   upgrade and of an unbound port waiting staged.
2. **c1** (`tests/test_owner_actions_recovery.py`, memory store only): a blocked `reviewed_base_moved` plan withdrawn once
   and requalified once (with the restart at every persisted state), main moving between the persisted document and the
   call, a changed goal, an unobservable GitHub, the family cap, the same blocked plan one action for restarts and second
   coordinators, another block reason and a touched host, a lane without the target row, a version 1 policy and the strict
   version 2 blocks.
3. **scheduler**: the delivery families discovered and advanced by `OwnerActions.tick` next to an idle research family, and
   `status` projecting them.

Layer: harness (never shipped). This module never imports `codex_harness`: everything from the product arrives through
`api`, the object a reference (later a target) driver builds: the `s7_delivery` API plus `OwnerActions(store, **ports)`,
`Continuation`, `validate_manifest`, `repository_identity`, `owner_domain` (the M7 `domain.owner_actions` names), `dc` (the M7
`domain.continuation` names), `UNCHANGED`, `WITHDRAWN`, `migration_lineage_digest`, `migration_request_id`, `new_intent` and
`digest`.

**Doubles** (each docstring names its source; none runs Git, a process, a host, GitHub or a model):
`Publisher` (M7 `adapters/owner_actions.GitPlanPublisher` in the shapes of the M7 test double), `Targets` (`TargetFiles`,
plan-scoped canary requests), `Port` (the first-activation port), `Withdrawals` (the lane's withdraw port, the REAL lane
HostDelivery behind labelled loss faults), `Mainline` (`LaneMainline`), `Requalify` (`Continuation.requalify_delivery`'s
return shapes and its two effects on the control store) and the trusted artifact store of `s6_owner_actions_research`. The
continuation policy is the REAL `Continuation` policy row of `s6_tick.policy_document`. The rows written by hand are LABELLED
fixtures of the M7 tests: the conducted delivery intent and the lane descriptor row.

The compared results are the tick receipts, the owner-action rows, what each double saw, the lane rows the registration
wrote, and the digests of both stores. The PostgreSQL, CLI and real-process/real-git tests are out of scope.
"""

from __future__ import annotations

import copy
import hashlib
import json

import s6_tick as T
import s7_delivery as D
import s7_migration as M
from s6_owner_actions_research import Artifacts
from s6_owner_paths import Evidence

NOW = "2026-09-26T00:00:00+00:00"
TARGET = "fleet-host"
PIN = {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"}
# LABELLED fake first-activation facts (M7 `tests/test_owner_actions_migration.py::FIRST_ACTIVATION`).
FIRST_ACTIVATION = {"worker_image": "sha256:" + "9" * 64, "profile_digest": "c" * 64, "image_source_revision": "a" * 40}
CONCRETE = {"worker_image": FIRST_ACTIVATION["worker_image"], "profile_digest": FIRST_ACTIVATION["profile_digest"]}
# LABELLED current descriptor (M7 `tests/test_owner_actions_first_activation.py::DESCRIPTOR`).
DESCRIPTOR = {"schema": "labelled", "target_id": TARGET, "revision": "1" * 40, "worker_image": "sha256:" + "2" * 64,
              "profile_digest": "3" * 64}
CANARY = {"lane": "a", "manifest": {}, "goal": {"path": "docs/c.md", "sha256": "a" * 64, "criterion": "labelled",
                                                "base_revision": "b" * 40, "bytes": 0}}
GOAL_SHA = "b" * 64            # the goal blob digest at every revision unless a case changes it
MOVED = "8" * 40               # another writer's commit on main (labelled)
ACTIONS, POLICIES, INTENTS = "owner_actions", "owner_action_policies", "continuation_intents"
MIGRATIONS = "owner_action_migrations"
UNREACHABLE = {}


def call(fn, *args, **kwargs):
    return D.call(fn, *args, **kwargs)


def rows(store, bucket):
    with store.transaction() as tx:
        return {row["id"]: row for row in tx.scan(bucket)}


# ---- labelled doubles ---------------------------------------------------------------------------------------
class Log(list):
    """The ordered record of every effect a double saw (publish, request, register)."""


class Publisher:
    """LABELLED. M7 `adapters/owner_actions.GitPlanPublisher` in the shapes of `tests/test_owner_actions_migration.py::
    FakePublisher`: `publish(data, path, ref, when)` creates `ref` at the content-addressed commit only when absent,
    recognizes its own and never moves another (`{"revision", "conflict"}`); `load(revision, path)` answers
    `{"plan", "pin": {"revision", "path", "sha256"}}`. `lose` loses one publish response AFTER the effect."""

    def __init__(self, log):
        self.refs, self.commits, self.log, self.lose, self.calls = {}, {}, log, False, []

    def publish(self, data, path, ref, when):
        self.calls.append(("publish", ref))
        revision = hashlib.sha1(path.encode() + b"\0" + data + b"\0" + when.encode()).hexdigest()
        existing = self.refs.get(ref)
        if existing is None:
            self.log.append(("publish", ref))
            self.refs[ref] = existing = revision
        self.commits[revision] = (path, data)
        if self.lose:
            self.lose = False
            raise TimeoutError("publish response lost (labelled injected fault)")
        return {"revision": revision, "conflict": existing != revision}

    def load(self, revision, path):
        self.calls.append(("load", revision))
        stored_path, data = self.commits[revision]
        assert stored_path == path
        return {"plan": json.loads(data), "pin": {"revision": revision, "path": path,
                                                  "sha256": hashlib.sha256(data).hexdigest()}}


class Targets:
    """LABELLED. M7 `adapters/owner_actions.TargetFiles` over the M7 test double: plan-scoped canary requests."""

    def __init__(self, log):
        self.requests, self.log = {}, log

    def request(self, target, plan_id):
        return copy.deepcopy(self.requests.get(plan_id))

    def write_request(self, target, plan_id, document):
        self.log.append(("request", plan_id))
        self.requests[plan_id] = copy.deepcopy(document)

    def startup(self, target):
        return None


class Port:
    """LABELLED first-activation port (M7 `tests/test_owner_actions_first_activation.py::Port`): records each
    consultation; answers `facts`, or raises `error`."""

    def __init__(self, facts=FIRST_ACTIVATION, error=None):
        self.facts, self.error, self.calls = facts, error, []

    def __call__(self, lane_id, revision):
        self.calls.append((lane_id, revision))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.facts)


class Withdrawals:
    """LABELLED. The lane's withdraw port (`adapters/owner_actions` builds a HostDelivery over the lane store): the REAL
    lane HostDelivery behind `withdrawals(lane_id)`. `error` raises before any effect; `lose` loses the next response AFTER
    the lane committed its withdrawal (M7 `Lossy`); `crash` raises before the port is reached (the M7 crash row)."""

    def __init__(self, delivery):
        self.delivery, self.error, self.lose, self.crash, self.calls = delivery, None, 0, None, []

    def __call__(self, lane_id):
        assert lane_id == "a"
        if self.crash is not None:
            raise self.crash
        return self

    def withdraw(self, plan_id, plan_sha256, reason, evidence_ref):
        self.calls.append((plan_id, reason))
        if self.error is not None:
            raise self.error
        result = self.delivery.withdraw(plan_id, plan_sha256, reason, evidence_ref)
        if self.lose:
            self.lose -= 1
            raise TimeoutError("response lost after the effect (labelled injected fault)")
        return result


class Mainline:
    """LABELLED. `adapters/owner_actions.LaneMainline` answering from the GitHub double: `remote_main` is its main (or
    raises `error`); every commit exists; the goal blob is `goal_sha` at every revision (M7 `GitHubMainline`)."""

    def __init__(self, github, goal_sha=GOAL_SHA):
        self.github, self.goal_sha, self.error, self.reads = github, goal_sha, None, 0

    def __call__(self, lane_id):
        assert lane_id == "a"
        return self

    def remote_main(self):
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.github.main

    def commit_exists(self, revision):
        return True

    def goal(self, revision, path):
        return {"mode": "100644", "sha256": self.goal_sha, "bytes": 3}


class Requalify:
    """LABELLED. The `requalify(document)` port of `adapters/owner_actions` (`Continuation.requalify_delivery`): it records
    each document (byte for byte) and answers that method's `{"cached", "requalification_intent", "successor_job"}` shape.
    Its two effects on the control store are the ones the continuation owner writes: the delivery intent is superseded and the
    ONE requalification intent (`dc.requalification_id`) is created; an identical replay is `cached`. `error` raises before
    the effect, `lose` loses the next response after it (M7 `Lossy`), `move` runs first (main moving before the read)."""

    def __init__(self, world):
        self.world, self.calls, self.error, self.lose, self.move = world, [], None, 0, None

    def __call__(self, document):
        self.calls.append(copy.deepcopy(document))
        api, store = self.world.api, self.world.control
        if self.move is not None:
            self.move(document)
        if self.error is not None:
            raise self.error
        # The two refusals `requalify_delivery` makes from its own mainline read (covered by
        # `coordination.continuation_owner_paths`): main moved since the document, or the goal blob changed at main.
        if document["main_revision"] != self.world.mainline.remote_main():
            raise api.dc.ContinuationRefused("requalification_main_changed", "owner", "main_revision")
        if self.world.mainline.goal_sha != GOAL_SHA:
            raise api.dc.ContinuationRefused("requalification_goal_changed", "owner", "goal")
        new_id = api.dc.requalification_id(document["intent_id"])
        with store.transaction() as tx:
            cached = tx.get(INTENTS, new_id) is not None
            if not cached:
                origin = tx.get(INTENTS, document["intent_id"])
                tx.put(INTENTS, document["intent_id"], {**origin, "state": api.dc.SUPERSEDED,
                                                        "superseded_by": new_id})
                tx.put(INTENTS, new_id, {"id": new_id, "policy_id": origin["policy_id"], "route": api.dc.REQUALIFICATION,
                                         "state": api.dc.ADMITTED, "family": origin.get("family"),
                                         "lane": origin.get("lane"), "main_revision": document["main_revision"],
                                         "created_at": NOW, "version": 1})
        if self.lose:
            self.lose -= 1
            raise TimeoutError("response lost after the effect (labelled injected fault)")
        return {"cached": cached, "requalification_intent": new_id, "successor_job": "job-" + new_id[:8]}


# ---- the world ---------------------------------------------------------------------------------------------
def owner_policy(api, *, policy_id="owners-1", v2=False, fleet=True, requalify=True, max_per_family=1, research=None,
                 schema=None):
    """The owner policy of the M7 tests: v1 (`tests/test_owner_actions_migration.py::policy_document`, the owner-canary
    check) or v2 (`tests/test_owner_actions_recovery.py::owner_policy`, requalification enabled)."""
    od = api.owner_domain
    document = {"schema": schema or (od.POLICY_SCHEMA_V2 if v2 else od.POLICY_SCHEMA), "id": policy_id, "enabled": True,
                "continuation_policy": "policy-1", "assessment": {"model_label": "labelled-fixture-assessor"},
                "delivery": {"target_id": TARGET, "repository": D.REPOSITORY, "required_checks": [D.CHECK],
                             "canary_check_id": api.CANARY_FLEET if fleet else api.CANARY_STARTUP,
                             "ci_timeout_seconds": 300, "consumption_timeout_seconds": 120},
                "canary": copy.deepcopy(CANARY) if fleet else None}
    if document["schema"] == od.POLICY_SCHEMA_V2:
        document["requalification"] = {"enabled": True, "reasons": ["reviewed_base_moved"],
                                       "max_per_family": max_per_family} if requalify else None
        document["research"] = research
    return document


class World:
    """One control store, ONE lane store with the REAL lane HostDelivery (`s7_delivery.build`: a reviewed, verified release
    built through `Releases`, the registered target, the GitHub double, the host and canary doubles), the REAL continuation
    policy row, and the owner with its labelled ports. The starting rows are M7's `ordinary_world`: one conducted
    AWAITING_OWNER delivery intent of the approved release with no plan yet."""

    def __init__(self, api, *, port="default", descriptor=None, policy=None, fleet=True, v2=False, verified=True,
                 fast_forward=False, intent_fields=None, register_owner=True, **policy_options):
        self.api, self.log = api, Log()
        self.control = D.SerialStore(api)
        self.system = D.build(api, store=D.SerialStore(api), register_plan=False, target_id=TARGET, verified=verified,
                              github=D.FakeGitHub(api, fast_forward=fast_forward))
        self.delivery, self.lane_store, self.release = (self.system["delivery"], self.system["store"],
                                                        self.system["release"])
        self.github = self.system["github"]
        self.continuation = api.Continuation(self.control, fleet=None, lanes=None, conductor=None,
                                             validate=api.validate_manifest, clock=T.ticking())
        self.continuation.register(T.policy_document(api), T.PIN)
        self.publisher, self.targets = Publisher(self.log), Targets(self.log)
        self.port = Port() if port == "default" else port
        self.evidence = Evidence()
        self.artifacts = Artifacts(self.evidence)
        self.mainline, self.withdrawals, self.requalify = Mainline(self.github), Withdrawals(self.delivery), Requalify(self)
        self.ports = {"continuation": self.continuation, "deliveries": self.lane, "publisher": self.publish_to,
                      "targets": self.targets, "first_activation": self.port}
        self.v2_ports = {"withdrawals": self.withdrawals, "mainline": self.mainline, "requalify": self.requalify,
                         "artifacts": self.artifacts}
        self.policy = policy or owner_policy(api, fleet=fleet, v2=v2, **policy_options)
        self.owner = self.build_owner()
        if register_owner:
            self.owner.register(self.policy, PIN)
        self.intent = {"id": "intent-1", "policy_id": "policy-1", "route": api.dc.DELIVERY,
                       "state": api.dc.AWAITING_OWNER, "release_id": self.release["id"], "delivery_target": TARGET,
                       "lane": "a", "created_at": NOW, "version": 3, "family": "family-1", "origin_job": "job-1",
                       **(intent_fields or {})}
        self.put(self.control, INTENTS, self.intent["id"], self.intent)
        if descriptor is not None:
            self.put(self.lane_store, D.BUCKET_DESCRIPTORS, TARGET, {"target_id": TARGET, "descriptor": descriptor})

    def lane(self, lane_id):
        assert lane_id == "a"
        return self.delivery

    def publish_to(self, lane_id):
        assert lane_id == "a"
        return self.publisher

    def build_owner(self, **overrides):
        ports = {**self.ports, **self.v2_ports, **overrides}
        return self.api.OwnerActions(self.control, clock=lambda: NOW, **ports)

    @staticmethod
    def put(store, bucket, key, body):
        with store.transaction() as tx:
            tx.put(bucket, key, body)

    def tick(self, policy_id=None, owner=None):
        return (owner or self.owner).tick(policy_id or self.policy["id"])

    def ticks(self, n=5, **kwargs):
        return [self.tick(**kwargs) for _ in range(n)]

    # ---- reads ----
    def actions(self, kind=None):
        found = sorted(rows(self.control, ACTIONS).values(), key=lambda r: (str(r.get("created_at")), r["id"]))
        return [r for r in found if kind is None or r["kind"] == kind]

    def lane_row(self, bucket, key):
        with self.lane_store.transaction() as tx:
            return tx.get(bucket, key)

    def stores(self):
        return {"control": D.store_digest(self.control), "lane": D.store_digest(self.lane_store)}

    def seen(self):
        """What every double saw, in order."""
        return {"log": [list(e) for e in self.log], "port": [list(c) for c in getattr(self.port, "calls", [])],
                "publisher_refs": sorted(self.publisher.refs), "requests": sorted(self.targets.requests),
                "github": {"publishes": self.github.publishes, "merges": self.github.merges,
                           "observations": self.github.observations}}


def receipt_view(receipt):
    return {key: receipt.get(key) for key in ("outcome", "reason_code", "created", "actions", "waits", "open")}


def plan_actions(world):
    return world.actions(world.api.owner_domain.DELIVERY_PLAN)


def guarded(world, fn, *args, **kwargs):
    """A call, its outcome and whether it wrote anything in EITHER store (a wait writes nothing)."""
    before = world.stores()
    out = call(fn, *args, **kwargs)
    return {**out, "wrote": world.stores() != before}


# ---- 1. G2 plan publication ------------------------------------------------------------------------------------------
def binding_of(api, expected, facts=None):
    """M7 `binding_of`: the plan binding of the recorded intent, release and policy row."""
    policy_row = {"id": "owners-1", "policy_sha256": "a" * 64}
    intent = {"id": "intent-1", "delivery_target": TARGET}
    release = {"id": "rel-1", "candidate": dict(D.candidate()), "policy_hash": "e" * 64}
    return api.owner_domain.plan_binding(policy_row, intent, release, expected, first_activation=facts)


def builder(api):
    """M7 `test_a_first_activation_plan_carries_the_concrete_tuple_and_an_upgrade_keeps_unchanged`,
    `test_an_absent_or_malformed_first_activation_is_refused_unbound` and
    `test_the_image_source_revision_is_provenance_only`: the pure domain builder."""
    od = api.owner_domain
    policy = od.validate_policy(owner_policy(api))
    facts = od.first_activation_tuple(FIRST_ACTIVATION)
    first = od.build_plan(policy, binding_of(api, None, facts), "f" * 64, first_activation=facts)
    upgrade = od.build_plan(policy, binding_of(api, "4" * 64), "f" * 64, first_activation=facts)
    malformed = [None, "sha256:" + "9" * 64, {}, {**FIRST_ACTIVATION, "worker_image": api.UNCHANGED},
                 {**FIRST_ACTIVATION, "worker_image": "zeus/worker:latest"},
                 {**FIRST_ACTIVATION, "worker_image": "sha256:" + "9" * 63},
                 {**FIRST_ACTIVATION, "worker_image": "sha256:" + "A" * 64},
                 {**FIRST_ACTIVATION, "profile_digest": api.UNCHANGED},
                 {**FIRST_ACTIVATION, "profile_digest": "c" * 63}, {**FIRST_ACTIVATION, "profile_digest": 7}]
    refusals = []
    for bad in malformed:
        try:
            od.build_plan(policy, binding_of(api, None), "f" * 64, first_activation=bad)
            refusals.append({"built": True})
        except od.OwnerActionRefused as exc:
            refusals.append({"reason_code": exc.reason_code, "field": exc.field})
    return {"first": first, "upgrade": upgrade,
            "upgrade_binding_has_no_first_activation_key": "first_activation" not in binding_of(api, "4" * 64),
            "first_binding_first_activation": binding_of(api, None, facts)["first_activation"],
            "refusals": refusals, "tuple": od.first_activation_tuple(FIRST_ACTIVATION),
            "provenance_only": od.first_activation_tuple({**CONCRETE, "image_source_revision": "labelled"})}


def ordinary_first_activation(api):
    """M7 `test_the_ordinary_first_activation_publishes_and_registers_the_concrete_tuple`."""
    w = World(api)
    receipts = [receipt_view(r) for r in w.ticks(5)]
    [action] = plan_actions(w)
    plan = action["plan"]
    return {"receipts": receipts, "action": action, "lane_plan": w.lane_row(D.BUCKET_PLANS, plan["plan_id"]),
            "lane_intent": w.lane_row(D.BUCKET_INTENTS, plan["plan_id"]), "seen": w.seen(), **w.stores()}


def upgrade(api):
    """M7 `test_an_upgrade_keeps_unchanged_and_never_consults_the_port`: the port raises if it is consulted."""
    w = World(api, port=Port(error=AssertionError("the port must not be consulted for an upgrade")),
              descriptor=DESCRIPTOR)
    receipts = [receipt_view(r) for r in w.ticks(5)]
    [action] = plan_actions(w)
    return {"receipts": receipts, "action": action, "expected_descriptor_is_digest": action["plan"][
        "expected_descriptor"] == api.descriptor_digest(DESCRIPTOR),
            "lane_plan": w.lane_row(D.BUCKET_PLANS, action["plan"]["plan_id"]), "seen": w.seen(), **w.stores()}


def port_waits(api):
    """M7 `test_a_missing_failing_or_malformed_port_is_a_named_wait_with_no_action_or_publication`."""
    out = {}
    cases = [("unconfigured", None), ("oserror", Port(error=OSError("labelled: lane repository unavailable"))),
             ("keyerror", Port(error=KeyError("labelled: lane not configured"))),
             ("delivery_refused", Port(error=api.DeliveryRefused("first_activation_image_unconfigured"))),
             ("unchanged_image", Port(facts={**FIRST_ACTIVATION, "worker_image": api.UNCHANGED})),
             ("no_facts", Port(facts=None))]
    for name, port in cases:
        w = World(api, port=port)
        before = w.stores()
        receipts = [receipt_view(r) for r in w.ticks(3)]
        out[name] = {"receipts": receipts, "actions": plan_actions(w), "seen": w.seen(),
                     "nothing_written": w.stores() == before, "requests_empty": w.targets.requests == {}}
    return out


def recovered_port(api):
    """M7 `test_a_recovered_port_then_plans_exactly_once`."""
    port = Port(error=OSError("labelled outage"))
    w = World(api, port=port)
    first = receipt_view(w.tick())
    port.error = None
    rest = [receipt_view(r) for r in w.ticks(5)]
    [action] = plan_actions(w)
    return {"first": first, "rest": rest, "action": action, "seen": w.seen(), **w.stores()}


def legacy_intended_row(api):
    """M7 `test_a_recorded_intended_row_without_bound_facts_is_refused_before_publication`: a LABELLED crafted row, as
    recorded before this change (a null predecessor and no tuple)."""
    od = api.owner_domain
    w = World(api)
    with w.control.transaction() as tx:
        policy_row = tx.get(POLICIES, "owners-1")
    intent = rows(w.control, INTENTS)["intent-1"]
    legacy = od.plan_binding(policy_row, intent, w.release, None)
    row = od.new_action(od.DELIVERY_PLAN, legacy, policy_row, {"intent_id": "intent-1", "lane": "a"}, NOW)
    w.put(w.control, ACTIONS, row["id"], row)
    first = receipt_view(w.tick())
    refused = rows(w.control, ACTIONS)[row["id"]]
    log_after_refusal = [list(e) for e in w.log]
    rest = [receipt_view(r) for r in w.ticks(5)]
    bound = [a for a in plan_actions(w) if a["id"] != row["id"]]
    return {"first": first, "refused": refused, "log_after_refusal": log_after_refusal, "rest": rest, "bound": bound,
            "seen": w.seen(), **w.stores()}


# ---- 2. C1 requalify and withdraw --------------------------------------------------------------------------------------
def blocked_world(api, *, twins=False, **options):
    """M7 `stale`: the plan the owner published and registered, then main moved (a LABELLED write: M7 merges another
    family's delivery first, which is `delivery.stages`), and the REAL lane controller blocking it at `_publish` with
    `reviewed_base_moved` and no PR. The continuation intent stays AWAITING_OWNER."""
    options = {"fleet": False, "v2": True, **options}
    w = World(api, **options)
    w.ticks(5)
    w.github.main = MOVED
    ticks = D.drive(w.system, until=api.MERGED, limit=8)
    w.blocked = [{key: t.get(key) for key in ("stage", "outcome", "reason_code")} for t in ticks]
    return w


def lane_stage(w, plan_id):
    row = w.lane_row(D.BUCKET_INTENTS, plan_id) or {}
    return {key: row.get(key) for key in ("stage", "reason_code", "withdrawal", "previous_stage")}


def requalified(w):
    return w.actions(w.api.owner_domain.DELIVERY_REQUALIFY)


def requalify_view(w, plan_id=None):
    """The requalify rows, the lane stage of the plan, what the doubles saw and the digest of both stores."""
    [plan] = plan_actions(w)[:1]
    plan_id = plan_id or plan["plan_id"]
    return {"rows": requalified(w), "lane": lane_stage(w, plan_id), "intents": intent_view(w),
            "requalify_calls": len(w.requalify.calls), "withdraw_calls": len(w.withdrawals.calls),
            "documents_equal_rows": all(c == r.get("document") for c in w.requalify.calls for r in requalified(w)[:1]),
            "seen": w.seen(), **w.stores()}


def intent_view(w):
    return {key: {k: row.get(k) for k in ("route", "state", "superseded_by")}
            for key, row in sorted(rows(w.control, INTENTS).items())}


def requalified_once(api):
    """M7 `test_the_second_candidate_on_the_stale_base_is_requalified_on_the_first_merge_and_delivered` and the tail of
    `test_b2_held_at_f4...` (the requalification, then nothing more across a restarted owner)."""
    w = blocked_world(api)
    first = receipt_view(w.tick())
    row_after_first = requalified(w)
    rest = [receipt_view(r) for r in w.ticks(3)]
    settled = requalify_view(w)
    before = w.stores()
    idle = [receipt_view(w.tick()), receipt_view(w.tick(owner=w.build_owner()))]
    return {"blocked": w.blocked, "first": first, "rows_after_first": row_after_first, "rest": rest, "settled": settled,
            "idle": idle, "idle_wrote_nothing": w.stores() == before, "rationale_held": sorted(w.evidence.held),
            "artifact_kinds": list(w.artifacts.kinds)}


def version1(api):
    """M7 `test_a_version1_policy_never_withdraws_requalifies_or_dispatches`."""
    w = blocked_world(api, v2=False)
    before = w.stores()
    receipts = [receipt_view(w.tick())]
    return {"blocked": w.blocked, "receipts": receipts, "rows": requalified(w), "lane": lane_stage(
        w, plan_actions(w)[0]["plan_id"]), "nothing_written": w.stores() == before, "calls": len(w.requalify.calls)}


def restart_matrix(api):
    """M7 `test_a_restart_at_any_persisted_state_replays_to_one_withdrawal_and_one_requalification`."""
    out = {}
    for crash in ("before_slot", "withdraw_response_lost", "before_document", "requalify_response_lost"):
        w = blocked_world(api)
        plan_id = plan_actions(w)[0]["plan_id"]
        if crash == "before_slot":
            w.withdrawals.crash = RuntimeError("crash")
            crashed = receipt_view(w.tick())
            w.withdrawals.crash = None
        elif crash == "withdraw_response_lost":
            w.withdrawals.lose = 1
            crashed = receipt_view(w.tick())
        elif crash == "before_document":
            w.mainline.error = OSError("ls-remote unavailable (labelled)")
            crashed = receipt_view(w.tick())
            w.mainline.error = None
        else:
            w.requalify.lose = 1
            crashed = receipt_view(w.tick())
        at_crash = {"receipt": crashed, "row": requalified(w)[0]["state"], "document_persisted":
                    requalified(w)[0].get("document") is not None, "lane": lane_stage(w, plan_id)["stage"],
                    "intents": intent_view(w)}
        restarted = w.build_owner()
        receipts = [receipt_view(w.tick(owner=restarted)) for _ in range(3)]
        row = requalified(w)[0]
        made = [k for k, v in rows(w.control, INTENTS).items() if v.get("route") == api.dc.REQUALIFICATION]
        out[crash] = {"at_crash": at_crash, "receipts": receipts, "row": row, "requalification_intents": made,
                      "evidence_ref_is_rationale": lane_stage(w, plan_id)["withdrawal"]["evidence_ref"]
                      == row["rationale_ref"], "documents_all_persisted": all(
                          c == row["document"] for c in w.requalify.calls), "calls": len(w.requalify.calls),
                      "seen": w.seen(), **w.stores()}
    return out


def main_moves(api):
    """M7 `test_main_moving_between_the_persisted_document_and_the_call_refuses_and_the_cap_holds`."""
    w = blocked_world(api)
    w.requalify.move = lambda document: setattr(w.github, "main", "8" * 39 + "1")
    w.tick()
    row = requalified(w)[0]
    made = [k for k, v in rows(w.control, INTENTS).items() if v.get("route") == api.dc.REQUALIFICATION]
    before = w.stores()
    rest = [receipt_view(w.tick()) for _ in range(3)]
    return {"row": row, "requalification_intents": made, "rest": rest, "nothing_more_written": w.stores() == before,
            "intents": intent_view(w)}


def goal_changed(api):
    """M7 `test_a_goal_changed_at_the_new_main_is_a_named_refusal_and_no_migration_is_written`."""
    w = blocked_world(api)
    w.mainline.goal_sha = "3" * 64
    w.tick()
    row = requalified(w)[0]
    return {"row": row, "goal_migration_in_document": "goal_migration" in row["document"],
            "stored": sorted(rows(w.control, "continuation_requalifications")), "intents": intent_view(w)}


def unobservable_github(api):
    """M7 `test_an_unobservable_github_keeps_the_row_and_the_target_busy_until_it_can_be_observed`."""
    w = blocked_world(api)
    plan_id = plan_actions(w)[0]["plan_id"]
    w.github.observe_error = OSError("GitHub unavailable (labelled)")
    lane_before = D.store_digest(w.lane_store)
    receipts = [receipt_view(w.tick()) for _ in range(3)]
    waiting = {"row": requalified(w)[0]["state"], "lane_unchanged": D.store_digest(w.lane_store) == lane_before,
               "lane": lane_stage(w, plan_id)["stage"]}
    w.github.observe_error = None
    after = receipt_view(w.tick())
    return {"receipts": receipts, "waiting": waiting, "after": after, "row": requalified(w)[0]["state"]}


def second_blocked_family(w):
    """LABELLED (M7 `second_blocked_family`): another completed plan of the same owner policy whose delivery the
    controller blocked as stale, for ANOTHER delivery intent of the SAME family; its plan is not registered with the lane."""
    [plan] = [r for r in w.actions(w.api.owner_domain.DELIVERY_PLAN)]
    twin_intent = {**rows(w.control, INTENTS)[plan["subject"]["intent_id"]], "id": "7" * 64,
                   "state": w.api.dc.AWAITING_OWNER}
    twin = {**plan, "id": "8" * 64, "plan_id": "own-twin", "plan_sha256": "9" * 64,
            "subject": {"intent_id": twin_intent["id"], "lane": "a"}}
    w.put(w.control, INTENTS, twin_intent["id"], twin_intent)
    w.put(w.control, ACTIONS, twin["id"], twin)
    w.put(w.lane_store, D.BUCKET_INTENTS, "own-twin", {"id": "own-twin", "plan_id": "own-twin", "plan_sha256": "9" * 64,
                                                        "target_id": TARGET, "stage": w.api.BLOCKED,
                                                        "reason_code": "reviewed_base_moved"})
    return twin


def family_cap(api):
    """M7 `test_max_per_family_one_allows_the_first_requalification_and_refuses_the_next`, and the adjudicated race as far
    as the public tick reaches (two coordinators over one store, each ticking; the slot interleaving is unreachable)."""
    w = blocked_world(api)
    twin = second_blocked_family(w)
    w.tick()
    found = {r["binding"]["plan_id"]: r for r in requalified(w)}
    slotted = [r for r in found.values() if r.get("cap_slot") == 1]
    exhausted = [r for r in found.values() if r["reason_code"] == "requalification_exhausted"]
    first = {"rows": found, "slotted": len(slotted), "exhausted": len(exhausted),
             "same_family": len({r["binding"]["family"] for r in found.values()}) == 1,
             "twin_present": twin["plan_id"] in found, "calls": len(w.requalify.calls)}
    racing = blocked_world(api)
    second_blocked_family(racing)
    a, b = racing.build_owner(), racing.build_owner()
    ticked = [receipt_view(racing.tick(owner=a)), receipt_view(racing.tick(owner=b))]
    slots = sorted(r.get("cap_slot") or 0 for r in requalified(racing))
    return {"first": first, "racing": {"receipts": ticked, "slots": slots, "calls": len(racing.requalify.calls),
                                       "rows": [(r["binding"]["plan_id"], r["state"], r["reason_code"]) for r in
                                                requalified(racing)]}}


def one_action(api):
    """M7 `test_the_same_blocked_plan_is_one_action_for_restarts_and_second_coordinators_and_never_another_policys`."""
    w = blocked_world(api)
    other = owner_policy(api, policy_id="owners-other", v2=True, fleet=False)
    w.owner.register(other, PIN)
    receipts = [receipt_view(w.tick(owner=owner)) for owner in (w.owner, w.build_owner(), w.build_owner())]
    theirs = receipt_view(w.tick("owners-other"))
    w.tick()
    w.tick(owner=w.build_owner())
    rows_ = requalified(w)
    return {"receipts": receipts, "other_policy_receipt": theirs, "rows": len(rows_), "row": rows_[0],
            "id_names_no_owner_policy": rows_[0]["id"] == api.owner_domain.action_id(
                api.owner_domain.DELIVERY_REQUALIFY, api.owner_domain.requalify_binding(
                    plan_actions(w)[0], rows(w.control, INTENTS)["intent-1"], w.lane_row(
                        D.BUCKET_INTENTS, plan_actions(w)[0]["plan_id"]))),
            "calls": len(w.requalify.calls)}


def other_reason_or_touched_host(api):
    """M7 `test_a_plan_blocked_for_another_reason_or_a_touched_host_is_never_requalified`."""
    w = blocked_world(api)
    plan_id = plan_actions(w)[0]["plan_id"]
    row = w.lane_row(D.BUCKET_INTENTS, plan_id)
    w.put(w.lane_store, D.BUCKET_INTENTS, plan_id, {**row, "reason_code": "descriptor_predecessor_moved"})
    other = receipt_view(w.tick())
    none_yet = requalified(w)
    w.put(w.lane_store, D.BUCKET_INTENTS, plan_id, {**row, "descriptor": {"schema": "fixture"}})
    touched = receipt_view(w.tick())
    return {"other_reason": other, "rows_after_other_reason": none_yet, "touched": touched, "rows": requalified(w),
            "calls": len(w.requalify.calls)}


def unregistered_target(api):
    """M7 `test_a_plan_whose_lane_store_has_no_target_row_is_a_named_wait`: the same target named from a lane whose store
    never registered it."""
    w = World(api, fleet=False, v2=True)
    other = api.HostDelivery(D.SerialStore(api), api.organization())
    owner = w.build_owner(deliveries=lambda lane: other)
    receipt = receipt_view(w.tick(owner=owner))
    return {"receipt": receipt, "actions": plan_actions(w), "publishes": w.github.publishes, "seen": w.seen()}


def two_targets(api):
    """M7 `test_two_targets_of_one_repository_main_are_each_bound_to_their_reviewed_base` (the REAL HostDelivery)."""
    store, org, github = D.SerialStore(api), api.organization(), D.FakeGitHub(api, fast_forward=True)
    delivery = api.HostDelivery(store, org, github=github, clock=D.clock(api), enabled=True, resume_seconds=0)
    registry = D.targets_document(api, target_id="t-one")
    registry["targets"] += D.targets_document(api, target_id="t-two", root=D.RUNTIME_ROOT + "-two")["targets"]
    delivery.register_targets(registry)
    first = D.plan_document(api, D.reviewed_release(api, store, org), plan_id="p-one", target_id="t-one")
    delivery.register(first, D.pin(path="docs/zeus/operations/p-one.json"))
    stages = []
    for _ in range(6):
        stages.append(delivery.tick("p-one")["stage"])
        api.advance(1)
        if stages[-1] == api.MERGED:
            break
    stale_candidate = {**D.candidate(), "revision": "5" * 40, "branch": "harness/two", "task_id": "two"}
    second = D.plan_document(api, D.reviewed_release(api, store, org, record_candidate=stale_candidate),
                             plan_id="p-two", target_id="t-two")
    delivery.register(second, D.pin(path="docs/zeus/operations/p-two.json"))
    blocked = [delivery.tick("p-two") for _ in range(2)][-1]
    return {"first_stages": stages, "main_is_first": github.main == first["revision"],
            "blocked": {key: blocked.get(key) for key in ("stage", "outcome", "reason_code")},
            "publishes": github.publishes, "merges": github.merges}


def strict_blocks(api):
    """M7 `test_version1_keeps_its_exact_canonical_form_and_version2_blocks_are_strict` (the pure policy grammar)."""
    od = api.owner_domain
    v1 = owner_policy(api, fleet=False, schema=od.POLICY_SCHEMA)
    canonical = od.validate_policy(v1)
    v2 = owner_policy(api, policy_id="owners-2", v2=True, fleet=False,
                      research={"enabled": True, "program_id": "rp-b2", "lane": "a"})
    valid = od.validate_policy(v2)
    req = {"enabled": True, "reasons": ["reviewed_base_moved"], "max_per_family": 1}
    bad = [{"requalification": {**req, "reasons": ["merged_tree_mismatch"]}},
           {"requalification": {**req, "reasons": ["descriptor_predecessor_moved"]}},
           {"requalification": {**req, "reasons": []}}, {"requalification": {**req, "max_per_family": 0}},
           {"requalification": {**req, "max_per_family": 4}}, {"requalification": {**req, "enabled": 1}},
           {"requalification": {**req, "goal_migration": True}},
           {"research": {"enabled": True, "program_id": "../x", "lane": "a"}},
           {"research": {"enabled": True, "program_id": "rp-b2"}}]
    refusals = []
    for change in bad:
        try:
            od.validate_policy({**v2, **change})
            refusals.append({"accepted": True})
        except od.OwnerActionRefused as exc:
            refusals.append({"reason_code": exc.reason_code, "field": exc.field})
    try:
        od.validate_policy({**v1, "research": None})
        v1_with_v2_block = {"accepted": True}
    except od.OwnerActionRefused as exc:
        v1_with_v2_block = {"reason_code": exc.reason_code, "field": exc.field}
    disabled = od.validate_policy({**v2, "requalification": {**v2["requalification"], "enabled": False}})
    return {"v1_fields_exact": set(canonical) == od.POLICY_FIELDS, "v1_schema": canonical["schema"],
            "v1_blocks": [od.requalification_policy(canonical), od.research_policy(canonical)],
            "v2_requalification": valid["requalification"], "v2_research": od.research_policy(valid),
            "refusals": refusals, "v1_with_v2_block": v1_with_v2_block,
            "disabled": od.requalification_policy(disabled)}


def c1(api):
    UNREACHABLE.update({
        "b2_research_and_fresh_job": "the research part of test_b2_held_at_f4... (two strikes, Portfolio, the ProgramRunner over "
        "a real Git repository, the research child) and the fresh job admitted on the new main through the real Fleet/"
        "Operation/conductor are research/coordination flows (coordination.owner_actions_research and "
        "coordination.continuation_*): the requalify tail is characterized by requalified_once with a LABELLED main move",
        "cap_race_interleaving": "M7 calls the private OwnerActions._discover and ._take_slot to interleave two coordinators "
        "at the slot; only the public tick is a surface (family_cap.racing ticks two coordinators in turn)",
        "same_plan_private_discovery": "M7 calls the private OwnerActions._discover directly; one_action drives the public tick"})
    return {"requalified_once": requalified_once(api), "version1": version1(api), "restart_matrix": restart_matrix(api),
            "main_moves": main_moves(api), "goal_changed": goal_changed(api),
            "unobservable_github": unobservable_github(api), "family_cap": family_cap(api),
            "one_action": one_action(api), "other_reason_or_touched_host": other_reason_or_touched_host(api),
            "unregistered_target": unregistered_target(api), "two_targets": two_targets(api),
            "strict_blocks": strict_blocks(api)}


# ---- 1b. the migration successor --------------------------------------------------------------------------------------
class Halted(M.Lane):
    """The REAL lane's halted source (`s7_migration.Lane.halt_group1`: a reviewed release REJECTED by an executed failed
    check after its candidate merged, through the real queue API plus ONE intent put) over the World's lane store, with the
    LABELLED evaluator-pin resolver of `s7_migration`. The World's own plan (the one the owner published) is the halted plan."""

    def __init__(self, world):
        self.api, self.label, self.steps, self.extra = world.api, "owner", [], {}
        self.system = world.system
        self.halted = self.halt_group1()
        self.pins = self.delivery.evaluator_pins = M.EvaluatorRepository()
        for revision in (M.E, M.OTHER_E):
            self.pins.add(revision)


class MigrationWorld(World):
    """M7 `tests/test_owner_actions_migration.py::world`: the original completed DELIVERY_PLAN action of a rejected
    source release (a LABELLED crafted control row, as M7 crafts it), its plan registered on the REAL lane and halted."""

    def __init__(self, api, **options):
        super().__init__(api, fleet=True, verified=False, **options)
        od = api.owner_domain
        with self.control.transaction() as tx:
            policy_row = tx.get(POLICIES, self.policy["id"])
        binding = od.plan_binding(policy_row, self.intent, self.release, None)
        identity = od.action_id(od.DELIVERY_PLAN, binding)
        self.plan = od.build_plan(policy_row["policy"], binding, identity, first_activation=FIRST_ACTIVATION)
        self.old_action = {**od.new_action(od.DELIVERY_PLAN, binding, policy_row,
                                           {"intent_id": "intent-1", "lane": "a"}, NOW),
                           "state": od.COMPLETED, "reason_code": "plan_registered", "plan": self.plan,
                           "plan_id": self.plan["plan_id"], "plan_sha256": api.plan_digest(self.plan), "version": 4,
                           # the fields a really published action carries (the crafted row of M7 lacks them because
                           # M7's lane intent is terminal `failed`; the halted intent here is `blocked`)
                           "path": od.plan_path(self.plan["plan_id"]), "ref": od.plan_ref(self.plan["plan_id"]),
                           "published_at": NOW}
        self.put(self.control, ACTIONS, identity, self.old_action)
        self.system["plan"] = self.plan
        self.delivery.register(self.plan, D.pin(path=od.plan_path(self.plan["plan_id"])))
        self.lane_halt = Halted(self)

    def document(self, **overrides):
        """M7 `document(w)`: the owner-only migration request naming the halted source."""
        api, evidence = self.api, "sha256:" + "4" * 64
        approval = {"source_release_id": self.release["id"], "base": self.release["candidate"]["base"],
                    "evaluator_revision": M.E, "evaluator_tree": "2" * 40, "patch_sha256": "3" * 64,
                    "paths": ["tests/test_fixture.py"], "evidence": evidence, "approved_by": "conductor"}
        return {"policy_id": self.policy["id"], "intent_id": "intent-1", "lane": "a", "target_id": TARGET,
                "source_release_id": self.release["id"], "source_policy_hash": self.release["policy_hash"],
                "candidate_revision": self.release["candidate"]["revision"], "old_plan_id": self.plan["plan_id"],
                "old_plan_sha256": api.plan_digest(self.plan), "approval": approval, "evidence": evidence,
                "actor": "conductor", **overrides}

    def migration_row(self):
        return rows(self.control, MIGRATIONS).get(self.release["id"])

    def settle(self, ticks=12, owner=None):
        results = []
        for _ in range(ticks):
            results.append(receipt_view(self.tick(owner=owner)))
            if (self.migration_row() or {}).get("state") in self.api.owner_domain.TERMINAL:
                break
        return results

    def successors(self):
        return [a for a in plan_actions(self) if (a.get("subject") or {}).get("migration")]

    def lane_record(self):
        return self.lane_row(D.BUCKET_MIGRATIONS if hasattr(D, "BUCKET_MIGRATIONS") else "host_delivery_migrations",
                             self.plan["plan_id"])

    def view(self):
        return {"migration": self.migration_row(), "successors": self.successors(), "lane_record": self.lane_record(),
                "seen": self.seen(), **self.stores()}


def migration_first_activation(api):
    """M7 `test_the_migration_successor_of_a_first_activation_carries_the_concrete_tuple`."""
    w = MigrationWorld(api)
    requested = call(w.owner.request_migration, w.document())
    settled = w.settle()
    [successor] = w.successors()
    return {"requested": requested, "settled": settled, **w.view(),
            "successor_tuple": successor["binding"].get("first_activation") == FIRST_ACTIVATION,
            "successor_plan_concrete": successor["plan"]["target_descriptor"], "expected_descriptor":
                successor["plan"]["expected_descriptor"],
            "lane_plan_equals": (w.lane_row(D.BUCKET_PLANS, successor["plan_id"]) or {}).get("plan") == successor["plan"]}


def migration_upgrade(api):
    """M7 `test_the_migration_successor_of_an_upgrade_keeps_unchanged_without_the_port`: a current descriptor is written
    after the halted first activation, and a port that raises replaces the owner's."""
    w = MigrationWorld(api)
    w.put(w.lane_store, D.BUCKET_DESCRIPTORS, TARGET, {"target_id": TARGET, "descriptor": DESCRIPTOR})
    port = Port(error=AssertionError("the port must not be consulted for an upgrade"))
    w.port = port
    w.ports["first_activation"] = port
    owner = w.owner = w.build_owner()
    requested = call(owner.request_migration, w.document())
    settled = w.settle()
    [successor] = w.successors()
    return {"requested": requested, "settled": settled, **w.view(), "port_calls": port.calls,
            "no_first_activation_key": "first_activation" not in successor["binding"],
            "expected_is_descriptor_digest": successor["plan"]["expected_descriptor"] == api.descriptor_digest(DESCRIPTOR),
            "worker_image": successor["plan"]["target_descriptor"]["worker_image"]}


def migration_unbound(api):
    """M7 `test_an_unbound_successor_waits_staged_with_no_plan_action_then_completes_once_bound`."""
    out = {}
    cases = [("unconfigured", None), ("unavailable", Port(error=OSError("labelled: lane repository unavailable"))),
             ("malformed", Port(facts={**FIRST_ACTIVATION, "profile_digest": "not-a-digest"}))]
    for name, port in cases:
        w = MigrationWorld(api)
        requested = call(w.owner.request_migration, w.document())
        blocked = w.build_owner(first_activation=port)
        receipts = [receipt_view(w.tick(owner=blocked)) for _ in range(4)]
        row = w.migration_row()
        waiting = {"row": row, "successors": w.successors(), "publish_logged": "publish" in [e[0] for e in w.log],
                   "requests": sorted(w.targets.requests)}
        owner = w.owner = w.build_owner(first_activation=Port())
        settled = w.settle(owner=owner)
        [successor] = w.successors()
        out[name] = {"requested": requested, "receipts": receipts, "waiting": waiting, "settled": settled,
                     **w.view(), "successor_plan_concrete": successor["plan"]["target_descriptor"]}
    return out


def g2(api):
    return {"builder": builder(api), "ordinary_first_activation": ordinary_first_activation(api),
            "upgrade": upgrade(api), "port_waits": port_waits(api), "recovered_port": recovered_port(api),
            "legacy_intended_row": legacy_intended_row(api), "migration_first_activation": migration_first_activation(api),
            "migration_upgrade": migration_upgrade(api), "migration_unbound": migration_unbound(api)}


# ---- 3. scheduler integration -----------------------------------------------------------------------------------------
def scheduler(api):
    """The delivery families discovered and advanced by `OwnerActions.tick` next to an idle research family (a policy v2
    with the research block and a research-route intent that is not held: nothing is owed and no research port exists), and
    `status` projecting them at every phase: the plan family, then the requalify family, then the migration."""
    block = {"enabled": True, "program_id": "rp-b2", "lane": "a"}
    w = World(api, fleet=False, v2=True, research=block)
    w.put(w.control, INTENTS, "research-1", {"id": "research-1", "policy_id": "policy-1", "route": api.dc.RESEARCH,
                                             "state": api.dc.ADMITTED, "lane": "a", "created_at": NOW, "version": 1})
    statuses = {"registered": w.owner.status(), "registered_by_policy": w.owner.status(w.policy["id"]),
                "unknown_policy": call(w.owner.status, "owners-none")}
    first = receipt_view(w.tick())
    statuses["after_first_tick"] = w.owner.status(w.policy["id"])
    rest = [receipt_view(r) for r in w.ticks(4)]
    statuses["plan_registered"] = w.owner.status(w.policy["id"])
    w.github.main = MOVED
    ticks = D.drive(w.system, until=api.MERGED, limit=8)
    blocked = [{key: t.get(key) for key in ("stage", "outcome", "reason_code")} for t in ticks]
    requalify = [receipt_view(r) for r in w.ticks(3)]
    statuses["requalified"] = w.owner.status()
    before = w.stores()
    idle = [receipt_view(w.tick()), receipt_view(w.tick(owner=w.build_owner()))]
    actions = [{"kind": a["kind"], "state": a["state"], "reason_code": a["reason_code"]} for a in w.actions()]
    research_rows = [a for a in w.actions() if a["kind"] in (api.owner_domain.RESEARCH_RECEIPT,
                                                            api.owner_domain.RESEARCH_DISPATCH)]
    m = MigrationWorld(api)
    m.owner.request_migration(m.document())
    statuses["migration_requested"] = m.owner.status(m.policy["id"])
    m.settle()
    statuses["migration_completed"] = m.owner.status(m.policy["id"])
    return {"statuses": statuses, "first": first, "rest": rest, "blocked": blocked, "requalify": requalify,
            "idle": idle, "idle_wrote_nothing": w.stores() == before, "actions": actions,
            "research_rows": research_rows, "migration_status": m.owner.migration(m.release["id"]),
            "migration_unknown": m.owner.migration("rel-none")}


def run(api) -> dict:
    return {"g2": g2(api), "c1": c1(api), "scheduler": scheduler(api), "unreachable": UNREACHABLE}
