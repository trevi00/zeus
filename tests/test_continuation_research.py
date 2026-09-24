"""INV-CONTINUATION-001, SPEC "Scoped research completion and evidence-repair delivery".

A research hold leaves `research_required` only through the owner's scoped receipt for the exact
intent, policy, family and COMPLETE failed attempt set, bound to the Portfolio investigation that
holds those jobs, the resolved accepted research dispatch and immutable evidence references.

Real MemoryStores (the Fleet control store is also the Portfolio and ResearchProgram store), the real
`Fleet`, finite `Operation`, `Portfolio` reconciler/bindings/dispositions, `ResearchProgram` with its
`ProgramRunner` over a real temporary Git repository and the real continuation owner. The lane
executor (`FakeExecutor`) and the research council (`FakeCouncil`, it writes the `autonomous_runs`
row the runner reads) are LABELLED fixtures: no model, provider, network or production store is
touched, and an injected council verdict is never evidence of real research quality.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from test_continuation import World, only
from test_fleet import config as fleet_config
from test_research_investigations import DEFINITIONS
from test_research_program import POLICY, build, registered
from test_research_program_fixtures import FakeCouncil, config
from test_research_recovery import FakeTransport, PublicationFailingCouncil, UnreachableBus

from codex_harness.adapters import continuation as adapter
from codex_harness.adapters import continuation_cli
from codex_harness.application.continuation import (
    BUCKET_RESEARCH_RECEIPTS,
    Continuation,
    LaneEvidence,
)
from codex_harness.application.fleet import Fleet
from codex_harness.application.portfolio import BUCKET_INVESTIGATIONS, Portfolio, family_id
from codex_harness.application.research_program import BUCKET_DISPATCHES
from codex_harness.domain import continuation as dc
from codex_harness.domain.model import digest
from codex_harness.domain.research_program import config_digest, validate_config

# The owner's research evidence: real bytes stored in the World's temporary FileArtifacts root by
# `receipt_for`, and read back (bounded, digest checked) at acceptance and again at consumption.
REPORT = "LABELLED fixture research report for the evidence_gate_refused family\n"
EVIDENCE = ["sha256:" + hashlib.sha256(REPORT.encode("utf-8")).hexdigest()]


def two_strikes(world, op_id, path):
    """One family failing the evidence gate twice: the root, its evidence-repair successor, held."""
    world.enqueue(op_id, path)
    world.tick()
    root, receipt = world.run_next(inspection="incomplete")
    assert receipt["reason_code"] == "evidence_gate_refused"
    world.tick()
    repair = only(world.intents(), origin_job=root, route=dc.EVIDENCE_REPAIR)
    successor, _ = world.run_next(inspection="incomplete")
    assert successor == repair["successor_job"]
    world.tick()
    research = only(world.intents(), origin_job=successor, route=dc.RESEARCH)
    assert research["state"] == dc.RESEARCH_REQUIRED and research["family"] == root
    return root, successor, research


def research_dispatch(world, tmp_path, jobs, status="accepted", project="ops"):
    """The existing research path end to end: the Portfolio groups the jobs, the owner binds them,
    an opted-in program claims the investigation and records the (LABELLED) council's run row."""
    rows = world.jobs()
    family = (rows[jobs[0]]["status"], rows[jobs[0]]["reason_code"])
    owner = Portfolio(world.control, DEFINITIONS)
    for job in jobs:
        owner.bind(job, project, "c1")
    owner.reconcile()
    root = tmp_path / "research"
    root.mkdir(exist_ok=True)
    env = build(root, store=world.control, council=FakeCouncil(world.control, status=status))
    registered(env, investigation_source={"topic": "storage", "project_ids": ["ops"], "reason_codes": [family[1]]})
    investigation = family_id(*family)
    ticked = env.runner.tick("rp-001")
    assert ticked["investigation"] == investigation
    with world.control.transaction() as tx:
        return investigation, tx.get(BUCKET_DISPATCHES, investigation)


