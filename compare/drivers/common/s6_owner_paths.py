"""Shared S6 scenario steps (`coordination.continuation_owner_paths`): the OWNER-triggered continuation paths of M7
`Continuation` and `LaneEvidence` (DESIGN-s6 §7; TRACE-s6 §3 and §4), in the sequences of the M7 tests
(tests/test_continuation_requalification.py, tests/test_environment_reverification_chain.py,
tests/test_owner_actions_migration.py, tests/test_continuation_research.py).

- **requalification.** After a conductor acceptance and a `host_delivery_intents` row of the policy target moved to
  `withdrawn` (`reviewed_base_moved`): the named wait that writes nothing; a valid document that supersedes the intent
  and creates the `requalification` intent on the new main (the next tick admits it through the ordinary path); the
  cached replay and `requalification_conflict`; a plan that is not withdrawn; a second requalification while the family
  has an open one; an intent moved during verification; every named refusal of the M7 `REFUSALS` table; the goal
  migration block (accepted with a changed goal digest at main, refused without one, every refusal, a malformed block,
  replay and conflict); tampered stored records and vanished review bytes stop the next effect.
- **migration chain.** `LaneEvidence.read` on a conductor-accepted job whose release delivery was `withdrawn` for
  `release_rejected_superseded`, over LABELLED `host_delivery_migrations` and successor `releases` rows: one hop, two
  hops, a branch, a cycle, a third hop, a candidate mismatch, and a non-active record that ends the walk. The `delivery`
  part of the evidence and the next tick are recorded.
- **migration resume.** The pure `migration_source` and `migration_resume` rules of `domain.continuation`.
- **ownership.** `Continuation.reconcile_ownership` for a successor admitted without inherited ownership.

Layer: harness (never shipped)

`api` is the `s6_tick` API plus: `Continuation(..., evidence=)`, `migration_source`, `migration_resume` and
`MAX_MIGRATION_HOPS`. Every case builds a fresh World from `s6_tick` (extended here only by subclassing). Fixture rows
and doubles are LABELLED: the `Mainline` port (what `git ls-remote` and the lane repository would answer), the
`Evidence` port (`verify(ref)` passes for held refs and raises a plain exception otherwise; M7 maps that to
`research_evidence_unreadable`), the withdrawn `host_delivery_intents` row of the shape `HostDelivery.withdraw` leaves,
the `host_delivery_migrations`/`releases` rows of the chain, and one `portfolio_bindings` row of the owner's binding.
The compared results are the owner-command receipts or refusals, whether a refused call wrote anything, a compact
projection, the final records of both stores by body digest, and the conductor calls and lane reads.
"""

from __future__ import annotations

import hashlib

import s6_routes
from s6_tick import CANDIDATE, PIN, Lanes, World, call, canonical_digest, records

MAIN = "9" * 40                    # the remote main the change is re-derived on (labelled)
BASE = CANDIDATE["base"]
PLAN_ID, PLAN_SHA = "own-h1-plan", "5" * 64
TARGET = "fleet-host"
TREE = CANDIDATE["tree"]
NEW_GOAL = "3" * 64                # the goal blob digest at MAIN after the goal document changed (labelled)
SCHEMA = "urn:zeus:continuation-delivery-requalification:1"
RATIONALE = "Owner decision: the reviewed base moved; re-derive the accepted change on the current main.\n"
REVIEW = "Codex goal-diff review (fixture text): criterion and scope unchanged.\n"
DEFAULT = object()
NOW = "2026-09-30T00:00:00.999999+00:00"


class Mainline:
    """LABELLED double of the lane mainline port. `goals` maps a revision to the goal blob digest there (default
    `goal_sha` at every revision)."""

    def __init__(self, main=MAIN, present=True, goal_sha="b" * 64, error=None, goals=None):
        self.main, self.present, self.goal_sha, self.error, self.reads = main, present, goal_sha, error, 0
        self.goals = dict(goals or {})

    def __call__(self, lane_id):
        assert lane_id == "a"
        return self

    def remote_main(self):
        self.reads += 1
        if self.error is not None:
            raise self.error
        return self.main

    def commit_exists(self, revision):
        return self.present

    def goal(self, revision, path):
        assert path == "docs/GOAL.md"
        return {"mode": "100644", "sha256": self.goals.get(revision, self.goal_sha), "bytes": 3}


