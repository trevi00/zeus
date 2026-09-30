"""Shared S7 scenario steps (`coordination.owner_actions_migration`): the migration request lifecycle of M7 `OwnerActions`
(`application/owner_actions.py`: `request_migration`, `migration`, `_advance_migrations`/`_advance_migration`,
`_plan_successor`, `_bind_successor`, `_finalize`, `_observe_pin`, `_observe_request`, `_lane_refused` and `_complete`, whose
transaction resumes the recorded source intent) over the REAL M7 `HostDelivery` of a lane store, in the sequences of
`tests/test_owner_actions_migration.py` (DESIGN-s7 §2 row `coordination.owner_actions_delivery`, the 11:50Z split; §3 step 4).

This family is the unit golden the later IntentStore routing of `_complete` must keep byte-equal: it records the exact rows
the completing transaction wrote (`unit`), and that a refusal inside it writes neither the row nor the intent.

Groups (each labelled in the result; the M7 test each case mirrors is named at its function):

1. **request**: one migration per source, the identical replay, every other document refused; the document that does not name
   the exact control records refused writing nothing.
2. **advance**: the ordered handoff, a lost response or a restart at every step, an outage waiting in place, a lane refusal at
   every step, the target reservation for every other plan, the successor edge `_migrated_delivery` follows.
3. **readiness**: the readiness tuple re-observed in the finalizing step (every unavailable or replaced evidence), the restored
   tuple finalizing once, the lost finalize response replaying without readiness, the observed ready record and `status`.
4. **complete** (the unit golden): the finalizing tick of an AWAITING_OWNER source and of a PAUSED source through the REAL
   `Continuation` (the real tick reaches the next item), a source moved between bound and finalize, and a source moved after the
   lane ack, with the control-store digests before and after and the exact rows written.
5. **lane**: the REAL lane owner completing the ordered handoff from a separate control store.

Layer: harness (never shipped). This module never imports `codex_harness`: everything from the product arrives through `api`,
the object a reference (later a target) driver builds: the `coordination.owner_actions_delivery` API plus `Fleet`,
`LaneEvidence`, `plan_binding_of(owner, policy_row, intent)` and `migrated_delivery(tx, deliveries, target, release_id,
revision, release)` (lambdas over the M7 private `OwnerActions._plan_binding` and `continuation._migrated_delivery`).

**Doubles** (each docstring names its source; none runs Git, a process, a host, GitHub or a model): the pilot 29/30 `Publisher`
and `Targets`, the labelled `DownTargets`, the labelled `FaultyLane` (a proxy of the REAL lane HostDelivery injecting the M7
`FakeLane`/`LosingDelivery` faults), the S6 `Conductor` variant naming the real release, and the labelled crafted rows of the M7
tests (the original completed DELIVERY_PLAN action, the paused conductor flow, the lane edge). The lane is never `FakeLane`.

Out of scope: the PostgreSQL tests (`test_pg_*`), `tests/test_owner_actions_migrate_cli.py` (CLI) and any test needing a real
process or a real git repository.
"""

from __future__ import annotations

import copy
import hashlib

import s6_tick as T
import s7_delivery as D
import s7_owner_actions_delivery as OD
from s7_owner_actions_delivery import (
    ACTIONS,
    INTENTS,
    MIGRATIONS,
    NOW,
    PIN,
    TARGET,
    Log,
    MigrationWorld,
    Port,
    Publisher,
    Targets,
    receipt_view,
    rows,
)

OTHER = "other-host"
BINDINGS = "continuation_effective_bindings"
LANE_MIGRATIONS = "host_delivery_migrations"
UNREACHABLE = {
    "pg_tests": "test_pg_* need two PostgreSQL schemas (HARNESS_INTEGRATION): out of scope",
    "migrate_cli": "tests/test_owner_actions_migrate_cli.py is the operator CLI: out of scope",
}


def call(fn, *args, **kwargs):
    return D.call(fn, *args, **kwargs)


# ---- labelled doubles ---------------------------------------------------------------------------------------
class DownTargets(Targets):
    """LABELLED. M7 `tests/test_owner_actions_migration.py::DownTargets`: the target-file port whose reads and/or writes fail
    (an injected outage) over the base port's requests."""

    def __init__(self, base, *, read=False, write=False):
        super().__init__(base.log)
        self.requests, self.read_down, self.write_down = base.requests, read, write

    def request(self, target, plan_id):
        if self.read_down:
            raise OSError("target file unreadable (labelled injected fault)")
        return super().request(target, plan_id)

    def write_request(self, target, plan_id, document):
        if self.write_down:
            raise OSError("target file unwritable (labelled injected fault)")
        super().write_request(target, plan_id, document)


class FaultyLane:
    """LABELLED. A proxy of the REAL lane HostDelivery carrying the fault points of M7 `FakeLane` and `LosingDelivery` on the
    three migration methods: `lose` commits the real call then loses its response (once), `down` fails once before any effect
    (an outage), `refuse` maps a method to a lane refusal raised before the effect (until removed) and `after` runs a hook after
    the real commit (the M7 `finalize_then_move` wrapper). `calls` records every call in order."""

    METHODS = ("stage_migration", "register_migration_plan", "finalize_migration")

    def __init__(self, api, real):
        self.api, self.real = api, real
        self.lose, self.down, self.refuse, self.after, self.calls = set(), set(), {}, {}, []

    def __getattr__(self, name):
        attr = getattr(self.real, name)
        if name not in self.METHODS:
            return attr

        def faulty(*args):
            self.calls.append(name)
            if name in self.down:
                self.down.discard(name)
                raise OSError("lane store unavailable (labelled injected fault)")
            if name in self.refuse:
                raise self.api.DeliveryRefused(self.refuse[name], "labelled")
            result = attr(*args)
            if name in self.after:
                self.after[name](result)
            if name in self.lose:
                self.lose.discard(name)
                raise TimeoutError("response lost after the lane committed (labelled injected fault)")
            return result
        return faulty

    def count(self, name):
        return len([c for c in self.calls if c == name])


