"""INV-HOST-DELIVERY-001 first activation, prevention in owner plan formation (aibox-migration-001 H1 s5.3).

A target without a current descriptor has nothing for `unchanged` to resolve against, so the owner's
plan must carry the CONCRETE image/profile the lane boundary's trusted port reports, and without them it
is refused before any action row or publication. An upgrade keeps `unchanged` and never asks the port.

The REAL `OwnerActions` coordinator, its DELIVERY_PLAN state machine and the migration successor step are
exercised over SEPARATE control and lane stores. The lane `HostDelivery`, the Git publisher, the target
files and the first-activation port are the LABELLED fakes of tests/test_owner_actions_migration.py (plus
a labelled ordinary `register`). Nothing here resolves a real image or profile or touches a host.
"""
from __future__ import annotations

from copy import deepcopy

import pytest
from test_owner_actions_migration import (
    CANDIDATE,
    FIRST_ACTIVATION,
    NOW,
    PIN,
    TARGET,
    FakeLane,
    FakePublisher,
    FakeTargets,
    Log,
    SerialStore,
    StubContinuation,
    document,
    first_activation_port,
    migration_row,
    policy_document,
    rows,
    settle,
    world,
)

from codex_harness.application.owner_actions import BUCKET_ACTIONS, BUCKET_POLICIES, OwnerActions
from codex_harness.domain import continuation as dc
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import (
    UNCHANGED,
    DeliveryRefused,
    descriptor_digest,
    plan_digest,
)

CONCRETE = {"worker_image": FIRST_ACTIVATION["worker_image"], "profile_digest": FIRST_ACTIVATION["profile_digest"]}
DESCRIPTOR = {"schema": "labelled", "target_id": TARGET, "revision": "1" * 40,       # LABELLED current descriptor
              "worker_image": "sha256:" + "2" * 64, "profile_digest": "3" * 64}


class OrdinaryLane(FakeLane):
    """LABELLED: the FakeLane plus the ordinary (non-migration) `register` of a conducted plan."""

    def register(self, plan, pin):
        sha = plan_digest(plan)
        with self.store.transaction() as tx:
            self.log.append(("register", plan["plan_id"]))
            tx.put("host_delivery_plans", plan["plan_id"], {"plan_id": plan["plan_id"], "plan": plan,
                                                            "plan_sha256": sha, "pin": pin,
                                                            "target_id": plan["target_id"]})
        return {"plan_sha256": sha, "cached": False}


class Port:
    """LABELLED first-activation port: records each consultation; answers, raises or returns `facts`."""

    def __init__(self, facts=FIRST_ACTIVATION, error=None):
        self.facts, self.error, self.calls = facts, error, []

    def __call__(self, lane_id, revision):
        self.calls.append((lane_id, revision))
        if self.error is not None:
            raise self.error
        return deepcopy(self.facts)


def ordinary_world(*, port="default", descriptor=None):
    """One conducted AWAITING_OWNER delivery intent of an approved release with no plan yet."""
    control, lane_store, log = SerialStore(), SerialStore(), Log()
    lane, publisher, targets = OrdinaryLane(lane_store, log), FakePublisher(log), FakeTargets(log)
    port = Port() if port == "default" else port
    ports = {"continuation": StubContinuation(), "deliveries": lambda lane_id: lane,
             "publisher": lambda lane_id: publisher, "targets": targets, "first_activation": port}
    owner = OwnerActions(control, clock=lambda: NOW, **ports)
    owner.register(policy_document(), PIN)
    release = {"id": "rel-1", "candidate": dict(CANDIDATE), "policy_hash": "e" * 64, "status": "verified"}
    intent = {"id": "intent-1", "policy_id": "policy-1", "route": dc.DELIVERY, "state": dc.AWAITING_OWNER,
              "release_id": "rel-1", "delivery_target": TARGET, "lane": "a", "created_at": NOW, "version": 3}
    with control.transaction() as tx:
        tx.put("continuation_intents", intent["id"], intent)
    with lane_store.transaction() as tx:
        tx.put("releases", release["id"], release)
        tx.put("host_delivery_targets", TARGET, {"target_id": TARGET})
        if descriptor is not None:
            tx.put("host_delivery_descriptors", TARGET, {"target_id": TARGET, "descriptor": descriptor})
    return {"control": control, "lane_store": lane_store, "owner": owner, "ports": ports, "port": port,
            "log": log, "publisher": publisher, "targets": targets}


