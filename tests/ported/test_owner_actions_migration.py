"""Ported SOURCE M7 suite `tests/test_owner_actions_migration.py` (e38aa722) run against the S7 target (DESIGN-s7 §6).

Every assertion is M7's, unchanged. Adaptations, all construction, import and patch-target (the `m7_coordination` and
`m7_delivery` shim docstrings name the routing): `OwnerActions` is the shim's facade over the split owner-action objects
(it also routes M7's private `_advance_canary`, `_plan_binding`, `_discover`, `_recovery_lane` and `_take_slot`, and the
one `clock`, to their split homes); `organization`, `packaged_policy`, `Workflow`, `unavailable`, `HostDelivery`,
`Releases`, `MemoryStore`, `GitPlanPublisher` (M7 `GitPlanPublisher(repository)` built through
`composition.owner_action_adapters.git_plan_publisher`, a named construction adaptation) and `TargetFiles`
(`delivery.adapters.target_files`) come from the shims; the owner-action BUCKET_* names, `CONTINUATION_BINDINGS`,
`lineage_of` and `plan_json` from `coordination.application.owner_actions.state`, the domain modules from
`coordination.domain` and `delivery.domain`, the adapter names from `delivery.adapters.host_delivery`, `digest` from
`kernel.ids`. `_migrated_delivery` is `coordination.application.continuation.lanes`'s; the PG helpers use `storage.adapters.postgres_store.PostgresStore` and the shim's `database_url`; `pg_continuation_world` takes `Fleet`/`Harness` from the shim, `SessionArchives` from the ported `test_worker_sessions` and `WorkerSessions` from `execution.application`. The PG cases keep M7's own skip behaviour.

M7 docstring follows.

INV-OWNER-ACTIONS-MIGRATION-001: the control half of the H1 evaluator migration.

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
from m7_coordination import Fleet, Harness, OwnerActions, organization
from m7_delivery import MemoryStore, database_url

from codex_harness.coordination.application.continuation.lanes import _migrated_delivery
from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    BUCKET_MIGRATIONS,
    BUCKET_POLICIES,
    CONTINUATION_BINDINGS,
    lineage_of,
    plan_json,
)
from codex_harness.coordination.domain import continuation as dc
from codex_harness.coordination.domain import owner_actions as do
from codex_harness.delivery.domain.host_delivery import (
    CANARY_FLEET,
    MIGRATION_ACK_FIELDS,
    DeliveryRefused,
    migration_request_id,
    plan_digest,
)
from codex_harness.kernel.ids import digest

TARGET, OTHER = "fleet-host", "other-host"
REPOSITORY = "github:zeus-owner/zeus-harness"
PIN = {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"}
CANDIDATE = {"revision": "c" * 40, "tree": "d" * 40, "base": "b" * 40, "repository": REPOSITORY}
NOW = "2026-09-26T00:00:00+00:00"
# LABELLED fake first-activation facts (INV-HOST-DELIVERY-001): what the lane boundary's trusted port
# reports for a target without a descriptor. No image, profile or host is resolved here.
FIRST_ACTIVATION = {"worker_image": "sha256:" + "9" * 64, "profile_digest": "c" * 64,
                    "image_source_revision": "a" * 40}


def first_activation_port(lane_id, revision):
    """LABELLED fake of the owner's `first_activation(lane_id, revision)` port."""
    return dict(FIRST_ACTIVATION)


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
        self.controller = "3" * 40      # labelled: the running controller code the lane's port reports

    def require_controller_code(self, expected):
        if self.controller is None:
            raise DeliveryRefused("migration_controller_code_unavailable", "controller_revision")
        if self.controller != expected:
            raise DeliveryRefused("migration_controller_code_mismatch", "controller_revision")
        return self.controller

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
             "publisher": lambda lane_id: publisher, "targets": targets, "first_activation": first_activation_port}
    owner = OwnerActions(control, clock=lambda: NOW, **ports)
    owner.register(policy_document(), PIN)
    source = {"id": "rel-old", "candidate": dict(CANDIDATE), "policy_hash": "e" * 64, "status": "rejected"}
    intent = {"id": "intent-1", "policy_id": "policy-1", "route": dc.DELIVERY, "state": dc.AWAITING_OWNER,
              "release_id": "rel-old", "delivery_target": TARGET, "lane": "a", "created_at": NOW, "version": 3}
    with control.transaction() as tx:
        policy_row = tx.get(BUCKET_POLICIES, "owners-1")
    binding = do.plan_binding(policy_row, intent, source, None)
    identity = do.action_id(do.DELIVERY_PLAN, binding)
    plan = do.build_plan(policy_row["policy"], binding, identity, first_activation=FIRST_ACTIVATION)
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
def real_lane(tmp_path, control, lane_store):
    """REAL `HostDelivery`/`Releases`/`ReleaseQueue` in the lane store (the Lane-2 fixture's labelled
    H1-shaped halted intent and its LABELLED evaluator-pin resolver); a SEPARATE control store with a
    real `OwnerActions`; LABELLED publisher and target files."""
    from test_host_delivery import CHECK
    from test_host_delivery import REPOSITORY as LANE_REPOSITORY
    from test_host_delivery_migration import rejected_merged

    system = rejected_merged(tmp_path, lane_store)
    release, plan, delivery = system["release"], system["plan"], system["delivery"]
    log = Log()
    publisher, targets = FakePublisher(log), FakeTargets(log)
    policy = policy_document()
    policy["delivery"] = {**policy["delivery"], "target_id": plan["target_id"], "repository": LANE_REPOSITORY,
                          "required_checks": [CHECK]}

    class Stub:
        def policy(self, name):
            return {"id": "policy-1", "policy": {"delivery_target": plan["target_id"]}}

    ports = {"continuation": Stub(), "deliveries": lambda lane_id: delivery,
             "publisher": lambda lane_id: publisher, "targets": targets, "first_activation": first_activation_port}
    owner = OwnerActions(control, clock=lambda: NOW, **ports)
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
    doc = {"policy_id": "owners-1", "intent_id": "intent-1", "lane": "a", "target_id": plan["target_id"],
           "source_release_id": release["id"], "source_policy_hash": release["policy_hash"],
           "candidate_revision": release["candidate"]["revision"], "old_plan_id": plan["plan_id"],
           "old_plan_sha256": plan_digest(plan), "approval": request["approval"],
           "evidence": request["approval"]["evidence"], "actor": request["actor"]}
    return {"system": system, "control": control, "lane_store": lane_store, "owner": owner, "ports": ports,
            "delivery": delivery, "release": release, "plan": plan, "log": log, "targets": targets,
            "publisher": publisher, "old_action": old_action, "request": request, "doc": doc}