def receipt_for(world, research, investigation, dispatch, **overrides):
    """What the owner submits: the attempt set the status projection names for this intent, each
    attempt's inspection from its own lane evidence, the dispatch binding and evidence refs whose
    bytes the research owner stored."""
    assert world.artifacts.put(REPORT, "research-council")["ref"] == EVIDENCE[0]
    status = world.controller.status("policy-1")
    attempts = only({row["id"]: row for row in status["intents"]}, id=research["id"])["attempts"]
    jobs, lane = world.jobs(), LaneEvidence(world.lane.store)
    return {"schema": dc.RESEARCH_RECEIPT_SCHEMA, "intent_id": research["id"], "policy_id": "policy-1",
            "policy_sha256": world.controller.policy("policy-1")["policy_sha256"], "family": research["family"],
            "attempts": [{**a, "inspection": dc.observed_attempt(jobs[a["job"]], lane.read(jobs[a["job"]]))["inspection"]}
                         for a in attempts],
            "investigation": investigation,
            "dispatch": {key: dispatch[key] for key in ("program", "run_id", "manifest_sha256", "snapshot_sha256")},
            "evidence_refs": list(EVIDENCE), **overrides}


def receipts(world):
    with world.control.transaction() as tx:
        return {row["id"]: row for row in tx.scan(BUCKET_RESEARCH_RECEIPTS)}


def research_rows(world, investigation):
    with world.control.transaction() as tx:
        return deepcopy((tx.get(BUCKET_INVESTIGATIONS, investigation), tx.get(BUCKET_DISPATCHES, investigation)))


def held(world, tmp_path):
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    investigation, dispatch = research_dispatch(world, tmp_path, [root, successor])
    return root, successor, research, investigation, dispatch


