"""INV-OWNER-ACTIONS-001, aibox-migration-001 SPEC s14 G2: exact approved delivery-plan publication and
the owner's actual canary handoff.

Real: the Fleet, finite Operation, continuation owner, `Releases` (propose/review/verify), `HostDelivery`
(registry, `approval`, `register`, stages, canary gate, rollback) with a real owned process target, and a
real temporary Git repository the plan is published into. LABELLED fixtures: the lane executor, the
conductor (it records the reviewed release through the real `Releases` owner), the GitHub port
(`FakeGitHub`) and the canary operation's executor (`test_continuation.FakeExecutor` via `World.run_next`).
No model, provider, network, live service or production store is touched; injected faults are labelled.
"""
from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from test_continuation import GOAL, ConductorFixture, World, manifest, only
from test_host_delivery import (
    REPOSITORY,
    await_receipt,
    binds_a_runtime,
    build,
    candidate,
    descriptor_of,
    drive,
    fixture_git,
    intent_of,
    pin,
    plan_document,
    release_policy,
    reviewed_release,
    stop_target,
    targets_document,
)

from codex_harness.adapters.host_delivery import (
    CANARY_RECEIPT_FILE,
    RECEIPT_FILE,
    owner_qualified_canary,
    startup_identity_canary,
)
from codex_harness.adapters.owner_actions import GitPlanPublisher, TargetFiles
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_delivery import HostDelivery
from codex_harness.application.owner_actions import BUCKET_ACTIONS, OwnerActions, plan_json
from codex_harness.application.releases import Releases
from codex_harness.bootstrap import organization
from codex_harness.domain import continuation as dc
from codex_harness.domain import owner_actions as do
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CONSUMPTION,
    CANARY_FLEET,
    CANARY_REQUEST_SCHEMA,
    CANARY_STARTUP,
    ROLLED_BACK,
    plan_digest,
    validate_plan,
)