def real_row(r):
    with r["control"].transaction() as tx:
        return tx.get(BUCKET_MIGRATIONS, r["release"]["id"])


def real_ticks(r, *, until=do.COMPLETED, restart=False, ticks=12):
    receipts = []
    for _ in range(ticks):
        owner = OwnerActions(r["control"], clock=lambda: NOW, **r["ports"]) if restart else r["owner"]
        receipts.append(owner.tick("owners-1"))
        row = real_row(r)
        if row["state"] == until or row["state"] in do.TERMINAL:
            break
    return row, receipts


def assert_real_lineage(r, row):
    """Exactly one migration, successor release, successor action and plan; the ack identity is bound
    to the final plan-scoped canary request; the original action is untouched history."""
    assert (row["state"], row["reason_code"]) == (do.COMPLETED, "migration_finalized"), row["history"]
    assert row["migration_id"] == r["request"]["migration_id"]     # the same identity both halves compute
    with r["lane_store"].transaction() as tx:
        records = tx.scan("host_delivery_migrations")
        successor_intent = tx.get("host_delivery_intents", row["plan_id"])
        queued = tx.get("release_queue", row["successor_release_id"])
        successors = [x for x in tx.scan("releases") if x["id"] == row["successor_release_id"]]
    assert len(records) == 1 and records[0]["state"] == "active" and records[0]["ack"] == row["ack"]
    assert len(successors) == 1 and successor_intent["held"] is None and queued is not None
    with r["control"].transaction() as tx:
        actions = tx.scan(BUCKET_ACTIONS)
        assert tx.get(BUCKET_ACTIONS, r["old_action"]["id"]) == r["old_action"]
    assert len([a for a in actions if (a.get("subject") or {}).get("migration")]) == 1
    assert list(r["targets"].requests) == [row["plan_id"]]
    assert row["ack"]["canary_request_id"] == digest(r["targets"].requests[row["plan_id"]])
    # One publication; the request is filed before registration (a retried register or a readiness
    # refile writes the SAME plan-scoped document again, never another plan's).
    assert [e[0] for e in r["log"]][:2] == ["publish", "request"]
    assert {e for e in r["log"] if e[0] == "request"} == {("request", row["plan_id"])}
    assert len([e for e in r["log"] if e[0] == "publish"]) == 1


