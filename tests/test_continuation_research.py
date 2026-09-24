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
    BUCKET_RESEARCH_SUPPLEMENTS,
    Continuation,
    LaneEvidence,
)
from codex_harness.application.fleet import Fleet
from codex_harness.application.observations import Observer
from codex_harness.application.portfolio import (
    BUCKET_BINDINGS,
    BUCKET_INVESTIGATIONS,
    Portfolio,
    family_id,
)
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


def research_dispatch(world, tmp_path, jobs, status="accepted", project="ops", program="rp-001", folder="research"):
    """The existing research path end to end: the Portfolio groups the jobs, the owner binds them,
    an opted-in program claims the investigation and records the (LABELLED) council's run row."""
    rows = world.jobs()
    family = (rows[jobs[0]]["status"], rows[jobs[0]]["reason_code"])
    owner = Portfolio(world.control, DEFINITIONS)
    for job in jobs:
        owner.bind(job, project, "c1")
    owner.reconcile()
    root = tmp_path / folder
    root.mkdir(exist_ok=True)
    env = build(root, store=world.control, council=FakeCouncil(world.control, status=status))
    registered(env, id=program,
               investigation_source={"topic": "storage", "project_ids": ["ops"], "reason_codes": [family[1]]})
    investigation = family_id(*family)
    ticked = env.runner.tick(program)
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


