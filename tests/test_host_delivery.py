"""Durable host delivery: plan policy, the release fence, real host targets, canary and rollback
(INV-HOST-DELIVERY-001).

The GitHub port here is a labelled in-test double: no `gh`, no network, no GitHub mutation, no
scheduled-task mutation, no provider and no model call happens anywhere in this module, and every
injected outage is labelled where it is injected. The HOST side is real - an actual temporary state
directory, an actual descriptor file replaced atomically, an actual detached child process started
from this interpreter through the shipped service entry, and the actual startup receipt that child
writes about itself. The one integration-gated test at the end skips honestly without
`HARNESS_INTEGRATION=1`.

The store is `SerialStore`: a MemoryStore that REFUSES a transaction opened while another one is
already open. The real `PostgresStore.transaction` connects and takes `pg_advisory_xact_lock` per
transaction, so a nested call would block until `lock_timeout`; this fixture turns that latent
deadlock into an immediate failure for every path below, including the `Releases` and
`ReleaseQueue` calls, which open their own transactions.
"""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    WORK_FILE,
    ProcessHostTarget,
    normalize_checks,
    owner_qualified_canary,
    serve,
    startup_identity_canary,
)
from codex_harness.adapters.observation_spool import MemorySpool
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_delivery import (
    BUCKET_DESCRIPTORS,
    BUCKET_INTENTS,
    BUCKET_PLANS,
    HostDelivery,
)
from codex_harness.application.observations import MemoryDirectory, Observer
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.releases import Releases
from codex_harness.bootstrap import organization
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CI,
    AWAITING_CONSUMPTION,
    AWAITING_REVIEW,
    BLOCKED,
    CANARY_FLEET,
    CANARY_STARTUP,
    DRAIN_INTENDED,
    MERGE_INTENDED,
    MERGED,
    PLAN_SCHEMA,
    PUBLISHING,
    REGISTERED,
    REGISTRY_SCHEMA,
    ROLLED_BACK,
    ROLLING_BACK,
    SWITCHING,
    DeliveryRefused,
    ci_verdict,
    consumption_verdict,
    descriptor_digest,
    validate_plan,
    validate_targets,
)
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import new_process_run_id

CANARY_TEXT = "CANARY-must-never-be-emitted"
REVISION = "a" * 40
BASE = "b" * 40
TREE = "c" * 64
IMAGE = "zeus-worker@sha256:" + "d" * 64
PROFILE = "e" * 64
MERGED_REVISION = "9" * 40
REPOSITORY = "github:zeus-owner/zeus-harness"
CHECK = "ci / required"
PLAN_PATH = "docs/zeus/operations/delivery.json"
START = "2026-09-22T00:00:00+00:00"


class SerialStore:
    """MemoryStore with the real control-plane contract made observable: opening a transaction
    inside another one is the nested case that deadlocks on the PostgreSQL advisory lock."""

    def __init__(self):
        self.inner, self.depth, self.transactions = MemoryStore(), 0, 0

    @property
    def data(self):
        return self.inner.data

    @contextmanager
    def transaction(self):
        if self.depth:
            raise AssertionError("a nested store transaction deadlocks the PG advisory lock")
        self.depth, self.transactions = self.depth + 1, self.transactions + 1
        try:
            with self.inner.transaction() as tx:
                yield tx
        finally:
            self.depth -= 1


class Clock:
    """A controllable clock: the controller's stage deadlines and its fence read the same time."""

    def __init__(self, start=START):
        self.at = datetime.fromisoformat(start)

    def __call__(self):
        return self.at.isoformat()

    def advance(self, seconds):
        self.at += timedelta(seconds=seconds)
        return self()


class FakeGitHub:
    """Labelled in-test double for the GitHub port.

    It records what was asked of it and can be told to fail AFTER its effect happened, which is the
    lost-response case; it never runs `gh`, opens a socket or touches a repository.
    """

    def __init__(self, *, checks=((CHECK, "success"),), head=None):
        self.rows = [{"name": name, "state": state} for name, state in checks]
        self.head = head  # None: each candidate's own revision, as a real PR head would be
        self.prs = {}
        self.publishes = self.merges = self.observations = 0
        self.publish_error = self.merge_error = self.observe_error = None

    @property
    def pr(self):
        return next(iter(self.prs.values()), None)

    @pr.setter
    def pr(self, value):
        self.prs[value["branch"]] = value

    def observe(self, candidate):
        self.observations += 1
        if self.observe_error is not None:
            raise self.observe_error  # labelled injected GitHub outage
        row = self.prs.get(candidate["branch"])
        if row is None:
            return None
        return {**row, "checks": list(self.rows)}

    def publish(self, candidate):
        self.publishes += 1
        self.prs[candidate["branch"]] = {
            "number": 181 + len(self.prs), "url": "https://example.invalid/pull/181",
            "head": self.head or candidate["revision"], "state": "OPEN",
            "merged_revision": None, "branch": candidate["branch"]}
        if self.publish_error is not None:
            raise self.publish_error  # labelled injected loss of the publish RESPONSE
        return {**self.prs[candidate["branch"]], "checks": []}

    def merge(self, candidate):
        self.merges += 1
        self.prs[candidate["branch"]] = {**self.prs[candidate["branch"]], "state": "MERGED",
                                         "merged_revision": MERGED_REVISION}
        if self.merge_error is not None:
            raise self.merge_error  # labelled injected loss of the merge RESPONSE
        return {"merged": True, "merged_revision": MERGED_REVISION}


def candidate(revision=REVISION, tree=TREE, repository=REPOSITORY):
    return {"revision": revision, "base": BASE, "tree": tree, "author": "worker:implementation",
            "branch": "harness/delivery-1", "task_id": "delivery-1", "repository": repository,
            "objective": CANARY_TEXT}


def release_policy():
    return {"checks": ["tests"], "evaluator": "fixture-incumbent-policy"}