def test_the_real_lane_owner_completes_the_ordered_handoff_from_a_separate_control_store(tmp_path):
    r = real_lane(tmp_path, SerialStore(), SerialStore())
    r["owner"].request_migration(r["doc"])
    row, _ = real_ticks(r)
    assert_real_lineage(r, row)


class LosingDelivery:
    """LABELLED proxy of the REAL lane HostDelivery: `lose` commits the real call then loses its response;
    `down` fails once before any effect (an outage)."""

    def __init__(self, real):
        self.real, self.lose, self.down = real, set(), set()

    def __getattr__(self, name):
        attr = getattr(self.real, name)
        if name not in {"stage_migration", "register_migration_plan", "finalize_migration"}:
            return attr

        def call(*args):
            if name in self.down:
                self.down.discard(name)
                raise OSError("lane unavailable (labelled injected fault)")
            result = attr(*args)
            if name in self.lose:
                self.lose.discard(name)
                raise TimeoutError("lane response lost after commit (labelled injected fault)")
            return result
        return call


@pytest.fixture
def second_pgstore():
    """A SECOND schema-isolated PostgreSQL store (the lane store), made exactly as `isolated_pgstore`."""
    import os
    from uuid import uuid4

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from codex_harness.storage.adapters.postgres_store import PostgresStore

    if os.environ.get("HARNESS_INTEGRATION") != "1":
        pytest.skip("Integration environment required")
    dsn, schema = database_url(), "test_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        store = PostgresStore(make_conninfo(dsn, options=f"-c search_path={schema},public"))
        store.migrate()
        yield store
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.integration
@pytest.mark.parametrize("fault", ["none", "restart", "lose:stage_migration", "lose:register_migration_plan",
                                   "lose:finalize_migration", "down:stage_migration", "down:register_migration_plan",
                                   "down:finalize_migration"])
def test_pg_separate_control_and_lane_schemas_complete_one_lineage_across_lost_responses_and_restarts(
        tmp_path, isolated_pgstore, second_pgstore, fault):
    """TWO isolated PostgreSQL schemas: control (OwnerActions) and lane (REAL HostDelivery)."""
    r = real_lane(tmp_path, isolated_pgstore, second_pgstore)
    proxy = LosingDelivery(r["delivery"])
    r["ports"]["deliveries"] = lambda lane_id: proxy
    r["owner"] = OwnerActions(r["control"], clock=lambda: NOW, **r["ports"])
    kind, _, method = fault.partition(":")
    if kind in {"lose", "down"}:
        getattr(proxy, kind).add(method)
    r["owner"].request_migration(r["doc"])
    row, receipts = real_ticks(r, restart=fault == "restart", ticks=16)
    assert_real_lineage(r, row)
    if kind in {"lose", "down"}:
        # The fault is a named wait of the step that met it (the migration row, or the successor plan
        # action whose registration it is); never a refusal or a second lineage.
        assert any(set(receipt["waits"].values()) & {"TimeoutError", "OSError"} for receipt in receipts)


