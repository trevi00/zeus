"""Investigation-to-research dispatch bridge (INV-RESEARCH-PROGRAM-001, research-dispatch-001):
opt-in source configuration, eligibility from authoritative portfolio/Fleet rows only, the immutable
bounded snapshot, the cross-program claim, replay/concurrency, a changed owner disposition, capture
failure, run-row result authority and the read-only projections.

The Git repository, the store transactions, the portfolio reconciler and the ProgramRunner path are
REAL. The Fleet job rows, the feeds, the machine ledger, the clock and the council are LABELLED
synthetic stand-ins: no provider, network or real PostgreSQL unless HARNESS_INTEGRATION=1. An
injected council response proves a transition contract, never live research quality.
"""
import json
import threading

import pytest
from test_research_program import POLICY, Clock, build, registered
from test_research_program_fixtures import BASE_CLOCK, CANARY, FakeBudget, FakeCouncil, config, git

from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import BUCKET_JOBS
from codex_harness.application.portfolio import (
    BUCKET_INVESTIGATIONS,
    Portfolio,
    family_id,
)
from codex_harness.application.research_program import (
    BUCKET_DISPATCHES,
    ResearchProgram,
)
from codex_harness.domain.autonomous import manifest_digest
from codex_harness.domain.model import digest
from codex_harness.domain.research_investigations import (
    MAX_JOB_SAMPLE,
    InvestigationRefused,
    eligible_investigations,
    snapshot,
    validate_source,
)
from codex_harness.domain.research_program import (
    CONFIG_FIELDS,
    ProgramRefused,
    config_digest,
    validate_config,
)

POLICY_TOPICS = {"storage"}
SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": ["store_timeout"]}
FAMILY = ("failed", "store_timeout")
INVESTIGATION = family_id(*FAMILY)
DEFINITIONS = {"schema": "urn:zeus:portfolio-definitions:1", "projects": [
    {"id": "ops", "title": "Operations", "outcome": "bound fleet work completes", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "jobs reach a terminal accepted state"}]},
    {"id": "other", "title": "Other", "outcome": "unrelated work", "source_ref": "docs/GOAL.md",
     "criteria": [{"id": "c1", "text": "unrelated criterion"}]}]}
# (job id, status, reason code, bound project): two distinct qualifying jobs and one same-family job
# bound to a project this program is NOT authorized for.
JOBS = (("j-1", "failed", "store_timeout", "ops"), ("j-2", "failed", "store_timeout", "ops"),
        ("j-3", "failed", "store_timeout", "other"), ("j-4", "rejected", "review_rejected", "ops"))


def portfolio(store, jobs=JOBS) -> Portfolio:
    """LABELLED synthetic Fleet rows (only the fields the reconciler reads) under the REAL portfolio
    reconciler, owner bindings and owner dispositions."""
    owner = Portfolio(store, DEFINITIONS, clock=lambda: BASE_CLOCK)
    with store.transaction() as tx:
        for job_id, status, reason, _ in jobs:
            tx.put(BUCKET_JOBS, job_id, {"id": job_id, "lane": "lane-1", "status": status, "reason_code": reason,
                                         "error_type": None, "updated_at": BASE_CLOCK})
    for job_id, _, _, project in jobs:
        owner.bind(job_id, project, "c1")
    owner.reconcile()
    return owner


def investigations(store) -> dict:
    with store.transaction() as tx:
        return {row["id"]: row for row in tx.scan(BUCKET_INVESTIGATIONS)}


def dispatches(store) -> list:
    with store.transaction() as tx:
        return tx.scan(BUCKET_DISPATCHES)