class Conductor(T.Conductor):
    """LABELLED. The S6 conductor fixture (`s6_tick.Conductor`, M7 `ConductorFixture`) whose decision names the REAL release of
    the lane's Releases owner instead of a crafted `releases` row."""

    def __init__(self, lane_store, release_id):
        super().__init__(lane_store, pending=False)
        self.release_id = release_id

    def finish(self, launch):
        job = self.jobs[launch]
        with self.lane_store.transaction() as tx:
            operation = tx.get("operations", job["id"])
            lead = tx.get("decisions_pending", operation["decision_id"])
            decision_id = "cond-" + job["id"]
            tx.put("decisions_pending", decision_id, {
                "id": decision_id, "actor": "conductor", "phase": "review_conductor", "status": "succeeded",
                "attempt": 1, "input": lead["input"],
                "message": {"correlation_id": operation["correlation_id"],
                            "what": {"details": {"decision_id": lead["id"]}}},
                "result": {"accepted": True, "reason": "fixture", "execution_ref": "sha256:" + "9" * 64,
                           "deployment": {"status": "queued", "release_id": self.release_id}}})
        self.launches[launch] = "exited"


# ---- worlds ------------------------------------------------------------------------------------------------
class MW(MigrationWorld):
    """`s7_owner_actions_delivery.MigrationWorld` (M7 `world()`: the original completed DELIVERY_PLAN action of a rejected
    source, its plan registered and halted on the REAL lane) with the lane reached through the labelled `FaultyLane`."""

    proxy = None

    def __init__(self, api, **options):
        super().__init__(api, **options)
        self.proxy = FaultyLane(api, self.delivery)

    def lane(self, lane_id):
        assert lane_id == "a"
        return self.proxy or self.delivery

    def overrides(self, **doc):
        """M7 `document(w, **overrides)`."""
        return self.document(**doc)