def reviewed_release(store, org, *, verified=True, record_candidate=None, lead=True, conductor=True):
    """A release record built through the EXISTING Releases authority; no shortcut row is written."""
    releases = Releases(store, org)
    row = releases.propose(record_candidate or candidate(), release_policy())
    if lead:
        releases.review(row["id"], "lead:improvement", row["candidate"]["revision"], True,
                        "fixture-lead-review-evidence")
    if conductor and lead:
        releases.review(row["id"], "conductor", row["candidate"]["revision"], True,
                        "fixture-conductor-review-evidence")
    if verified and lead and conductor:
        releases.verify(row["id"], row["candidate"]["revision"], row["policy_hash"],
                        {"tests": {"passed": True, "evidence": "fixture-incumbent-check-receipt"}})
    with store.transaction() as tx:
        return tx.get("releases", row["id"])


def targets_document(tmp_path, target_id="canary-service", kind="process"):
    return {"schema": REGISTRY_SCHEMA,
            "targets": [{"target_id": target_id, "kind": kind, "root": str(tmp_path / "root"),
                         "state_dir": str(tmp_path / ("state-" + target_id)),
                         "service": "zeus-canary-service"}]}


def plan_document(release, *, plan_id="delivery-plan-1", target_id="canary-service", expected=None,
                  checks=(CHECK,), canary=CANARY_STARTUP, image=IMAGE, profile=PROFILE,
                  revision=None, tree=None, policy_hash=None, repository=REPOSITORY,
                  descriptor_revision=None, ci_timeout=300, consumption_timeout=120):
    return {"schema": PLAN_SCHEMA, "plan_id": plan_id, "release_id": release["id"],
            "revision": revision or release["candidate"]["revision"],
            "tree": tree or release["candidate"]["tree"],
            "policy_hash": policy_hash or release["policy_hash"], "repository": repository,
            "required_checks": list(checks), "target_id": target_id,
            "expected_descriptor": expected,
            "target_descriptor": {"revision": descriptor_revision or REVISION,
                                  "worker_image": image, "profile_digest": profile},
            "canary_check_id": canary, "ci_timeout_seconds": ci_timeout,
            "consumption_timeout_seconds": consumption_timeout}


def pin(path=PLAN_PATH, revision="f" * 40, body=b"fixture-plan-bytes"):
    return {"revision": revision, "path": path, "sha256": hashlib.sha256(body).hexdigest()}


def observer_for(store):
    return Observer(store, MemorySpool(new_process_run_id()), component="unit",
                    directory=MemoryDirectory())


def build(tmp_path, *, github=None, canaries=None, enabled=True, clock=None, observer=None,
          store=None, org=None, max_seconds=60, target_id="canary-service", kind="process",
          verified=True, lead=True, conductor=True, plan_overrides=None, register_plan=True):
    """One wired controller over a real process target and a labelled GitHub double."""
    store = store or SerialStore()
    org = org or organization()
    clock = clock or Clock()
    release = reviewed_release(store, org, verified=verified, lead=lead, conductor=conductor)
    host = ProcessHostTarget(max_seconds=max_seconds)
    delivery = HostDelivery(store, org, github=github if github is not None else FakeGitHub(),
                            hosts={kind: host},
                            canaries=canaries or {CANARY_STARTUP: startup_identity_canary,
                                                  CANARY_FLEET: owner_qualified_canary},
                            clock=clock, observer=observer, enabled=enabled, resume_seconds=0)
    delivery.register_targets(targets_document(tmp_path, target_id=target_id, kind=kind))
    plan = plan_document(release, target_id=target_id, **(plan_overrides or {}))
    if register_plan:
        delivery.register(plan, pin())
    return {"store": store, "org": org, "clock": clock, "delivery": delivery, "release": release,
            "plan": plan, "host": host, "github": delivery.github,
            "target": targets_document(tmp_path, target_id=target_id, kind=kind)["targets"][0]}


def drive(system, *, until=ACTIVE, limit=40, sleep=0.05):
    """Tick until the delivery reaches a stage, giving the REAL child process time to report.

    The controller's clock moves one second per tick, as a real bounded loop's would, so a stage
    deadline is reached by ticking rather than by a test reaching into the intent.
    """
    results = []
    for _ in range(limit):
        result = system["delivery"].tick()
        system["clock"].advance(1)
        results.append(result)
        if result["stage"] in {until, BLOCKED, ROLLED_BACK}:
            if result["stage"] == until:
                return results
        if result["outcome"] == "pending":
            time.sleep(sleep)
        if result["outcome"] in {"blocked", "refused"}:
            return results
    return results


def stages(results):
    return [result["stage"] for result in results]


def visited(results):
    """The stages in order with consecutive repeats collapsed; a bounded wait is not a new stage."""
    seen = []
    for stage in stages(results):
        if not seen or seen[-1] != stage:
            seen.append(stage)
    return seen


def intent_of(system):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_INTENTS, system["plan"]["plan_id"])


def descriptor_of(system, target_id="canary-service"):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_DESCRIPTORS, target_id)


def stop_target(system):
    """Leave no owned child process behind, whatever the test proved."""
    try:
        system["host"].stop(system["target"])
    except Exception:  # cleanup is best effort; a leaked pid is reported by the test that made it
        pass


