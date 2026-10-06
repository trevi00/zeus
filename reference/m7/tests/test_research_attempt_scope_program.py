"""Attempt-scoped research, research-program layer (INV-RESEARCH-ATTEMPT-SCOPE-001, FLEET-U2B-SPEC §3 and §5):
the owner-bound target reservation, in-transaction synthesis and exact-target selection, the forward and
reverse overlap defences, final scoped failure and legacy byte identity.

Every Fleet, Portfolio, continuation, owner-action, program and lineage row seeded here is a LABELLED synthetic
fixture carrying only the fields the rules read. The store transactions, the state machine, the Git capture and
the ProgramRunner path are REAL; the feeds, ledger, clock and council are the labelled stand-ins of
test_research_program_fixtures. No provider, model, network or real PostgreSQL unless HARNESS_INTEGRATION=1.
A passing fixture proves a transition contract, never a live research outcome."""
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
from test_research_program import POLICY, Clock, build, registered
from test_research_program_fixtures import CANARY, FakeCouncil, config, git

import codex_harness.application.research_program as application
from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.portfolio import family_id
from codex_harness.application.research_program import (
    BUCKET_CANDIDATES,
    BUCKET_CYCLES,
    BUCKET_DISPATCHES,
    BUCKET_HEADS,
    BUCKET_PROGRAMS,
    BUCKET_RECOVERIES,
    BUCKET_SUCCESSORS,
    ResearchProgram,
)
from codex_harness.domain import owner_actions as do
from codex_harness.domain.continuation import attempt_scope_id
from codex_harness.domain.model import digest
from codex_harness.domain.research_program import ProgramRefused, validate_config

POLICY_ID, POLICY_SHA = "policy-1", "5" * 64
STATUS, REASON = "failed", "store_timeout"
CAUSE = family_id(STATUS, REASON)
J_F0, S1 = "aibox-qual-b2-fault", "aibox-qual-b2-fault-s1"
# The P1 shape: 21 historical family members, the first 11 bound to the authorized project; Q1 is the latest
# scoped member, captured by no dispatch. J_F0/S1 are the held lineage and are NOT among the 21.
HISTORICAL = ["hist-%02d" % i for i in range(1, 22)]
SCOPED, Q1 = HISTORICAL[:11], HISTORICAL[10]
SOURCE = {"topic": "storage", "continuation_policy": POLICY_ID, "continuation_policy_sha256": POLICY_SHA,
          "families": [J_F0], "project_ids": ["ops"], "reason_codes": [REASON]}
FAMILY_SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": [REASON, "review_rejected"]}
T0, T_F0, T_R = "2027-12-31T00:00:00+00:00", "2028-01-01T00:00:00+00:00", "2028-01-01T00:10:00+00:00"
COUNTS = {"this_host": 0, "all_hosts": 0}
NOTE_SHA = hashlib.sha256(b"# local residual\n").hexdigest()
# LABELLED attractive discovery leads that a scoped cycle must never select instead of its target.
LEADS = [{"source": "local", "identity": "docs/research/note.md", "id": "local-note", "path": "docs/research/note.md",
          "sha256": NOTE_SHA, "topic": "storage", "title": "docs/research/note.md", "summary": "postgres advisory lock",
          "url": None, "content_sha256": NOTE_SHA},
         {"source": "github", "identity": "https://github.com/acme/pgtool", "url": "https://github.com/acme/pgtool",
          "title": "acme/pgtool", "summary": "Postgres tooling", "content_sha256": "1" * 64}]


def hexid(label: str) -> str:
    return digest(["fixture-intent", label])


I_F0, I_R = hexid("f0"), hexid("r")
SCOPE = attempt_scope_id(I_R)
ATTEMPTS = [{"job": J_F0, "evidence_sha256": "a" * 64}, {"job": S1, "evidence_sha256": "b" * 64}]


# ----- labelled synthetic rows ---------------------------------------------------------------------------------
def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def records(store) -> list:
    with store.transaction() as tx:
        return tx.records()


def intent(identity, route, state, origin, evidence, created_at, family=J_F0):
    return {"id": identity, "route": route, "state": state, "policy_id": POLICY_ID, "policy_sha256": POLICY_SHA,
            "family": family, "origin_job": origin, "evidence_sha256": evidence, "created_at": created_at,
            "lane": "lane-1"}


def job(tx, job_id, project, status=STATUS, reason=REASON):
    tx.put("fleet_jobs", job_id, {"id": job_id, "status": status, "reason_code": reason})
    tx.put("portfolio_bindings", job_id, {"job_id": job_id, "project_id": project})


def family_dispatch(key, ids, program, state="resolved", result="failed", total=None, cause=(STATUS, REASON)):
    ids = sorted(ids)
    return {"schema": "urn:zeus:research-investigation-dispatch:1", "id": key, "investigation": family_id(*cause),
            "kind": "failure_family", "scope": None, "program": program, "cycle": program + ":001", "cycle_number": 1,
            "candidate": "inv-fixture", "state": state, "snapshot_sha256": "c" * 64, "family_status": cause[0],
            "reason_code": cause[1], "job_ids": ids, "job_ids_total": len(ids) if total is None else total,
            "job_ids_sha256": digest(ids), "run_id": program + ".c001", "manifest_sha256": "d" * 64,
            "result": result, "claimed_at": T0, "updated_at": T0}


def held_world(store, *, lineage=True, members=None):
    """The held lineage (prior failure F0 on J_F0, held research intent R on S1), their Fleet rows and bindings,
    the undecided cause row with 21 historical members (11 scoped) and, with `lineage`, the P1 history: four
    resolved family dispatches, a claimed recovery, two claimed successors, their head and 15 terminal programs."""
    with store.transaction() as tx:
        tx.put("continuation_policies", POLICY_ID, {"id": POLICY_ID, "policy_sha256": POLICY_SHA})
        tx.put("continuation_intents", I_F0, intent(I_F0, "correction", "admitted", J_F0, "a" * 64, T_F0))
        tx.put("continuation_intents", I_R, intent(I_R, "research", "research_required", S1, "b" * 64, T_R))
        for held in (J_F0, S1):
            job(tx, held, "ops")
        for index, member in enumerate(HISTORICAL):
            job(tx, member, "ops" if index < 11 else "other")
        ids = list(HISTORICAL if members is None else members)
        tx.put("portfolio_investigations", CAUSE, {
            "id": CAUSE, "kind": "failure_family", "state": "research_required", "family_status": STATUS,
            "reason_code": REASON, "job_ids": ids, "count": len(ids)})
        if not lineage:
            return
        keys = [CAUSE, CAUSE + ".recovery-1", CAUSE + ".recovery-2", CAUSE + ".recovery-3"]
        for number, key in enumerate(keys):
            tx.put(BUCKET_DISPATCHES, key, family_dispatch(key, SCOPED[:4 + 2 * number], "rp-hist-%02d" % (number + 1)))
        tx.put(BUCKET_RECOVERIES, CAUSE, {
            "id": CAUSE, "investigation": CAUSE, "state": "claimed", "request_sha256": "6" * 64,
            "failed": {"program": "rp-hist-01", "cycle": "rp-hist-01:001"},
            "replacement": {"program": "rp-hist-02", "dispatch": keys[1], "cycle": "rp-hist-02:001"}})
        for version in (2, 3):
            tx.put(BUCKET_SUCCESSORS, CAUSE + ":" + str(version), {
                "id": CAUSE + ":" + str(version), "investigation": CAUSE, "version": version, "state": "claimed",
                "predecessor": {"program": "rp-hist-%02d" % version}, "replacement": {
                    "program": "rp-hist-%02d" % (version + 1), "dispatch": keys[version]}})
        tx.put(BUCKET_HEADS, CAUSE, {"id": CAUSE, "investigation": CAUSE, "version": 3, "successor": CAUSE + ":3",
                                     "dispatch": keys[3]})
        for number in range(1, 16):
            tx.put(BUCKET_PROGRAMS, "rp-hist-%02d" % number, {
                "id": "rp-hist-%02d" % number, "state": "completed" if number % 2 else "blocked",
                "config": {"investigation_source": dict(FAMILY_SOURCE)}})