class PausedWorld(MW):
    """M7 `paused_world` (`tests/test_owner_actions_migration.py`, over `test_continuation.World`): the REAL Fleet and the REAL
    `Continuation` (with `LaneEvidence` over the lane store), a conductor-accepted job whose delivery intent is AWAITING_OWNER,
    the original DELIVERY_PLAN action (labelled crafted, as `MigrationWorld`), its plan registered on the REAL lane and halted
    (`Halted`), and the real tick pausing the family (`delivery_blocked`). Nothing here is a lane fake."""

    def __init__(self, api):
        self.api, self.log = api, Log()
        self.clock = T.ticking()
        self.control = api.MemoryStore()
        self.system = D.build(api, store=D.SerialStore(api), register_plan=False, target_id=TARGET, verified=False,
                              github=D.FakeGitHub(api))
        self.delivery, self.lane_store, self.release = (self.system["delivery"], self.system["store"],
                                                        self.system["release"])
        self.github = self.system["github"]
        self.fleet = api.Fleet(self.control, self.clock, T.tokens())
        self.fleet.register(T.config())
        self.conductor = Conductor(self.lane_store, self.release["id"])
        self.lanes = T.Lanes(api, self.lane_store)
        self.runtime_down = False
        self.document_ = T.policy_document(api)
        self.controller = self.build_controller()
        self.controller.register(self.document_, T.PIN)
        self.publisher, self.targets = Publisher(self.log), Targets(self.log)
        self.port = Port()
        self.evidence, self.mainline, self.withdrawals, self.requalify = None, None, None, None
        self.ports = {"continuation": self.controller, "deliveries": self.lane, "publisher": self.publish_to,
                      "targets": self.targets, "first_activation": self.port}
        self.v2_ports = {}
        self.policy = OD.owner_policy(api, fleet=True)
        self.proxy = None
        self.owner = self.build_owner()
        self.owner.register(self.policy, PIN)
        self.terminal("op-a", "accepted")
        for _ in range(6):
            self.ctick()
            found = self.delivery_intents()
            if found:
                break
        [self.intent] = self.delivery_intents()
        assert self.intent["state"] == api.dc.AWAITING_OWNER, self.intent
        od = api.owner_domain
        with self.control.transaction() as tx:
            policy_row = tx.get(OD.POLICIES, self.policy["id"])
        binding = od.plan_binding(policy_row, self.intent, self.release, None)
        identity = od.action_id(od.DELIVERY_PLAN, binding)
        self.plan = od.build_plan(policy_row["policy"], binding, identity, first_activation=OD.FIRST_ACTIVATION)
        self.old_action = {**od.new_action(od.DELIVERY_PLAN, binding, policy_row,
                                           {"intent_id": self.intent["id"], "lane": "a"}, NOW),
                           "state": od.COMPLETED, "reason_code": "plan_registered", "plan": self.plan,
                           "plan_id": self.plan["plan_id"], "plan_sha256": api.plan_digest(self.plan), "version": 4,
                           "path": od.plan_path(self.plan["plan_id"]), "ref": od.plan_ref(self.plan["plan_id"]),
                           "published_at": NOW}
        self.put(self.control, ACTIONS, identity, self.old_action)
        self.system["plan"] = self.plan
        self.delivery.register(self.plan, D.pin(path=od.plan_path(self.plan["plan_id"])))
        self.lane_halt = OD.Halted(self)
        self.proxy = FaultyLane(api, self.delivery)
        self.ctick()      # the REAL consumer observes the original rejection and pauses the family
        [self.paused] = self.delivery_intents()
        assert (self.paused["state"], self.paused["reason_code"]) == (api.dc.PAUSED, "delivery_blocked"), self.paused

    # ---- the Continuation side ----
    def build_controller(self):
        return self.api.Continuation(self.control, fleet=self.fleet, lanes=self.lanes, conductor=self.conductor,
                                     validate=self.api.validate_manifest, clock=self.clock)

    def runtime(self, lane_id):
        return {"image": T.IMAGE, "profile": "worker-v1", "session_archive_sha256": T.ARCHIVE}

    def ctick(self, controller=None):
        return (controller or self.controller).tick("policy-1", pin_sha256=T.PIN["sha256"], runtime=self.runtime)

    def terminal(self, op_id, status):
        """`s6_tick.World.terminal`, with the lane rows' candidate the REAL release's (the conductor's accepted change)."""
        self.fleet.enqueue("a", T.manifest(self.api, op_id), T.GOAL, [])
        job = self.fleet.admit_one()["job"]
        self.fleet.finalize(job["id"], job["owner_token"], {"status": status, "reason_code": "accepted", "exit_code": 0,
                                                             "owner_handoff": None, "calls": {}})
        candidate = copy.deepcopy(self.release["candidate"])
        task_id, decision_id = "task-" + op_id, "dec-" + op_id
        with self.lane_store.transaction() as tx:
            tx.put("operations", op_id, {"id": op_id, "status": status, "reason_code": "accepted", "task_id": task_id,
                                         "decision_id": decision_id, "correlation_id": "corr-" + op_id})
            tx.put("tasks", task_id, {"id": task_id, "status": "succeeded", "generation": 1, "attempt": 1,
                                      "result": {"candidate": candidate}})
            tx.put("decisions_pending", decision_id, {
                "id": decision_id, "actor": "lead:improvement", "phase": "review_lead", "status": "succeeded",
                "input": {"candidate": candidate},
                "result": {"accepted": True, "execution_ref": "sha256:" + "8" * 64}})

    def delivery_intents(self):
        return [r for r in rows(self.control, INTENTS).values() if r.get("route") == self.api.dc.DELIVERY]

    def source_intent(self):
        [found] = self.delivery_intents()
        return found

    def document(self, **overrides):
        return MigrationWorld.document(self, intent_id=self.paused["id"], **overrides)

    def verifies_successor(self, row):
        """LABELLED stand-in (M7 `lane_verifies_successor`) for the lane controller's verification of the (acknowledged)
        successor: the successor's HostDelivery intent moves verifying -> active."""
        with self.lane_store.transaction() as tx:
            intent = tx.get(D.BUCKET_INTENTS, row["plan_id"])
            held = intent.get("held")
            tx.put(D.BUCKET_INTENTS, row["plan_id"], {**intent, "stage": self.api.ACTIVE})
        return {"held_when_verified": held}


# ---- shared views --------------------------------------------------------------------------------------------
def settle(w, ticks=12, *, restart=False, until=None):
    """M7 `settle`/`owner_ticks`: tick the owner until the migration is terminal (or `until`); `restart` builds a fresh
    coordinator for every tick."""
    results = []
    for _ in range(ticks):
        results.append(receipt_view(w.tick(owner=w.build_owner() if restart else None)))
        state = (w.migration_row() or {}).get("state")
        if state in w.api.owner_domain.TERMINAL or state == until:
            break
    return results


def to_bound(w):
    """M7 `to_bound`: request the migration and tick until it is `bound` (the readiness step is next)."""
    requested = call(w.owner.request_migration, w.document())
    ticks = settle(w, until="bound")
    return requested, ticks, w.migration_row()


def counts(w):
    """M7 `assert_single_lineage` as data: the actions, the lane releases and migration records, the effects each double saw and
    the lane calls."""
    actions = rows(w.control, ACTIONS)
    lane_releases = rows(w.lane_store, "releases")
    published = [e for e in w.log if e[0] == "publish"]
    requested = [e for e in w.log if e[0] == "request"]
    return {"actions": len(actions), "successor_actions": len(w.successors()),
            "lane_releases": len(lane_releases), "lane_migrations": len(rows(w.lane_store, LANE_MIGRATIONS)),
            "publishes": len(published), "request_writes": len(requested),
            "requests": sorted(w.targets.requests), "lane_calls": {name: w.proxy.count(name) for name in w.proxy.METHODS}
            if w.proxy is not None else None}


def lineage(w):
    """The rows of one migration lineage: the migration row, the successor action(s), the lane record and the effective
    binding, with everything the doubles saw and both store digests."""
    row = w.migration_row()
    successors = w.successors()
    binding = rows(w.control, BINDINGS).get(row["subject"]["intent_id"] if row else "intent-1")
    out = {"migration": row, "successors": successors, "binding": binding, "lane_record": w.lane_record(),
           "counts": counts(w), "seen": w.seen(), "original_action_untouched": rows(w.control, ACTIONS).get(
               w.old_action["id"]) == w.old_action, **w.stores()}
    if row is not None and successors:
        action = successors[0]
        out["published_bytes_sha256_is_action"] = hashlib.sha256(
            w.publisher.commits[action["commit"]][1]).hexdigest() == action["bytes_sha256"]
        out["ack_names_action"] = row.get("ack", {}).get("control_action_id") == action["id"]
        out["ack_lineage_is_literal"] = row.get("ack", {}).get("lineage_sha256") == w.api.digest({
            "source_release_id": row["id"], "successor_release_id": row["successor_release_id"],
            "old_plan_id": w.plan["plan_id"], "plan_id": action["plan_id"], "migration_id": row["migration_id"]})
    return out