# ----- plan and registry grammar -----------------------------------------------------------------
def test_plan_grammar_refuses_unknown_fields_bad_identities_and_foreign_canaries(tmp_path):
    good = plan_document({"id": "release-1", "candidate": {"revision": REVISION, "tree": TREE},
                          "policy_hash": "1" * 64})
    canonical = validate_plan(good)
    assert canonical["required_checks"] == [CHECK] and canonical["expected_descriptor"] is None
    for field, value in (("plan_id", "not a token"), ("revision", "z" * 40), ("tree", "c" * 63),
                         ("policy_hash", 1), ("repository", "https://github.com/o/r"),
                         ("required_checks", []), ("required_checks", [CHECK, CHECK]),
                         ("canary_check_id", "rm -rf /"), ("target_id", "../other"),
                         ("expected_descriptor", "short"), ("ci_timeout_seconds", 1),
                         ("ci_timeout_seconds", True), ("consumption_timeout_seconds", 10 ** 9)):
        with pytest.raises(DeliveryRefused) as refused:
            validate_plan({**good, field: value})
        assert CANARY_TEXT not in str(refused.value) and str(value) not in str(refused.value)
    with pytest.raises(DeliveryRefused):
        validate_plan({**good, "extra": 1})
    with pytest.raises(DeliveryRefused):
        validate_plan({**good, "target_descriptor": {"revision": REVISION, "worker_image": IMAGE}})


def test_registry_is_host_configuration_and_a_plan_can_only_name_a_registered_target(tmp_path):
    document = targets_document(tmp_path)
    assert validate_targets(document)["targets"][0]["service"] == "zeus-canary-service"
    with pytest.raises(DeliveryRefused):
        validate_targets({**document, "targets": document["targets"] * 2})
    with pytest.raises(DeliveryRefused):
        validate_targets({**document, "targets": [{**document["targets"][0], "kind": "docker"}]})
    store, org = SerialStore(), organization()
    release = reviewed_release(store, org)
    delivery = HostDelivery(store, org)
    with pytest.raises(DeliveryRefused) as refused:
        delivery.register(plan_document(release, target_id="unregistered-target"), pin())
    assert refused.value.reason_code == "target_unregistered"
    with store.transaction() as tx:
        assert tx.scan(BUCKET_PLANS) == []


def test_registration_is_idempotent_and_refuses_editing_an_in_flight_delivery(tmp_path):
    system = build(tmp_path, register_plan=False)
    first = system["delivery"].register(system["plan"], pin())
    again = system["delivery"].register(system["plan"], pin())
    assert first["cached"] is False and again["cached"] is True
    assert again["plan_sha256"] == first["plan_sha256"]
    system["delivery"].tick()  # leaves `registered` behind: the delivery is now in flight
    assert intent_of(system)["stage"] != REGISTERED
    moved = {**system["plan"], "target_descriptor": {**system["plan"]["target_descriptor"],
                                                     "profile_digest": "0" * 64}}
    with pytest.raises(DeliveryRefused) as refused:
        system["delivery"].register(moved, pin())
    assert refused.value.reason_code == "delivery_in_flight"
    with system["store"].transaction() as tx:
        assert tx.get(BUCKET_PLANS, system["plan"]["plan_id"])["plan"] == system["plan"]


# ----- the existing release authority -------------------------------------------------------------
def test_registration_before_review_projects_awaiting_review_and_touches_nothing(tmp_path):
    system = build(tmp_path, lead=False, conductor=False)
    result = system["delivery"].tick()
    assert result["outcome"] == "pending" and result["stage"] == AWAITING_REVIEW
    assert result["reason_code"] == "release_reviews_incomplete"
    assert system["github"].publishes == 0 and system["github"].merges == 0
    with system["store"].transaction() as tx:
        assert tx.scan("release_queue") == []  # not even a queue row before the review exists
        assert tx.get("deployment_locks", "controller") is None
    assert system["delivery"].status()["deliveries"][0]["stage"] == AWAITING_REVIEW


@pytest.mark.parametrize("field,value,reason", [
    ("revision", "1" * 40, "release_revision_mismatch"),
    ("tree", "2" * 64, "release_tree_mismatch"),
    ("policy_hash", "3" * 64, "release_policy_mismatch"),
    ("repository", "github:other-owner/other-repo", "release_repository_mismatch")])
def test_a_plan_that_names_another_candidate_or_evaluator_is_refused_without_side_effects(
        tmp_path, field, value, reason):
    system = build(tmp_path, plan_overrides={field: value})
    result = system["delivery"].tick()
    assert result["outcome"] == "refused" and result["reason_code"] == reason
    assert system["github"].publishes == 0 and system["github"].observations == 0
    assert intent_of(system)["stage"] == BLOCKED


def test_only_the_conductor_review_of_the_authors_own_lead_opens_the_delivery(tmp_path):
    system = build(tmp_path, conductor=False)
    assert system["delivery"].tick()["stage"] == AWAITING_REVIEW
    Releases(system["store"], system["org"]).review(
        system["release"]["id"], "conductor", REVISION, True, "fixture-conductor-review-evidence")
    Releases(system["store"], system["org"]).verify(
        system["release"]["id"], REVISION, system["release"]["policy_hash"],
        {"tests": {"passed": True, "evidence": "fixture-incumbent-check-receipt"}})
    assert system["delivery"].tick()["stage"] == PUBLISHING


def test_an_unverified_release_stops_before_the_host_is_touched(tmp_path):
    system = build(tmp_path, verified=False)
    results = drive(system, until=MERGED, limit=8)
    assert stages(results)[-1] == MERGED
    blocked = system["delivery"].tick()
    assert blocked["outcome"] == "blocked" and blocked["reason_code"] == "release_not_verified"
    assert descriptor_of(system) is None
    assert not (tmp_path / "state-canary-service" / DESCRIPTOR_FILE).exists()