def launch(store, program="rp-001", cycle=1, intent_id=I_R, jobs=(J_F0, S1), state=do.RUNNING, investigation=None,
           family=J_F0) -> str:
    """The owner-actions `research_dispatch` row whose launch id the child reserves under (LABELLED: written
    through the owner's own row constructors, never through its coordinator)."""
    binding = do.research_dispatch_binding({"id": intent_id, "policy_id": POLICY_ID, "family": family},
                                           {"program_id": program}, investigation or attempt_scope_id(intent_id),
                                           list(jobs), cycle)
    row = do.new_action(do.RESEARCH_DISPATCH, binding, {"id": "owners-002", "policy_sha256": "3" * 64},
                        {"intent_id": intent_id, "lane": "lane-1"}, T0)
    if state != do.INTENDED:
        row = do.moved(row, do.LAUNCHING, T0, "research_launch_intended", launches=1,
                       launch_id=do.research_launch_id(row["id"], 1))
    if state in (do.RUNNING, do.COMPLETED):
        row = do.moved(row, do.RUNNING, T0, "research_launched")
    if state == do.COMPLETED:
        row = do.moved(row, do.COMPLETED, T0, "research_dispatch_accepted")
    put(store, "owner_actions", row["id"], row)
    return row.get("launch_id") or digest(["no-launch", row["id"]])


def scoped_program(store, program_id="rp-001", token="0" * 32, clock=None, source=None, **overrides):
    cfg = validate_config(config("a" * 40, id=program_id, attempt_scope_source=dict(source or SOURCE), **overrides),
                          POLICY)
    programs = ResearchProgram(store, clock=clock or Clock(), token=lambda: token)
    programs.register(cfg, "repo-1", [])
    programs.resume(program_id)
    return programs


def family_program(store, program_id="rp-fam", clock=None):
    cfg = validate_config(config("a" * 40, id=program_id, investigation_source=dict(FAMILY_SOURCE)), POLICY)
    programs = ResearchProgram(store, clock=clock or Clock())
    programs.register(cfg, "repo-1", [])
    programs.resume(program_id)
    return programs


def collect(programs, program_id="rp-001", items=()):
    reserved = programs.reserve_cycle(program_id, "repo-1")
    assert reserved["reserved"], reserved
    cycle = reserved["cycle"]
    return programs.record_collection(cycle["id"], cycle["owner"], {}, [dict(i) for i in items], COUNTS)


def claim_scope(store, **kwargs):
    """The real scoped claim of R through the state machine: one owner launch, one reserved cycle, one claim."""
    programs = scoped_program(store, token=launch(store), **kwargs)
    recorded = collect(programs)
    assert recorded["candidate"]["investigation"] == SCOPE, recorded["cycle"]["selection"]
    return programs, recorded


def history(store) -> dict:
    """Every pre-existing row that a scoped tick must leave byte for byte: everything but the program's own
    lifecycle rows, the council's run row and the new scope dispatch."""
    own = {BUCKET_PROGRAMS, BUCKET_CANDIDATES, BUCKET_CYCLES, "autonomous_runs"}
    return {(r["bucket"], r["id"]): r["body"] for r in records(store)
            if r["bucket"] not in own and (r["bucket"], r["id"]) != (BUCKET_DISPATCHES, SCOPE)}


def refused(call, *args, **kwargs) -> ProgramRefused:
    with pytest.raises(ProgramRefused) as info:
        call(*args, **kwargs)
    assert CANARY not in str(info.value)
    return info.value


# ----- U2B-2 / U2B-10 pin: legacy byte identity (golden) --------------------------------------------------------
# The digests below were computed with this exact scenario at d71febf (before U2(b)) and at 96d15cf, and are
# unchanged by this layer: no registered attempt_scope_source and no scope claim means no new key, read effect or
# refusal on any legacy cycle, candidate, dispatch, status or return value.
GOLDEN = {"plain": "fe1006824a299e6395050f261972057d82d70c092b0f224194edb2b6093fc313",
          "family": "7a249a53576bc1712f769973891a5798e2427c5595de0f4ce375764fc65056c7",
          "dual": "d3d7477a1231bf48605aa6b9b24561d392d285c21028a7b3e85b46c7f65b313e"}


def _golden_template():
    return {"schema": "urn:zeus:autonomous:2", "id": "council-template", "base_revision": "a" * 40,
            "goal": {"path": "docs/GOAL.md", "sha256": "0" * 64, "criterion": "c", "rationale": "r"},
            "plan": {"objective": "improve the research report", "acceptance_criteria": ["focused tests pass"],
                     "allowed_paths": ["docs/RUNBOOK.md"]},
            "budget": {"per_host": 10, "total": 20},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1},
            "deadline": "2030-01-01T00:00:00+00:00",
            "research": {"topic": "research report", "questions": ["What is the SSOT?"], "search_scope": ["docs"]},
            "current_state": {"records": [{"bucket": "tasks", "id": "t-1"}], "max_age_seconds": 600}}


def _golden_config(program_id, **overrides):
    document = {"schema": "urn:zeus:research-program:1", "id": program_id, "base_revision": "a" * 40,
                "deadline": "2029-06-01T00:00:00+00:00", "interval_seconds": 3600, "max_cycles": 2,
                "max_adoptions": 1, "budget": {"per_host": 10, "total": 20},
                "topics": [{"id": "storage", "keywords": ["advisory lock", "postgres"]}],
                "local_candidates": [{"id": "local-note", "topic": "storage", "path": "docs/research/note.md",
                                      "sha256": NOTE_SHA, "rationale": "residual"}],
                "template": _golden_template()}
    document.update(overrides)
    return validate_config(document, packaged_policy())


def _golden_family(store):
    with store.transaction() as tx:
        for job_id, project in (("j-1", "ops"), ("j-2", "ops"), ("j-3", "other")):
            tx.put("fleet_jobs", job_id, {"id": job_id, "status": STATUS, "reason_code": REASON})
            tx.put("portfolio_bindings", job_id, {"job_id": job_id, "project_id": project})
        tx.put("portfolio_investigations", "f" * 64, {
            "id": "f" * 64, "kind": "failure_family", "state": "research_required", "family_status": STATUS,
            "reason_code": REASON, "job_ids": ["j-1", "j-2", "j-3"], "count": 3})


_GOLDEN_ITEMS = [{"source": "local", "identity": "docs/research/note.md", "id": "local-note",
                  "path": "docs/research/note.md", "sha256": NOTE_SHA, "topic": "storage",
                  "title": "docs/research/note.md", "summary": "residual", "url": None, "content_sha256": NOTE_SHA},
                 {"source": "github", "identity": "https://github.com/acme/pgtool", "url": "https://github.com/acme/pgtool",
                  "title": "acme/pgtool", "summary": "Postgres tooling", "content_sha256": "1" * 64}]


def _golden_tick(programs, program_id, result="accepted"):
    reserved = programs.reserve_cycle(program_id, "repo-1")
    if not reserved["reserved"]:
        return [reserved]
    cycle, owner = reserved["cycle"]["id"], reserved["cycle"]["owner"]
    recorded = programs.record_collection(cycle, owner, {"local": {"status": "ok"}}, [dict(i) for i in _GOLDEN_ITEMS],
                                          {"this_host": 0, "all_hosts": 0, "unreadable": 0})
    out = [reserved, recorded]
    if recorded["candidate"] is None:
        out.append(programs.complete_cycle(cycle, owner))
        return out
    run_id = program_id + ".c%03d" % reserved["cycle"]["number"]
    out.append(programs.record_capture(cycle, owner, {"revision": "c" * 40, "ref": "refs/zeus/research/x",
                                                      "path": "docs/x.json", "sha256": "e" * 64}))
    out.append(programs.record_council_start(cycle, owner, run_id, "d" * 64, "sha256:" + "e" * 64))
    with programs.store.transaction() as tx:
        tx.put("autonomous_runs", run_id, {"id": run_id, "status": result, "stage": "promotion",
                                           "manifest_sha256": "d" * 64, "reason_code": "fixture_" + result})
    out.append(programs.record_council_result(cycle, owner, {"result": result, "reason_code": "fixture",
                                                             "row_status": result}))
    return out


def _golden(name) -> str:
    store, clock = MemoryStore(), Clock("2028-01-01T00:00:00+00:00")
    programs = ResearchProgram(store, clock=clock, token=lambda: "0" * 32)
    source = {"topic": "storage", "project_ids": ["ops"], "reason_codes": [REASON]}
    if name == "plain":
        configs = [_golden_config("rp-001")]
    elif name == "family":
        _golden_family(store)
        configs = [_golden_config("rp-001", investigation_source=dict(source)),
                   _golden_config("rp-002", investigation_source=dict(source))]
    else:
        _golden_family(store)
        configs = [_golden_config("rp-001", investigation_source=dict(source),
                                  audit_progress_source={"topic": "storage", "audit_ids": ["audit-1"]})]
    outputs = []
    for cfg in configs:
        outputs += [programs.register(cfg, "repo-1", []), programs.resume(cfg["id"])]
    for cfg in configs:
        outputs += _golden_tick(programs, cfg["id"])
    clock.value = "2028-01-01T02:00:00+00:00"
    for cfg in configs:
        outputs += _golden_tick(programs, cfg["id"], result="rejected")
    for cfg in configs:
        outputs += [programs.status(cfg["id"]), programs.candidates(cfg["id"]), programs.dispatches(cfg["id"])]
    return digest({"outputs": outputs, "records": records(store)})


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_legacy_programs_are_byte_identical_without_an_opted_in_source_or_a_scope_claim(name):
    """U2B-2/U2B-10 pin: the plain, the family and the legacy dual-source program keep their exact bytes."""
    assert _golden(name) == GOLDEN[name]


