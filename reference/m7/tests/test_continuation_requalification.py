"""INV-CONTINUATION-001 owner delivery requalification (aibox SPEC s15, D5).

The world of test_continuation: real MemoryStores (the Fleet control store and one lane store), the
real `Fleet`, `Operation`, `Workflow`, `WorkerSessions` and `ResearchEvidence` over a real temporary
content-addressed store. The lane's worker/lead executor is the LABELLED `FakeExecutor` fixture and
the conductor port the LABELLED `ConductorFixture`. The HostDelivery row the owner withdrew is written
into the lane store as `HostDelivery.withdraw` shapes it (labelled). The remote-main port is the
LABELLED `Mainline` double: it answers what `git ls-remote` and the lane repository would. No model,
provider, network, GitHub or production store is touched, and nothing here is a live requalification.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from copy import deepcopy

import pytest
from test_continuation import BASE, CANDIDATE, World, accepted_item, only

from codex_harness.adapters import continuation as adapter
from codex_harness.adapters.continuation_cli import add_parser
from codex_harness.application.continuation import BUCKET_INTENTS, LANE_BINDINGS
from codex_harness.domain import continuation as dc
from codex_harness.domain.model import digest

MAIN = "9" * 40                   # the remote main the change is re-derived on (labelled)
PLAN_ID, PLAN_SHA = "own-h1-plan", "5" * 64
TREE = "7" * 40                   # the fixture worker's candidate tree (test_operation.FakeExecutor)
RATIONALE = "Owner decision: the reviewed base moved; re-derive the accepted change on the current main.\n"


class Mainline:
    """LABELLED double of the lane mainline port (`adapters.continuation.LaneMainline`). `goals` maps a
    revision to the goal blob digest there (default `goal_sha` at every revision)."""

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


def withdraw(world, release_id, *, stage="withdrawn", reason="reviewed_base_moved"):
    """The lane's HostDelivery intent as `HostDelivery.withdraw` leaves it (labelled)."""
    with world.lane.store.transaction() as tx:
        tx.put("host_delivery_intents", PLAN_ID, {
            "id": PLAN_ID, "plan_id": PLAN_ID, "release_id": release_id, "target_id": "fleet-host",
            "revision": CANDIDATE, "stage": stage, "plan_sha256": PLAN_SHA, "updated_at": "t",
            "withdrawal": {"reason_code": reason, "evidence_ref": "sha256:" + "e" * 64, "main_effect": "none"}
            if stage == "withdrawn" else None})


def withdrawn_world(tmp_path, **kwargs):
    world = World(tmp_path, **kwargs)
    world.register()
    job = accepted_item(world)
    world.tick()
    world.tick()
    delivery = only(world.intents(), route=dc.DELIVERY)
    assert delivery["state"] == dc.AWAITING_OWNER
    withdraw(world, delivery["release_id"])
    rationale = world.artifacts.put(RATIONALE, "owner-rationale")["ref"]
    return world, job, delivery, rationale


def document(delivery, rationale, **overrides):
    return {"schema": dc.REQUALIFICATION_SCHEMA, "policy_id": "policy-1", "policy_sha256": delivery["policy_sha256"],
            "intent_id": delivery["id"], "family": delivery["family"], "release_id": delivery["release_id"],
            "candidate": {"revision": CANDIDATE, "tree": TREE, "base": BASE},
            "plan": {"plan_id": PLAN_ID, "plan_sha256": PLAN_SHA}, "withdrawal_reason": "reviewed_base_moved",
            "main_revision": MAIN, "rationale_ref": rationale, **overrides}


def requalify(world, doc, mainline=None, **kwargs):
    return world.controller.requalify_delivery(doc, pin_sha256=kwargs.get("pin", world.pin["sha256"]),
                                               runtime=kwargs.get("runtime", world.runtime),
                                               mainline=mainline or Mainline())


def lane_snapshot(world):
    return deepcopy(world.lane.store.data)


def kept_rows(world, delivery, job):
    """Digests of the rows a failed replacement must never change: the superseded intent, the withdrawn
    lane delivery, the origin job and the stored owner document."""
    with world.lane.store.transaction() as tx:
        lane_delivery = tx.get("host_delivery_intents", PLAN_ID)
    with world.control.transaction() as tx:
        stored = tx.get("continuation_requalifications", delivery["id"])
    return {"delivery": digest(world.intents()[delivery["id"]]), "lane_delivery": digest(lane_delivery),
            "origin": digest(world.jobs()[job]), "document": digest(stored)}


# ----- the named wait, then the owner's document ------------------------------------------------------------
def test_a_withdrawn_delivery_is_a_named_wait_that_writes_nothing(tmp_path):
    world, _, delivery, _ = withdrawn_world(tmp_path)
    before = deepcopy(world.control.data)
    for controller in (world.controller, world.build()):   # restart: the same wait, no write
        result = world.tick(controller=controller)
        assert {"subject": delivery["id"], "reason_code": "delivery_withdrawn", "next_owner": "operator"} \
            in result["skipped"]
    assert world.control.data == before
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER


def test_requalification_supersedes_the_intent_and_reserves_one_fresh_operation_on_main(tmp_path):
    world, job, delivery, rationale = withdrawn_world(tmp_path)
    lane_before = lane_snapshot(world)
    result = requalify(world, document(delivery, rationale))
    assert result["requalified"] is True and result["cached"] is False
    intents = world.intents()
    old = intents[delivery["id"]]
    new = intents[dc.requalification_id(delivery["id"])]
    # The old intent: terminal, linked, its snapshot and history kept (never a TRANSITIONS edge).
    assert old["state"] == dc.SUPERSEDED and old["superseded_by"] == new["id"]
    assert old["history"][:-1] == delivery["history"] and old["history"][-1]["previous"] == dc.AWAITING_OWNER
    assert dc.SUPERSEDED not in dc.TRANSITIONS[dc.AWAITING_OWNER]
    # The new intent: same family, origin and authorization; explicit lineage; nothing external yet.
    assert (new["route"], new["state"]) == (dc.REQUALIFICATION, dc.INTENDED)
    assert new["family"] == delivery["family"] and new["origin_job"] == job
    assert new["predecessor_intent"] == delivery["id"] and new["authorization"] == delivery["authorization"]
    assert new["successor_job"] == dc.successor_id(new["id"]) == result["successor_job"]
    origin = world.jobs()[job]["manifest"]
    manifest = new["manifest"]
    assert manifest["base_revision"] == MAIN != origin["base_revision"]
    for key in ("goal", "budget", "claude"):
        assert manifest[key] == origin[key], key
    for key in ("allowed_paths", "acceptance_criteria"):
        assert manifest["plan"][key] == origin["plan"][key], key
    assert manifest["plan"]["objective"].endswith(origin["plan"]["objective"])
    assert "withdrawal_reason=reviewed_base_moved" in manifest["plan"]["objective"]
    assert new["goal"] == {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit", "base_revision": MAIN,
                           "bytes": 3}
    binding = new["binding"]
    assert (binding["route"], binding["session"], binding["workspace"]) == (dc.REQUALIFICATION, None, None)
    assert binding["predecessor"]["intent_id"] == delivery["id"] and dc.validate_binding(binding) == binding
    assert world.lane.store.data == lane_before, "the lane (plan, action, request, withdrawal) is untouched"
    assert world.jobs().keys() == {job}, "no admission happens in the owner command"
    # Replay: cached, nothing written; any other document for the intent: a conflict, nothing written.
    snapshot = deepcopy(world.control.data)
    assert requalify(world, document(delivery, rationale))["cached"] is True
    other = world.artifacts.put(RATIONALE + "second\n", "owner-rationale")["ref"]
    with pytest.raises(dc.ContinuationRefused) as conflict:
        requalify(world, document(delivery, other))
    assert conflict.value.reason_code == "requalification_conflict" and world.control.data == snapshot
    status = world.controller.status("policy-1")
    assert status["requalifications"][0]["requalification_intent"] == new["id"]
    projected = {row["id"]: row for row in status["intents"]}
    assert projected[delivery["id"]]["superseded_by"] == new["id"]
    assert "requalification" in projected[delivery["id"]]["next_action"]


def test_the_existing_path_admits_it_once_on_the_new_base_and_the_candidate_is_reviewed_again(tmp_path):
    world, job, delivery, rationale = withdrawn_world(tmp_path)
    requalify(world, document(delivery, rationale))
    new_id = dc.requalification_id(delivery["id"])
    world.tick()
    new = world.intents()[new_id]
    successor = new["successor_job"]
    assert new["state"] == dc.ADMITTED
    admitted = world.jobs()[successor]
    assert admitted["manifest"]["base_revision"] == MAIN and admitted["goal"]["base_revision"] == MAIN
    assert world.binding(successor) == new["binding"]
    snapshot = deepcopy(world.control.data)
    world.tick()
    world.tick(controller=world.build())
    assert world.control.data == snapshot and len(world.jobs()) == 2, "duplicate admission: the same id once"
    # The operation claim turns the manifest base into the assignment's base (the executor prepares the
    # implementation workspace at `where.revision`; no continued workspace or session is attached).
    successor_job, receipt = world.run_next(verdict=True)
    assert successor_job == successor and receipt["status"] == "accepted"
    with world.lane.store.transaction() as tx:
        operation = tx.get("operations", successor)
        assignment = tx.get("outbox", operation["assignment_message_id"])["message"]
    assert assignment["where"]["revision"] == MAIN
    assert assignment["what"]["details"]["continuation"]["workspace"] is None
    world.tick()
    world.tick()
    intents = world.intents()
    assert intents[new_id]["state"] == dc.COMPLETED
    conducted = only(intents, route=dc.CONDUCTOR, origin_job=successor)
    assert conducted["family"] == delivery["family"] and conducted["predecessor_intent"] == new_id
    # The origin job is never re-routed and the superseded intent stays as it was.
    assert intents[delivery["id"]]["state"] == dc.SUPERSEDED
    assert len([row for row in intents.values() if row["origin_job"] == job and row["route"] == dc.DELIVERY]) == 1


def test_a_failed_replacement_is_corrected_on_the_same_new_base_and_the_old_rows_never_change(tmp_path):
    world, job, delivery, rationale = withdrawn_world(tmp_path, max_corrections=1)
    requalify(world, document(delivery, rationale))
    world.tick()
    old = kept_rows(world, delivery, job)
    successor, receipt = world.run_next(verdict=False)
    assert receipt["status"] == "rejected"
    world.await_review(successor)
    world.tick()
    correction = only(world.intents(), route=dc.CORRECTION)
    # The requalification is not a failure successor: the one allowed correction is still available.
    assert correction["state"] == dc.ADMITTED and correction["origin_job"] == successor
    assert world.jobs()[correction["successor_job"]]["manifest"]["base_revision"] == MAIN
    assert dc.capacity_count(list(world.intents().values()), "policy-1", delivery["family"]) == 1
    assert dc.prior_failures(list(world.intents().values()), delivery["family"]) == [correction["evidence_sha256"]]
    assert kept_rows(world, delivery, job) == old