# ----- opt-in configuration -------------------------------------------------------------------------------
def test_absent_source_keeps_the_legacy_config_and_digest_and_the_block_is_strict():
    head = "a" * 40
    disabled = validate_config(config(head), POLICY)
    assert set(disabled) == CONFIG_FIELDS and "investigation_source" not in disabled
    enabled = validate_config(config(head, investigation_source=dict(SOURCE)), POLICY)
    assert enabled["investigation_source"] == SOURCE
    legacy = {k: v for k, v in enabled.items() if k != "investigation_source"}
    assert legacy == disabled and config_digest(legacy, "repo-1") == config_digest(disabled, "repo-1")
    assert config_digest(enabled, "repo-1") != config_digest(disabled, "repo-1"), "opting in is a new identity"
    cases = [(None, "config_invalid"), ([], "config_invalid"), ({"topic": "storage"}, "config_fields"),
             ({**SOURCE, "extra": 1}, "config_fields"), ({**SOURCE, "topic": "unknown"}, "config_invalid"),
             ({**SOURCE, "topic": None}, "config_invalid"), ({**SOURCE, "project_ids": []}, "config_invalid"),
             ({**SOURCE, "project_ids": None}, "config_invalid"), ({**SOURCE, "project_ids": ["*"]}, "config_invalid"),
             ({**SOURCE, "project_ids": ["ops", "ops"]}, "config_duplicate"),
             ({**SOURCE, "project_ids": ["ops-%d" % i for i in range(21)]}, "config_invalid"),
             ({**SOURCE, "reason_codes": ["ops " + CANARY]}, "config_invalid"),
             ({**SOURCE, "reason_codes": ["c-%d" % i for i in range(51)]}, "config_invalid"),
             ({**SOURCE, "reason_codes": [None]}, "config_invalid")]
    for override, code in cases:
        with pytest.raises(ProgramRefused) as info:
            validate_config(config(head, investigation_source=override), POLICY)
        assert info.value.reason_code == code, override
        assert CANARY not in str(info.value)
    with pytest.raises(InvestigationRefused, match="config_fields"):
        validate_source({"topic": "storage"}, POLICY_TOPICS)


def test_eligibility_uses_only_scoped_rows_and_records_bounded_exclusions():
    store = MemoryStore()
    portfolio(store)
    with store.transaction() as tx:
        rows, jobs, bindings = tx.scan(BUCKET_INVESTIGATIONS), tx.scan(BUCKET_JOBS), tx.scan("portfolio_bindings")
    found = eligible_investigations(investigations=rows, jobs=jobs, bindings=bindings, source=SOURCE,
                                    claimed=set(), required_state="research_required", minimum=2)
    assert [c["investigation"] for c in found["candidates"]] == [INVESTIGATION]
    assert found["candidates"][0]["job_ids"] == ["j-1", "j-2"], "the out-of-scope family member is never included"
    assert found["candidates"][0]["projects"] == ["ops"]
    assert found["counts"]["scanned"] == 1 and found["counts"]["eligible"] == 1
    claimed = eligible_investigations(investigations=rows, jobs=jobs, bindings=bindings, source=SOURCE,
                                      claimed={INVESTIGATION}, required_state="research_required", minimum=2)
    assert claimed["candidates"] == [] and claimed["counts"]["claimed"] == 1
    other = eligible_investigations(investigations=rows, jobs=jobs, bindings=bindings,
                                    source={**SOURCE, "project_ids": ["other"]}, claimed=set(),
                                    required_state="research_required", minimum=2)
    assert other["candidates"] == [] and other["counts"]["insufficient_jobs"] == 1, "one scoped job is not a family"
    codes = eligible_investigations(investigations=rows, jobs=jobs, bindings=bindings,
                                    source={**SOURCE, "reason_codes": ["other_code"]}, claimed=set(),
                                    required_state="research_required", minimum=2)
    assert codes["candidates"] == [] and codes["counts"]["reason_code"] == 1
    decided = eligible_investigations(investigations=[{**rows[0], "state": "researched"}], jobs=jobs, bindings=bindings,
                                      source=SOURCE, claimed=set(), required_state="research_required", minimum=2)
    assert decided["candidates"] == [] and decided["counts"]["state"] == 1
    malformed = eligible_investigations(investigations=[{"id": "x", "state": "research_required", "reason_code": "store_timeout",
                                                         "family_status": "failed", "job_ids": "j-1"}, "not a row"],
                                        jobs=jobs, bindings=bindings, source=SOURCE, claimed=set(),
                                        required_state="research_required", minimum=2)
    assert malformed["candidates"] == [] and malformed["counts"]["malformed"] == 2


def test_snapshot_is_bounded_versioned_and_explicit_about_truncation():
    ids = ["j-%03d" % i for i in range(60)]
    document = snapshot(candidate={"investigation": INVESTIGATION, "family_status": "failed",
                                   "reason_code": "store_timeout", "job_ids": ids, "projects": ["ops"]},
                        program_id="rp-001", cycle_number=1, topic="storage", observed_at=BASE_CLOCK)
    assert document["schema"] == "urn:zeus:research-investigation-snapshot:1"
    assert len(document["job_ids"]) == MAX_JOB_SAMPLE and document["job_ids_total"] == 60
    assert document["job_ids_truncated"] is True and document["job_ids_sha256"] == digest(sorted(ids))
    assert "hypothesis" in document["trust"] and document["observed_at"] == BASE_CLOCK