def snap(store):
    with store.transaction() as tx:
        return {(r["bucket"], r["id"]): copy.deepcopy(r["body"]) for r in tx.records()}


def written(before, after):
    """The rows (bucket, id, canonical body) that are new or changed between two snapshots of one store."""
    return [{"bucket": b, "id": i, "body": body} for (b, i), body in sorted(after.items()) if before.get((b, i)) != body]


# ---- 1. request ------------------------------------------------------------------------------------------------------
def request(api):
    """M7 `test_request_records_one_migration_per_source_replays_identically_and_refuses_any_other`."""
    w = MW(api)
    first = call(w.owner.request_migration, w.document())
    row = w.migration_row()
    replay = call(w.owner.request_migration, w.document())
    other_doc = w.document(evidence="sha256:" + "5" * 64)
    other_doc["approval"] = {**other_doc["approval"], "evidence": other_doc["evidence"]}
    other = call(w.owner.request_migration, other_doc)
    actor = call(w.owner.request_migration, w.document(actor="lead:other"))
    expected = {k: v for k, v in row["request"].items() if k != "migration_id"}
    return {"first": first, "row": row, "replay": replay, "other_evidence": other, "other_actor": actor,
            "migration_id_is_request_id": row["migration_id"] == api.migration_request_id(expected),
            "rows": len(rows(w.control, MIGRATIONS)), "kinds": sorted({a["kind"] for a in w.actions()}),
            "migration_view": w.owner.migration(w.release["id"]), "unknown_view": w.owner.migration("rel-none"),
            **w.stores()}


REFUSED_REQUESTS = (("source_release_id", {"source_release_id": "rel-other"}),
                    ("intent_id", {"intent_id": "intent-missing"}), ("target_id", {"target_id": OTHER}),
                    ("old_plan_id", {"old_plan_id": "own-missing"}), ("old_plan_sha256", {"old_plan_sha256": "0" * 64}),
                    ("candidate_revision", {"candidate_revision": "f" * 40}), ("evidence", {"evidence": "not-a-ref"}))


def request_refusals(api):
    """M7 `test_a_request_not_naming_the_exact_control_records_is_refused_and_writes_nothing` (every override)."""
    out = {}
    for name, overrides in REFUSED_REQUESTS:
        w = MW(api)
        before = w.stores()
        refused = call(w.owner.request_migration, w.document(**overrides))
        extra = call(w.owner.request_migration, {**w.document(), "extra": 1})
        out[name] = {"refused": refused, "extra_field": extra, "row": w.migration_row(),
                     "wrote": w.stores() != before}
    return out


# ---- 2. advance ------------------------------------------------------------------------------------------------------
def ordered(api):
    """M7 `test_the_migration_advances_stage_plan_request_held_registration_binding_ack_in_order`."""
    w = MW(api)
    intent_before = copy.deepcopy(rows(w.control, INTENTS)["intent-1"])
    release_before = copy.deepcopy(rows(w.lane_store, "releases")[w.release["id"]])
    requested = call(w.owner.request_migration, w.document())
    receipts = settle(w)
    row = w.migration_row()
    kinds = [e[0] for e in w.log]
    view = lineage(w)
    again = receipt_view(w.tick())
    return {"requested": requested, "receipts": receipts, "history": [s["state"] for s in row["history"]],
            "log_kinds": kinds, "lineage": view, "source_release_untouched": rows(w.lane_store, "releases")[
                w.release["id"]] == release_before,
            "source_intent_untouched": rows(w.control, INTENTS)["intent-1"] == intent_before,
            "effective": rows(w.control, BINDINGS).get("intent-1"),
            "idle_tick": again, "idle_has_no_migration_action": all(a["kind"] != "evaluator_migration"
                                                                    for a in again["actions"]),
            "after_idle": lineage(w)}


def lost_responses(api):
    """M7 `test_a_lost_response_or_restart_at_any_step_resumes_to_exactly_one_lineage` (every fault point)."""
    out = {}
    for fault in ("stage_migration", "register_migration_plan", "finalize_migration", "publish"):
        w = MW(api)
        if fault == "publish":
            w.publisher.lose = True
        else:
            w.proxy.lose.add(fault)
        requested = call(w.owner.request_migration, w.document())
        receipts = settle(w, ticks=16, restart=True)
        out[fault] = {"requested": requested, "receipts": receipts, "a_named_wait": any(r["waits"] for r in receipts),
                      "lineage": lineage(w)}
    return out


def outage(api):
    """M7 `test_an_outage_waits_in_place_and_never_refuses_or_completes`."""
    w = MW(api)
    requested = call(w.owner.request_migration, w.document())
    w.proxy.down.add("stage_migration")
    down = receipt_view(w.tick())
    at_down = w.migration_row()["state"]
    w.proxy.refuse["finalize_migration"] = "migration_unobservable"
    held = settle(w, ticks=8)
    at_retryable = w.migration_row()
    lane_before_release = w.lane_record()
    del w.proxy.refuse["finalize_migration"]
    done = settle(w)
    return {"requested": requested, "down": down, "state_after_outage": at_down, "held_receipts": held,
            "row_while_retryable": at_retryable, "lane_record_while_retryable": lane_before_release,
            "done": done, "lineage": lineage(w)}


