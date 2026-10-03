"""Ported SOURCE M7 suite `tests/test_environment_reverification_chain.py` (e38aa722) run against the S6/S7 target.

Every assertion is M7's, unchanged. Adaptations, all construction/import: `OwnerActions` comes from the `m7_coordination`
shim (the facade over the split owner-action objects; its docstring names the routing); `MAX_MIGRATION_HOPS` and
`_migrated_delivery` are `coordination.application.continuation.lanes`'s; `BUCKET_ACTIONS`, `BUCKET_MIGRATIONS`,
`BUCKET_POLICIES`, `CONTINUATION_BINDINGS` and `ENVIRONMENT_REVERIFICATION` are
`coordination.application.owner_actions.state`'s; the domain modules `continuation` and `owner_actions` are
`coordination.domain`'s; `plan_digest` and `validate_plan` are `delivery.domain.host_delivery`'s;
`environment_successor_id` is `review.application.releases`'s; `MemoryStore` is `storage.adapters.memory_store`'s. The
sibling helper modules (`test_owner_actions_migration`, `test_host_delivery`) are the ported ones.
- The tests that build `real_env` run (batch U2b): their lazy
  `from test_release_environment_reverification import approval_for, migrated_rejected_plan` is M7's own line, now
  resolving to the module batch P8 ported.

M7 module docstring follows.

INV-RELEASE-ENVIRONMENT-REVERIFY-001 (with INV-OWNER-ACTIONS-MIGRATION-001): the owner's
environment reverification of a migrated, then rejected, successor, and the two-edge continuation chain.

The REAL `OwnerActions` coordinator, the REAL `Continuation` tick (test_continuation World) and the REAL
`LaneEvidence` chain helper are exercised. The lane migration interface is the LABELLED `FakeLane` of
tests/test_owner_actions_migration.py; the successor's rejection and activation are LABELLED synthetic
lane verdicts. Lost responses are LABELLED injected faults. Nothing here is a production verification.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from m7_coordination import OwnerActions
from test_owner_actions_migration import (  # noqa: F401  (second_pgstore is a fixture)
    CANDIDATE,
    NOW,
    TARGET,
    first_activation_port,
    lane_verifies_successor,
    paused_world,
    pg_continuation_world,
    rows,
    second_pgstore,
)

from codex_harness.coordination.application.continuation.lanes import MAX_MIGRATION_HOPS, _migrated_delivery
from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    BUCKET_MIGRATIONS,
    CONTINUATION_BINDINGS,
    ENVIRONMENT_REVERIFICATION,
)
from codex_harness.coordination.domain import continuation as dc
from codex_harness.coordination.domain import owner_actions as do
from codex_harness.coordination.domain.owner_actions import OwnerActionRefused
from codex_harness.storage.adapters.memory_store import MemoryStore

ENV = ENVIRONMENT_REVERIFICATION


def ticks_of(p, source, *, restart=False, until=do.COMPLETED, ticks=12):
    for _ in range(ticks):
        owner = OwnerActions(p["world"].control, clock=lambda: NOW, **p["ports"]) if restart else p["owner"]
        owner.tick("owners-1")
        row = rows(p["world"].control, BUCKET_MIGRATIONS)[source]
        if row["state"] == until or row["state"] in do.TERMINAL:
            break
    return row


def lane_rejects(p, plan_id):
    """LABELLED synthetic verification verdict: the lane controller rejected the successor's delivery."""
    with p["world"].lane.store.transaction() as tx:
        intent = tx.get("host_delivery_intents", plan_id)
        tx.put("host_delivery_intents", plan_id, {**intent, "stage": "blocked", "reason_code": "release_rejected"})


