"""INV-HOST-DELIVERY-001 pre-merge bindings and owner withdrawal (aibox SPEC s15, D2/D3).

The same fixtures as test_host_delivery: a SerialStore (a nested transaction fails immediately), the
real Releases/ReleaseQueue authorities, a real process target for the host side and the LABELLED
GitHub double. `FakeGitHub(fast_forward=True)` models the lease fast-forward merger: main becomes the
reviewed revision and the PR's own state is left alone. Every other injected GitHub fact (main moved,
a UI merge, a lost response, a refused push, an outage) is labelled where it is injected. Nothing here
runs `gh`, opens a socket or touches a real repository; the bare-repository Git behaviour itself is
tests/test_git_merge_cas.py.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_host_delivery import (
    BASE,
    CHECK,
    MERGED_REVISION,
    REVISION,
    TREE,
    FakeGitHub,
    binds_a_runtime,
    build,
    descriptor_of,
    drive,
    intent_of,
    pin,
    plan_document,
    reviewed_release,
    stop_target,
    successor_candidate,
)

from codex_harness.adapters.git import GitCommandError
from codex_harness.adapters.host_delivery import canary_request_file
from codex_harness.application.host_delivery import BUCKET_INTENTS, BUCKET_PLANS, HostDelivery
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AWAITING_CI,
    BLOCKED,
    FAILED,
    MERGE_INTENDED,
    MERGED,
    PUBLISHING,
    WITHDRAWN,
    DeliveryRefused,
)

MOVED = "7" * 40            # another writer's commit on main (labelled)
EVIDENCE = "sha256:" + "e" * 64


def ff_build(tmp_path, **kwargs):
    return build(tmp_path, github=FakeGitHub(fast_forward=True), **kwargs)


def second_plan(system, *, base=None, expected=None, revision="5" * 40, plan_id="delivery-plan-2"):
    record = successor_candidate(system, revision=revision, branch="harness/two", task_id="two")
    if base is not None:
        record["base"] = base
    release = reviewed_release(system["store"], system["org"], record_candidate=record)
    plan = plan_document(release, plan_id=plan_id, expected=expected)
    system["delivery"].register(plan, pin(path="docs/zeus/operations/" + plan_id + ".json"))
    return plan


def tick_plan(system, plan_id, n=1):
    results = []
    for _ in range(n):
        results.append(system["delivery"].tick(plan_id))
        system["clock"].advance(1)
    return results


def intent(system, plan_id):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_INTENTS, plan_id)


def queue_row(system, release_id):
    with system["store"].transaction() as tx:
        return tx.get("release_queue", release_id)


def plan_row(system, plan_id):
    with system["store"].transaction() as tx:
        return tx.get(BUCKET_PLANS, plan_id)


# ----- D1/D2: the current candidate and main drift ---------------------------------------------------
def test_the_current_candidate_is_fast_forwarded_once_and_qualified(tmp_path):
    system = ff_build(tmp_path)
    results = drive(system, until=MERGED, limit=6)
    assert results[-1]["stage"] == MERGED, results[-1]
    github = system["github"]
    assert github.merges == 1 and github.main == REVISION and github.mainline == [REVISION]
    assert intent_of(system)["merged_revision"] == REVISION and github.qualifications == [REVISION]


def test_main_drift_before_publish_blocks_with_no_pr_and_no_ci(tmp_path):
    system = ff_build(tmp_path)
    system["github"].main = MOVED   # labelled: main moved after the review, before publication
    results = drive(system, until=AWAITING_CI, limit=4)
    assert results[-1]["stage"] == BLOCKED and results[-1]["reason_code"] == "reviewed_base_moved"
    assert intent_of(system)["previous_stage"] == PUBLISHING
    assert system["github"].publishes == 0 and system["github"].prs == {}


def test_main_drift_before_the_merge_blocks_and_leaves_main_to_its_writer(tmp_path):
    system = ff_build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    system["github"].main = MOVED   # labelled: root merged something else after CI passed
    blocked = system["delivery"].tick()
    assert blocked["stage"] == BLOCKED and blocked["reason_code"] == "reviewed_base_moved"
    assert system["github"].merges == 0 and system["github"].main == MOVED


@pytest.mark.parametrize("code", ["reviewed_base_moved", "merge_push_refused", "candidate_not_fast_forward"])
def test_a_definite_merge_refusal_blocks_with_its_own_code(tmp_path, code):
    system = ff_build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    system["github"].merge_refusal = code   # labelled: the server's (or the ancestry check's) refusal
    refused = system["delivery"].tick()
    assert refused["stage"] == BLOCKED and refused["reason_code"] == code
    assert system["github"].main == BASE and intent_of(system)["merged_revision"] is None


# ----- lost and unknown responses ---------------------------------------------------------------------------
def test_a_lost_push_response_is_recognized_from_main_and_never_pushed_again(tmp_path):
    system = ff_build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    system["github"].merge_error = GitCommandError("injected: push outcome unknown after the update")
    lost = system["delivery"].tick()
    assert lost["outcome"] == "unavailable" and lost["stage"] == MERGE_INTENDED
    assert system["github"].main == REVISION   # the effect happened
    system["github"].merge_error = None
    system["clock"].advance(120)
    # A RESTARTED controller over the same durable state reconciles R1 before anything else.
    restarted = HostDelivery(system["store"], system["org"], github=system["github"],
                             hosts=system["delivery"].hosts, canaries=system["delivery"].canaries,
                             clock=system["clock"], enabled=True, resume_seconds=0)
    recovered = restarted.tick()
    assert recovered["stage"] == MERGED and system["github"].merges == 1
    assert intent_of(system)["merged_revision"] == REVISION


def test_an_unknown_push_with_main_still_at_the_base_retries_only_through_the_fence(tmp_path):
    system = ff_build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    github = system["github"]
    original = github.merge

    def unknown(candidate, observed=None):   # labelled: the transport died before any update
        github.merges += 1
        raise GitCommandError("injected: push outcome unknown, remote untouched")
    github.merge = unknown
    assert system["delivery"].tick()["outcome"] == "unavailable" and github.main == BASE
    github.merge = original
    busy = system["delivery"].tick()   # the retry waits for the queue's own bounded backoff
    assert busy["outcome"] == "controller_busy" and busy["reason_code"] == "release_retry_not_due"
    system["clock"].advance(120)
    merged = system["delivery"].tick()
    assert merged["stage"] == MERGED and github.main == REVISION and github.mainline == [REVISION]


# ----- external effects -------------------------------------------------------------------------------------
def test_an_external_merge_of_the_same_tree_is_recognized_and_qualified_without_a_push(tmp_path):
    system = ff_build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    github = system["github"]
    github.pr = {**github.pr, "state": "MERGED", "merged_revision": MERGED_REVISION}   # labelled UI merge
    github.main = MERGED_REVISION
    merged = system["delivery"].tick()
    assert merged["stage"] == MERGED and github.merges == 0
    assert intent_of(system)["merged_revision"] == MERGED_REVISION


def test_an_external_merge_of_another_tree_stays_blocked(tmp_path):
    system = build(tmp_path, github=FakeGitHub(fast_forward=True, merged_tree="d" * 64))
    drive(system, until=MERGE_INTENDED, limit=4)
    github = system["github"]
    github.pr = {**github.pr, "state": "MERGED", "merged_revision": MERGED_REVISION}   # labelled UI merge
    github.main = MERGED_REVISION
    blocked = system["delivery"].tick()
    assert blocked["reason_code"] == "merged_tree_mismatch" and github.merges == 0


# ----- the existing gates before a NEW effect (owner review binding 3) -------------------------------------
def test_a_required_check_that_regressed_is_not_bypassed_by_the_fast_forward(tmp_path):
    system = ff_build(tmp_path)
    drive(system, until=MERGE_INTENDED, limit=4)
    system["github"].rows = [{"name": CHECK, "state": "failure"}]   # labelled: a re-run failed
    blocked = system["delivery"].tick()
    assert blocked["reason_code"] == "ci_check_failed" and system["github"].merges == 0


def test_a_missing_closed_or_moved_publication_is_refused_before_any_push(tmp_path):
    for mutate, code in ((lambda g: g.prs.clear(), "publication_missing"),
                         (lambda g: setattr(g, "pr", {**g.pr, "head": "6" * 40}), "ci_head_changed"),
                         (lambda g: setattr(g, "pr", {**g.pr, "state": "MERGED", "merged_revision": None}),
                          "publication_not_open")):
        system = ff_build(tmp_path / code)
        drive(system, until=MERGE_INTENDED, limit=4)
        mutate(system["github"])   # labelled provider fact
        blocked = system["delivery"].tick()
        assert blocked["reason_code"] == code and system["github"].merges == 0, code


def test_a_candidate_already_on_main_does_not_skip_its_required_checks(tmp_path):
    """Indirect recognition is recovery of an effect, never CI approval."""
    system = build(tmp_path, github=FakeGitHub(fast_forward=True, checks=((CHECK, "pending"),)))
    drive(system, until=AWAITING_CI, limit=3)
    system["github"].mainline.append(REVISION)   # labelled: someone pushed the candidate directly
    system["github"].main = REVISION
    waiting = system["delivery"].tick()
    assert waiting["stage"] == AWAITING_CI and waiting["reason_code"] == "ci_check_pending"


# ----- the predecessor binding (D2) and the H1/H2 shape (D4 counterpart) ----------------------------------
@binds_a_runtime
def test_a_second_plan_waits_while_the_first_is_merged_and_is_refused_once_it_is_active(tmp_path):
    system = ff_build(tmp_path)
    try:
        drive(system, until=MERGED, limit=6)
        plan2 = second_plan(system)                 # cut on the new main; expected predecessor null (H2)
        results = tick_plan(system, plan2["plan_id"], 4)
        waiting = results[-1]
        assert (waiting["stage"], waiting["outcome"], waiting["reason_code"]) == (
            MERGE_INTENDED, "pending", "predecessor_in_flight"), results
        assert waiting["attempts"] == 0 and system["github"].merges == 1
        assert drive(system)[-1]["stage"] == ACTIVE   # the first delivery settles the host (D1)
        refused = tick_plan(system, plan2["plan_id"])[-1]
        assert refused["stage"] == BLOCKED and refused["reason_code"] == "descriptor_predecessor_moved"
        assert system["github"].merges == 1 and system["github"].main == REVISION
    finally:
        stop_target(system)


def test_an_old_second_plan_on_the_stale_base_never_publishes(tmp_path):
    """The exact H2 state: registered on the first candidate's base after the first merged."""
    system = ff_build(tmp_path)
    drive(system, until=MERGED, limit=6)
    plan2 = second_plan(system, base=BASE)
    blocked = tick_plan(system, plan2["plan_id"], 2)[-1]
    assert blocked["reason_code"] == "reviewed_base_moved" and system["github"].publishes == 1