def lane_refusals(api):
    """M7 `test_a_lane_refusal_is_refused_with_the_lane_reason_and_never_completes` (every step)."""
    out = {}
    for step in ("stage_migration", "finalize_migration"):
        w = MW(api)
        w.proxy.refuse[step] = "migration_source_mismatch"
        requested = call(w.owner.request_migration, w.document())
        receipts = settle(w)
        row = w.migration_row()
        out[step] = {"requested": requested, "receipts": receipts, "row": row, "has_ack": "ack" in row,
                     "finalize_calls": w.proxy.count("finalize_migration"),
                     "successor_actions": w.successors(), "lineage": lineage(w)}
    return out


def rival(w):
    """M7 `rival`: another conducted delivery intent (a different release of the same repository lane) on the target. The
    release is the REAL Releases owner's (a candidate of another revision), the intent a LABELLED control row."""
    api = w.api
    candidate = {**D.candidate(), "revision": "4" * 40, "branch": "harness/rival", "task_id": "rival"}
    release = D.reviewed_release(api, w.lane_store, w.system["org"], record_candidate=candidate)
    return {"id": "intent-" + release["id"], "policy_id": "policy-1", "route": api.dc.DELIVERY,
            "state": api.dc.AWAITING_OWNER, "release_id": release["id"], "delivery_target": TARGET, "lane": "a",
            "created_at": NOW, "version": 1}


def policy_row_of(w):
    with w.control.transaction() as tx:
        return tx.get(OD.POLICIES, "owners-1")


def target_busy(api):
    """M7 `test_a_staged_or_registered_migration_keeps_its_target_busy_for_every_other_plan`."""
    w = MW(api)
    requested = call(w.owner.request_migration, w.document())
    w.tick()      # staged in the lane
    staged = w.lane_record()["state"]
    other = rival(w)
    binding = call(api.plan_binding_of, w.owner, policy_row_of(w), other)
    w.put(w.control, INTENTS, other["id"], other)
    waiting = receipt_view(w.tick())
    receipts = settle(w)
    return {"requested": requested, "lane_state_when_staged": staged, "rival_binding": binding,
            "rival_wait": waiting["waits"].get(other["id"]), "waiting_receipt": waiting, "receipts": receipts,
            "migration_state": w.migration_row()["state"], "lane_state_after": w.lane_record()["state"],
            "lineage": lineage(w)}


def target_elsewhere(api):
    """M7 `test_a_migration_reserving_another_target_does_not_block_this_one`."""
    w = MW(api)
    w.put(w.lane_store, LANE_MIGRATIONS, "own-elsewhere", {"id": "own-elsewhere", "migration_id": "m" * 64,
                                                           "state": "staged", "target_id": OTHER})
    old = w.lane_row(D.BUCKET_INTENTS, w.plan["plan_id"])
    w.put(w.lane_store, D.BUCKET_INTENTS, old["plan_id"], {**old, "stage": api.ROLLED_BACK})
    other = rival(w)
    binding = api.plan_binding_of(w.owner, policy_row_of(w), other)
    return {"binding": binding, "is_the_rival": binding is not None and binding["release_id"] == other["release_id"]}


CANDIDATE = {"revision": D.REVISION, "tree": D.TREE, "base": D.BASE, "repository": D.REPOSITORY}


def edge_store(api, *, state="active", successor_candidate=None, reason="release_rejected_superseded"):
    """LABELLED. M7 `edge_store`: the lane rows of one supersession edge (a MemoryStore, crafted as M7 crafts them)."""
    store = api.MemoryStore()
    successor_candidate = dict(CANDIDATE) if successor_candidate is None else successor_candidate
    with store.transaction() as tx:
        tx.put("releases", "rel-old", {"id": "rel-old", "candidate": dict(CANDIDATE)})
        tx.put("releases", "rel-new", {"id": "rel-new", "candidate": successor_candidate})
        tx.put(D.BUCKET_INTENTS, "own-old", {
            "id": "own-old", "plan_id": "own-old", "target_id": TARGET, "release_id": "rel-old",
            "revision": CANDIDATE["revision"], "stage": "withdrawn", "reason_code": reason,
            "supersession": {"migration_id": "m" * 64, "successor_release_id": "rel-new"}})
        tx.put(D.BUCKET_INTENTS, "own-new", {
            "id": "own-new", "plan_id": "own-new", "plan_sha256": "1" * 64, "target_id": TARGET,
            "release_id": "rel-new", "revision": CANDIDATE["revision"], "stage": "verifying"})
        tx.put(LANE_MIGRATIONS, "own-old", {
            "id": "own-old", "migration_id": "m" * 64, "state": state, "source_release_id": "rel-old",
            "successor_release_id": "rel-new", "target_id": TARGET, "plan_id": "own-new", "plan_sha256": "1" * 64})
    return store


def edge(api, store):
    with store.transaction() as tx:
        deliveries = [r for r in tx.scan(D.BUCKET_INTENTS) if r.get("release_id") == "rel-old"]
        return api.migrated_delivery(tx, deliveries, TARGET, "rel-old", CANDIDATE["revision"],
                                     tx.get("releases", "rel-old"))