def plan_actions(control):
    return [a for a in rows(control, BUCKET_ACTIONS).values() if a["kind"] == do.DELIVERY_PLAN]


def lane_plan(w, plan_id):
    with w["lane_store"].transaction() as tx:
        return tx.get("host_delivery_plans", plan_id)


def ticks(w, n=5):
    return [w["owner"].tick("owners-1") for _ in range(n)]


# ----- the domain builder ---------------------------------------------------------------------------
def binding_of(expected, facts=None):
    policy_row = {"id": "owners-1", "policy_sha256": "a" * 64}
    intent = {"id": "intent-1", "delivery_target": TARGET}
    release = {"id": "rel-1", "candidate": dict(CANDIDATE), "policy_hash": "e" * 64}
    return do.plan_binding(policy_row, intent, release, expected, first_activation=facts)


def test_a_first_activation_plan_carries_the_concrete_tuple_and_an_upgrade_keeps_unchanged():
    policy = do.validate_policy(policy_document())
    facts = do.first_activation_tuple(FIRST_ACTIVATION)
    first = do.build_plan(policy, binding_of(None, facts), "f" * 64, first_activation=facts)
    assert first["expected_descriptor"] is None
    assert first["target_descriptor"] == {"revision": CANDIDATE["revision"], **CONCRETE}
    upgrade = do.build_plan(policy, binding_of("4" * 64), "f" * 64, first_activation=facts)
    assert upgrade["target_descriptor"] == {"revision": CANDIDATE["revision"], "worker_image": UNCHANGED,
                                            "profile_digest": UNCHANGED}
    # The upgrade binding (and so every existing action identity) is unchanged: no first-activation key.
    assert "first_activation" not in binding_of("4" * 64) and binding_of(None, facts)["first_activation"] == facts


@pytest.mark.parametrize("facts", [
    None, "sha256:" + "9" * 64, {},
    {**FIRST_ACTIVATION, "worker_image": UNCHANGED},
    {**FIRST_ACTIVATION, "worker_image": "zeus/worker:latest"},
    {**FIRST_ACTIVATION, "worker_image": "sha256:" + "9" * 63},
    {**FIRST_ACTIVATION, "worker_image": "sha256:" + "A" * 64},
    {**FIRST_ACTIVATION, "profile_digest": UNCHANGED},
    {**FIRST_ACTIVATION, "profile_digest": "c" * 63},
    {**FIRST_ACTIVATION, "profile_digest": 7},
])
def test_an_absent_or_malformed_first_activation_is_refused_unbound(facts):
    policy = do.validate_policy(policy_document())
    with pytest.raises(do.OwnerActionRefused) as refused:
        do.build_plan(policy, binding_of(None), "f" * 64, first_activation=facts)
    assert (refused.value.reason_code, refused.value.field) == ("first_activation_unbound", "target_descriptor")


def test_the_image_source_revision_is_provenance_only():
    assert do.first_activation_tuple(FIRST_ACTIVATION) == FIRST_ACTIVATION
    assert do.first_activation_tuple({**CONCRETE, "image_source_revision": "labelled"}) == {
        **CONCRETE, "image_source_revision": None}


# ----- the ordinary discovery callsite ----------------------------------------------------------------
def test_the_ordinary_first_activation_publishes_and_registers_the_concrete_tuple():
    w = ordinary_world()
    ticks(w)
    [action] = plan_actions(w["control"])
    assert action["state"] == do.COMPLETED and action["binding"]["first_activation"] == FIRST_ACTIVATION
    plan = action["plan"]
    assert plan["expected_descriptor"] is None
    assert plan["target_descriptor"] == {"revision": CANDIDATE["revision"], **CONCRETE}
    assert lane_plan(w, plan["plan_id"])["plan"] == plan
    # Resolved once, at discovery, with the lane and the candidate revision; publication reuses the binding.
    assert w["port"].calls == [("a", CANDIDATE["revision"])]