def test_a_failed_predecessor_with_an_unverified_descriptor_stops_a_new_merge(tmp_path):
    """Owner review: a terminal `failed` intent is not safe-to-switch evidence."""
    system = ff_build(tmp_path)
    system["delivery"].tick()   # plan 1 has an intent
    with system["store"].transaction() as tx:   # labelled: plan 1 failed after binding a descriptor
        row = tx.get(BUCKET_INTENTS, "delivery-plan-1")
        tx.put(BUCKET_INTENTS, row["id"], {**row, "stage": FAILED, "descriptor": {"schema": "fixture"},
                                           "rollback": {"requested": True, "verified": False}})
    plan2 = second_plan(system)
    waiting = tick_plan(system, plan2["plan_id"], 4)[-1]
    assert waiting["reason_code"] == "predecessor_in_flight" and system["github"].merges == 0
    with system["store"].transaction() as tx:   # labelled: its rollback was proven after all
        row = tx.get(BUCKET_INTENTS, "delivery-plan-1")
        tx.put(BUCKET_INTENTS, row["id"], {**row, "rollback": {"requested": True, "verified": True}})
    merged = tick_plan(system, plan2["plan_id"])[-1]
    assert merged["stage"] == MERGED and system["github"].merges == 1


# ----- D3: owner withdrawal ---------------------------------------------------------------------------------
def stale_pair(tmp_path):
    """H1 at awaiting_ci with an OPEN PR and H2 registered without an intent, both on the old base, then
    main moves (root's merge of something else): exactly the recorded aibox state."""
    system = build(tmp_path, github=FakeGitHub(fast_forward=True, checks=((CHECK, "pending"),)))
    drive(system, until=AWAITING_CI, limit=3)
    plan2 = second_plan(system, base=BASE)
    request = Path(system["target"]["state_dir"]) / canary_request_file(plan2["plan_id"])
    request.parent.mkdir(parents=True, exist_ok=True)   # the plan's filed canary request, kept inert
    request.write_text(json.dumps({"plan_id": plan2["plan_id"], "labelled": "fixture request"}), "utf-8")
    system["github"].main = MOVED   # labelled
    return system, plan2, request