def test_a_legacy_cycle_carries_no_scope_key_and_reads_no_owner_launch():
    store = MemoryStore()
    _golden_family(store)
    programs = ResearchProgram(store, clock=Clock(), token=lambda: "0" * 32)
    programs.register(_golden_config("rp-001", investigation_source={"topic": "storage", "project_ids": ["ops"],
                                                                     "reason_codes": [REASON]}), "repo-1", [])
    programs.resume("rp-001")
    recorded = collect(programs)   # a random token and no owner action: the legacy reservation never looks
    cycle = get(store, BUCKET_CYCLES, "rp-001:001")
    assert "attempt_scope" not in cycle and "attempt_scope_target" not in cycle
    assert "attempt_scope" not in recorded["cycle"] and "attempt_scope" not in programs.status("rp-001")
    assert recorded["candidate"]["investigation"] == "f" * 64


# ----- identity -------------------------------------------------------------------------------------------------
def test_the_scope_candidate_is_the_full_intent_id_under_the_scope_key():
    store = MemoryStore()
    held_world(store, lineage=False)
    programs = scoped_program(store, token=launch(store))
    recorded = collect(programs)
    candidate = recorded["candidate"]
    assert candidate["id"] == "as-" + I_R and len(candidate["id"]) == 67, "never a shortened second identity"
    assert candidate["key"] == "investigation:" + SCOPE and candidate["kind"] == "attempt_scope"
    assert candidate["investigation"] == SCOPE and candidate["snapshot"]["scope"]["intent_id"] == I_R
    assert get(store, BUCKET_CANDIDATES, "rp-001:as-" + I_R)["status"] == "claimed"


# ----- U2B-3: the P1-shaped fixture captures exactly the held pair -----------------------------------------------
def test_p1_shaped_history_captures_exactly_the_held_pair_and_leaves_history_byte_identical(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store, council=FakeCouncil(store, status="accepted"))
    held_world(store)
    registered(env, attempt_scope_source=dict(SOURCE))
    owner = launch(store)
    env.programs.token = lambda: owner
    before = history(store)
    receipt = env.runner.tick("rp-001", intent="incident")
    assert receipt["selected"] == "as-" + I_R and receipt["investigation"] == SCOPE and receipt["result"] == "accepted"
    row = get(store, BUCKET_DISPATCHES, SCOPE)
    assert row["id"] == row["investigation"] == SCOPE and row["kind"] == "attempt_scope" and row["program"] == "rp-001"
    assert row["job_ids"] == [J_F0, S1] and row["job_ids_total"] == 2 and row["job_ids_sha256"] == digest([J_F0, S1])
    assert row["scope"] == {"schema": "urn:zeus:research-attempt-scope:1", "intent_id": I_R,
                            "continuation_policy": POLICY_ID, "policy_sha256": POLICY_SHA, "family": J_F0,
                            "family_investigation": CAUSE, "attempts": ATTEMPTS, "attempts_sha256": digest(ATTEMPTS)}
    assert row["state"] == "resolved" and row["result"] == "accepted" and row["reported_result"] == "accepted"
    assert not set(HISTORICAL) & set(row["job_ids"]) and Q1 not in json.dumps(row), "no historical member is captured"
    # The cycle keeps its owner-bound target; the council received the exact scope snapshot at the capture.
    cycle = get(store, BUCKET_CYCLES, "rp-001:001")
    assert cycle["owner"] == owner and cycle["investigations"] is None and cycle["audit_progress"] is None
    assert cycle["attempt_scope_target"] == {"scope": SCOPE, "intent_id": I_R, "attempts_sha256": digest(ATTEMPTS)}
    captured = json.loads(git(env.root, "show", cycle["capture"]["revision"] + ":" + cycle["capture"]["path"]).stdout)
    assert "investigation" not in captured and captured["attempt_scope"]["job_ids"] == [J_F0, S1]
    assert captured["attempt_scope"]["job_ids_truncated"] is False and captured["attempt_scope"]["scope"] == row["scope"]
    assert row["snapshot_sha256"] == digest(captured["attempt_scope"])
    view = env.programs.status("rp-001")
    receipt_view = view["cycle_receipts"][0]["attempt_scope"]
    assert receipt_view["counts"]["scanned"] == 1 and receipt_view["counts"]["eligible"] == 1
    assert receipt_view == {**receipt_view, "new": 1, "ineligible": 0, "claimed": SCOPE, "result": "accepted",
                            "reported_result": "accepted"}
    assert view["attempt_scope"]["accepted"] == 1 and view["adoptions"]["dispatched"] == 1
    # The attractive leads were recorded as discovery only: the one adoption went to the exact target.
    leads = {c["id"]: c for c in env.programs.candidates("rp-001") if c["source"] != "investigation"}
    assert leads and all(c["claimed_cycle"] is None for c in leads.values())
    assert history(store) == before, "every historical, Portfolio, Fleet, binding, intent and owner row is unchanged"
    events = [json.loads(line) for line in
              (env.runtime / "research-program" / "rp-001" / "events.jsonl").read_text("utf-8").splitlines()]
    names = [e["event"] for e in events]
    assert {"attempt_scope_scanned", "attempt_scope_claimed", "attempt_scope_result"} <= set(names)
    assert "investigation_claimed" not in names and "investigations_scanned" not in names
    report = (env.runtime / "research-program" / "rp-001" / "report.md").read_text(encoding="utf-8")
    assert "Attempt scope dispatches" in report and "attempt scope scanned 1 eligible 1" in report
    assert CANARY not in json.dumps(events) + report and Q1 not in json.dumps(events) + report


def test_portfolio_membership_of_the_held_jobs_alone_does_not_refuse():
    store = MemoryStore()
    held_world(store, members=HISTORICAL + [J_F0, S1])   # U2B-5: the reconciler added them; no capture holds them
    programs = scoped_program(store, token=launch(store))
    assert collect(programs)["candidate"]["investigation"] == SCOPE
    assert get(store, "portfolio_investigations", CAUSE)["job_ids"] == HISTORICAL + [J_F0, S1]


# ----- U2B-4 / U2B-15: every exclusion after the owner preflight, with attractive leads waiting --------------------
def _drop(store, bucket, key):
    del store.data[(bucket, key)]   # LABELLED: the in-memory store has no delete; a vanished row is the fixture


def _set(bucket, key, **fields):
    def change(store):
        row = get(store, bucket, key)
        row.update(fields)
        put(store, bucket, key, row)
    return change


EXCLUSIONS = {
    "malformed": lambda s: put(s, "portfolio_bindings", "dup", {"job_id": S1, "project_id": "ops"}),
    "state": _set("continuation_intents", I_R, state="awaiting_owner"),
    "policy": _set("continuation_policies", POLICY_ID, policy_sha256="7" * 64),
    "family": _set("continuation_intents", I_R, family="another-root"),
    "receipted": lambda s: put(s, "continuation_research_receipts", I_R, {"id": I_R}),
    "insufficient_attempts": _set("continuation_intents", I_F0, state="refused"),
    "attempt_unavailable": lambda s: _drop(s, "fleet_jobs", S1),
    "mixed": _set("fleet_jobs", S1, reason_code="other_reason"),
    "mixed_evidence": lambda s: put(s, "continuation_intents", hexid("f0b"), intent(
        hexid("f0b"), "correction", "admitted", J_F0, "c" * 64, "2028-01-01T00:05:00+00:00")),
    "reason_code": lambda s: [_set("fleet_jobs", j, reason_code="unlisted_reason")(s) for j in (J_F0, S1)],
    "project": _set("portfolio_bindings", S1, project_id="other"),
    "family_state": _set("portfolio_investigations", CAUSE, state="researched"),
    "family_state_missing": _set("portfolio_investigations", CAUSE, kind="audit_progress"),
    "claimed": lambda s: put(s, BUCKET_HEADS, SCOPE, {"id": SCOPE, "investigation": SCOPE}),
    "overlap": lambda s: put(s, BUCKET_DISPATCHES, "foreign", family_dispatch("foreign", [S1, "x-1"], "rp-x")),
    "overlap_unverifiable": lambda s: put(s, BUCKET_DISPATCHES, "sample", family_dispatch("sample", ["x-1"], "rp-x",
                                                                                          total=60)),
}