class Evidence:
    """LABELLED double of the research-evidence port: `verify(ref)` passes for refs it holds and raises a plain
    exception (an unreadable store) otherwise."""

    def __init__(self):
        self.held = set()

    def put(self, text):
        ref = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.held.add(ref)
        return ref

    def verify(self, ref):
        if ref not in self.held:
            raise FileNotFoundError("evidence bytes unreadable (injected)")


class OLanes(Lanes):
    """The s6_tick lane port plus the two read-only lane methods `requalify_delivery` reads."""

    def __call__(self, lane_id):
        lane = super().__call__(lane_id)
        lane.delivery_intent, lane.release = lane.inner.delivery_intent, lane.inner.release
        return lane


class OWorld(World):
    """`World` with the research-evidence port on the controller and the owner lane reads."""

    def __init__(self, api, *, pending=False, max_corrections=3):
        self.evidence = Evidence()
        super().__init__(api, pending=pending)
        self.document = {**self.document, "max_corrections": max_corrections}
        self.lanes = OLanes(api, self.lane_store)
        self.controller = self.build()

    def build(self):
        return self.api.Continuation(self.control, fleet=self.fleet, lanes=self.lanes, conductor=self.conductor,
                                     validate=self.api.validate_manifest, clock=self.clock, evidence=self.evidence)


# ---- labelled rows and projections ------------------------------------------------------------------
def raw_intents(world):
    with world.control.transaction() as tx:
        return {row["id"]: row for row in tx.scan("continuation_intents")}


def only(world, **match):
    found = [row for row in raw_intents(world).values() if all(row.get(k) == v for k, v in match.items())]
    assert len(found) == 1, found
    return found[0]


def withdraw(world, release_id, *, stage="withdrawn", reason="reviewed_base_moved"):
    """The lane's HostDelivery intent as `HostDelivery.withdraw` leaves it (labelled)."""
    with world.lane_store.transaction() as tx:
        tx.put("host_delivery_intents", PLAN_ID, {
            "id": PLAN_ID, "plan_id": PLAN_ID, "release_id": release_id, "target_id": TARGET,
            "revision": CANDIDATE["revision"], "stage": stage, "plan_sha256": PLAN_SHA, "updated_at": "t",
            "withdrawal": {"reason_code": reason, "evidence_ref": "sha256:" + "e" * 64, "main_effect": "none"}
            if stage == "withdrawn" else None})


def owner_view(world):
    """The owner-path fields of every intent and the stored owner documents (compact)."""
    with world.control.transaction() as tx:
        stored = tx.scan("continuation_requalifications")
    intents = []
    for row in sorted(raw_intents(world).values(), key=lambda r: (str(r.get("created_at")), r["id"])):
        if row.get("route") in ("host_delivery", "requalification") or row.get("superseded_by"):
            intents.append({"id": row["id"], "route": row.get("route"), "state": row.get("state"),
                            "reason_code": row.get("reason_code"), "superseded_by": row.get("superseded_by"),
                            "requalification": row.get("requalification"), "goal": row.get("goal"),
                            "base_revision": (row.get("manifest") or {}).get("base_revision"),
                            "manifest_goal": ((row.get("manifest") or {}).get("goal") or {}).get("sha256"),
                            "binding": (row.get("binding") or {}).get("predecessor"),
                            "session_mode": row.get("session_mode"), "version": row.get("version"),
                            "history": [[e.get("state"), e.get("reason_code")] for e in row.get("history") or []]})
    return {"intents": intents,
            "stored": sorted([{k: row.get(k) for k in ("id", "document_sha256", "requalification_intent",
                                                       "successor_job", "goal_migration", "superseded")}
                              for row in stored], key=lambda r: r["id"])}


def digests(world):
    return records(world.control), records(world.lane_store)


def guarded(world, fn, *args, **kwargs):
    """`call`, plus whether the call left every record of both stores unchanged."""
    before = digests(world)
    out = call(fn, *args, **kwargs)
    out["records_unchanged"] = before == digests(world)
    return out


def withdrawn_world(api, **kwargs):
    """A conductor-accepted item, the delivery intent AWAITING_OWNER, the lane plan withdrawn by the owner."""
    world = OWorld(api, **kwargs)
    world.register()
    world.terminal("op-a", "accepted")
    call(world.tick)
    call(world.tick)
    delivery = only(world, route="host_delivery")
    assert delivery["state"] == "awaiting_owner", delivery
    withdraw(world, delivery["release_id"])
    return world, delivery, world.evidence.put(RATIONALE)