def rejected_successor(tmp_path, *, restart=False, world=None):
    """original rejection -> first (evaluator) migration completed -> successor rejected -> paused."""
    p = paused_world(tmp_path, world)
    world, only = p["world"], p["only"]
    p["owner"].request_migration(p["doc"])
    first = ticks_of(p, p["release_id"], restart=restart)
    assert (first["state"], first["source_resumed"]) == (do.COMPLETED, True), first["history"]
    lane_rejects(p, first["plan_id"])
    world.tick(world.build() if restart else world.controller)
    paused = only(world.intents(), route=dc.DELIVERY)
    assert (paused["state"], paused["reason_code"]) == (dc.PAUSED, "delivery_blocked")
    assert paused["release_id"] == p["release_id"], "the conductor's release stays provenance"
    successor = first["successor_release_id"]
    with world.lane.store.transaction() as tx:
        release = tx.get("releases", successor)
    plan_action = rows(world.control, BUCKET_ACTIONS)[first["plan_action_id"]]
    approval = {"kind": ENV, "source_release_id": successor, "source_policy_hash": release["policy_hash"],
                "old_plan_id": first["plan_id"], "old_plan_sha256": plan_action["plan_sha256"],
                "intent_id": paused["id"], "policy_id": "owners-1", "target_id": TARGET, "lane": "a",
                "fix_evidence": "sha256:" + "5" * 64, "controller_revision": "3" * 40, "approved_by": "lead:root"}
    doc = {"kind": ENV, "policy_id": "owners-1", "intent_id": paused["id"], "lane": "a", "target_id": TARGET,
           "source_release_id": successor, "source_policy_hash": release["policy_hash"],
           "candidate_revision": release["candidate"]["revision"], "old_plan_id": first["plan_id"],
           "old_plan_sha256": plan_action["plan_sha256"], "approval": approval,
           "evidence": "sha256:" + "5" * 64, "actor": "lead:root"}
    return {**p, "first": first, "successor": successor, "paused2": paused, "env": doc}


@pytest.mark.parametrize("restart", [False, True])
def test_the_real_tick_follows_both_edges_from_rejection_to_next_item(tmp_path, restart):
    p = rejected_successor(tmp_path, restart=restart)
    world, only, source = p["world"], p["only"], p["successor"]
    receipt = p["owner"].request_migration(p["env"])
    assert (receipt["cached"], receipt["kind"], receipt["state"]) == (False, ENV, do.INTENDED)
    assert p["owner"].request_migration(deepcopy(p["env"]))["cached"] is True
    row = ticks_of(p, source, restart=restart, until="bound")
    assert row["request"]["kind"] == ENV and row["state"] == "bound"
    world.tick(world.build() if restart else world.controller)
    assert only(world.intents(), route=dc.DELIVERY) == p["paused2"], "no auto-resume before the acknowledgement"
    row = ticks_of(p, source, restart=restart)
    assert (row["state"], row["source_resumed"], row["kind"]) == (do.COMPLETED, True, ENV), row["history"]
    binding = rows(world.control, CONTINUATION_BINDINGS)[p["paused2"]["id"]]
    assert binding["binding"]["successor_release_id"] == row["successor_release_id"]
    assert binding["previous"]["binding"]["successor_release_id"] == source
    resumed = only(world.intents(), route=dc.DELIVERY)
    assert (resumed["state"], resumed["reason_code"], resumed["release_id"]) == (
        dc.AWAITING_OWNER, "migration_resumed", p["release_id"])
    assert resumed["migration_resume"]["migration_id"] == row["migration_id"]
    assert resumed["migration_resume"]["previous"]["migration_id"] == p["first"]["migration_id"]
    world.tick(world.build() if restart else world.controller)      # second successor verifying: wait
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER
    lane_verifies_successor(p, row)                                 # LABELLED synthetic lane activation
    world.tick(world.build() if restart else world.controller)
    intents = world.intents()
    delivered = only(intents, route=dc.DELIVERY)
    assert (delivered["state"], delivered["reason_code"]) == (dc.COMPLETED, "delivery_active")
    assert delivered["delivery_plan"]["plan_id"] == row["plan_id"]
    assert only(intents, route=dc.NEXT_ITEM)["predecessor_intent"] == delivered["id"]
    status = {m["source_release_id"]: m["kind"] for m in p["owner"].status("owners-1")["migrations"]}
    assert status == {p["release_id"]: "evaluator_migration", source: ENV}
    first = rows(world.control, BUCKET_MIGRATIONS)[p["release_id"]]
    assert first == p["first"], "the first migration row stays unchanged history"