def test_an_upgrade_keeps_unchanged_and_never_consults_the_port():
    w = ordinary_world(port=Port(error=AssertionError("the port must not be consulted for an upgrade")),
                       descriptor=DESCRIPTOR)
    ticks(w)
    [action] = plan_actions(w["control"])
    assert action["state"] == do.COMPLETED and "first_activation" not in action["binding"]
    assert action["plan"]["expected_descriptor"] == descriptor_digest(DESCRIPTOR)
    assert action["plan"]["target_descriptor"]["worker_image"] == UNCHANGED
    assert action["plan"]["target_descriptor"]["profile_digest"] == UNCHANGED
    assert w["port"].calls == []


@pytest.mark.parametrize("port, reason", [
    (None, "first_activation_unconfigured"),
    (Port(error=OSError("labelled: lane repository unavailable")), "first_activation_unavailable"),
    (Port(error=KeyError("labelled: lane not configured")), "first_activation_unavailable"),
    (Port(error=DeliveryRefused("first_activation_image_unconfigured")), "first_activation_image_unconfigured"),
    (Port(facts={**FIRST_ACTIVATION, "worker_image": UNCHANGED}), "first_activation_unbound"),
    (Port(facts=None), "first_activation_unbound"),
])
def test_a_missing_failing_or_malformed_port_is_a_named_wait_with_no_action_or_publication(port, reason):
    w = ordinary_world(port=port)
    control, lane = deepcopy(w["control"].inner.data), deepcopy(w["lane_store"].inner.data)
    for receipt in ticks(w, 3):
        assert receipt["created"] == [] and receipt["waits"] == {"intent-1": reason}
    assert plan_actions(w["control"]) == [] and w["log"] == [] and w["publisher"].refs == {}
    assert w["targets"].requests == {}
    assert w["control"].inner.data == control and w["lane_store"].inner.data == lane


def test_a_recovered_port_then_plans_exactly_once():
    port = Port(error=OSError("labelled outage"))
    w = ordinary_world(port=port)
    assert w["owner"].tick("owners-1")["waits"] == {"intent-1": "first_activation_unavailable"}
    port.error = None
    ticks(w)
    [action] = plan_actions(w["control"])
    assert action["state"] == do.COMPLETED and action["plan"]["target_descriptor"]["worker_image"] == \
        FIRST_ACTIVATION["worker_image"]
    assert [e[0] for e in w["log"]] == ["publish", "request", "register"]


def test_a_recorded_intended_row_without_bound_facts_is_refused_before_publication():
    """A DELIVERY_PLAN row recorded before this change (LABELLED crafted row): its binding has a null
    predecessor and no tuple. It is refused, never published, and discovery then binds the tuple."""
    w = ordinary_world()
    with w["control"].transaction() as tx:
        policy_row = tx.get(BUCKET_POLICIES, "owners-1")
    with w["lane_store"].transaction() as tx:
        release = tx.get("releases", "rel-1")
    intent = rows(w["control"], "continuation_intents")["intent-1"]
    legacy = do.plan_binding(policy_row, intent, release, None)
    row = do.new_action(do.DELIVERY_PLAN, legacy, policy_row, {"intent_id": "intent-1", "lane": "a"}, NOW)
    with w["control"].transaction() as tx:
        tx.put(BUCKET_ACTIONS, row["id"], row)
    w["owner"].tick("owners-1")
    refused = rows(w["control"], BUCKET_ACTIONS)[row["id"]]
    assert (refused["state"], refused["reason_code"]) == (do.REFUSED, "first_activation_unbound")
    assert "plan" not in refused and w["log"] == []
    ticks(w)
    [bound] = [a for a in plan_actions(w["control"]) if a["id"] != row["id"]]
    assert bound["state"] == do.COMPLETED and bound["plan"]["target_descriptor"]["profile_digest"] == \
        FIRST_ACTIVATION["profile_digest"]
    assert [e[0] for e in w["log"]] == ["publish", "request", "register"]


# ----- the migration successor callsite -----------------------------------------------------------------
def successor_of(w):
    return [a for a in plan_actions(w["control"]) if (a.get("subject") or {}).get("migration")]