@pytest.mark.integration
@pytest.mark.parametrize("hold", ["request_deleted", "request_unreadable", "request_replaced", "source_moved"])
def test_pg_readiness_failures_hold_bound_then_a_competing_h2_plan_is_refused_and_the_restored_tuple_completes(
        tmp_path, isolated_pgstore, second_pgstore, hold):
    from m7_delivery import Releases
    from test_host_delivery_migration import pin as lane_pin
    from test_host_delivery_migration import plan_document, refused

    r = real_lane(tmp_path, isolated_pgstore, second_pgstore)
    r["owner"].request_migration(r["doc"])
    row, _ = real_ticks(r, until="bound")
    assert row["state"] == "bound", row["history"]
    # A competing H2 plan on the reserved target is refused by the REAL lane while the migration is held.
    competitor = Releases(r["lane_store"], r["system"]["org"]).propose(
        {**r["release"]["candidate"], "revision": "8" * 40},
        {"checks": ["tests"], "evaluator": "fixture-incumbent-policy"})
    refused("target_reserved_by_migration", r["delivery"].register,
            plan_document(competitor, plan_id="delivery-plan-h2"), lane_pin())
    base = r["targets"]
    if hold == "request_deleted":
        del base.requests[row["plan_id"]]
        targets = DownTargets(base, write=True)
        reason = "migration_readiness_canary_request_missing"
    elif hold == "request_unreadable":
        targets, reason = DownTargets(base, read=True), "migration_readiness_canary_request_unreadable"
    elif hold == "request_replaced":
        base.requests[row["plan_id"]] = {**base.requests[row["plan_id"]], "plan_sha256": "0" * 64}
        targets, reason = DownTargets(base, write=True), "migration_readiness_canary_request_replaced"
    else:
        with r["control"].transaction() as tx:
            intent = tx.get("continuation_intents", "intent-1")
            tx.put("continuation_intents", "intent-1", {**intent, "version": intent["version"] + 1})
        targets, reason = base, "migration_readiness_source_intent"
    held = OwnerActions(r["control"], clock=lambda: NOW, **{**r["ports"], "targets": targets})
    for _ in range(2):
        assert held.tick("owners-1")["waits"][row["action_id"]] == reason
        assert real_row(r) == row
        with r["lane_store"].transaction() as tx:
            assert tx.get("host_delivery_migrations", r["plan"]["plan_id"])["state"] == "registered"
    if hold == "source_moved":
        return      # the moved source is the owner's to resolve; nothing proceeds
    done, _ = real_ticks(r)     # the owner's own port refiles the identical request; readiness now holds
    assert_real_lineage(r, done)


# ----- L2: the readiness tuple is re-observed in the finalizing step (bound -> completed) ----------------
def to_bound(w):
    w["owner"].request_migration(document(w))
    for _ in range(12):
        w["owner"].tick("owners-1")
        if migration_row(w)["state"] == "bound":
            break
    assert migration_row(w)["state"] == "bound", migration_row(w)["history"]
    return migration_row(w)


class DownTargets(FakeTargets):
    """LABELLED target-file port whose reads and/or writes fail (injected outage)."""

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


def held_tick(w, targets=None, publisher=None):
    ports = {**w["ports"], **({"targets": targets} if targets else {}), **({"publisher": publisher} if publisher else {})}
    before = (deepcopy(rows(w["control"], BUCKET_MIGRATIONS)), deepcopy(rows(w["lane_store"], "host_delivery_migrations")))
    receipt = OwnerActions(w["control"], clock=lambda: NOW, **ports).tick("owners-1")
    after = (rows(w["control"], BUCKET_MIGRATIONS), rows(w["lane_store"], "host_delivery_migrations"))
    assert after == before, "a readiness wait writes nothing in either store"
    assert not [e for e in w["log"] if e[0] == "finalize"]
    return receipt