def test_requalification_from_a_paused_family_releases_only_that_hold(tmp_path):
    world = World(tmp_path)
    world.register()
    accepted_item(world)
    world.tick()
    world.tick()
    delivery = only(world.intents(), route=dc.DELIVERY)
    withdraw(world, delivery["release_id"], stage="blocked")
    world.tick()
    paused = only(world.intents(), route=dc.DELIVERY)
    assert paused["state"] == dc.PAUSED and dc.blocked_families(list(world.intents().values()))
    withdraw(world, delivery["release_id"])   # the owner withdrew the blocked, untouched delivery
    rationale = world.artifacts.put(RATIONALE, "owner-rationale")["ref"]
    requalify(world, document(paused, rationale))
    assert dc.blocked_families(list(world.intents().values())) == {}
    world.tick()
    assert world.intents()[dc.requalification_id(delivery["id"])]["state"] == dc.ADMITTED


# ----- refusals: named, and nothing is written -----------------------------------------------------------------
REFUSALS = {
    "requalification_unverified": dict(pin=None),
    "requalification_policy_foreign": dict(doc={"policy_sha256": "0" * 64}),
    "requalification_intent_unknown": dict(doc={"intent_id": "0" * 64}),
    "requalification_intent_mismatch": dict(doc={"family": "other-family"}),
    "requalification_plan_mismatch": dict(doc={"plan": {"plan_id": PLAN_ID, "plan_sha256": "6" * 64}}),
    "requalification_reason_mismatch": dict(doc={"withdrawal_reason": "descriptor_predecessor_moved"}),
    "requalification_candidate_mismatch": dict(doc={"candidate": {"revision": CANDIDATE, "tree": TREE,
                                                                  "base": "1" * 40}}),
    "requalification_main_changed": dict(mainline=Mainline(main="8" * 40)),
    "requalification_main_missing": dict(mainline=Mainline(present=False)),
    "requalification_main_not_moved": dict(doc={"main_revision": BASE}, mainline=Mainline(main=BASE)),
    "requalification_goal_changed": dict(mainline=Mainline(goal_sha="0" * 64)),
    "requalification_main_unreadable": dict(mainline=Mainline(error=subprocess.TimeoutExpired("git", 60))),
    "requalification_rationale_missing": dict(doc={"rationale_ref": "sha256:" + "0" * 64}),
    "image_changed": dict(runtime=lambda lane: {"image": "other@sha256:" + "0" * 64, "profile": "worker-v1",
                                                "session_archive_sha256": "d" * 64}),
    "requalification_invalid": dict(doc={"main_revision": "HEAD"}),
    "requalification_reason_unsupported": dict(doc={"withdrawal_reason": "because"}),
}


@pytest.mark.parametrize("code", sorted(REFUSALS))
def test_every_unproven_binding_refuses_by_name_and_writes_nothing(tmp_path, code):
    world, _, delivery, rationale = withdrawn_world(tmp_path)
    case = REFUSALS[code]
    control, lane = deepcopy(world.control.data), lane_snapshot(world)
    kwargs = {key: case[key] for key in ("pin", "runtime") if key in case}
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(delivery, rationale, **case.get("doc", {})), case.get("mainline"), **kwargs)
    assert refused.value.reason_code == code
    assert world.control.data == control and world.lane.store.data == lane


def test_a_plan_that_was_not_withdrawn_is_never_requalified(tmp_path):
    world, _, delivery, rationale = withdrawn_world(tmp_path)
    withdraw(world, delivery["release_id"], stage="awaiting_ci")
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(delivery, rationale))
    assert refused.value.reason_code == "requalification_plan_not_withdrawn"
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER


def test_an_intent_that_moved_during_verification_commits_nothing(tmp_path):
    world, _, delivery, rationale = withdrawn_world(tmp_path)

    class Racing(Mainline):
        def remote_main(self):   # labelled: another writer moves the intent between read and commit
            with world.control.transaction() as tx:
                row = tx.get(BUCKET_INTENTS, delivery["id"])
                tx.put(BUCKET_INTENTS, row["id"], {**row, "version": row["version"] + 1})
            return super().remote_main()
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(delivery, rationale), Racing())
    assert refused.value.reason_code == "requalification_intent_changed"
    assert dc.requalification_id(delivery["id"]) not in world.intents()


def test_a_second_requalification_waits_while_the_family_has_an_open_one(tmp_path):
    world, _, delivery, rationale = withdrawn_world(tmp_path)
    requalify(world, document(delivery, rationale))
    twin = {**delivery, "id": "1" * 64, "state": dc.AWAITING_OWNER}
    with world.control.transaction() as tx:   # labelled: another delivery intent of the same family
        tx.put(BUCKET_INTENTS, twin["id"], twin)
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(twin, rationale, intent_id=twin["id"]))
    assert refused.value.reason_code == "requalification_family_open"