def document(delivery, rationale, **overrides):
    return {"schema": SCHEMA, "policy_id": "policy-1", "policy_sha256": delivery["policy_sha256"],
            "intent_id": delivery["id"], "family": delivery["family"], "release_id": delivery["release_id"],
            "candidate": {"revision": CANDIDATE["revision"], "tree": TREE, "base": BASE},
            "plan": {"plan_id": PLAN_ID, "plan_sha256": PLAN_SHA}, "withdrawal_reason": "reviewed_base_moved",
            "main_revision": MAIN, "rationale_ref": rationale, **overrides}


def requalify(world, doc, mainline=None, pin=DEFAULT, runtime=None):
    return world.controller.requalify_delivery(doc, pin_sha256=PIN["sha256"] if pin is DEFAULT else pin,
                                               runtime=runtime or world.runtime, mainline=mainline or Mainline())


def moved_goal(**kwargs):
    """The goal document changed between the origin's base and MAIN (labelled double)."""
    return Mainline(goals={MAIN: NEW_GOAL, **kwargs.pop("goals", {})}, **kwargs)


def migration(review, **overrides):
    return {"path": "docs/GOAL.md", "criterion": "crit", "from_sha256": "b" * 64, "to_sha256": NEW_GOAL,
            "review_ref": review, **overrides}


def twin_of(world, delivery):
    """Another delivery intent of the same family (labelled row)."""
    twin = {**delivery, "id": "1" * 64, "state": "awaiting_owner"}
    with world.control.transaction() as tx:
        tx.put("continuation_intents", twin["id"], twin)
    return twin


# ---- 1. requalification -----------------------------------------------------------------------------
def unproven(api) -> dict:
    """Each named refusal of the M7 `REFUSALS` table (labelled rows reach all of them) writes nothing."""
    cases = {
        "requalification_unverified": dict(pin=None),
        "requalification_policy_foreign": dict(doc={"policy_sha256": "0" * 64}),
        "requalification_intent_unknown": dict(doc={"intent_id": "0" * 64}),
        "requalification_intent_mismatch": dict(doc={"family": "other-family"}),
        "requalification_plan_mismatch": dict(doc={"plan": {"plan_id": PLAN_ID, "plan_sha256": "6" * 64}}),
        "requalification_reason_mismatch": dict(doc={"withdrawal_reason": "descriptor_predecessor_moved"}),
        "requalification_candidate_mismatch": dict(doc={"candidate": {"revision": CANDIDATE["revision"],
                                                                       "tree": TREE, "base": "1" * 40}}),
        "requalification_main_changed": dict(mainline=lambda: Mainline(main="8" * 40)),
        "requalification_main_missing": dict(mainline=lambda: Mainline(present=False)),
        "requalification_main_not_moved": dict(doc={"main_revision": BASE}, mainline=lambda: Mainline(main=BASE)),
        "requalification_goal_changed": dict(mainline=lambda: Mainline(goal_sha="0" * 64)),
        "requalification_main_unreadable": dict(mainline=lambda: Mainline(error=TimeoutError("git timed out"))),
        "requalification_rationale_missing": dict(doc={"rationale_ref": "sha256:" + "0" * 64}),
        "image_changed": dict(runtime=lambda lane: {"image": "other@sha256:" + "0" * 64, "profile": "worker-v1",
                                                    "session_archive_sha256": "d" * 64}),
        "requalification_invalid": dict(doc={"main_revision": "HEAD"}),
        "requalification_reason_unsupported": dict(doc={"withdrawal_reason": "because"}),
    }
    out = {}
    for name in sorted(cases):
        world, delivery, rationale = withdrawn_world(api)
        case = cases[name]
        mainline = case["mainline"]() if "mainline" in case else None
        kwargs = {key: case[key] for key in ("pin", "runtime") if key in case}
        out[name] = guarded(world, requalify, world, document(delivery, rationale, **case.get("doc", {})),
                            mainline, **kwargs)
    return out