# ----- the normal path ------------------------------------------------------------------------------
def test_normal_path_publishes_observes_ci_merges_switches_and_proves_consumption(tmp_path):
    system = build(tmp_path)
    try:
        results = drive(system)
        assert results[-1]["stage"] == ACTIVE, stages(results)
        # The exact stage path, with the bounded `awaiting_consumption` polls collapsed: waiting for
        # a real process to report is a repeat of one stage, never a stage of its own.
        assert visited(results) == [PUBLISHING, AWAITING_CI, MERGE_INTENDED, MERGED,
                                    DRAIN_INTENDED, SWITCHING, AWAITING_CONSUMPTION, ACTIVE]
        assert system["github"].publishes == 1 and system["github"].merges == 1
        intent = intent_of(system)
        assert intent["head"] == REVISION and intent["merged_revision"] == MERGED_REVISION
        # The descriptor file on the host is the one the intent bound, and the process that started
        # reported exactly that digest back.
        written = json.loads((tmp_path / "state-canary-service" / DESCRIPTOR_FILE).read_text("utf-8"))
        assert descriptor_digest(written) == intent["descriptor_sha256"]
        receipt = json.loads((tmp_path / "state-canary-service" / RECEIPT_FILE).read_text("utf-8"))
        assert receipt["descriptor_sha256"] == intent["descriptor_sha256"]
        assert receipt["revision"] == REVISION and receipt["worker_image"] == IMAGE
        assert receipt["instance_id"] == intent["instance_id"]
        assert os.path.isdir(receipt["module_root"])
        row = descriptor_of(system)
        assert row["consumed"] is True and row["instance_id"] == receipt["instance_id"]
        # The active release moved only through the existing Releases authority.
        with system["store"].transaction() as tx:
            assert tx.get("deployment", "active")["release_id"] == system["release"]["id"]
            assert tx.get("releases", system["release"]["id"])["status"] == "active"
        assert system["delivery"].tick()["outcome"] == "idle"
    finally:
        stop_target(system)


def test_the_status_projection_carries_identities_and_digests_but_no_bodies(tmp_path):
    system = build(tmp_path)
    try:
        drive(system)
        projection = system["delivery"].status()
        text = json.dumps(projection)
        assert CANARY_TEXT not in text and str(tmp_path) not in text
        assert "zeus-canary-service" not in text  # the service name is host configuration
        view = projection["deliveries"][0]
        assert view["stage"] == ACTIVE and view["consumed"] is True
        assert view["active_descriptor_sha256"] == intent_of(system)["descriptor_sha256"]
        assert projection["targets"][0]["target_id"] == "canary-service"
        assert projection["counts"] == {ACTIVE: 1}
        missing = system["delivery"].status("no-such-plan")
        assert missing["registered"] is False and missing["outcome"] == "plan_unregistered"
    finally:
        stop_target(system)


# ----- CI observation ---------------------------------------------------------------------------------
@pytest.mark.parametrize("rows,state,reason", [
    ([(CHECK, "success")], "passed", None),
    ([], "pending", "ci_check_missing"),
    ([(CHECK, "pending")], "pending", "ci_check_pending"),
    ([(CHECK, "failure")], "failed", "ci_check_failed"),
    ([("other", "success")], "pending", "ci_check_missing")])
def test_ci_verdict_counts_only_a_finished_success_for_the_required_check(rows, state, reason):
    verdict = ci_verdict([CHECK], [{"name": n, "state": s} for n, s in rows], REVISION,
                         observed_head=REVISION)
    assert verdict["state"] == state and verdict["reason_code"] == reason


def test_ci_head_change_goes_to_requalification_rather_than_a_silent_rebase(tmp_path):
    system = build(tmp_path)
    drive(system, until=AWAITING_CI, limit=3)
    system["github"].head = "7" * 40  # the PR head moved after the reviewed acceptance
    system["github"].pr = {**system["github"].pr, "head": "7" * 40}
    result = system["delivery"].tick()
    assert result["outcome"] == "blocked" and result["reason_code"] == "ci_head_changed"
    assert system["github"].merges == 0


def test_skipped_and_cancelled_conclusions_are_never_a_pass():
    rows = [{"name": CHECK, "status": "COMPLETED", "conclusion": conclusion}
            for conclusion in ("SKIPPED", "CANCELLED", "NEUTRAL", "FAILURE")]
    assert all(row["state"] == "failure" for row in normalize_checks(rows))
    assert normalize_checks([{"name": CHECK, "status": "IN_PROGRESS", "conclusion": None}]) == [
        {"name": CHECK, "state": "pending"}]
    assert normalize_checks([{"context": CHECK, "state": "SUCCESS"}]) == [
        {"name": CHECK, "state": "success"}]


def test_pending_ci_releases_the_lease_and_the_stage_deadline_ends_the_wait(tmp_path):
    system = build(tmp_path, github=FakeGitHub(checks=((CHECK, "pending"),)))
    drive(system, until=AWAITING_CI, limit=3)
    result = system["delivery"].tick()
    assert result["outcome"] == "pending" and result["reason_code"] == "ci_check_pending"
    with system["store"].transaction() as tx:
        # A 20 minute CI run is never waited out while holding the controller lease.
        assert (tx.get("deployment_locks", "controller") or {}).get("lease_until") is None
        assert tx.get("release_queue", system["release"]["id"])["attempt"] == 0
    assert system["delivery"].tick()["outcome"] == "pending"  # still bounded, still waiting
    system["clock"].advance(600)  # past `ci_timeout_seconds`
    timed_out = system["delivery"].tick()
    assert timed_out["outcome"] == "blocked" and timed_out["reason_code"] == "ci_timeout"
    assert system["github"].merges == 0


# ----- lost responses, restart and competing controllers -----------------------------------------------
def test_a_lost_publish_response_is_reconciled_once_and_never_published_twice(tmp_path):
    system = build(tmp_path)
    system["github"].publish_error = TimeoutError("injected: publish response lost")
    system["delivery"].tick()  # registered -> publishing
    lost = system["delivery"].tick()
    assert lost["outcome"] == "unavailable" and lost["error_type"] == "TimeoutError"
    assert system["github"].publishes == 1
    system["github"].publish_error = None
    system["clock"].advance(120)  # past the existing queue backoff
    recovered = system["delivery"].tick()
    assert recovered["stage"] == AWAITING_CI and system["github"].publishes == 1
    assert intent_of(system)["pr_number"] == 181