def test_the_same_source_under_the_other_kind_is_a_conflict_and_writes_nothing(tmp_path):
    p = rejected_successor(tmp_path)
    p["owner"].request_migration(p["env"])
    before = rows(p["world"].control, BUCKET_MIGRATIONS)
    other = {k: v for k, v in p["env"].items() if k != "kind"}
    other["approval"] = {**p["doc"]["approval"], "source_release_id": p["successor"]}
    other["evidence"] = other["approval"]["evidence"]
    with pytest.raises(OwnerActionRefused) as refused:
        p["owner"].request_migration(other)
    assert refused.value.reason_code == "migration_conflict"
    # the first source under the environment kind conflicts with its evaluator row too
    env_first = {**p["env"], "source_release_id": p["release_id"],
                 "approval": {**p["env"]["approval"], "source_release_id": p["release_id"]}}
    with pytest.raises(OwnerActionRefused) as refused:
        p["owner"].request_migration(env_first)
    assert refused.value.reason_code == "migration_conflict"
    assert rows(p["world"].control, BUCKET_MIGRATIONS) == before


@pytest.mark.parametrize("change, field", [
    (lambda a: a.pop("fix_evidence"), "approval"),
    (lambda a: a.update(extra="x"), "approval"),
    (lambda a: a.update(kind="evaluator_migration"), "kind"),
    (lambda a: a.update(source_release_id="rel-other"), "source_release_id"),
    (lambda a: a.update(old_plan_id="own-other"), "old_plan_id"),
    (lambda a: a.update(old_plan_sha256="0" * 64), "old_plan_sha256"),
    (lambda a: a.update(intent_id="intent-other"), "intent_id"),
    (lambda a: a.update(policy_id="owners-2"), "policy_id"),
    (lambda a: a.update(target_id="other-host"), "target_id"),
    (lambda a: a.update(lane="b"), "lane"),
    (lambda a: a.update(source_policy_hash="0" * 64), "source_policy_hash"),
    (lambda a: a.update(fix_evidence="sha1:" + "5" * 40), "fix_evidence"),
    (lambda a: a.update(controller_revision="3" * 39), "controller_revision"),
    (lambda a: a.update(approved_by=""), "approval"),
])
def test_a_wrong_environment_approval_is_refused_before_any_read_or_effect(tmp_path, change, field):
    p = rejected_successor(tmp_path)
    before_control = rows(p["world"].control, BUCKET_MIGRATIONS)
    lane_log = list(p["log"])
    doc = deepcopy(p["env"])
    change(doc["approval"])
    with pytest.raises(OwnerActionRefused) as refused:
        p["owner"].request_migration(doc)
    assert (refused.value.reason_code, refused.value.field) == ("migration_approval_invalid", field)
    assert rows(p["world"].control, BUCKET_MIGRATIONS) == before_control and p["log"] == lane_log


def test_an_unknown_kind_or_a_source_that_is_not_the_effective_successor_is_refused(tmp_path):
    p = rejected_successor(tmp_path)
    with pytest.raises(OwnerActionRefused) as refused:
        p["owner"].request_migration({**p["env"], "kind": "fresh_base"})
    assert refused.value.reason_code == "migration_document_invalid"
    with p["world"].control.transaction() as tx:
        bound = tx.get(CONTINUATION_BINDINGS, p["paused2"]["id"])
        tx.put(CONTINUATION_BINDINGS, bound["id"], {**bound, "binding": {**bound["binding"],
                                                                         "successor_release_id": "rel-other"}})
    with pytest.raises(OwnerActionRefused) as refused:
        p["owner"].request_migration(p["env"])
    assert refused.value.reason_code == "migration_intent_mismatch"
    assert p["successor"] not in rows(p["world"].control, BUCKET_MIGRATIONS)


def test_an_explicit_evaluator_kind_keeps_the_exact_old_identity(tmp_path):
    p = paused_world(tmp_path)
    explicit = p["owner"].request_migration({**p["doc"], "kind": "evaluator_migration"})
    replay = p["owner"].request_migration(p["doc"])
    assert replay["cached"] is True and replay["action_id"] == explicit["action_id"]
    row = rows(p["world"].control, BUCKET_MIGRATIONS)[p["release_id"]]
    assert "kind" not in row["request"] and "kind" not in row["document"] and row["kind"] == "evaluator_migration"


def test_a_source_moved_before_planning_refuses_and_never_resumes(tmp_path):
    p = rejected_successor(tmp_path)
    p["owner"].request_migration(p["env"])
    ticks_of(p, p["successor"], until="staged")
    with p["world"].control.transaction() as tx:
        intent = tx.get("continuation_intents", p["paused2"]["id"])
        tx.put("continuation_intents", intent["id"], {**intent, "version": intent["version"] + 1})
    row = ticks_of(p, p["successor"])
    assert (row["state"], row["reason_code"]) == (do.REFUSED, "migration_intent_changed")
    assert p["only"](p["world"].intents(), route=dc.DELIVERY)["state"] == dc.PAUSED