def test_a_crash_between_withdrawal_and_requalification_is_completed_by_the_owner_once(tmp_path):
    world, _, delivery, rationale = withdrawn_world(tmp_path)
    for _ in range(3):   # the controller restarts any number of times in between
        world.tick(controller=world.build())
    assert only(world.intents(), route=dc.DELIVERY)["state"] == dc.AWAITING_OWNER
    first = requalify(world, document(delivery, rationale))
    again = world.build().requalify_delivery(document(delivery, rationale), pin_sha256=world.pin["sha256"],
                                             runtime=world.runtime, mainline=Mainline())
    assert (first["cached"], again["cached"]) == (False, True)
    assert len([row for row in world.intents().values() if row["route"] == dc.REQUALIFICATION]) == 1


# ----- the route-set audit (every SUCCESSOR_ROUTES use has an explicit decision) ------------------------------
def test_the_requalification_route_is_admitting_but_never_a_failure_successor():
    assert dc.REQUALIFICATION in dc.ROUTES and dc.REQUALIFICATION in dc.ADMITTING_ROUTES
    assert dc.REQUALIFICATION not in dc.SUCCESSOR_ROUTES and dc.REQUALIFICATION not in dc.FAILURE_ROUTES
    for state in (dc.INTENDED, dc.PUBLISHED, dc.ADMITTED, dc.RETURNED):
        assert (dc.REQUALIFICATION, state) in dc.RESUME
    assert dc.ROUTE_STATES[dc.DELIVERY][-1] == dc.SUPERSEDED and not dc.TRANSITIONS[dc.SUPERSEDED]
    assert dc.SUPERSEDED not in dc.OPEN_STATES and dc.SUPERSEDED not in dc.BLOCKING_STATES
    rows = [{"family": "f", "route": dc.REQUALIFICATION, "state": dc.ADMITTED, "policy_id": "p", "created_at": "1",
             "id": "r", "evidence_sha256": "e"}]
    assert dc.capacity_count(rows, "p", "f") == 0 and dc.prior_failures(rows, "f") == []
    with pytest.raises(dc.ContinuationRefused):
        dc.successor_manifest({}, dc.REQUALIFICATION, "x", {})


def test_ownership_reconciliation_stays_a_failure_successor_repair(tmp_path):
    world, _, delivery, rationale = withdrawn_world(tmp_path)
    requalify(world, document(delivery, rationale))
    world.tick()
    with pytest.raises(dc.ContinuationRefused) as refused:
        world.controller.reconcile_ownership(dc.requalification_id(delivery["id"]))
    assert refused.value.reason_code == "ownership_intent_invalid"


def test_a_tampered_stored_document_stops_the_next_effect(tmp_path):
    world, _, delivery, rationale = withdrawn_world(tmp_path)
    requalify(world, document(delivery, rationale))
    with world.control.transaction() as tx:   # labelled tamper of the stored owner document
        row = tx.get("continuation_requalifications", delivery["id"])
        tx.put("continuation_requalifications", row["id"], {**row, "document": {**row["document"], "main_revision": "8" * 40}})
    result = world.tick()
    assert any(skip["reason_code"] == "requalification_corrupt" for skip in result["skipped"])
    new = world.intents()[dc.requalification_id(delivery["id"])]
    assert new["state"] == dc.INTENDED and world.binding(new["successor_job"]) is None


# ----- R2: one open requalification per family, rechecked inside the commit ----------------------------------
def test_two_intents_of_one_family_interleaved_during_the_mainline_read_commit_only_one(tmp_path):
    """Owner review R2 (injected ordering, not a production race claim): the second delivery intent of the
    family is requalified while the first request is between its checks and its commit."""
    world, _, delivery, rationale = withdrawn_world(tmp_path)
    twin = {**delivery, "id": "1" * 64, "state": dc.AWAITING_OWNER}
    with world.control.transaction() as tx:   # labelled: another delivery intent of the same family
        tx.put(BUCKET_INTENTS, twin["id"], twin)
    won = {}

    class Interleaved(Mainline):
        def remote_main(self):
            if self.reads == 0:
                won.update(requalify(world, document(twin, rationale, intent_id=twin["id"])))
                won["control"] = deepcopy(world.control.data)
            return super().remote_main()
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(delivery, rationale), Interleaved())
    assert refused.value.reason_code == "requalification_family_open"
    assert won["requalified"] is True and won["cached"] is False
    # Nothing of the refused request was written: no document, no supersession, no successor.
    assert world.control.data == won["control"]
    intents = world.intents()
    assert intents[delivery["id"]] == delivery and dc.requalification_id(delivery["id"]) not in intents
    assert [row["predecessor_intent"] for row in intents.values() if row["route"] == dc.REQUALIFICATION] == [twin["id"]]
    # The winner still replays; the loser keeps refusing while the family's requalification is open.
    assert requalify(world, document(twin, rationale, intent_id=twin["id"]))["cached"] is True
    with pytest.raises(dc.ContinuationRefused) as again:
        requalify(world, document(delivery, rationale))
    assert again.value.reason_code == "requalification_family_open"


# ----- R1: an owner-reviewed goal migration (optional strict block of the same document) ----------------------
NEW_GOAL = "3" * 64               # the goal blob digest at MAIN after the goal document changed (labelled)
REVIEW = "Codex goal-diff review (fixture text): criterion and scope unchanged.\n"
MIGRATION_ROW_KEYS = {"path", "criterion", "from", "to", "review_ref", "review"}


def moved_goal(**kwargs):
    """The goal document changed between the origin's base and MAIN (labelled double)."""
    return Mainline(goals={MAIN: NEW_GOAL, **kwargs.pop("goals", {})}, **kwargs)