@pytest.mark.parametrize("case, reason", [
    ("deleted_refile_fails", "migration_readiness_canary_request_missing"),
    ("unreadable", "migration_readiness_canary_request_unreadable"),
    ("replaced_refile_fails", "migration_readiness_canary_request_replaced"),
    ("pin_unreadable", "migration_readiness_pin_unreadable"),
    ("pin_replaced", "migration_readiness_pin_mismatch"),
    ("source_moved", "migration_readiness_source_intent"),
    ("binding_replaced", "migration_readiness_binding"),
])
def test_unavailable_or_replaced_readiness_evidence_holds_bound_with_a_named_wait_and_never_finalizes(case, reason):
    w = world()
    row = to_bound(w)
    plan_id, targets, publisher = row["plan_id"], None, None
    if case == "deleted_refile_fails":
        del w["targets"].requests[plan_id]
        targets = DownTargets(w["targets"], write=True)
    elif case == "unreadable":
        targets = DownTargets(w["targets"], read=True)
    elif case == "replaced_refile_fails":
        w["targets"].requests[plan_id] = {**w["targets"].requests[plan_id], "plan_sha256": "0" * 64}
        targets = DownTargets(w["targets"], write=True)
    elif case in {"pin_unreadable", "pin_replaced"}:
        publisher = FakePublisher(w["log"])
        if case == "pin_replaced":
            action = rows(w["control"], BUCKET_ACTIONS)[row["plan_action_id"]]
            publisher.commits[action["commit"]] = (action["path"], b'{"replaced": true}\n')
    elif case == "source_moved":
        with w["control"].transaction() as tx:
            intent = tx.get("continuation_intents", "intent-1")
            tx.put("continuation_intents", "intent-1", {**intent, "version": intent["version"] + 1})
    elif case == "binding_replaced":
        with w["control"].transaction() as tx:
            bound = tx.get(CONTINUATION_BINDINGS, "intent-1")
            tx.put(CONTINUATION_BINDINGS, "intent-1", {**bound, "binding": {**bound["binding"], "plan_sha256": "0" * 64}})
    receipt = held_tick(w, targets=targets, publisher=publisher and (lambda lane_id: publisher))
    assert receipt["waits"][row["action_id"]] == reason
    assert migration_row(w)["state"] == "bound"
    with w["lane_store"].transaction() as tx:
        assert tx.get("host_delivery_migrations", w["plan"]["plan_id"])["state"] == "registered"


def test_a_restored_readiness_tuple_finalizes_once_and_a_lost_finalize_response_replays_without_readiness():
    w = world()
    row = to_bound(w)
    del w["targets"].requests[row["plan_id"]]
    held_tick(w, targets=DownTargets(w["targets"], write=True))
    w["lane"].lose.add("finalize_migration")
    first = w["owner"].tick("owners-1")              # refiled, re-observed, finalized; response lost
    assert migration_row(w)["state"] == "bound" and first["waits"][row["action_id"]] == "TimeoutError"
    # The lane already holds the identical ack: the replay completes with NO further readiness read.
    w["targets"].requests.clear()
    replay = OwnerActions(w["control"], clock=lambda: NOW, **{**w["ports"], "targets": DownTargets(
        w["targets"], read=True, write=True)}).tick("owners-1")
    done = migration_row(w)
    assert (done["state"], done["reason_code"]) == (do.COMPLETED, "migration_finalized"), replay
    assert done["finalized"]["cached"] is True and done["readiness"] is None
    assert len([e for e in w["log"] if e[0] == "finalize"]) == 1
    from codex_harness.delivery.domain.host_delivery import migration_lineage_digest
    assert done["ack"]["lineage_sha256"] == migration_lineage_digest(**done["lineage"])
    assert done["ack"]["canary_request_id"] != "not_requested"


def test_a_completed_migration_carries_its_observed_ready_record_and_status_shows_the_lineage():
    w = world()
    w["owner"].request_migration(document(w))
    settle(w)
    done = migration_row(w)
    assert done["state"] == do.COMPLETED and done["source_resumed"] is False
    ready = done["readiness"]
    action = rows(w["control"], BUCKET_ACTIONS)[done["plan_action_id"]]
    assert (ready["plan_id"], ready["plan_sha256"], ready["bytes_sha256"]) == (
        action["plan_id"], action["plan_sha256"], action["bytes_sha256"])
    assert ready["canary_request_id"] == done["ack"]["canary_request_id"] == digest(w["targets"].requests[action["plan_id"]])
    status = w["owner"].status("owners-1")["migrations"]
    assert status == [{"source_release_id": "rel-old", "kind": "evaluator_migration", "state": do.COMPLETED,
                       "reason_code": "migration_finalized",
                       "phases": [{"state": h["state"], "reason_code": h["reason_code"], "at": h["at"]}
                                  for h in done["history"]][-8:],
                       "successor_release_id": done["successor_release_id"], "plan_id": done["plan_id"],
                       "intent_id": "intent-1", "source_intent_state": dc.AWAITING_OWNER,
                       "owner": {"policy_id": "owners-1", "lane": "a"}, "version": done["version"]}]
    intent = rows(w["control"], "continuation_intents")["intent-1"]
    assert intent == w["intent"], "an AWAITING_OWNER source is never rewritten by the migration"