def test_a_lost_merge_response_is_recognized_instead_of_merged_again(tmp_path):
    system = build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    system["github"].merge_error = TimeoutError("injected: merge response lost")
    lost = system["delivery"].tick()
    assert lost["outcome"] == "unavailable" and system["github"].merges == 1
    system["github"].merge_error = None
    system["clock"].advance(120)
    recovered = system["delivery"].tick()
    assert recovered["stage"] == MERGED and system["github"].merges == 1
    assert intent_of(system)["merged_revision"] == MERGED_REVISION


def test_a_restarted_controller_resumes_the_same_intent_without_repeating_its_effects(tmp_path):
    system = build(tmp_path)
    try:
        drive(system, until=AWAITING_CONSUMPTION, limit=8)
        state = json.loads((tmp_path / "state-canary-service" / STATE_FILE).read_text("utf-8"))
        # A second controller process over the SAME durable state, as a restart would be.
        successor = HostDelivery(system["store"], system["org"], github=system["github"],
                                 hosts={"process": system["host"]},
                                 canaries={CANARY_STARTUP: startup_identity_canary},
                                 clock=system["clock"], enabled=True, resume_seconds=0)
        for _ in range(20):
            result = successor.tick()
            if result["stage"] == ACTIVE:
                break
            time.sleep(0.05)
        assert result["stage"] == ACTIVE
        after = json.loads((tmp_path / "state-canary-service" / STATE_FILE).read_text("utf-8"))
        assert after["pid"] == state["pid"]  # the running instance was reconciled, not restarted
        assert system["github"].publishes == 1 and system["github"].merges == 1
    finally:
        stop_target(system)


def test_a_second_controller_cannot_act_while_the_lease_is_held(tmp_path):
    system = build(tmp_path)
    system["delivery"].tick()
    queue = ReleaseQueue(system["store"])
    held = queue.claim()
    assert held is not None and held["id"] == system["release"]["id"]
    busy = system["delivery"].tick()
    assert busy["outcome"] == "controller_busy" and busy["reason_code"] == "controller_lease_held"
    assert system["github"].publishes == 0
    assert intent_of(system)["stage"] == PUBLISHING  # the stage it was left at, unchanged
    queue.finish(held, {"status": "blocked", "reason": "fixture owner stop"})
    stopped = system["delivery"].tick()
    # A queue row that is no longer runnable is its own fact, not a lease that is held.
    assert stopped["outcome"] == "controller_busy"
    assert stopped["reason_code"] == "release_queue_blocked"


def test_a_stale_claim_cannot_commit_an_observation(tmp_path):
    system = build(tmp_path)
    queue = ReleaseQueue(system["store"])
    queue.enqueue(system["release"]["id"], "fixture")
    stale = queue.claim()
    queue.finish(stale, {"status": "retry", "reason": "fixture"})
    queue.claim()  # a newer generation owns the row now
    with pytest.raises(ContractError):
        with system["store"].transaction() as tx:
            queue.owned(tx, stale)


def test_the_controller_claims_only_the_rows_a_registered_plan_names(tmp_path):
    system = build(tmp_path)
    other = reviewed_release(system["store"], system["org"],
                             record_candidate={**candidate(), "revision": "5" * 40,
                                               "branch": "harness/other", "task_id": "other"})
    ReleaseQueue(system["store"]).enqueue(other["id"], "another controller's work")
    result = system["delivery"].tick()
    assert result["release_id"] == system["release"]["id"] and result["stage"] == PUBLISHING
    with system["store"].transaction() as tx:
        foreign = tx.get("release_queue", other["id"])
    assert foreign["status"] == "queued" and foreign["attempt"] == 0  # untouched, unspent


# ----- the host boundary ------------------------------------------------------------------------------
def test_the_descriptor_switch_compares_its_predecessor_under_a_target_lock(tmp_path):
    host = ProcessHostTarget()
    target = targets_document(tmp_path)["targets"][0]
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": target["root"], "revision": REVISION, "worker_image": IMAGE,
                  "profile_digest": PROFILE, "predecessor": None}
    host.switch(target, descriptor, expected=None)
    assert host.current(target) == descriptor
    with pytest.raises(DeliveryRefused) as refused:
        host.switch(target, {**descriptor, "revision": "8" * 40}, expected=None)
    assert refused.value.reason_code == "descriptor_changed"
    successor = {**descriptor, "revision": "8" * 40, "predecessor": descriptor_digest(descriptor)}
    host.switch(target, successor, expected=descriptor_digest(descriptor))
    assert host.current(target)["revision"] == "8" * 40
    (host.path(target, "switch.lock")).mkdir()
    try:
        host.lock_timeout = 0.2
        with pytest.raises(DeliveryRefused) as held:
            host.switch(target, descriptor, expected=descriptor_digest(successor))
        assert held.value.reason_code == "target_lock_held"
    finally:
        host.path(target, "switch.lock").rmdir()


def test_unconfirmed_host_effects_block_the_switch_and_do_not_kill_active_work(tmp_path):
    system = build(tmp_path)
    drive(system, until=DRAIN_INTENDED, limit=6)
    state = tmp_path / "state-canary-service"
    state.mkdir(parents=True, exist_ok=True)
    # A labelled injected host state: the service reports work whose effect is not confirmed.
    (state / WORK_FILE).write_text(json.dumps({"active": 1, "unconfirmed": 1}), encoding="utf-8")
    (state / STATE_FILE).write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    waiting = system["delivery"].tick()
    assert waiting["outcome"] == "pending" and waiting["reason_code"] == "drain_unconfirmed_effects"
    assert not (state / DESCRIPTOR_FILE).exists()
    system["clock"].advance(600)
    blocked = system["delivery"].tick()
    assert blocked["outcome"] == "blocked" and blocked["reason_code"] == "drain_unconfirmed_effects"
    assert not (state / DESCRIPTOR_FILE).exists()