def migration(review, **overrides):
    return {"path": "docs/GOAL.md", "criterion": "crit", "from_sha256": "b" * 64, "to_sha256": NEW_GOAL,
            "review_ref": review, **overrides}


def migrated_world(tmp_path, **kwargs):
    world, job, delivery, rationale = withdrawn_world(tmp_path, **kwargs)
    review = world.artifacts.put(REVIEW, "goal-review")["ref"]
    return world, job, delivery, rationale, review


def migrate(world, delivery, rationale, review, **overrides):
    return requalify(world, document(delivery, rationale, goal_migration=migration(review, **overrides)),
                     moved_goal())


OLD_SPEC = b"# Goal\n\ncriterion: crit\n"
NEW_SPEC = OLD_SPEC + b"\n## Later accepted history (appended, never erased)\n"


def real_goal_world(tmp_path, monkeypatch):
    """A REAL lane repository whose goal document changed between the origin's base and main (the
    ced2028 -> current-main shape), a real bare remote read with `ls-remote`, and the production
    `LaneMainline` port. Only the remote URL seam points at the local bare repository."""
    import hashlib

    from test_continuation import manifest as origin_manifest
    from test_git_workspace import git, repository

    from codex_harness.adapters.git import GitWorkspace
    from codex_harness.adapters.providers import packaged_policy
    from codex_harness.domain.operation import validate_manifest

    root = repository(tmp_path)
    (root / "docs").mkdir()
    (root / "docs" / "GOAL.md").write_bytes(OLD_SPEC)
    git(root, "add", ".")
    git(root, "commit", "-m", "goal at the origin's base")
    old = git(root, "rev-parse", "HEAD")
    (root / "docs" / "GOAL.md").write_bytes(NEW_SPEC)
    git(root, "commit", "-am", "later accepted history on the same goal document")
    new = git(root, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "--bare", "-q", str(root), str(remote))
    monkeypatch.setattr(GitWorkspace, "_remote_url", lambda self: str(remote))
    old_sha, new_sha = hashlib.sha256(OLD_SPEC).hexdigest(), hashlib.sha256(NEW_SPEC).hexdigest()
    world = World(tmp_path)
    world.document["goals"] = [{"path": "docs/GOAL.md", "sha256": old_sha, "criterion": "crit"}]
    world.register()
    origin = deepcopy(origin_manifest("op-1"))
    origin["base_revision"], origin["goal"]["sha256"] = old, old_sha
    world.fleet.enqueue("a", validate_manifest(origin, packaged_policy()),
                        {"path": "docs/GOAL.md", "sha256": old_sha, "criterion": "crit", "base_revision": old,
                         "bytes": len(OLD_SPEC)}, [])
    world.tick()
    job, receipt = world.run_next(verdict=True)
    assert receipt["status"] == "accepted"
    world.tick()
    world.tick()
    delivery = only(world.intents(), route=dc.DELIVERY)
    withdraw(world, delivery["release_id"])
    rationale = world.artifacts.put(RATIONALE, "owner-rationale")["ref"]
    review = world.artifacts.put(REVIEW, "goal-review")["ref"]
    port = adapter.LaneMainline({"lanes": [{"id": "a", "repository": str(root), "runtime": str(tmp_path / "rt"),
                                            "team": "t", "schema": "s"}]}, {"HARNESS_GITHUB_REPO": "owner/repo"})
    return {"world": world, "job": job, "delivery": delivery, "rationale": rationale, "review": review,
            "port": port, "root": root, "old": old, "new": new, "old_sha": old_sha, "new_sha": new_sha}


def test_a_real_goal_blob_that_changed_is_refused_without_and_rebound_with_an_owner_migration(tmp_path, monkeypatch):
    from codex_harness.adapters.fleet_recovery import _queued_bindings

    w = real_goal_world(tmp_path, monkeypatch)
    world, delivery, job = w["world"], w["delivery"], w["job"]
    control, lane = deepcopy(world.control.data), lane_snapshot(world)
    plain = document(delivery, w["rationale"], main_revision=w["new"])
    with pytest.raises(dc.ContinuationRefused) as refused:   # the equality gate stays: no silent rebinding
        requalify(world, plain, w["port"])
    assert refused.value.reason_code == "requalification_goal_changed"
    assert world.control.data == control and world.lane.store.data == lane
    block = migration(w["review"], from_sha256=w["old_sha"], to_sha256=w["new_sha"])
    result = requalify(world, {**plain, "goal_migration": block}, w["port"])
    assert result["requalified"] is True and result["cached"] is False
    # The durable comparison inputs: exact old/new revision, digest and size (hashes only, no review claim).
    assert result["goal_migration"] == {
        "path": "docs/GOAL.md", "criterion": "crit", "review_ref": w["review"], "review": "owner_reference_recorded",
        "from": {"revision": w["old"], "sha256": w["old_sha"], "bytes": len(OLD_SPEC)},
        "to": {"revision": w["new"], "sha256": w["new_sha"], "bytes": len(NEW_SPEC)}}
    intents = world.intents()
    new = intents[dc.requalification_id(delivery["id"])]
    origin = world.jobs()[job]
    assert new["goal"] == {"path": "docs/GOAL.md", "sha256": w["new_sha"], "criterion": "crit",
                           "base_revision": w["new"], "bytes": len(NEW_SPEC)}
    assert new["manifest"]["goal"] == {**origin["manifest"]["goal"], "sha256": w["new_sha"]}
    for key in ("budget", "claude"):
        assert new["manifest"][key] == origin["manifest"][key], key
    for key in ("allowed_paths", "acceptance_criteria"):
        assert new["manifest"]["plan"][key] == origin["manifest"]["plan"][key], key
    # The origin's pins and history are kept, not frozen away: the old intent and its authorization.
    assert new["authorization"] == delivery["authorization"]
    assert delivery["authorization"]["goal"]["sha256"] == w["old_sha"] == origin["goal"]["sha256"]
    assert intents[delivery["id"]]["history"][:-1] == delivery["history"]
    world.tick()
    admitted = world.jobs()[new["successor_job"]]
    assert world.intents()[new["id"]]["state"] == dc.ADMITTED
    assert admitted["goal"] == {"path": "docs/GOAL.md", "sha256": w["new_sha"], "criterion": "crit",
                                "base_revision": w["new"]}
    assert admitted["manifest"]["goal"]["sha256"] == w["new_sha"] and admitted["manifest"]["base_revision"] == w["new"]
    # The Fleet recovery reader's own check on the real repository: both jobs' goal bytes at their base.
    assert [row["goal_matches"] for row in _queued_bindings(str(w["root"]), [admitted, origin])] == [True, True]
    assert world.jobs()[job] == origin