# ----- the chain helper over a crafted lane store (LABELLED records; real `_migrated_delivery`) -------
def put_hop(tx, n, *, source, successor, state="active", plan=None):
    plan = plan or f"own-{n}"
    tx.put("host_delivery_migrations", f"own-{n - 1}", {
        "id": f"own-{n - 1}", "migration_id": str(n) * 64, "state": state, "source_release_id": source,
        "successor_release_id": successor, "target_id": TARGET, "plan_id": plan, "plan_sha256": str(n) * 64})


def put_delivery(tx, n, release, *, successor=None, migration=None):
    row = {"id": f"own-{n}", "plan_id": f"own-{n}", "plan_sha256": str(n) * 64 if n else "0" * 64,
           "target_id": TARGET, "release_id": release, "revision": CANDIDATE["revision"], "stage": "verifying"}
    if successor is not None:
        row.update(stage="withdrawn", reason_code="release_rejected_superseded",
                   supersession={"migration_id": migration, "successor_release_id": successor})
    tx.put("host_delivery_intents", row["id"], row)


def chain(*, hop2="active", hop2_successor="rel-2", tree2=None, branch=False, depth3=False):
    store = MemoryStore()
    with store.transaction() as tx:
        for rid in ("rel-0", "rel-1", "rel-2", "rel-3"):
            tx.put("releases", rid, {"id": rid, "candidate": dict(CANDIDATE)})
        if tree2 is not None:
            tx.put("releases", "rel-2", {"id": "rel-2", "candidate": {**CANDIDATE, "tree": tree2}})
        put_delivery(tx, 0, "rel-0", successor="rel-1", migration="1" * 64)
        put_hop(tx, 1, source="rel-0", successor="rel-1")
        put_delivery(tx, 1, "rel-1", successor=hop2_successor, migration="2" * 64)
        put_hop(tx, 2, source="rel-1", successor=hop2_successor, state=hop2)
        if depth3:
            put_delivery(tx, 2, "rel-2", successor="rel-3", migration="3" * 64)
            put_hop(tx, 3, source="rel-2", successor="rel-3")
            put_delivery(tx, 3, "rel-3")
        else:
            put_delivery(tx, 2, "rel-2")
        if branch:
            tx.put("host_delivery_migrations", "own-x", {
                "id": "own-x", "migration_id": "x" * 64, "state": "staged", "source_release_id": "rel-1",
                "successor_release_id": "rel-3", "target_id": TARGET, "plan_id": None, "plan_sha256": None})
    return store


def walk(store):
    with store.transaction() as tx:
        deliveries = [r for r in tx.scan("host_delivery_intents") if r.get("release_id") == "rel-0"]
        return _migrated_delivery(tx, deliveries, TARGET, "rel-0", CANDIDATE["revision"], tx.get("releases", "rel-0"))


def test_a_verified_two_edge_chain_binds_the_final_successor_and_keeps_provenance():
    bound = walk(chain())
    assert MAX_MIGRATION_HOPS == 2
    assert (bound["binding"], bound["release_id"], bound["effective_release_id"], bound["plan_id"],
            bound["stage"]) == (dc.DELIVERY_BOUND, "rel-0", "rel-2", "own-2", "verifying")
    assert [(h["source_release_id"], h["successor_release_id"]) for h in bound["hops"]] == [
        ("rel-0", "rel-1"), ("rel-1", "rel-2")]
    assert bound["migration"] == bound["hops"][-1]
    assert dc.delivery_tuple(bound)["release_id"] == "rel-0"


@pytest.mark.parametrize("state", ["staged", "registered", "stopped"])
def test_a_held_or_stopped_second_hop_is_not_followed(state):
    bound = walk(chain(hop2=state))
    assert (bound["effective_release_id"], bound["plan_id"], bound["stage"], len(bound["hops"])) == (
        "rel-1", "own-1", "withdrawn", 1), "the walk ends at the first successor, as today"


@pytest.mark.parametrize("store", [
    lambda: chain(branch=True),
    lambda: chain(hop2_successor="rel-0"),
    lambda: chain(tree2="0" * 40),
    lambda: chain(depth3=True),
])
def test_a_branch_cycle_candidate_mismatch_or_third_hop_refuses_the_whole_chain(store):
    assert walk(store()) is None


