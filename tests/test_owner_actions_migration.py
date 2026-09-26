"""INV-OWNER-ACTIONS-MIGRATION-001: the control half of the H1 evaluator migration.

A SEPARATE control store and lane store (two SerialStores: a nested transaction fails loudly). The lane
`HostDelivery` is a LABELLED fake (`FakeLane`) implementing the pinned lane interface
(`stage_migration`, `register_migration_plan`, `finalize_migration`, `approval`); the Git publisher and
the target-file port are LABELLED fakes too. The real `OwnerActions` coordinator, its real
DELIVERY_PLAN state machine and the real `LaneEvidence` edge helper are exercised. Lost responses and
outages are LABELLED injected faults; nothing here is a production verification.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy

import pytest

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.continuation import _migrated_delivery
from codex_harness.application.owner_actions import (
    BUCKET_ACTIONS,
    BUCKET_MIGRATIONS,
    BUCKET_POLICIES,
    CONTINUATION_BINDINGS,
    OwnerActions,
    lineage_of,
    plan_json,
)
from codex_harness.domain import continuation as dc
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import (
    CANARY_FLEET,
    MIGRATION_ACK_FIELDS,
    DeliveryRefused,
    migration_request_id,
    plan_digest,
)
from codex_harness.domain.model import digest

TARGET, OTHER = "fleet-host", "other-host"
REPOSITORY = "github:zeus-owner/zeus-harness"
PIN = {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"}
CANDIDATE = {"revision": "c" * 40, "tree": "d" * 40, "base": "b" * 40, "repository": REPOSITORY}
NOW = "2026-09-26T00:00:00+00:00"


class SerialStore:
    """MemoryStore whose nested transaction fails loudly (the PG advisory-lock deadlock case)."""

    def __init__(self):
        self.inner, self.depth = MemoryStore(), 0

    @contextmanager
    def transaction(self):
        if self.depth:
            raise AssertionError("a nested store transaction deadlocks the PG advisory lock")
        self.depth += 1
        try:
            with self.inner.transaction() as tx:
                yield tx
        finally:
            self.depth -= 1


def policy_document():
    return {"schema": do.POLICY_SCHEMA, "id": "owners-1", "enabled": True, "continuation_policy": "policy-1",
            "assessment": {"model_label": "labelled-fixture-assessor"},
            "delivery": {"target_id": TARGET, "repository": REPOSITORY, "required_checks": ["ci / required"],
                         "canary_check_id": CANARY_FLEET, "ci_timeout_seconds": 300,
                         "consumption_timeout_seconds": 120},
            "canary": {"lane": "a", "manifest": {}, "goal": {"path": "docs/c.md", "sha256": "a" * 64,
                                                             "criterion": "labelled", "base_revision": "b" * 40,
                                                             "bytes": 0}}}


class Log(list):
    pass


class FakeLane:
    """LABELLED fake of the lane HostDelivery migration interface over its OWN lane store. `lose` names
    methods whose next call commits its effect and then loses the response; `down` names methods whose
    next call fails before any effect; `refuse` maps a method to a lane refusal reason."""

    def __init__(self, store, log):
        self.store, self.log = store, log
        self.lose, self.down, self.refuse = set(), set(), {}

    def _fault(self, name, before):
        if before and name in self.down:
            self.down.discard(name)
            raise OSError("lane store unavailable (labelled injected fault)")
        if before and name in self.refuse:
            raise DeliveryRefused(self.refuse[name], "labelled")
        if not before and name in self.lose:
            self.lose.discard(name)
            raise TimeoutError("response lost after the lane committed (labelled injected fault)")

    def approval(self, plan):
        return {"state": "approved"}

    def stage_migration(self, request):
        self._fault("stage_migration", True)
        assert request["migration_id"] == migration_request_id(request)
        sha = digest(request)
        with self.store.transaction() as tx:
            record = tx.get("host_delivery_migrations", request["old_plan_id"])
            if record is not None:
                if record["request_sha256"] != sha:
                    raise DeliveryRefused("migration_conflict", "request")
            else:
                self.log.append(("stage", request["migration_id"]))
                source = tx.get("releases", request["source_release_id"])
                successor = {**deepcopy(source), "id": "rel-mig-" + request["migration_id"][:12],
                             "policy_hash": "f" * 64, "status": "reviewed", "checks": {}}
                tx.put("releases", successor["id"], successor)
                old = tx.get("host_delivery_intents", request["old_plan_id"])
                tx.put("host_delivery_intents", old["plan_id"], {
                    **old, "stage": "withdrawn", "reason_code": "release_rejected_superseded",
                    "supersession": {"migration_id": request["migration_id"], "successor_release_id": successor["id"],
                                     "original_halt": {"stage": old["stage"], "reason_code": old["reason_code"]}}})
                record = {"id": request["old_plan_id"], "migration_id": request["migration_id"], "request": request,
                          "request_sha256": sha, "state": "staged", "successor_release_id": successor["id"],
                          "source_release_id": request["source_release_id"], "target_id": request["target_id"],
                          "plan_id": None, "plan_sha256": None, "ack": None, "at": NOW}
                tx.put("host_delivery_migrations", record["id"], record)
        self._fault("stage_migration", False)
        return self.view(record)

    @staticmethod
    def view(record):
        return {"migration": True, **{k: record[k] for k in ("migration_id", "state", "request_sha256",
                                                             "source_release_id", "successor_release_id",
                                                             "target_id", "plan_id", "plan_sha256")},
                "old_plan_id": record["id"], "acknowledged": record["ack"] is not None}

    def _record(self, tx, migration_id):
        found = [r for r in tx.scan("host_delivery_migrations") if r["migration_id"] == migration_id]
        if not found:
            raise DeliveryRefused("migration_unknown", "migration_id")
        return found[0]

    def register_migration_plan(self, plan, pin, migration_id):
        self._fault("register_migration_plan", True)
        sha = plan_digest(plan)
        with self.store.transaction() as tx:
            record = self._record(tx, migration_id)
            if record["state"] != "staged":
                if (record["plan_id"], record["plan_sha256"]) != (plan["plan_id"], sha):
                    raise DeliveryRefused("migration_conflict", "plan_id")
                view = {**self.view(record), "cached": True}
            else:
                assert plan["release_id"] == record["successor_release_id"]
                self.log.append(("register", plan["plan_id"]))
                tx.put("host_delivery_plans", plan["plan_id"], {"plan_id": plan["plan_id"], "plan": plan,
                                                                "plan_sha256": sha, "pin": pin,
                                                                "target_id": plan["target_id"]})
                tx.put("host_delivery_intents", plan["plan_id"], {
                    "id": plan["plan_id"], "plan_id": plan["plan_id"], "plan_sha256": sha,
                    "target_id": plan["target_id"], "release_id": plan["release_id"], "revision": plan["revision"],
                    "stage": "verifying", "held": "migration_unacknowledged",
                    "migration": {"migration_id": migration_id}})
                record = {**record, "state": "registered", "plan_id": plan["plan_id"], "plan_sha256": sha}
                tx.put("host_delivery_migrations", record["id"], record)
                view = {**self.view(record), "cached": False}
        self._fault("register_migration_plan", False)
        return view

    def finalize_migration(self, migration_id, ack):
        self._fault("finalize_migration", True)
        assert set(ack) == MIGRATION_ACK_FIELDS
        with self.store.transaction() as tx:
            record = self._record(tx, migration_id)
            if record["state"] == "active":
                if record["ack"] != ack:
                    raise DeliveryRefused("migration_conflict", "ack")
                view = {**self.view(record), "cached": True}
            else:
                if record["state"] != "registered" or (ack["plan_id"], ack["plan_sha256"], ack["request_sha256"]) != (
                        record["plan_id"], record["plan_sha256"], record["request_sha256"]):
                    raise DeliveryRefused("migration_ack_mismatch", "ack")
                self.log.append(("finalize", record["plan_id"]))
                intent = tx.get("host_delivery_intents", record["plan_id"])
                tx.put("host_delivery_intents", record["plan_id"], {**intent, "held": None})
                record = {**record, "state": "active", "ack": ack}
                tx.put("host_delivery_migrations", record["id"], record)
                view = {**self.view(record), "cached": False}
        self._fault("finalize_migration", False)
        return view

    def register(self, plan, pin):
        raise AssertionError("a migration successor must never take the ordinary registration")


class FakePublisher:
    """LABELLED Git publisher: content-addressed commits; `lose` loses one publish response."""

    def __init__(self, log):
        self.refs, self.commits, self.log, self.lose = {}, {}, log, False

    def publish(self, data, path, ref, when):
        revision = hashlib.sha1(data).hexdigest()
        if ref in self.refs and self.refs[ref] != revision:
            return {"conflict": True}
        if ref not in self.refs:
            self.log.append(("publish", ref))
        self.refs[ref], self.commits[revision] = revision, (path, data)
        if self.lose:
            self.lose = False
            raise TimeoutError("publish response lost (labelled injected fault)")
        return {"revision": revision, "conflict": False}

    def load(self, commit, path):
        stored_path, data = self.commits[commit]
        assert stored_path == path
        return {"plan": json.loads(data), "pin": {"revision": commit, "path": path,
                                                  "sha256": hashlib.sha256(data).hexdigest()}}


class FakeTargets:
    """LABELLED target-file port: plan-scoped canary requests."""

    def __init__(self, log):
        self.requests, self.log = {}, log

    def request(self, target, plan_id):
        return self.requests.get(plan_id)

    def write_request(self, target, plan_id, document):
        self.log.append(("request", plan_id))
        self.requests[plan_id] = deepcopy(document)

    def startup(self, target):
        return None


class StubContinuation:
    def policy(self, name):
        return {"id": "policy-1", "policy": {"delivery_target": TARGET}} if name == "policy-1" else None


def world():
    control, lane_store, log = SerialStore(), SerialStore(), Log()
    lane, publisher, targets = FakeLane(lane_store, log), FakePublisher(log), FakeTargets(log)
    ports = {"continuation": StubContinuation(), "deliveries": lambda lane_id: lane,
             "publisher": lambda lane_id: publisher, "targets": targets}
    owner = OwnerActions(control, clock=lambda: NOW, **ports)
    owner.register(policy_document(), PIN)
    source = {"id": "rel-old", "candidate": dict(CANDIDATE), "policy_hash": "e" * 64, "status": "rejected"}
    intent = {"id": "intent-1", "policy_id": "policy-1", "route": dc.DELIVERY, "state": dc.AWAITING_OWNER,
              "release_id": "rel-old", "delivery_target": TARGET, "lane": "a", "created_at": NOW, "version": 3}
    with control.transaction() as tx:
        policy_row = tx.get(BUCKET_POLICIES, "owners-1")
    binding = do.plan_binding(policy_row, intent, source, None)
    identity = do.action_id(do.DELIVERY_PLAN, binding)
    plan = do.build_plan(policy_row["policy"], binding, identity)
    old_action = {**do.new_action(do.DELIVERY_PLAN, binding, policy_row, {"intent_id": "intent-1", "lane": "a"}, NOW),
                  "state": do.COMPLETED, "reason_code": "plan_registered", "plan": plan, "plan_id": plan["plan_id"],
                  "plan_sha256": plan_digest(plan), "version": 4}
    with control.transaction() as tx:
        tx.put("continuation_intents", intent["id"], intent)
        tx.put(BUCKET_ACTIONS, identity, old_action)
    with lane_store.transaction() as tx:
        tx.put("releases", source["id"], source)
        tx.put("host_delivery_targets", TARGET, {"target_id": TARGET})
        tx.put("host_delivery_plans", plan["plan_id"], {"plan_id": plan["plan_id"], "plan": plan,
                                                        "plan_sha256": plan_digest(plan), "target_id": TARGET})
        tx.put("host_delivery_intents", plan["plan_id"], {
            "id": plan["plan_id"], "plan_id": plan["plan_id"], "plan_sha256": plan_digest(plan), "target_id": TARGET,
            "release_id": "rel-old", "revision": CANDIDATE["revision"], "stage": "failed",
            "reason_code": "release_rejected", "merged_revision": CANDIDATE["revision"]})
    return {"control": control, "lane_store": lane_store, "lane": lane, "publisher": publisher, "targets": targets,
            "log": log, "owner": owner, "ports": ports, "old_action": old_action, "plan": plan, "source": source,
            "intent": intent}


def document(w, **overrides):
    evidence = "sha256:" + "9" * 64
    approval = {"source_release_id": "rel-old", "base": CANDIDATE["base"], "evaluator_revision": "7" * 40,
                "evaluator_tree": "8" * 40, "patch_sha256": "6" * 64, "paths": ["tests/test_x.py"],
                "evidence": evidence, "approved_by": "lead:root"}
    return {"policy_id": "owners-1", "intent_id": "intent-1", "lane": "a", "target_id": TARGET,
            "source_release_id": "rel-old", "source_policy_hash": "e" * 64, "candidate_revision": CANDIDATE["revision"],
            "old_plan_id": w["plan"]["plan_id"], "old_plan_sha256": plan_digest(w["plan"]), "approval": approval,
            "evidence": evidence, "actor": "lead:root", **overrides}


def rows(store, bucket):
    with store.transaction() as tx:
        return {row["id"]: row for row in tx.scan(bucket)}


def migration_row(w):
    return rows(w["control"], BUCKET_MIGRATIONS).get("rel-old")


def settle(w, ticks=12, *, restart=False):
    results = []
    for _ in range(ticks):
        owner = OwnerActions(w["control"], clock=lambda: NOW, **w["ports"]) if restart else w["owner"]
        results.append(owner.tick("owners-1"))
        if (migration_row(w) or {}).get("state") in do.TERMINAL:
            break
    return results


def assert_single_lineage(w):
    control_actions = rows(w["control"], BUCKET_ACTIONS)
    successors = [a for a in control_actions.values() if (a.get("subject") or {}).get("migration")]
    assert len(successors) == 1 and len(control_actions) == 2
    lane_releases = rows(w["lane_store"], "releases")
    assert len(lane_releases) == 2 and len(rows(w["lane_store"], "host_delivery_migrations")) == 1
    assert [e for e in w["log"] if e[0] == "stage"] == [("stage", migration_row(w)["migration_id"])]
    assert len([e for e in w["log"] if e[0] == "register"]) == 1
    assert len([e for e in w["log"] if e[0] == "finalize"]) == 1
    assert len([e for e in w["log"] if e[0] == "publish"]) == 1
    assert list(w["targets"].requests) == [successors[0]["plan_id"]]
    return successors[0]


# ----- the request ---------------------------------------------------------------------------------
def test_request_records_one_migration_per_source_replays_identically_and_refuses_any_other(tmp_path):
    w = world()
    first = w["owner"].request_migration(document(w))
    assert (first["state"], first["cached"], first["kind"]) == (do.INTENDED, False, "evaluator_migration")
    row = migration_row(w)
    expected = {k: v for k, v in row["request"].items() if k != "migration_id"}
    assert row["migration_id"] == migration_request_id(expected) == first["migration_id"]
    assert w["owner"].request_migration(document(w))["cached"] is True
    other = document(w, evidence="sha256:" + "5" * 64)
    other["approval"] = {**other["approval"], "evidence": other["evidence"]}
    with pytest.raises(do.OwnerActionRefused, match="migration_conflict"):
        w["owner"].request_migration(other)
    with pytest.raises(do.OwnerActionRefused, match="migration_conflict"):
        w["owner"].request_migration(document(w, actor="lead:other"))
    assert len(rows(w["control"], BUCKET_MIGRATIONS)) == 1
    # No new kind is ever written into `owner_actions` (an older coordinator would crash on it).
    assert {a["kind"] for a in rows(w["control"], BUCKET_ACTIONS).values()} == {do.DELIVERY_PLAN}


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"source_release_id": "rel-other"}, "migration_approval_invalid"),
    ({"intent_id": "intent-missing"}, "migration_intent_mismatch"),
    ({"target_id": OTHER}, "delivery_target_mismatch"),
    ({"old_plan_id": "own-missing"}, "migration_plan_action_missing"),
    ({"old_plan_sha256": "0" * 64}, "migration_plan_action_mismatch"),
    ({"candidate_revision": "a" * 40}, "migration_plan_action_mismatch"),
    ({"evidence": "not-a-ref"}, "migration_document_invalid"),
])
def test_a_request_not_naming_the_exact_control_records_is_refused_and_writes_nothing(overrides, reason):
    w = world()
    with pytest.raises(do.OwnerActionRefused, match=reason):
        w["owner"].request_migration(document(w, **overrides))
    assert migration_row(w) is None
    with pytest.raises(do.OwnerActionRefused, match="migration_document_invalid"):
        w["owner"].request_migration({**document(w), "extra": 1})


# ----- the ordered handoff -------------------------------------------------------------------------
def test_the_migration_advances_stage_plan_request_held_registration_binding_ack_in_order(tmp_path):
    w = world()
    old_action, old_release = deepcopy(w["old_action"]), deepcopy(w["source"])
    intent_before = rows(w["control"], "continuation_intents")["intent-1"]
    w["owner"].request_migration(document(w))
    settle(w)
    row = migration_row(w)
    assert row["state"] == do.COMPLETED and row["reason_code"] == "migration_finalized"
    assert [s["state"] for s in row["history"]] == ["intended", "staged", "planning", "bound", "completed"]
    successor = assert_single_lineage(w)
    # The canary request is filed BEFORE the held registration, which precedes the acknowledgement.
    kinds = [e[0] for e in w["log"]]
    assert kinds == ["stage", "publish", "request", "register", "finalize"]
    link = successor["subject"]["migration"]
    assert link == {"migration_action_id": row["action_id"], "migration_id": row["migration_id"],
                    "source_release_id": "rel-old", "successor_release_id": row["successor_release_id"]}
    assert successor["state"] == do.COMPLETED and successor["plan"]["release_id"] == row["successor_release_id"]
    assert successor["binding"]["intent_id"] == "intent-1"
    # The plan is exactly the published bytes; the ack names exactly the control action and plan.
    assert w["publisher"].commits[successor["commit"]][1] == plan_json(successor["plan"])
    record = rows(w["lane_store"], "host_delivery_migrations")[w["plan"]["plan_id"]]
    assert record["state"] == "active" and record["ack"] == row["ack"]
    assert row["ack"]["control_action_id"] == successor["id"]
    assert row["ack"]["lineage_sha256"] == digest(lineage_of(row, successor)) == digest({
        "source_release_id": "rel-old", "successor_release_id": row["successor_release_id"],
        "old_plan_id": w["plan"]["plan_id"], "plan_id": successor["plan_id"], "migration_id": row["migration_id"]})
    effective = rows(w["control"], CONTINUATION_BINDINGS)["intent-1"]["binding"]
    assert (effective["source_release_id"], effective["successor_release_id"], effective["plan_id"]) == (
        "rel-old", row["successor_release_id"], successor["plan_id"])
    # History is untouched: the original action, the source release and the conductor's release id.
    assert rows(w["control"], BUCKET_ACTIONS)[old_action["id"]] == old_action
    assert rows(w["lane_store"], "releases")["rel-old"] == old_release
    assert rows(w["control"], "continuation_intents")["intent-1"] == intent_before
    # Further ticks are idle for the migration and never re-plan the source release.
    again = w["owner"].tick("owners-1")
    assert all(a["kind"] != "evaluator_migration" for a in again["actions"])
    assert_single_lineage(w)


@pytest.mark.parametrize("fault", ["stage_migration", "register_migration_plan", "finalize_migration", "publish"])
def test_a_lost_response_or_restart_at_any_step_resumes_to_exactly_one_lineage(fault):
    w = world()
    if fault == "publish":
        w["publisher"].lose = True
    else:
        w["lane"].lose.add(fault)
    w["owner"].request_migration(document(w))
    results = settle(w, ticks=16, restart=True)
    assert any(r["waits"] for r in results)             # the lost response was a named wait, not a verdict
    assert migration_row(w)["state"] == do.COMPLETED
    assert_single_lineage(w)


def test_an_outage_waits_in_place_and_never_refuses_or_completes():
    w = world()
    w["owner"].request_migration(document(w))
    w["lane"].down.add("stage_migration")
    result = w["owner"].tick("owners-1")
    assert migration_row(w)["state"] == do.INTENDED and "OSError" in result["waits"].values()
    w["lane"].refuse["finalize_migration"] = "migration_unobservable"
    settle(w, ticks=8)
    assert migration_row(w)["state"] == "bound"            # retryable lane refusal: waiting, not completed
    del w["lane"].refuse["finalize_migration"]
    settle(w)
    assert migration_row(w)["state"] == do.COMPLETED


@pytest.mark.parametrize("step", ["stage_migration", "finalize_migration"])
def test_a_lane_refusal_is_refused_with_the_lane_reason_and_never_completes(step):
    w = world()
    w["lane"].refuse[step] = "migration_source_mismatch"
    w["owner"].request_migration(document(w))
    settle(w)
    row = migration_row(w)
    assert (row["state"], row["reason_code"]) == (do.REFUSED, "migration_source_mismatch")
    assert "ack" not in row and "finalize" not in [e[0] for e in w["log"]]
    if step == "stage_migration":
        assert [a for a in rows(w["control"], BUCKET_ACTIONS).values() if a["subject"].get("migration")] == []


# ----- target reservation --------------------------------------------------------------------------
def rival(w, target=TARGET, release_id="rel-rival"):
    """Another conducted delivery intent (a different release of the same candidate lane) on `target`."""
    release = {"id": release_id, "candidate": {**CANDIDATE, "revision": "4" * 40}, "policy_hash": "e" * 64}
    with w["lane_store"].transaction() as tx:
        tx.put("releases", release_id, release)
    return {"id": "intent-" + release_id, "policy_id": "policy-1", "route": dc.DELIVERY, "state": dc.AWAITING_OWNER,
            "release_id": release_id, "delivery_target": target, "lane": "a", "created_at": NOW, "version": 1}


def test_a_staged_or_registered_migration_keeps_its_target_busy_for_every_other_plan():
    w = world()
    w["owner"].request_migration(document(w))
    w["owner"].tick("owners-1")                                       # staged in the lane
    assert rows(w["lane_store"], "host_delivery_migrations")[w["plan"]["plan_id"]]["state"] == "staged"
    with w["control"].transaction() as tx:
        policy_row = tx.get(BUCKET_POLICIES, "owners-1")
    other = rival(w)
    with pytest.raises(do.OwnerActionRefused, match="delivery_target_busy"):
        w["owner"]._plan_binding(policy_row, other)
    with w["control"].transaction() as tx:
        tx.put("continuation_intents", other["id"], other)
    result = w["owner"].tick("owners-1")
    assert result["waits"].get(other["id"]) == "delivery_target_busy"
    settle(w)
    assert migration_row(w)["state"] == do.COMPLETED
    # Once active, the reservation is released: the ordinary busy rules decide again.
    assert rows(w["lane_store"], "host_delivery_migrations")[w["plan"]["plan_id"]]["state"] == "active"


def test_a_migration_reserving_another_target_does_not_block_this_one():
    w = world()
    with w["lane_store"].transaction() as tx:
        tx.put("host_delivery_migrations", "own-elsewhere", {"id": "own-elsewhere", "migration_id": "m" * 64,
                                                             "state": "staged", "target_id": OTHER})
    with w["control"].transaction() as tx:
        policy_row = tx.get(BUCKET_POLICIES, "owners-1")
        # The source delivery is terminal; this rival is the only candidate for the target.
    with w["lane_store"].transaction() as tx:
        old = tx.get("host_delivery_intents", w["plan"]["plan_id"])
        tx.put("host_delivery_intents", old["plan_id"], {**old, "stage": "rolled_back"})
    binding = w["owner"]._plan_binding(policy_row, rival(w))
    assert binding is not None and binding["release_id"] == "rel-rival"


# ----- the verified lane edge (LaneEvidence.read) --------------------------------------------------
def edge_store(*, state="active", successor_candidate=None, reason="release_rejected_superseded"):
    store = MemoryStore()
    successor_candidate = dict(CANDIDATE) if successor_candidate is None else successor_candidate
    with store.transaction() as tx:
        tx.put("releases", "rel-old", {"id": "rel-old", "candidate": dict(CANDIDATE)})
        tx.put("releases", "rel-new", {"id": "rel-new", "candidate": successor_candidate})
        tx.put("host_delivery_intents", "own-old", {
            "id": "own-old", "plan_id": "own-old", "target_id": TARGET, "release_id": "rel-old",
            "revision": CANDIDATE["revision"], "stage": "withdrawn", "reason_code": reason,
            "supersession": {"migration_id": "m" * 64, "successor_release_id": "rel-new"}})
        tx.put("host_delivery_intents", "own-new", {
            "id": "own-new", "plan_id": "own-new", "plan_sha256": "1" * 64, "target_id": TARGET,
            "release_id": "rel-new", "revision": CANDIDATE["revision"], "stage": "verifying"})
        tx.put("host_delivery_migrations", "own-old", {
            "id": "own-old", "migration_id": "m" * 64, "state": state, "source_release_id": "rel-old",
            "successor_release_id": "rel-new", "target_id": TARGET, "plan_id": "own-new", "plan_sha256": "1" * 64})
    return store


def edge(store):
    with store.transaction() as tx:
        deliveries = [r for r in tx.scan("host_delivery_intents") if r.get("release_id") == "rel-old"]
        return _migrated_delivery(tx, deliveries, TARGET, "rel-old", CANDIDATE["revision"],
                                  tx.get("releases", "rel-old"))


def test_the_superseded_source_binds_only_its_active_verified_successor_delivery():
    bound = edge(edge_store())
    assert (bound["binding"], bound["release_id"], bound["effective_release_id"], bound["plan_id"]) == (
        dc.DELIVERY_BOUND, "rel-old", "rel-new", "own-new")
    assert dc.delivery_tuple(bound) == {"target_id": TARGET, "release_id": "rel-old",
                                        "revision": CANDIDATE["revision"]}


@pytest.mark.parametrize("store", [
    lambda: edge_store(state="staged"),
    lambda: edge_store(state="registered"),
    lambda: edge_store(successor_candidate={**CANDIDATE, "tree": "0" * 40}),
    lambda: edge_store(successor_candidate={**CANDIDATE, "base": "0" * 40}),
    lambda: edge_store(reason="release_rejected"),
])
def test_an_unacknowledged_or_non_identical_successor_is_never_followed(store):
    assert edge(store()) is None


# ----- REAL lane code: the Lane-2 HostDelivery migration owner over its own lane store ---------------
def test_the_real_lane_owner_completes_the_ordered_handoff_from_a_separate_control_store(tmp_path):
    """REAL `HostDelivery`/`Releases`/`ReleaseQueue` in the lane store (the Lane-2 fixture's labelled
    H1-shaped halted intent); a SEPARATE control store; LABELLED publisher and target files."""
    from test_host_delivery import CHECK
    from test_host_delivery import REPOSITORY as LANE_REPOSITORY
    from test_host_delivery_migration import rejected_merged

    lane_store = SerialStore()
    system = rejected_merged(tmp_path, lane_store)
    release, plan, delivery = system["release"], system["plan"], system["delivery"]
    control, log = SerialStore(), Log()
    publisher, targets = FakePublisher(log), FakeTargets(log)
    policy = policy_document()
    policy["delivery"] = {**policy["delivery"], "target_id": plan["target_id"], "repository": LANE_REPOSITORY,
                          "required_checks": [CHECK]}

    class Stub:
        def policy(self, name):
            return {"id": "policy-1", "policy": {"delivery_target": plan["target_id"]}}

    owner = OwnerActions(control, continuation=Stub(), deliveries=lambda lane_id: delivery,
                         publisher=lambda lane_id: publisher, targets=targets, clock=lambda: NOW)
    owner.register(policy, PIN)
    intent = {"id": "intent-1", "policy_id": "policy-1", "route": dc.DELIVERY, "state": dc.AWAITING_OWNER,
              "release_id": release["id"], "delivery_target": plan["target_id"], "lane": "a", "created_at": NOW,
              "version": 3}
    with control.transaction() as tx:
        policy_row = tx.get(BUCKET_POLICIES, "owners-1")
    # LABELLED crafted control row: the original completed DELIVERY_PLAN action of the lane's plan.
    old_binding = do.plan_binding(policy_row, intent, release, None)
    old_action = {**do.new_action(do.DELIVERY_PLAN, old_binding, policy_row, {"intent_id": "intent-1", "lane": "a"},
                                  NOW), "state": do.COMPLETED, "plan_id": plan["plan_id"],
                  "plan_sha256": plan_digest(plan), "plan": plan, "version": 4}
    with control.transaction() as tx:
        tx.put("continuation_intents", intent["id"], intent)
        tx.put(BUCKET_ACTIONS, old_action["id"], old_action)
    request = system["request"]
    evidence = request["approval"]["evidence"]
    owner.request_migration({"policy_id": "owners-1", "intent_id": "intent-1", "lane": "a",
                             "target_id": plan["target_id"], "source_release_id": release["id"],
                             "source_policy_hash": release["policy_hash"],
                             "candidate_revision": release["candidate"]["revision"], "old_plan_id": plan["plan_id"],
                             "old_plan_sha256": plan_digest(plan), "approval": request["approval"],
                             "evidence": evidence, "actor": request["actor"]})
    for _ in range(12):
        owner.tick("owners-1")
        with control.transaction() as tx:
            row = tx.get(BUCKET_MIGRATIONS, release["id"])
        if row["state"] in do.TERMINAL:
            break
    assert (row["state"], row["reason_code"]) == (do.COMPLETED, "migration_finalized"), row["history"]
    assert row["migration_id"] == request["migration_id"]      # the same identity both halves compute
    with lane_store.transaction() as tx:
        record = tx.get("host_delivery_migrations", plan["plan_id"])
        successor_intent = tx.get("host_delivery_intents", record["plan_id"])
        queued = tx.get("release_queue", record["successor_release_id"])
    assert record["state"] == "active" and record["ack"] == row["ack"]
    assert successor_intent["held"] is None and queued is not None
    assert [e[0] for e in log] == ["publish", "request"]       # the request is filed before registration
    with control.transaction() as tx:
        assert tx.get(BUCKET_ACTIONS, old_action["id"]) == old_action