# ----- L1: a PAUSED source through the REAL Continuation consumer (test_continuation.World) ------------
# REAL: Fleet, lane Operation/Harness store, Continuation.tick with LaneEvidence over the lane store,
# OwnerActions over the control store. LABELLED: the conductor fixture, FakeLane (HostDelivery migration
# interface) over the SAME lane store the Continuation reads, the Git publisher and the target files, and
# the one step that stands in for the lane controller's verification of the successor (stage -> active).
def pg_continuation_world(tmp_path, control, lane_store):
    """test_continuation.World rebuilt over TWO PostgreSQL stores: the Fleet/Continuation control store
    and the lane Harness store (REAL Fleet, Operation, WorkerSessions, Continuation, LaneEvidence)."""
    from test_continuation import ConductorFixture, World
    from test_fleet import config as fleet_config
    from test_worker_sessions import SessionArchives

    from codex_harness.execution.application.worker_sessions import WorkerSessions

    world = World(tmp_path)
    world.control, world.fleet = control, Fleet(control)
    world.fleet.register(fleet_config(tmp_path, max_parallel=2))
    world.lane = Harness(lane_store, organization())
    world.sessions = WorkerSessions(lane_store, SessionArchives(tmp_path / "pg-archives"))
    world.conductor = ConductorFixture(world.lane)
    world.controller = world.build()
    return world


def paused_world(tmp_path, world=None):
    from test_continuation import World, accepted_item, only

    world = world or World(tmp_path)
    world.register()
    accepted_item(world)
    world.tick()
    world.tick()
    source = only(world.intents(), route=dc.DELIVERY)
    assert source["state"] == dc.AWAITING_OWNER
    log = Log()
    lane, publisher, targets = FakeLane(world.lane.store, log), FakePublisher(log), FakeTargets(log)
    ports = {"continuation": world.controller, "deliveries": lambda lane_id: lane,
             "publisher": lambda lane_id: publisher, "targets": targets, "first_activation": first_activation_port}
    owner = OwnerActions(world.control, clock=lambda: NOW, **ports)
    owner.register(policy_document(), PIN)
    release_id = source["release_id"]
    with world.lane.store.transaction() as tx:
        release = tx.get("releases", release_id)
        release = {**release, "candidate": {**release["candidate"], "repository": REPOSITORY},
                   "policy_hash": "e" * 64, "status": "rejected"}
        tx.put("releases", release_id, release)
        tx.put("host_delivery_targets", TARGET, {"target_id": TARGET})
    policy_row = rows(world.control, BUCKET_POLICIES)["owners-1"]
    binding = do.plan_binding(policy_row, source, release, None)
    identity = do.action_id(do.DELIVERY_PLAN, binding)
    plan = do.build_plan(policy_row["policy"], binding, identity, first_activation=FIRST_ACTIVATION)
    old_action = {**do.new_action(do.DELIVERY_PLAN, binding, policy_row, {"intent_id": source["id"], "lane": "a"}, NOW),
                  "state": do.COMPLETED, "reason_code": "plan_registered", "plan": plan, "plan_id": plan["plan_id"],
                  "plan_sha256": plan_digest(plan), "published_at": NOW, "version": 4}
    with world.control.transaction() as tx:
        tx.put(BUCKET_ACTIONS, identity, old_action)
    with world.lane.store.transaction() as tx:
        tx.put("host_delivery_plans", plan["plan_id"], {"plan_id": plan["plan_id"], "plan": plan,
                                                        "plan_sha256": plan_digest(plan), "target_id": TARGET})
        tx.put("host_delivery_intents", plan["plan_id"], {
            "id": plan["plan_id"], "plan_id": plan["plan_id"], "plan_sha256": plan_digest(plan), "target_id": TARGET,
            "release_id": release_id, "revision": release["candidate"]["revision"], "stage": "blocked",
            "reason_code": "release_rejected", "merged_revision": release["candidate"]["revision"]})
    world.tick()        # the REAL consumer observes the original rejection and pauses the family
    paused = only(world.intents(), route=dc.DELIVERY)
    assert (paused["state"], paused["reason_code"]) == (dc.PAUSED, "delivery_blocked")
    approval = {"source_release_id": release_id, "base": release["candidate"]["base"],
                "evaluator_revision": "7" * 40, "evaluator_tree": "8" * 40, "patch_sha256": "6" * 64,
                "paths": ["tests/test_x.py"], "evidence": "sha256:" + "9" * 64, "approved_by": "lead:root"}
    doc = {"policy_id": "owners-1", "intent_id": paused["id"], "lane": "a", "target_id": TARGET,
           "source_release_id": release_id, "source_policy_hash": "e" * 64,
           "candidate_revision": release["candidate"]["revision"], "old_plan_id": plan["plan_id"],
           "old_plan_sha256": plan_digest(plan), "approval": approval, "evidence": approval["evidence"],
           "actor": "lead:root"}
    return {"world": world, "owner": owner, "ports": ports, "lane": lane, "log": log, "targets": targets,
            "paused": paused, "doc": doc, "release_id": release_id, "only": only}


