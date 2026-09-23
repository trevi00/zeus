"""Durable host delivery: plan policy, the release fence, real host targets, canary and rollback
(INV-HOST-DELIVERY-001).

The GitHub port here is a labelled in-test double: no `gh`, no network, no GitHub mutation, no
scheduled-task mutation, no provider and no model call happens anywhere in this module, and every
injected outage is labelled where it is injected. The HOST side is real - an actual temporary state
directory, an actual descriptor file replaced atomically, an actual detached child process started
from THIS CHECKOUT as its registered runtime root, and the actual startup receipt that child writes
about the code it really imported. Nothing is ever written into that root: the runtime facts are
read from it (its own `HEAD`, its packaged profile, its effective worker image), and every mutable
file of a target lives under a temporary state directory. The one integration-gated test at the end
skips honestly without `HARNESS_INTEGRATION=1`.

The store is `SerialStore`: a MemoryStore that REFUSES a transaction opened while another one is
already open. The real `PostgresStore.transaction` connects and takes `pg_advisory_xact_lock` per
transaction, so a nested call would block until `lock_timeout`; this fixture turns that latent
deadlock into an immediate failure for every path below, including the `Releases` and
`ReleaseQueue` calls, which open their own transactions.
"""
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from codex_harness.adapters.configuration import aliases, read_env
from codex_harness.adapters.host_delivery import (
    CANARY_RECEIPT_FILE,
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    WORK_FILE,
    ProcessHostTarget,
    ScheduledTaskHostTarget,
    collect_monitor_canary,
    effective_profile_digest,
    effective_worker_image,
    loaded_runtime,
    normalize_checks,
    owner_qualified_canary,
    runtime_revision,
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
    CANARY_COLLECT,
    CANARY_FLEET,
    CANARY_STARTUP,
    DRAIN_INTENDED,
    EVENT_SWITCHED,
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
    LifecycleInterrupted,
    ci_verdict,
    consumption_verdict,
    descriptor_digest,
    validate_plan,
    validate_targets,
)
from codex_harness.domain.model import ContractError
from codex_harness.domain.observation import new_process_run_id
from codex_harness.domain.policy import POLICY

CANARY_TEXT = "CANARY-must-never-be-emitted"
REVISION = "a" * 40
BASE = "b" * 40
TREE = "c" * 64
MERGED_REVISION = "9" * 40

# The runtime a delivery activates here is THIS checkout: its own root, the revision it is really
# at, the worker image its configuration really names and the digest of the profile it really
# packages. None of these is invented by a fixture, and none of them is taken from a descriptor -
# which is exactly why the tests below can tell an actually delivered runtime from an echo.
RUNTIME_ROOT = loaded_runtime()["runtime_root"]
RUNTIME_REVISION = runtime_revision(RUNTIME_ROOT)
IMAGE = effective_worker_image()
PROFILE = effective_profile_digest()
# A checkout that attests no revision of its own (an exported copy with no Git directory and no
# owner `runtime.json`) cannot bind a real runtime; those tests skip honestly rather than pretend.
DESCRIPTOR_REVISION = RUNTIME_REVISION or REVISION
binds_a_runtime = pytest.mark.skipif(
    RUNTIME_REVISION is None or PROFILE is None,
    reason="this checkout attests no runtime revision or packaged profile digest")
# An identity-only descriptor for the pure policy tests, with no host behind it.
FIXTURE_IMAGE = "zeus-worker@sha256:" + "d" * 64
FIXTURE_PROFILE = "e" * 64
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

    def __init__(self, *, checks=((CHECK, "success"),), head=None, merged_tree=TREE):
        self.rows = [{"name": name, "state": state} for name, state in checks]
        self.head = head  # None: each candidate's own revision, as a real PR head would be
        self.prs = {}
        self.publishes = self.merges = self.observations = 0
        self.publish_error = self.merge_error = self.observe_error = None
        self.merged_tree, self.qualifications = merged_tree, []

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

    def qualify(self, candidate, merged_revision):
        """The merge owner's own merged-tree qualification, recorded rather than executed.

        `merged_tree` is the labelled injected answer: what the merged revision's tree actually is
        on the provider side. It is compared to the REVIEWED tree, exactly as `GitWorkspace` does.
        """
        self.qualifications.append(merged_revision)
        if self.merged_tree != candidate["tree"]:
            raise ContractError("Merged tree differs from reviewed candidate")
        return {"merged_revision": merged_revision, "tree": self.merged_tree}


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


def targets_document(tmp_path, target_id="canary-service", kind="process", root=None):
    """The owner's host configuration: the registered runtime root is this checkout, and every
    mutable file of the target lives in a temporary state directory beside it."""
    return {"schema": REGISTRY_SCHEMA,
            "targets": [{"target_id": target_id, "kind": kind, "root": root or RUNTIME_ROOT,
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
            "target_descriptor": {"revision": descriptor_revision or DESCRIPTOR_REVISION,
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
          verified=True, lead=True, conductor=True, plan_overrides=None, register_plan=True,
          root=None):
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
    registry = targets_document(tmp_path, target_id=target_id, kind=kind, root=root)
    delivery.register_targets(registry)
    plan = plan_document(release, target_id=target_id, **(plan_overrides or {}))
    if register_plan:
        delivery.register(plan, pin())
    return {"store": store, "org": org, "clock": clock, "delivery": delivery, "release": release,
            "plan": plan, "host": host, "github": delivery.github,
            "target": registry["targets"][0]}


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
        validate_plan({**good, "target_descriptor": {"revision": REVISION,
                                                     "worker_image": FIXTURE_IMAGE}})


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
@binds_a_runtime
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
        # The runtime facts are the ones the child OBSERVED about itself, not the ones it was sent.
        assert receipt["revision"] == RUNTIME_REVISION and receipt["worker_image"] == IMAGE
        assert receipt["profile_digest"] == PROFILE
        assert receipt["instance_id"] == intent["instance_id"]
        assert os.path.isdir(receipt["module_root"])
        assert Path(receipt["module_root"]).is_relative_to(Path(receipt["runtime_root"]))
        assert Path(receipt["runtime_root"]) == Path(RUNTIME_ROOT)
        row = descriptor_of(system)
        assert row["consumed"] is True and row["instance_id"] == receipt["instance_id"]
        assert row["startup_observed"] is True
        assert row["observed_instance_id"] == receipt["instance_id"]
        assert system["github"].qualifications == [MERGED_REVISION]
        # The active release moved only through the existing Releases authority.
        with system["store"].transaction() as tx:
            assert tx.get("deployment", "active")["release_id"] == system["release"]["id"]
            assert tx.get("releases", system["release"]["id"])["status"] == "active"
        assert system["delivery"].tick()["outcome"] == "idle"
    finally:
        stop_target(system)


@binds_a_runtime
def test_the_status_projection_carries_identities_and_digests_but_no_bodies(tmp_path):
    system = build(tmp_path)
    try:
        drive(system)
        projection = system["delivery"].status()
        text = json.dumps(projection)
        assert CANARY_TEXT not in text and str(tmp_path) not in text
        assert RUNTIME_ROOT not in text  # the runtime root is host configuration, not a projection
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
    # The RECOVERED merge was qualified against the reviewed tree, exactly like a performed one.
    assert system["github"].qualifications == [MERGED_REVISION]


def test_a_recovered_merge_whose_tree_is_not_the_reviewed_one_stays_blocked(tmp_path):
    """The same qualification on both paths: observing MERGED is not a qualified deployment."""
    system = build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    system["github"].merge_error = TimeoutError("injected: merge response lost")
    system["delivery"].tick()
    system["github"].merge_error = None
    # Labelled injected provider fact: the merged revision does NOT carry the reviewed tree.
    system["github"].merged_tree = "d" * 64
    system["clock"].advance(120)
    blocked = system["delivery"].tick()
    assert blocked["outcome"] == "blocked" and blocked["reason_code"] == "merged_tree_mismatch"
    assert system["github"].merges == 1  # nothing was merged a second time to "fix" it
    assert intent_of(system)["stage"] == BLOCKED
    # And it does not become qualified by being observed again on a later tick.
    system["clock"].advance(600)
    later = system["delivery"].tick()
    assert later["outcome"] == "idle" and descriptor_of(system) is None


def test_a_merge_this_controller_performed_is_qualified_before_the_host_is_touched(tmp_path):
    system = build(tmp_path, github=FakeGitHub(merged_tree="d" * 64))
    results = drive(system, until=MERGED, limit=6)
    assert results[-1]["outcome"] == "blocked"
    assert results[-1]["reason_code"] == "merged_tree_mismatch"
    assert system["github"].qualifications == [MERGED_REVISION]
    assert intent_of(system)["merged_revision"] == MERGED_REVISION  # the evidence is preserved
    assert descriptor_of(system) is None


@binds_a_runtime
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
                  "root": target["root"], "revision": REVISION, "worker_image": FIXTURE_IMAGE,
                  "profile_digest": FIXTURE_PROFILE, "predecessor": None}
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


def test_the_switch_re_checks_the_fence_inside_the_target_lock_and_writes_nothing_when_stale(tmp_path):
    """The mutation boundary: ownership is proven while the lock is held, before the replacement."""
    host = ProcessHostTarget()
    target = targets_document(tmp_path)["targets"][0]
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": target["root"], "revision": REVISION, "worker_image": FIXTURE_IMAGE,
                  "profile_digest": FIXTURE_PROFILE, "predecessor": None}
    observed = []

    def authorize():
        observed.append(host.current(target))  # the lock is held and nothing was written yet
        raise ContractError("Stale release controller")

    with pytest.raises(ContractError):
        host.switch(target, descriptor, expected=None, authorize=authorize)
    assert observed == [None] and host.current(target) is None
    assert not host.path(target, "switch.lock").exists()  # the lock is released either way
    host.switch(target, descriptor, expected=None, authorize=lambda: None)
    assert host.current(target) == descriptor


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


@binds_a_runtime
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
    # A descriptor that REQUESTS another runtime entirely; the receipt still reports this one.
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": str(tmp_path / "root"), "revision": "6" * 40,
                  "worker_image": FIXTURE_IMAGE, "profile_digest": FIXTURE_PROFILE,
                  "predecessor": None}
    (state / DESCRIPTOR_FILE).write_text(json.dumps(descriptor), encoding="utf-8")
    (state / "stop.json").write_text(json.dumps({"stop": True}), encoding="utf-8")
    assert serve(str(state), 5) == 0
    receipt = json.loads((state / RECEIPT_FILE).read_text("utf-8"))
    assert receipt["descriptor_sha256"] == descriptor_digest(descriptor)
    assert receipt["pid"] == os.getpid()
    # Observed, not echoed: this process's own root, package, revision and effective configuration.
    assert receipt["runtime_root"] == RUNTIME_ROOT
    assert receipt["module_root"] == loaded_runtime()["module_root"]
    assert receipt["revision"] == (RUNTIME_REVISION or "")
    assert receipt["worker_image"] == IMAGE and receipt["profile_digest"] == (PROFILE or "")
    assert receipt["revision"] != descriptor["revision"]
    # And exactly that difference refuses the activation the descriptor asked for.
    assert consumption_verdict(descriptor, receipt)["consumed"] is False