# ----- two isolated PostgreSQL schemas ---------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.parametrize("fault", ["none", "lose:stage_migration", "lose:finalize_migration", "moved"])
def test_pg_environment_reverification_across_two_schemas(tmp_path, request, fault):
    isolated_pgstore, lane_store = request.getfixturevalue("isolated_pgstore"), request.getfixturevalue("second_pgstore")
    world = pg_continuation_world(tmp_path, isolated_pgstore, lane_store)
    p = rejected_successor(tmp_path, restart=True, world=world)
    assert world.control is isolated_pgstore and world.lane.store is lane_store and lane_store is not isolated_pgstore
    kind, _, method = fault.partition(":")
    if kind == "lose":
        p["lane"].lose.add(method)
    p["owner"].request_migration(p["env"])
    if kind == "moved":
        ticks_of(p, p["successor"], restart=True, until="staged")
        with world.control.transaction() as tx:
            intent = tx.get("continuation_intents", p["paused2"]["id"])
            tx.put("continuation_intents", intent["id"], {**intent, "version": intent["version"] + 1})
        row = ticks_of(p, p["successor"], restart=True)
        assert (row["state"], row["reason_code"]) == (do.REFUSED, "migration_intent_changed")
        return
    row = ticks_of(p, p["successor"], restart=True)
    assert (row["state"], row["kind"], row["source_resumed"]) == (do.COMPLETED, ENV, True), row["history"]
    assert len([e for e in p["log"] if e[0] == "stage"]) == 2
    assert len([e for e in p["log"] if e[0] == "finalize"]) == 2
    lane_verifies_successor(p, row)
    world.tick(world.build())
    delivered = p["only"](world.intents(), route=dc.DELIVERY)
    assert (delivered["state"], delivered["delivery_plan"]["plan_id"]) == (dc.COMPLETED, row["plan_id"])
    assert p["only"](world.intents(), route=dc.NEXT_ITEM)["predecessor_intent"] == delivered["id"]


# ----- REAL lane code: B1's HostDelivery/Releases environment kind under a separate control store ------
def real_env(tmp_path, control, lane_store, monkeypatch):
    """REAL lane (`HostDelivery`, `Releases`, `ReleaseQueue`: the lane fixture's real first migration and
    its real rejection verdict of the migrated successor, B1's `migrated_rejected_plan`) and a REAL
    `OwnerActions` over a SEPARATE control store. LABELLED: the publisher and target files, and the
    crafted control history of the completed first migration (its row, effective binding and plan action)."""
    from test_host_delivery import CHECK
    from test_host_delivery import REPOSITORY as LANE_REPOSITORY
    from test_owner_actions_migration import PIN, FakePublisher, FakeTargets, Log, policy_document
    from test_release_environment_reverification import approval_for, migrated_rejected_plan

    from codex_harness.coordination.application.owner_actions.state import BUCKET_POLICIES
    from codex_harness.delivery.domain.host_delivery import plan_digest, validate_plan

    system = migrated_rejected_plan(tmp_path, lane_store, monkeypatch)
    original, source, plan = system["release"], system["migrated"], system["migrated_plan"]
    log = Log()
    publisher, targets = FakePublisher(log), FakeTargets(log)
    policy = policy_document()
    policy["delivery"] = {**policy["delivery"], "target_id": plan["target_id"], "repository": LANE_REPOSITORY,
                          "required_checks": [CHECK]}

    class Stub:
        def policy(self, name):
            return {"id": "policy-1", "policy": {"delivery_target": plan["target_id"]}}

    ports = {"continuation": Stub(), "deliveries": lambda lane_id: system["delivery"],
             "publisher": lambda lane_id: publisher, "targets": targets, "first_activation": first_activation_port}
    owner = OwnerActions(control, clock=lambda: NOW, **ports)
    owner.register(policy, PIN)
    intent = {"id": "intent-1", "policy_id": "policy-1", "route": dc.DELIVERY, "state": dc.PAUSED,
              "reason_code": "delivery_blocked", "release_id": original["id"], "delivery_target": plan["target_id"],
              "lane": "a", "created_at": NOW, "version": 7, "history": []}
    with control.transaction() as tx:
        policy_row = tx.get(BUCKET_POLICIES, "owners-1")
    sha = plan_digest(validate_plan(plan))
    binding = do.plan_binding(policy_row, intent, source, None)
    old_action = {**do.new_action(do.DELIVERY_PLAN, binding, policy_row, {"intent_id": "intent-1", "lane": "a"},
                                  NOW), "state": do.COMPLETED, "plan_id": plan["plan_id"], "plan_sha256": sha,
                  "plan": plan, "version": 4}
    effective = {"intent_id": "intent-1", "source_release_id": original["id"], "successor_release_id": source["id"],
                 "plan_id": plan["plan_id"], "plan_sha256": sha, "target_id": plan["target_id"]}
    with control.transaction() as tx:
        tx.put("continuation_intents", "intent-1", intent)
        tx.put(BUCKET_ACTIONS, old_action["id"], old_action)
        tx.put(BUCKET_MIGRATIONS, original["id"], {
            "id": original["id"], "kind": "evaluator_migration", "state": do.COMPLETED, "policy_id": "owners-1",
            "successor_release_id": source["id"], "subject": {"intent_id": "intent-1", "lane": "a"},
            "created_at": NOW, "version": 9})
        tx.put(CONTINUATION_BINDINGS, "intent-1", {"id": "intent-1", "binding": effective,
                                                   "binding_sha256": "labelled"})
    approval = approval_for(source, old_plan_id=plan["plan_id"], old_plan_sha256=sha, target_id=plan["target_id"],
                            intent_id="intent-1", policy_id="owners-1", lane="a")
    doc = {"kind": ENV, "policy_id": "owners-1", "intent_id": "intent-1", "lane": "a",
           "target_id": plan["target_id"], "source_release_id": source["id"],
           "source_policy_hash": source["policy_hash"], "candidate_revision": source["candidate"]["revision"],
           "old_plan_id": plan["plan_id"], "old_plan_sha256": sha, "approval": approval,
           "evidence": "sha256:" + "5" * 64, "actor": "conductor"}
    return {"system": system, "control": control, "lane_store": lane_store, "owner": owner, "ports": ports,
            "source": source, "original": original, "plan": plan, "doc": doc, "log": log, "targets": targets}