def owner_ticks(p, *, restart=False, until="completed", ticks=12):
    for _ in range(ticks):
        owner = OwnerActions(p["world"].control, clock=lambda: NOW, **p["ports"]) if restart else p["owner"]
        receipt = owner.tick("owners-1")
        row = rows(p["world"].control, BUCKET_MIGRATIONS)[p["release_id"]]
        if row["state"] == until or row["state"] in do.TERMINAL:
            return row, receipt
    return row, receipt


def lane_verifies_successor(p, row):
    """LABELLED stand-in for the lane controller's verification of the (acknowledged) successor."""
    with p["world"].lane.store.transaction() as tx:
        intent = tx.get("host_delivery_intents", row["plan_id"])
        assert intent["held"] is None, "only an acknowledged successor is ever verified"
        tx.put("host_delivery_intents", row["plan_id"], {**intent, "stage": "active"})


@pytest.mark.parametrize("restart", [False, True])
def test_a_paused_source_is_resumed_once_by_the_finalized_migration_and_the_real_tick_reaches_next_item(
        tmp_path, restart):
    p = paused_world(tmp_path)
    world, only = p["world"], p["only"]
    p["owner"].request_migration(p["doc"])
    assert rows(world.control, BUCKET_MIGRATIONS)[p["release_id"]]["source_intent"]["state"] == dc.PAUSED
    row, _ = owner_ticks(p, restart=restart, until="bound")
    assert row["state"] == "bound"
    controller = world.build() if restart else world.controller
    world.tick(controller)
    assert only(world.intents(), route=dc.DELIVERY) == p["paused"], "no auto-resume before the acknowledgement"
    row, _ = owner_ticks(p, restart=restart)
    assert (row["state"], row["source_resumed"]) == (do.COMPLETED, True), row["history"]
    resumed = only(world.intents(), route=dc.DELIVERY)
    assert (resumed["state"], resumed["reason_code"], resumed["version"]) == (
        dc.AWAITING_OWNER, "migration_resumed", p["paused"]["version"] + 1)
    record = resumed["migration_resume"]
    assert (record["from_state"], record["from_version"], record["paused_reason_code"]) == (
        dc.PAUSED, p["paused"]["version"], "delivery_blocked")
    assert (record["migration_id"], record["plan_id"]) == (row["migration_id"], row["plan_id"])
    assert resumed["history"][:-1] == p["paused"]["history"] and resumed["history"][-1]["previous"] == dc.PAUSED
    assert resumed["release_id"] == p["release_id"], "the conductor's release id stays as provenance"
    controller = world.build() if restart else world.controller
    world.tick(controller)                                   # successor still verifying: a quiet wait
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER
    lane_verifies_successor(p, row)
    world.tick(world.build() if restart else controller)
    intents = world.intents()
    delivered = only(intents, route=dc.DELIVERY)
    assert (delivered["state"], delivered["reason_code"]) == (dc.COMPLETED, "delivery_active")
    assert delivered["delivery_plan"]["plan_id"] == row["plan_id"]
    assert only(intents, route=dc.NEXT_ITEM)["predecessor_intent"] == delivered["id"]
    assert len([e for e in p["log"] if e[0] == "finalize"]) == 1
    settled = rows(world.control, "continuation_intents")
    owner_ticks(p, restart=restart, ticks=2)
    world.tick()
    assert rows(world.control, "continuation_intents") == settled, "nothing is resumed or delivered twice"