@pytest.mark.parametrize("case", sorted(EXCLUSIONS))
def test_each_exclusion_after_reservation_selects_nothing_and_consumes_no_adoption(case):
    store = MemoryStore()
    held_world(store, lineage=False)
    programs = scoped_program(store, token=launch(store))
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    assert reserved["cycle"]["attempt_scope_target"]["scope"] == SCOPE
    EXCLUSIONS[case](store)
    recorded = programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {},
                                          [dict(i) for i in LEADS], COUNTS)
    counts = recorded["cycle"]["attempt_scope"]["counts"]
    name = {"mixed_evidence": "mixed", "family_state_missing": "family_state"}.get(case, case)
    assert counts[name] == 1 and counts["eligible"] == 0, counts
    assert recorded["candidate"] is None and recorded["cycle"]["status"] == "no_selection"
    assert recorded["cycle"]["selection"]["reason"] == "attempt_scope_target_ineligible"
    assert get(store, BUCKET_PROGRAMS, "rp-001")["adoptions"] == 0 and get(store, BUCKET_DISPATCHES, SCOPE) is None
    leads = [c for c in programs.candidates("rp-001") if c["source"] != "investigation"]
    assert leads and all(c["status"] == "eligible" and c["claimed_cycle"] is None for c in leads), \
        "an eligible feed or local lead never substitutes for the target"
    assert programs.complete_cycle(reserved["cycle"]["id"], reserved["cycle"]["owner"])["status"] == "completed"


def test_a_stale_cached_scope_snapshot_is_dropped_and_never_runs_later():
    store = MemoryStore()
    held_world(store, lineage=False)
    programs = scoped_program(store, token=launch(store))
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    cycle = reserved["cycle"]
    full = {"this_host": 10, "all_hosts": 10}   # LABELLED: no headroom, so the eligible target waits cached
    first = programs.record_collection(cycle["id"], cycle["owner"], {}, [], full)
    assert first["cycle"]["selection"]["reason"] == "machine_headroom_insufficient"
    assert programs.candidate("rp-001", "as-" + I_R)["status"] == "eligible"
    programs.complete_cycle(cycle["id"], cycle["owner"])
    second_launch = launch(store, cycle=2)
    programs.clock.value = "2028-01-01T02:00:00+00:00"
    programs.token = lambda: second_launch
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    put(store, "continuation_research_receipts", I_R, {"id": I_R})   # the hold ends after the owner preflight
    second = programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert second["candidate"] is None and second["cycle"]["attempt_scope"]["ineligible"] == 1
    stale = programs.candidate("rp-001", "as-" + I_R)
    assert stale["status"] == "ignored" and stale["reason"] == "attempt_scope_ineligible" and stale["snapshot"] is None
    assert get(store, BUCKET_DISPATCHES, SCOPE) is None


# ----- U2B-15: the owner-bound target ---------------------------------------------------------------------------
def _target_cases():
    def tampered(store):
        owner = launch(store)
        [row] = scan(store, "owner_actions")
        row["binding"]["attempts"] = [S1]
        put(store, "owner_actions", row["id"], row)
        return owner

    def twice(store):
        owner = launch(store)
        [row] = scan(store, "owner_actions")
        put(store, "owner_actions", "copy", {**row, "id": "copy"})
        return owner

    def receipted(store):
        put(store, "continuation_research_receipts", I_R, {"id": I_R})
        return launch(store)
    return {"no_owner_launch": (lambda s: "0" * 32, "cycle_owner"),
            "ambiguous_launch": (twice, "cycle_owner"),
            "intended": (lambda s: launch(s, state=do.INTENDED), "cycle_owner"),
            "completed": (lambda s: launch(s, state=do.COMPLETED), "owner_action"),
            "tampered_binding": (tampered, "owner_action"),
            "other_program": (lambda s: launch(s, program="rp-other"), "binding"),
            "other_cycle": (lambda s: launch(s, cycle=2), "binding"),
            "family_identity": (lambda s: launch(s, investigation=CAUSE), "binding.intent_id"),
            "other_family": (lambda s: launch(s, family="another-root"), "binding.intent_id"),
            "not_held": (receipted, "binding.intent_id"),
            "partial_attempts": (lambda s: launch(s, jobs=(S1,)), "binding.attempts"),
            "wider_attempts": (lambda s: launch(s, jobs=(J_F0, S1, Q1)), "binding.attempts")}


@pytest.mark.parametrize("case", sorted(_target_cases()))
def test_a_missing_or_foreign_owner_target_refuses_before_anything_is_reserved(case):
    store = MemoryStore()
    held_world(store, lineage=False)
    make, field = _target_cases()[case]
    owner = make(store)
    programs = scoped_program(store, token=owner)
    before = get(store, BUCKET_PROGRAMS, "rp-001")
    error = refused(programs.reserve_cycle, "rp-001", "repo-1")
    assert (error.reason_code, error.field) == ("attempt_scope_target_unavailable", field)
    assert get(store, BUCKET_PROGRAMS, "rp-001") == before and scan(store, BUCKET_CYCLES) == []


def test_a_scheduled_runner_tick_without_a_bound_launch_refuses(tmp_path):
    store = MemoryStore()
    env = build(tmp_path, store=store)
    held_world(store, lineage=False)
    registered(env, attempt_scope_source=dict(SOURCE))
    assert refused(env.runner.tick, "rp-001", intent="incident").reason_code == "attempt_scope_target_unavailable"
    assert scan(store, BUCKET_CYCLES) == [] and env.council.manifests == []


def test_the_launching_state_also_binds_and_the_target_is_immutable_through_collection():
    store = MemoryStore()
    held_world(store, lineage=False)
    programs = scoped_program(store, token=launch(store, state=do.LAUNCHING))
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    target = reserved["cycle"]["attempt_scope_target"]
    # A later-recorded earlier failure widens the intent's attempt set after the owner preflight.
    put(store, "continuation_intents", hexid("f1"), intent(hexid("f1"), "correction", "admitted", "late-job", "c" * 64,
                                                           "2028-01-01T00:05:00+00:00"))
    with store.transaction() as tx:
        job(tx, "late-job", "ops")
    recorded = programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert recorded["cycle"]["attempt_scope"]["counts"]["eligible"] == 1, "the widened scope is eligible on its own"
    assert recorded["candidate"] is None and recorded["cycle"]["selection"]["reason"] == "attempt_scope_target_ineligible"
    assert get(store, BUCKET_CYCLES, "rp-001:001")["attempt_scope_target"] == target, "never a new target"
    assert get(store, BUCKET_DISPATCHES, SCOPE) is None and get(store, BUCKET_PROGRAMS, "rp-001")["adoptions"] == 0


def test_another_held_scope_never_replaces_the_target():
    store = MemoryStore()
    held_world(store, lineage=False)
    other_root, other_f, other_r = "other-root", hexid("g0"), hexid("g1")
    source = {**SOURCE, "families": [J_F0, other_root]}
    programs = scoped_program(store, token=launch(store), source=source)
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    with store.transaction() as tx:   # a second held lineage of another listed root becomes eligible meanwhile
        tx.put("continuation_intents", other_f, intent(other_f, "correction", "admitted", "g-0", "d" * 64, T_F0,
                                                       family=other_root))
        tx.put("continuation_intents", other_r, intent(other_r, "research", "research_required", "g-1", "e" * 64, T_R,
                                                       family=other_root))
        job(tx, "g-0", "ops")
        job(tx, "g-1", "ops")
    cycle = reserved["cycle"]
    both = programs.record_collection(cycle["id"], cycle["owner"], {}, [], COUNTS)
    assert both["cycle"]["attempt_scope"]["counts"]["eligible"] == 2
    assert both["candidate"] is None and both["cycle"]["selection"]["reason"] == "attempt_scope_target_ambiguous"
    programs.complete_cycle(cycle["id"], cycle["owner"])
    second_launch = launch(store, cycle=2)
    programs.clock.value = "2028-01-01T02:00:00+00:00"
    programs.token = lambda: second_launch
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    put(store, "continuation_research_receipts", I_R, {"id": I_R})   # the target leaves; the other stays eligible
    alone = programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert alone["cycle"]["attempt_scope"]["counts"]["eligible"] == 1
    assert alone["candidate"] is None and alone["cycle"]["selection"]["reason"] == "attempt_scope_target_ineligible"
    assert scan(store, BUCKET_DISPATCHES) == [], "the other held scope is never claimed on this owner's launch"
    assert get(store, BUCKET_PROGRAMS, "rp-001")["adoptions"] == 0


@pytest.mark.parametrize("state,rival", [("paused", True), ("active", True), ("stopped", True), ("mystery", True),
                                         ("completed", False), ("blocked", False)])