# ---- the exact covered pair leaves research_required once -------------------------------------------
def test_exact_receipt_releases_the_hold_once_and_admits_one_evidence_repair_successor(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    assert research["family_jobs"] == sorted([root, successor])
    # A coarse `researched` disposition is evidence that the owner looked, never approval.
    Portfolio(world.control, DEFINITIONS).disposition(investigation, "researched", ["sha256:" + "1" * 64])
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED
    assert world.controller.status("policy-1")["held_families"] == {root: "two_distinct_failures"}
    before = research_rows(world, investigation)
    old_jobs = {job: world.jobs()[job] for job in (root, successor)}
    old_repair = only(world.intents(), origin_job=root, route=dc.EVIDENCE_REPAIR)

    document = receipt_for(world, research, investigation, dispatch)
    assert [a["job"] for a in document["attempts"]] == sorted([root, successor])
    assert all(a["inspection"].startswith("insp-") for a in document["attempts"])
    accepted = world.controller.accept_research(document)
    assert accepted["accepted"] is True and accepted["cached"] is False
    assert accepted["covered_jobs"] == sorted([root, successor]) and accepted["evidence_refs"] == EVIDENCE
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED, "acceptance moves nothing"

    result = world.tick()
    intents = world.intents()
    done = intents[research["id"]]
    assert done["state"] == dc.COMPLETED and done["reason_code"] == "research_receipt_accepted"
    assert done["evidence_refs"] == EVIDENCE and done["research_receipt"] == receipts(world)[research["id"]]["receipt_sha256"]
    repair = only(intents, origin_job=successor, route=dc.EVIDENCE_REPAIR)
    assert repair["state"] == dc.ADMITTED and repair["family"] == root
    assert "Evidence repair" in world.jobs()[repair["successor_job"]]["manifest"]["plan"]["objective"]
    assert {"subject": research["id"], "effect": "research_resolved", "route": dc.RESEARCH} in result["actions"]
    # Nothing the research owners wrote, and no old failure verdict, was rewritten.
    assert research_rows(world, investigation) == before
    assert {job: world.jobs()[job] for job in (root, successor)} == old_jobs
    assert intents[old_repair["id"]] == old_repair
    # Replay of the receipt and further ticks: one acceptance, one successor.
    stored, jobs = deepcopy(receipts(world)), len(world.jobs())
    assert world.controller.accept_research(document)["cached"] is True
    world.tick()
    world.tick(controller=world.build())
    assert len(world.jobs()) == jobs and receipts(world) == stored
    status = world.controller.status("policy-1")
    shown = only({row["id"]: row for row in status["intents"]}, id=research["id"])
    assert shown["receipt"]["covered_jobs"] == sorted([root, successor]) and shown["receipt"]["evidence_refs"] == EVIDENCE
    assert shown["receipt"]["investigation"] == investigation and status["held_families"] == {}
    assert shown["research_receipt"] == shown["receipt"]["receipt_sha256"]


# ---- the matrix of refusals: nothing is stored and the family stays held ----------------------------
def _drop_one(document, world, ids):
    return {"attempts": document["attempts"][:1]}


def _foreign_sha(document, world, ids):
    return {"policy_sha256": "0" * 64}


def _foreign_policy(document, world, ids):
    return {"policy_id": "policy-2"}


def _wrong_intent(document, world, ids):
    return {"intent_id": only(world.intents(), route=dc.EVIDENCE_REPAIR)["id"]}


def _unknown_intent(document, world, ids):
    return {"intent_id": "0" * 64}


def _changed_attempt(document, world, ids):
    return {"attempts": [{**document["attempts"][0], "evidence_sha256": "0" * 64}, document["attempts"][1]]}


def _wrong_inspection(document, world, ids):
    return {"attempts": [{**document["attempts"][0], "inspection": "insp-other"}, document["attempts"][1]]}


def _other_family(document, world, ids):
    return {"family": "op-other"}


def _no_evidence(document, world, ids):
    return {"evidence_refs": []}


def _mutable_evidence(document, world, ids):
    return {"evidence_refs": ["docs/notes.md"]}


def _other_run(document, world, ids):
    return {"dispatch": {**document["dispatch"], "run_id": "rp-001.c999"}}


def _unknown_investigation(document, world, ids):
    return {"investigation": "0" * 64}


@pytest.mark.parametrize("change, reason", [
    (_drop_one, "research_coverage_partial"), (_foreign_sha, "research_policy_foreign"),
    (_foreign_policy, "research_policy_foreign"), (_wrong_intent, "research_intent_wrong"),
    (_unknown_intent, "research_intent_unknown"), (_changed_attempt, "research_attempts_changed"),
    (_wrong_inspection, "research_inspection_mismatch"), (_other_family, "research_family_mismatch"),
    (_no_evidence, "research_receipt_invalid"), (_mutable_evidence, "research_receipt_invalid"),
    (_other_run, "research_dispatch_mismatch"), (_unknown_investigation, "research_investigation_unknown")])
def test_partial_foreign_wrong_changed_or_absent_evidence_is_refused_and_stays_held(tmp_path, change, reason):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    forged = {**document, **change(document, world, (root, successor))}
    with pytest.raises(dc.ContinuationRefused) as info:
        world.controller.accept_research(forged)
    assert info.value.reason_code == reason
    assert receipts(world) == {}
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED
    assert len(world.jobs()) == 2, "no successor without an accepted receipt"


@pytest.mark.parametrize("council, reason", [("rejected", "research_not_accepted"), ("failed", "research_not_accepted")])
def test_rejected_or_failed_research_never_releases(tmp_path, council, reason):
    world = World(tmp_path)
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    investigation, dispatch = research_dispatch(world, tmp_path, [root, successor], status=council)
    with pytest.raises(dc.ContinuationRefused, match=reason):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    assert receipts(world) == {}


def test_unfinished_research_and_an_unclaimed_investigation_never_release(tmp_path):
    world = World(tmp_path)
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    owner = Portfolio(world.control, DEFINITIONS)
    for job in (root, successor):
        owner.bind(job, "ops", "c1")
    owner.reconcile()
    investigation = family_id("failed", "evidence_gate_refused")
    bound = {"program": "rp-001", "run_id": "rp-001.c001", "manifest_sha256": "d" * 64, "snapshot_sha256": "e" * 64}
    document = {**receipt_for(world, research, investigation, {**bound}), "dispatch": bound}
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_unknown"):
        world.controller.accept_research(document)
    # The real claim/capture/council-start boundary, with no council result yet (a crash here).
    (tmp_path / "research").mkdir()
    env = build(tmp_path / "research", store=world.control)
    registered(env, investigation_source={"topic": "storage", "project_ids": ["ops"],
                                          "reason_codes": ["evidence_gate_refused"]})
    reserved = env.programs.reserve_cycle("rp-001", env.identity)
    cycle, token = reserved["cycle"]["id"], reserved["cycle"]["owner"]
    env.programs.record_collection(cycle, token, {}, [], {"this_host": 0, "all_hosts": 0})
    env.programs.record_capture(cycle, token, {"revision": "c" * 40, "ref": "refs/zeus/research/rp-001/001",
                                               "path": "docs/zeus/research-captures/rp-001/001.json"})
    env.programs.record_council_start(cycle, token, "rp-001.c001", "d" * 64, "sha256:" + "e" * 64)
    with world.control.transaction() as tx:
        dispatch = tx.get(BUCKET_DISPATCHES, investigation)
    assert dispatch["state"] == "dispatched"
    with pytest.raises(dc.ContinuationRefused, match="research_unfinished"):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    assert receipts(world) == {}


def test_a_member_outside_the_investigation_or_the_dispatch_scope_is_unverifiable(tmp_path):
    world = World(tmp_path)
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    world.register()
    # Only the root is bound to the program's project: the dispatch never names the successor.
    two_strikes(world, "op-z", "docs/c.md")
    jobs = world.jobs()
    other = sorted(job for job in jobs if job not in {root, successor} and jobs[job]["status"] == "failed")
    investigation, dispatch = research_dispatch(world, tmp_path, [root, *other])
    assert successor not in dispatch["job_ids"]
    with pytest.raises(dc.ContinuationRefused, match="research_scope_unverified"):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))