def test_withdrawal_retires_both_stale_plans_and_keeps_every_record(tmp_path):
    system, plan2, request = stale_pair(tmp_path)
    delivery, github = system["delivery"], system["github"]
    plans = {p: deepcopy(plan_row(system, p)) for p in ("delivery-plan-1", plan2["plan_id"])}
    prs, request_bytes = deepcopy(github.prs), request.read_bytes()
    h1 = delivery.withdraw("delivery-plan-1", plans["delivery-plan-1"]["plan_sha256"], "reviewed_base_moved", EVIDENCE)
    assert h1["withdrawn"] is True and h1["cached"] is False and h1["queue"] == WITHDRAWN
    assert h1["withdrawal"]["previous_stage"] == AWAITING_CI and h1["withdrawal"]["main_effect"] == "none"
    assert h1["withdrawal"]["observed"]["main"] == MOVED and h1["withdrawal"]["observed"]["pr_state"] == "OPEN"
    assert h1["next_action"] == "owner_requalify_candidate"
    h2 = delivery.withdraw(plan2["plan_id"], plans[plan2["plan_id"]]["plan_sha256"], "reviewed_base_moved", EVIDENCE)
    assert h2["withdrawal"]["previous_stage"] == "registered" and h2["withdrawal"]["observed"]["pr_state"] is None
    assert queue_row(system, system["release"]["id"])["status"] == WITHDRAWN
    assert queue_row(system, plan2["release_id"])["status"] == WITHDRAWN
    # Immutable: plan rows, the PR and the plan's canary request are exactly as they were.
    assert {p: plan_row(system, p) for p in plans} == plans
    assert github.prs == prs and github.publishes == 1 and github.merges == 0
    assert request.read_bytes() == request_bytes
    # Replays are cached; another reason or evidence for a withdrawn plan is a conflict.
    before = deepcopy(system["store"].data)
    again = delivery.withdraw("delivery-plan-1", plans["delivery-plan-1"]["plan_sha256"], "reviewed_base_moved",
                              EVIDENCE)
    assert again["cached"] is True and system["store"].data == before
    for reason, evidence in (("descriptor_predecessor_moved", EVIDENCE), ("reviewed_base_moved", "sha256:" + "f" * 64)):
        with pytest.raises(DeliveryRefused) as conflict:
            delivery.withdraw("delivery-plan-1", plans["delivery-plan-1"]["plan_sha256"], reason, evidence)
        assert conflict.value.reason_code == "withdrawal_conflict"
    # Restart: a new controller never selects them and touches nothing external.
    restarted = HostDelivery(system["store"], system["org"], github=github, hosts=delivery.hosts,
                             canaries=delivery.canaries, clock=system["clock"], enabled=True, resume_seconds=0)
    idle = restarted.tick()
    assert idle["outcome"] == "idle" and idle["blocked"] == {"delivery-plan-1": WITHDRAWN, plan2["plan_id"]: WITHDRAWN}
    assert github.publishes == 1 and github.merges == 0
    status = restarted.status()
    assert status["counts"] == {WITHDRAWN: 2}
    assert {view["withdrawal"]["reason_code"] for view in status["deliveries"]} == {"reviewed_base_moved"}