def successor_edge(api):
    """M7 `test_the_superseded_source_binds_only_its_active_verified_successor_delivery` and
    `test_an_unacknowledged_or_non_identical_successor_is_never_followed` (a memory store of crafted lane rows)."""
    bound = edge(api, edge_store(api))
    out = {"bound": bound, "tuple": api.dc.delivery_tuple(bound) if bound is not None else None}
    never = {"staged": dict(state="staged"), "registered": dict(state="registered"),
             "tree_differs": dict(successor_candidate={**CANDIDATE, "tree": "0" * 40}),
             "base_differs": dict(successor_candidate={**CANDIDATE, "base": "0" * 40}),
             "not_superseded": dict(reason="release_rejected")}
    out["never_followed"] = {name: edge(api, edge_store(api, **kwargs)) for name, kwargs in never.items()}
    return out


def advance(api):
    return {"ordered": ordered(api), "lost_responses": lost_responses(api), "outage": outage(api),
            "lane_refusals": lane_refusals(api), "target_busy": target_busy(api),
            "target_elsewhere": target_elsewhere(api), "successor_edge": successor_edge(api)}


# ---- 3. readiness ----------------------------------------------------------------------------------------------------
def held_tick(w, targets=None, publisher=None):
    """M7 `held_tick`: one tick of a coordinator with the given ports; a readiness wait writes nothing in either store and
    never calls the lane's finalize."""
    ports = {**({"targets": targets} if targets else {}), **({"publisher": (lambda lane_id: publisher)} if publisher
                                                             else {})}
    before = (copy.deepcopy(rows(w.control, MIGRATIONS)), copy.deepcopy(rows(w.lane_store, LANE_MIGRATIONS)),
              w.stores())
    finalizes = w.proxy.count("finalize_migration")
    receipt = receipt_view(w.tick(owner=w.build_owner(**ports)))
    after = (rows(w.control, MIGRATIONS), rows(w.lane_store, LANE_MIGRATIONS), w.stores())
    return {"receipt": receipt, "wrote_nothing": after == before,
            "finalize_calls_added": w.proxy.count("finalize_migration") - finalizes}


HOLDS = (("deleted_refile_fails", "migration_readiness_canary_request_missing"),
         ("unreadable", "migration_readiness_canary_request_unreadable"),
         ("replaced_refile_fails", "migration_readiness_canary_request_replaced"),
         ("pin_unreadable", "migration_readiness_pin_unreadable"),
         ("pin_replaced", "migration_readiness_pin_mismatch"),
         ("source_moved", "migration_readiness_source_intent"),
         ("binding_replaced", "migration_readiness_binding"))


def holds(api):
    """M7 `test_unavailable_or_replaced_readiness_evidence_holds_bound_with_a_named_wait_and_never_finalizes`."""
    out = {}
    for case, reason in HOLDS:
        w = MW(api)
        requested, ticks, row = to_bound(w)
        plan_id, targets, publisher = row["plan_id"], None, None
        if case == "deleted_refile_fails":
            del w.targets.requests[plan_id]
            targets = DownTargets(w.targets, write=True)
        elif case == "unreadable":
            targets = DownTargets(w.targets, read=True)
        elif case == "replaced_refile_fails":
            w.targets.requests[plan_id] = {**w.targets.requests[plan_id], "plan_sha256": "0" * 64}
            targets = DownTargets(w.targets, write=True)
        elif case in {"pin_unreadable", "pin_replaced"}:
            publisher = Publisher(w.log)
            if case == "pin_replaced":
                action = rows(w.control, ACTIONS)[row["plan_action_id"]]
                publisher.commits[action["commit"]] = (action["path"], b'{"replaced": true}\n')
        elif case == "source_moved":
            with w.control.transaction() as tx:
                intent = tx.get(INTENTS, "intent-1")
                tx.put(INTENTS, "intent-1", {**intent, "version": intent["version"] + 1})
        elif case == "binding_replaced":
            with w.control.transaction() as tx:
                bound = tx.get(BINDINGS, "intent-1")
                tx.put(BINDINGS, "intent-1", {**bound, "binding": {**bound["binding"], "plan_sha256": "0" * 64}})
        held = held_tick(w, targets=targets, publisher=publisher)
        out[case] = {"expected_reason": reason, "held": held,
                     "wait_is_expected": held["receipt"]["waits"].get(row["action_id"]) == reason,
                     "migration": w.migration_row(), "lane_state": w.lane_record()["state"]}
    return out


def restored(api):
    """M7 `test_a_restored_readiness_tuple_finalizes_once_and_a_lost_finalize_response_replays_without_readiness`."""
    w = MW(api)
    requested, ticks, row = to_bound(w)
    del w.targets.requests[row["plan_id"]]
    held = held_tick(w, targets=DownTargets(w.targets, write=True))
    w.proxy.lose.add("finalize_migration")
    first = receipt_view(w.tick())          # refiled, re-observed, finalized; the response is lost
    after_first = w.migration_row()
    # The lane already holds the identical ack: the replay completes with NO further readiness read.
    w.targets.requests.clear()
    replay = receipt_view(w.tick(owner=w.build_owner(targets=DownTargets(w.targets, read=True, write=True))))
    done = w.migration_row()
    return {"held": held, "first": first, "state_after_first": after_first["state"],
            "first_wait": first["waits"].get(row["action_id"]), "replay": replay, "done": done,
            "cached": done["finalized"]["cached"], "readiness_is_none": done["readiness"] is None,
            "finalize_calls": w.proxy.count("finalize_migration"),
            "lineage_digest_matches": done["ack"]["lineage_sha256"] == api.migration_lineage_digest(**done["lineage"]),
            "canary_request_is_requested": done["ack"]["canary_request_id"] != "not_requested",
            "lineage": lineage(w)}