def test_rival_programs_withhold_the_target_unless_completed_or_blocked(state, rival):
    store = MemoryStore()
    held_world(store, lineage=False)
    put(store, BUCKET_PROGRAMS, "rp-legacy", {"id": "rp-legacy", "state": state,
                                              "config": {"investigation_source": dict(FAMILY_SOURCE)}})
    programs = scoped_program(store, token=launch(store))
    recorded = collect(programs, items=LEADS)
    if rival:
        assert recorded["candidate"] is None
        assert recorded["cycle"]["selection"]["reason"] == "attempt_scope_competing_program"
        assert get(store, BUCKET_PROGRAMS, "rp-001")["adoptions"] == 0
    else:
        assert recorded["candidate"]["investigation"] == SCOPE


def test_a_scoped_rival_sharing_the_policy_and_a_root_withholds_the_target():
    store = MemoryStore()
    held_world(store, lineage=False)
    scoped_program(store, program_id="rp-002")   # paused registration never ticks, but could take the same work
    ResearchProgram(store).pause("rp-002")
    programs = scoped_program(store, token=launch(store))
    recorded = collect(programs)
    assert recorded["candidate"] is None and recorded["cycle"]["selection"]["reason"] == "attempt_scope_competing_program"


# ----- U2B-7: one claim, one adoption; stale candidates and pre-commit faults roll back whole ---------------------
def test_a_second_program_and_a_repeated_tick_see_the_claim_and_consume_nothing():
    store = MemoryStore()
    held_world(store)
    first, recorded = claim_scope(store)
    assert recorded["cycle"]["attempt_scope"]["claimed"] == SCOPE
    second = scoped_program(store, program_id="rp-002", token=launch(store, program="rp-002"))
    other = collect(second, "rp-002", items=LEADS)
    assert other["candidate"] is None and other["cycle"]["attempt_scope"]["counts"]["claimed"] == 1
    assert get(store, BUCKET_PROGRAMS, "rp-002")["adoptions"] == 0
    # A restarted coordinator on the same launch finds the owned cycle busy, never a second reservation.
    restarted = ResearchProgram(store, clock=Clock(), token=first.token)
    assert restarted.reserve_cycle("rp-001", "repo-1")["reason"] == "busy"
    assert [d["id"] for d in scan(store, BUCKET_DISPATCHES) if d.get("kind") == "attempt_scope"] == [SCOPE]