def test_a_descriptor_that_moved_under_the_plan_refuses_before_any_host_change(tmp_path):
    system = build(tmp_path, plan_overrides={"expected": "4" * 64})
    results = drive(system, until=MERGED, limit=6)
    assert stages(results)[-1] == MERGED
    blocked = system["delivery"].tick()
    assert blocked["reason_code"] == "descriptor_predecessor_mismatch"
    assert descriptor_of(system) is None


def test_an_unchanged_binding_without_a_predecessor_refuses_instead_of_guessing(tmp_path):
    system = build(tmp_path, plan_overrides={"image": "unchanged"})
    results = drive(system, until=MERGED, limit=6)
    assert stages(results)[-1] == MERGED
    refused = system["delivery"].tick()
    assert refused["outcome"] == "refused"
    assert refused["reason_code"] == "unchanged_without_predecessor"
    assert descriptor_of(system) is None


def test_a_lost_switch_response_writes_no_second_descriptor_and_starts_no_second_process(tmp_path):
    system = build(tmp_path)
    try:
        drive(system, until=SWITCHING, limit=7)
        host, target = system["host"], system["target"]
        intent = intent_of(system)
        # Exactly what a tick that lost its response after switching AND starting would leave: the
        # host moved, the durable intent still says `switching`.
        host.switch(target, intent["descriptor"], expected=None)
        host.start(target, intent["descriptor"])
        for _ in range(100):
            if (tmp_path / "state-canary-service" / RECEIPT_FILE).exists():
                break
            time.sleep(0.05)
        first = json.loads((tmp_path / "state-canary-service" / RECEIPT_FILE).read_text("utf-8"))
        result = system["delivery"].tick()
        assert result["stage"] == AWAITING_CONSUMPTION
        assert intent_of(system)["switch"]["recovered"] is True
        after = json.loads((tmp_path / "state-canary-service" / RECEIPT_FILE).read_text("utf-8"))
        assert after["instance_id"] == first["instance_id"]  # the same instance, not a second one
        assert drive(system, until=ACTIVE, limit=20)[-1]["stage"] == ACTIVE
        assert descriptor_of(system)["instance_id"] == first["instance_id"]
    finally:
        stop_target(system)


def test_an_unavailable_store_is_reported_as_an_outage_and_never_as_progress(tmp_path):
    system = build(tmp_path)
    system["delivery"].tick()

    class BrokenStore:
        """Injected store outage: the delivery's own reads and the fence both fail."""

        def __init__(self, inner):
            self.inner = inner
            self.failing = False

        @contextmanager
        def transaction(self):
            if self.failing:
                raise ConnectionError("injected: store unavailable")
            with self.inner.transaction() as tx:
                yield tx

    broken = BrokenStore(system["store"])
    outage = HostDelivery(broken, system["org"], github=system["github"],
                          hosts={"process": system["host"]}, clock=system["clock"],
                          enabled=True, queue=ReleaseQueue(broken))
    broken.failing = True
    result = outage.tick()
    # The durable state cannot be read at all: an explicit outage, never an idle or empty success.
    assert result["outcome"] == "unavailable" and result["reason_code"] == "store_unavailable"
    assert result["error_type"] == "ConnectionError" and result["stage"] is None
    broken.failing = False
    assert outage.status()["deliveries"][0]["stage"] == PUBLISHING


def test_the_launched_service_reports_the_identity_it_actually_loaded(tmp_path):
    state = tmp_path / "state-canary-service"
    state.mkdir(parents=True)
    assert serve(str(state), 1) == 2  # no descriptor to load: no receipt is written at all
    assert not (state / RECEIPT_FILE).exists()
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": str(tmp_path / "root"), "revision": REVISION, "worker_image": IMAGE,
                  "profile_digest": PROFILE, "predecessor": None}
    (state / DESCRIPTOR_FILE).write_text(json.dumps(descriptor), encoding="utf-8")
    (state / "stop.json").write_text(json.dumps({"stop": True}), encoding="utf-8")
    assert serve(str(state), 5) == 0
    receipt = json.loads((state / RECEIPT_FILE).read_text("utf-8"))
    assert receipt["descriptor_sha256"] == descriptor_digest(descriptor)
    assert receipt["pid"] == os.getpid() and receipt["revision"] == REVISION


@pytest.mark.parametrize("mutation,reason", [
    ({"revision": "6" * 40}, "receipt_revision_mismatch"),
    ({"worker_image": "zeus-worker@sha256:" + "f" * 64}, "receipt_worker_image_mismatch"),
    ({"profile_digest": "7" * 64}, "receipt_profile_digest_mismatch"),
    ({"descriptor_sha256": "8" * 64}, "receipt_descriptor_sha256_mismatch"),
    ({"instance_id": "not-hex"}, "receipt_invalid")])
def test_a_wrong_startup_receipt_never_grants_activation(mutation, reason):
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": "/opt/zeus", "revision": REVISION, "worker_image": IMAGE,
                  "profile_digest": PROFILE, "predecessor": None}
    receipt = {"schema": "urn:zeus:host-startup-receipt:1", "target_id": "canary-service",
               "instance_id": "1" * 32, "pid": 4242, "started_at": START,
               "module_root": "/opt/zeus/src/codex_harness",
               "descriptor_sha256": descriptor_digest(descriptor), "revision": REVISION,
               "worker_image": IMAGE, "profile_digest": PROFILE}
    assert consumption_verdict(descriptor, receipt)["consumed"] is True
    assert consumption_verdict(descriptor, None)["reason_code"] == "receipt_missing"
    verdict = consumption_verdict(descriptor, {**receipt, **mutation})
    assert verdict["consumed"] is False and verdict["reason_code"] == reason
    stale = consumption_verdict(descriptor, receipt, expected_instance="1" * 32)
    assert stale["consumed"] is False and stale["reason_code"] == "receipt_stale_instance"