def supersede(api) -> dict:
    out = {}
    world, delivery, rationale = withdrawn_world(api)
    before = owner_view(world)
    lane_before = records(world.lane_store)
    waits = []
    for controller in (world.controller, world.build()):   # restart: the same wait, no write
        control = records(world.control)
        waits.append({"tick": call(world.tick, controller=controller),
                      "records_unchanged": control == records(world.control)})
    out["withdrawn_wait"] = {"waits": waits, "view": owner_view(world), "before": before}
    first = guarded(world, requalify, world, document(delivery, rationale))
    new = only(world, route="requalification")
    out["requalify"] = {"first": first, "view": owner_view(world), "jobs": s6_routes.jobs(world),
                        "lane_unchanged": lane_before == records(world.lane_store)}
    out["replay"] = guarded(world, requalify, world, document(delivery, rationale))
    other = world.evidence.put(RATIONALE + "second\n")
    out["conflict"] = guarded(world, requalify, world, document(delivery, other))
    status = call(world.controller.status, "policy-1")
    projected = {row["id"]: row for row in (status.get("value") or {}).get("intents") or []}
    out["status"] = {"requalifications": (status.get("value") or {}).get("requalifications"),
                     "superseded_next_action": (projected.get(delivery["id"]) or {}).get("next_action"),
                     "superseded_by": (projected.get(delivery["id"]) or {}).get("superseded_by")}
    out["ownership_on_requalification"] = guarded(world, world.controller.reconcile_ownership, new["id"])
    admitted = call(world.tick)
    out["admission"] = {"tick": admitted, "view": owner_view(world), "jobs": s6_routes.jobs(world),
                        "bindings": s6_routes.bindings(world), "again": s6_routes.settled(world, 2),
                        "state": world.state()}
    return out


def open_and_moved(api) -> dict:
    out = {}
    world, delivery, rationale = withdrawn_world(api)
    withdraw(world, delivery["release_id"], stage="awaiting_ci")
    out["not_withdrawn"] = {"refused": guarded(world, requalify, world, document(delivery, rationale)),
                            "delivery_state": only(world, route="host_delivery")["state"]}
    world, delivery, rationale = withdrawn_world(api)

    class Racing(Mainline):
        def remote_main(self):   # labelled: another writer moves the intent between read and commit
            with world.control.transaction() as tx:
                row = tx.get("continuation_intents", delivery["id"])
                tx.put("continuation_intents", row["id"], {**row, "version": row["version"] + 1})
            return super().remote_main()
    out["moved_during_verification"] = {
        "refused": call(requalify, world, document(delivery, rationale), Racing()),
        "requalification_created": any(r["route"] == "requalification" for r in raw_intents(world).values()),
        "stored": owner_view(world)["stored"]}
    world, delivery, rationale = withdrawn_world(api)
    first = call(requalify, world, document(delivery, rationale))
    twin = twin_of(world, delivery)
    out["family_open"] = {"first": first, "second": guarded(
        world, requalify, world, document(delivery, rationale, intent_id=twin["id"])) | {"twin": twin["id"]}}
    return out


def goal_migration(api) -> dict:
    out = {}
    world, delivery, rationale = withdrawn_world(api)
    review = world.evidence.put(REVIEW)
    plain = guarded(world, requalify, world, document(delivery, rationale), moved_goal())
    out["without_block_refused"] = plain
    first = guarded(world, requalify, world, document(delivery, rationale, goal_migration=migration(review)),
                    moved_goal())
    out["accepted"] = {"first": first, "view": owner_view(world)}
    out["replay"] = guarded(world, requalify, world,
                            document(delivery, rationale, goal_migration=migration(review)), moved_goal())
    other = world.evidence.put(REVIEW + "second reviewer\n")
    out["conflicts"] = {
        "no_block": guarded(world, requalify, world, document(delivery, rationale), moved_goal()),
        "other_review": guarded(world, requalify, world,
                                document(delivery, rationale, goal_migration=migration(other)), moved_goal())}
    status = call(world.controller.status, "policy-1")
    out["status_migration"] = [row.get("goal_migration") for row in (status.get("value") or {}).get(
        "requalifications") or []]
    out["admission"] = {"tick": call(world.tick), "view": owner_view(world), "jobs": s6_routes.jobs(world),
                        "again": s6_routes.settled(world, 1), "state": world.state()}
    refusals = {
        "from_not_the_stored_binding": (dict(from_sha256="0" * 64), {}),
        "from_not_the_origin_base_blob": ({}, {BASE: "0" * 64}),
        "to_not_the_main_blob": (dict(to_sha256="d" * 64), {}),
        "goal_unchanged_at_main": ({}, {MAIN: "b" * 64}),
        "other_path": (dict(path="docs/OTHER.md"), {}),
        "wider_criterion": (dict(criterion="crit and more"), {}),
        "same_digests": (dict(to_sha256="b" * 64), {}),
        "unknown_field": (dict(allowed_paths=["docs/z.md"]), {}),
        "review_missing": (dict(review_ref="sha256:" + "0" * 64), {}),
    }
    out["refusals"] = {}
    for name in sorted(refusals):
        world, delivery, rationale = withdrawn_world(api)
        review = world.evidence.put(REVIEW)
        overrides, goals = refusals[name]
        out["refusals"][name] = guarded(world, requalify, world, document(
            delivery, rationale, goal_migration=migration(review, **overrides)), moved_goal(goals=goals))
    out["malformed"] = {}
    for name in ("null", "review_is_the_rationale", "not_a_ref", "unsafe_path"):
        world, delivery, rationale = withdrawn_world(api)
        review = world.evidence.put(REVIEW)
        value = {"null": None, "review_is_the_rationale": migration(rationale), "not_a_ref": migration("latest"),
                 "unsafe_path": migration(review, path="../GOAL.md")}[name]
        refused = guarded(world, requalify, world, document(delivery, rationale, goal_migration=value), moved_goal())
        out["malformed"][name] = refused
    return out