GOAL_MIGRATION_REFUSALS = {
    "from_not_the_stored_binding": ("requalification_goal_migration_origin", dict(from_sha256="0" * 64), {}),
    "from_not_the_origin_base_blob": ("requalification_goal_migration_origin", {}, {BASE: "0" * 64}),
    "to_not_the_main_blob": ("requalification_goal_migration_target", dict(to_sha256="d" * 64), {}),
    "goal_unchanged_at_main": ("requalification_goal_migration_target", {}, {MAIN: "b" * 64}),
    "other_path": ("requalification_goal_migration_scope", dict(path="docs/OTHER.md"), {}),
    "wider_criterion": ("requalification_goal_migration_scope", dict(criterion="crit and more"), {}),
    "same_digests": ("requalification_invalid", dict(to_sha256="b" * 64), {}),
    "unknown_field": ("requalification_invalid", dict(allowed_paths=["docs/z.md"]), {}),
    "review_missing": ("requalification_goal_review_missing", dict(review_ref="sha256:" + "0" * 64), {}),
}


@pytest.mark.parametrize("case", sorted(GOAL_MIGRATION_REFUSALS))
def test_every_unproven_goal_migration_refuses_by_name_and_writes_nothing(tmp_path, case):
    code, overrides, goals = GOAL_MIGRATION_REFUSALS[case]
    world, _, delivery, rationale, review = migrated_world(tmp_path)
    control, lane = deepcopy(world.control.data), lane_snapshot(world)
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(delivery, rationale, goal_migration=migration(review, **overrides)),
                  moved_goal(goals=goals))
    assert refused.value.reason_code == code
    assert world.control.data == control and world.lane.store.data == lane


@pytest.mark.parametrize("block", ["null", "review_is_the_rationale", "not_a_ref", "unsafe_path"])
def test_a_malformed_goal_migration_block_is_invalid(tmp_path, block):
    world, _, delivery, rationale, review = migrated_world(tmp_path)
    value = {"null": None, "review_is_the_rationale": migration(rationale), "not_a_ref": migration("latest"),
             "unsafe_path": migration(review, path="../GOAL.md")}[block]
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(delivery, rationale, goal_migration=value), moved_goal())
    assert (refused.value.reason_code, refused.value.field) == ("requalification_invalid", "goal_migration")


def test_without_a_block_the_stored_document_and_successor_stay_the_unchanged_goal_shape(tmp_path):
    world, job, delivery, rationale = withdrawn_world(tmp_path)
    result = requalify(world, document(delivery, rationale))
    assert result["goal_migration"] is None
    with world.control.transaction() as tx:
        stored = tx.get("continuation_requalifications", delivery["id"])
    assert "goal_migration" not in stored["document"] and stored["goal_migration"] is None
    assert dc.validate_requalification(document(delivery, rationale)) == stored["document"]
    new = world.intents()[dc.requalification_id(delivery["id"])]
    assert new["manifest"]["goal"] == world.jobs()[job]["manifest"]["goal"]


def test_goal_migration_replay_is_cached_and_any_other_block_conflicts(tmp_path):
    world, _, delivery, rationale, review = migrated_world(tmp_path)
    first = migrate(world, delivery, rationale, review)
    assert first["cached"] is False and first["goal_migration"]["to"]["sha256"] == NEW_GOAL
    snapshot = deepcopy(world.control.data)
    assert migrate(world, delivery, rationale, review)["cached"] is True
    other = world.artifacts.put(REVIEW + "second reviewer\n", "goal-review")["ref"]
    for conflicting in (document(delivery, rationale),
                        document(delivery, rationale, goal_migration=migration(other))):
        with pytest.raises(dc.ContinuationRefused) as conflict:
            requalify(world, conflicting, moved_goal())
        assert conflict.value.reason_code == "requalification_conflict"
    assert world.control.data == snapshot
    assert world.controller.status("policy-1")["requalifications"][0]["goal_migration"] == first["goal_migration"]