# ---- two families under one coarse investigation stay independent ----------------------------------
def test_two_families_sharing_one_coarse_investigation_are_released_only_by_their_own_receipt(tmp_path):
    world = World(tmp_path)
    world.register()
    x_root, x_successor, x_research = two_strikes(world, "op-x", "docs/a.md")
    y_root, y_successor, y_research = two_strikes(world, "op-y", "docs/b.md")
    investigation, dispatch = research_dispatch(world, tmp_path, [x_root, x_successor, y_root, y_successor])
    assert dispatch["job_ids"] == sorted([x_root, x_successor, y_root, y_successor]), "one coarse row, four jobs"
    x_document = receipt_for(world, x_research, investigation, dispatch)
    y_document = receipt_for(world, y_research, investigation, dispatch)
    # Neither family's attempts cover the other, and a merged set is not either family's set.
    with pytest.raises(dc.ContinuationRefused, match="research_family_mismatch"):
        world.controller.accept_research({**x_document, "intent_id": y_research["id"]})
    with pytest.raises(dc.ContinuationRefused, match="research_attempts_changed"):
        world.controller.accept_research({**x_document, "attempts": x_document["attempts"] + y_document["attempts"]})
    world.controller.accept_research(x_document)
    world.tick()
    intents = world.intents()
    assert intents[x_research["id"]]["state"] == dc.COMPLETED
    assert intents[y_research["id"]]["state"] == dc.RESEARCH_REQUIRED
    assert world.controller.status("policy-1")["held_families"] == {y_root: "two_distinct_failures"}
    assert only(intents, origin_job=x_successor, route=dc.EVIDENCE_REPAIR)["state"] == dc.ADMITTED
    assert not [row for row in intents.values() if row["origin_job"] == y_successor and row["route"] != dc.RESEARCH]
    world.controller.accept_research(y_document)
    world.tick()
    assert world.intents()[y_research["id"]]["state"] == dc.COMPLETED


# ---- immutability, concurrency and restart ----------------------------------------------------------
def test_concurrent_submission_keeps_one_receipt_and_a_different_one_conflicts(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    start, results = threading.Barrier(2), []

    def submit():
        start.wait()
        results.append(Continuation(world.control, lanes=world.lanes, evidence=world.evidence).accept_research(document))
    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r["cached"] for r in results) == [False, True] and len(receipts(world)) == 1
    stored = deepcopy(receipts(world))
    with pytest.raises(dc.ContinuationRefused, match="research_receipt_conflict"):
        world.controller.accept_research({**document, "evidence_refs": ["sha256:" + "6" * 64]})
    assert receipts(world) == stored, "the stored receipt is never edited"