def test_withdrawal_refusals_write_nothing(tmp_path):
    system, plan2, _ = stale_pair(tmp_path)
    delivery, github = system["delivery"], system["github"]
    sha = plan_row(system, "delivery-plan-1")["plan_sha256"]

    def refused(code, *args):
        before = deepcopy(system["store"].data)
        with pytest.raises(DeliveryRefused) as raised:
            delivery.withdraw(*args)
        assert raised.value.reason_code == code
        assert system["store"].data == before, code

    refused("plan_unregistered", "no-such-plan", sha, "reviewed_base_moved", EVIDENCE)
    refused("withdraw_plan_mismatch", "delivery-plan-1", "0" * 64, "reviewed_base_moved", EVIDENCE)
    refused("withdraw_reason_unsupported", "delivery-plan-1", sha, "because", EVIDENCE)
    refused("withdraw_evidence_invalid", "delivery-plan-1", sha, "reviewed_base_moved", "decision.md")
    github.observe_error = ConnectionError("injected: GitHub unreachable")
    refused("withdraw_unobservable", "delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)
    github.observe_error = None
    github.main = BASE   # labelled: main is the reviewed base again
    refused("withdraw_not_stale", "delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)
    refused("withdraw_not_stale", "delivery-plan-1", sha, "descriptor_predecessor_moved", EVIDENCE)
    refused("withdraw_not_stale", "delivery-plan-1", sha, "merged_tree_mismatch", EVIDENCE)
    github.mainline.append(REVISION)   # labelled: the candidate is on main after all
    github.main = REVISION
    refused("withdraw_merge_observed", "delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)


def test_withdrawal_takes_the_same_fence_a_tick_takes(tmp_path):
    system, _, _ = stale_pair(tmp_path)
    held = ReleaseQueue(system["store"]).claim(now=system["delivery"]._now())   # another controller
    assert held is not None
    before = deepcopy(system["store"].data)
    with pytest.raises(DeliveryRefused) as busy:
        system["delivery"].withdraw("delivery-plan-1", plan_row(system, "delivery-plan-1")["plan_sha256"],
                                    "reviewed_base_moved", EVIDENCE)
    assert busy.value.reason_code == "controller_lease_held" and system["store"].data == before


def test_a_touched_host_is_never_withdrawn(tmp_path):
    system = ff_build(tmp_path)
    system["delivery"].tick()
    with system["store"].transaction() as tx:   # labelled: the delivery already bound a descriptor
        row = tx.get(BUCKET_INTENTS, "delivery-plan-1")
        tx.put(BUCKET_INTENTS, row["id"], {**row, "stage": BLOCKED, "descriptor": {"schema": "fixture"}})
    with pytest.raises(DeliveryRefused) as touched:
        system["delivery"].withdraw("delivery-plan-1", plan_row(system, "delivery-plan-1")["plan_sha256"],
                                    "reviewed_base_moved", EVIDENCE)
    assert touched.value.reason_code == "withdraw_host_touched"


def test_a_crash_between_the_withdrawal_and_the_queue_finish_is_completed_by_the_replay(tmp_path):
    system, _, _ = stale_pair(tmp_path)
    delivery = system["delivery"]
    sha = plan_row(system, "delivery-plan-1")["plan_sha256"]
    finish = delivery.queue.finish

    def crash(*args, **kwargs):
        raise RuntimeError("injected: controller died after the intent commit")
    delivery.queue.finish = crash
    with pytest.raises(RuntimeError):
        delivery.withdraw("delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)
    assert intent(system, "delivery-plan-1")["stage"] == WITHDRAWN
    assert queue_row(system, system["release"]["id"])["status"] == "running"
    delivery.queue.finish = finish
    system["clock"].advance(3600)   # the dead controller's lease has expired
    replay = delivery.withdraw("delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)
    assert replay["cached"] is True and replay["queue"] == WITHDRAWN
    assert queue_row(system, system["release"]["id"])["status"] == WITHDRAWN
    assert system["github"].publishes == 1 and system["github"].merges == 0


def test_a_recorded_tree_mismatch_is_retired_only_as_what_it_is(tmp_path):
    """The exception keeps its merge in the record and is never labelled a no-GitHub-effect withdrawal."""
    system = build(tmp_path, github=FakeGitHub(merged_tree="d" * 64))
    blocked = drive(system, until=MERGED, limit=6)[-1]
    assert blocked["reason_code"] == "merged_tree_mismatch"
    sha = plan_row(system, "delivery-plan-1")["plan_sha256"]
    with pytest.raises(DeliveryRefused) as observed:
        system["delivery"].withdraw("delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)
    assert observed.value.reason_code == "withdraw_merge_observed"
    retired = system["delivery"].withdraw("delivery-plan-1", sha, "merged_tree_mismatch", EVIDENCE)
    assert retired["withdrawal"]["main_effect"] == "merged"
    assert retired["withdrawal"]["merged_revision"] == MERGED_REVISION == intent(system, "delivery-plan-1")[
        "merged_revision"]
    assert retired["queue"] is None and descriptor_of(system) is None


def test_a_stale_predecessor_binding_is_withdrawn_under_its_own_reason(tmp_path):
    system = build(tmp_path, github=FakeGitHub(fast_forward=True), plan_overrides={"expected": "4" * 64})
    blocked = drive(system, until=MERGED, limit=6)[-1]
    assert blocked["reason_code"] == "descriptor_predecessor_moved"
    sha = plan_row(system, "delivery-plan-1")["plan_sha256"]
    with pytest.raises(DeliveryRefused) as fresh:
        system["delivery"].withdraw("delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)
    assert fresh.value.reason_code == "withdraw_not_stale"   # main IS still the reviewed base
    retired = system["delivery"].withdraw("delivery-plan-1", sha, "descriptor_predecessor_moved", EVIDENCE)
    assert retired["withdrawal"]["previous_stage"] == BLOCKED and retired["withdrawal"]["main_effect"] == "none"
    assert system["github"].merges == 0 and TREE == system["release"]["candidate"]["tree"]


# ----- isolated PostgreSQL ----------------------------------------------------------------------------------
@pytest.mark.integration
def test_withdrawal_and_pre_merge_bindings_hold_on_an_isolated_postgresql(isolated_pgstore, tmp_path):
    """The real advisory-lock transaction boundary for the new paths, against a disposable schema."""
    system = build(tmp_path, store=isolated_pgstore, github=FakeGitHub(fast_forward=True,
                                                                        checks=((CHECK, "pending"),)))
    drive(system, until=AWAITING_CI, limit=3)
    system["github"].main = MOVED   # labelled
    sha = plan_row(system, "delivery-plan-1")["plan_sha256"]
    retired = system["delivery"].withdraw("delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)
    assert retired["queue"] == WITHDRAWN and intent(system, "delivery-plan-1")["stage"] == WITHDRAWN
    assert system["delivery"].withdraw("delivery-plan-1", sha, "reviewed_base_moved", EVIDENCE)["cached"] is True
    assert system["delivery"].tick()["outcome"] == "idle"