def ready_record(api):
    """M7 `test_a_completed_migration_carries_its_observed_ready_record_and_status_shows_the_lineage`."""
    w = MW(api)
    call(w.owner.request_migration, w.document())
    settle(w)
    done = w.migration_row()
    action = rows(w.control, ACTIONS)[done["plan_action_id"]]
    ready = done["readiness"]
    status = w.owner.status("owners-1")["migrations"]
    expected = [{"source_release_id": w.release["id"], "kind": "evaluator_migration", "state": api.owner_domain.COMPLETED,
                 "reason_code": "migration_finalized",
                 "phases": [{"state": h["state"], "reason_code": h["reason_code"], "at": h["at"]}
                            for h in done["history"]][-8:],
                 "successor_release_id": done["successor_release_id"], "plan_id": done["plan_id"],
                 "intent_id": "intent-1", "source_intent_state": api.dc.AWAITING_OWNER,
                 "owner": {"policy_id": "owners-1", "lane": "a"}, "version": done["version"]}]
    return {"done": done, "source_resumed": done["source_resumed"], "ready": ready,
            "ready_names_action": (ready["plan_id"], ready["plan_sha256"], ready["bytes_sha256"]) == (
                action["plan_id"], action["plan_sha256"], action["bytes_sha256"]),
            "canary_request_id_is_digest": ready["canary_request_id"] == done["ack"]["canary_request_id"] == api.digest(
                w.targets.requests[action["plan_id"]]),
            "status": status, "status_is_expected": status == expected,
            "intent_untouched": rows(w.control, INTENTS)["intent-1"] == w.intent}


def readiness(api):
    return {"holds": holds(api), "restored": restored(api), "ready_record": ready_record(api)}


# ---- 4. complete (the unit golden) -----------------------------------------------------------------------------------
def unit(w, *, tick=None):
    """One completing attempt: the control store's snapshot and digest before and after, the exact rows the attempt wrote to
    the control store and to the lane store, and the receipt. `tick` runs the attempt (default: one owner tick)."""
    control_before, lane_before = snap(w.control), snap(w.lane_store)
    digests_before = w.stores()
    receipt = receipt_view((tick or (lambda: w.tick()))())
    control_after, lane_after = snap(w.control), snap(w.lane_store)
    return {"receipt": receipt, "digests_before": digests_before, "digests_after": w.stores(),
            "control_written": written(control_before, control_after), "lane_written": written(lane_before, lane_after),
            "control_rows_removed": sorted(b + "/" + i for b, i in control_before if (b, i) not in control_after)}


def bind_only(w):
    """The `bound` row of an AWAITING_OWNER/PAUSED source (M7 `owner_ticks(until="bound")`)."""
    requested = call(w.owner.request_migration, w.document())
    ticks = settle(w, until="bound")
    row = w.migration_row()
    assert row["state"] == "bound", row["history"]
    return requested, ticks, row


def complete_awaiting(api):
    """The `_complete` unit for an AWAITING_OWNER source (`test_a_completed_migration_carries...`): the resume is a no-op and the
    completing transaction writes the migration row only."""
    w = MW(api)
    requested, ticks, bound = bind_only(w)
    attempt = unit(w)
    row = w.migration_row()
    return {"requested": requested, "ticks": ticks, "bound_row": bound, "attempt": attempt, "completed_row": row,
            "source_resumed": row["source_resumed"], "intent_untouched": rows(w.control, INTENTS)["intent-1"] == w.intent,
            "lineage": lineage(w)}


def complete_paused(api, restart):
    """M7 `test_a_paused_source_is_resumed_once_by_the_finalized_migration_and_the_real_tick_reaches_next_item` (both
    parametrizations): the REAL `Continuation` over the control store, the REAL lane."""
    w = PausedWorld(api)
    dc = api.dc
    requested = call(w.owner.request_migration, w.document())
    snapshot_in_row = w.migration_row()["source_intent"]
    ticks = settle(w, restart=restart, until="bound")
    row = w.migration_row()
    controller = w.build_controller() if restart else w.controller
    w.ctick(controller)
    before_ack = w.source_intent()
    attempt = unit(w, tick=lambda: w.tick(owner=w.build_owner() if restart else None))
    done = w.migration_row()
    resumed = w.source_intent()
    controller = w.build_controller() if restart else w.controller
    w.ctick(controller)      # the successor still verifying: a quiet wait
    still = w.source_intent()
    verified = w.verifies_successor(done)
    w.ctick(w.build_controller() if restart else controller)
    intents = w.delivery_intents()
    delivered = w.source_intent()
    next_items = [r for r in rows(w.control, INTENTS).values() if r.get("route") == dc.NEXT_ITEM]
    settled = rows(w.control, INTENTS)
    idle = settle(w, ticks=2, restart=restart)
    w.ctick()
    record = resumed.get("migration_resume")
    return {"requested": requested, "source_snapshot": snapshot_in_row, "ticks": ticks, "bound_row": row,
            "no_auto_resume_before_ack": before_ack == w.paused, "attempt": attempt, "completed_row": done,
            "source_resumed": done["source_resumed"], "resumed": resumed,
            "resumed_shape": {"state": resumed["state"], "reason_code": resumed["reason_code"],
                              "version_is_next": resumed["version"] == w.paused["version"] + 1,
                              "from": [record["from_state"], record["from_version"], record["paused_reason_code"]],
                              "lineage": [record["migration_id"] == done["migration_id"],
                                          record["plan_id"] == done["plan_id"]],
                              "history_extends_paused": resumed["history"][:-1] == w.paused["history"],
                              "last_previous": resumed["history"][-1]["previous"],
                              "release_id_is_provenance": resumed["release_id"] == w.release["id"]},
            "still_waiting": {"state": still["state"]}, "verified": verified,
            "delivered": {"state": delivered["state"], "reason_code": delivered["reason_code"],
                          "plan_id_is_successor": (delivered.get("delivery_plan") or {}).get("plan_id") == done["plan_id"]},
            "next_item_predecessors": [r["predecessor_intent"] == delivered["id"] for r in next_items],
            "delivery_intents": len(intents), "finalize_calls": w.proxy.count("finalize_migration"),
            "nothing_twice": rows(w.control, INTENTS) == settled, "idle": idle, "lineage": lineage(w)}