def test_the_migration_successor_of_a_first_activation_carries_the_concrete_tuple():
    w = world()
    w["owner"].request_migration(document(w))
    settle(w)
    assert migration_row(w)["state"] == do.COMPLETED
    [successor] = successor_of(w)
    assert successor["binding"]["first_activation"] == FIRST_ACTIVATION
    assert successor["plan"]["expected_descriptor"] is None
    assert successor["plan"]["target_descriptor"] == {"revision": CANDIDATE["revision"], **CONCRETE}
    assert lane_plan(w, successor["plan_id"])["plan"] == successor["plan"]


def test_the_migration_successor_of_an_upgrade_keeps_unchanged_without_the_port():
    w = world()
    with w["lane_store"].transaction() as tx:
        tx.put("host_delivery_descriptors", TARGET, {"target_id": TARGET, "descriptor": DESCRIPTOR})
    port = Port(error=AssertionError("the port must not be consulted for an upgrade"))
    w["ports"]["first_activation"] = port
    w["owner"] = OwnerActions(w["control"], clock=lambda: NOW, **w["ports"])
    w["owner"].request_migration(document(w))
    settle(w)
    assert migration_row(w)["state"] == do.COMPLETED and port.calls == []
    [successor] = successor_of(w)
    assert "first_activation" not in successor["binding"]
    assert successor["plan"]["expected_descriptor"] == descriptor_digest(DESCRIPTOR)
    assert successor["plan"]["target_descriptor"]["worker_image"] == UNCHANGED


@pytest.mark.parametrize("port, reason", [
    (None, "first_activation_unconfigured"),
    (Port(error=OSError("labelled: lane repository unavailable")), "first_activation_unavailable"),
    (Port(facts={**FIRST_ACTIVATION, "profile_digest": "not-a-digest"}), "first_activation_unbound"),
])
def test_an_unbound_successor_waits_staged_with_no_plan_action_then_completes_once_bound(port, reason):
    w = world()
    w["owner"].request_migration(document(w))
    blocked = OwnerActions(w["control"], clock=lambda: NOW, **{**w["ports"], "first_activation": port})
    for _ in range(4):
        receipt = blocked.tick("owners-1")
    row = migration_row(w)
    assert (row["state"], receipt["waits"]) == ("staged", {row["action_id"]: reason})
    assert successor_of(w) == [] and "publish" not in [e[0] for e in w["log"]]
    assert w["targets"].requests == {}
    # The same staged row proceeds once the port answers: one successor, bound to the concrete tuple.
    w["owner"] = OwnerActions(w["control"], clock=lambda: NOW, **{**w["ports"],
                                                                 "first_activation": first_activation_port})
    settle(w)
    assert migration_row(w)["state"] == do.COMPLETED
    [successor] = successor_of(w)
    assert successor["plan"]["target_descriptor"] == {"revision": CANDIDATE["revision"], **CONCRETE}


# ----- the adapter wiring -------------------------------------------------------------------------------
def test_the_owner_coordinator_binds_the_lane_first_activation_port(tmp_path, monkeypatch):
    """The coordinator resolves the tuple through the lane boundary's `first_activation_facts` (imported
    at call time) for the configured lane, the host settings and the candidate revision. The resolver
    itself is replaced by a LABELLED fake: no Docker, Git or host setting is read here."""
    from types import SimpleNamespace

    import codex_harness.adapters.host_delivery as lane_adapter
    from codex_harness.adapters import owner_actions as adapter
    from codex_harness.adapters.store import MemoryStore
    from codex_harness.bootstrap import organization

    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path / "runtime"))
    seen = []
    monkeypatch.setattr(lane_adapter, "first_activation_facts",
                        lambda lane, host, revision: seen.append((lane, host, revision)) or dict(FIRST_ACTIVATION),
                        raising=False)
    config, host = {"lanes": [{"id": "a", "repository": "labelled-repo"}]}, {"labelled": "host"}
    owner = adapter.coordinator(SimpleNamespace(store=MemoryStore(), org=organization()), config, host,
                                lanes=lambda lane_id: SimpleNamespace(store=MemoryStore()), assessments=object(),
                                continuation=object())
    assert owner.first_activation("a", CANDIDATE["revision"]) == FIRST_ACTIVATION
    assert seen == [(config["lanes"][0], host, CANDIDATE["revision"])]