# ----- normal dispatch -------------------------------------------------------------------------------------
def test_two_jobs_one_candidate_one_claim_immutable_snapshot_and_a_linked_run(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store, council=FakeCouncil(store, status="accepted"))
    portfolio(store)
    registered(env, investigation_source=dict(SOURCE))
    receipt = env.runner.tick("rp-001")
    assert receipt["investigation"] == INVESTIGATION and receipt["result"] == "accepted"
    assert receipt["selected"] == "inv-" + INVESTIGATION[:24], "the investigation outranks the local lead"
    view = env.programs.status("rp-001")
    cycle = view["cycle_receipts"][0]
    assert cycle["investigations"] == {"counts": {"scanned": 1, "eligible": 1, "malformed": 0, "state": 0,
                                                  "reason_code": 0, "insufficient_jobs": 0, "claimed": 0},
                                       "new": 1, "ineligible": 0, "claimed": INVESTIGATION,
                                       "result": "accepted", "reported_result": "accepted"}
    assert cycle["selection"]["source"] == "investigation" and cycle["result"] == "accepted"
    # The council received the immutable snapshot at the capture commit, and only the scoped ids.
    captured = json.loads(git(env.root, "show", cycle["capture"]["revision"] + ":" + cycle["capture"]["path"]).stdout)
    assert captured["investigation"]["job_ids"] == ["j-1", "j-2"] and captured["investigation"]["job_ids_total"] == 2
    assert captured["investigation"]["investigation"] == INVESTIGATION and captured["investigation"]["cycle"] == 1
    assert captured["investigation"]["job_ids_truncated"] is False
    manifest = env.council.manifests[0]
    assert cycle["capture"]["path"] in manifest["research"]["search_scope"]
    assert manifest["base_revision"] == cycle["capture"]["revision"]
    # The dispatch names the EXACT run row and manifest digest the council actually started.
    row = dispatches(store)[0]
    assert row["id"] == INVESTIGATION and row["investigation"] == INVESTIGATION and row["program"] == "rp-001"
    assert row["cycle"] == "rp-001:001" and row["state"] == "resolved" and row["result"] == "accepted"
    assert row["run_id"] == manifest["id"] == cycle["council"]["run_id"]
    assert row["manifest_sha256"] == manifest_digest(manifest) == cycle["council"]["manifest_sha256"]
    assert row["snapshot_sha256"] == digest(captured["investigation"])
    assert row["job_ids"] == ["j-1", "j-2"] and row["job_ids_total"] == 2 and row["reported_result"] == "accepted"
    assert row["failure"] is None and "disposition" not in row["authority"].split()[0]
    # The owner's investigation row is untouched: no state, evidence or membership change.
    assert investigations(store)[INVESTIGATION] == {**investigations(store)[INVESTIGATION], "state": "research_required",
                                                    "evidence_refs": [], "decided_at": None,
                                                    "job_ids": ["j-1", "j-2", "j-3"], "count": 3}
    assert view["investigations"] == {"total": 1, "claimed": 0, "dispatched": 0, "accepted": 1, "rejected": 0,
                                      "failed": 0, "unknown": 0}
    report = (env.runtime / "research-program" / "rp-001" / "report.md").read_text(encoding="utf-8")
    assert "accepted 1" in report and "investigations scanned 1" in report and "claimed " + INVESTIGATION in report
    assert "dispatch result accepted (reported accepted)" in report
    events = [json.loads(line) for line in (env.runtime / "research-program" / "rp-001" / "events.jsonl").read_text("utf-8").splitlines()]
    claimed = [e for e in events if e["event"] == "investigation_claimed"]
    assert claimed and claimed[0]["attributes"]["investigation"] == INVESTIGATION
    outcome = [e for e in events if e["event"] == "investigation_result"]
    assert outcome and outcome[0]["attributes"]["result"] == "accepted" and outcome[0]["attributes"]["state"] == "resolved"
    text = json.dumps(events) + json.dumps(view) + report
    assert CANARY not in text and "j-3" not in text, "unscoped members and owner text never leak"