@pytest.mark.parametrize("backend, restart", [
    ("memory", False), ("memory", True),
    pytest.param("postgres", True, marks=pytest.mark.integration)])
def test_the_real_lane_environment_kind_completes_from_a_separate_control_store(tmp_path, monkeypatch, request,
                                                                                backend, restart):
    import test_host_delivery as delivery_fixtures
    from test_owner_actions_migration import SerialStore

    from codex_harness.review.application.releases import environment_successor_id

    if backend == "memory":
        control, lane_store = SerialStore(), delivery_fixtures.SerialStore()
    else:   # two isolated PostgreSQL schemas: control and lane
        control, lane_store = request.getfixturevalue("isolated_pgstore"), request.getfixturevalue("second_pgstore")
        assert control is not lane_store
    r = real_env(tmp_path, control, lane_store, monkeypatch)
    r["owner"].request_migration(r["doc"])
    p = {"world": type("W", (), {"control": r["control"]})(), "ports": r["ports"], "owner": r["owner"]}
    row = ticks_of(p, r["source"]["id"], restart=restart)
    assert (row["state"], row["reason_code"], row["kind"]) == (do.COMPLETED, "migration_finalized", ENV), \
        row["history"]
    assert row["successor_release_id"] == environment_successor_id(r["source"]["id"])
    with r["lane_store"].transaction() as tx:
        record = tx.get("host_delivery_migrations", r["plan"]["plan_id"])
        old = tx.get("host_delivery_intents", r["plan"]["plan_id"])
        held = tx.get("host_delivery_intents", row["plan_id"])
        deliveries = [x for x in tx.scan("host_delivery_intents") if x.get("release_id") == r["original"]["id"]]
        walked = _migrated_delivery(tx, deliveries, r["plan"]["target_id"], r["original"]["id"],
                                    r["original"]["candidate"]["revision"], tx.get("releases", r["original"]["id"]))
    assert (record["kind"], record["state"], record["ack"]) == (ENV, "active", row["ack"])
    assert (old["stage"], old["reason_code"], held["held"]) == ("withdrawn", "release_rejected_superseded", None)
    assert walked is not None, "the REAL lane records form the verified two-edge chain"
    assert (walked["effective_release_id"], walked["plan_id"], len(walked["hops"])) == (
        row["successor_release_id"], row["plan_id"], 2)
    resumed = rows(r["control"], "continuation_intents")["intent-1"]
    assert (resumed["state"], resumed["reason_code"]) == (dc.AWAITING_OWNER, "migration_resumed")