# ----- canary and rollback ------------------------------------------------------------------------------
def test_a_failed_canary_restores_the_exact_predecessor_and_proves_it_was_consumed(tmp_path):
    verdicts = {"passed": True}

    def canary(target, descriptor):
        # Labelled injected canary verdict: the first delivery passes, the successor fails.
        return {"passed": verdicts["passed"], "reason_code": None if verdicts["passed"]
                else "canary_fixture_failed"}

    system = build(tmp_path, canaries={CANARY_STARTUP: canary})
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        verdicts["passed"] = False
        successor = reviewed_release(system["store"], system["org"],
                                     record_candidate={**candidate(), "revision": "5" * 40,
                                                       "branch": "harness/two", "task_id": "two"})
        plan = plan_document(successor, plan_id="delivery-plan-2",
                             expected=good["descriptor_sha256"], descriptor_revision="5" * 40)
        system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
        system["plan"] = plan
        results = drive(system, until=ROLLED_BACK, limit=40)
        assert results[-1]["stage"] == ROLLED_BACK, "\n".join(
            str((r["stage"], r["outcome"], r["reason_code"])) for r in results)
        rolled = descriptor_of(system)
        assert rolled["descriptor_sha256"] == good["descriptor_sha256"]
        assert rolled["consumed"] is True and rolled["rolled_back"] is True
        # The predecessor was restored as a whole tuple and the running process proves it.
        written = json.loads((tmp_path / "state-canary-service" / DESCRIPTOR_FILE).read_text("utf-8"))
        assert descriptor_digest(written) == good["descriptor_sha256"]
        receipt = json.loads((tmp_path / "state-canary-service" / RECEIPT_FILE).read_text("utf-8"))
        assert receipt["descriptor_sha256"] == good["descriptor_sha256"]
        assert receipt["instance_id"] == rolled["instance_id"]
        intent = intent_of(system)
        assert intent["rollback"]["restored"] is True and intent["rollback"]["verified"] is True
        with system["store"].transaction() as tx:
            # The failed candidate never became the active release.
            assert tx.get("deployment", "active")["release_id"] == system["release"]["id"]
    finally:
        stop_target(system)


def test_a_rollback_that_cannot_be_proven_blocks_and_alerts_instead_of_claiming_success(tmp_path):
    class BrokenHost(ProcessHostTarget):
        """The predecessor is restored on disk but its process never reports: an injected fault."""

        def start(self, target, descriptor):
            self.stop(target)
            return {"started": True, "pid": None}

    system = build(tmp_path, canaries={CANARY_STARTUP: lambda target, descriptor: {
        "passed": False, "reason_code": "canary_fixture_failed"}},
        plan_overrides={"consumption_timeout": 10})
    system["delivery"].hosts["process"] = BrokenHost(max_seconds=30)
    try:
        # A first activation with no predecessor cannot roll back at all, and says so.
        results = drive(system, until=ACTIVE, limit=30)
        assert results[-1]["outcome"] == "blocked"
        assert results[-1]["reason_code"] == "no_known_good_predecessor"
        assert intent_of(system)["rollback"]["restored"] is False
        with system["store"].transaction() as tx:
            assert tx.get("deployment", "active") is None
    finally:
        stop_target(system)


def test_an_unproven_restoration_blocks_with_a_critical_alert(tmp_path):
    """A rollback is requested, the descriptor is restored, and its runtime never reports."""
    store = SerialStore()
    observer = observer_for(store)
    verdicts = {"passed": True}
    system = build(tmp_path, store=store, observer=observer,
                   canaries={CANARY_STARTUP: lambda target, descriptor: {
                       "passed": verdicts["passed"], "reason_code": None if verdicts["passed"]
                       else "canary_fixture_failed"}})
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        verdicts["passed"] = False

        class BrokenHost(ProcessHostTarget):
            """Injected fault: the restored descriptor's service is never actually started."""

            def start(self, target, descriptor):
                self.stop(target)
                return {"started": True, "pid": None}

        successor = reviewed_release(system["store"], system["org"],
                                     record_candidate={**candidate(), "revision": "5" * 40,
                                                       "branch": "harness/two", "task_id": "two"})
        system["delivery"].register(plan_document(successor, plan_id="delivery-plan-2",
                                                  expected=good["descriptor_sha256"],
                                                  descriptor_revision="5" * 40,
                                                  consumption_timeout=10),
                                    pin(path="docs/zeus/operations/delivery-2.json"))
        system["plan"] = plan_document(successor, plan_id="delivery-plan-2")
        drive(system, until=ROLLING_BACK, limit=20)
        system["delivery"].hosts["process"] = BrokenHost(max_seconds=30)
        results = drive(system, until=ROLLED_BACK, limit=30)
        assert results[-1]["outcome"] == "blocked"
        assert results[-1]["reason_code"] == "rollback_unverified"
        intent = intent_of(system)
        assert intent["rollback"]["restored"] is True and intent["rollback"]["verified"] is False
        alerts = [record for record in observer.spool.records()
                  if record["event_type"] == "operations.delivery_rollback"]
        assert alerts[-1]["severity"] == "critical"
        assert alerts[-1]["attributes"]["verified"] is False
        # The durable record still shows an unconsumed descriptor; nothing claims a restoration.
        assert descriptor_of(system)["consumed"] is False
    finally:
        stop_target(system)


def test_an_owner_qualified_canary_needs_the_owners_own_receipt(tmp_path):
    target = targets_document(tmp_path)["targets"][0]
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": target["root"], "revision": REVISION, "worker_image": IMAGE,
                  "profile_digest": PROFILE, "predecessor": None}
    assert owner_qualified_canary(target, descriptor)["reason_code"] == "canary_owner_receipt_missing"
    state = tmp_path / "state-canary-service"
    state.mkdir(parents=True, exist_ok=True)
    (state / "owner-canary-receipt.json").write_text(
        json.dumps({"descriptor_sha256": "0" * 64, "passed": True}), encoding="utf-8")
    assert owner_qualified_canary(target, descriptor)["reason_code"] == "canary_owner_receipt_stale"
    (state / "owner-canary-receipt.json").write_text(
        json.dumps({"descriptor_sha256": descriptor_digest(descriptor), "passed": True,
                    "evidence": "sha256:" + "a" * 64}), encoding="utf-8")
    assert owner_qualified_canary(target, descriptor)["passed"] is True