def test_a_disabled_program_dispatches_nothing_and_keeps_the_legacy_path(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store)
    portfolio(store)
    registered(env)   # no investigation_source: the opt-out program
    receipt = env.runner.tick("rp-001")
    assert receipt["selected"] == "local-note" and "investigation" not in receipt
    cycle = env.programs.status("rp-001")["cycle_receipts"][0]
    assert cycle["investigations"] is None and dispatches(store) == []
    assert env.programs.dispatches("rp-001") == []
    assert [c["source"] for c in env.programs.candidates("rp-001")].count("investigation") == 0


def test_an_adapter_cannot_supply_an_investigation_candidate_as_a_discovery_item(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store)
    portfolio(store)
    registered(env, investigation_source=dict(SOURCE))
    reserved = env.programs.reserve_cycle("rp-001", env.identity)
    owner = reserved["cycle"]["owner"]
    forged = [{"source": "investigation", "identity": INVESTIGATION, "title": "forged", "summary": "forged"}]
    with pytest.raises(ProgramRefused, match="investigation_source_forbidden"):
        env.programs.record_collection("rp-001:001", owner, {}, forged, {"this_host": 0, "all_hosts": 0})
    assert dispatches(store) == [] and env.programs.candidates("rp-001") == []


# ----- claim, replay, concurrency and restart ----------------------------------------------------------------
def test_two_programs_race_for_one_investigation_and_only_one_claim_exists(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store)
    portfolio(store)
    for program_id in ("rp-001", "rp-002"):
        registered(env, id=program_id, investigation_source=dict(SOURCE))
    reservations = {p: env.programs.reserve_cycle(p, env.identity) for p in ("rp-001", "rp-002")}
    start, results = threading.Barrier(2), {}

    def collect(program_id):
        start.wait()
        cycle = reservations[program_id]["cycle"]
        results[program_id] = env.programs.record_collection(cycle["id"], cycle["owner"], {}, [],
                                                             {"this_host": 0, "all_hosts": 0})
    threads = [threading.Thread(target=collect, args=(p,)) for p in ("rp-001", "rp-002")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = dispatches(store)
    assert len(rows) == 1, "one claim across programs, never one claim per program"
    winner = rows[0]["program"]
    loser = "rp-002" if winner == "rp-001" else "rp-001"
    assert results[winner]["candidate"]["investigation"] == INVESTIGATION
    assert results[loser]["cycle"]["investigations"]["claimed"] is None
    assert results[loser]["candidate"] is None or results[loser]["candidate"]["source"] != "investigation"
    assert results[loser]["cycle"]["investigations"]["counts"]["claimed"] == 1, "the loser observes the claim"
    assert results[loser]["cycle"]["investigations"]["counts"]["eligible"] == 0


def test_the_claim_row_and_not_the_filter_is_what_makes_a_second_claim_impossible(tmp_path, monkeypatch):
    """LABELLED injected fault: eligibility is forced to forget every existing claim. The durable
    row keyed solely by investigation id must still refuse the second claim inside the transaction."""
    store = MemoryStore()
    env = build(tmp_path, store=store, council=FakeCouncil(store, status="accepted"))
    portfolio(store)
    registered(env, investigation_source=dict(SOURCE))
    registered(env, id="rp-002", investigation_source=dict(SOURCE))
    env.runner.tick("rp-001")
    assert len(dispatches(store)) == 1
    import codex_harness.application.research_program as application
    forgetful = application.eligible_investigations
    monkeypatch.setattr(application, "eligible_investigations",
                        lambda **kw: forgetful(**{**kw, "claimed": set()}))
    reserved = env.programs.reserve_cycle("rp-002", env.identity)
    with pytest.raises(ProgramRefused, match="investigation_already_claimed"):
        env.programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [],
                                       {"this_host": 0, "all_hosts": 0})
    rows = dispatches(store)
    assert len(rows) == 1 and rows[0]["program"] == "rp-001", "the refused transaction left nothing behind"
    assert env.programs.status("rp-002")["cycles"]["active"] == "rp-002:001", "the refusal is not a silent success"


def test_replay_keeps_the_original_claim_and_never_opens_a_second_attempt(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store, council=FakeCouncil(store, status="accepted"))
    portfolio(store)
    registered(env, investigation_source=dict(SOURCE), max_cycles=3, max_adoptions=3)
    env.runner.tick("rp-001")
    first = dispatches(store)[0]
    env.clock.value = "2028-01-01T02:00:00+00:00"
    second = env.runner.tick("rp-001")
    assert second["selected"] == "local-note", "the claimed investigation is not offered again"
    rows = dispatches(store)
    assert len(rows) == 1 and rows[0] == first, "the original reference is retained byte for byte"
    candidate = env.programs.candidate("rp-001", "inv-" + INVESTIGATION[:24])
    assert candidate["status"] == "claimed" and candidate["claimed_cycle"] == 1 and candidate["result"] == "accepted"