# ----- PR214 review B1: the creation-time controller-code preflight at the owner/lane boundary ---------
def _stores(backend, request):
    import test_host_delivery as delivery_fixtures
    from test_owner_actions_migration import SerialStore

    if backend == "memory":
        return SerialStore(), delivery_fixtures.SerialStore()
    return request.getfixturevalue("isolated_pgstore"), request.getfixturevalue("second_pgstore")


def _everything(store):
    buckets = ("continuation_intents", CONTINUATION_BINDINGS, BUCKET_MIGRATIONS, BUCKET_ACTIONS, "releases",
               "host_delivery_intents", "host_delivery_plans", "host_delivery_migrations", "release_queue",
               "deployment_locks")
    with store.transaction() as tx:
        return {bucket: sorted(tx.scan(bucket), key=lambda r: str(r.get("id"))) for bucket in buckets}


BACKENDS = ["memory", pytest.param("postgres", marks=pytest.mark.integration)]


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("running, code", [("0" * 40, "migration_controller_code_mismatch"),
                                           (None, "migration_controller_code_unavailable")])
def test_wrong_or_unknown_running_controller_code_leaves_everything_unused(tmp_path, monkeypatch, request,
                                                                           backend, running, code):
    """The approval's `controller_revision` is compared with what the lane's trusted port RESOLVES
    for the running code, before the owner request row exists: other or unknown code refuses by name
    and the source, its intent, the source-keyed request identity and the lane are unchanged. The
    identical document then proceeds once the approved code is the running code."""
    from codex_harness.review.application.releases import environment_successor_id

    control, lane_store = _stores(backend, request)
    r = real_env(tmp_path, control, lane_store, monkeypatch)
    delivery, approved = r["system"]["delivery"], r["doc"]["approval"]["controller_revision"]
    before = (_everything(control), _everything(lane_store))
    delivery.controller_code = (lambda: running) if running else None
    with pytest.raises(OwnerActionRefused) as caught:
        r["owner"].request_migration(r["doc"])
    assert (caught.value.reason_code, before) == (code, (_everything(control), _everything(lane_store)))
    delivery.controller_code = lambda: approved
    created = r["owner"].request_migration(r["doc"])
    assert created["cached"] is False, "the refused attempt consumed no request identity"
    assert rows(control, BUCKET_MIGRATIONS)[r["source"]["id"]]["controller_code"] == approved
    p = {"world": type("W", (), {"control": control})(), "ports": r["ports"], "owner": r["owner"]}
    row = ticks_of(p, r["source"]["id"], restart=True)
    assert (row["state"], row["successor_release_id"]) == (do.COMPLETED, environment_successor_id(r["source"]["id"]))
    with lane_store.transaction() as tx:
        receipt = tx.get("releases", row["successor_release_id"])["environment_reverification"]
    assert receipt["controller_resolved"] == approved


@pytest.mark.parametrize("backend", BACKENDS)
def test_code_that_changes_after_the_request_waits_and_never_consumes_the_successor(tmp_path, monkeypatch,
                                                                                    request, backend):
    """Code redeployed between the request and the stage: the lane refuses before any effect and the
    owner row WAITS in `intended` (a named wait, not a verdict); the approved code then completes it."""
    from codex_harness.review.application.releases import environment_successor_id

    control, lane_store = _stores(backend, request)
    r = real_env(tmp_path, control, lane_store, monkeypatch)
    delivery, approved = r["system"]["delivery"], r["doc"]["approval"]["controller_revision"]
    r["owner"].request_migration(r["doc"])
    lane_before = _everything(lane_store)
    delivery.controller_code = lambda: "9" * 40
    p = {"world": type("W", (), {"control": control})(), "ports": r["ports"], "owner": r["owner"]}
    row = ticks_of(p, r["source"]["id"], restart=True, ticks=3)
    assert (row["state"], row["version"]) == (do.INTENDED, 1)
    assert _everything(lane_store) == lane_before
    with lane_store.transaction() as tx:
        assert tx.get("releases", environment_successor_id(r["source"]["id"])) is None
    delivery.controller_code = lambda: approved
    row = ticks_of(p, r["source"]["id"], restart=True)
    assert (row["state"], row["reason_code"]) == (do.COMPLETED, "migration_finalized")