def tampered(api) -> dict:
    out = {}

    def edit(world, delivery, change):
        with world.control.transaction() as tx:   # labelled tamper of the stored owner record
            row = tx.get("continuation_requalifications", delivery["id"])
            change(row)
            tx.put("continuation_requalifications", row["id"], row)

    def next_tick(world):
        return {"tick": call(world.tick), "view": owner_view(world), "bindings": s6_routes.bindings(world)}

    world, delivery, rationale = withdrawn_world(api)
    call(requalify, world, document(delivery, rationale))
    edit(world, delivery, lambda row: row["document"].update(main_revision="8" * 40))
    out["document_main_revision"] = next_tick(world)
    for where in ("document", "comparison"):
        world, delivery, rationale = withdrawn_world(api)
        review = world.evidence.put(REVIEW)
        call(requalify, world, document(delivery, rationale, goal_migration=migration(review)), moved_goal())
        if where == "document":
            edit(world, delivery, lambda row: row["document"]["goal_migration"].update(to_sha256="d" * 64))
        else:
            edit(world, delivery, lambda row: row["goal_migration"]["to"].update(sha256="d" * 64))
        out["goal_migration_" + where] = next_tick(world)
    world, delivery, rationale = withdrawn_world(api)
    review = world.evidence.put(REVIEW)
    call(requalify, world, document(delivery, rationale, goal_migration=migration(review)), moved_goal())
    world.evidence.held.discard(review)   # labelled: the review bytes changed after recording
    out["review_bytes_gone"] = next_tick(world)
    return out


def requalification(api) -> dict:
    return {"unproven": unproven(api), "supersede": supersede(api), "open_and_moved": open_and_moved(api),
            "goal_migration": goal_migration(api), "tampered": tampered(api)}


# ---- 2. migration chain -----------------------------------------------------------------------------
def put_hop(tx, n, *, source, successor, state="active"):
    tx.put("host_delivery_migrations", "own-%d" % (n - 1), {
        "id": "own-%d" % (n - 1), "migration_id": str(n) * 64, "state": state, "source_release_id": source,
        "successor_release_id": successor, "target_id": TARGET, "plan_id": "own-%d" % n, "plan_sha256": str(n) * 64})


def put_delivery(tx, n, release, *, successor=None, migration_id=None):
    row = {"id": "own-%d" % n, "plan_id": "own-%d" % n, "plan_sha256": str(n) * 64 if n else "0" * 64,
           "target_id": TARGET, "release_id": release, "revision": CANDIDATE["revision"], "stage": "verifying"}
    if successor is not None:
        row.update(stage="withdrawn", reason_code="release_rejected_superseded",
                   supersession={"migration_id": migration_id, "successor_release_id": successor})
    tx.put("host_delivery_intents", row["id"], row)