def test_a_crash_after_the_claim_leaves_an_owned_dispatch_with_recovery_facts(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store)
    portfolio(store)
    registered(env, investigation_source=dict(SOURCE))
    reserved = env.programs.reserve_cycle("rp-001", env.identity)
    cycle, owner = reserved["cycle"]["id"], reserved["cycle"]["owner"]
    env.programs.record_collection(cycle, owner, {}, [], {"this_host": 0, "all_hosts": 0})
    env.programs.record_capture(cycle, owner, {"revision": "c" * 40, "ref": "refs/zeus/research/rp-001/001",
                                               "path": "docs/zeus/research-captures/rp-001/001.json"})
    env.programs.record_council_start(cycle, owner, "rp-001.c001", "d" * 64, "sha256:" + "e" * 64)
    row = dispatches(store)[0]   # the process dies here: nothing releases the claim on its own
    assert row["state"] == "dispatched" and row["run_id"] == "rp-001.c001" and row["manifest_sha256"] == "d" * 64
    assert row["result"] is None and row["finished_at"] is None and row["claimed_at"] == BASE_CLOCK
    assert env.programs.reserve_cycle("rp-001", env.identity)["reason"] == "busy"
    restarted = ResearchProgram(store, clock=Clock("2028-01-01T05:00:00+00:00"))
    assert restarted.reserve_cycle("rp-001", env.identity)["reason"] == "busy", "no timeout-based replay"
    assert dispatches(store)[0] == row and investigations(store)[INVESTIGATION]["state"] == "research_required"


def test_a_changed_owner_disposition_cannot_run_later_from_an_old_cache(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store, budget=FakeBudget(this_host=4, all_hosts=4))   # LABELLED: no headroom
    owner = portfolio(store)
    registered(env, investigation_source=dict(SOURCE), max_cycles=3, max_adoptions=2)
    first = env.runner.tick("rp-001")
    assert first["reason"] == "machine_headroom_insufficient" and dispatches(store) == []
    cached = env.programs.candidate("rp-001", "inv-" + INVESTIGATION[:24])
    assert cached["status"] == "eligible" and cached["snapshot"]["investigation"] == INVESTIGATION
    owner.disposition(INVESTIGATION, "researched", ["docs/zeus/operations/research-dispatch-001/SPEC.md"])
    env.runner.budget = FakeBudget()   # LABELLED: headroom restored; only the disposition changed
    env.clock.value = "2028-01-01T02:00:00+00:00"
    second = env.runner.tick("rp-001")
    assert second["selected"] == "local-note" and "investigation" not in second
    assert dispatches(store) == [], "a decided investigation is never dispatched from the cache"
    stale = env.programs.candidate("rp-001", "inv-" + INVESTIGATION[:24])
    assert stale["status"] == "ignored" and stale["reason"] == "investigation_ineligible" and stale["snapshot"] is None
    cycle = env.programs.status("rp-001")["cycle_receipts"][1]
    assert cycle["investigations"]["ineligible"] == 1 and cycle["investigations"]["counts"]["state"] == 1
    assert investigations(store)[INVESTIGATION]["state"] == "researched", "the owner's decision is untouched"


# ----- failure and result authority ----------------------------------------------------------------------------
def test_a_capture_failure_keeps_a_failed_dispatch_with_a_fixed_stage_and_code(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store)
    portfolio(store)
    registered(env, investigation_source=dict(SOURCE))
    git(env.root, "update-ref", "refs/zeus/research/rp-001/001", env.head)   # a stale ref from an earlier attempt
    receipt = env.runner.tick("rp-001")
    assert receipt["failure"] == {"stage": "capture", "code": "capture_ref_exists"}
    assert receipt["investigation"] == INVESTIGATION and receipt["state"] == "blocked"
    row = dispatches(store)[0]
    assert row["state"] == "resolved" and row["result"] == "failed" and row["run_id"] is None
    assert row["failure"] == {"stage": "capture", "code": "capture_ref_exists"}
    assert env.council.manifests == [], "no council ran"
    view = env.programs.status("rp-001")
    assert view["investigations"]["failed"] == 1
    assert view["cycle_receipts"][0]["investigations"]["result"] == "failed"
    assert investigations(store)[INVESTIGATION]["state"] == "research_required"