def owned_receipt(descriptor, **overrides):
    return {"schema": "urn:zeus:host-startup-receipt:1", "target_id": "canary-service",
            "instance_id": "1" * 32, "pid": 4242, "started_at": START,
            "runtime_root": "/opt/zeus", "module_root": "/opt/zeus/src/codex_harness",
            "descriptor_sha256": descriptor_digest(descriptor), "revision": REVISION,
            "worker_image": FIXTURE_IMAGE, "profile_digest": FIXTURE_PROFILE, **overrides}


@pytest.mark.parametrize("mutation,reason", [
    ({"revision": "6" * 40}, "receipt_revision_mismatch"),
    ({"worker_image": "zeus-worker@sha256:" + "f" * 64}, "receipt_worker_image_mismatch"),
    ({"profile_digest": "7" * 64}, "receipt_profile_digest_mismatch"),
    ({"descriptor_sha256": "8" * 64}, "receipt_descriptor_sha256_mismatch"),
    ({"instance_id": "not-hex"}, "receipt_invalid"),
    # The runtime identity itself: another root, or a package imported from outside that root.
    ({"runtime_root": "/opt/zeus-old"}, "receipt_runtime_root_mismatch"),
    ({"module_root": "/usr/lib/python3/codex_harness"}, "receipt_module_root_foreign"),
    ({"runtime_root": "/opt/zeus-extra"}, "receipt_runtime_root_mismatch")])
def test_a_wrong_startup_receipt_never_grants_activation(mutation, reason):
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": "/opt/zeus", "revision": REVISION, "worker_image": FIXTURE_IMAGE,
                  "profile_digest": FIXTURE_PROFILE, "predecessor": None}
    receipt = owned_receipt(descriptor)
    assert consumption_verdict(descriptor, receipt)["consumed"] is True
    assert consumption_verdict(descriptor, None)["reason_code"] == "receipt_missing"
    verdict = consumption_verdict(descriptor, {**receipt, **mutation})
    assert verdict["consumed"] is False and verdict["reason_code"] == reason
    stale = consumption_verdict(descriptor, receipt, expected_instance="1" * 32)
    assert stale["consumed"] is False and stale["reason_code"] == "receipt_stale_instance"


@binds_a_runtime
def test_an_old_runtime_never_activates_a_new_descriptor_however_alive_its_process_is(tmp_path):
    """The process starts, reports and stays alive - from the runtime that is actually installed.

    The plan asks for another revision, so what the host is running is not what was approved, and
    no pid, no receipt and no successful switch makes that an activation.
    """
    system = build(tmp_path, plan_overrides={"descriptor_revision": "5" * 40,
                                             "consumption_timeout": 10})
    try:
        results = drive(system, until=ACTIVE, limit=30)
        assert results[-1]["stage"] != ACTIVE
        assert results[-1]["reason_code"] == "no_known_good_predecessor"
        # The runtime really did start and really is alive; it is simply not the requested one.
        # The child publishes its own receipt asynchronously, and the delivery may have reached its
        # consumption deadline first, so this waits for that evidence within a bound rather than
        # assuming the file had already landed.
        assert await_receipt(system["target"])["revision"] == RUNTIME_REVISION != "5" * 40
        assert system["host"].running(system["target"]) is True
        row = descriptor_of(system)
        assert row["consumed"] is False and row["startup_observed"] is False
        with system["store"].transaction() as tx:
            assert tx.get("deployment", "active") is None
    finally:
        stop_target(system)


@binds_a_runtime
def test_a_descriptor_that_names_another_image_than_the_runtime_is_not_consumed(tmp_path):
    """Image and profile are EFFECTIVE configuration of the runtime, not a claim in a plan."""
    system = build(tmp_path, plan_overrides={"image": "zeus-worker@sha256:" + "f" * 64,
                                             "consumption_timeout": 10})
    try:
        results = drive(system, until=ACTIVE, limit=30)
        assert results[-1]["stage"] != ACTIVE
        assert descriptor_of(system)["consumed"] is False
    finally:
        stop_target(system)


# ----- canary and rollback ------------------------------------------------------------------------------
@binds_a_runtime
def test_a_failed_canary_restores_the_exact_predecessor_and_proves_it_was_consumed(tmp_path):
    verdicts = {"passed": True}

    def canary(target, descriptor, startup):
        # Labelled injected canary verdict: the first delivery passes, the successor fails.
        assert startup["instance_id"] and startup["runtime_root"] == RUNTIME_ROOT
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
                             expected=good["descriptor_sha256"])
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