# ----- outages, concurrency and the store boundary --------------------------------------------------------
def test_an_unavailable_github_is_explicit_and_unrelated_targets_keep_moving(tmp_path):
    system = build(tmp_path)
    system["github"].observe_error = ConnectionError("injected: GitHub unreachable")
    system["delivery"].tick()
    outage = system["delivery"].tick()
    assert outage["outcome"] == "unavailable" and outage["error_type"] == "ConnectionError"
    assert outage["reason_code"] == "stage_unavailable"
    assert intent_of(system)["stage"] == PUBLISHING  # the stage and its evidence are preserved
    assert system["delivery"].status()["deliveries"][0]["error_type"] == "ConnectionError"


def test_a_missing_host_or_canary_port_is_unavailable_not_an_empty_success(tmp_path):
    system = build(tmp_path, canaries={})
    system["delivery"].hosts = {}
    results = drive(system, until=DRAIN_INTENDED, limit=8)
    assert stages(results)[-1] == DRAIN_INTENDED
    blocked = system["delivery"].tick()
    assert blocked["outcome"] == "refused" and blocked["reason_code"] == "host_port_unavailable"
    assert descriptor_of(system) is None


def test_two_plans_on_one_target_serialize_and_an_unrelated_plan_is_not_starved(tmp_path):
    system = build(tmp_path)
    try:
        drive(system, until=AWAITING_CONSUMPTION, limit=8)
        second = reviewed_release(system["store"], system["org"],
                                  record_candidate={**candidate(), "revision": "5" * 40,
                                                    "branch": "harness/two", "task_id": "two"})
        system["delivery"].register(plan_document(second, plan_id="delivery-plan-2",
                                                  descriptor_revision="5" * 40),
                                    pin(path="docs/zeus/operations/delivery-2.json"))
        result = system["delivery"].tick()
        # The in-flight delivery keeps the target; the newcomer is recorded as waiting, not failed.
        assert result["plan_id"] == "delivery-plan-1"
        assert system["delivery"].status()["deliveries"][1]["stage"] == REGISTERED
    finally:
        stop_target(system)


def test_no_tick_opens_a_nested_transaction_and_an_idle_poll_writes_nothing(tmp_path):
    system = build(tmp_path)
    try:
        drive(system)  # SerialStore raises on any nested transaction anywhere in the path
        before = repr(sorted((str(key), repr(value)) for key, value in system["store"].data.items()))
        idle = system["delivery"].tick()
        assert idle["outcome"] == "idle"
        after = repr(sorted((str(key), repr(value)) for key, value in system["store"].data.items()))
        assert after == before
    finally:
        stop_target(system)


def test_delivery_is_disabled_by_default_and_writes_no_intent(tmp_path):
    system = build(tmp_path, enabled=False)
    result = system["delivery"].tick()
    assert result["outcome"] == "disabled" and result["reason_code"] == "delivery_disabled"
    assert intent_of(system) is None and system["github"].observations == 0
    with system["store"].transaction() as tx:
        assert tx.scan("release_queue") == []


# ----- structured observation ---------------------------------------------------------------------------------
def test_transitions_are_structured_observations_with_identities_and_codes_only(tmp_path):
    store = SerialStore()
    observer = observer_for(store)
    system = build(tmp_path, store=store, observer=observer)
    try:
        drive(system)
        records = observer.spool.records()
        types = [event["event_type"] for event in records]
        assert "general.delivery_stage_entered" in types
        assert "development.delivery_check_observed" in types
        assert "operations.delivery_switched" in types
        body = json.dumps(records)
        assert CANARY_TEXT not in body and str(tmp_path) not in body
        assert "zeus-canary-service" not in body
        switched = [e for e in records if e["event_type"] == "operations.delivery_switched"]
        assert switched[-1]["attributes"]["consumed"] is True
        assert switched[-1]["attributes"]["descriptor_sha256"] == intent_of(system)["descriptor_sha256"]
        before = len(observer.spool.records())
        system["delivery"].tick()
        system["delivery"].tick()
        assert len(observer.spool.records()) == before  # repeated idle polls emit nothing
    finally:
        stop_target(system)


def test_a_blocked_delivery_emits_one_operations_alert_with_its_stage(tmp_path):
    store = SerialStore()
    observer = observer_for(store)
    system = build(tmp_path, store=store, observer=observer,
                   github=FakeGitHub(checks=((CHECK, "failure"),)))
    drive(system, until=AWAITING_CI, limit=4)
    system["delivery"].tick()
    blocked = [record for record in observer.spool.records()
               if record["event_type"] == "operations.delivery_blocked"]
    assert len(blocked) == 1 and blocked[0]["severity"] == "error"
    assert blocked[0]["attributes"]["stage"] == AWAITING_CI
    assert blocked[0]["reason_code"] == "ci_check_failed"


# ----- isolated PostgreSQL --------------------------------------------------------------------------------------
@pytest.mark.integration
def test_transaction_boundaries_hold_on_an_isolated_postgresql(isolated_pgstore, tmp_path):
    """The real advisory-lock boundary, against a disposable schema. Skips honestly without it."""
    org = organization()
    system = build(tmp_path, store=isolated_pgstore, org=org, target_id="pg-target")
    try:
        results = drive(system)
        assert results[-1]["stage"] == ACTIVE, stages(results)
        with isolated_pgstore.transaction() as tx:
            assert tx.get(BUCKET_DESCRIPTORS, "pg-target")["consumed"] is True
            assert tx.get("deployment", "active")["release_id"] == system["release"]["id"]
    finally:
        stop_target(system)