# ---- settled read-only successor (SPEC "Real council progress", 2026-09-24) ---------------------------
def test_a_settled_read_only_successor_binds_the_receipt_to_the_current_successor_only(tmp_path):
    """rp-001 revoked -> rp-002's REAL council settles researcher + DBA and fails `foreign_message`
    (LABELLED executor, bus, snapshot) -> the owner's explicit successor authorizes rp-003, whose
    (LABELLED) council accepts. A receipt naming the failed predecessor never approves; the current
    successor's does, and only while the retained chain holds (LABELLED injected fault)."""
    from test_research_recovery import ForeignMessageCouncil

    world = World(tmp_path)
    research, investigation, replacement, fence_key = revoked_research_failing(world, tmp_path)
    with pytest.raises(dc.ContinuationRefused, match="research_not_accepted"):
        world.controller.accept_research(receipt_for(world, research, investigation, replacement))
    env = world.research_env
    cfg = validate_config(config(env.head, id="rp-003", investigation_source=dict(world.research_source)), POLICY)
    env.programs.register(cfg, env.identity, [])
    with world.control.transaction() as tx:
        lineage = tx.get("research_dispatch_recoveries", investigation)
        program = tx.get("research_programs", "rp-002")
    council = world.research_council
    assert isinstance(council, ForeignMessageCouncil)
    result = env.programs.recover_dispatch(
        {"schema": "urn:zeus:research-dispatch-recovery:3", "mode": "settled_read_only_successor",
         "investigation": investigation,
         "predecessor": {"dispatch": investigation + ".recovery-1", "lineage_version": 1,
                         "lineage_request_sha256": lineage["request_sha256"], "program": "rp-002",
                         "config_sha256": program["config_sha256"],
                         **{k: replacement[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}},
         "replacement": {"program": "rp-003", "config_sha256": config_digest(cfg, env.identity)}}, None, council.artifacts)
    assert result["state"] == "authorized"
    # Authorized, not yet claimed: the predecessor no longer answers and nothing approves.
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_unknown"):
        world.controller.accept_research(receipt_for(world, research, investigation, replacement))
    env.programs.resume("rp-003")
    env.runner.council = FakeCouncil(world.control, status="accepted")
    assert env.runner.tick("rp-003")["result"] == "accepted"
    with world.control.transaction() as tx:
        current = deepcopy(tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2"))
        assert tx.get(BUCKET_DISPATCHES, investigation + ".recovery-1") == replacement, "the predecessor is retained"
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_mismatch"):
        world.controller.accept_research(receipt_for(world, research, investigation, replacement))
    assert receipts(world) == {}

    with world.control.lock:   # LABELLED injected fault: the ORIGINAL retained revocation fence is lost
        fence = world.control.data.pop(fence_key)
    with pytest.raises(dc.ContinuationRefused, match="research_recovery_revocation_fence_missing"):
        world.controller.accept_research(receipt_for(world, research, investigation, current))
    with world.control.lock:
        world.control.data[fence_key] = fence
    accepted = world.controller.accept_research(receipt_for(world, research, investigation, current))
    assert accepted["accepted"] is True and accepted["dispatch"]["run_id"] == "rp-003.c001"

    with world.control.transaction() as tx:   # LABELLED injected fault: a bound predecessor execution changed
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
        tx.put("tasks", task["id"], {**task, "status": "retry"})
    stored = deepcopy(receipts(world))
    result = world.tick()
    assert {"subject": research["id"], "reason_code": "research_recovery_successor_history_changed",
            "next_owner": "portfolio_research"} in result["skipped"]
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED and receipts(world) == stored
    with world.control.transaction() as tx:
        tx.put("tasks", task["id"], task)
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.COMPLETED


def revoked_research_failing(world, tmp_path):
    """`revoked_research` with the replacement rp-002 run by the REAL council that settles researcher +
    DBA and then fails `foreign_message`. Keeps the env, source and council on the world object."""
    from test_research_recovery import ForeignMessageCouncil

    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    owner = Portfolio(world.control, DEFINITIONS)
    for job in (root, successor):
        owner.bind(job, "ops", "c1")
    owner.reconcile()
    investigation = family_id("failed", "evidence_gate_refused")
    source = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["evidence_gate_refused"]}
    (tmp_path / "research").mkdir()
    env = build(tmp_path / "research", store=world.control,
                council=PublicationFailingCouncil(world.control, UnreachableBus(bound=False)))
    registered(env, investigation_source=source)
    assert env.runner.tick("rp-001")["reason_code"] == "publication_incomplete"
    with world.control.transaction() as tx:
        failed = deepcopy(tx.get(BUCKET_DISPATCHES, investigation))
        [item] = [o for o in tx.scan("outbox") if o["message"]["correlation_id"] == "autonomous:rp-001.c001"]
    cfg = validate_config(config(env.head, id="rp-002", investigation_source=source), POLICY)
    env.programs.register(cfg, env.identity, [])
    pinned = {k: failed[k] for k in ("program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256")}
    env.programs.recover_dispatch(
        {"schema": "urn:zeus:research-dispatch-recovery:2", "mode": "execution_revocation",
         "investigation": investigation, "failed": pinned,
         "replacement": {"program": "rp-002", "config_sha256": config_digest(cfg, env.identity)},
         "revoke": {"message_id": item["message"]["message_id"], "source_sha256": digest(item)}}, None)
    env.programs.resume("rp-002")
    council = ForeignMessageCouncil(world.control)
    env.runner.council = council
    assert env.runner.tick("rp-002")["result"] == "failed"
    world.research_env, world.research_source, world.research_council = env, source, council
    with world.control.transaction() as tx:
        replacement = deepcopy(tx.get(BUCKET_DISPATCHES, investigation + ".recovery-1"))
    assert replacement["result_reason"] == "foreign_message"
    return research, investigation, replacement, ("execution_fences", "tasks:" + item["message"]["message_id"])


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


# ---- research coverage ownership (SPEC "Research coverage ownership: accepted003 receipt refusal") -----
ATTESTATION = ("LABELLED fixture owner coverage attestation: the owner read the accepted report and judges that it "
               "covers the captured root and its continuation successor (owner judgment, not a model verdict)\n")


def bindings(world):
    with world.control.transaction() as tx:
        return {row["id"]: row for row in tx.scan(BUCKET_BINDINGS)}


def supplements(world):
    with world.control.transaction() as tx:
        return {row["id"]: row for row in tx.scan(BUCKET_RESEARCH_SUPPLEMENTS)}


class LostAfterEnqueue(Fleet):
    def enqueue(self, *args):
        super().enqueue(*args)
        raise ConnectionError("response lost after the Fleet commit (injected fault)")


def failed_root(world, op_id="op-x", path="docs/a.md", bind=True):
    world.enqueue(op_id, path)
    world.tick()
    root, receipt = world.run_next(inspection="incomplete")
    assert receipt["reason_code"] == "evidence_gate_refused"
    if bind:
        Portfolio(world.control, DEFINITIONS).bind(root, "ops", "c1")
    return root


def test_a_new_successor_inherits_its_origins_project_once_and_an_unbound_origin_is_never_guessed(tmp_path):
    world = World(tmp_path)
    world.register()
    bound = failed_root(world, "op-x", "docs/a.md")
    unbound = failed_root(world, "op-y", "docs/b.md", bind=False)
    world.tick()
    intents = world.intents()
    x = only(intents, origin_job=bound, route=dc.EVIDENCE_REPAIR)
    y = only(intents, origin_job=unbound, route=dc.EVIDENCE_REPAIR)
    assert x["state"] == y["state"] == dc.ADMITTED
    assert x["ownership"] == {"state": "inherited", "project_id": "ops", "criterion_id": "c1"}
    assert y["ownership"] == {"state": "origin_unbound", "project_id": None, "criterion_id": None}
    rows = bindings(world)
    assert rows[x["successor_job"]]["project_id"] == "ops" and rows[x["successor_job"]]["criterion_id"] == "c1"
    assert rows[x["successor_job"]]["lineage"] == {"origin_job": bound, "intent_id": x["id"]}
    assert rows[x["successor_job"]]["recorded_by"] == "continuation_lineage"
    assert y["successor_job"] not in rows and unbound not in rows, "no project is guessed for unbound work"
    # Restart and further ticks: the same single binding, never rewritten.
    stored = deepcopy(bindings(world))
    world.tick(controller=world.build())
    world.tick()
    assert bindings(world) == stored


def test_an_interrupted_admission_binds_once_on_replay_and_a_conflicting_binding_holds_the_intent(tmp_path):
    world = World(tmp_path)
    world.register()
    failed_root(world)
    lost = world.tick(controller=world.build(fleet=LostAfterEnqueue(world.control)))
    assert lost["skipped"][0]["error_type"] == "ConnectionError"
    intent = only(world.intents(), route=dc.EVIDENCE_REPAIR)
    successor = intent["successor_job"]
    assert intent["state"] == dc.PUBLISHED and successor in world.jobs() and successor not in bindings(world)
    # The owner binds the admitted successor elsewhere meanwhile: the replay refuses and never overwrites.
    Portfolio(world.control, DEFINITIONS).bind(successor, "other", "c1")
    conflict = world.tick(controller=world.build())
    assert {"subject": intent["id"], "reason_code": "successor_binding_conflict",
            "next_owner": "portfolio"} in conflict["skipped"]
    assert world.intents()[intent["id"]]["state"] == dc.PUBLISHED, "the intent does not advance"
    assert bindings(world)[successor]["project_id"] == "other" and len(world.jobs()) == 2


def test_concurrent_controllers_after_an_interrupted_admission_bind_and_admit_exactly_once(tmp_path):
    world = World(tmp_path)
    world.register()
    root = failed_root(world)
    world.tick(controller=world.build(fleet=LostAfterEnqueue(world.control)))
    start = threading.Barrier(2)

    def tick(controller):
        start.wait()
        world.tick(controller=controller)
    threads = [threading.Thread(target=tick, args=(world.build(),)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    intent = only(world.intents(), route=dc.EVIDENCE_REPAIR)
    assert intent["state"] == dc.ADMITTED and len(world.jobs()) == 2
    assert [h["state"] for h in intent["history"]].count(dc.ADMITTED) == 1
    row = bindings(world)[intent["successor_job"]]
    assert (row["project_id"], row["lineage"]) == ("ops", {"origin_job": root, "intent_id": intent["id"]})


def accepted003(world, tmp_path):
    """The actual accepted003 shape: the root and another family's jobs are bound and captured by the
    accepted current dispatch; the root's evidence-repair successor (`cont-...`) was admitted unbound
    before any binding existed, so the immutable sample excludes it and the receipt refuses."""
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    two_strikes(world, "op-z", "docs/c.md")
    jobs = world.jobs()
    other = sorted(job for job in jobs if job not in {root, successor} and jobs[job]["status"] == "failed")
    investigation, dispatch = research_dispatch(world, tmp_path, [root, *other])
    assert successor not in dispatch["job_ids"] and successor not in bindings(world)
    with world.control.transaction() as tx:
        assert successor in tx.get(BUCKET_INVESTIGATIONS, investigation)["job_ids"], "the broad family includes it"
    repair = only(world.intents(), origin_job=root, route=dc.EVIDENCE_REPAIR)
    return root, successor, research, investigation, dispatch, repair


def accepted_promotion(world, dispatch, revision="9" * 40):
    """LABELLED synthetic promotion evidence of the accepted council run (the rows the real promotion
    writes: the run's promotion digest, the promotion receipt, the implementation task and the
    accepting independent review); no model or provider produced them."""
    run_id, graph = dispatch["run_id"], "7" * 64
    with world.control.transaction() as tx:
        run = tx.get("autonomous_runs", run_id)
        tx.put("autonomous_runs", run_id, {**run, "promotion": {"id": run_id, "graph_sha256": graph}})
        tx.put("tasks", "impl-003", {"id": "impl-003", "agent": "worker", "status": "succeeded",
                                     "result": {"candidate": {"revision": revision}}})
        tx.put("decisions_pending", "review-003", {"id": "review-003", "phase": "review_lead", "status": "succeeded",
                                                   "input": {"candidate": {"revision": revision}},
                                                   "result": {"accepted": True}})
        tx.put("promotions", run_id, {"id": run_id, "graph_sha256": graph,
                                      "evidence": {"decision_id": "review-003", "implementation_task_id": "impl-003"}})
    return {"graph_sha256": graph, "candidate_revision": revision, "decision_id": "review-003"}


def supplement_for(world, research, investigation, dispatch, repair, acceptance, **overrides):
    receipt = receipt_for(world, research, investigation, dispatch)
    attestation = world.artifacts.put(ATTESTATION, "owner-attestation")["ref"]
    return {"schema": dc.SUPPLEMENT_SCHEMA,
            **{k: receipt[k] for k in ("intent_id", "policy_id", "policy_sha256", "family", "attempts", "investigation")},
            "dispatch": {**receipt["dispatch"], "id": dispatch["id"], "job_ids_sha256": dispatch["job_ids_sha256"]},
            "captured": [repair["origin_job"]],
            "descendants": [{"job": repair["successor_job"], "parent_job": repair["origin_job"], "intent_id": repair["id"]}],
            "acceptance": acceptance, "report_ref": EVIDENCE[0], "attestation_ref": attestation, **overrides}


def owned003(world, tmp_path):
    root, successor, research, investigation, dispatch, repair = accepted003(world, tmp_path)
    world.controller.reconcile_ownership(repair["id"])
    acceptance = accepted_promotion(world, dispatch)
    document = supplement_for(world, research, investigation, dispatch, repair, acceptance)
    return root, successor, research, investigation, dispatch, repair, document


def test_explicit_ownership_reconcile_proves_exact_lineage_only(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair = accepted003(world, tmp_path)
    before = deepcopy((world.intents(), world.jobs()))
    result = world.controller.reconcile_ownership(repair["id"])
    assert result["reconciled"] is True and result["cached"] is False
    assert (result["successor_job"], result["origin_job"], result["project_id"]) == (successor, root, "ops")
    assert "not historical capture" in result["authority"]
    assert bindings(world)[successor]["lineage"] == {"origin_job": root, "intent_id": repair["id"]}
    assert world.controller.reconcile_ownership(repair["id"])["cached"] is True
    assert (world.intents(), world.jobs()) == before, "no intent or Fleet row is written"
    with world.control.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, investigation) == dispatch, "the capture is never rewritten"
    for intent_id, reason in ((research["id"], "ownership_intent_invalid"), ("0" * 64, "ownership_intent_invalid")):
        with pytest.raises(dc.ContinuationRefused, match=reason):
            world.controller.reconcile_ownership(intent_id)


def test_ownership_reconcile_refuses_an_unbound_origin_and_a_broken_lineage(tmp_path):
    world = World(tmp_path)
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    repair = only(world.intents(), origin_job=root, route=dc.EVIDENCE_REPAIR)
    with pytest.raises(dc.ContinuationRefused, match="ownership_origin_unbound"):
        world.controller.reconcile_ownership(repair["id"])
    assert bindings(world) == {}
    Portfolio(world.control, DEFINITIONS).bind(root, "ops", "c1")
    with world.control.transaction() as tx:   # LABELLED injected fault: the admitted manifest differs
        job = tx.get("fleet_jobs", successor)
        tx.put("fleet_jobs", successor, {**job, "manifest": {**job["manifest"], "id": "op-forged"}})
    with pytest.raises(dc.ContinuationRefused, match="ownership_lineage_unproven"):
        world.controller.reconcile_ownership(repair["id"])
    with world.control.transaction() as tx:
        tx.put("fleet_jobs", successor, job)
    Portfolio(world.control, DEFINITIONS).bind(successor, "other", "c1")
    with pytest.raises(dc.ContinuationRefused, match="successor_binding_conflict"):
        world.controller.reconcile_ownership(repair["id"])
    assert bindings(world)[successor]["project_id"] == "other", "never overwritten"


def test_baseline_the_unbound_successor_is_excluded_and_the_receipt_refuses_even_after_ownership(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair = accepted003(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    with pytest.raises(dc.ContinuationRefused, match="research_scope_unverified"):
        world.controller.accept_research(document)
    world.controller.reconcile_ownership(repair["id"])
    accepted_promotion(world, dispatch)
    with pytest.raises(dc.ContinuationRefused, match="research_scope_unverified"):
        world.controller.accept_research(document)   # present ownership alone never widens the sample
    assert receipts(world) == {}


def test_accepted003_owner_supplement_releases_exactly_the_two_attempt_receipt_once(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair, document = owned003(world, tmp_path)
    before = research_rows(world, investigation)
    old_jobs = deepcopy(world.jobs())
    recorded = world.controller.supplement_research_scope(document)
    assert recorded["supplemented"] is True and recorded["cached"] is False
    assert recorded["captured"] == [root] and [d["job"] for d in recorded["descendants"]] == [successor]
    assert recorded["coverage"] == "owner_supplement" and "not the original capture" in recorded["authority"]
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED, "a supplement releases nothing"
    assert world.controller.supplement_research_scope(document)["cached"] is True
    with pytest.raises(dc.ContinuationRefused, match="research_supplement_conflict"):
        world.controller.supplement_research_scope({**document, "captured": [root, successor]})

    receipt = receipt_for(world, research, investigation, dispatch)
    assert [a["job"] for a in receipt["attempts"]] == sorted([root, successor])
    accepted = world.controller.accept_research(receipt)
    assert accepted["coverage"] == "owner_supplement"
    assert accepted["supplement_sha256"] == supplements(world)[research["id"]]["supplement_sha256"]
    world.tick()
    intents = world.intents()
    assert intents[research["id"]]["state"] == dc.COMPLETED
    assert intents[research["id"]]["research_coverage"] == "owner_supplement"
    third = only(intents, origin_job=successor, route=dc.EVIDENCE_REPAIR)
    assert third["state"] == dc.ADMITTED and third["ownership"]["state"] == "inherited"
    # The original capture, the investigation and every failure verdict are exactly as they were.
    assert research_rows(world, investigation) == before
    assert {job: world.jobs()[job] for job in old_jobs} == old_jobs
    status = world.controller.status("policy-1")
    shown = only({row["id"]: row for row in status["intents"]}, id=research["id"])
    assert shown["receipt"]["coverage"] == "owner_supplement" and shown["supplement"]["captured"] == [root]
    other = [row for row in status["intents"] if row["route"] == dc.RESEARCH and row["id"] != research["id"]]
    assert other and all(row["supplement"] is None for row in other), "no other job or family is covered"
    world.tick(controller=world.build())
    assert len(world.jobs()) == len(old_jobs) + 1, "one successor across replays"


def _descendant(document, **change):
    return {"descendants": [{**document["descendants"][0], **change}]}


def _via_research_intent(document, world, ids):
    return _descendant(document, intent_id=document["intent_id"])


def _foreign_parent(document, world, ids):
    other = next(row for row in world.intents().values() if row["route"] == dc.EVIDENCE_REPAIR
                 and row["family"] != document["family"])
    return _descendant(document, parent_job=other["origin_job"], intent_id=other["id"])


def _arbitrary_job(document, world, ids):
    other = next(row for row in world.intents().values() if row["route"] == dc.EVIDENCE_REPAIR
                 and row["family"] != document["family"])
    extra = {"job": other["successor_job"], "parent_job": other["origin_job"], "intent_id": other["id"]}
    return {"descendants": document["descendants"] + [extra]}


def _captured_too_much(document, world, ids):
    return {"captured": sorted(document["captured"] + [document["descendants"][0]["job"]])}


def _incomplete(document, world, ids):
    return {"attempts": document["attempts"][:1]}


def _stale_sample(document, world, ids):
    return {"dispatch": {**document["dispatch"], "job_ids_sha256": "0" * 64}}


def _other_candidate(document, world, ids):
    return {"acceptance": {**document["acceptance"], "candidate_revision": "8" * 40}}


def _missing_attestation(document, world, ids):
    return {"attestation_ref": "sha256:" + hashlib.sha256(b"never stored").hexdigest()}


def _no_descendants(document, world, ids):
    return {"descendants": []}


@pytest.mark.parametrize("change, reason", [
    (_via_research_intent, "research_supplement_lineage_broken"),
    (_foreign_parent, "research_supplement_lineage_broken"),
    (_arbitrary_job, "research_supplement_scope_mismatch"),
    (_captured_too_much, "research_supplement_capture_mismatch"),
    (_incomplete, "research_coverage_partial"), (_stale_sample, "research_dispatch_mismatch"),
    (_other_candidate, "research_supplement_acceptance_unproven"),
    (_missing_attestation, "research_evidence_missing"), (_no_descendants, "research_supplement_invalid")])
def test_a_forged_foreign_partial_or_unproven_supplement_is_refused_and_stores_nothing(tmp_path, change, reason):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair, document = owned003(world, tmp_path)
    with pytest.raises(dc.ContinuationRefused) as info:
        world.controller.supplement_research_scope({**document, **change(document, world, (root, successor))})
    assert info.value.reason_code == reason
    assert supplements(world) == {}
    with pytest.raises(dc.ContinuationRefused, match="research_scope_unverified"):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))


def test_an_unowned_successor_or_an_unaccepted_review_never_registers(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair = accepted003(world, tmp_path)
    acceptance = accepted_promotion(world, dispatch)
    document = supplement_for(world, research, investigation, dispatch, repair, acceptance)
    with pytest.raises(dc.ContinuationRefused, match="research_supplement_ownership_mismatch"):
        world.controller.supplement_research_scope(document)
    world.controller.reconcile_ownership(repair["id"])
    with world.control.transaction() as tx:   # LABELLED injected fault: the review did not accept
        row = tx.get("decisions_pending", "review-003")
        tx.put("decisions_pending", "review-003", {**row, "result": {"accepted": False}})
    with pytest.raises(dc.ContinuationRefused, match="research_supplement_acceptance_unproven"):
        world.controller.supplement_research_scope(document)
    assert supplements(world) == {}


def test_concurrent_identical_supplements_store_one_row(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair, document = owned003(world, tmp_path)
    start, results = threading.Barrier(2), []

    def submit():
        start.wait()
        owner = Continuation(world.control, lanes=world.lanes, evidence=world.evidence)
        results.append(owner.supplement_research_scope(document))
    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r["cached"] for r in results) == [False, True] and len(supplements(world)) == 1


def _review_withdrawn(world, successor):
    with world.control.transaction() as tx:   # LABELLED injected fault: the accepted review changed
        row = tx.get("decisions_pending", "review-003")
        tx.put("decisions_pending", "review-003", {**row, "status": "retry"})
    return "research_supplement_acceptance_unproven", ("decisions_pending", "review-003", row)


def _attestation_lost(world, successor):
    ref = supplements(world)[next(iter(supplements(world)))]["supplement"]["attestation_ref"]
    path = stored_path(world, ref)
    data = path.read_bytes()
    path.unlink()   # LABELLED injected fault: the attestation bytes are gone
    return "research_evidence_missing", ("file", path, data)


def _ownership_changed(world, successor):
    with world.control.transaction() as tx:   # LABELLED injected fault: the successor's binding changed
        row = tx.get(BUCKET_BINDINGS, successor)
        tx.put(BUCKET_BINDINGS, successor, {**row, "project_id": "other"})
    return "research_supplement_ownership_mismatch", (BUCKET_BINDINGS, successor, row)


def _supplement_tampered(world, successor):
    with world.control.transaction() as tx:   # LABELLED injected fault: the stored supplement was edited
        [row] = tx.scan(BUCKET_RESEARCH_SUPPLEMENTS)
        tx.put(BUCKET_RESEARCH_SUPPLEMENTS, row["id"], {**row, "supplement": {**row["supplement"], "captured": []}})
    return "research_supplement_corrupt", (BUCKET_RESEARCH_SUPPLEMENTS, row["id"], row)


@pytest.mark.parametrize("fault", [_review_withdrawn, _attestation_lost, _ownership_changed, _supplement_tampered])
def test_consumption_rechecks_the_supplement_and_holds_until_it_verifies_again(tmp_path, fault):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair, document = owned003(world, tmp_path)
    world.controller.supplement_research_scope(document)
    world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    stored = deepcopy(receipts(world))
    reason, undo = fault(world, successor)
    result = world.tick(controller=world.build())
    assert [s["reason_code"] for s in result["skipped"] if s["subject"] == research["id"]] == [reason]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED and receipts(world) == stored
    jobs = len(world.jobs())
    if undo[0] == "file":
        undo[1].write_bytes(undo[2])
    else:
        with world.control.transaction() as tx:
            tx.put(*undo)
    world.tick()
    assert world.intents()[research["id"]]["state"] == dc.COMPLETED and len(world.jobs()) == jobs + 1


def test_a_new_attempt_after_the_supplement_refuses_both_its_receipt_and_a_reused_supplement(tmp_path):
    world = World(tmp_path)
    root, successor, research, investigation, dispatch, repair, document = owned003(world, tmp_path)
    world.controller.supplement_research_scope(document)
    receipt = receipt_for(world, research, investigation, dispatch)
    world.controller.accept_research(receipt)
    world.tick()
    third, _ = world.run_next(inspection="incomplete")   # the released repair fails again
    world.tick()
    again = only(world.intents(), origin_job=third, route=dc.RESEARCH)
    with pytest.raises(dc.ContinuationRefused, match="research_attempts_changed"):
        world.controller.supplement_research_scope({**document, "intent_id": again["id"]})
    with pytest.raises(dc.ContinuationRefused, match="research_attempts_changed"):
        world.controller.accept_research({**receipt, "intent_id": again["id"]})
    assert set(supplements(world)) == {research["id"]} and set(receipts(world)) == {research["id"]}


# ---- accepted investigation follow-up (SPEC "Accepted investigation follow-up for newly observed evidence") --
FOLLOWUP_SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["evidence_gate_refused"]}
FINISHED = "2026-09-24T00:00:00+00:00"


def settle_accepted(world, dispatch, revision="9" * 40):
    """LABELLED synthetic evidence of a fully settled ACCEPTED council run: the five council role tasks
    (succeeded, each bound to its recorded execution ref and a settled reservation), seven settled starts,
    the approved design, the accepted operation and `accepted_promotion`'s receipt and accepting review. No
    model or provider produced any of it; it is the shape the real run row records."""
    from codex_harness.domain.council import COUNCIL_AGENTS, COUNCIL_ORDER

    run_id, roles, slots = dispatch["run_id"], {}, []
    with world.control.transaction() as tx:
        for role in COUNCIL_ORDER:
            task_id = run_id + "." + role
            ref = "sha256:" + hashlib.sha256(task_id.encode("utf-8")).hexdigest()
            tx.put("tasks", task_id, {"id": task_id, "agent": COUNCIL_AGENTS[role], "status": "succeeded",
                                      "generation": 1, "attempt": 1, "result": {"execution_ref": ref},
                                      "message": {"correlation_id": "autonomous:" + run_id,
                                                  "what": {"details": {"role": role}}}})
            tx.put("invocation_reservations", "res-" + task_id, {"id": "res-" + task_id, "task_id": task_id,
                                                                 "status": "settled"})
            roles[role] = {"task_id": task_id, "execution_ref": ref}
            slots.append({"id": task_id, "kind": "task", "agent": COUNCIL_AGENTS[role], "settled": True,
                          "settle_error": None, "operation": None})
        for slot in ("impl-" + run_id, "review-" + run_id):
            slots.append({"id": slot, "kind": "task", "agent": "worker", "settled": True, "settle_error": None,
                          "operation": "op-" + run_id})
        run = tx.get("autonomous_runs", run_id)
        tx.put("autonomous_runs", run_id, {
            **run, "roles": roles, "starts": {"reserved": len(slots), "settled": len(slots), "slots": slots},
            "design": {"state": "design_approved"}, "finished_at": FINISHED,
            "operation": {"id": "op-" + run_id, "status": "accepted", "task_id": "impl-003", "decision_id": "review-003"}})
    return accepted_promotion(world, dispatch, revision)


def accepted_report(world, tmp_path):
    """The actual accepted-then-new-evidence shape: rp-001's report-only council ACCEPTED a dispatch that
    captured the root and another family's jobs; the root's evidence-repair successor is a member of the
    same investigation but was not yet bound, so the accepted snapshot never captured it."""
    world.register()
    root, successor, research = two_strikes(world, "op-x", "docs/a.md")
    two_strikes(world, "op-z", "docs/c.md")
    jobs = world.jobs()
    other = sorted(job for job in jobs if job not in {root, successor} and jobs[job]["status"] == "failed")
    owner = Portfolio(world.control, DEFINITIONS)
    for job in (root, *other):
        owner.bind(job, "ops", "c1")
    owner.reconcile()
    (tmp_path / "research").mkdir()
    env = build(tmp_path / "research", store=world.control, council=FakeCouncil(world.control, status="accepted"))
    registered(env, investigation_source=dict(FOLLOWUP_SOURCE))
    investigation = family_id("failed", "evidence_gate_refused")
    assert env.runner.tick("rp-001")["investigation"] == investigation
    with world.control.transaction() as tx:
        dispatch = deepcopy(tx.get(BUCKET_DISPATCHES, investigation))
        assert successor in tx.get(BUCKET_INVESTIGATIONS, investigation)["job_ids"]
    assert dispatch["result"] == "accepted" and successor not in dispatch["job_ids"]
    settle_accepted(world, dispatch)
    return env, owner, root, successor, research, investigation, dispatch


def followup_program(env, program_id="rp-002", **overrides):
    cfg = validate_config(config(env.head, **{"id": program_id, "investigation_source": dict(FOLLOWUP_SOURCE),
                                              **overrides}), POLICY)
    env.programs.register(cfg, env.identity, [])
    return config_digest(cfg, env.identity)


def followup_request(world, dispatch, job_ids, config_sha256, program="rp-002", version=0, lineage_sha=None, **pinned):
    with world.control.transaction() as tx:
        predecessor = tx.get("research_programs", dispatch["program"])
    ids = sorted(job_ids)
    return {"schema": "urn:zeus:research-dispatch-followup:1", "mode": "accepted_evidence_followup",
            "investigation": dispatch["investigation"],
            "predecessor": {"dispatch": dispatch["id"], "lineage_version": version, "lineage_request_sha256": lineage_sha,
                            "program": dispatch["program"], "config_sha256": predecessor["config_sha256"],
                            **{k: dispatch[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")},
                            **pinned},
            "members": {"previous_sha256": dispatch["job_ids_sha256"], "job_ids": ids, "sha256": digest(ids)},
            "replacement": {"program": program, "config_sha256": config_sha256}}


def lineage_rows(world):
    with world.control.transaction() as tx:
        return deepcopy((tx.scan("research_dispatch_successors"), tx.scan("research_dispatch_heads")))


def refused_code(call, *args) -> str:
    from codex_harness.domain.research_program import ProgramRefused

    with pytest.raises(ProgramRefused) as caught:
        call(*args)
    return caught.value.reason_code


def test_an_accepted_report_follow_up_captures_the_new_member_once_and_binds_only_the_new_receipt(tmp_path):
    """Accepted rp-001 + a newly bound authoritative member -> the owner's explicit follow-up authorizes rp-002
    once; registration alone releases nothing; rp-002's (LABELLED) council accepts a FRESH snapshot that
    captures the new member; only a receipt naming THAT dispatch approves, under its original capture."""
    from codex_harness.application.research_program import ResearchProgram

    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    captured = list(dispatch["job_ids"])
    with pytest.raises(dc.ContinuationRefused, match="research_scope_unverified"):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    sha = followup_program(env)
    # Unchanged authoritative membership: nothing new was observed, so nothing may be followed up.
    assert refused_code(env.programs.recover_dispatch, followup_request(world, dispatch, captured, sha), None) \
        == "followup_membership_unchanged"
    assert lineage_rows(world) == ([], [])

    owner.bind(successor, "ops", "c1")   # the owner binds the new member: authoritative, not owner-asserted
    keys = (investigation, dispatch["cycle"], "rp-001", dispatch["run_id"])
    buckets = (BUCKET_DISPATCHES, "research_program_cycles", "research_programs", "autonomous_runs")
    with world.control.transaction() as tx:
        before = deepcopy({b: {k: tx.get(b, k) for k in keys} for b in buckets})
    document = followup_request(world, dispatch, [*captured, successor], sha)
    result = env.programs.recover_dispatch(document, None)
    assert result["cached"] is False and result["state"] == "authorized" and result["proof"] == "accepted_report_followup"
    assert result["mode"] == "accepted_evidence_followup" and result["version"] == 2 and result["fence"] == []
    assert result["members"]["added"] == [successor] and result["members"]["previous_sha256"] == dispatch["job_ids_sha256"]
    assert result["replacement"]["dispatch"] == investigation + ".recovery-2"
    # The identical request replays after a restart; any other request for this head conflicts.
    assert ResearchProgram(world.control, clock=env.clock).recover_dispatch(document, None)["cached"] is True
    other = followup_program(env, "rp-009")
    assert refused_code(env.programs.recover_dispatch,
                        followup_request(world, dispatch, [*captured, successor], other, program="rp-009"), None) \
        == "recovery_conflict"
    # Registration alone releases no hold: the accepted predecessor no longer answers, nothing approves.
    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_unknown"):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    assert receipts(world) == {}

    env.programs.resume("rp-002")
    env.runner.council = FakeCouncil(world.control, status="accepted")
    env.clock.value = "2028-01-01T02:00:00+00:00"
    assert env.runner.tick("rp-002")["result"] == "accepted"
    with world.control.transaction() as tx:
        current = deepcopy(tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2"))
        after = {b: {k: tx.get(b, k) for k in keys} for b in buckets}
        row = tx.get("research_dispatch_successors", investigation + ":2")
    assert after == before, "the accepted predecessor's dispatch, cycle, program and run stay history"
    assert set(current["job_ids"]) == {*captured, successor} and current["job_ids_sha256"] == document["members"]["sha256"]
    assert current["supersedes"]["dispatch"] == investigation and current["recovery"] == investigation + ":2"
    assert row["state"] == "claimed" and row["replacement"]["cycle"] == current["cycle"]
    assert env.programs.recover_dispatch(document, None)["cached"] is True, "the claimed head replays, never twice"

    with pytest.raises(dc.ContinuationRefused, match="research_dispatch_mismatch"):
        world.controller.accept_research(receipt_for(world, research, investigation, dispatch))
    accepted = world.controller.accept_research(receipt_for(world, research, investigation, current))
    assert accepted["accepted"] is True and accepted["dispatch"]["run_id"] == "rp-002.c001"
    assert accepted["coverage"] == dc.COVERAGE_ORIGINAL, "the fresh snapshot captured the new member itself"
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.COMPLETED

    # No unchanged replay: a follow-up of the new accepted head with the same membership refuses, and a
    # request still pinning the former initial dispatch names an occupied head.
    settle_accepted(world, current, revision="8" * 40)
    third = followup_program(env, "rp-003")
    head = lineage_rows(world)[1][0]
    again = followup_request(world, current, current["job_ids"], third, program="rp-003", version=2,
                             lineage_sha=head["request_sha256"])
    assert refused_code(env.programs.recover_dispatch, again, None) == "followup_membership_unchanged"
    stale = followup_request(world, dispatch, [*captured, successor], third, program="rp-003")
    assert refused_code(env.programs.recover_dispatch, stale, None) == "recovery_conflict"
    assert len(lineage_rows(world)[0]) == 1


def _mutate(bucket, key, change):
    def fault(world, dispatch):
        name = key(dispatch) if callable(key) else key
        with world.control.transaction() as tx:
            row = deepcopy(tx.get(bucket, name))
            change(row, dispatch)
            tx.put(bucket, name, row)
    return fault


def _run(change):
    return _mutate("autonomous_runs", lambda d: d["run_id"], change)


def _task(change):
    return _mutate("tasks", lambda d: d["run_id"] + ".dba", change)


def _add(bucket, key, body):
    def fault(world, dispatch):
        with world.control.transaction() as tx:
            tx.put(bucket, key, {**body, "task_id": dispatch["run_id"] + ".dba",
                                 "message": {"correlation_id": "autonomous:" + dispatch["run_id"]}})
    return fault


def _termination(bucket, task, status):
    """An actual-shaped termination record (`Observer.mark_unconfirmed`): keyed by its digest `record_id`,
    owned by its (`bucket`, `task_id`), never by its key."""
    def fault(world, dispatch):
        task_id = task(dispatch) if callable(task) else task
        record_id = Observer.termination_id({"id": task_id, "_bucket": bucket, "generation": 1, "attempt": 1})
        with world.control.transaction() as tx:
            tx.put("observation_terminations", record_id, {
                "record_id": record_id, "status": status, "task_id": task_id, "bucket": bucket, "generation": 1,
                "attempt": 1, "reservation_id": "res-" + task_id, "boundary": "reserved", "invocation_outcome": "unknown"})
    return fault


def _council_task(dispatch):
    return dispatch["run_id"] + ".dba"


FOLLOWUP_FAULTS = [
    ("slot_unsettled", _run(lambda r, d: r["starts"]["slots"][0].update(settled=False)), "recovery_invocation_unsettled"),
    ("six_starts", _run(lambda r, d: r["starts"].update(slots=r["starts"]["slots"][:6], reserved=6, settled=6)),
     "recovery_invocation_unsettled"),
    ("reservation_open", _mutate("invocation_reservations", lambda d: "res-" + d["run_id"] + ".dba",
                                 lambda r, d: r.update(status="reserved")), "recovery_invocation_unsettled"),
    ("terminated", _add("observation_terminations", "term-1", {"id": "term-1"}), "recovery_effect_unknown"),
    ("council_unconfirmed", _termination("tasks", _council_task, "unconfirmed"), "recovery_effect_unknown"),
    ("council_pending", _termination("tasks", _council_task, "pending_reconciliation"), "recovery_effect_unknown"),
    ("worker_unconfirmed", _termination("tasks", "impl-003", "unconfirmed"), "recovery_effect_unknown"),
    ("review_pending", _termination("decisions_pending", "review-003", "pending_reconciliation"),
     "recovery_effect_unknown"),
    ("task_running", _task(lambda r, d: r.update(status="running")), "recovery_predecessor_active"),
    ("task_failed", _task(lambda r, d: r.update(status="failed")), "recovery_effect_unknown"),
    ("execution_changed", _task(lambda r, d: r.update(result={"execution_ref": "sha256:" + "0" * 64})),
     "recovery_evidence_mismatch"),
    ("unsent_publication", _add("outbox", "late-1", {"sent": False}), "recovery_effect_unknown"),
    ("design_open", _run(lambda r, d: r.update(design={"state": "needs_research"})), "followup_acceptance_unproven"),
    ("review_withdrawn", _mutate("decisions_pending", "review-003", lambda r, d: r.update(result={"accepted": False})),
     "followup_acceptance_unproven"),
    ("foreign_promotion", _mutate("promotions", lambda d: d["run_id"], lambda r, d: r.update(graph_sha256="6" * 64)),
     "followup_acceptance_unproven"),
    ("run_rejected", _run(lambda r, d: r.update(status="rejected")), "followup_predecessor_not_accepted"),
    ("dispatch_rejected", _mutate(BUCKET_DISPATCHES, lambda d: d["id"], lambda r, d: r.update(result="rejected")),
     "followup_predecessor_not_accepted"),
    ("dispatch_open", _mutate(BUCKET_DISPATCHES, lambda d: d["id"], lambda r, d: r.update(state="dispatched")),
     "recovery_predecessor_active"),
    ("program_busy", _mutate("research_programs", "rp-001", lambda r, d: r.update(active_cycle="rp-001:002")),
     "recovery_predecessor_active"),
    ("runtime_edit", _mutate("research_programs", "rp-001",
                             lambda r, d: r["config"]["template"]["plan"].update(allowed_paths=["src/codex_harness/x.py"])),
     "followup_not_report_only"),
    ("investigation_decided", _mutate(BUCKET_INVESTIGATIONS, lambda d: d["investigation"],
                                      lambda r, d: r.update(state="researched")), "recovery_investigation_changed"),
]


def test_active_unknown_unproven_or_runtime_edit_predecessors_refuse_and_write_nothing(tmp_path):
    """Each LABELLED injected fault is applied alone to the settled accepted world, then undone."""
    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    document = followup_request(world, dispatch, [*dispatch["job_ids"], successor], followup_program(env))
    with world.control.lock:
        clean = deepcopy(world.control.data)
    observed = {}
    for name, fault, _ in FOLLOWUP_FAULTS:
        fault(world, dispatch)
        observed[name] = refused_code(env.programs.recover_dispatch, document, None)
        assert lineage_rows(world) == ([], []), name
        with world.control.lock:
            world.control.data = deepcopy(clean)
    assert observed == {name: code for name, _, code in FOLLOWUP_FAULTS}
    assert env.programs.recover_dispatch(document, None)["state"] == "authorized", "the clean world authorizes"


def test_settled_or_foreign_termination_records_do_not_block_the_followup(tmp_path):
    """Closed and operator-resolved markers of the run's own tasks, and an unresolved marker of another
    task (or of the right id in another bucket), are not the accepted predecessor's unknown effects."""
    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    document = followup_request(world, dispatch, [*dispatch["job_ids"], successor], followup_program(env))
    for fault in (_termination("tasks", _council_task, "closed"), _termination("tasks", "impl-003", "resolved"),
                  _termination("decisions_pending", "review-003", "closed"),
                  _termination("tasks", "foreign-task", "unconfirmed"),
                  _termination("decisions_pending", "impl-003", "pending_reconciliation")):
        fault(world, dispatch)
    assert env.programs.recover_dispatch(document, None)["state"] == "authorized"


def test_stale_foreign_or_missing_evidence_and_changed_authority_refuse_and_write_nothing(tmp_path):
    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    sha, members = followup_program(env), [*dispatch["job_ids"], successor]
    wider = followup_program(env, "rp-004", investigation_source={**FOLLOWUP_SOURCE,
                                                                   "reason_codes": ["evidence_gate_refused", "x"]})
    previous = followup_request(world, dispatch, members, sha)
    previous["members"]["previous_sha256"] = "3" * 64
    cases = {
        "foreign_run": (followup_request(world, dispatch, members, sha, run_id="rp-009.c001"), "recovery_dispatch_mismatch"),
        "stale_head": (followup_request(world, {**dispatch, "id": investigation + ".recovery-1"}, members, sha,
                                        version=1, lineage_sha="1" * 64), "recovery_successor_corrupt"),
        "missing_member": (followup_request(world, dispatch, dispatch["job_ids"][:-1] + [successor], sha),
                           "followup_membership_mismatch"),
        "foreign_member": (followup_request(world, dispatch, [*members, "op-foreign"], sha), "followup_membership_mismatch"),
        "changed_authority": (followup_request(world, dispatch, members, wider, program="rp-004"), "recovery_scope_changed"),
        "unregistered": (followup_request(world, dispatch, members, "2" * 64), "recovery_replacement_mismatch"),
        "stale_capture": (previous, "recovery_dispatch_mismatch"),
    }
    for name, (document, code) in cases.items():
        assert refused_code(env.programs.recover_dispatch, document, None) == code, name
    assert lineage_rows(world) == ([], [])
    for change in ({"mode": "settled_read_only_successor"}, {"extra": 1}):
        document = {**followup_request(world, dispatch, members, sha), **change}
        assert refused_code(env.programs.recover_dispatch, document, None) == "followup_request_invalid"
    forged = followup_request(world, dispatch, members, sha)
    forged["members"]["sha256"] = "4" * 64
    assert refused_code(env.programs.recover_dispatch, forged, None) == "followup_request_invalid"
    assert lineage_rows(world) == ([], [])


def test_membership_drift_after_authorization_holds_the_claim_until_it_is_exact_again(tmp_path):
    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    document = followup_request(world, dispatch, [*dispatch["job_ids"], successor], followup_program(env))
    env.programs.recover_dispatch(document, None)
    env.programs.resume("rp-002")
    with world.control.transaction() as tx:   # LABELLED injected fault: the new member's binding moves project
        binding = deepcopy(tx.get(BUCKET_BINDINGS, successor))
        tx.put(BUCKET_BINDINGS, successor, {**binding, "project_id": "elsewhere"})
    env.clock.value = "2028-01-01T02:00:00+00:00"
    reserved = env.programs.reserve_cycle("rp-002", env.identity)
    recorded = env.programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [],
                                              {"this_host": 0, "all_hosts": 0})
    assert recorded["candidate"] is None and recorded["cycle"]["investigations"]["counts"]["claimed"] == 1
    env.programs.complete_cycle(reserved["cycle"]["id"], reserved["cycle"]["owner"])
    with world.control.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2") is None, "never silently recaptured"
        assert tx.get("research_dispatch_successors", investigation + ":2")["state"] == "authorized"
        tx.put(BUCKET_BINDINGS, successor, binding)
    env.runner.council = FakeCouncil(world.control, status="accepted")
    env.clock.value = "2028-01-01T04:00:00+00:00"
    assert env.runner.tick("rp-002")["result"] == "accepted"
    with world.control.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2")["job_ids_sha256"] == document["members"]["sha256"]


def test_concurrent_follow_up_requests_record_one_row_and_one_claim(tmp_path):
    from codex_harness.application.research_program import ResearchProgram

    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    document = followup_request(world, dispatch, [*dispatch["job_ids"], successor], followup_program(env))
    results, errors = [], []

    def request():
        try:
            results.append(ResearchProgram(world.control, clock=env.clock).recover_dispatch(document, None))
        except Exception as exc:   # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=request) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and len(results) == 4 and sum(not r["cached"] for r in results) == 1
    successors, heads = lineage_rows(world)
    assert len(successors) == 1 and len(heads) == 1
    env.programs.resume("rp-002")
    env.clock.value = "2028-01-01T02:00:00+00:00"
    env.runner.tick("rp-002")
    with world.control.transaction() as tx:
        assert sorted(d["id"] for d in tx.scan(BUCKET_DISPATCHES)) == [investigation, investigation + ".recovery-2"]


def test_a_failed_follow_up_stays_held_and_is_never_followed_up_again(tmp_path):
    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    members = [*dispatch["job_ids"], successor]
    env.programs.recover_dispatch(followup_request(world, dispatch, members, followup_program(env)), None)
    env.programs.resume("rp-002")
    env.runner.council = FakeCouncil(world.control, status="rejected")
    env.clock.value = "2028-01-01T02:00:00+00:00"
    assert env.runner.tick("rp-002")["result"] == "rejected"
    with world.control.transaction() as tx:
        current = deepcopy(tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2"))
        head = deepcopy(tx.get("research_dispatch_heads", investigation))
    with pytest.raises(dc.ContinuationRefused, match="research_not_accepted"):
        world.controller.accept_research(receipt_for(world, research, investigation, current))
    world.tick()
    assert only(world.intents(), id=research["id"])["state"] == dc.RESEARCH_REQUIRED
    again = followup_request(world, current, members, followup_program(env, "rp-003"), program="rp-003", version=2,
                             lineage_sha=head["request_sha256"])
    assert refused_code(env.programs.recover_dispatch, again, None) == "followup_predecessor_not_accepted"


def test_the_cli_follow_up_reads_the_control_store_only_and_builds_no_bus(tmp_path, monkeypatch):
    from codex_harness.adapters.research_program_cli import recover

    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    path = tmp_path / "followup.json"
    path.write_text(json.dumps(followup_request(world, dispatch, [*dispatch["job_ids"], successor],
                                                followup_program(env))), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("the follow-up must not build a bus or an artifact port")
    monkeypatch.setattr("codex_harness.adapters.bus.RedisBus", forbidden)
    monkeypatch.setattr("codex_harness.adapters.autonomous_evidence.ExecutionEvidence", forbidden)
    service, args = type("Service", (), {"store": world.control})(), type("Args", (), {"file": path})()
    result = recover(service, args)
    assert result["exit_code"] == 0 and result["proof"] == "accepted_report_followup" and result["state"] == "authorized"


# ---- accepted follow-up report scope binding (SPEC "Accepted follow-up report scope binding") ----------------
OLD_PAIR = "Analyze ONLY the delivery-tree/cont-8a33 failure pair"
NEW_PAIR = "Analyze ONLY the cont-fe15931105e915769378e016 and cont-6adfa87f8938c830ab60ac35 failure pair"


def report_template(head, objective=OLD_PAIR, **changes):
    """The fixture template with the report objective set; `changes` maps a template field to a dict merged
    into it (or to a whole value for a non-dict field)."""
    from test_research_program_fixtures import template

    document = template(head)
    document["plan"]["objective"] = objective
    for name, value in changes.items():
        document[name] = {**document[name], **value} if isinstance(value, dict) else value
    return document


def new_pair_changes():
    """Every report-content field the SPEC admits, re-pointed at the newly authorized pair."""
    return {"goal": {"sha256": "b" * 64, "criterion": "whole-loop criterion at the newer goal"},
            "plan": {"objective": NEW_PAIR, "acceptance_criteria": ["the new pair's cause is named with evidence"]},
            "research": {"topic": "new pair evidence gate", "questions": ["Why did the new pair fail?"],
                         "search_scope": ["docs", "src/codex_harness/domain"]},
            "current_state": {"records": [{"bucket": "tasks", "id": "t-2"}], "max_age_seconds": 900}}


def pinned_config(head, program_id, template, **overrides):
    return validate_config(config(head, **{"id": program_id, "investigation_source": dict(FOLLOWUP_SOURCE),
                                           "template": template, **overrides}), POLICY)


def test_followup_scope_admits_only_report_content_and_narrowing_and_never_loosens_same_authority():
    from codex_harness.domain.research_program import followup_scope, same_authority

    head = "a" * 40
    old = pinned_config(head, "rp-001", report_template(head))
    new = pinned_config("c" * 40, "rp-002", report_template("c" * 40, NEW_PAIR, **new_pair_changes()),
                        deadline="2029-07-01T00:00:00+00:00")
    assert same_authority(old, new) is False, "legacy failure recovery stays exact: a report change is refused there"
    scope = followup_scope(old, new)
    assert scope["content"]["changed"] == ["current_state", "goal.criterion", "goal.sha256", "plan.acceptance_criteria",
                                           "plan.objective", "research"]
    assert scope["content"]["previous_sha256"] != scope["content"]["sha256"]
    assert scope["authority"]["previous_sha256"] == scope["authority"]["sha256"] and scope["authority"]["narrowed"] == []
    same = followup_scope(old, pinned_config(head, "rp-002", report_template(head)))
    assert same["content"]["changed"] == [] and same["content"]["sha256"] == same["content"]["previous_sha256"]

    # Narrowing is admitted and named, never hidden as "same".
    wide = pinned_config(head, "rp-001", report_template(head, plan={"allowed_paths": ["docs/RUNBOOK.md", "docs/B.md"]}))
    narrow = followup_scope(wide, pinned_config(head, "rp-002", report_template(head, NEW_PAIR), max_cycles=1,
                                                max_adoptions=0))
    assert narrow["authority"]["narrowed"] == ["max_adoptions", "max_cycles", "template.plan.allowed_paths"]
    assert narrow["authority"]["previous_sha256"] != narrow["authority"]["sha256"]

    source = dict(FOLLOWUP_SOURCE)
    refused = {
        "project": dict(investigation_source={**source, "project_ids": ["ops", "other"]}),
        "reason": dict(investigation_source={**source, "reason_codes": ["evidence_gate_refused", "x"]}),
        "topics": dict(topics=[{"id": "storage", "keywords": ["advisory lock"]}]),
        "local": dict(local_candidates=[]),
        "interval": dict(interval_seconds=60),
        "more_cycles": dict(max_cycles=3),
        "more_adoptions": dict(max_adoptions=2),
        "budget": dict(budget={"per_host": 10, "total": 30},
                       template=report_template(head, NEW_PAIR, budget={"per_host": 10, "total": 30})),
        "model": dict(template=report_template(head, NEW_PAIR, claude={"model": "claude-other-model"})),
        "claude_budget": dict(template=report_template(head, NEW_PAIR, claude={"max_budget_usd": 5})),
        "timeout": dict(template=report_template(head, NEW_PAIR, claude={"timeout_seconds": 600})),
        "goal_path": dict(template=report_template(head, NEW_PAIR, goal={"path": "docs/OTHER.md"})),
        "template_id": dict(template=report_template(head, NEW_PAIR, id="council-other")),
        "path_widened": dict(template=report_template(head, NEW_PAIR, plan={"allowed_paths": ["docs/RUNBOOK.md",
                                                                                               "docs/NEW.md"]})),
        "path_moved": dict(template=report_template(head, NEW_PAIR, plan={"allowed_paths": ["docs/NEW.md"]})),
        "runtime_edit": dict(template=report_template(head, NEW_PAIR, plan={"allowed_paths": ["src/codex_harness/x.py"]})),
    }
    for name, overrides in refused.items():
        candidate = pinned_config(head, "rp-002", overrides.pop("template", report_template(head, NEW_PAIR)), **overrides)
        assert followup_scope(old, candidate) is None, name
    without = {k: v for k, v in old.items() if k != "investigation_source"}
    malformed = [None, {}, {**new, "template": None}, {**new, "template": {**new["template"], "plan": None}},
                 {**new, "max_cycles": "1"}]
    assert followup_scope(without, {k: v for k, v in new.items() if k != "investigation_source"}) is None
    assert [followup_scope(old, m) for m in malformed] == [None] * len(malformed)
    assert followup_scope(None, new) is None


def test_an_owner_pinned_new_pair_report_follow_up_authorizes_claims_and_records_the_transition(tmp_path):
    """Real-shaped: the accepted report investigated one pair; the owner pins a NEW registered config whose
    report content names ONLY the new pair. Recover authorizes (legacy `same_authority` would refuse), the row
    and view carry both authority and content digests, and the claimed council runs the new content under the
    predecessor's unchanged model, budget and report paths."""
    from codex_harness.domain.research_program import same_authority

    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    changes = new_pair_changes()
    changes["goal"] = {"criterion": "whole-loop criterion for the new pair"}   # the fixture goal bytes stay bound
    sha = followup_program(env, template=report_template(env.head, NEW_PAIR, **changes))
    with world.control.transaction() as tx:
        old, new = deepcopy(tx.get("research_programs", "rp-001")), deepcopy(tx.get("research_programs", "rp-002"))
    assert same_authority(old["config"], new["config"]) is False
    document = followup_request(world, dispatch, [*dispatch["job_ids"], successor], sha)
    result = env.programs.recover_dispatch(document, None)
    assert result["state"] == "authorized" and result["proof"] == "accepted_report_followup"
    scope = result["scope"]
    assert scope["content"]["changed"] == ["current_state", "goal.criterion", "plan.acceptance_criteria",
                                           "plan.objective", "research"]
    assert scope["authority"]["sha256"] == scope["authority"]["previous_sha256"]
    with world.control.transaction() as tx:
        assert tx.get("research_dispatch_successors", investigation + ":2")["scope"] == scope
    assert env.programs.recover_dispatch(document, None)["cached"] is True

    env.programs.resume("rp-002")
    env.runner.council = council = FakeCouncil(world.control, status="accepted")
    env.clock.value = "2028-01-01T02:00:00+00:00"
    assert env.runner.tick("rp-002")["result"] == "accepted"
    manifest = council.manifests[-1]
    assert manifest["plan"]["objective"] == NEW_PAIR
    assert manifest["plan"]["allowed_paths"] == old["config"]["template"]["plan"]["allowed_paths"]
    assert manifest["claude"] == old["config"]["template"]["claude"] and manifest["budget"] == old["config"]["budget"]
    with world.control.transaction() as tx:
        current = deepcopy(tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2"))
        assert tx.get("research_dispatch_successors", investigation + ":2")["state"] == "claimed"
    assert current["job_ids_sha256"] == document["members"]["sha256"]


def test_followup_authority_broadening_stale_or_malformed_bindings_refuse_and_write_nothing(tmp_path):
    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    members, head = [*dispatch["job_ids"], successor], env.head

    def program(program_id, template=None, repository=None, **overrides):
        cfg = pinned_config(head, program_id, template or report_template(head, NEW_PAIR), **overrides)
        env.programs.register(cfg, repository or env.identity, [])
        return config_digest(cfg, repository or env.identity)
    cases = {
        "repository": ("rp-011", program("rp-011", repository="other-repository")),
        "model": ("rp-012", program("rp-012", report_template(head, NEW_PAIR, claude={"model": "claude-other-model"}))),
        "budget": ("rp-013", program("rp-013", report_template(head, NEW_PAIR, budget={"per_host": 20, "total": 40}),
                                     budget={"per_host": 20, "total": 40})),
        "cycles": ("rp-014", program("rp-014", max_cycles=3)),
        "paths": ("rp-015", program("rp-015", report_template(head, NEW_PAIR, plan={
            "allowed_paths": ["docs/RUNBOOK.md", "docs/zeus/NEW.md"]}))),
        "projects": ("rp-016", program("rp-016", investigation_source={**FOLLOWUP_SOURCE, "project_ids": ["ops", "x"]})),
    }
    for name, (program_id, sha) in cases.items():
        request = followup_request(world, dispatch, members, sha, program=program_id)
        assert refused_code(env.programs.recover_dispatch, request, None) == "recovery_scope_changed", name
    valid = program("rp-002")
    assert refused_code(env.programs.recover_dispatch, followup_request(world, dispatch, members, "5" * 64), None) \
        == "recovery_replacement_mismatch"
    assert refused_code(env.programs.recover_dispatch,
                        followup_request(world, dispatch, members, valid, program="rp-099"), None) \
        == "recovery_replacement_mismatch"
    malformed = followup_request(world, dispatch, members, valid)
    malformed["replacement"]["config_sha256"] = "not-a-digest"
    assert refused_code(env.programs.recover_dispatch, malformed, None) == "followup_request_invalid"
    with world.control.transaction() as tx:   # LABELLED injected fault: the new member is bound to another project
        tx.put(BUCKET_BINDINGS, successor, {**tx.get(BUCKET_BINDINGS, successor), "project_id": "elsewhere"})
    assert refused_code(env.programs.recover_dispatch, followup_request(world, dispatch, members, valid), None) \
        == "followup_membership_mismatch"
    assert lineage_rows(world) == ([], [])


@pytest.mark.parametrize("fault", ["predecessor_config", "replacement_registration"])
def test_a_scope_bound_follow_up_is_held_at_claim_when_either_registered_config_changed(tmp_path, fault):
    """LABELLED injected faults after authorization: the pinned replacement registration, or the predecessor
    config it was compared with, no longer recomputes to the recorded transition, so nothing is claimed until
    it is exact again."""
    world = World(tmp_path)
    env, owner, root, successor, research, investigation, dispatch = accepted_report(world, tmp_path)
    owner.bind(successor, "ops", "c1")
    sha = followup_program(env, template=report_template(env.head, NEW_PAIR))
    env.programs.recover_dispatch(followup_request(world, dispatch, [*dispatch["job_ids"], successor], sha), None)
    env.programs.resume("rp-002")
    key = "rp-001" if fault == "predecessor_config" else "rp-002"
    field = "config" if fault == "predecessor_config" else "config_sha256"
    with world.control.transaction() as tx:
        changed = deepcopy(tx.get("research_programs", key))
        clean = deepcopy(changed[field])
        if fault == "predecessor_config":
            changed["config"]["template"]["claude"]["model"] = "claude-other-model"
        else:
            changed["config_sha256"] = "6" * 64
        tx.put("research_programs", key, changed)
    env.clock.value = "2028-01-01T02:00:00+00:00"
    reserved = env.programs.reserve_cycle("rp-002", env.identity)
    recorded = env.programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [],
                                              {"this_host": 0, "all_hosts": 0})
    assert recorded["candidate"] is None
    env.programs.complete_cycle(reserved["cycle"]["id"], reserved["cycle"]["owner"])
    with world.control.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2") is None, "never claimed under a changed scope"
        assert tx.get("research_dispatch_successors", investigation + ":2")["state"] == "authorized"
        tx.put("research_programs", key, {**tx.get("research_programs", key), field: clean})
    env.runner.council = FakeCouncil(world.control, status="accepted")
    env.clock.value = "2028-01-01T04:00:00+00:00"
    assert env.runner.tick("rp-002")["result"] == "accepted"
    with world.control.transaction() as tx:
        assert tx.get(BUCKET_DISPATCHES, investigation + ".recovery-2") is not None


# ---- mixed-cause family receipt (SPEC "Mixed-cause continuation research receipt") ------------------------
MIXED_ATTESTATION = ("LABELLED fixture owner attestation: the owner read the accepted report and judges that it covers "
                     "the lead-rejected parent and its evidence-refused successor as distinct causes (owner "
                     "judgment, not a model verdict)\n")


def mixed_family(world, tmp_path):
    """The actual shape of hold ed1af386: a rejected root whose correction was rejected again (the
    first research hold, released by its own schema-1 receipt over the `lead_rejected` investigation),
    then the next correction failed the evidence gate. The second hold covers the rejected parent and the
    evidence-refused child; an unrelated evidence-refused family fills the `evidence_gate_refused`
    investigation, whose accepted current dispatch captures the child but never the parent."""
    world.register()
    world.enqueue("op-x", "docs/a.md")
    world.tick()
    root, first = world.run_next(verdict=False)
    world.tick()
    parent, second = world.run_next(verdict=False)
    assert (first["status"], first["reason_code"]) == (second["status"], second["reason_code"]) == ("rejected",
                                                                                                    "lead_rejected")
    world.tick()
    earlier = only(world.intents(), origin_job=parent, route=dc.RESEARCH)
    rejected_investigation, rejected_dispatch = research_dispatch(world, tmp_path, [root, parent])
    world.controller.accept_research(receipt_for(world, earlier, rejected_investigation, rejected_dispatch))
    world.tick()
    assert world.intents()[earlier["id"]]["state"] == dc.COMPLETED
    edge = only(world.intents(), origin_job=parent, route=dc.CORRECTION)
    child, receipt = world.run_next(inspection="incomplete")
    assert child == edge["successor_job"] and receipt["reason_code"] == "evidence_gate_refused"
    world.tick()
    research = only(world.intents(), origin_job=child, route=dc.RESEARCH)
    assert research["state"] == dc.RESEARCH_REQUIRED and research["family"] == root
    other, other_successor, _ = two_strikes(world, "op-z", "docs/c.md")
    investigation, dispatch = research_dispatch(world, tmp_path, [child, other, other_successor], program="rp-002",
                                                folder="research-mixed")
    assert child in dispatch["job_ids"] and parent not in dispatch["job_ids"]
    return {"root": root, "parent": parent, "child": child, "edge": edge, "earlier": earlier, "research": research,
            "investigation": investigation, "dispatch": dispatch, "rejected_investigation": rejected_investigation,
            "acceptance": accepted_promotion(world, dispatch)}


def mixed_for(world, family, **overrides):
    """What the owner submits: the status projection's attempt set, each member's inspection from its
    lane and its OWN investigation, status and reason from the Fleet row, the persisted edge, the current
    dispatch, the accepted report's promotion binding and the stored attestation."""
    base = receipt_for(world, family["research"], family["investigation"], family["dispatch"])
    jobs = world.jobs()
    attempts = [{**a, "status": jobs[a["job"]]["status"], "reason_code": jobs[a["job"]]["reason_code"],
                 "investigation": family_id(jobs[a["job"]]["status"], jobs[a["job"]]["reason_code"])}
                for a in base["attempts"]]
    attestation = world.artifacts.put(MIXED_ATTESTATION, "owner-attestation")["ref"]
    return {**base, "schema": dc.MIXED_RECEIPT_SCHEMA, "attempts": attempts,
            "lineage": [{"parent_job": family["parent"], "job": family["child"], "intent_id": family["edge"]["id"]}],
            "dispatch": {**base["dispatch"], "id": family["dispatch"]["id"],
                         "job_ids_sha256": family["dispatch"]["job_ids_sha256"]},
            "captured": [family["child"]], "acceptance": family["acceptance"], "attestation_ref": attestation,
            **overrides}


def test_actual_mixed_family_is_refused_by_schema1_and_released_once_by_the_mixed_receipt_into_evidence_repair(
        tmp_path):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    research, parent, child = family["research"], family["parent"], family["child"]
    # The reproduced boundary: the unchanged schema-1 gate refuses the truthful mixed set by membership.
    with pytest.raises(dc.ContinuationRefused, match="research_investigation_membership"):
        world.controller.accept_research(receipt_for(world, research, family["investigation"], family["dispatch"]))
    assert set(receipts(world)) == {family["earlier"]["id"]}
    before_rows = research_rows(world, family["investigation"]) + research_rows(world, family["rejected_investigation"])
    before_intents = {key: row for key, row in deepcopy(world.intents()).items() if key != research["id"]}
    before_jobs, before_receipts = deepcopy(world.jobs()), deepcopy(receipts(world))

    document = mixed_for(world, family)
    assert [a["job"] for a in document["attempts"]] == sorted([parent, child])
    accepted = world.controller.accept_research(document)
    assert accepted["accepted"] is True and accepted["cached"] is False and accepted["coverage"] == "mixed_family"
    assert {c["job"]: (c["status"], c["reason_code"]) for c in accepted["causes"]} == {
        parent: ("rejected", "lead_rejected"), child: ("failed", "evidence_gate_refused")}
    assert accepted["captured"] == [child] and accepted["lineage"][0]["intent_id"] == family["edge"]["id"]
    assert accepted["acceptance"] == family["acceptance"] and "no shared cause" in accepted["mixed_authority"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED, "acceptance moves nothing"

    result = world.tick()
    intents = world.intents()
    done = intents[research["id"]]
    assert {"subject": research["id"], "effect": "research_resolved", "route": dc.RESEARCH} in result["actions"]
    assert done["state"] == dc.COMPLETED and done["research_coverage"] == "mixed_family"
    assert done["research_receipt"] == receipts(world)[research["id"]]["receipt_sha256"]
    # The existing route selection continues: evidence repair of the retained candidate, never a new correction.
    repair = only(intents, origin_job=child, route=dc.EVIDENCE_REPAIR)
    assert repair["state"] == dc.ADMITTED and repair["family"] == family["root"]
    assert world.binding(repair["successor_job"])["workspace"]["head"] == "c" * 40
    assert "Evidence repair" in world.jobs()[repair["successor_job"]]["manifest"]["plan"]["objective"]
    # The correction count is the family's history, never reset: three successors, old rows untouched.
    successors = [row for row in intents.values() if row["family"] == family["root"] and row["route"] in
                  dc.SUCCESSOR_ROUTES]
    assert sorted(row["route"] for row in successors) == [dc.CORRECTION, dc.CORRECTION, dc.EVIDENCE_REPAIR]
    assert {key: intents[key] for key in before_intents} == before_intents
    assert {job: world.jobs()[job] for job in before_jobs} == before_jobs
    assert world.jobs()[parent]["status"] == "rejected", "the historical rejection stays rejected"
    after_rows = research_rows(world, family["investigation"]) + research_rows(world, family["rejected_investigation"])
    assert after_rows == before_rows
    assert {key: receipts(world)[key] for key in before_receipts} == before_receipts
    # Replays: the identical receipt is cached, a restarted controller admits nothing more.
    stored, count = deepcopy(receipts(world)), len(world.jobs())
    assert world.controller.accept_research(document)["cached"] is True
    world.tick(controller=world.build())
    assert receipts(world) == stored and len(world.jobs()) == count
    status = world.controller.status("policy-1")
    shown = {row["id"]: row for row in status["intents"]}
    assert shown[research["id"]]["receipt"]["coverage"] == "mixed_family"
    assert shown[research["id"]]["receipt"]["causes"] == accepted["causes"]
    legacy = shown[family["earlier"]["id"]]["receipt"]
    assert legacy["coverage"] == "original_capture" and "causes" not in legacy, "a schema-1 view is unchanged"


def _attempt(document, job, **change):
    return {"attempts": [{**a, **change} if a["job"] == job else a for a in document["attempts"]]}


def _edge(document, **change):
    return {"lineage": [{**document["lineage"][0], **change}]}


def _unrelated(document, world, family):
    """A well-formed receipt that adds another family's captured evidence-refused job, joined by that
    family's own persisted repair intent: same reason, not a member of this hold."""
    other = next(row for row in world.intents().values() if row["route"] == dc.EVIDENCE_REPAIR
                 and row["family"] != document["family"] and row["successor_job"] in family["dispatch"]["job_ids"])
    child = next(a for a in document["attempts"] if a["job"] == family["child"])
    return {"attempts": document["attempts"] + [{**child, "job": other["successor_job"]}],
            "lineage": document["lineage"] + [{"parent_job": family["child"], "job": other["successor_job"],
                                               "intent_id": other["id"]}],
            "captured": sorted([family["child"], other["successor_job"]])}


def _mutate_row(bucket, key_of, change):
    """A LABELLED injected fault: one authoritative row changed in place before the check."""
    def fault(document, world, family):
        key = key_of(family)
        with world.control.transaction() as tx:
            row = tx.get(bucket, key)
            tx.put(bucket, key, {**row, **change})
        return {}
    return fault


MIXED_FAULTS = [
    ("partial", lambda d, w, f: {"attempts": d["attempts"][:1], "lineage": [], "captured": d["captured"]},
     "research_receipt_invalid"),
    ("foreign_policy_sha", lambda d, w, f: {"policy_sha256": "0" * 64}, "research_policy_foreign"),
    ("foreign_family", lambda d, w, f: {"family": "op-z"}, "research_family_mismatch"),
    ("foreign_lane", _mutate_row("continuation_intents", lambda f: f["edge"]["id"], {"lane": "b"}),
     "research_mixed_lineage_broken"),
    ("foreign_project", _mutate_row(BUCKET_BINDINGS, lambda f: f["parent"], {"project_id": "other"}),
     "research_mixed_ownership_mismatch"),
    ("foreign_criterion", _mutate_row(BUCKET_BINDINGS, lambda f: f["parent"], {"criterion_id": "c2"}),
     "research_mixed_ownership_mismatch"),
    ("wrong_reason", lambda d, w, f: _attempt(d, f["parent"], reason_code="evidence_gate_refused"),
     "research_investigation_membership"),
    ("wrong_status", lambda d, w, f: _attempt(d, f["parent"], status="failed"), "research_investigation_membership"),
    ("unknown_investigation", lambda d, w, f: _attempt(d, f["parent"], investigation="0" * 64),
     "research_investigation_unknown"),
    ("same_investigation", lambda d, w, f: _attempt(d, f["parent"], investigation=f["investigation"]),
     "research_receipt_invalid"),
    ("missing_lineage", lambda d, w, f: {"lineage": []}, "research_receipt_invalid"),
    ("cyclic_lineage", lambda d, w, f: {"lineage": d["lineage"] + [{**d["lineage"][0], "parent_job": f["child"],
                                                                     "job": f["parent"]}]},
     "research_receipt_invalid"),
    ("broken_lineage", lambda d, w, f: _edge(d, intent_id=f["earlier"]["id"]), "research_mixed_lineage_broken"),
    ("reversed_lineage", lambda d, w, f: _edge(d, parent_job=f["child"], job=f["parent"]),
     "research_mixed_lineage_broken"),
    ("similar_named_edge", lambda d, w, f: _edge(d, intent_id=f["edge"]["id"][:-1]
                                                 + ("1" if f["edge"]["id"].endswith("0") else "0")),
     "research_mixed_lineage_broken"),
    ("unrelated_same_reason_job", lambda d, w, f: _unrelated(d, w, f), "research_attempts_changed"),
    ("changed_evidence", lambda d, w, f: _attempt(d, f["parent"], evidence_sha256="1" * 64),
     "research_attempts_changed"),
    ("changed_inspection", lambda d, w, f: _attempt(d, f["child"], inspection="insp-other"),
     "research_inspection_mismatch"),
    ("captured_parent", lambda d, w, f: {"captured": [f["parent"]]}, "research_mixed_capture_mismatch"),
    ("stale_sample", lambda d, w, f: {"dispatch": {**d["dispatch"], "job_ids_sha256": "0" * 64}},
     "research_dispatch_mismatch"),
    ("stale_run", lambda d, w, f: {"dispatch": {**d["dispatch"], "run_id": "run-old"}}, "research_dispatch_mismatch"),
    ("other_dispatch_investigation", lambda d, w, f: {"investigation": f["rejected_investigation"]},
     "research_dispatch_mismatch"),
    ("unaccepted_report", _mutate_row("decisions_pending", lambda f: "review-003", {"result": {"accepted": False}}),
     "research_mixed_acceptance_unproven"),
    ("foreign_candidate", lambda d, w, f: {"acceptance": {**d["acceptance"], "candidate_revision": "8" * 40}},
     "research_mixed_acceptance_unproven"),
    ("foreign_decision", lambda d, w, f: {"acceptance": {**d["acceptance"], "decision_id": "review-other"}},
     "research_mixed_acceptance_unproven"),
    ("foreign_promotion", lambda d, w, f: {"acceptance": {**d["acceptance"], "graph_sha256": "6" * 64}},
     "research_mixed_acceptance_unproven"),
    ("missing_attestation", lambda d, w, f: {"attestation_ref": "sha256:" + hashlib.sha256(b"never").hexdigest()},
     "research_evidence_missing"),
    ("attestation_is_report", lambda d, w, f: {"attestation_ref": d["evidence_refs"][0]}, "research_receipt_invalid"),
    ("rejected_council", _mutate_row("autonomous_runs", lambda f: f["dispatch"]["run_id"], {"status": "rejected"}),
     "research_not_accepted"),
]


@pytest.mark.parametrize("name, change, reason", MIXED_FAULTS, ids=[fault[0] for fault in MIXED_FAULTS])
def test_partial_foreign_stale_unproven_or_unreadable_mixed_evidence_refuses_with_no_mutation(tmp_path, name, change,
                                                                                               reason):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    document = mixed_for(world, family)
    document = {**document, **change(document, world, family)}
    before = (deepcopy(receipts(world)), deepcopy(world.jobs()))
    with pytest.raises(dc.ContinuationRefused) as info:
        world.controller.accept_research(document)
    assert info.value.reason_code == reason
    assert (receipts(world), world.jobs()) == before, "nothing is stored"
    world.tick()
    assert world.intents()[family["research"]["id"]]["state"] == dc.RESEARCH_REQUIRED


def test_a_receipt_releases_no_correction_budget(tmp_path):
    """The mixed receipt releases the hold; the existing `max_corrections` still decides the successor."""
    world = World(tmp_path, max_corrections=2)
    family = mixed_family(world, tmp_path)
    world.controller.accept_research(mixed_for(world, family))
    world.tick()
    intents = world.intents()
    assert intents[family["research"]["id"]]["state"] == dc.COMPLETED
    refused = only(intents, origin_job=family["child"], route=dc.EVIDENCE_REPAIR)
    assert refused["state"] == dc.REFUSED and refused["reason_code"] == "correction_budget_exhausted"
    assert refused["successor_job"] is None
    assert world.controller.status("policy-1")["held_families"][family["root"]] == "correction_budget_exhausted"


def test_an_unavailable_lane_or_an_unknown_or_active_execution_never_approves(tmp_path):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    document = mixed_for(world, family)

    class Down(LaneEvidence):
        def read(self, job, target=None):
            raise ConnectionError("lane store unavailable (injected fault)")
    with pytest.raises(ConnectionError):
        world.build(lanes=lambda lane: Down(world.lane.store)).accept_research(document)
    with world.lane.store.transaction() as tx:   # LABELLED injected fault: an unconfirmed execution marker
        task = tx.get("operations", family["child"])["owner_handoff"]["task_id"]
        tx.put("observation_terminations", "marker-1", {"record_id": "marker-1", "task_id": task,
                                                         "status": "unconfirmed"})
    with pytest.raises(dc.ContinuationRefused, match="research_attempt_changed"):
        world.controller.accept_research(document)
    with world.lane.store.transaction() as tx:   # its owner resolved the marker
        tx.put("observation_terminations", "marker-1", {"record_id": "marker-1", "task_id": task, "status": "resolved"})
    with world.control.transaction() as tx:   # LABELLED injected fault: the parent is active again
        job = tx.get("fleet_jobs", family["parent"])
        tx.put("fleet_jobs", family["parent"], {**job, "status": "dispatching"})
    with pytest.raises(dc.ContinuationRefused, match="research_attempt_changed"):
        world.controller.accept_research(document)
    with world.control.transaction() as tx:
        tx.put("fleet_jobs", family["parent"], job)
    assert set(receipts(world)) == {family["earlier"]["id"]}
    assert world.controller.accept_research(document)["cached"] is False


def test_concurrent_mixed_submissions_store_one_receipt_and_a_different_one_conflicts(tmp_path):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    document = mixed_for(world, family)
    start, results = threading.Barrier(2), []

    def submit():
        start.wait()
        results.append(Continuation(world.control, lanes=world.lanes, evidence=world.evidence).accept_research(document))
    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r["cached"] for r in results) == [False, True]
    stored = deepcopy(receipts(world))
    other = world.artifacts.put(MIXED_ATTESTATION + "second judgment\n", "owner-attestation")["ref"]
    with pytest.raises(dc.ContinuationRefused, match="research_receipt_conflict"):
        world.controller.accept_research({**document, "attestation_ref": other})
    assert receipts(world) == stored, "a conflict never overwrites"


def test_restart_and_concurrent_controllers_consume_the_mixed_receipt_once_with_its_provenance(tmp_path):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    world.controller.accept_research(mixed_for(world, family))
    stored = deepcopy(receipts(world))
    start = threading.Barrier(2)

    def tick(controller):
        start.wait()
        world.tick(controller=controller)
    threads = [threading.Thread(target=tick, args=(world.build(),)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    world.tick(controller=world.build())
    intents = world.intents()
    done = intents[family["research"]["id"]]
    assert done["state"] == dc.COMPLETED and [h["state"] for h in done["history"]].count(dc.COMPLETED) == 1
    assert len([row for row in intents.values() if row["origin_job"] == family["child"]
                and row["route"] == dc.EVIDENCE_REPAIR]) == 1
    assert receipts(world) == stored and done["research_receipt"] == stored[done["id"]]["receipt_sha256"]


def _mixed_ownership_changed(world, family):
    with world.control.transaction() as tx:   # LABELLED injected fault: the parent's binding changed
        row = tx.get(BUCKET_BINDINGS, family["parent"])
        tx.put(BUCKET_BINDINGS, family["parent"], {**row, "project_id": "other"})
    return "research_mixed_ownership_mismatch", (BUCKET_BINDINGS, family["parent"], row)


def _mixed_review_withdrawn(world, family):
    with world.control.transaction() as tx:   # LABELLED injected fault: the accepted review changed
        row = tx.get("decisions_pending", "review-003")
        tx.put("decisions_pending", "review-003", {**row, "status": "retry"})
    return "research_mixed_acceptance_unproven", ("decisions_pending", "review-003", row)


def _mixed_receipt_tampered(world, family):
    with world.control.transaction() as tx:   # LABELLED injected fault: the stored receipt was edited
        row = tx.get(BUCKET_RESEARCH_RECEIPTS, family["research"]["id"])
        tx.put(BUCKET_RESEARCH_RECEIPTS, row["id"], {**row, "receipt": {**row["receipt"], "captured": []}})
    return "research_receipt_corrupt", (BUCKET_RESEARCH_RECEIPTS, row["id"], row)


def _mixed_attestation_lost(world, family):
    path = stored_path(world, receipts(world)[family["research"]["id"]]["receipt"]["attestation_ref"])
    data = path.read_bytes()
    path.unlink()   # LABELLED injected fault: the attestation bytes are gone
    return "research_evidence_missing", ("file", path, data)


@pytest.mark.parametrize("fault", [_mixed_ownership_changed, _mixed_review_withdrawn, _mixed_receipt_tampered,
                                   _mixed_attestation_lost])
def test_consumption_rechecks_the_mixed_receipt_and_holds_until_it_verifies_again(tmp_path, fault):
    world = World(tmp_path)
    family = mixed_family(world, tmp_path)
    world.controller.accept_research(mixed_for(world, family))
    stored = deepcopy(receipts(world))
    reason, undo = fault(world, family)
    result = world.tick(controller=world.build())
    assert [s["reason_code"] for s in result["skipped"] if s["subject"] == family["research"]["id"]] == [reason]
    assert world.intents()[family["research"]["id"]]["state"] == dc.RESEARCH_REQUIRED
    jobs = len(world.jobs())
    if undo[0] == "file":
        undo[1].write_bytes(undo[2])
    else:
        with world.control.transaction() as tx:
            tx.put(*undo)
    assert receipts(world) == stored
    world.tick()
    assert world.intents()[family["research"]["id"]]["state"] == dc.COMPLETED and len(world.jobs()) == jobs + 1