def test_restart_and_concurrent_controllers_consume_the_persisted_receipt_once(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    controllers = [world.build(), world.build()]   # a restarted process and a second controller
    start = threading.Barrier(2)

    def tick(controller):
        start.wait()
        world.tick(controller=controller)
    threads = [threading.Thread(target=tick, args=(c,)) for c in controllers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    world.tick()
    intents = world.intents()
    assert intents[research["id"]]["state"] == dc.COMPLETED
    completions = [h for h in intents[research["id"]]["history"] if h["state"] == dc.COMPLETED]
    assert len(completions) == 1
    repairs = [row for row in intents.values() if row["origin_job"] == successor and row["route"] == dc.EVIDENCE_REPAIR]
    assert len(repairs) == 1 and len(world.jobs()) == 3, "one successor across restart and two controllers"


def test_an_unreadable_lane_or_a_changed_attempt_after_acceptance_never_approves(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    world.controller.accept_research(receipt_for(world, research, investigation, dispatch))

    class Down(LaneEvidence):
        def read(self, job, target=None):
            raise ConnectionError("lane store unavailable (injected fault)")

    down = world.tick(controller=world.build(lanes=lambda lane: Down(world.lane.store, world.sessions)))
    assert {"subject": research["id"], "reason_code": "unavailable", "error_type": "ConnectionError"} in down["skipped"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED
    # LABELLED injected fault: the lane's evidence of one covered attempt changes after acceptance.
    with world.lane.store.transaction() as tx:
        row = tx.get("operations", successor)
        row["owner_handoff"] = {**row["owner_handoff"], "inspection": {**row["owner_handoff"]["inspection"],
                                                                       "id": "insp-replaced"}}
        tx.put("operations", successor, row)
    changed = world.tick()
    # The decisive evidence digest binds the handoff's inspection, so the attempt itself changed.
    assert [s["reason_code"] for s in changed["skipped"] if s["subject"] == research["id"]] == [
        "research_attempt_changed"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED and len(world.jobs()) == 2


def test_an_old_receipt_never_authorizes_a_new_failure_of_the_family(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    world.controller.accept_research(document)
    world.tick()
    third, _ = world.run_next(inspection="incomplete")   # the evidence-repair successor fails again
    world.tick()
    again = only(world.intents(), origin_job=third, route=dc.RESEARCH)
    assert again["state"] == dc.RESEARCH_REQUIRED and again["family"] == root
    status = only({row["id"]: row for row in world.controller.status("policy-1")["intents"]}, id=again["id"])
    assert [a["job"] for a in status["attempts"]] == sorted([successor, third])
    with pytest.raises(dc.ContinuationRefused, match="research_attempts_changed"):
        world.controller.accept_research({**document, "intent_id": again["id"]})
    world.tick()
    assert world.intents()[again["id"]]["state"] == dc.RESEARCH_REQUIRED and set(receipts(world)) == {research["id"]}


# ---- actual evidence bytes (SPEC "Scoped research resubmission: actual artifact availability") ------
def stored_path(world, ref) -> Path:
    return Path(world.artifacts.root) / (ref.partition(":")[2] + ".txt")


def _missing(world):
    return ["sha256:" + hashlib.sha256(b"never stored").hexdigest()]


def _one_missing(world):
    return sorted(EVIDENCE + _missing(world))


def _unreadable(world):
    # LABELLED injected fault: the content-addressed path exists but cannot be read as a file.
    path = stored_path(world, EVIDENCE[0])
    path.unlink()
    path.mkdir()
    return list(EVIDENCE)


def _tampered(world):
    stored_path(world, EVIDENCE[0]).write_text(REPORT + "edited after storage\n", encoding="utf-8")
    return list(EVIDENCE)


def _oversized(world):
    return [world.artifacts.put("x" * (adapter.MAX_RESEARCH_EVIDENCE_BYTES + 1), "research-council")["ref"]]


def _not_text(world):
    data = b"\xff\xfe\x00 binary"
    ref = "sha256:" + hashlib.sha256(data).hexdigest()
    stored_path(world, ref).write_bytes(data)
    return [ref]


@pytest.mark.parametrize("fault, reason", [
    (_missing, "research_evidence_missing"), (_one_missing, "research_evidence_missing"),
    (_unreadable, "research_evidence_unreadable"), (_tampered, "research_evidence_corrupt"),
    (_oversized, "research_evidence_oversized"), (_not_text, "research_evidence_invalid")])
def test_acceptance_reads_the_actual_evidence_bytes_and_refuses_what_is_not_there(tmp_path, fault, reason):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    document["evidence_refs"] = fault(world)
    with pytest.raises(dc.ContinuationRefused) as info:
        world.controller.accept_research(document)
    assert (info.value.reason_code, info.value.owner) == (reason, "portfolio_research")
    assert str(tmp_path) not in json.dumps(continuation_cli.refusal(info.value)), "no path leaves"
    assert receipts(world) == {}
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED and len(world.jobs()) == 2


def test_an_absent_verifier_neither_accepts_nor_consumes_a_receipt(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    with pytest.raises(dc.ContinuationRefused, match="research_evidence_unverified"):
        world.build(evidence=None).accept_research(document)
    assert receipts(world) == {}
    world.controller.accept_research(document)
    unverified = world.tick(controller=world.build(evidence=None))
    assert [s["reason_code"] for s in unverified["skipped"] if s["subject"] == research["id"]] == [
        "research_evidence_unverified"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED and len(world.jobs()) == 2


def _remove(world):
    stored_path(world, EVIDENCE[0]).unlink()
    return "research_evidence_missing"


def _tamper(world):
    _tampered(world)
    return "research_evidence_corrupt"


def _block(world):
    _unreadable(world)
    return "research_evidence_unreadable"


@pytest.mark.parametrize("fault", [_remove, _tamper, _block])
def test_evidence_lost_after_acceptance_keeps_the_hold_until_it_verifies_again(tmp_path, fault):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    stored = deepcopy(receipts(world))
    reason = fault(world)
    # A reconstructed controller (a restart): the cached acceptance never substitutes for this read.
    result = world.tick(controller=world.build())
    assert {"subject": research["id"], "reason_code": reason, "next_owner": "portfolio_research"} in result["skipped"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED
    assert len(world.jobs()) == 2 and receipts(world) == stored, "no successor, receipt unchanged"
    # The same bytes restored: the next tick's own read verifies them and releases exactly once.
    path = stored_path(world, EVIDENCE[0])
    if path.is_dir():
        shutil.rmtree(path)
    path.write_bytes(REPORT.encode("utf-8"))
    world.tick(controller=world.build())
    world.tick()
    intents = world.intents()
    assert intents[research["id"]]["state"] == dc.COMPLETED and len(world.jobs()) == 3
    assert only(intents, origin_job=successor, route=dc.EVIDENCE_REPAIR)["state"] == dc.ADMITTED
    assert receipts(world) == stored


# ---- research dispatch transport recovery (research-dispatch-recovery-001) ---------------------------
def test_a_recovered_dispatch_binds_the_scoped_receipt_to_the_accepted_replacement_only(tmp_path):
    """The REAL council fails before provider entry (LABELLED transport fault), the owner authorizes
    one replacement program, and only a receipt naming THAT accepted run releases the hold."""
    world = World(tmp_path)
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    owner = Portfolio(world.control, DEFINITIONS)
    for job in (root, successor):
        owner.bind(job, "ops", "c1")
    owner.reconcile()
    investigation = family_id("failed", "evidence_gate_refused")
    source = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["evidence_gate_refused"]}
    (tmp_path / "research").mkdir()
    env = build(tmp_path / "research", store=world.control, council=PublicationFailingCouncil(world.control))
    registered(env, investigation_source=source)
    assert env.runner.tick("rp-001")["reason_code"] == "publication_incomplete"
    with world.control.transaction() as tx:
        failed = deepcopy(tx.get(BUCKET_DISPATCHES, investigation))
    with pytest.raises(dc.ContinuationRefused, match="research_not_accepted"):
        world.controller.accept_research(receipt_for(world, research, investigation, failed))

    cfg = validate_config(config(env.head, id="rp-002", investigation_source=source), POLICY)
    env.programs.register(cfg, env.identity, [])
    pinned = {k: failed[k] for k in ("program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256")}
    env.programs.recover_dispatch({"schema": "urn:zeus:research-dispatch-recovery:1", "investigation": investigation,
                                   "failed": pinned, "replacement": {"program": "rp-002",
                                                                     "config_sha256": config_digest(cfg, env.identity)}},
                                  FakeTransport())
    # Authorized but not yet claimed: the failed original no longer answers, nothing approves.
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_unknown"):
        world.controller.accept_research(receipt_for(world, research, investigation, failed))
    env.programs.resume("rp-002")
    env.runner.council = FakeCouncil(world.control, status="accepted")
    assert env.runner.tick("rp-002")["result"] == "accepted"
    with world.control.transaction() as tx:
        current = deepcopy(tx.get(BUCKET_DISPATCHES, investigation + ".recovery-1"))
        assert tx.get(BUCKET_DISPATCHES, investigation) == failed, "the failed original is retained as it was"
    # A stale receipt naming the failed attempt never approves, even though a replacement was accepted.
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_mismatch"):
        world.controller.accept_research(receipt_for(world, research, investigation, failed))
    assert receipts(world) == {}
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED
    accepted = world.controller.accept_research(receipt_for(world, research, investigation, current))
    assert accepted["accepted"] is True and accepted["dispatch"]["run_id"] == "rp-002.c001"
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.COMPLETED


def revoked_research(world, tmp_path):
    """The REAL council fails before provider entry on a LABELLED legacy bus with NO transport
    binding; the owner's explicit revocation authorizes the replacement, whose (LABELLED) council
    accepts. Returns the held intent, the investigation, the accepted replacement dispatch and the
    retained fence's key."""
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    owner = Portfolio(world.control, DEFINITIONS)
    for job in (root, successor):
        owner.bind(job, "ops", "c1")
    owner.reconcile()
    investigation = family_id("failed", "evidence_gate_refused")
    source = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["evidence_gate_refused"]}
    (tmp_path / "research").mkdir()
    council = PublicationFailingCouncil(world.control, UnreachableBus(bound=False))
    env = build(tmp_path / "research", store=world.control, council=council)
    registered(env, investigation_source=source)
    assert env.runner.tick("rp-001")["reason_code"] == "publication_incomplete"
    with world.control.transaction() as tx:
        failed = deepcopy(tx.get(BUCKET_DISPATCHES, investigation))
        [item] = [o for o in tx.scan("outbox") if o["message"]["correlation_id"] == "autonomous:rp-001.c001"]
    cfg = validate_config(config(env.head, id="rp-002", investigation_source=source), POLICY)
    env.programs.register(cfg, env.identity, [])
    pinned = {k: failed[k] for k in ("program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256")}
    result = env.programs.recover_dispatch(
        {"schema": "urn:zeus:research-dispatch-recovery:2", "mode": "execution_revocation",
         "investigation": investigation, "failed": pinned,
         "replacement": {"program": "rp-002", "config_sha256": config_digest(cfg, env.identity)},
         "revoke": {"message_id": item["message"]["message_id"], "source_sha256": digest(item)}}, None)
    assert result["proof"] == "execution_revoked"
    env.programs.resume("rp-002")
    env.runner.council = FakeCouncil(world.control, status="accepted")
    assert env.runner.tick("rp-002")["result"] == "accepted"
    with world.control.transaction() as tx:
        current = deepcopy(tx.get(BUCKET_DISPATCHES, investigation + ".recovery-1"))
    return research, investigation, current, ("execution_fences", "tasks:" + item["message"]["message_id"])


def test_an_execution_revocation_releases_the_receipt_only_while_its_retained_fence_holds(tmp_path):
    """SPEC "Actual legacy research recovery: execution revocation": a lost retained fence (LABELLED
    injected fault) holds both acceptance and consumption by name; the exact fence restored releases
    exactly once."""
    world = World(tmp_path)
    research, investigation, current, key = revoked_research(world, tmp_path)
    with world.control.lock:   # LABELLED injected fault: the retained fence row is lost
        fence = world.control.data.pop(key)
    with pytest.raises(dc.ContinuationRefused, match="research_recovery_revocation_fence_missing"):
        world.controller.accept_research(receipt_for(world, research, investigation, current))
    assert receipts(world) == {}
    with world.control.lock:
        world.control.data[key] = fence
    assert world.controller.accept_research(receipt_for(world, research, investigation, current))["accepted"] is True
    with world.control.lock:   # the same fault after acceptance: consumption holds, receipt unchanged
        world.control.data.pop(key)
    stored = deepcopy(receipts(world))
    result = world.tick()
    assert {"subject": research["id"], "reason_code": "research_recovery_revocation_fence_missing",
            "next_owner": "portfolio_research"} in result["skipped"]
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED and receipts(world) == stored
    with world.control.lock:
        world.control.data[key] = fence
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.COMPLETED


# ---- revocation resubmission: replay acceptance (SPEC 2026-09-24) ------------------------------------
# Every accepted return, the initial cached replay and the concurrent insertion branch included,
# answers only while the retained fence holds; the immutable receipt and its accepted_at are kept.
def _lose(world, key):
    with world.control.lock:   # LABELLED injected fault: the retained fence row is lost
        world.control.data.pop(key)


def _change(world, key):
    with world.control.transaction() as tx:   # LABELLED injected fault: the retained fence row is rewritten
        tx.put(*key, {**tx.get(*key), "owner": "someone-else"})


def _malform(world, key):
    with world.control.transaction() as tx:   # LABELLED injected fault: the retained fence row is malformed
        tx.put(*key, {"id": key[1], "generation": "one"})


def _restore(world, key, fence):
    with world.control.transaction() as tx:
        tx.put(*key, fence)


def _fence(world, key):
    with world.control.transaction() as tx:
        return deepcopy(tx.get(*key))


@pytest.mark.parametrize("fault, reason", [
    (_lose, "research_recovery_revocation_fence_missing"),
    (_change, "research_recovery_revocation_fence_changed"),
    (_malform, "research_recovery_revocation_fence_changed")])
def test_a_cached_replay_answers_only_while_the_retained_fence_holds(tmp_path, fault, reason):
    world = World(tmp_path)
    research, investigation, current, key = revoked_research(world, tmp_path)
    document, fence = receipt_for(world, research, investigation, current), _fence(world, key)
    assert world.controller.accept_research(document)["cached"] is False
    stored = deepcopy(receipts(world))
    replay = world.controller.accept_research(document)
    assert replay["accepted"] is True and replay["cached"] is True, "intact fence: idempotent replay"
    fault(world, key)
    with pytest.raises(dc.ContinuationRefused, match=reason):
        world.build().accept_research(document)
    with pytest.raises(dc.ContinuationRefused, match="research_receipt_conflict"):
        world.controller.accept_research({**document, "evidence_refs": ["sha256:" + "6" * 64]})
    assert receipts(world) == stored, "a refused replay never erases the prior acceptance"
    result = world.tick()
    assert {"subject": research["id"], "reason_code": reason, "next_owner": "portfolio_research"} in result["skipped"]
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED and receipts(world) == stored
    _restore(world, key, fence)
    again = world.controller.accept_research(document)
    assert again["cached"] is True and receipts(world) == stored
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.COMPLETED


def _interleave(world, key, controller, document, insert, fault):
    """LABELLED forced interleaving: after the checked reads and the evidence read, before the write
    transaction, a second controller records the identical receipt and/or the fence is mutated."""
    verify = controller._verify_evidence

    def between(receipt):
        verify(receipt)
        if insert:
            assert world.build().accept_research(document)["cached"] is False
        if fault is not None:
            fault(world, key)
    controller._verify_evidence = between


@pytest.mark.parametrize("insert, fault, reason", [
    (True, None, None),
    (True, _lose, "research_recovery_revocation_fence_missing"),
    (True, _change, "research_recovery_revocation_fence_changed"),
    (False, _change, "research_recovery_revocation_fence_changed")])
def test_the_write_transaction_rechecks_the_fence_on_concurrent_insertion_and_on_insert(tmp_path, insert, fault,
                                                                                         reason):
    world = World(tmp_path)
    research, investigation, current, key = revoked_research(world, tmp_path)
    document, controller = receipt_for(world, research, investigation, current), world.build()
    _interleave(world, key, controller, document, insert, fault)
    if reason is None:
        assert controller.accept_research(document)["cached"] is True, "the concurrent insertion branch was taken"
        return
    with pytest.raises(dc.ContinuationRefused, match=reason):
        controller.accept_research(document)
    kept = list(receipts(world).values())
    assert len(kept) == int(insert), "the concurrent receipt is kept; a refused insert writes nothing"
    assert all(row["receipt"] == document for row in kept)
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED


def test_postgres_replay_and_concurrent_insertion_recheck_the_fence_in_one_writer_transaction(tmp_path,
                                                                                               isolated_pgstore):
    """Real isolated PostgreSQL (HARNESS_INTEGRATION=1): the same control store backs the Fleet, the
    research program and the continuation owner. The fault is a transactional rewrite (no in-memory
    row surgery); the recheck reuses the open writer transaction rather than nesting one."""
    world = World(tmp_path)
    world.control, world.fleet = isolated_pgstore, Fleet(isolated_pgstore)
    world.fleet.register(fleet_config(tmp_path, max_parallel=2))
    world.controller = world.build()
    research, investigation, current, key = revoked_research(world, tmp_path)
    document, fence = receipt_for(world, research, investigation, current), _fence(world, key)
    controller = world.build()
    _interleave(world, key, controller, document, True, _change)
    with pytest.raises(dc.ContinuationRefused, match="research_recovery_revocation_fence_changed"):
        controller.accept_research(document)
    stored = deepcopy(receipts(world))
    assert len(stored) == 1
    with pytest.raises(dc.ContinuationRefused, match="research_recovery_revocation_fence_changed"):
        world.build().accept_research(document)
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED and receipts(world) == stored
    _restore(world, key, fence)
    assert world.build().accept_research(document)["cached"] is True and receipts(world) == stored
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.COMPLETED