TARGET = "fleet-host"
OWNER_PIN = {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"}


def delivery_policy(**overrides):
    return {"target_id": TARGET, "repository": REPOSITORY, "required_checks": ["ci / required"],
            "canary_check_id": CANARY_STARTUP, "ci_timeout_seconds": 300, "consumption_timeout_seconds": 120,
            **overrides}


def owner_policy(canary=None, **delivery):
    return {"schema": do.POLICY_SCHEMA, "id": "owners-1", "enabled": True, "continuation_policy": "policy-1",
            "assessment": {"model_label": "labelled-fixture-assessor"}, "delivery": delivery_policy(**delivery),
            "canary": canary}


class ReleasingConductor(ConductorFixture):
    """LABELLED conductor fixture that records the accepted candidate through the REAL `Releases` owner:
    proposed, reviewed by the author's lead and the conductor, verified under the incumbent checks."""

    def __init__(self, lane, *, repository=REPOSITORY, conductor_review=True):
        super().__init__(lane)
        self.repository, self.conductor_review = repository, conductor_review

    def decide(self, job):
        with self.lane.store.transaction() as tx:
            operation = tx.get("operations", job["id"])
            lead = tx.get("decisions_pending", operation["decision_id"])
            task = tx.get("tasks", operation["task_id"])
        record = {**task["result"]["candidate"], "author": "worker:implementation", "repository": self.repository,
                  "branch": "harness/" + job["id"], "task_id": operation["task_id"], "objective": "fixture"}
        releases = Releases(self.lane.store, self.lane.org)
        row = releases.propose(record, release_policy())
        releases.review(row["id"], "lead:improvement", record["revision"], True, "fixture-lead-review-evidence")
        if self.conductor_review:
            releases.review(row["id"], "conductor", record["revision"], True, "fixture-conductor-review-evidence")
            releases.verify(row["id"], record["revision"], row["policy_hash"],
                            {"tests": {"passed": True, "evidence": "fixture-incumbent-check-receipt"}})
        with self.lane.store.transaction() as tx:
            decision_id = "cond-" + job["id"]
            tx.put("decisions_pending", decision_id, {
                "id": decision_id, "actor": "conductor", "phase": "review_conductor", "status": "succeeded",
                "attempt": 1, "input": lead["input"],
                "message": {"correlation_id": operation["correlation_id"],
                            "what": {"details": {"decision_id": lead["id"]}}},
                "result": {"accepted": True, "reason": "fixture", "execution_ref": "sha256:" + "9" * 64,
                           "deployment": {"status": "queued", "release_id": row["id"]}}})


def git_repository(tmp_path) -> Path:
    root = tmp_path / "owner-source"
    root.mkdir()
    (root / "README.md").write_text("labelled fixture owner source\n", encoding="utf-8")
    fixture_git(root, "init", "-q")
    fixture_git(root, "add", "--all")
    fixture_git(root, "commit", "-q", "--no-verify", "-m", "labelled fixture base")
    return root


class FlakyPublisher(GitPlanPublisher):
    """LABELLED injected faults: fail BEFORE any Git write, or lose the response AFTER the ref moved."""

    def __init__(self, repository, *, before=0, after=0):
        super().__init__(repository)
        self.before, self.after, self.calls = before, after, 0

    def publish(self, data, path, ref, when):
        self.calls += 1
        if self.before:
            self.before -= 1
            raise RuntimeError("git unavailable before the effect (labelled injected fault)")
        result = super().publish(data, path, ref, when)
        if self.after:
            self.after -= 1
            raise TimeoutError("publication response lost after the ref moved (labelled injected fault)")
        return result


class LostRegistration:
    """LABELLED injected fault: the registration happens, then its response is lost once."""

    def __init__(self, inner):
        self.inner, self.store, self.lost, self.calls = inner, inner.store, 1, 0

    def approval(self, plan):
        return self.inner.approval(plan)

    def register(self, plan, pin_):
        self.calls += 1
        result = self.inner.register(plan, pin_)
        if self.lost:
            self.lost -= 1
            raise TimeoutError("registration response lost (labelled injected fault)")
        return result


def delivery_world(tmp_path, *, publisher_factory=GitPlanPublisher, conductor_review=True, repository=REPOSITORY,
                   deliveries=None):
    world = World(tmp_path, conductor=False)
    world.conductor = ReleasingConductor(world.lane, repository=repository, conductor_review=conductor_review)
    world.controller = world.build()
    world.register()
    org = organization()
    host = HostDelivery(world.lane.store, org)
    host.register_targets(targets_document(tmp_path, target_id=TARGET))
    repo = git_repository(tmp_path)
    publisher = publisher_factory(repo)
    owner = OwnerActions(world.control, continuation=world.controller, org=org, lanes=world.lanes,
                         deliveries=deliveries or (lambda lane: host), publisher=lambda lane: publisher,
                         targets=TargetFiles())
    owner.register(owner_policy(), OWNER_PIN)
    world.enqueue("op-1", "docs/a.md")
    world.tick()
    job, receipt = world.run_next(verdict=True)
    assert receipt["status"] == "accepted"
    world.tick()
    world.tick()
    delivery = only(world.intents(), route=dc.DELIVERY)
    assert delivery["state"] == dc.AWAITING_OWNER
    return {"world": world, "owner": owner, "host": host, "repo": repo, "publisher": publisher, "delivery": delivery,
            "job": job}


def rows(world):
    with world.control.transaction() as tx:
        return {row["id"]: row for row in tx.scan(BUCKET_ACTIONS)}


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def settle(owner, ticks=5):
    return [owner.tick("owners-1") for _ in range(ticks)]


# ---- the exact approved plan: owner policy + reviewed release only, Git first, then registration -----------
def test_a_conducted_release_is_published_as_the_exact_owner_plan_and_registered_once(tmp_path):
    system = delivery_world(tmp_path)
    world, owner, host, repo = system["world"], system["owner"], system["host"], system["repo"]
    settle(owner)
    [action] = rows(world).values()
    assert action["kind"] == do.DELIVERY_PLAN and action["state"] == do.COMPLETED
    plan = action["plan"]
    with world.lane.store.transaction() as tx:
        release = tx.get("releases", system["delivery"]["release_id"])
    # Every authority field is the owner's; every identity field is the reviewed record's.
    assert plan["target_id"] == TARGET and plan["required_checks"] == ["ci / required"]
    assert plan["repository"] == REPOSITORY and plan["canary_check_id"] == CANARY_STARTUP
    assert (plan["release_id"], plan["revision"], plan["tree"], plan["policy_hash"]) == (
        release["id"], release["candidate"]["revision"], release["candidate"]["tree"], release["policy_hash"])
    assert plan["target_descriptor"] == {"revision": release["candidate"]["revision"], "worker_image": "unchanged",
                                         "profile_digest": "unchanged"}
    assert plan["expected_descriptor"] is None and validate_plan(plan) == plan
    # Git holds exactly these bytes at the recorded commit on the owner ref; the working tree is untouched.
    assert git(repo, "rev-parse", do.plan_ref(plan["plan_id"])) == action["commit"]
    shown = subprocess.run(["git", "-C", str(repo), "show", action["commit"] + ":" + do.plan_path(plan["plan_id"])],
                           capture_output=True, check=True).stdout
    assert shown == plan_json(plan) and git(repo, "status", "--porcelain") == ""
    # The existing HostDelivery registered the plan read back from Git, pinned to that commit and those bytes.
    registered = host.plan(plan["plan_id"])
    assert registered["plan"] == plan and registered["pin"]["revision"] == action["commit"]
    assert registered["pin"]["sha256"] == action["bytes_sha256"] == digest_bytes(plan_json(plan))
    # The continuation now observes the bound delivery of exactly this release: no second plan is owed.
    world.tick()
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER
    snapshot, lane = deepcopy(world.control.data), deepcopy(world.lane.store.data)
    refs = git(repo, "for-each-ref", "refs/zeus")
    settle(owner, 3)
    settle(OwnerActions(world.control, continuation=world.controller, org=organization(), lanes=world.lanes,
                        deliveries=lambda _: host, publisher=lambda _: system["publisher"], targets=TargetFiles()), 3)
    assert world.control.data == snapshot and world.lane.store.data == lane
    assert git(repo, "for-each-ref", "refs/zeus") == refs


def digest_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def test_an_unapproved_foreign_or_busy_release_publishes_nothing(tmp_path):
    # The conductor's review is missing: the existing gate says not approved; nothing is published.
    system = delivery_world(tmp_path / "unreviewed", conductor_review=False)
    result = system["owner"].tick("owners-1")
    assert result["created"] == [] and "release_reviews_incomplete" in result["waits"].values()
    assert rows(system["world"]) == {} and git(system["repo"], "for-each-ref", "refs/zeus") == ""
    # A candidate of another repository can never get a plan under this owner policy.
    foreign = delivery_world(tmp_path / "foreign", repository="github:someone-else/other-repo")
    result = foreign["owner"].tick("owners-1")
    assert "candidate_repository_foreign" in result["waits"].values() and rows(foreign["world"]) == {}
    # Another delivery in flight on the target: the plan waits rather than race or re-point it.
    busy = delivery_world(tmp_path / "busy")
    with busy["world"].lane.store.transaction() as tx:
        tx.put("host_delivery_intents", "other-plan", {"id": "other-plan", "plan_id": "other-plan",
                                                        "target_id": TARGET, "revision": "1" * 40,
                                                        "release_id": "other", "stage": "awaiting_ci"})
    result = busy["owner"].tick("owners-1")
    assert "delivery_target_busy" in result["waits"].values() and rows(busy["world"]) == {}
    # Once that delivery finished, the target's history of OTHER revisions (`stale`) owes this candidate its plan.
    with busy["world"].lane.store.transaction() as tx:
        row = tx.get("host_delivery_intents", "other-plan")
        tx.put("host_delivery_intents", "other-plan", {**row, "stage": "active"})
    settle(busy["owner"])
    [action] = rows(busy["world"]).values()
    assert action["state"] == do.COMPLETED and busy["host"].plan(action["plan_id"]) is not None


def test_the_plan_can_never_carry_a_candidate_chosen_target_path_or_command():
    policy = do.validate_policy(owner_policy())
    binding = {"policy_id": "owners-1", "policy_sha256": "a" * 64, "intent_id": "b" * 64, "target_id": TARGET,
               "release_id": "r1", "revision": "c" * 40, "tree": "d" * 40, "policy_hash": "e" * 64,
               "repository": REPOSITORY, "expected_descriptor": None}
    plan = do.build_plan(policy, binding, "f" * 64)
    assert set(plan) == set(validate_plan(plan)) and "root" not in plan and "service" not in plan
    with pytest.raises(do.OwnerActionRefused, match="delivery_target_foreign"):
        do.build_plan(policy, {**binding, "target_id": "another-target"}, "f" * 64)
    with pytest.raises(do.OwnerActionRefused, match="candidate_repository_foreign"):
        do.build_plan(policy, {**binding, "repository": "github:x/y"}, "f" * 64)
    # The owner policy selects the actual canary only together with its fixed canary operation.
    with pytest.raises(do.OwnerActionRefused, match="policy_invalid"):
        do.validate_policy(owner_policy(canary_check_id=CANARY_FLEET))


@pytest.mark.parametrize("fault", ["before", "after"])
def test_a_crash_before_or_after_the_git_effect_publishes_one_commit_and_registers_once(tmp_path, fault):
    system = delivery_world(tmp_path, publisher_factory=lambda repo: FlakyPublisher(repo, **{fault: 1}))
    flaky = system["publisher"]
    settle(system["owner"], 6)
    [action] = rows(system["world"]).values()
    assert action["state"] == do.COMPLETED and flaky.calls == 2
    refs = git(system["repo"], "for-each-ref", "--format=%(refname) %(objectname)", "refs/zeus").splitlines()
    assert refs == [do.plan_ref(action["plan_id"]) + " " + action["commit"]]
    assert system["host"].plan(action["plan_id"])["pin"]["revision"] == action["commit"]


def test_a_lost_registration_response_is_recognized_as_the_cached_registration(tmp_path):
    lost = {}
    system = delivery_world(tmp_path, deliveries=lambda lane: lost["port"])
    lost["port"] = LostRegistration(system["host"])
    settle(system["owner"], 6)
    [action] = rows(system["world"]).values()
    assert action["state"] == do.COMPLETED and action["registration"]["cached"] is True
    assert lost["port"].calls == 2 and system["host"].plan(action["plan_id"])["plan"] == action["plan"]


def test_a_ref_that_names_other_content_is_held_as_a_conflict_and_never_overwritten(tmp_path):
    system = delivery_world(tmp_path)
    world, owner, repo = system["world"], system["owner"], system["repo"]
    owner.tick("owners-1")                 # the intent: plan bytes and ref persisted before Git
    [action] = rows(world).values()
    assert action["state"] == do.PUBLISHING
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", action["ref"], head)   # LABELLED injected foreign ref content
    settle(owner, 3)
    [action] = rows(world).values()
    assert action["state"] == do.UNKNOWN and action["reason_code"] == "plan_ref_conflict"
    assert git(repo, "rev-parse", action["ref"]) == head and system["host"].plan(action["plan_id"]) is None


# ---- the opt-in canary wait: pending only for the owner's matching request, never past the deadline -------
def canary_system(tmp_path, *, consumption_timeout=120):
    """An active predecessor on a real process target, then a successor plan whose canary is the owner's
    actual `fleet_worker_operation` (the incumbent check reading the owner receipt)."""
    system = build(tmp_path, target_id=TARGET, canaries={CANARY_STARTUP: startup_identity_canary,
                                                           CANARY_FLEET: owner_qualified_canary})
    assert drive(system)[-1]["stage"] == ACTIVE
    good = descriptor_of(system, TARGET)
    successor = reviewed_release(system["store"], system["org"],
                                 record_candidate={**candidate(), "revision": "5" * 40, "branch": "harness/two",
                                                   "task_id": "two"})
    plan = plan_document(successor, plan_id="delivery-plan-2", target_id=TARGET, expected=good["descriptor_sha256"],
                         canary=CANARY_FLEET, consumption_timeout=consumption_timeout)
    system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
    system["plan"], system["good"] = plan, good
    return system


def request_for(system, **overrides):
    plan = system["plan"]
    document = {"schema": CANARY_REQUEST_SCHEMA, "action_id": "a" * 64, "plan_id": plan["plan_id"],
                "plan_sha256": plan_digest(validate_plan(plan)), "target_id": TARGET,
                "revision": plan["target_descriptor"]["revision"], "expected_descriptor": plan["expected_descriptor"],
                "requested_at": "2026-09-25T00:00:00+00:00", **overrides}
    TargetFiles.write_request(system["target"], document)


def consuming(system, limit=40):
    results = drive(system, until=AWAITING_CONSUMPTION, limit=limit)
    assert results[-1]["stage"] == AWAITING_CONSUMPTION, [(r["stage"], r["reason_code"]) for r in results]
    # The candidate's OWN startup receipt, waited for within a bound (it is written asynchronously).
    await_receipt(system["target"], intent_of(system)["descriptor_sha256"], timeout=30.0)
    return results


def owner_receipt(system, passed):
    intent = intent_of(system)
    startup = json.loads((Path(system["target"]["state_dir"]) / RECEIPT_FILE).read_text("utf-8"))
    TargetFiles.write_receipt(system["target"], {"schema": "urn:zeus:owner-canary-receipt:1",
                                                 "descriptor_sha256": intent["descriptor_sha256"],
                                                 "instance_id": startup["instance_id"], "passed": passed,
                                                 "evidence": {"labelled": "fixture owner canary outcome"}})


@binds_a_runtime
def test_a_matching_owner_request_waits_for_the_actual_canary_and_only_its_passed_receipt_activates(tmp_path):
    system = canary_system(tmp_path)
    try:
        request_for(system)
        consuming(system)
        waits = [system["delivery"].tick() for _ in range(3)]
        assert {r["reason_code"] for r in waits if r["stage"] == AWAITING_CONSUMPTION} >= {
            "canary_owner_receipt_pending"}
        assert intent_of(system)["stage"] == AWAITING_CONSUMPTION, "pending is never a pass or a rollback"
        with system["store"].transaction() as tx:
            assert tx.get("deployment", "active")["release_id"] != system["plan"]["release_id"]
        owner_receipt(system, True)
        assert drive(system)[-1]["stage"] == ACTIVE
        assert intent_of(system)["canary"]["passed"] is True
    finally:
        stop_target(system)


@binds_a_runtime
@pytest.mark.parametrize("case", ["deadline", "failed", "unmatched"])
def test_a_missing_failed_or_unrequested_owner_canary_never_activates_and_restores_the_predecessor(tmp_path, case):
    system = canary_system(tmp_path, consumption_timeout=10)
    try:
        if case != "unmatched":
            request_for(system)
        else:
            request_for(system, revision="7" * 40)      # a request for another delivery changes nothing
        consuming(system)
        if case == "failed":
            owner_receipt(system, False)
        results = drive(system, until=ROLLED_BACK, limit=60)
        assert results[-1]["stage"] == ROLLED_BACK, [(r["stage"], r["reason_code"]) for r in results]
        reason = intent_of(system)["rollback"]["reason_code"]
        assert reason == {"deadline": "canary_owner_receipt_pending", "failed": "canary_owner_receipt_failed",
                          "unmatched": "canary_owner_receipt_missing"}[case]
        assert descriptor_of(system, TARGET)["descriptor_sha256"] == system["good"]["descriptor_sha256"]
        with system["store"].transaction() as tx:
            assert tx.get("deployment", "active")["release_id"] != system["plan"]["release_id"]
    finally:
        stop_target(system)


# ---- the coordinator's actual canary: the fixed operation runs, its independent review decides -----------
def canary_owner(tmp_path, system, *, verdict=True):
    """The coordinator over the delivery store of `system` (lane "a") and a World whose Fleet admits
    and runs the owner's fixed canary operation (LABELLED fixture executor)."""
    world = World(tmp_path / "control")
    world.register()
    org = organization()
    template = manifest("canary-template", "docs/c.md")
    policy = owner_policy(canary={"lane": "a", "manifest": template, "goal": GOAL}, canary_check_id=CANARY_FLEET,
                          consumption_timeout_seconds=120)
    owner = OwnerActions(world.control, continuation=world.controller, org=org, lanes=world.lanes,
                         deliveries=lambda lane: system["delivery"], publisher=lambda lane: None,
                         targets=TargetFiles(), fleet=world.fleet, validate=lambda m: m)
    owner.register(policy, OWNER_PIN)
    plan = validate_plan(system["plan"])
    completed = {"id": "p" * 64, "kind": do.DELIVERY_PLAN, "state": do.COMPLETED, "binding": {},
                 "binding_sha256": "q" * 64, "policy_id": "owners-1", "policy_sha256": "r" * 64,
                 "subject": {"intent_id": "s" * 64, "lane": "a"}, "plan": plan, "plan_id": plan["plan_id"],
                 "plan_sha256": plan_digest(plan), "created_at": "2026-09-25T00:00:00+00:00", "version": 4,
                 "history": [], "reason_code": "plan_registered"}
    with world.control.transaction() as tx:
        # LABELLED: the completed plan action the G2 publication test above produces for this plan.
        tx.put(BUCKET_ACTIONS, completed["id"], completed)
    return world, owner


@binds_a_runtime
@pytest.mark.parametrize("verdict", [True, False])
def test_the_owner_runs_the_fixed_canary_and_writes_the_instance_bound_receipt_only_from_its_outcome(tmp_path,
                                                                                                  verdict):
    system = canary_system(tmp_path / "delivery")
    try:
        request_for(system)
        consuming(system)
        world, owner = canary_owner(tmp_path, system)
        owner.tick("owners-1")                      # discovers the consuming instance and requests the canary
        [canary] = [r for r in rows(world).values() if r["kind"] == do.DELIVERY_CANARY]
        assert canary["state"] == do.REQUESTED and canary["job_id"] in world.jobs()
        startup = json.loads((Path(system["target"]["state_dir"]) / RECEIPT_FILE).read_text("utf-8"))
        assert canary["binding"]["instance_id"] == startup["instance_id"]
        assert canary["binding"]["descriptor_sha256"] == intent_of(system)["descriptor_sha256"]
        # While the actual operation runs, nothing is written for the delivery and it only waits.
        owner.tick("owners-1")
        assert not (Path(system["target"]["state_dir"]) / CANARY_RECEIPT_FILE).exists()
        assert system["delivery"].tick()["reason_code"] == "canary_owner_receipt_pending"
        job, receipt = world.run_next(verdict=verdict)
        assert job == canary["job_id"] and receipt["status"] == ("accepted" if verdict else "rejected")
        owner.tick("owners-1")
        [canary] = [r for r in rows(world).values() if r["kind"] == do.DELIVERY_CANARY]
        written = json.loads((Path(system["target"]["state_dir"]) / CANARY_RECEIPT_FILE).read_text("utf-8"))
        assert written["passed"] is verdict and written["instance_id"] == startup["instance_id"]
        assert written["evidence"]["job_id"] == job
        if verdict:
            assert canary["state"] == do.COMPLETED
            assert drive(system)[-1]["stage"] == ACTIVE
        else:
            assert canary["state"] == do.REJECTED
            assert drive(system, until=ROLLED_BACK, limit=60)[-1]["stage"] == ROLLED_BACK
        # One canary operation, however often the owner wakes.
        before = len(world.jobs())
        for _ in range(3):
            owner.tick("owners-1")
        assert len(world.jobs()) == before
    finally:
        stop_target(system)


@binds_a_runtime
def test_an_unknown_canary_writes_no_receipt_and_the_delivery_rolls_back_at_its_own_deadline(tmp_path):
    system = canary_system(tmp_path / "delivery", consumption_timeout=10)
    try:
        request_for(system)
        consuming(system)
        world, owner = canary_owner(tmp_path, system)
        owner.tick("owners-1")
        [canary] = [r for r in rows(world).values() if r["kind"] == do.DELIVERY_CANARY]
        with world.control.transaction() as tx:     # LABELLED injected unknown effect of the canary job
            job = tx.get("fleet_jobs", canary["job_id"])
            tx.put("fleet_jobs", job["id"], {**job, "status": "unknown", "reason_code": "exception:injected"})
        owner.tick("owners-1")
        [canary] = [r for r in rows(world).values() if r["kind"] == do.DELIVERY_CANARY]
        assert canary["state"] == do.UNKNOWN and canary["reason_code"] == "canary_job_unknown"
        assert not (Path(system["target"]["state_dir"]) / CANARY_RECEIPT_FILE).exists()
        assert drive(system, until=ROLLED_BACK, limit=60)[-1]["stage"] == ROLLED_BACK
    finally:
        stop_target(system)


def test_the_canary_verdict_needs_the_actual_accepted_operation_and_its_independent_review():
    job = {"id": "canary-1", "status": "accepted"}
    lead = {"id": "d1", "phase": "review_lead", "status": "succeeded",
            "result": {"accepted": True, "execution_ref": "sha256:" + "a" * 64}}
    good = {"operation": {"status": "accepted"}, "lead": lead, "markers": []}
    assert do.canary_outcome(job, good)["state"] == do.VERDICT_ACCEPTED
    assert do.canary_outcome({**job, "status": "dispatching"}, good)["state"] == "running"
    assert do.canary_outcome(job, {**good, "markers": ["m1"]})["state"] == do.VERDICT_UNKNOWN
    assert do.canary_outcome(job, {**good, "lead": {**lead, "result": {"accepted": True}}})["state"] == \
        do.VERDICT_UNKNOWN
    assert do.canary_outcome(job, {**good, "lead": {**lead, "phase": "review_conductor"}})["state"] == \
        do.VERDICT_UNKNOWN
    assert do.canary_outcome({**job, "status": "rejected"}, good)["state"] == do.VERDICT_REJECTED
    assert do.canary_outcome({**job, "status": "unknown"}, good)["state"] == do.VERDICT_UNKNOWN



# ---- R2: a persisted canary intent admits work only while its delivery binding is still current ------------
class CapturingFleet:
    """LABELLED Fleet stand-in: records admissions and writes the job row as the real `enqueue` would."""

    def __init__(self, store):
        self.store, self.calls = store, []

    def enqueue(self, lane, manifest, goal, dependencies):
        self.calls.append(manifest["id"])
        with self.store.transaction() as tx:
            tx.put("fleet_jobs", manifest["id"], {"id": manifest["id"], "lane": lane, "status": "queued"})
        return {"job": {"id": manifest["id"]}, "cached": False}


class StartupFiles:
    """LABELLED target-file port: the candidate's startup receipt as the owner would read it."""

    def __init__(self, receipt):
        self.receipt = receipt

    def startup(self, target):
        return self.receipt


def admission(stage=AWAITING_CONSUMPTION, plan_sha="1" * 64, descriptor="2" * 64, instance="inst-1",
              state=do.INTENDED):
    """Control and delivery MemoryStores holding one completed plan action, its delivery intent and one
    canary action bound to (plan, target, descriptor, instance); the parameters move one piece."""
    control, lane = MemoryStore(), MemoryStore()
    plan = {"plan_id": "plan-1", "target_id": TARGET}
    plan_action = {"id": "p" * 64, "kind": do.DELIVERY_PLAN, "state": do.COMPLETED, "plan": plan,
                   "plan_id": "plan-1", "plan_sha256": "1" * 64, "subject": {"intent_id": "s" * 64, "lane": "a"}}
    binding = {"plan_id": "plan-1", "plan_sha256": "1" * 64, "target_id": TARGET, "descriptor_sha256": "2" * 64,
               "instance_id": "inst-1"}
    action = {"id": "c" * 64, "kind": do.DELIVERY_CANARY, "state": state, "binding": binding,
              "subject": {"intent_id": "s" * 64, "lane": "a"}, "version": 2, "history": [], "reason_code": None}
    if state == do.REQUESTED:
        action["job_id"] = do.canary_job_id(action["id"])
    with control.transaction() as tx:
        tx.put(BUCKET_ACTIONS, plan_action["id"], plan_action)
        tx.put(BUCKET_ACTIONS, action["id"], action)
    with lane.transaction() as tx:
        tx.put("host_delivery_intents", "plan-1", {"plan_id": "plan-1", "stage": stage, "plan_sha256": plan_sha,
                                                   "target_id": TARGET, "descriptor_sha256": descriptor})
        tx.put("host_delivery_targets", TARGET, {"id": TARGET})
    fleet = CapturingFleet(control)
    owner = OwnerActions(control, lanes=lambda lane_id: None, fleet=fleet,
                         deliveries=lambda lane_id: type("Delivery", (), {"store": lane})(),
                         targets=StartupFiles({"instance_id": instance, "descriptor_sha256": "2" * 64}))
    policy = {"policy": {"canary": {"lane": "a", "manifest": {"id": "template"}, "goal": {}}}}
    return owner, policy, action, fleet, control


def current(control, identity):
    with control.transaction() as tx:
        return tx.get(BUCKET_ACTIONS, identity)


@pytest.mark.parametrize("state", [do.INTENDED, do.REQUESTED])
# Deadline passed (rolling back / rolled back), replaced instance, switched descriptor, another plan version.
@pytest.mark.parametrize("moved", [{"stage": "rolling_back"}, {"stage": ROLLED_BACK},
                                   {"instance": "inst-replaced"}, {"descriptor": "3" * 64}, {"plan_sha": "9" * 64}])
def test_a_stale_canary_intent_is_refused_before_first_admission_and_before_missing_job_replay(state, moved):
    owner, policy, action, fleet, control = admission(state=state, **moved)
    effect = owner._advance_canary(policy, {}, action)
    assert effect["state"] == do.REFUSED and effect["reason_code"] == "canary_delivery_moved"
    assert fleet.calls == [] and current(control, action["id"])["state"] == do.REFUSED
    # Refused is terminal: a later wakeup admits nothing either.
    assert owner._advance_canary(policy, {}, current(control, action["id"])) is None and fleet.calls == []


def test_a_current_canary_intent_admits_once_and_a_missing_job_replay_keeps_the_same_identity():
    owner, policy, action, fleet, control = admission()
    effect = owner._advance_canary(policy, {}, action)
    assert effect["state"] == do.REQUESTED and fleet.calls == [do.canary_job_id(action["id"])]
    # LABELLED lost admission response: the row is REQUESTED but its job row never committed.
    owner, policy, action, fleet, control = admission(state=do.REQUESTED)
    assert owner._advance_canary(policy, {}, action) is None
    assert fleet.calls == [action["job_id"]] and current(control, action["id"])["state"] == do.REQUESTED
    # Once the job exists the replay admits nothing more.
    owner._advance_canary(policy, {}, current(control, action["id"]))
    assert fleet.calls == [action["job_id"]]


def test_an_admitted_canary_whose_delivery_moved_keeps_the_result_time_refusal():
    owner, policy, action, fleet, control = admission(state=do.REQUESTED, instance="inst-replaced")
    with control.transaction() as tx:
        tx.put("fleet_jobs", action["job_id"], {"id": action["job_id"], "lane": "a", "status": "accepted"})
    effect = owner._advance_canary(policy, {}, action)
    assert effect["state"] == do.UNKNOWN and effect["reason_code"] == "canary_delivery_moved" and fleet.calls == []