def seed_chain(world, *, records_on=True, hop1="active", hop2="active", hop2_successor="rel-2", tree2=None,
               branch=False, depth3=False):
    """LABELLED lane rows of a release chain rel-op-a -> rel-1 -> rel-2 (-> rel-3), as the M7 chain test crafts them."""
    with world.lane_store.transaction() as tx:
        for rid in ("rel-1", "rel-2", "rel-3"):
            tx.put("releases", rid, {"id": rid, "candidate": dict(CANDIDATE)})
        if tree2 is not None:
            tx.put("releases", "rel-2", {"id": "rel-2", "candidate": {**CANDIDATE, "tree": tree2}})
        put_delivery(tx, 0, "rel-op-a", successor="rel-1", migration_id="1" * 64)
        if not records_on:
            return
        put_hop(tx, 1, source="rel-op-a", successor="rel-1", state=hop1)
        put_delivery(tx, 1, "rel-1", successor=hop2_successor, migration_id="2" * 64)
        put_hop(tx, 2, source="rel-1", successor=hop2_successor, state=hop2)
        if depth3:
            put_delivery(tx, 2, "rel-2", successor="rel-3", migration_id="3" * 64)
            put_hop(tx, 3, source="rel-2", successor="rel-3")
            put_delivery(tx, 3, "rel-3")
        else:
            put_delivery(tx, 2, "rel-2")
        if branch:
            tx.put("host_delivery_migrations", "own-x", {
                "id": "own-x", "migration_id": "x" * 64, "state": "staged", "source_release_id": "rel-1",
                "successor_release_id": "rel-3", "target_id": TARGET, "plan_id": None, "plan_sha256": None})


def chain_case(api, **kwargs) -> dict:
    world = OWorld(api)
    world.register()
    world.terminal("op-a", "accepted")
    dispatched = call(world.tick)
    seed_chain(world, **kwargs)
    with world.control.transaction() as tx:
        job = tx.get("fleet_jobs", "op-a")
    delivery = api.LaneEvidence(world.lane_store).read(job, TARGET)["delivery"]
    tick = call(world.tick)
    return {"dispatched": dispatched, "delivery": delivery, "tick": tick, "intents": s6_routes.intents(world),
            "again": s6_routes.settled(world, 2), "state": world.state()}


def migration_chain(api) -> dict:
    out = {"max_migration_hops": api.MAX_MIGRATION_HOPS}
    cases = {
        "no_migration_records": dict(records_on=False),
        "two_hops": {},
        "branch": dict(branch=True),
        "cycle": dict(hop2_successor="rel-op-a"),
        "beyond_max_hops": dict(depth3=True),
        "first_hop_not_active": dict(hop1="staged"),
        "one_hop_second_staged": dict(hop2="staged"),
        "second_hop_registered": dict(hop2="registered"),
        "second_hop_stopped": dict(hop2="stopped"),
        "successor_candidate_mismatch": dict(tree2="0" * 40),
    }
    for name in sorted(cases):
        out[name] = chain_case(api, **cases[name])
    return out


# ---- 3. migration resume ----------------------------------------------------------------------------
def migration_resume(api) -> dict:
    out = {}
    world = OWorld(api)
    world.register()
    world.terminal("op-a", "accepted")
    call(world.tick)
    call(world.tick)
    awaiting = only(world, route="host_delivery")
    paused_world = OWorld(api)
    paused_world.register()
    paused_world.terminal("op-a", "accepted")
    call(paused_world.tick)
    call(paused_world.tick)
    s6_routes.deliver(paused_world, "plan-1", "rel-op-a", "rolled_back")
    call(paused_world.tick)
    paused = only(paused_world, route="host_delivery")
    lineage = {"migration_id": "m" * 64, "plan_id": "own-x"}
    out["states"] = {"awaiting": awaiting["state"], "paused": paused["state"]}
    out["source_awaiting"] = api.migration_source(awaiting)
    out["source_paused"] = api.migration_source(paused)

    def resumed(current, recorded):
        result = call(api.migration_resume, current, recorded, lineage, NOW)
        value = result.get("value")
        if isinstance(value, dict):
            result["value"] = {"row": value, "digest": canonical_digest(value)}
        return result

    out["from_paused"] = resumed(paused, api.migration_source(paused))
    out["from_awaiting"] = resumed(awaiting, api.migration_source(awaiting))
    out["source_changed_version"] = resumed({**paused, "version": paused["version"] + 1}, api.migration_source(paused))
    out["source_changed_state"] = resumed({**paused, "state": "awaiting_owner"}, api.migration_source(paused))
    out["source_changed_release"] = resumed({**paused, "release_id": "rel-other"}, api.migration_source(paused))
    out["current_missing"] = resumed(None, api.migration_source(paused))
    outside = {**paused, "state": "completed"}
    out["recorded_state_outside"] = resumed(outside, api.migration_source(outside))
    again = call(api.migration_resume, paused, api.migration_source(paused), lineage, NOW)["value"]
    second = {**again, "state": "paused"}   # labelled: the resumed row paused again, keeping its resume record
    out["second_hop_keeps_previous"] = resumed(second, api.migration_source(second))
    return out