def test_a_source_moved_between_bound_and_finalize_is_held_and_never_resumed(tmp_path):
    p = paused_world(tmp_path)
    world, only = p["world"], p["only"]
    p["owner"].request_migration(p["doc"])
    row, _ = owner_ticks(p, until="bound")
    with world.control.transaction() as tx:          # LABELLED: another owner moved the source (a CAS)
        intent = tx.get("continuation_intents", p["paused"]["id"])
        tx.put("continuation_intents", intent["id"], {**intent, "version": intent["version"] + 1})
    moved = only(world.intents(), route=dc.DELIVERY)
    lane_before = deepcopy(rows(world.lane.store, "host_delivery_migrations"))
    for _ in range(3):
        receipt = p["owner"].tick("owners-1")
        assert receipt["waits"][row["action_id"]] == "migration_readiness_source_intent"
    assert rows(world.control, BUCKET_MIGRATIONS)[p["release_id"]] == row
    assert rows(world.lane.store, "host_delivery_migrations") == lane_before
    world.tick()
    assert only(world.intents(), route=dc.DELIVERY) == moved, "PAUSED stays PAUSED: no global resume"


def test_a_source_moved_after_the_lane_ack_refuses_the_resume_inside_the_completing_transaction(tmp_path):
    p = paused_world(tmp_path)
    world, only = p["world"], p["only"]
    p["owner"].request_migration(p["doc"])
    row, _ = owner_ticks(p, until="bound")
    lane, finalize = p["lane"], p["lane"].finalize_migration

    def finalize_then_move(migration_id, ack):     # LABELLED: the source moves after the lane commit
        result = finalize(migration_id, ack)
        with world.control.transaction() as tx:
            intent = tx.get("continuation_intents", p["paused"]["id"])
            tx.put("continuation_intents", intent["id"], {**intent, "version": intent["version"] + 1})
        return result

    lane.finalize_migration = finalize_then_move
    receipt = p["owner"].tick("owners-1")
    assert receipt["waits"][row["action_id"]] == "migration_source_changed"
    assert rows(world.control, BUCKET_MIGRATIONS)[p["release_id"]] == row, "bound, nothing written"
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.PAUSED
    again = p["owner"].tick("owners-1")
    assert again["waits"][row["action_id"]] == "migration_readiness_source_intent"


@pytest.mark.integration
def test_pg_paused_source_resumes_through_the_real_continuation_tick_to_next_item(
        tmp_path, isolated_pgstore, second_pgstore):
    """TWO isolated PostgreSQL schemas: control (Fleet, Continuation, OwnerActions) and lane (Harness,
    LaneEvidence, the LABELLED FakeLane migration interface); restart = fresh owners every tick."""
    p = paused_world(tmp_path, pg_continuation_world(tmp_path, isolated_pgstore, second_pgstore))
    world, only = p["world"], p["only"]
    assert world.control is isolated_pgstore and world.lane.store is second_pgstore
    assert isolated_pgstore is not second_pgstore
    p["owner"].request_migration(p["doc"])
    row, _ = owner_ticks(p, restart=True)
    assert (row["state"], row["source_resumed"]) == (do.COMPLETED, True), row["history"]
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER
    lane_verifies_successor(p, row)
    world.tick(world.build())
    delivered = only(world.intents(), route=dc.DELIVERY)
    assert (delivered["state"], delivered["delivery_plan"]["plan_id"]) == (dc.COMPLETED, row["plan_id"])
    assert only(world.intents(), route=dc.NEXT_ITEM)["predecessor_intent"] == delivered["id"]