def test_a_stale_scope_candidate_hits_the_claim_row_and_rolls_back_whole(monkeypatch):
    """LABELLED injected fault: eligibility forgets every lifecycle row. The claim defence must still refuse
    inside the transaction and leave no candidate, selection or adoption behind."""
    store = MemoryStore()
    held_world(store, lineage=False)
    first, recorded = claim_scope(store)
    first.fail_cycle(recorded["cycle"]["id"], recorded["cycle"]["owner"], "capture", "fixture")   # blocked: no rival
    forgetful = application.eligible_attempt_scopes
    monkeypatch.setattr(application, "eligible_attempt_scopes", lambda **kw: forgetful(
        **{**kw, "dispatches": [], "recoveries": [], "heads": [], "successors": []}))
    second = scoped_program(store, program_id="rp-002", token=launch(store, program="rp-002"))
    reserved = second.reserve_cycle("rp-002", "repo-1")
    before = records(store)
    error = refused(second.record_collection, reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert error.reason_code == "investigation_already_claimed"
    assert records(store) == before, "candidate, cycle selection and adoption rolled back together"
    assert get(store, BUCKET_CYCLES, "rp-002:001")["status"] == "collecting"


def test_a_fault_before_commit_rolls_back_the_selection_the_adoption_and_the_claim(monkeypatch):
    store = MemoryStore()
    held_world(store, lineage=False)
    programs = scoped_program(store, token=launch(store))
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    before = records(store)

    def crash(**kwargs):
        raise RuntimeError("LABELLED injected fault before commit")
    monkeypatch.setattr(application, "dispatch_row", crash)
    with pytest.raises(RuntimeError):
        programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert records(store) == before
    monkeypatch.undo()
    replay = programs.record_collection(reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert replay["candidate"]["investigation"] == SCOPE and get(store, BUCKET_PROGRAMS, "rp-001")["adoptions"] == 1


# ----- U2B-9: forward overlap, before selection and again at the claim ---------------------------------------------
FORWARD = {
    "claimed": lambda s: put(s, BUCKET_DISPATCHES, "f", family_dispatch("f", [S1], "rp-x", state="claimed", result=None)),
    "dispatched": lambda s: put(s, BUCKET_DISPATCHES, "f", family_dispatch("f", [J_F0], "rp-x", state="dispatched",
                                                                           result=None)),
    "accepted": lambda s: put(s, BUCKET_DISPATCHES, "f", family_dispatch("f", [S1], "rp-x", result="accepted")),
    "rejected": lambda s: put(s, BUCKET_DISPATCHES, "f", family_dispatch("f", [S1], "rp-x", result="rejected")),
    "unknown": lambda s: put(s, BUCKET_DISPATCHES, "f", family_dispatch("f", [J_F0], "rp-x", result="unknown")),
    "pinned_followup": lambda s: put(s, BUCKET_SUCCESSORS, CAUSE + ":2", {
        "id": CAUSE + ":2", "investigation": CAUSE, "version": 2, "state": "authorized",
        "members": {"job_ids": [J_F0, "x-1"], "sha256": digest([J_F0, "x-1"])}}),
    "truncated_sample": lambda s: put(s, BUCKET_DISPATCHES, "f", family_dispatch("f", ["x-1"], "rp-x", total=51)),
}


@pytest.mark.parametrize("case", sorted(FORWARD))
def test_forward_overlap_refuses_before_selection_and_again_at_the_claim(case, monkeypatch):
    store = MemoryStore()
    held_world(store, lineage=False)
    FORWARD[case](store)
    programs = scoped_program(store, token=launch(store))
    recorded = collect(programs)
    exclusion = "overlap_unverifiable" if case == "truncated_sample" else "overlap"
    assert recorded["cycle"]["attempt_scope"]["counts"][exclusion] == 1 and recorded["candidate"] is None
    # LABELLED injected fault: the rule forgets every reservation; the claim defence still refuses whole.
    forgetful = application.eligible_attempt_scopes
    monkeypatch.setattr(application, "eligible_attempt_scopes", lambda **kw: forgetful(
        **{**kw, "dispatches": [], "successors": []}))
    programs.complete_cycle("rp-001:001", recorded["cycle"]["owner"])
    second_launch = launch(store, cycle=2)
    programs.clock.value = "2028-01-01T02:00:00+00:00"
    programs.token = lambda: second_launch
    reserved = programs.reserve_cycle("rp-001", "repo-1")
    before = records(store)
    error = refused(programs.record_collection, reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert error.reason_code == "attempt_scope_overlap" and records(store) == before


# ----- U2B-10: reverse overlap, permanent in every state ------------------------------------------------------------
def reverse_world(store, members=(J_F0, S1, "h-1", "h-2")):
    """No family history: the undecided cause holds the held pair plus two other scoped members."""
    held_world(store, lineage=False, members=list(members))
    with store.transaction() as tx:
        for member in members:
            if member not in (J_F0, S1):
                job(tx, member, "ops")


@pytest.mark.parametrize("state,result", [("claimed", None), ("dispatched", None), ("resolved", "accepted"),
                                          ("resolved", "rejected"), ("resolved", "failed"), ("resolved", "unknown")])
def test_a_scope_claim_in_any_state_blocks_the_family_and_its_recovery_replacement(state, result, monkeypatch):
    store = MemoryStore()
    reverse_world(store)
    claim_scope(store)
    row = get(store, BUCKET_DISPATCHES, SCOPE)
    row.update(state=state, result=result)   # LABELLED: the scope claim's lifecycle, never released
    put(store, BUCKET_DISPATCHES, SCOPE, row)
    # An authorized replacement for the family program would otherwise release the family claim.
    put(store, BUCKET_RECOVERIES, CAUSE, {"id": CAUSE, "investigation": CAUSE, "state": "authorized",
                                          "failed": {"program": "rp-x"}, "request_sha256": "6" * 64,
                                          "replacement": {"program": "rp-fam", "dispatch": CAUSE + ".recovery-1"}})
    family = family_program(store)
    recorded = collect(family, "rp-fam")
    bridge = recorded["cycle"]["investigations"]
    assert bridge["counts"]["claimed"] == 1 and bridge["counts"]["eligible"] == 0 and recorded["candidate"] is None
    # LABELLED injected fault: the pre-filter forgets the scope; the claim defence refuses the replacement whole.
    monkeypatch.setattr(application.ResearchProgram, "_scope_held_families", staticmethod(lambda *a: set()))
    family.complete_cycle("rp-fam:001", recorded["cycle"]["owner"])
    family.clock.value = "2028-01-01T02:00:00+00:00"
    reserved = family.reserve_cycle("rp-fam", "repo-1")
    before = records(store)
    error = refused(family.record_collection, reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert error.reason_code == "investigation_scope_overlap" and records(store) == before


def test_a_disjoint_family_stays_eligible_and_a_truncated_same_cause_family_is_blocked(monkeypatch):
    store = MemoryStore()
    many = ["m-%02d" % i for i in range(55)]
    reverse_world(store, members=many)   # the cause row never holds the pair, but its sample is truncated
    other = family_id("rejected", "review_rejected")
    with store.transaction() as tx:
        for member in ("r-1", "r-2"):
            job(tx, member, "ops", status="rejected", reason="review_rejected")
        tx.put("portfolio_investigations", other, {"id": other, "kind": "failure_family", "state": "research_required",
                                                   "family_status": "rejected", "reason_code": "review_rejected",
                                                   "job_ids": ["r-1", "r-2"], "count": 2})
    claim_scope(store)
    family = family_program(store)
    recorded = collect(family, "rp-fam")
    assert recorded["candidate"]["investigation"] == other, "a disjoint complete family keeps its existing rule"
    assert recorded["cycle"]["investigations"]["counts"]["claimed"] == 1, "the truncated same-cause family is held"
    monkeypatch.setattr(application.ResearchProgram, "_scope_held_families", staticmethod(lambda *a: set()))
    second = family_program(store, program_id="rp-fam2")
    reserved = second.reserve_cycle("rp-fam2", "repo-1")
    error = refused(second.record_collection, reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert error.reason_code == "investigation_scope_overlap", "a truncated sample cannot prove disjointness"


def test_the_legacy_sweep_never_touches_a_scope_candidate():
    store = MemoryStore()
    programs = ResearchProgram(store, clock=Clock())
    scoped = {"id": "as-" + I_R, "_key": "rp-x:as-" + I_R, "source": "investigation", "kind": "attempt_scope",
              "status": "eligible", "investigation": SCOPE, "snapshot": {"investigation": SCOPE}}
    known = {"investigation:" + SCOPE: dict(scoped)}
    row = {"id": "rp-x", "config": {"investigation_source": dict(FAMILY_SOURCE)}}
    with store.transaction() as tx:
        receipt = programs._investigations(tx, row, {"number": 1}, known, "2028-01-01T00:00:00+00:00")
    assert receipt["ineligible"] == 0 and known["investigation:" + SCOPE] == scoped


# ----- U2B-11: a scope claim is final: no recovery, successor or follow-up names it --------------------------------
def _pinned(dispatch):
    return {k: dispatch[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}


def _requests(dispatch, replacement_sha):
    failed = {"program": "rp-001", **_pinned(dispatch)}
    replacement = {"program": "rp-002", "config_sha256": replacement_sha}
    predecessor = {"dispatch": SCOPE, "lineage_version": 0, "lineage_request_sha256": None, "program": "rp-001",
                   "config_sha256": "8" * 64, **_pinned(dispatch)}
    return {
        "v1_transport": {"schema": "urn:zeus:research-dispatch-recovery:1", "investigation": SCOPE, "failed": failed,
                         "replacement": replacement},
        "v2_revocation": {"schema": "urn:zeus:research-dispatch-recovery:2", "mode": "execution_revocation",
                          "investigation": SCOPE, "failed": failed, "replacement": replacement,
                          "revoke": {"message_id": "m-1", "source_sha256": "9" * 64}},
        "v3_successor": {"schema": "urn:zeus:research-dispatch-recovery:3", "mode": "settled_read_only_successor",
                         "investigation": SCOPE, "replacement": replacement,
                         "predecessor": {**predecessor, "dispatch": SCOPE + ".recovery-1", "lineage_version": 1,
                                         "lineage_request_sha256": "6" * 64}},
        "v4_contract": {"schema": "urn:zeus:research-dispatch-recovery:4", "mode": "settled_contract_failure_successor",
                        "investigation": SCOPE, "replacement": replacement, "predecessor": predecessor,
                        "failure": {"role": "improvement_lead", "task_id": "t-1", "execution_ref": "sha256:" + "a" * 64,
                                    "check": "council_field_invalid:improvement_lead.summary:too_long"}},
        "followup": {"schema": "urn:zeus:research-dispatch-followup:1", "mode": "accepted_evidence_followup",
                     "investigation": SCOPE, "replacement": replacement, "predecessor": predecessor,
                     "members": {"previous_sha256": dispatch["job_ids_sha256"], "job_ids": [J_F0, S1, "x-1"],
                                 "sha256": digest([J_F0, S1, "x-1"])}}}


def test_no_recovery_version_successor_or_followup_may_name_a_scope_and_nothing_is_written():
    store = MemoryStore()
    held_world(store, lineage=False)
    programs, recorded = claim_scope(store)
    cycle, owner = recorded["cycle"]["id"], recorded["cycle"]["owner"]
    programs.record_capture(cycle, owner, {"revision": "c" * 40, "ref": "r", "path": "p"})
    programs.record_council_start(cycle, owner, "rp-001.c001", "d" * 64, "sha256:" + "e" * 64)
    programs.fail_cycle(cycle, owner, "council_start", "publication_incomplete")
    dispatch = get(store, BUCKET_DISPATCHES, SCOPE)
    assert dispatch["result"] == "failed" and dispatch["kind"] == "attempt_scope"
    replacement = scoped_program(store, program_id="rp-002")
    sha = get(store, BUCKET_PROGRAMS, "rp-002")["config_sha256"]
    before = records(store)
    for name, document in _requests(dispatch, sha).items():
        # Each request is well formed (its own strict validator passes), so only the scope guard refuses it; the
        # transport and evidence ports are inert objects that a refusal before any read never touches.
        error = refused(replacement.recover_dispatch, document, object(), object())
        assert (error.reason_code, error.field) == ("attempt_scope_final", "investigation"), name
        assert records(store) == before, name + " wrote something"
    # The failed claim keeps its members: another program, or a fresh held intent retrying the same jobs, cannot
    # reclaim them.
    replacement_launch = launch(store, program="rp-002")
    replacement.token = lambda: replacement_launch
    again = collect(replacement, "rp-002")
    assert again["candidate"] is None and again["cycle"]["attempt_scope"]["counts"]["claimed"] == 1
    retry = hexid("r2")
    with store.transaction() as tx:
        tx.put("continuation_intents", retry, intent(retry, "research", "research_required", "s2-job", "f" * 64,
                                                     "2028-01-01T00:20:00+00:00"))
        job(tx, "s2-job", "ops")
    third = scoped_program(store, program_id="rp-003", token=launch(store, program="rp-003", intent_id=retry,
                                                                     jobs=(J_F0, "s2-job")))
    fresh = collect(third, "rp-003")
    assert fresh["candidate"] is None and fresh["cycle"]["attempt_scope"]["counts"]["overlap"] == 1
    assert [d["id"] for d in scan(store, BUCKET_DISPATCHES)] == [SCOPE]


# ----- U2B-10 / U2B-11: reverse exclusion at AUTHORIZATION, not only at the claim ----------------------------------
# Each world is an existing, otherwise valid legacy authorization fixture of test_research_recovery (recovery v1 and
# v2, successor v3 and v4) or test_continuation_research (the accepted-report follow-up): REAL store transactions,
# state machine, Portfolio reconciler and CouncilRun; LABELLED councils, fixture role executors, transport proof,
# artifact store and clock. The stored scope claims are LABELLED synthetic rows. No executor transport is driven.
SCOPE_STATES = [("claimed", None), ("dispatched", None), ("resolved", "accepted"), ("resolved", "rejected"),
                ("resolved", "failed"), ("resolved", "unknown")]
RECOVERY_CAUSE = ("failed", "store_timeout")
DISJOINT = ["x-held", "x-other"]    # LABELLED scope members that are in no family


@pytest.fixture
def inert_executor(monkeypatch):
    """Belt and braces: none of these worlds drives the executor, and neither executor transport could start."""
    from codex_harness.adapters import executor

    def never(*args, **kwargs):
        raise AssertionError("an executor transport was started")
    monkeypatch.setattr(executor, "AppServer", never)
    monkeypatch.setattr(executor, "ClaudeCodeRuntime", never)


class EvidenceSpy:
    """LABELLED wrapper of the executor artifact store: records every execution artifact read."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def document(self, ref):
        self.calls.append(ref)
        return self.inner.document(ref)


class CommitsFirst:
    """LABELLED interleaving: the first port read (transport probe or artifact load, both outside any transaction)
    commits a concurrent scope claim, after the read step and before the writing transaction."""

    def __init__(self, inner, commit):
        self.inner, self.commit, self.calls = inner, commit, []

    def _read(self):
        self.calls.append(True)
        if len(self.calls) == 1:
            self.commit()

    def inspect(self, recipient, message_id):
        self._read()
        return self.inner.inspect(recipient, message_id)

    def document(self, ref):
        self._read()
        return self.inner.document(ref)


def scope_claim(key, ids, cause, state="resolved", result="failed"):
    """A LABELLED stored attempt-scope claim of `cause` holding `ids`; whatever its state it is never released."""
    listed = isinstance(ids, list)
    ids = sorted(ids, key=str) if listed else ids
    return {"schema": "urn:zeus:research-investigation-dispatch:1", "id": key, "investigation": key,
            "kind": "attempt_scope", "program": "rp-scope", "cycle": "rp-scope:001", "cycle_number": 1,
            "state": state, "family_status": cause[0], "reason_code": cause[1], "job_ids": ids,
            "job_ids_total": len(ids) if listed else None, "job_ids_sha256": digest(ids) if listed else None,
            "result": result, "claimed_at": T0, "updated_at": T0}


def later_member(store, job_id="j-5"):
    """A LABELLED later same-cause Fleet job that the REAL Portfolio binds and reconciles into the family AFTER its
    dispatch was captured: the captured history is unchanged, the family's CURRENT scoped membership grew."""
    from test_research_investigations import DEFINITIONS

    from codex_harness.application.portfolio import Portfolio
    with store.transaction() as tx:
        tx.put("fleet_jobs", job_id, {"id": job_id, "lane": "lane-1", "status": RECOVERY_CAUSE[0],
                                      "reason_code": RECOVERY_CAUSE[1], "error_type": None, "updated_at": T0})
    owner = Portfolio(store, DEFINITIONS, clock=lambda: T0)
    owner.bind(job_id, "ops", "c1")
    owner.reconcile()
    return job_id


def _v1_transport(tmp_path):
    from test_research_recovery import FakeTransport, failed_world, replacement, request
    env, _ = failed_world(tmp_path)
    _, sha = replacement(env)
    return SimpleNamespace(store=env.store, clock=env.clock, document=request(env, sha), member=later_member(env.store),
                           cause=RECOVERY_CAUSE, field="investigation", ports=lambda: (FakeTransport(), None))


def _v2_revocation(tmp_path):
    from test_research_recovery import legacy_world, replacement, revocation
    env, _ = legacy_world(tmp_path)
    _, sha = replacement(env)
    return SimpleNamespace(store=env.store, clock=env.clock, document=revocation(env, sha),
                           member=later_member(env.store), cause=RECOVERY_CAUSE, field="investigation",
                           ports=lambda: (None, None))


def _v3_successor(tmp_path):
    from test_research_recovery import (
        FakeTransport,
        read_only_world,
        replacement,
        successor_request,
    )
    env, council, _ = read_only_world(tmp_path)
    _, sha = replacement(env, "rp-003")
    return SimpleNamespace(store=env.store, clock=env.clock, document=successor_request(env, sha),
                           member=later_member(env.store), cause=RECOVERY_CAUSE, field="investigation",
                           ports=lambda: (FakeTransport(error=AssertionError("never read")),
                                          EvidenceSpy(council.artifacts)))


def _v4_contract(tmp_path):
    from test_research_recovery import FakeTransport, contract_request, initial_world, replacement
    env, council = initial_world(tmp_path)
    _, sha = replacement(env)
    return SimpleNamespace(store=env.store, clock=env.clock, document=contract_request(env, sha),
                           member=later_member(env.store), cause=RECOVERY_CAUSE, field="investigation",
                           ports=lambda: (FakeTransport(error=AssertionError("never read")),
                                          EvidenceSpy(council.artifacts)))


def _followup(tmp_path):
    from test_continuation import World
    from test_continuation_research import accepted_report, followup_program, followup_request
    world = World(tmp_path)
    env, owner, _, successor, _, _, dispatch = accepted_report(world, tmp_path)
    sha = followup_program(env)
    owner.bind(successor, "ops", "c1")   # the newly observed member the follow-up pins
    return SimpleNamespace(store=world.control, clock=env.clock,
                           document=followup_request(world, dispatch, [*dispatch["job_ids"], successor], sha),
                           member=successor, cause=("failed", "evidence_gate_refused"), field="members.job_ids",
                           ports=lambda: (None, None))


AUTHORIZATIONS = {"v1_transport": _v1_transport, "v2_revocation": _v2_revocation, "v3_successor": _v3_successor,
                  "v4_contract": _v4_contract, "followup": _followup}


def authorize(world, store=None, ports=None):
    transport, evidence = ports or world.ports()
    return ResearchProgram(store or world.store, clock=world.clock).recover_dispatch(world.document, transport, evidence)


def copy_store(store) -> MemoryStore:
    copy = MemoryStore()
    rows = records(store)
    with copy.transaction() as tx:
        for row in rows:
            tx.put(row["bucket"], row["id"], row["body"])
    return copy


@pytest.mark.parametrize("kind", sorted(AUTHORIZATIONS))
def test_an_authorization_whose_claim_would_take_a_scope_held_job_refuses_in_every_state_with_zero_writes(
        kind, tmp_path, inert_executor):
    """Recovery v1-v4 and successor over the family's CURRENT scoped membership (which the replacement recaptures),
    and the follow-up over its pinned members: a scope claim holding one member refuses the authorization
    `investigation_scope_overlap` before any fence, quarantine, lineage row or head, in every scope state."""
    world = AUTHORIZATIONS[kind](tmp_path)
    key = attempt_scope_id(hexid("held-" + kind))
    for state, result in SCOPE_STATES:
        put(world.store, BUCKET_DISPATCHES, key, scope_claim(key, [world.member, "x-held"], world.cause, state, result))
        before = records(world.store)
        transport, evidence = world.ports()
        error = refused(authorize, world, ports=(transport, evidence))
        assert (error.reason_code, error.field) == ("investigation_scope_overlap", world.field), (state, result)
        assert records(world.store) == before, (state, result, "zero writes")
        assert getattr(transport, "calls", []) == [] and getattr(evidence, "calls", []) == [], "no port was read"
    # LABELLED fixture step (a stored scope claim is never released in production): with the claim's members made
    # disjoint the SAME request authorizes, so the one intersecting member alone refused it.
    put(world.store, BUCKET_DISPATCHES, key, scope_claim(key, DISJOINT, world.cause))
    assert authorize(world)["state"] == "authorized"


@pytest.mark.parametrize("scope", ["none", "disjoint"])
@pytest.mark.parametrize("kind", sorted(AUTHORIZATIONS))
def test_pin_without_an_intersecting_scope_claim_the_same_authorization_is_byte_identical(
        kind, scope, tmp_path, monkeypatch, inert_executor):
    """PIN (U2B-10 K): with no scope claim, or a disjoint complete one of the same cause, every authorization is
    exactly what it is without the guard: the same result and the same store bytes."""
    world = AUTHORIZATIONS[kind](tmp_path)
    if scope == "disjoint":
        key = attempt_scope_id(hexid("disjoint-" + kind))
        put(world.store, BUCKET_DISPATCHES, key, scope_claim(key, DISJOINT, world.cause))
    # LABELLED fixed wall clock of the outbox quarantine and the task fence, so two stores compare byte for byte.
    monkeypatch.setattr("codex_harness.application.outbox.utcnow", lambda: T0)
    monkeypatch.setattr("codex_harness.application.execution_fence.utcnow", lambda: T0)
    legacy = copy_store(world.store)
    result = authorize(world)
    # LABELLED: the same request on an identical copy with the authorization guard removed.
    monkeypatch.setattr(application.ResearchProgram, "_refuse_scope_overlap", lambda self, tx, request: None,
                        raising=False)
    assert authorize(world, legacy) == result and result["state"] == "authorized"
    assert records(world.store) == records(legacy)


@pytest.mark.parametrize("kind", ["v1_transport", "v3_successor", "v4_contract"])
def test_a_scope_claim_committed_during_the_port_read_is_refused_by_the_writing_transaction(
        kind, tmp_path, inert_executor):
    """The guard is re-read in the transaction that writes: a claim committed while the transport or the execution
    artifacts are read (outside any transaction) still refuses, and no authorization, successor or head is
    written. A v1 row fenced before the claim existed stays fenced, never authorized."""
    world = AUTHORIZATIONS[kind](tmp_path)
    key = attempt_scope_id(hexid("race-" + kind))
    transport, evidence = world.ports()

    def commit():
        put(world.store, BUCKET_DISPATCHES, key, scope_claim(key, [world.member, "x-held"], world.cause))
    if kind == "v1_transport":
        transport = CommitsFirst(transport, commit)
    else:
        evidence = CommitsFirst(evidence, commit)

    def lineage():
        return {bucket: scan(world.store, bucket) for bucket in (BUCKET_RECOVERIES, BUCKET_SUCCESSORS, BUCKET_HEADS)}
    before = lineage()
    error = refused(authorize, world, ports=(transport, evidence))
    assert (error.reason_code, error.field) == ("investigation_scope_overlap", "investigation")
    assert get(world.store, BUCKET_DISPATCHES, key) is not None, "the interleaved claim did commit"
    after = lineage()
    if kind == "v1_transport":
        assert before[BUCKET_RECOVERIES] == [] and [r["state"] for r in after[BUCKET_RECOVERIES]] == ["fenced"]
        assert after[BUCKET_SUCCESSORS] == before[BUCKET_SUCCESSORS] and after[BUCKET_HEADS] == before[BUCKET_HEADS]
    else:
        assert after == before, "no successor row and no head"


# ----- a scope claim whose job ids cannot be read holds its whole cause (the owner layer's rule, mirrored) --------
@pytest.mark.parametrize("ids", [None, "hist-01", [""], [None]], ids=["null", "string", "empty_id", "null_id"])
def test_a_scope_claim_whose_members_cannot_be_read_holds_every_family_of_its_cause(ids, monkeypatch):
    store = MemoryStore()
    reverse_world(store)
    other = family_id("rejected", "review_rejected")
    with store.transaction() as tx:
        for member in ("r-1", "r-2"):
            job(tx, member, "ops", status="rejected", reason="review_rejected")
        tx.put("portfolio_investigations", other, {"id": other, "kind": "failure_family", "state": "research_required",
                                                   "family_status": "rejected", "reason_code": "review_rejected",
                                                   "job_ids": ["r-1", "r-2"], "count": 2})
    key = attempt_scope_id(hexid("unreadable"))
    put(store, BUCKET_DISPATCHES, key, scope_claim(key, ids, (STATUS, REASON)))
    family = family_program(store)
    recorded = collect(family, "rp-fam")
    assert recorded["cycle"]["investigations"]["counts"]["claimed"] == 1, "unknown membership never proves disjoint"
    assert recorded["candidate"]["investigation"] == other, "another cause keeps its legacy eligibility"
    # LABELLED injected fault: the pre-filter forgets the scope; the claim defence still refuses the family whole.
    monkeypatch.setattr(application.ResearchProgram, "_scope_held_families", staticmethod(lambda *a: set()))
    second = family_program(store, program_id="rp-fam2")
    reserved = second.reserve_cycle("rp-fam2", "repo-1")
    before = records(store)
    error = refused(second.record_collection, reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [], COUNTS)
    assert error.reason_code == "investigation_scope_overlap" and records(store) == before


def test_an_unreadable_same_cause_scope_claim_refuses_a_recovery_authorization_with_zero_writes(
        tmp_path, inert_executor):
    world = _v1_transport(tmp_path)
    key = attempt_scope_id(hexid("unreadable-recovery"))
    put(world.store, BUCKET_DISPATCHES, key, scope_claim(key, None, world.cause))
    before = records(world.store)
    transport, evidence = world.ports()
    error = refused(authorize, world, ports=(transport, evidence))
    assert (error.reason_code, error.field) == ("investigation_scope_overlap", "investigation")
    assert records(world.store) == before and transport.calls == []


# ----- U2B-8: concurrent claims (memory, and real isolated PostgreSQL when HARNESS_INTEGRATION=1) -------------------
def _race(left, right):
    """Two already reserved collections released together; neither holds a barrier inside its transaction."""
    start, results, errors = threading.Barrier(2), {}, []

    def run(name, programs, cycle):
        start.wait()
        try:
            results[name] = programs.record_collection(cycle["id"], cycle["owner"], {}, [], COUNTS)
        except Exception as exc:   # pragma: no cover - asserted below
            errors.append(exc)
    threads = [threading.Thread(target=run, args=args) for args in (left, right)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []
    return results


def _two_scoped_programs(store):
    held_world(store, lineage=False)
    pairs = []
    for program_id in ("rp-001", "rp-002"):
        programs = scoped_program(store, program_id=program_id, token=launch(store, program=program_id))
        pairs.append((program_id, programs, programs.reserve_cycle(program_id, "repo-1")["cycle"]))
    return pairs


def _scoped_race(store, monkeypatch):
    """Two active scoped programs sharing the policy and root are each other's rival, so neither claims. With the
    rival read bypassed (LABELLED injected fault), the claim transaction alone must still let exactly one win."""
    pairs = _two_scoped_programs(store)
    results = _race(*pairs)
    assert scan(store, BUCKET_DISPATCHES) == [] and all(r["candidate"] is None for r in results.values())
    assert {r["cycle"]["selection"]["reason"] for r in results.values()} == {"attempt_scope_competing_program"}
    monkeypatch.setattr(application, "scope_rivals", lambda *a, **k: [])
    for program_id, programs, cycle in pairs:
        programs.complete_cycle(cycle["id"], cycle["owner"])
        programs.clock.value = "2028-01-01T02:00:00+00:00"
        again = launch(store, program=program_id, cycle=2)
        programs.token = lambda owner=again: owner
    pairs = [(p, programs, programs.reserve_cycle(p, "repo-1")["cycle"]) for p, programs, _ in pairs]
    results = _race(*pairs)
    assert [d["id"] for d in scan(store, BUCKET_DISPATCHES)] == [SCOPE]
    assert sum(r["candidate"] is not None for r in results.values()) == 1
    assert sum(get(store, BUCKET_PROGRAMS, p)["adoptions"] for p in results) == 1
    loser = next(r for r in results.values() if r["candidate"] is None)
    assert loser["cycle"]["attempt_scope"]["counts"]["claimed"] == 1, "the loser observes the committed claim"


def test_two_scoped_programs_race_for_one_held_intent_and_exactly_one_claims(monkeypatch):
    _scoped_race(MemoryStore(), monkeypatch)


@pytest.mark.integration
def test_postgres_two_scoped_programs_race_for_one_held_intent(isolated_pgstore, monkeypatch):
    _scoped_race(isolated_pgstore, monkeypatch)


def _scope_versus_family(store, order, monkeypatch):
    reverse_world(store)
    if order == "scope_first":
        # The scope claims while no rival exists; a family program registered later can never take the pair.
        claim_scope(store)
        family = family_program(store)
        recorded = collect(family, "rp-fam")
        assert recorded["candidate"] is None and recorded["cycle"]["investigations"]["counts"]["claimed"] == 1
    elif order == "family_first":
        # The family program claims the pair first and is then blocked; the scope is overlap, never a second claim.
        family = family_program(store)
        recorded = collect(family, "rp-fam")
        assert recorded["candidate"]["investigation"] == CAUSE
        family.fail_cycle(recorded["cycle"]["id"], recorded["cycle"]["owner"], "capture", "fixture")
        scoped = scoped_program(store, token=launch(store))
        other = collect(scoped)
        assert other["candidate"] is None and other["cycle"]["attempt_scope"]["counts"]["overlap"] == 1
    else:
        # Both active at once are rivals; the rival read is bypassed (LABELLED injected fault) so the two claim
        # transactions really race, and the serialized overlap checks alone must leave one holder of the pair.
        monkeypatch.setattr(application, "scope_rivals", lambda *a, **k: [])
        scoped, family = scoped_program(store, token=launch(store)), family_program(store)
        _race(("rp-001", scoped, scoped.reserve_cycle("rp-001", "repo-1")["cycle"]),
              ("rp-fam", family, family.reserve_cycle("rp-fam", "repo-1")["cycle"]))
    claims = scan(store, BUCKET_DISPATCHES)
    assert len(claims) == 1 and len([d for d in claims if {J_F0, S1} & set(d["job_ids"])]) == 1
    assert claims[0]["id"] == {"scope_first": SCOPE, "family_first": CAUSE}.get(order, claims[0]["id"])
    assert sum(get(store, BUCKET_PROGRAMS, p)["adoptions"] for p in ("rp-001", "rp-fam")
               if get(store, BUCKET_PROGRAMS, p) is not None) == 1


@pytest.mark.parametrize("order", ["scope_first", "family_first", "race"])
def test_scope_versus_family_in_either_winning_order_leaves_one_claim(order, monkeypatch):
    _scope_versus_family(MemoryStore(), order, monkeypatch)


@pytest.mark.integration
@pytest.mark.parametrize("order", ["scope_first", "family_first", "race"])
def test_postgres_scope_versus_family_in_either_winning_order_leaves_one_claim(order, isolated_pgstore, monkeypatch):
    _scope_versus_family(isolated_pgstore, order, monkeypatch)