def test_the_migrated_successor_is_conducted_under_its_new_goal_without_widening_scope(tmp_path):
    world, job, delivery, rationale, review = migrated_world(tmp_path)
    migrate(world, delivery, rationale, review)
    world.tick()
    successor, receipt = world.run_next(verdict=True)
    assert receipt["status"] == "accepted"
    world.tick()
    world.tick()
    conducted = only(world.intents(), route=dc.CONDUCTOR, origin_job=successor)
    origin = delivery["authorization"]
    assert conducted["authorization"]["goal"] == {"path": "docs/GOAL.md", "sha256": NEW_GOAL, "criterion": "crit"}
    for key in ("allowed_paths", "acceptance_criteria", "model", "repository", "lane", "policy_sha256", "pin_sha256"):
        assert conducted["authorization"][key] == origin[key], key
    assert conducted["family"] == delivery["family"]


def test_the_migrated_successor_is_corrected_on_its_new_goal_and_base(tmp_path):
    world, job, delivery, rationale, review = migrated_world(tmp_path, max_corrections=1)
    migrate(world, delivery, rationale, review)
    world.tick()
    successor, receipt = world.run_next(verdict=False)
    assert receipt["status"] == "rejected"
    world.await_review(successor)
    world.tick()
    correction = only(world.intents(), route=dc.CORRECTION)
    assert correction["state"] == dc.ADMITTED and correction["origin_job"] == successor
    corrected = world.jobs()[correction["successor_job"]]
    assert corrected["manifest"]["goal"]["sha256"] == NEW_GOAL == corrected["goal"]["sha256"]
    assert corrected["manifest"]["base_revision"] == MAIN
    origin = world.jobs()[job]["manifest"]
    assert corrected["manifest"]["plan"]["allowed_paths"] == origin["plan"]["allowed_paths"]
    assert corrected["manifest"]["budget"] == origin["budget"]


def tamper(world, delivery, change):
    with world.control.transaction() as tx:   # labelled tamper of the stored owner record
        row = tx.get("continuation_requalifications", delivery["id"])
        change(row)
        tx.put("continuation_requalifications", row["id"], row)


@pytest.mark.parametrize("where", ["document", "comparison"])
def test_a_tampered_goal_migration_stops_the_next_effect_and_extends_no_membership(tmp_path, where):
    world, _, delivery, rationale, review = migrated_world(tmp_path)
    migrate(world, delivery, rationale, review)
    if where == "document":
        tamper(world, delivery, lambda row: row["document"]["goal_migration"].update(to_sha256="d" * 64))
    else:
        tamper(world, delivery, lambda row: row["goal_migration"]["to"].update(sha256="d" * 64))
    result = world.tick()
    assert any(skip["reason_code"] == "requalification_corrupt" for skip in result["skipped"])
    new = world.intents()[dc.requalification_id(delivery["id"])]
    assert new["state"] == dc.INTENDED and world.binding(new["successor_job"]) is None
    with world.control.transaction() as tx:
        rows = tx.scan("continuation_requalifications")
    assert dc.migrated_goals("policy-1", delivery["policy_sha256"], rows) == []


def test_a_migrated_successor_is_routed_only_while_its_owner_record_is_intact(tmp_path):
    world, _, delivery, rationale, review = migrated_world(tmp_path)
    migrate(world, delivery, rationale, review)
    world.tick()
    successor, _ = world.run_next(verdict=True)
    with world.control.transaction() as tx:
        kept = tx.get("continuation_requalifications", delivery["id"])
    tamper(world, delivery, lambda row: row["document"].update(rationale_ref="sha256:" + "0" * 64))
    world.tick()
    world.tick()
    assert not [row for row in world.intents().values() if row["origin_job"] == successor], \
        "a job bound to an unrecorded goal digest is not this policy's work"
    with world.control.transaction() as tx:
        tx.put("continuation_requalifications", kept["id"], kept)
    world.tick()
    world.tick()
    assert only(world.intents(), route=dc.CONDUCTOR, origin_job=successor)["authorization"]["goal"]["sha256"] \
        == NEW_GOAL


def test_review_evidence_changed_after_recording_stops_the_next_effect(tmp_path):
    world, _, delivery, rationale, review = migrated_world(tmp_path)
    migrate(world, delivery, rationale, review)
    (tmp_path / "runtime" / "artifacts" / (review.split(":", 1)[1] + ".txt")).write_text("rewritten", encoding="utf-8")
    result = world.tick()
    assert any(skip["reason_code"] == "requalification_goal_review_corrupt" for skip in result["skipped"])
    new = world.intents()[dc.requalification_id(delivery["id"])]
    assert new["state"] == dc.INTENDED and world.binding(new["successor_job"]) is None


def test_goal_migration_interacts_with_family_exclusion_and_a_raced_intent(tmp_path):
    world, _, delivery, rationale, review = migrated_world(tmp_path)
    twin = {**delivery, "id": "1" * 64, "state": dc.AWAITING_OWNER}
    with world.control.transaction() as tx:
        tx.put(BUCKET_INTENTS, twin["id"], twin)
    migrate(world, twin, rationale, review)   # the twin's migration commits first
    with pytest.raises(dc.ContinuationRefused) as refused:
        migrate(world, delivery, rationale, review)
    assert refused.value.reason_code == "requalification_family_open"
    assert dc.requalification_id(delivery["id"]) not in world.intents()