class MismatchedCouncil:
    """LABELLED council stand-in that writes a run row for ANOTHER manifest digest."""

    def __init__(self, store):
        self.store, self.manifests = store, []

    def __call__(self, service, args):
        manifest = json.loads(open(args.file, encoding="utf-8").read())
        self.manifests.append(manifest)
        with self.store.transaction() as tx:
            tx.put("autonomous_runs", manifest["id"], {"id": manifest["id"], "status": "accepted", "stage": "promotion",
                                                       "manifest_sha256": "0" * 64, "reason_code": "fixture_accepted"})
        return {"status": "accepted", "exit_code": 0}


def test_a_mismatched_run_row_is_unknown_and_caller_prose_is_not_authority(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store, council=MismatchedCouncil(store))
    portfolio(store)
    registered(env, investigation_source=dict(SOURCE))
    receipt = env.runner.tick("rp-001")
    assert receipt["result"] == "unknown" and receipt["reason_code"] == "run_row_mismatch"
    row = dispatches(store)[0]
    assert row["result"] == "unknown" and row["result_reason"] == "run_row_mismatch" and row["row_status"] == "accepted"
    assert env.programs.status("rp-001")["investigations"]["unknown"] == 1
    assert env.programs.status("rp-001")["state"] == "blocked", "unknown blocks and keeps the claim"
    # LABELLED control: a second program whose caller CLAIMS acceptance while no run row exists at all.
    other = MemoryStore()
    env2 = build(tmp_path / "b", store=other)
    portfolio(other)
    registered(env2, investigation_source=dict(SOURCE))
    reserved = env2.programs.reserve_cycle("rp-001", env2.identity)
    cycle, owner = reserved["cycle"]["id"], reserved["cycle"]["owner"]
    env2.programs.record_collection(cycle, owner, {}, [], {"this_host": 0, "all_hosts": 0})
    env2.programs.record_capture(cycle, owner, {"revision": "c" * 40, "ref": "r", "path": "p"})
    env2.programs.record_council_start(cycle, owner, "rp-001.c001", "d" * 64, "sha256:" + "e" * 64)
    env2.programs.record_council_result(cycle, owner, {"result": "accepted", "reason_code": "model_said_so",
                                                       "row_status": "accepted"})
    claimed = dispatches(other)[0]
    assert claimed["result"] == "unknown" and claimed["result_reason"] == "run_row_missing"
    assert claimed["reported_result"] == "accepted", "the caller's claim is recorded as an unverified report only"
    receipt = env2.programs.status("rp-001")["cycle_receipts"][0]["investigations"]
    assert receipt == {**receipt, "result": "unknown", "reported_result": "accepted"}
    assert investigations(other)[INVESTIGATION]["state"] == "research_required"


# ----- isolated PostgreSQL ---------------------------------------------------------------------------------------
def test_postgres_two_programs_claim_one_investigation(isolated_pgstore):
    """Real isolated PostgreSQL (HARNESS_INTEGRATION=1): the advisory-locked transaction serializes
    the cross-program claim exactly as the serialized memory store does."""
    store = isolated_pgstore
    portfolio(store)
    programs = ResearchProgram(store, clock=Clock())
    for program_id in ("rp-001", "rp-002"):
        cfg = validate_config(config("a" * 40, id=program_id, investigation_source=dict(SOURCE)), POLICY)
        programs.register(cfg, "repo-1", [])
        programs.resume(program_id)
    reservations = {p: programs.reserve_cycle(p, "repo-1") for p in ("rp-001", "rp-002")}
    start, results = threading.Barrier(2), {}

    def collect(program_id):
        cycle = reservations[program_id]["cycle"]
        start.wait()
        results[program_id] = programs.record_collection(cycle["id"], cycle["owner"], {}, [],
                                                         {"this_host": 0, "all_hosts": 0})
    threads = [threading.Thread(target=collect, args=(p,)) for p in ("rp-001", "rp-002")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with store.transaction() as tx:
        rows = tx.scan(BUCKET_DISPATCHES)
        owner_rows = tx.scan(BUCKET_INVESTIGATIONS)
    assert len(rows) == 1 and rows[0]["investigation"] == INVESTIGATION
    assert sum(r["cycle"]["investigations"]["claimed"] is not None for r in results.values()) == 1
    assert owner_rows[0]["state"] == "research_required", "no owner disposition is written by the bridge"