def moved_before_finalize(api):
    """M7 `test_a_source_moved_between_bound_and_finalize_is_held_and_never_resumed`."""
    w = PausedWorld(api)
    call(w.owner.request_migration, w.document())
    ticks = settle(w, until="bound")
    row = w.migration_row()
    with w.control.transaction() as tx:          # LABELLED: another owner moved the source (a CAS)
        intent = tx.get(INTENTS, w.paused["id"])
        tx.put(INTENTS, intent["id"], {**intent, "version": intent["version"] + 1})
    moved = w.source_intent()
    lane_before = copy.deepcopy(rows(w.lane_store, LANE_MIGRATIONS))
    attempts = [unit(w) for _ in range(3)]
    w.ctick()
    return {"ticks": ticks, "bound_row": row, "attempts": attempts,
            "waits": [a["receipt"]["waits"].get(row["action_id"]) for a in attempts],
            "row_unchanged": w.migration_row() == row, "lane_unchanged": rows(w.lane_store, LANE_MIGRATIONS) == lane_before,
            "finalize_calls": w.proxy.count("finalize_migration"),
            "paused_stays_paused": w.source_intent() == moved, "lineage": lineage(w)}


def moved_after_ack(api):
    """M7 `test_a_source_moved_after_the_lane_ack_refuses_the_resume_inside_the_completing_transaction`: the refusal inside
    `_complete`'s transaction writes neither the migration row nor the intent (both stay as they were), the lane already
    holding the ack."""
    w = PausedWorld(api)
    call(w.owner.request_migration, w.document())
    ticks = settle(w, until="bound")
    row = w.migration_row()
    moved = {}

    def move(result):          # LABELLED: the source moves after the lane commit
        with w.control.transaction() as tx:
            intent = tx.get(INTENTS, w.paused["id"])
            tx.put(INTENTS, intent["id"], {**intent, "version": intent["version"] + 1})
        moved["digests"] = w.stores()
        moved["control"] = snap(w.control)

    w.proxy.after["finalize_migration"] = move
    attempt = unit(w)
    w.proxy.after.clear()
    control_after = snap(w.control)
    again = unit(w)
    return {"ticks": ticks, "bound_row": row, "attempt": attempt,
            "wait": attempt["receipt"]["waits"].get(row["action_id"]),
            "row_unchanged": w.migration_row() == row,
            "control_written_after_the_move": written(moved["control"], control_after),
            "control_digest_unchanged_by_the_refusal": moved["digests"]["control"] == w.stores()["control"] or None,
            "source_still_paused": w.source_intent()["state"] == api.dc.PAUSED,
            "lane_record": w.lane_record(), "again": again, "again_wait": again["receipt"]["waits"].get(row["action_id"]),
            "lineage": lineage(w)}


def complete(api):
    return {"awaiting_owner": complete_awaiting(api), "paused": complete_paused(api, False),
            "paused_restarted": complete_paused(api, True), "moved_before_finalize": moved_before_finalize(api),
            "moved_after_ack": moved_after_ack(api)}


# ---- 5. the real lane owner ------------------------------------------------------------------------------------------
def real_lane(api):
    """M7 `test_the_real_lane_owner_completes_the_ordered_handoff_from_a_separate_control_store`: the REAL HostDelivery over
    the `s7_delivery` doubles and a SEPARATE control store (every case above already keeps two stores; this one reads the
    lane's own records)."""
    w = MW(api)
    requested = call(w.owner.request_migration, w.document())
    receipts = settle(w)
    row = w.migration_row()
    record = w.lane_record()
    with w.lane_store.transaction() as tx:
        successor_intent = tx.get(D.BUCKET_INTENTS, row["plan_id"])
        queued = tx.get("release_queue", row["successor_release_id"])
        successors = [x for x in tx.scan("releases") if x["id"] == row["successor_release_id"]]
    return {"requested": requested, "receipts": receipts, "row": row, "lane_record": record,
            "same_migration_id": row["migration_id"] == record["migration_id"],
            "ack_is_lane_ack": record["ack"] == row["ack"], "successor_releases": len(successors),
            "successor_not_held": successor_intent["held"] is None, "successor_queued": queued is not None,
            "canary_request_id_is_request": row["ack"]["canary_request_id"] == api.digest(
                w.targets.requests[row["plan_id"]]),
            "log_order": [e[0] for e in w.log][:2], "lineage": lineage(w),
            "separate_stores": w.control is not w.lane_store}


def run(api) -> dict:
    return {"request": {"lifecycle": request(api), "refusals": request_refusals(api)}, "advance": advance(api),
            "readiness": readiness(api), "complete": complete(api), "lane": real_lane(api), "unreachable": UNREACHABLE}