@binds_a_runtime
def test_a_rollback_that_cannot_be_proven_blocks_and_alerts_instead_of_claiming_success(tmp_path):
    class BrokenHost(ProcessHostTarget):
        """The predecessor is restored on disk but its process never reports: an injected fault."""

        def start(self, target, descriptor, *, authorize=None, replaces=None):
            self.stop(target)
            return {"started": True, "pid": None}

    system = build(tmp_path, canaries={CANARY_STARTUP: lambda target, descriptor, startup: {
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


@binds_a_runtime
def test_an_unproven_restoration_blocks_with_a_critical_alert(tmp_path):
    """A rollback is requested, the descriptor is restored, and its runtime never reports."""
    store = SerialStore()
    observer = observer_for(store)
    verdicts = {"passed": True}
    system = build(tmp_path, store=store, observer=observer,
                   canaries={CANARY_STARTUP: lambda target, descriptor, startup: {
                       "passed": verdicts["passed"], "reason_code": None if verdicts["passed"]
                       else "canary_fixture_failed"}})
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        verdicts["passed"] = False

        class BrokenHost(ProcessHostTarget):
            """Injected fault: the restored descriptor's service is never actually started."""

            def start(self, target, descriptor, *, authorize=None, replaces=None):
                self.stop(target)
                return {"started": True, "pid": None}

        successor = reviewed_release(system["store"], system["org"],
                                     record_candidate={**candidate(), "revision": "5" * 40,
                                                       "branch": "harness/two", "task_id": "two"})
        system["delivery"].register(plan_document(successor, plan_id="delivery-plan-2",
                                                  expected=good["descriptor_sha256"],
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
                  "root": target["root"], "revision": REVISION, "worker_image": FIXTURE_IMAGE,
                  "profile_digest": FIXTURE_PROFILE, "predecessor": None}
    startup = {"instance_id": "1" * 32, "runtime_root": target["root"]}
    assert owner_qualified_canary(target, descriptor,
                                  startup)["reason_code"] == "canary_owner_receipt_missing"
    state = tmp_path / "state-canary-service"
    state.mkdir(parents=True, exist_ok=True)
    (state / CANARY_RECEIPT_FILE).write_text(
        json.dumps({"descriptor_sha256": "0" * 64, "passed": True}), encoding="utf-8")
    assert owner_qualified_canary(target, descriptor,
                                  startup)["reason_code"] == "canary_owner_receipt_stale"
    (state / CANARY_RECEIPT_FILE).write_text(
        json.dumps({"descriptor_sha256": descriptor_digest(descriptor), "passed": True,
                    "instance_id": "2" * 32, "evidence": "sha256:" + "a" * 64}), encoding="utf-8")
    # The owner qualified ANOTHER instance of this descriptor; that receipt is not this one's.
    assert owner_qualified_canary(target, descriptor,
                                  startup)["reason_code"] == "canary_owner_receipt_stale"
    (state / CANARY_RECEIPT_FILE).write_text(
        json.dumps({"descriptor_sha256": descriptor_digest(descriptor), "passed": True,
                    "instance_id": "1" * 32, "evidence": "sha256:" + "a" * 64}), encoding="utf-8")
    assert owner_qualified_canary(target, descriptor, startup)["passed"] is True


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
        system["delivery"].register(plan_document(second, plan_id="delivery-plan-2"),
                                    pin(path="docs/zeus/operations/delivery-2.json"))
        result = system["delivery"].tick()
        # The in-flight delivery keeps the target; the newcomer is recorded as waiting, not failed.
        assert result["plan_id"] == "delivery-plan-1"
        assert result["blocked"]["delivery-plan-2"] == "target_busy"
        assert system["delivery"].status()["deliveries"][1]["stage"] == REGISTERED
    finally:
        stop_target(system)


def test_a_plan_awaiting_review_does_not_starve_a_qualified_plan_on_another_target(tmp_path):
    """Fair selection: what cannot be acted on does not consume the single selection of a tick."""
    system = build(tmp_path, lead=False, conductor=False)  # plan 1: no reviews at all
    delivery = system["delivery"]
    delivery.register_targets(targets_document(tmp_path, target_id="second-service"))
    ready = reviewed_release(system["store"], system["org"],
                             record_candidate={**candidate(), "revision": "5" * 40,
                                               "branch": "harness/two", "task_id": "two"})
    delivery.register(plan_document(ready, plan_id="delivery-plan-2", target_id="second-service"),
                      pin(path="docs/zeus/operations/delivery-2.json"))
    result = delivery.tick()
    # The reviewed plan moves; the unreviewed one is recorded with its own explicit wait reason.
    assert result["plan_id"] == "delivery-plan-2" and result["stage"] == PUBLISHING
    assert result["blocked"]["delivery-plan-1"] == "release_reviews_incomplete"
    published = delivery.tick()
    assert published["plan_id"] == "delivery-plan-2" and published["stage"] == AWAITING_CI
    assert system["github"].publishes == 1
    # Plan 1 published nothing, took no queue row and did not become an in-flight delivery.
    assert delivery.status("delivery-plan-1")["deliveries"][0]["stage"] == REGISTERED


def test_a_queue_row_in_backoff_or_exhausted_does_not_starve_another_target(tmp_path):
    system = build(tmp_path)
    delivery = system["delivery"]
    delivery.register_targets(targets_document(tmp_path, target_id="second-service"))
    ready = reviewed_release(system["store"], system["org"],
                             record_candidate={**candidate(), "revision": "5" * 40,
                                               "branch": "harness/two", "task_id": "two"})
    delivery.register(plan_document(ready, plan_id="delivery-plan-2", target_id="second-service"),
                      pin(path="docs/zeus/operations/delivery-2.json"))
    queue = ReleaseQueue(system["store"])
    queue.enqueue(system["release"]["id"], "fixture")
    claim = queue.claim()
    # Plan 1's own row is now in its bounded backoff; plan 2 has nothing to do with it.
    queue.finish(claim, {"status": "retry", "reason": "fixture injected retry"})
    result = delivery.tick()
    assert result["plan_id"] == "delivery-plan-2" and result["stage"] == PUBLISHING
    assert result["blocked"]["delivery-plan-1"] == "release_retry_not_due"
    with system["store"].transaction() as tx:
        row = tx.get("release_queue", system["release"]["id"])
        row.update(status="blocked", reason="fixture owner stop")
        tx.put("release_queue", system["release"]["id"], row)
    later = delivery.tick()
    assert later["plan_id"] == "delivery-plan-2"
    assert later["blocked"]["delivery-plan-1"] == "release_queue_blocked"
    with system["store"].transaction() as tx:
        row = tx.get("release_queue", system["release"]["id"])
        row.update(status="queued", attempt=POLICY.release_max_attempts, retry_at=None)
        tx.put("release_queue", system["release"]["id"], row)
    exhausted = delivery.tick()
    assert exhausted["plan_id"] == "delivery-plan-2"
    assert exhausted["blocked"]["delivery-plan-1"] == "release_attempts_exhausted"


@binds_a_runtime
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
@binds_a_runtime
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


# ----- the fresh collect canary -----------------------------------------------------------------------------
@binds_a_runtime
def test_the_collect_canary_binds_a_fresh_monitor_source_to_this_instance_and_runtime(tmp_path):
    """The real coordinator with the real incumbent canary: the fresh read-only monitor source
    shows the instance that just started, before any activation has been recorded."""
    store = SerialStore()
    system = build(tmp_path, store=store, plan_overrides={"canary": CANARY_COLLECT},
                   canaries={CANARY_COLLECT: lambda target, descriptor, startup:
                             collect_monitor_canary(target, descriptor, startup, store=store)})
    try:
        results = drive(system)
        assert results[-1]["stage"] == ACTIVE, stages(results)
        row = descriptor_of(system)
        assert row["startup_observed"] is True and row["consumed"] is True
        assert row["observed_revision"] == RUNTIME_REVISION
        view = system["delivery"].status()["deliveries"][0]
        assert view["canary"]["check_id"] == CANARY_COLLECT
        assert view["canary"]["evidence"] == row["observed_instance_id"]
    finally:
        stop_target(system)


def test_the_collect_canary_refuses_a_missing_or_stale_monitor_source(tmp_path):
    store = SerialStore()
    target = targets_document(tmp_path)["targets"][0]
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "canary-service",
                  "root": target["root"], "revision": REVISION, "worker_image": FIXTURE_IMAGE,
                  "profile_digest": FIXTURE_PROFILE, "predecessor": None}
    startup = {"instance_id": "1" * 32, "revision": REVISION, "runtime_root": target["root"]}

    def observed(**fields):
        with store.transaction() as tx:
            tx.put(BUCKET_DESCRIPTORS, "canary-service",
                   {"id": "canary-service", "target_id": "canary-service", **fields})
        return collect_monitor_canary(target, descriptor, startup, store=store)

    assert collect_monitor_canary(target, descriptor, startup,
                                  store=None)["reason_code"] == "canary_store_unavailable"
    assert collect_monitor_canary(target, descriptor, startup,
                                  store=store)["reason_code"] == "canary_target_unobserved"
    # A source collected BEFORE the switch: it names the descriptor that was there then.
    stale = observed(descriptor_sha256="0" * 64, startup_observed=True,
                     observed_instance_id="1" * 32, observed_revision=REVISION)
    assert stale["reason_code"] == "canary_descriptor_not_observed"
    # The right descriptor was switched to, but no startup has been observed for it at all.
    unobserved = observed(descriptor_sha256=descriptor_digest(descriptor), startup_observed=False,
                          observed_instance_id=None, observed_revision=None)
    assert unobserved["reason_code"] == "canary_descriptor_not_observed"
    # An earlier instance of the same descriptor is not this delivery's instance.
    other = observed(descriptor_sha256=descriptor_digest(descriptor), startup_observed=True,
                     observed_instance_id="2" * 32, observed_revision=REVISION)
    assert other["reason_code"] == "canary_instance_not_observed"
    # The right instance, running another revision than the descriptor requested.
    moved = observed(descriptor_sha256=descriptor_digest(descriptor), startup_observed=True,
                     observed_instance_id="1" * 32, observed_revision="6" * 40)
    assert moved["reason_code"] == "canary_runtime_not_observed"
    passed = observed(descriptor_sha256=descriptor_digest(descriptor), startup_observed=True,
                      observed_instance_id="1" * 32, observed_revision=REVISION)
    assert passed["passed"] is True and passed["evidence"] == "1" * 32


# ----- reconciliation at the restore, start and receipt boundaries -------------------------------------------
def test_a_foreign_descriptor_blocks_the_switch_instead_of_overwriting_it(tmp_path):
    system = build(tmp_path)
    drive(system, until=SWITCHING, limit=7)
    intent = intent_of(system)
    # Labelled injected host state: something outside this delivery owns the target now.
    foreign = {**intent["descriptor"], "revision": "7" * 40}
    system["host"].switch(system["target"], foreign, expected=None)
    result = system["delivery"].tick()
    assert result["outcome"] == "blocked" and result["reason_code"] == "descriptor_foreign"
    assert system["host"].current(system["target"]) == foreign  # not overwritten, not started
    assert descriptor_of(system) is None


@binds_a_runtime
def test_a_restoration_interrupted_before_its_acknowledgement_resumes_and_is_proven(tmp_path):
    """The crash case: the predecessor is back on the host, its durable record never happened."""
    verdicts = {"passed": True}
    system = build(tmp_path, canaries={CANARY_STARTUP: lambda target, descriptor, startup: {
        "passed": verdicts["passed"], "reason_code": None if verdicts["passed"]
        else "canary_fixture_failed"}})
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        verdicts["passed"] = False
        successor = reviewed_release(system["store"], system["org"],
                                     record_candidate={**candidate(), "revision": "5" * 40,
                                                       "branch": "harness/two", "task_id": "two"})
        plan = plan_document(successor, plan_id="delivery-plan-2",
                             expected=good["descriptor_sha256"])
        system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
        system["plan"] = plan
        drive(system, until=ROLLING_BACK, limit=30)
        intent = intent_of(system)
        assert intent["stage"] == ROLLING_BACK and not (intent.get("rollback") or {}).get("restored")
        # The restoration happened; the acknowledgement did not.
        system["host"].switch(system["target"], intent["previous_descriptor"],
                              expected=intent["descriptor_sha256"])
        results = drive(system, until=ROLLED_BACK, limit=40)
        assert results[-1]["stage"] == ROLLED_BACK, "\n".join(
            str((r["stage"], r["outcome"], r["reason_code"])) for r in results)
        rolled = descriptor_of(system)
        assert rolled["descriptor_sha256"] == good["descriptor_sha256"]
        assert rolled["consumed"] is True and rolled["rolled_back"] is True
        receipt = json.loads((tmp_path / "state-canary-service" / RECEIPT_FILE).read_text("utf-8"))
        assert receipt["descriptor_sha256"] == good["descriptor_sha256"]
        assert intent_of(system)["rollback"]["verified"] is True
    finally:
        stop_target(system)


@binds_a_runtime
def test_a_rollback_onto_a_foreign_descriptor_blocks_rather_than_overwriting_it(tmp_path):
    verdicts = {"passed": True}
    system = build(tmp_path, canaries={CANARY_STARTUP: lambda target, descriptor, startup: {
        "passed": verdicts["passed"], "reason_code": None if verdicts["passed"]
        else "canary_fixture_failed"}})
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        verdicts["passed"] = False
        successor = reviewed_release(system["store"], system["org"],
                                     record_candidate={**candidate(), "revision": "5" * 40,
                                                       "branch": "harness/two", "task_id": "two"})
        plan = plan_document(successor, plan_id="delivery-plan-2",
                             expected=good["descriptor_sha256"])
        system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
        system["plan"] = plan
        drive(system, until=ROLLING_BACK, limit=30)
        intent = intent_of(system)
        foreign = {**intent["descriptor"], "revision": "7" * 40}
        system["host"].switch(system["target"], foreign, expected=intent["descriptor_sha256"])
        result = system["delivery"].tick()
        assert result["outcome"] == "blocked"
        assert result["reason_code"] == "rollback_foreign_descriptor"
        assert system["host"].current(system["target"]) == foreign
        assert intent_of(system)["rollback"]["restored"] is False
        assert descriptor_of(system)["consumed"] is False
    finally:
        stop_target(system)


# ----- ownership at the mutation boundary ----------------------------------------------------------------
def supersede(system):
    """A labelled injected supersession: this controller's lease expires and a successor claims."""
    past = "2000-01-01T00:00:00+00:00"
    with system["store"].transaction() as tx:
        row = tx.get("release_queue", system["release"]["id"])
        row["lease_until"] = past
        tx.put("release_queue", row["id"], row)
        lock = tx.get("deployment_locks", "controller") or {}
        tx.put("deployment_locks", "controller", {**lock, "lease_until": past})
    return ReleaseQueue(system["store"]).claim()


def test_a_superseded_controller_makes_no_external_change_and_records_nothing(tmp_path):
    """Loss BEFORE the effect: the fence is checked at the mutation boundary, not afterwards."""
    system = build(tmp_path)
    system["delivery"].tick()  # registered -> publishing
    github = system["github"]
    observe = github.observe

    def stolen(candidate):
        result = observe(candidate)
        supersede(system)
        return result

    before = intent_of(system)
    github.observe = stolen
    result = system["delivery"].tick()
    assert result["controller"] == "stale" and github.publishes == 0
    assert intent_of(system)["stage"] == PUBLISHING  # the stage it was left at, unchanged
    assert intent_of(system) == before  # and nothing this tick observed was recorded


def test_an_effect_across_a_lost_fence_is_ambiguous_and_is_reconciled_once(tmp_path):
    """Loss ACROSS the effect: the publication exists, its record does not, and the successor
    adopts it instead of publishing a second one."""
    system = build(tmp_path)
    system["delivery"].tick()  # registered -> publishing
    github = system["github"]
    publish = github.publish

    def stolen(candidate):
        row = publish(candidate)
        supersede(system)  # the response came back; the fence is gone before it can be recorded
        return row

    github.publish = stolen
    result = system["delivery"].tick()
    assert result["outcome"] == "conflict" and result["controller"] == "stale"
    assert result["ambiguous_effect"] == "published" and github.publishes == 1
    # The durable intent still names the stage that was entered BEFORE the effect: that is the
    # evidence the next owner reconciles from, and the effect is never claimed to be cancelled.
    assert intent_of(system)["stage"] == PUBLISHING
    github.publish = publish
    with system["store"].transaction() as tx:
        tx.put("deployment_locks", "controller", {"owner": None, "lease_until": None})
        row = tx.get("release_queue", system["release"]["id"])
        row.update(status="queued", owner=None, lease_until=None, retry_at=None, attempt=0)
        tx.put("release_queue", row["id"], row)
    system["clock"].advance(120)
    recovered = system["delivery"].tick()
    assert recovered["stage"] == AWAITING_CI and github.publishes == 1


@binds_a_runtime
def test_a_promotion_that_loses_the_fence_never_moves_the_pointer_and_reconciles(tmp_path):
    """Promotion and ownership share one transaction: there is no check-then-promote window."""
    system = build(tmp_path)
    delivery = system["delivery"]
    emit = delivery._emit
    stolen = {"done": False}

    def racing(event_type, outcome, plan, **fields):
        emit(event_type, outcome, plan, **fields)
        if event_type == EVENT_SWITCHED and outcome == "succeeded" and not stolen["done"]:
            # Labelled injected supersession, exactly between the recorded consumption and the
            # promotion that would move the existing active-release pointer.
            stolen["done"] = True
            supersede(system)

    delivery._emit = racing
    try:
        results = drive(system, until=ACTIVE, limit=30)
        conflicts = [result for result in results if result["outcome"] == "conflict"]
        assert len(conflicts) == 1, stages(results)
        assert conflicts[0]["ambiguous_effect"] == "release_promotion"
        assert conflicts[0]["controller"] == "stale"
        with system["store"].transaction() as tx:
            # The release pointer never moved, and the release was never marked active.
            assert tx.get("deployment", "active") is None
            assert tx.get("releases", system["release"]["id"])["status"] == "verified"
        # The host effect IS durable evidence: the descriptor was consumed by a real instance.
        consumed = descriptor_of(system)
        assert consumed["consumed"] is True and consumed["startup_observed"] is True
        assert intent_of(system)["stage"] == AWAITING_CONSUMPTION
        instance = consumed["instance_id"]
        with system["store"].transaction() as tx:
            tx.put("deployment_locks", "controller", {"owner": None, "lease_until": None})
            row = tx.get("release_queue", system["release"]["id"])
            row.update(status="queued", owner=None, lease_until=None, retry_at=None, attempt=0)
            tx.put("release_queue", row["id"], row)
        system["clock"].advance(120)
        finished = drive(system, until=ACTIVE, limit=20)
        assert finished[-1]["stage"] == ACTIVE
        # The same instance finished the delivery: nothing was switched or started a second time.
        assert descriptor_of(system)["instance_id"] == instance
        with system["store"].transaction() as tx:
            assert tx.get("deployment", "active")["release_id"] == system["release"]["id"]
    finally:
        delivery._emit = emit
        stop_target(system)


# ----- the shared target lifecycle guard --------------------------------------------------------------------
# One service is one lifecycle: the descriptor replacement, the pause, the stop, the retirement of
# the old instance's files, the launch and the state that identifies it. These exercise the ADAPTER
# effects of that boundary - real temporary state directories, real child processes and a labelled
# injected `schtasks` runner - not only the coordinator's return codes.
def descriptor_for(target, *, revision=None, predecessor=None, **overrides):
    """A complete descriptor for a real target: rooted at this checkout so it can really launch,
    and bound by default to the facts this runtime really has, so an instance of it is one the
    incumbent consumption check can actually recognize."""
    return {"schema": "urn:zeus:host-descriptor:1", "target_id": target["target_id"],
            "root": target["root"], "revision": revision or DESCRIPTOR_REVISION,
            "worker_image": IMAGE, "profile_digest": PROFILE or FIXTURE_PROFILE,
            "predecessor": predecessor, **overrides}


def await_receipt(target, digest=None, timeout=20.0):
    """The launched child's OWN receipt, waited for within a bound; optionally for one descriptor."""
    path = Path(target["state_dir"]) / RECEIPT_FILE
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            document = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            document = None
        if isinstance(document, dict) and (digest is None
                                           or document.get("descriptor_sha256") == digest):
            return document
        time.sleep(0.05)
    raise AssertionError("no startup receipt for the expected descriptor appeared")


def fixture_git(root, *args):
    """Git confined to one disposable fixture repository: no global or system configuration is
    read or written, and every setting the commit needs is passed for this one command only."""
    done = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "commit.gpgsign=false",
         "-c", "user.name=Zeus Fixture", "-c", "user.email=fixture@localhost", *args],
        cwd=str(root), capture_output=True, text=True, timeout=120,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip()


def runtime_copy(tmp_path, *, attested=True):
    """A test-owned runtime root: this checkout's REAL `src/codex_harness`, copied byte for byte.

    Attested, the copy is committed to a tiny repository of its own, so the revision its child
    observes is a real `HEAD` whether or not the checkout running the tests has a Git directory at
    all (an exported source archive does not). Unattested, it has no Git directory and no owner
    `runtime.json`: the deliberate no-git runtime, whose child honestly reports no revision.
    """
    root = tmp_path / ("attested-runtime" if attested else "unattested-runtime")
    if not root.exists():
        shutil.copytree(Path(RUNTIME_ROOT) / "src" / "codex_harness",
                        root / "src" / "codex_harness",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if attested:
            fixture_git(root, "init", "-q")
            fixture_git(root, "add", "--all")
            fixture_git(root, "commit", "-q", "--no-verify", "-m", "attested runtime fixture")
    return root


def runtime_image(root):
    """The worker image a runtime at `root` configures, read exactly as its own `settings()` does."""
    return effective_worker_image({**aliases(read_env(Path(root))), **aliases(dict(os.environ))})


def live_target(tmp_path, host, target_id="canary-service"):
    """A real target with a real running child process that has reported its own startup.

    The target runs the attested runtime copy, and the descriptor binds what that runtime really is:
    its own committed revision, its effective image and its packaged profile. The fixture is proven
    valid - the incumbent consumption check accepts the child's own receipt - BEFORE any test
    reaches the boundary it is about, so a later refusal is that boundary and not an unknown
    instance.
    """
    root = runtime_copy(tmp_path)
    revision = runtime_revision(root)
    assert revision is not None and revision == fixture_git(root, "rev-parse", "HEAD")
    target = targets_document(tmp_path, target_id=target_id, root=str(root))["targets"][0]
    descriptor = descriptor_for(target, revision=revision, worker_image=runtime_image(root))
    host.switch(target, descriptor, expected=None)
    host.start(target, descriptor)
    receipt = await_receipt(target, descriptor_digest(descriptor))
    verdict = consumption_verdict(descriptor, receipt)
    assert verdict["consumed"], verdict["reason_code"]
    return target, descriptor, receipt


def test_a_runtime_that_attests_no_revision_is_unreadable_and_the_attested_fixture_is_not(tmp_path):
    """The discriminating control for an exported source archive with no Git directory.

    The same real source, launched from a root that attests no revision, reports an empty revision;
    that receipt identifies nobody, so a replacement is refused as `instance_receipt_unreadable`
    before any stop. Production validation is unchanged: absent Git proves no revision, and only the
    fixture's own committed runtime yields the valid receipt the lifecycle tests start from.
    """
    host = ProcessHostTarget(max_seconds=60)
    bare = runtime_copy(tmp_path, attested=False)
    assert runtime_revision(bare) is None
    target = targets_document(tmp_path, target_id="unattested-service",
                              root=str(bare))["targets"][0]
    descriptor = descriptor_for(target, worker_image=runtime_image(bare))
    host.switch(target, descriptor, expected=None)
    host.start(target, descriptor)
    try:
        receipt = await_receipt(target, descriptor_digest(descriptor))
        assert receipt["revision"] == ""
        assert consumption_verdict(descriptor, receipt)["reason_code"] == "receipt_invalid"
        successor = descriptor_for(target, revision="8" * 40, worker_image=runtime_image(bare),
                                   predecessor=descriptor_digest(descriptor))
        authority = replaces(target, descriptor, receipt)
        host.switch(target, successor, expected=descriptor_digest(descriptor))
        with pytest.raises(DeliveryRefused) as unreadable:
            host.start(target, successor, authorize=lambda: None, replaces=authority)
        assert unreadable.value.reason_code == "instance_receipt_unreadable"
        assert host.running(target) and not state_of(target, "stop.json").exists()
    finally:
        host.stop(target)
    # The attested copy of the very same source is a valid, consumed runtime.
    attested_target, _, attested = live_target(tmp_path, host, target_id="attested-service")
    try:
        assert attested["revision"] == runtime_revision(attested_target["root"])
    finally:
        host.stop(attested_target)


def stale_fence(after=0):
    """A labelled injected fence: it authorizes `after` calls, then reports the lease it lost."""
    def authorize():
        authorize.calls += 1
        if authorize.calls > after:
            raise ContractError("injected: stale release controller")

    authorize.calls = 0
    return authorize


def state_of(target, name):
    return Path(target["state_dir"]) / name


def launch_of(target):
    """The launch record this component wrote for a target, read straight from its state file."""
    path = state_of(target, STATE_FILE)
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def replaces(target, descriptor, receipt=None, *, instance_id=None, launch=True):
    """The durable authority the coordinator passes to a start: exactly which instance this
    transition may replace. Built here from the same two facts the coordinator captures - the
    descriptor the instance was running and its own instance or launch identity."""
    return {"descriptor_sha256": descriptor_digest(descriptor),
            "instance_id": instance_id or (receipt or {}).get("instance_id"),
            "launch": launch_of(target) if launch is True else launch}


def test_a_stale_controller_stops_nothing_and_unlinks_nothing_before_the_guard(tmp_path):
    """The rejected R5 path itself: a superseded controller resumes into `start`.

    Before this guard, `start` stopped the service and deleted its receipt BEFORE calling the
    caller's authorization and outside any lock, so a controller whose lease had expired took out
    the successor it had lost the target to and destroyed that successor's evidence. Ownership is
    now proven inside the guard, before the first mutation of any kind.
    """
    host = ProcessHostTarget(max_seconds=60)
    target, descriptor, receipt = live_target(tmp_path, host)
    try:
        successor = descriptor_for(target, revision="8" * 40,
                                   predecessor=descriptor_digest(descriptor))
        host.switch(target, successor, expected=descriptor_digest(descriptor))
        fence = stale_fence()
        with pytest.raises(ContractError):
            host.start(target, successor, authorize=fence)
        assert fence.calls == 1  # asked once, inside the guard, and refused there
        assert host.running(target)  # the live instance was never stopped
        assert await_receipt(target)["instance_id"] == receipt["instance_id"]
        assert not state_of(target, "stop.json").exists()  # nothing was even asked to stop
        assert not state_of(target, "switch.lock").exists()  # and the guard was released
    finally:
        host.stop(target)


def test_a_successor_started_between_the_outer_check_and_the_guard_survives(tmp_path):
    """The review's controlled barrier, deterministically interleaved.

    A passes its own outer fence check; B then claims the target and completes its WHOLE lifecycle
    operation; only then does A resume into the adapter. A must neither stop B's service nor remove
    B's receipt, whether the authority it carries reports the loss or is absent altogether.
    """
    first, second = ProcessHostTarget(max_seconds=60), ProcessHostTarget(max_seconds=60)
    target = targets_document(tmp_path)["targets"][0]
    mine = descriptor_for(target, revision="1" * 40)
    first.switch(target, mine, expected=None)
    fence = stale_fence(after=1)
    fence()  # A's outer check, passed while it still owned the lease
    # --- the barrier: B takes the target over completely before A acts on it ---
    theirs = descriptor_for(target, revision="2" * 40, predecessor=descriptor_digest(mine))
    second.switch(target, theirs, expected=descriptor_digest(mine))
    second.start(target, theirs)
    running = await_receipt(target, descriptor_digest(theirs))
    try:
        with pytest.raises(ContractError):
            first.start(target, mine, authorize=fence)
        assert second.running(target)
        assert await_receipt(target)["instance_id"] == running["instance_id"]
        # Even with no authority to ask at all, the target no longer carries A's descriptor: that
        # is a foreign state, refused before anything is stopped or unlinked.
        with pytest.raises(DeliveryRefused) as foreign:
            first.start(target, mine)
        assert foreign.value.reason_code == "descriptor_foreign"
        assert second.running(target) and second.current(target) == theirs
        assert await_receipt(target)["instance_id"] == running["instance_id"]
        assert not state_of(target, "stop.json").exists()
    finally:
        second.stop(target)


def test_a_fence_lost_during_the_bounded_stop_preserves_the_effect_and_starts_nothing(tmp_path):
    """A stop can outlive a lease. What it already did is preserved, and nothing follows it."""
    host = ProcessHostTarget(max_seconds=60)
    target, descriptor, receipt = live_target(tmp_path, host)
    try:
        successor = descriptor_for(target, revision="8" * 40,
                                   predecessor=descriptor_digest(descriptor))
        authority = replaces(target, descriptor, receipt)
        host.switch(target, successor, expected=descriptor_digest(descriptor))
        recorded = json.loads(state_of(target, STATE_FILE).read_text("utf-8"))
        fence = stale_fence(after=1)  # the guard entry passes; the check after the stop does not
        with pytest.raises(LifecycleInterrupted) as interrupted:
            host.start(target, successor, authorize=fence, replaces=authority)
        assert interrupted.value.effect == "service_stopped"
        assert isinstance(interrupted.value.cause, ContractError)
        # The stop happened and is kept as the observed effect it is: no cleanup, no launch, and
        # the stopped instance's own evidence is not erased or called cancelled.
        assert not host.running(target)
        assert await_receipt(target)["instance_id"] == receipt["instance_id"]
        assert json.loads(state_of(target, STATE_FILE).read_text("utf-8")) == recorded
        # The guard is released, so the successor is serialized behind it rather than locked out.
        # The instance it replaces is the stopped one this transition named: an interrupted
        # lifecycle is resumed, not a reason to act on an unidentified target.
        successor_host = ProcessHostTarget(max_seconds=60)
        assert successor_host.start(target, successor, authorize=lambda: None,
                                    replaces=authority)["started"] is True
        assert await_receipt(target, descriptor_digest(successor))["instance_id"] \
            != receipt["instance_id"]
    finally:
        host.stop(target)


def test_a_supersession_during_the_switch_stop_is_reported_as_an_ambiguous_effect(tmp_path):
    """The same interruption through the REAL coordinator: a conflict carrying the effect it had."""
    armed = {"on": False, "system": None}

    class SupersedingHost(ProcessHostTarget):
        """Labelled injected supersession, exactly inside the lifecycle's own bounded stop."""

        def stop(self, target):
            observed = super().stop(target)
            if armed["on"]:
                armed["on"] = False
                supersede(armed["system"])
            return observed

    system = build(tmp_path)
    armed["system"] = system
    system["host"] = system["delivery"].hosts["process"] = SupersedingHost(max_seconds=60)
    try:
        drive(system, until=SWITCHING, limit=7)
        armed["on"] = True
        result = system["delivery"].tick()
        assert result["outcome"] == "conflict" and result["controller"] == "stale"
        assert result["ambiguous_effect"] == "service_stopped"
        # The durable intent still names the stage entered BEFORE the effect, and neither the
        # switch nor a consumption is claimed: the next owner reconciles this target.
        assert intent_of(system)["stage"] == SWITCHING
        assert descriptor_of(system) is None
        assert not state_of(system["target"], RECEIPT_FILE).exists()
    finally:
        stop_target(system)


@binds_a_runtime
def test_a_restarted_start_recognizes_the_matching_live_instance_instead_of_restarting_it(tmp_path):
    """Recovery is recognition: the instance already running the intended descriptor is kept.

    It is the incumbent consumption check that decides "already running this", so this is the real
    runtime's own receipt and not a digest echo. It is also the same call the forward switch and
    the rollback both make, so a start reached again after a lost acknowledgement - in either
    direction - reconciles rather than churns the service.
    """
    host = ProcessHostTarget(max_seconds=60)
    target, descriptor, receipt = live_target(tmp_path, host)
    try:
        recorded = json.loads(state_of(target, STATE_FILE).read_text("utf-8"))
        again = host.start(target, descriptor, authorize=lambda: None)
        assert again == {"started": False, "recovered": True,
                         "instance_id": receipt["instance_id"], "launch": recorded}
        assert host.running(target)
        assert await_receipt(target)["instance_id"] == receipt["instance_id"]
        assert json.loads(state_of(target, STATE_FILE).read_text("utf-8")) == recorded
        assert not state_of(target, "stop.json").exists()  # it was never asked to stop
    finally:
        host.stop(target)


class LateReceiptHost(ProcessHostTarget):
    """Labelled injected timing: the next `miss` receipt reads answer None.

    That is exactly the window the guard closes - the coordinator looked before the restored
    instance had published its startup, so its own check says "start it", and the guarded start
    looks again at the moment it would otherwise kill that instance.
    """

    def __init__(self, *, miss=0, **kwargs):
        super().__init__(**kwargs)
        self.miss = miss

    def receipt(self, target):
        if self.miss > 0:
            self.miss -= 1
            return None
        return super().receipt(target)


@binds_a_runtime
def test_a_rollback_start_after_a_lost_acknowledgement_keeps_the_restored_instance(tmp_path):
    """The rollback half of that reconciliation, through the coordinator and a real process."""
    verdicts = {"passed": True}
    system = build(tmp_path, canaries={CANARY_STARTUP: lambda target, descriptor, startup: {
        "passed": verdicts["passed"], "reason_code": None if verdicts["passed"]
        else "canary_fixture_failed"}})
    system["host"] = system["delivery"].hosts["process"] = LateReceiptHost(max_seconds=60)
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        verdicts["passed"] = False
        successor = reviewed_release(system["store"], system["org"],
                                     record_candidate={**candidate(), "revision": "5" * 40,
                                                       "branch": "harness/two", "task_id": "two"})
        plan = plan_document(successor, plan_id="delivery-plan-2",
                             expected=good["descriptor_sha256"])
        system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
        system["plan"] = plan
        drive(system, until=ROLLING_BACK, limit=30)
        for _ in range(20):
            if (intent_of(system).get("rollback") or {}).get("started"):
                break
            system["delivery"].tick()
            system["clock"].advance(1)
            time.sleep(0.05)
        restored = await_receipt(system["target"], good["descriptor_sha256"])
        with system["store"].transaction() as tx:
            intent = tx.get(BUCKET_INTENTS, system["plan"]["plan_id"])
            # Labelled injected loss of the start acknowledgement: the predecessor IS running, the
            # durable record of having started it never happened, so the stage starts it again.
            intent["rollback"] = {**intent["rollback"], "started": False}
            tx.put(BUCKET_INTENTS, intent["id"], intent)
        # ...and the coordinator's own check misses that instance's receipt, so the start is the
        # one thing standing between the restored runtime and being killed for nothing.
        system["host"].miss = 1
        results = drive(system, until=ROLLED_BACK, limit=30)
        assert results[-1]["stage"] == ROLLED_BACK, "\n".join(
            str((r["stage"], r["outcome"], r["reason_code"])) for r in results)
        # The same restored instance proved the rollback: it was recognized, never restarted.
        assert descriptor_of(system)["instance_id"] == restored["instance_id"]
    finally:
        stop_target(system)


def test_lifecycle_operations_serialize_on_one_target_and_never_across_targets(tmp_path):
    """The guard is per target: one service is exclusive, an unrelated one is not affected."""
    holder, elsewhere = ProcessHostTarget(max_seconds=60), ProcessHostTarget(max_seconds=60)
    first = targets_document(tmp_path, target_id="canary-service")["targets"][0]
    second = targets_document(tmp_path, target_id="other-service")["targets"][0]
    inside, release, outcome = threading.Event(), threading.Event(), {}
    descriptor = descriptor_for(first)

    def barrier():
        """A controlled barrier: the holder stays inside the guard until this is released."""
        inside.set()
        release.wait(30)

    def hold():
        try:
            outcome["result"] = holder.switch(first, descriptor, expected=None, authorize=barrier)
        except Exception as exc:  # reported through the result, never swallowed
            outcome["error"] = exc

    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert inside.wait(30)
        contender = ProcessHostTarget(max_seconds=60, lock_timeout=0.3)
        with pytest.raises(DeliveryRefused) as held:
            contender.start(first, descriptor, authorize=lambda: None)
        # A held guard is a conflicting change on that target: waited for, then refused, never
        # broken on age, and nothing of the operation it would have performed happened.
        assert held.value.reason_code == "target_lock_held"
        assert not state_of(first, "stop.json").exists()
        assert not state_of(first, STATE_FILE).exists()
        # The unrelated target is free while that one is held.
        assert elsewhere.switch(second, descriptor_for(second), expected=None)["written"] is True
    finally:
        release.set()
        worker.join(30)
    assert outcome.get("error") is None and outcome["result"]["written"] is True


def test_an_unavailable_authority_stops_the_lifecycle_before_any_effect(tmp_path):
    """The fence cannot be read at all: the operation refuses and the service stays exactly as is."""
    host = ProcessHostTarget(max_seconds=60)
    target, descriptor, receipt = live_target(tmp_path, host)

    def unavailable():
        raise ConnectionError("injected: the fence cannot be read")

    try:
        successor = descriptor_for(target, revision="8" * 40,
                                   predecessor=descriptor_digest(descriptor))
        with pytest.raises(ConnectionError):
            host.switch(target, successor, expected=descriptor_digest(descriptor),
                        authorize=unavailable)
        assert host.current(target) == descriptor  # not replaced
        with pytest.raises(ConnectionError):
            host.start(target, descriptor, authorize=unavailable)
        assert host.running(target)  # not stopped
        assert await_receipt(target)["instance_id"] == receipt["instance_id"]
        assert not state_of(target, "stop.json").exists()
        assert not state_of(target, "switch.lock").exists()
        with pytest.raises(ConnectionError):
            host.drain(target, authorize=unavailable)
        assert not state_of(target, "pause.json").exists()  # not even paused
    finally:
        host.stop(target)


# ----- who may replace THIS instance ------------------------------------------------------------
# Descriptor identity and authority over a running instance are different facts. These exercise the
# classification on real targets: a real child process, its own real receipt, the real launch record
# this component writes, and a labelled injected scheduled-task runner.
class LegacyReplacementHost(ProcessHostTarget):
    """The REJECTED pre-R5 rule, reproduced here as a controlled counterexample and used nowhere
    else: any receipt that did not match the descriptor being started was read as permission to
    stop that instance, delete its evidence and launch over it."""

    def start(self, target, descriptor, *, authorize=None, replaces=None):
        with self.guard(target, authorize):
            context = self._prepare(target, descriptor)
            self._reconcile(target, descriptor)
            verdict = consumption_verdict(descriptor, self.receipt(target))
            if verdict["consumed"] and self.running(target):
                return {"started": False, "recovered": True, "instance_id": verdict["instance_id"]}
            self.stop(target)
            self._retire(target)
            return self._launch(target, descriptor, context)


@binds_a_runtime
def test_the_old_nonmatching_receipt_rule_replaces_a_live_instance_and_the_new_one_refuses(tmp_path):
    """The counterexample and the correction, on the same interleaving and the same evidence."""
    legacy, host = LegacyReplacementHost(max_seconds=60), ProcessHostTarget(max_seconds=60)
    first, descriptor, receipt = live_target(tmp_path, legacy, target_id="legacy-service")
    try:
        successor = descriptor_for(first, revision="8" * 40,
                                   predecessor=descriptor_digest(descriptor))
        legacy.switch(first, successor, expected=descriptor_digest(descriptor))
        # The defect: a live instance that is merely NOT the intended one is stopped, its own
        # receipt deleted and a second instance launched over it, with no authority anywhere.
        assert legacy.start(first, successor, authorize=lambda: None)["started"] is True
        assert await_receipt(first, descriptor_digest(successor))["instance_id"] \
            != receipt["instance_id"]
    finally:
        legacy.stop(first)
    second, current, running = live_target(tmp_path, host, target_id="corrected-service")
    try:
        successor = descriptor_for(second, revision="8" * 40,
                                   predecessor=descriptor_digest(current))
        host.switch(second, successor, expected=descriptor_digest(current))
        with pytest.raises(DeliveryRefused) as refused:
            host.start(second, successor, authorize=lambda: None)
        assert refused.value.reason_code == "instance_not_authorized"
        # The service and its evidence are exactly as they were: refused before stop and cleanup.
        assert host.running(second)
        assert await_receipt(second)["instance_id"] == running["instance_id"]
        assert not state_of(second, "stop.json").exists()
    finally:
        host.stop(second)


@binds_a_runtime
def test_only_the_predecessor_this_transition_captured_may_be_replaced(tmp_path):
    """The forward half of the fixed matrix: the authorized predecessor, and nothing else."""
    host = ProcessHostTarget(max_seconds=60)
    target, descriptor, receipt = live_target(tmp_path, host)
    try:
        authority = replaces(target, descriptor, receipt)
        successor = descriptor_for(target, revision="8" * 40,
                                   predecessor=descriptor_digest(descriptor))
        host.switch(target, successor, expected=descriptor_digest(descriptor))
        # An authority over ANOTHER instance is no authority over this one.
        with pytest.raises(DeliveryRefused) as other:
            host.start(target, successor, authorize=lambda: None,
                       replaces={**authority, "instance_id": "c" * 32})
        assert other.value.reason_code == "instance_not_authorized"
        # The right instance under the wrong descriptor is contradictory evidence, not a licence.
        with pytest.raises(DeliveryRefused) as contradictory:
            host.start(target, successor, authorize=lambda: None,
                       replaces={"descriptor_sha256": "0" * 64,
                                 "instance_id": receipt["instance_id"], "launch": None})
        assert contradictory.value.reason_code == "instance_contradictory"
        assert host.running(target) and not state_of(target, "stop.json").exists()
        assert await_receipt(target)["instance_id"] == receipt["instance_id"]
        # The exact instance this transition captured before the descriptor was replaced IS
        # replaceable, once, and the launch it performs is reported as the evidence it wrote.
        started = host.start(target, successor, authorize=lambda: None, replaces=authority)
        assert started["started"] is True and started["launch"]["pid"] == started["pid"]
        assert started["launch"] == launch_of(target)
        assert await_receipt(target, descriptor_digest(successor))["instance_id"] \
            != receipt["instance_id"]
    finally:
        host.stop(target)


@binds_a_runtime
def test_a_missing_or_malformed_receipt_beside_a_live_process_preserves_it(tmp_path):
    """An unidentified live instance is never an absence, and the launch record is what recovers it."""
    host = ProcessHostTarget(max_seconds=60)
    target, descriptor, receipt = live_target(tmp_path, host)
    try:
        authority = replaces(target, descriptor, receipt)
        successor = descriptor_for(target, revision="8" * 40,
                                   predecessor=descriptor_digest(descriptor))
        host.switch(target, successor, expected=descriptor_digest(descriptor))
        state_of(target, RECEIPT_FILE).write_text("{not json", encoding="utf-8")
        with pytest.raises(DeliveryRefused) as unreadable:
            host.start(target, successor, authorize=lambda: None, replaces=authority)
        assert unreadable.value.reason_code == "instance_receipt_unreadable"
        assert host.running(target)
        assert state_of(target, RECEIPT_FILE).read_text("utf-8") == "{not json"
        # Gone entirely, with a process still running: unidentified, not absent.
        state_of(target, RECEIPT_FILE).unlink()
        with pytest.raises(DeliveryRefused) as unidentified:
            host.start(target, successor, authorize=lambda: None,
                       replaces={**authority, "launch": None})
        assert unidentified.value.reason_code == "instance_unidentified"
        assert host.running(target) and not state_of(target, "stop.json").exists()
        # A startup identity that was never confirmed is reconciled by the launch record THIS
        # component wrote for that instance - not by a live pid, and not by a guess.
        assert host.start(target, successor, authorize=lambda: None,
                          replaces=authority)["started"] is True
        assert await_receipt(target, descriptor_digest(successor))["instance_id"] \
            != receipt["instance_id"]
    finally:
        host.stop(target)


def test_a_clean_target_starts_and_an_absence_that_is_not_proven_does_not(tmp_path):
    """Initial activation needs POSITIVE evidence of absence; a read that says nothing is not one."""
    host = ProcessHostTarget(max_seconds=60)
    target = targets_document(tmp_path, target_id="clean-service")["targets"][0]
    descriptor = descriptor_for(target)
    host.switch(target, descriptor, expected=None)
    state_of(target, RECEIPT_FILE).write_text("", encoding="utf-8")
    with pytest.raises(DeliveryRefused) as unknown:
        host.start(target, descriptor, authorize=lambda: None)
    assert unknown.value.reason_code == "instance_receipt_unreadable"
    assert not state_of(target, STATE_FILE).exists()  # nothing was launched or recorded
    state_of(target, RECEIPT_FILE).unlink()
    try:
        assert host.start(target, descriptor, authorize=lambda: None)["started"] is True
    finally:
        host.stop(target)


@binds_a_runtime
def test_a_known_dead_instance_of_this_delivery_is_resumed_and_an_unknown_one_is_not(tmp_path):
    """Known-dead recovery: this delivery's own stopped instance, proven by its own receipt."""
    host = ProcessHostTarget(max_seconds=60)
    target, descriptor, receipt = live_target(tmp_path, host)
    assert host.stop(target)["stopped"] is True
    try:
        assert host.start(target, descriptor, authorize=lambda: None)["started"] is True
        second = await_receipt(target, descriptor_digest(descriptor))
        assert second["instance_id"] != receipt["instance_id"]
    finally:
        host.stop(target)
    # A stopped instance of ANOTHER descriptor, with nothing naming it, stays blocked.
    successor = descriptor_for(target, revision="8" * 40, predecessor=descriptor_digest(descriptor))
    host.switch(target, successor, expected=descriptor_digest(descriptor))
    with pytest.raises(DeliveryRefused) as unknown:
        host.start(target, successor, authorize=lambda: None)
    assert unknown.value.reason_code == "instance_not_authorized"
    assert not host.running(target)
    assert await_receipt(target)["instance_id"] == second["instance_id"]


class FakeSchtasks:
    """A labelled in-test double for `schtasks`: it records argv and answers from its own state.

    No scheduled task is created, queried, started or ended on this or any host; nothing here runs
    `schtasks` and no production service is reachable from it.
    """

    def __init__(self, running=False):
        self.calls, self.running = [], running

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        verb = argv[1]
        if verb == "/Query":
            return subprocess.CompletedProcess(
                argv, 0, "Status: " + ("Running" if self.running else "Ready"), "")
        if verb == "/End":
            self.running = False
        if verb == "/Run":
            self.running = True
        return subprocess.CompletedProcess(argv, 0, "", "")

    @property
    def verbs(self):
        return [call[1] for call in self.calls]


def test_the_scheduled_task_target_shares_the_guard_authorization_and_reconciliation(tmp_path):
    """The Windows host target under exactly the same lifecycle boundary, with an injected runner."""
    runner = FakeSchtasks(running=True)
    host = ScheduledTaskHostTarget(runner=runner)
    target = targets_document(tmp_path, target_id="fleet-service",
                              kind="windows_scheduled_task")["targets"][0]
    # An identity-only runtime: this target's service is the owner's task, which this never
    # launches itself, so the descriptor's root is a registered path and not this checkout.
    descriptor = descriptor_for(target, root="/opt/zeus", revision=REVISION,
                                worker_image=FIXTURE_IMAGE, profile_digest=FIXTURE_PROFILE)
    host.switch(target, descriptor, expected=None)
    # A superseded controller ends nothing and runs nothing: the task is not even queried.
    with pytest.raises(ContractError):
        host.start(target, descriptor, authorize=stale_fence())
    assert runner.verbs == [] and runner.running is True
    # A descriptor that is not the target's is foreign, and refuses before the task is touched.
    with pytest.raises(DeliveryRefused) as refused:
        host.start(target, descriptor_for(target, root="/opt/zeus", revision="7" * 40,
                                          worker_image=FIXTURE_IMAGE,
                                          profile_digest=FIXTURE_PROFILE))
    assert refused.value.reason_code == "descriptor_foreign" and runner.verbs == []
    # A live instance that is really running this descriptor is recognized, not restarted.
    receipt = owned_receipt(descriptor, target_id="fleet-service", instance_id="a" * 32)
    state_of(target, RECEIPT_FILE).write_text(json.dumps(receipt), encoding="utf-8")
    assert host.start(target, descriptor, authorize=lambda: None) == {
        "started": False, "recovered": True, "instance_id": "a" * 32, "launch": None}
    assert runner.verbs == ["/Query"] and runner.running is True
    # Another instance's receipt beside the correct descriptor. This is the R5 boundary itself, and
    # it used to END the task and delete that instance's evidence: a receipt that does not match
    # the descriptor being started was read as permission to replace whatever was running. It is
    # now a refusal BEFORE any stop or cleanup, because nothing authorizes replacing THIS instance.
    unrelated = owned_receipt(descriptor, target_id="fleet-service", instance_id="b" * 32,
                              descriptor_sha256="0" * 64)
    state_of(target, RECEIPT_FILE).write_text(json.dumps(unrelated), encoding="utf-8")
    with pytest.raises(DeliveryRefused) as unauthorized:
        host.start(target, descriptor, authorize=lambda: None)
    assert unauthorized.value.reason_code == "instance_not_authorized"
    assert "/End" not in runner.verbs and "/Run" not in runner.verbs
    assert runner.running is True  # the running task survived
    assert json.loads(state_of(target, RECEIPT_FILE).read_text("utf-8")) == unrelated
    assert not state_of(target, STATE_FILE).exists()  # and nothing was launched or recorded
    # Named as the instance this transition replaces, the SAME state is ended, retired and started
    # exactly once - by the authority the coordinator carries, not by the adapter's own reading.
    assert host.start(target, descriptor, authorize=lambda: None,
                      replaces={"descriptor_sha256": "0" * 64, "instance_id": "b" * 32,
                                "launch": None}) == {
        "started": True, "service": target["service"],
        "launch": launch_of(target)}
    assert runner.verbs.index("/End") < runner.verbs.index("/Run")
    assert runner.verbs.count("/Run") == 1 and runner.running is True
    assert not state_of(target, RECEIPT_FILE).exists()
    assert json.loads(state_of(target, STATE_FILE).read_text("utf-8"))["descriptor_sha256"] \
        == descriptor_digest(descriptor)
    assert not state_of(target, "switch.lock").exists()


def test_a_target_whose_liveness_cannot_be_read_refuses_before_any_effect(tmp_path):
    """Unknown liveness is an unknown, never a licence: the task is neither ended nor started."""

    class UnreadableSchtasks(FakeSchtasks):
        """Labelled injected outage: this task's status cannot be read at all."""

        def __call__(self, argv, timeout=None):
            if argv[1] == "/Query":
                self.calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 1, "", "injected: status unavailable")
            return super().__call__(argv, timeout=timeout)

    runner = UnreadableSchtasks(running=True)
    host = ScheduledTaskHostTarget(runner=runner)
    target = targets_document(tmp_path, target_id="fleet-service",
                              kind="windows_scheduled_task")["targets"][0]
    descriptor = descriptor_for(target, root="/opt/zeus", revision=REVISION,
                                worker_image=FIXTURE_IMAGE, profile_digest=FIXTURE_PROFILE)
    host.switch(target, descriptor, expected=None)
    with pytest.raises(DeliveryRefused) as unknown:
        host.start(target, descriptor, authorize=lambda: None,
                   replaces={"descriptor_sha256": "0" * 64, "instance_id": "b" * 32,
                             "launch": None})
    assert unknown.value.reason_code == "instance_liveness_unknown"
    assert runner.verbs == ["/Query"] and runner.running is True
    assert not state_of(target, STATE_FILE).exists()


# ----- the same authority through the coordinator ------------------------------------------------
def second_plan(system, *, expected, plan_id="delivery-plan-2"):
    """A second reviewed candidate for the same target, registered through the existing authority."""
    successor = reviewed_release(system["store"], system["org"],
                                 record_candidate={**candidate(), "revision": "5" * 40,
                                                   "branch": "harness/two", "task_id": "two"})
    plan = plan_document(successor, plan_id=plan_id, expected=expected)
    system["delivery"].register(plan, pin(path="docs/zeus/operations/delivery-2.json"))
    system["plan"] = plan
    return plan


@binds_a_runtime
def test_an_instance_the_records_do_not_name_stops_the_delivery_before_the_host(tmp_path):
    """The identity is captured from the target BEFORE the descriptor is replaced, and it must
    agree with this delivery's own durable record of what is running there."""
    system = build(tmp_path)
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        second_plan(system, expected=good["descriptor_sha256"])
        # A labelled injected foreign instance: an otherwise perfect receipt for another instance.
        receipt = json.loads(state_of(system["target"], RECEIPT_FILE).read_text("utf-8"))
        foreign = {**receipt, "instance_id": "c" * 32}
        state_of(system["target"], RECEIPT_FILE).write_text(json.dumps(foreign), encoding="utf-8")
        results = drive(system, until=SWITCHING, limit=20)
        assert results[-1]["outcome"] == "blocked"
        assert results[-1]["reason_code"] == "target_instance_mismatch"
        # Nothing on the host was touched: the predecessor's descriptor, process and evidence stand.
        written = json.loads(state_of(system["target"], DESCRIPTOR_FILE).read_text("utf-8"))
        assert descriptor_digest(written) == good["descriptor_sha256"]
        assert system["host"].running(system["target"])
        assert json.loads(state_of(system["target"], RECEIPT_FILE).read_text("utf-8")) == foreign
    finally:
        stop_target(system)


@binds_a_runtime
def test_an_instance_that_appears_after_the_authority_was_captured_blocks_the_start(tmp_path):
    """The other side of the same boundary: the target changes hands between the captured identity
    and the start, so the start refuses and the running service is left alone."""
    system = build(tmp_path)
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        second_plan(system, expected=good["descriptor_sha256"])
        assert drive(system, until=SWITCHING, limit=20)[-1]["stage"] == SWITCHING
        receipt = json.loads(state_of(system["target"], RECEIPT_FILE).read_text("utf-8"))
        foreign = {**receipt, "instance_id": "c" * 32}
        state_of(system["target"], RECEIPT_FILE).write_text(json.dumps(foreign), encoding="utf-8")
        result = system["delivery"].tick()
        assert result["outcome"] == "refused"
        assert result["reason_code"] == "instance_not_authorized"
        assert system["host"].running(system["target"])  # never stopped
        assert json.loads(state_of(system["target"], RECEIPT_FILE).read_text("utf-8")) == foreign
        # Nothing was recorded for the candidate: the durable row still names the predecessor and
        # the instance that actually ran it, so no activation was claimed for this switch.
        row = descriptor_of(system)
        assert row["descriptor_sha256"] == good["descriptor_sha256"]
        assert row["instance_id"] == good["instance_id"]
        assert intent_of(system)["stage"] == BLOCKED
    finally:
        stop_target(system)


@binds_a_runtime
def test_a_rollback_replaces_the_candidate_it_started_and_not_the_predecessor(tmp_path):
    """The rollback half: the authority it carries names the FAILED candidate instance."""
    verdicts = {"passed": True}
    system = build(tmp_path, canaries={CANARY_STARTUP: lambda target, descriptor, startup: {
        "passed": verdicts["passed"],
        "reason_code": None if verdicts["passed"] else "canary_fixture_failed"}})
    try:
        assert drive(system)[-1]["stage"] == ACTIVE
        good = descriptor_of(system)
        verdicts["passed"] = False
        second_plan(system, expected=good["descriptor_sha256"])
        drive(system, until=ROLLING_BACK, limit=30)
        intent = intent_of(system)
        candidate_receipt = json.loads(
            state_of(system["target"], RECEIPT_FILE).read_text("utf-8"))
        # What the rollback is authorized to replace is the instance this intent launched, named by
        # its own receipt and by the launch record this component wrote for it.
        assert intent["candidate_instance_id"] == candidate_receipt["instance_id"]
        assert intent["candidate_launch"]["descriptor_sha256"] == intent["descriptor_sha256"]
        assert intent["previous_instance_id"] == good["instance_id"]
        assert intent["previous_launch"]["descriptor_sha256"] == good["descriptor_sha256"]
        results = drive(system, until=ROLLED_BACK, limit=30)
        assert results[-1]["stage"] == ROLLED_BACK, "\n".join(
            str((r["stage"], r["outcome"], r["reason_code"])) for r in results)
        rolled = descriptor_of(system)
        assert rolled["descriptor_sha256"] == good["descriptor_sha256"]
        assert rolled["consumed"] is True and rolled["rolled_back"] is True
        # The restored runtime is a NEW instance of the predecessor tuple, and the failed
        # candidate's instance is gone rather than left running beside it.
        assert rolled["instance_id"] not in {candidate_receipt["instance_id"],
                                             good["instance_id"]}
    finally:
        stop_target(system)


# ----- isolated PostgreSQL --------------------------------------------------------------------------------------
@binds_a_runtime
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