# ---- 4. ownership reconciliation --------------------------------------------------------------------
def bind_origin(world, job_id, project="ops"):
    """The owner's `portfolio_bindings` row (LABELLED; the shape `Portfolio.bind` writes)."""
    with world.control.transaction() as tx:
        tx.put("portfolio_bindings", job_id, {"id": job_id, "job_id": job_id, "project_id": project,
                                              "criterion_id": "c1", "recorded_by": "owner", "created_at": "t"})


def portfolio_rows(world):
    with world.control.transaction() as tx:
        rows = tx.scan("portfolio_bindings")
    return sorted([{k: r.get(k) for k in ("job_id", "project_id", "criterion_id", "recorded_by", "lineage",
                                          "authority")} for r in rows], key=lambda r: r["job_id"])


def ownership(api) -> dict:
    out = {}
    world = OWorld(api)
    world.register()
    world.terminal("op-1", "rejected")
    first = call(world.tick)
    correction = only(world, route="correction")
    before = (s6_routes.intents(world), s6_routes.jobs(world))
    out["admitted"] = {"first": first, "ownership": correction.get("ownership"), "successor": correction["successor_job"],
                       "state": correction["state"]}
    out["unbound_origin"] = guarded(world, world.controller.reconcile_ownership, correction["id"])
    bind_origin(world, "op-1")
    out["reconciled"] = call(world.controller.reconcile_ownership, correction["id"])
    out["replay"] = call(world.controller.reconcile_ownership, correction["id"])
    out["binding_rows"] = portfolio_rows(world)
    out["intents_and_jobs_unchanged"] = before == (s6_routes.intents(world), s6_routes.jobs(world))
    out["state"] = world.state()

    invalid = {}
    world = OWorld(api)
    world.register()
    world.terminal("op-a", "accepted")
    call(world.tick)
    call(world.tick)
    for route in ("conductor_review", "host_delivery"):
        invalid[route] = guarded(world, world.controller.reconcile_ownership, only(world, route=route)["id"])
    invalid["unknown"] = guarded(world, world.controller.reconcile_ownership, "0" * 64)
    invalid["empty"] = guarded(world, world.controller.reconcile_ownership, "")
    invalid["not_a_string"] = guarded(world, world.controller.reconcile_ownership, None)
    out["intent_invalid"] = invalid

    lineage = {}
    world = OWorld(api)
    world.register()
    world.terminal("op-x", "rejected")
    call(world.tick)
    child = only(world, route="correction")
    bind_origin(world, "op-x")

    def fleet_job(job_id):
        with world.control.transaction() as tx:
            return tx.get("fleet_jobs", job_id)

    def put_job(job):
        with world.control.transaction() as tx:
            tx.put("fleet_jobs", job["id"], job)

    successor, origin = fleet_job(child["successor_job"]), fleet_job("op-x")
    put_job({**successor, "manifest": {**successor["manifest"], "id": "op-forged"}})   # labelled injected fault
    lineage["successor_manifest_forged"] = guarded(world, world.controller.reconcile_ownership, child["id"])
    put_job(successor)
    put_job({**origin, "lane": "b"})
    lineage["origin_lane_changed"] = guarded(world, world.controller.reconcile_ownership, child["id"])
    put_job(origin)
    lineage["restored"] = call(world.controller.reconcile_ownership, child["id"])
    out["lineage"] = lineage

    world = OWorld(api)
    world.register()
    world.terminal("op-y", "rejected")
    call(world.tick)
    child = only(world, route="correction")
    bind_origin(world, "op-y")
    bind_origin(world, child["successor_job"], project="other")
    out["binding_conflict"] = {"refused": guarded(world, world.controller.reconcile_ownership, child["id"]),
                               "rows": portfolio_rows(world)}
    return out


def run(api) -> dict:
    return {"requalification": requalification(api), "migration_chain": migration_chain(api),
            "migration_resume": migration_resume(api), "ownership": ownership(api)}