# ----- the adapter and CLI -----------------------------------------------------------------------------------
def test_the_lane_mainline_port_reads_the_goal_digest_at_an_explicit_commit(tmp_path):
    from test_git_workspace import git, repository
    root = repository(tmp_path)
    (root / "docs").mkdir()
    (root / "docs" / "GOAL.md").write_text("goal", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "goal")
    head = git(root, "rev-parse", "HEAD")
    port = adapter.LaneMainline({"lanes": [{"id": "a", "repository": str(root), "runtime": str(tmp_path / "rt"),
                                            "team": "t", "schema": "s"}]}, {"HARNESS_GITHUB_REPO": "owner/repo"})("a")
    import hashlib
    assert port.commit_exists(head) and not port.commit_exists("0" * 40)
    assert port.goal(head, "docs/GOAL.md") == {"mode": "100644", "sha256": hashlib.sha256(b"goal").hexdigest(),
                                               "bytes": 4}
    assert port.goal(head, "docs/MISSING.md") is None


def test_the_cli_reads_a_bounded_owner_file_and_names_the_command(tmp_path):
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["continuation", "delivery-requalify", "--file", str(tmp_path / "doc.json")])
    assert args.continuation_command == "delivery-requalify"
    (tmp_path / "doc.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(dc.ContinuationRefused) as refused:
        adapter.read_requalification(tmp_path / "doc.json")
    assert refused.value.reason_code == "requalification_invalid"
    (tmp_path / "doc.json").write_text(json.dumps({"schema": dc.REQUALIFICATION_SCHEMA}), encoding="utf-8")
    assert adapter.read_requalification(tmp_path / "doc.json") == {"schema": dc.REQUALIFICATION_SCHEMA}
    with pytest.raises(dc.ContinuationRefused) as missing:
        adapter.read_requalification(tmp_path / "absent.json")
    assert missing.value.reason_code == "requalification_unreadable"
    assert LANE_BINDINGS == "continuation_bindings"


# ----- isolated PostgreSQL: the family recheck under concurrent commit transactions -------------------------
class PausingStore:
    """LABELLED wrapper of a real store: the first owner-record write of an armed controller signals and
    holds its open transaction (and so the advisory lock) until released."""

    def __init__(self, store):
        import threading
        self.store, self.inside, self.release = store, threading.Event(), threading.Event()

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def held():
            with self.store.transaction() as tx:
                yield PausingTransaction(tx, self)
        return held()


class PausingTransaction:
    def __init__(self, tx, owner):
        self.tx, self.owner = tx, owner

    def __getattr__(self, name):
        return getattr(self.tx, name)

    def put(self, bucket, key, body):
        if bucket == "continuation_requalifications" and not self.owner.inside.is_set():
            self.owner.inside.set()
            assert self.owner.release.wait(20)
        self.tx.put(bucket, key, body)


@pytest.mark.integration
def test_family_exclusion_holds_across_concurrent_postgresql_transactions(isolated_pgstore, tmp_path):
    """Two different delivery intents of one family, both past the pre-check; the twin's commit
    transaction is open (advisory lock held) when the first request enters its own commit. The first
    blocks on the lock, then rechecks the family inside its transaction and refuses with no write."""
    import threading
    import time

    from test_fleet import config as fleet_config

    from codex_harness.application.continuation import Continuation
    from codex_harness.application.fleet import Fleet

    world = World(tmp_path)
    world.control = isolated_pgstore
    world.fleet = Fleet(isolated_pgstore)
    world.fleet.register(fleet_config(tmp_path, max_parallel=2))
    world.controller = world.build()
    world.register()
    accepted_item(world)
    world.tick()
    world.tick()
    delivery = only(world.intents(), route=dc.DELIVERY)
    withdraw(world, delivery["release_id"])
    rationale = world.artifacts.put(RATIONALE, "owner-rationale")["ref"]
    twin = {**delivery, "id": "1" * 64, "state": dc.AWAITING_OWNER}
    with isolated_pgstore.transaction() as tx:   # labelled: another delivery intent of the same family
        tx.put(BUCKET_INTENTS, twin["id"], twin)
    pausing = PausingStore(isolated_pgstore)
    other = world.build(cls=lambda _store, **ports: Continuation(pausing, **ports))
    outcome, times = {}, {}

    def second():
        outcome["twin"] = other.requalify_delivery(document(twin, rationale, intent_id=twin["id"]),
                                                   pin_sha256=world.pin["sha256"], runtime=world.runtime,
                                                   mainline=Mainline())
        times["twin_committed"] = time.monotonic()

    thread = threading.Thread(target=second)

    class Concurrent(Mainline):
        def remote_main(self):
            if self.reads == 0:
                thread.start()
                assert pausing.inside.wait(20), "the twin never reached its commit transaction"
                threading.Timer(0.5, pausing.release.set).start()
            return super().remote_main()
    with pytest.raises(dc.ContinuationRefused) as refused:
        requalify(world, document(delivery, rationale), Concurrent())
    times["refused"] = time.monotonic()
    thread.join(30)
    assert refused.value.reason_code == "requalification_family_open"
    assert outcome["twin"]["requalified"] is True and times["twin_committed"] <= times["refused"]
    intents = world.intents()
    assert intents[delivery["id"]]["state"] == dc.AWAITING_OWNER
    assert dc.requalification_id(delivery["id"]) not in intents
    with isolated_pgstore.transaction() as tx:
        stored = [row["id"] for row in tx.scan("continuation_requalifications")]
    assert stored == [twin["id"]]
