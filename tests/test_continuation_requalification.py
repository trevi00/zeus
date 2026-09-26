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
    """LABELLED double of the lane mainline port (`adapters.continuation.LaneMainline`)."""

    def __init__(self, main=MAIN, present=True, goal_sha="b" * 64, error=None):
        self.main, self.present, self.goal_sha, self.error, self.reads = main, present, goal_sha, error, 0

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
        return {"mode": "100644", "sha256": self.goal_sha, "bytes": 3}


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
