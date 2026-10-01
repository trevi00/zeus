"""Shared S8 scenario steps (`research.program_records`): the record and accounting surface of M7
`application/research_program.py` `ResearchProgram` that `ProgramRunner` and the owner paths use, characterized BEFORE
step 3 moves it (DESIGN-s8 §2 row `research.program_records` and V8; TRACE-s8 §2 "Adoption accounting").

- **g1_registration**: `register` strictness and immutability, the identical register again, `config`, `pause`/`resume`
  transitions and refusals, and the M7 `test_config_is_strict_and_binds_template_base_and_budget` and
  `test_registration_is_immutable_and_counters_and_schedule_are_durable` cases.
- **g2_reservation**: `reserve_cycle` reserved, busy, paused, completed, blocked, deadline, the cycles cap, not due,
  `repository_mismatch`, the remaining counts, and two sequential reservations claiming exactly one cycle (the
  memory-store form of `test_concurrent_reservations_claim_exactly_one_cycle`).
- **g3_collection**: `record_collection` dedup and relevance (M7 `test_relevance_is_deterministic_lexical_...`), the fixed
  selection reasons, the adoption reservation counted from the claim on, the adoptions cap reached, a cycle that selects
  nothing and never consumes its adoption (application line 678 in M7: `_scope_pool`), the counters that never reset.
- **g4_scope_and_bridges**: the investigations, audit_progress and attempt_scope bridges (`counts`, `new`, `ineligible`,
  `claimed`), a scope overlap refused, a member job held permanently against another claim, and the audit_progress and
  attempt_scope dispatch results that `research.program_tick` recorded as unreachable.
- **g5_capture_council**: `record_capture`, `record_council_start`, `record_council_result` with each verdict,
  `_record_dispatch_result` for an investigation candidate, `_owned` refusals.
- **g6_closing**: `complete_cycle`, `fail_cycle` with and without `recovery`, `_close`, `status`, `candidates`, `monitor`.

Layer: harness (never shipped)

Every double is `s8_research_program` (pilot 58, unchanged) or LABELLED here. No repository, provider, network or process is
touched: a `ResearchProgram` over a `MemoryStore` is driven directly. A synthetic row (a Fleet job, a binding, a held
research intent, an owner-action launch row, an audit-progress window) is LABELLED where it is written and carries only the
fields the rules read; the owner-action row is built by the owner's own row constructors. An injected fault is labelled at
its injection point. A case unreachable with the doubles is `{"unreachable": ...}`. For every refusal the digest of the whole
store before and after is recorded (nothing written)."""

from __future__ import annotations

from types import SimpleNamespace

import s8_research_program as R

HEAD = "a" * 40
REPO = "repo-1"
COUNTS = {"this_host": 0, "all_hosts": 0}
LATER = "2028-01-01T02:00:00+00:00"        # past the 3600 s interval of the default configuration
CAPTURE = {"revision": "c" * 40, "ref": R.CAPTURE_REF, "path": R.CAPTURE_PATH, "blob": "b" * 40, "sha256": "e" * 64}
MANIFEST_SHA, MANIFEST_REF = "d" * 64, "sha256:" + "e" * 64


# ---- builders ---------------------------------------------------------------------------------------------------------
def system(api, ws, store=None, clock=None, token=None):
    """A `ResearchProgram` over a `MemoryStore` (or the given store) with the labelled clock; `token` replaces the
    cycle owner token source (the owner launch id of an attempt-scope program, LABELLED)."""
    store = store or api.MemoryStore()
    clock = clock or R.Clock()
    options = {} if token is None else {"token": token}
    return SimpleNamespace(api=api, ws=ws, store=store, clock=clock,
                           programs=api.ResearchProgram(store, clock=clock, **options))


def cfg(api, program=R.PROGRAM, **overrides):
    return api.validate_config(R.config(HEAD, id=program, **overrides), api.POLICY)


def register(s, program=R.PROGRAM, resume=True, repository=REPO, **overrides):
    config = cfg(s.api, program, **overrides)
    s.programs.register(config, repository, [])
    if resume:
        s.programs.resume(program)
    return config


def reserve(s, program=R.PROGRAM):
    reserved = s.programs.reserve_cycle(program, REPO)
    if not reserved["reserved"]:
        raise AssertionError("fixture reservation refused: " + str(reserved))
    return reserved["cycle"]


def collect(s, cycle, items=(), counts=COUNTS, sources=None):
    return s.programs.record_collection(cycle["id"], cycle["owner"], sources or {}, [dict(i) for i in items], counts)


def github(name, title, summary):
    url = "https://github.com/acme/" + name
    return {"source": "github", "identity": url, "url": url, "title": title, "summary": summary,
            "content_sha256": R.sha256(name.encode())}


LOCAL = {"source": "local", "identity": "docs/research/note.md", "id": "local-note", "path": "docs/research/note.md",
         "sha256": R.sha256(R.NOTE), "topic": "storage", "title": "docs/research/note.md", "summary": "residual",
         "url": None, "content_sha256": R.sha256(R.NOTE)}
PGTOOL = github("pgtool", "acme/pgtool", "Postgres tooling")
UNRELATED = github("unrelated", "acme/unrelated", "a game engine")


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def drop(store, bucket, key):
    del store.data[(bucket, key)]   # LABELLED: the in-memory store has no delete; a vanished row is the fixture


def edit(store, bucket, key, **fields):
    """LABELLED row edit: a state no honest call path reaches (or that another actor wrote)."""
    row = get(store, bucket, key)
    row.update(fields)
    put(store, bucket, key, row)


# ---- observations -----------------------------------------------------------------------------------------------------
def counters(s, program=R.PROGRAM):
    row = get(s.store, s.api.BUCKET_PROGRAMS, program)
    if row is None:
        return None
    keys = ("state", "cycles", "adoptions", "next_cycle", "active_cycle", "last_tick_at", "stop_reason", "blocked_reason",
            "updated_at")
    return {k: row[k] for k in keys}


def cands(s, program=R.PROGRAM):
    keys = ("id", "source", "status", "topic", "reason", "result", "seen", "claimed_cycle", "first_cycle", "last_cycle")
    return [{k: row.get(k) for k in keys} for row in s.programs.candidates(program)]


def brief(cycle):
    keys = ("id", "number", "status", "counts", "selection", "remaining", "capture", "council", "result", "failure",
            "stop_reason", "investigations", "audit_progress", "attempt_scope", "attempt_scope_target", "finished_at")
    return {k: cycle.get(k) for k in keys if k in cycle}


def refused(s, fn, *args, **kwargs):
    """A call expected to refuse: the refusal and the digest of the whole store before and after."""
    before = R.store_digest(s.store)
    result = R.call(s.ws, fn, *args, **kwargs)
    after = R.store_digest(s.store)
    return {**result, "store_before": before, "store_after": after, "nothing_written": before == after}


def settle(s, cycle, result="accepted", reason="fixture", sha=MANIFEST_SHA, run_status="same", reported=None):
    """The council records of one selected cycle: capture, start, the run row, the result. `run_status` "same" writes a
    row with the result as its status; None writes no row (LABELLED: the council row is the stand-in's)."""
    number = cycle["number"]
    run = R.PROGRAM + ".c%03d" % number
    out = {"capture": brief(s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)),
           "start": brief(s.programs.record_council_start(cycle["id"], cycle["owner"], run, MANIFEST_SHA, MANIFEST_REF))}
    status = result if run_status == "same" else run_status
    if status is not None:
        put(s.store, s.api.RUNS, run, {"id": run, "status": status, "stage": "promotion", "manifest_sha256": sha,
                                       "reason_code": "fixture_" + str(status)})
    verdict = {"result": reported or result, "reason_code": reason, "row_status": status}
    out["result"] = brief(s.programs.record_council_result(cycle["id"], cycle["owner"], verdict))
    return out


def dispatch(s, key):
    row = get(s.store, s.api.BUCKET_DISPATCHES, key)
    keys = ("id", "kind", "program", "cycle", "state", "result", "result_reason", "row_status", "reported_result", "run_id",
            "manifest_sha256", "failure", "reason_code", "job_ids", "job_ids_total", "scope")
    return None if row is None else {k: row.get(k) for k in keys}


# ---- G1 --------------------------------------------------------------------------------------------------------------------
def finished(s, program, how):
    """A completed or a blocked program, through the real calls."""
    register(s, program, max_cycles=1)
    cycle = reserve(s, program)
    if how == "completed":
        collect(s, cycle)
        s.programs.complete_cycle(cycle["id"], cycle["owner"])
    else:   # a cycle that never collected fails at the `collecting` status
        s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "fixture_stop")


def g1_registration(api, ws):
    results = {}
    s = system(api, ws)
    config = cfg(api)
    results["register_first"] = {**R.guarded(ws, s, s.programs.register, config, REPO, []), "row": counters(s)}
    results["register_identical_again"] = R.guarded(ws, s, s.programs.register, config, REPO, [])
    results["register_other_repository"] = refused(s, s.programs.register, config, "repo-2", [])
    results["register_other_config"] = refused(s, s.programs.register, cfg(api, max_cycles=3), REPO, [])
    results["register_other_deadline_is_another_digest"] = refused(
        s, s.programs.register, cfg(api, deadline="2029-07-01T00:00:00+00:00"), REPO, [])
    results["register_unvalidated_config"] = refused(s, s.programs.register, {"id": "rp-raw"}, REPO, [])
    v = system(api, ws)
    verified = [{"id": "local-note", "path": "docs/research/note.md", "sha256": R.sha256(R.NOTE), "extra": "dropped"}]
    registered = v.programs.register(cfg(api), REPO, verified)
    results["register_verified_local_projection"] = {
        "registered": registered, "verified_local": get(v.store, api.BUCKET_PROGRAMS, R.PROGRAM)["verified_local"]}
    stored = s.programs.config(R.PROGRAM)
    results["config_returns_the_registered_document"] = {"equal": stored == config, "sha256": R.canonical_digest(stored),
                                                         "topics": stored["topics"], "max_adoptions": stored["max_adoptions"]}
    results["config_unknown_program"] = refused(s, s.programs.config, "nope")
    results["initial_state_is_paused"] = counters(s)
    # pause / resume transitions and refusals (counters untouched either way)
    results["pause_paused_is_a_no_op"] = R.guarded(ws, s, s.programs.pause, R.PROGRAM)
    results["resume_paused"] = R.guarded(ws, s, s.programs.resume, R.PROGRAM)
    results["resume_active_is_a_no_op"] = R.guarded(ws, s, s.programs.resume, R.PROGRAM)
    results["pause_active"] = R.guarded(ws, s, s.programs.pause, R.PROGRAM)
    results["pause_and_resume_leave_the_counters"] = counters(s)
    results["pause_unknown_program"] = refused(s, s.programs.pause, "nope")
    results["resume_unknown_program"] = refused(s, s.programs.resume, "nope")
    c = system(api, ws)
    finished(c, "rp-done", "completed")
    results["resume_completed_refused"] = refused(c, c.programs.resume, "rp-done")
    results["pause_completed_is_a_no_op"] = R.guarded(ws, c, c.programs.pause, "rp-done")
    finished(c, "rp-blocked", "blocked")
    results["resume_blocked_refused"] = refused(c, c.programs.resume, "rp-blocked")
    results["pause_blocked_is_a_no_op"] = R.guarded(ws, c, c.programs.pause, "rp-blocked")
    results["completed_and_blocked_rows"] = {"completed": counters(c, "rp-done"), "blocked": counters(c, "rp-blocked")}
    results["strict_config"] = strict_config(api, ws)
    results["m7_registration_sequence"] = m7_registration(api, ws)
    return results


def strict_config(api, ws):
    """M7 `test_config_is_strict_and_binds_template_base_and_budget`: each refusal by reason code, no canary in the text."""
    valid = api.validate_config(R.config(HEAD), api.POLICY)
    out = {"valid": {"base_revision": valid["template"]["base_revision"], "deadline": valid["deadline"],
                     "sha256": R.canonical_digest(valid),
                     "deterministic": api.validate_config(R.config(HEAD), api.POLICY) == valid}}
    base = R.config(HEAD)
    local = base["local_candidates"][0]
    cases = [("extra_field", {"extra": 1}), ("max_adoptions_3", {"max_adoptions": 3}), ("max_cycles_0", {"max_cycles": 0}),
             ("interval_true", {"interval_seconds": True}), ("deadline_naive", {"deadline": "2029-06-01T00:00:00"}),
             ("keyword_uppercase", {"topics": [{"id": "t", "keywords": ["Upper"]}]}), ("topics_empty", {"topics": []}),
             ("budget_mismatch", {"budget": {"per_host": 1, "total": 2}}),
             ("template_base_mismatch", {"template": R.template("b" * 40)}),
             ("template_schema", {"template": {**R.template(HEAD), "schema": "urn:zeus:autonomous:1"}}),
             ("template_extra", {"template": {**R.template(HEAD), "extra": 1}}),
             ("local_unknown_topic", {"local_candidates": [{"id": "x", "topic": "missing", "path": "docs/a.md",
                                                            "sha256": "0" * 64, "rationale": "r"}]}),
             ("local_duplicate", {"local_candidates": [dict(local, id="dup"), dict(local, id="dup2")]})]
    for label, override in cases:
        document = R.config(HEAD)
        document.update(override)
        out[label] = R.call(ws, api.validate_config, document, api.POLICY)
        out[label]["canary_in_message"] = R.CANARY in str(out[label].get("message"))
    out["config_schema"] = R.call(ws, api.validate_config, {"schema": "x"}, api.POLICY)
    return out


def m7_registration(api, ws):
    """M7 `test_registration_is_immutable_and_counters_and_schedule_are_durable`, step by step."""
    out = {}
    s = system(api, ws)
    config = cfg(api)
    out["first"] = s.programs.register(config, "repo-1", [])
    out["cached"] = s.programs.register(config, "repo-1", [])["cached"]
    out["conflict_repository"] = R.call(ws, s.programs.register, config, "repo-2", [])
    out["conflict_config"] = R.call(ws, s.programs.register, cfg(api, max_cycles=3), "repo-1", [])
    out["paused_reserve"] = s.programs.reserve_cycle(R.PROGRAM, "repo-1")
    out["resume"] = s.programs.resume(R.PROGRAM)
    out["mismatch"] = [R.call(ws, s.programs.reserve_cycle, R.PROGRAM, other) for other in ("repo-2", "", None)]
    out["mismatch_reserved_nothing"] = {"cycles": len(scan(s.store, api.BUCKET_CYCLES)),
                                        "next_cycle": get(s.store, api.BUCKET_PROGRAMS, R.PROGRAM)["next_cycle"]}
    reserved = s.programs.reserve_cycle(R.PROGRAM, "repo-1")
    out["reserved"] = brief(reserved["cycle"])
    out["busy"] = s.programs.reserve_cycle(R.PROGRAM, "repo-1")["reason"]
    out["pause_owned_active_cycle"] = s.programs.pause(R.PROGRAM)
    owner = reserved["cycle"]["owner"]
    out["owner_mismatch"] = R.call(ws, s.programs.complete_cycle, "rp-001:001", "someone-else")
    recorded = s.programs.record_collection("rp-001:001", owner, {"local": {"status": "ok", "code": None}}, [], COUNTS)
    out["empty_collection"] = {"candidate": recorded["candidate"], "reason": recorded["cycle"]["selection"]["reason"]}
    s.programs.complete_cycle("rp-001:001", owner)
    out["view_after_first"] = {k: s.programs.status(R.PROGRAM)[k] for k in ("cycles", "state")}
    s.programs.resume(R.PROGRAM)
    out["not_due"] = s.programs.reserve_cycle(R.PROGRAM, "repo-1")["reason"]
    s.clock.value = "2028-01-01T01:00:00+00:00"
    second = s.programs.reserve_cycle(R.PROGRAM, "repo-1")
    out["second"] = {"reserved": second["reserved"], "number": second["cycle"]["number"]}
    s.programs.record_collection("rp-001:002", second["cycle"]["owner"], {}, [], COUNTS)
    s.programs.complete_cycle("rp-001:002", second["cycle"]["owner"])
    status = s.programs.status(R.PROGRAM)
    out["completed"] = {"state": status["state"], "stop_reason": status["stop_reason"]}
    out["reserve_completed"] = s.programs.reserve_cycle(R.PROGRAM, "repo-1")["reason"]
    out["resume_completed"] = R.call(ws, s.programs.resume, R.PROGRAM)
    late = system(api, ws, store=s.store, clock=R.Clock("2031-01-01T00:00:00+00:00"))
    register(late, "rp-late")
    out["deadline"] = {"reason": late.programs.reserve_cycle("rp-late", "repo-1")["reason"],
                       "state": late.programs.status("rp-late")["state"]}
    out["status_unknown_program"] = R.call(ws, s.programs.status, "nope")
    return out


# ---- G2 --------------------------------------------------------------------------------------------------------------------
def g2_reservation(api, ws):
    results = {}
    s = system(api, ws)
    register(s, max_cycles=3, max_adoptions=2)
    results["reserved"] = R.guarded(ws, s, s.programs.reserve_cycle, R.PROGRAM, REPO)
    results["reserved_row"] = counters(s)
    results["busy_never_takes_over"] = R.guarded(ws, s, s.programs.reserve_cycle, R.PROGRAM, REPO)
    for label, other in (("other", "repo-2"), ("empty", ""), ("none", None)):
        results["repository_mismatch_" + label] = refused(s, s.programs.reserve_cycle, R.PROGRAM, other)
    results["unknown_program"] = refused(s, s.programs.reserve_cycle, "nope", REPO)
    p = system(api, ws)
    register(p, resume=False)
    results["paused"] = R.guarded(ws, p, p.programs.reserve_cycle, R.PROGRAM, REPO)
    results["paused_mismatch_comes_first"] = refused(p, p.programs.reserve_cycle, R.PROGRAM, "repo-2")
    d = system(api, ws, clock=R.Clock("2031-01-01T00:00:00+00:00"))
    register(d)
    results["deadline_expired"] = {**R.guarded(ws, d, d.programs.reserve_cycle, R.PROGRAM, REPO), "row": counters(d)}
    results["deadline_expired_then_completed"] = R.guarded(ws, d, d.programs.reserve_cycle, R.PROGRAM, REPO)
    n = system(api, ws)
    register(n)
    cycle = reserve(n)
    collect(n, cycle)
    n.programs.complete_cycle(cycle["id"], cycle["owner"])
    results["not_due"] = R.guarded(ws, n, n.programs.reserve_cycle, R.PROGRAM, REPO)
    n.clock.value = "2028-01-01T00:59:59+00:00"
    results["not_due_one_second_early"] = R.guarded(ws, n, n.programs.reserve_cycle, R.PROGRAM, REPO)
    n.clock.value = "2028-01-01T01:00:00+00:00"
    results["due_on_the_boundary"] = R.guarded(ws, n, n.programs.reserve_cycle, R.PROGRAM, REPO)
    c = system(api, ws)
    finished(c, "rp-done", "completed")
    results["program_completed"] = R.guarded(ws, c, c.programs.reserve_cycle, "rp-done", REPO)
    finished(c, "rp-blocked", "blocked")
    results["program_blocked"] = R.guarded(ws, c, c.programs.reserve_cycle, "rp-blocked", REPO)
    m = system(api, ws)
    register(m, max_cycles=2)
    edit(m.store, api.BUCKET_PROGRAMS, R.PROGRAM, cycles=2)   # LABELLED row edit: `_close` completes a program first
    results["max_cycles_reached_labelled_row_edit"] = {**R.guarded(ws, m, m.programs.reserve_cycle, R.PROGRAM, REPO),
                                                       "row": counters(m)}
    results["max_cycles_note"] = ("every honest path reaches the cap through `_close`, which completes the program, so the "
                                  "reservation's own check is reachable only through a stored row with cycles at the cap")
    q = system(api, ws)
    register(q)
    first = R.call(ws, q.programs.reserve_cycle, R.PROGRAM, REPO)
    second = R.call(ws, q.programs.reserve_cycle, R.PROGRAM, REPO)
    results["two_sequential_reservations_claim_exactly_one_cycle"] = {
        "reserved": [first["value"]["reserved"], second["value"]["reserved"]], "second_reason": second["value"]["reason"],
        "cycles": len(scan(q.store, api.BUCKET_CYCLES)), "row": counters(q)}
    results["remaining_counts_across_cycles"] = remaining_counts(api, ws)
    results["adoptions_remaining_zero_after_one_dispatched_attempt"] = cap_example(api, ws)["reservation"]
    return results


def remaining_counts(api, ws):
    s = system(api, ws)
    register(s, max_cycles=3, max_adoptions=2)
    out = []
    for round_ in range(3):
        cycle = reserve(s)
        items = (LOCAL,) if round_ == 0 else (PGTOOL,) if round_ == 1 else ()
        recorded = collect(s, cycle, items)
        entry = {"number": cycle["number"], "reserved_remaining": cycle["remaining"],
                 "collected_remaining": recorded["cycle"]["remaining"], "selected": recorded["cycle"]["selection"]}
        if recorded["candidate"] is None:
            closed = s.programs.complete_cycle(cycle["id"], cycle["owner"])
        else:
            settle(s, cycle, "rejected")
            closed = get(s.store, api.BUCKET_CYCLES, cycle["id"])
        entry["closed_remaining"], entry["row"] = closed["remaining"], counters(s)
        out.append(entry)
        s.clock.advance(3600)
    return out


def cap_example(api, ws):
    """Examples 1 of the spec: adoptions cap 1, after one dispatched attempt `reserve_cycle` reports adoptions remaining 0
    and the next selection reason is the cap."""
    s = system(api, ws)
    register(s, max_cycles=3, max_adoptions=1)
    first = reserve(s)
    chosen = collect(s, first, (LOCAL, PGTOOL))
    settled = settle(s, first, "accepted")
    s.clock.advance(3600)
    second = s.programs.reserve_cycle(R.PROGRAM, REPO)
    later = collect(s, second["cycle"], (PGTOOL,))
    return {"first_selection": chosen["cycle"]["selection"], "first_settled": settled["result"]["status"],
            "reservation": {"reserved": second["reserved"], "remaining": second["cycle"]["remaining"],
                            "row": counters(s)},
            "next_selection": later["cycle"]["selection"], "candidate": later["candidate"],
            "candidates": cands(s), "adoptions_after": counters(s)["adoptions"]}


# ---- G3 --------------------------------------------------------------------------------------------------------------------
def g3_collection(api, ws):
    results = {}
    topics = [{"id": "storage", "keywords": ["advisory lock", "postgres"]}, {"id": "ui", "keywords": ["frontend"]}]
    s = system(api, ws)
    register(s, topics=topics, local_candidates=[], max_adoptions=1)
    cycle = reserve(s)
    items = [github("lock", "Advisory Lock patterns", ""), github("ui", "x", "a frontend thing"),
             github("game", "game engine", "graphics"), github("long", None, "postgres " * 2000),
             github("both", "frontend and postgres", "")]
    recorded = collect(s, cycle, items)
    results["relevance_lexical"] = {"tally": recorded["cycle"]["counts"], "selection": recorded["cycle"]["selection"],
                                    "candidates": cands(s), "budget": recorded["cycle"]["budget"]}
    # dedup across cycles: the same identity again is a duplicate, seen counted, never a second row
    s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "fixture_stop")
    d = system(api, ws)
    register(d, max_cycles=3, max_adoptions=2)
    first = reserve(d)
    one = collect(d, first, (UNRELATED, github("lock", "Advisory Lock", "")))
    d.programs.complete_cycle(first["id"], first["owner"]) if one["candidate"] is None else settle(d, first, "rejected")
    d.clock.advance(3600)
    second = reserve(d)
    two = collect(d, second, (UNRELATED, github("lock", "Advisory Lock", ""), PGTOOL))
    results["dedup_across_cycles"] = {"first": one["cycle"]["counts"], "second": two["cycle"]["counts"],
                                      "second_selection": two["cycle"]["selection"], "candidates": cands(d)}
    results["dedup_within_one_collection"] = dedup_within(api, ws)
    results["selection_reasons"] = selection_reasons(api, ws)
    results["adoption_reservation_counted_from_the_claim"] = adoption_claim(api, ws)
    results["adoptions_cap_reached"] = cap_example(api, ws)
    results["nothing_selected_never_consumes_the_adoption"] = nothing_selected(api, ws)
    results["counters_never_reset"] = never_reset(api, ws)
    results["investigation_source_forbidden"] = forbidden_source(api, ws)
    results["collection_ownership_refusals"] = collection_refusals(api, ws)
    results["local_candidate_is_owner_authorized"] = local_candidate(api, ws)
    return results


def dedup_within(api, ws):
    s = system(api, ws)
    register(s)
    cycle = reserve(s)
    recorded = collect(s, cycle, (PGTOOL, PGTOOL, UNRELATED, UNRELATED))
    return {"tally": recorded["cycle"]["counts"], "candidates": cands(s)}


def selection_reasons(api, ws):
    out = {}
    tight = {"this_host": 4, "all_hosts": 4}
    plans = [("no_eligible_candidate_empty", (), COUNTS), ("first_eligible_authorized_local_first", (PGTOOL, LOCAL), COUNTS),
             ("first_eligible_external_only", (PGTOOL,), COUNTS),
             ("machine_headroom_insufficient_tight", (PGTOOL,), tight),
             ("machine_headroom_insufficient_unreadable", (PGTOOL,), {"unreadable": "OSError"}),
             ("machine_headroom_insufficient_missing_counts", (PGTOOL,), {}),
             ("headroom_exactly_enough", (PGTOOL,), {"this_host": 3, "all_hosts": 3}),
             ("no_eligible_candidate_only_ignored", (UNRELATED,), COUNTS)]
    for label, items, counts in plans:
        s = system(api, ws)
        register(s)
        cycle = reserve(s)
        recorded = collect(s, cycle, items, counts)
        out[label] = {"selection": recorded["cycle"]["selection"], "budget": recorded["cycle"]["budget"],
                      "candidate": None if recorded["candidate"] is None else recorded["candidate"]["id"],
                      "tally": recorded["cycle"]["counts"], "row": counters(s), "candidates": cands(s)}
    return out


def adoption_claim(api, ws):
    s = system(api, ws)
    register(s, max_cycles=3, max_adoptions=2)
    cycle = reserve(s)
    before = counters(s)
    recorded = collect(s, cycle, (LOCAL, PGTOOL))
    claimed = {"before": before, "after_claim": counters(s), "selected": recorded["cycle"]["selection"],
               "candidate": recorded["candidate"], "remaining": recorded["cycle"]["remaining"],
               "tally": recorded["cycle"]["counts"], "candidates": cands(s),
               "view_adoptions": s.programs.status(R.PROGRAM)["adoptions"]}
    # the adoption counts from the claim on, whatever the council then does
    failed = s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "fixture_stop")
    claimed["after_failed_cycle"] = {"row": counters(s), "remaining": failed["remaining"], "candidates": cands(s)}
    return claimed


def nothing_selected(api, ws):
    s = system(api, ws)
    register(s, max_cycles=3, max_adoptions=1)
    cycle = reserve(s)
    before = counters(s)
    recorded = collect(s, cycle, (UNRELATED,))
    out = {"before": before, "selected": recorded["cycle"]["selection"], "candidate": recorded["candidate"],
           "after": counters(s), "remaining": recorded["cycle"]["remaining"], "tally": recorded["cycle"]["counts"],
           "candidates": cands(s)}
    closed = s.programs.complete_cycle(cycle["id"], cycle["owner"])
    out["closed"] = {"remaining": closed["remaining"], "result": closed["result"], "row": counters(s)}
    s.clock.advance(3600)
    again = reserve(s)
    later = collect(s, again, (PGTOOL,))
    out["the_unconsumed_adoption_is_used_next_cycle"] = {"selection": later["cycle"]["selection"], "row": counters(s)}
    return out


def never_reset(api, ws):
    s = system(api, ws)
    register(s, max_cycles=4, max_adoptions=2)
    trail = []

    def mark(label):
        trail.append({"step": label, "row": counters(s)})
    for number, items in enumerate(((LOCAL,), (UNRELATED,), (PGTOOL,), ()), 1):
        cycle = reserve(s)
        recorded = collect(s, cycle, items)
        mark("collected_%d_%s" % (number, recorded["cycle"]["selection"]["reason"]))
        if recorded["candidate"] is None:
            s.programs.complete_cycle(cycle["id"], cycle["owner"])
        else:
            settle(s, cycle, "rejected" if number == 1 else "accepted")
        mark("closed_%d" % number)
        if number == 2:
            s.programs.pause(R.PROGRAM)
            s.programs.resume(R.PROGRAM)
            mark("paused_and_resumed")
        s.clock.advance(3600)
    return {"trail": trail, "status": {k: s.programs.status(R.PROGRAM)[k] for k in ("cycles", "adoptions", "state",
                                                                                      "stop_reason")}}


def forbidden_source(api, ws):
    s = system(api, ws)
    register(s)
    cycle = reserve(s)
    forged = {"source": "investigation", "identity": "f" * 64, "id": "forged", "url": None, "title": "forged",
              "summary": "forged"}
    return {"forged_only": refused(s, s.programs.record_collection, cycle["id"], cycle["owner"], {}, [forged], {}),
            "forged_among_valid_items": refused(s, s.programs.record_collection, cycle["id"], cycle["owner"], {},
                                                [dict(PGTOOL), forged], COUNTS),
            "refused_even_with_a_foreign_owner": refused(s, s.programs.record_collection, cycle["id"], "someone-else",
                                                         {}, [forged], {}),
            "cycle_still_collecting": get(s.store, api.BUCKET_CYCLES, cycle["id"])["status"]}


def collection_refusals(api, ws):
    s = system(api, ws)
    register(s)
    cycle = reserve(s)
    out = {"unknown_cycle": refused(s, s.programs.record_collection, "rp-001:009", cycle["owner"], {}, [], COUNTS),
           "owner_mismatch": refused(s, s.programs.record_collection, cycle["id"], "someone-else", {}, [], COUNTS),
           "owner_empty": refused(s, s.programs.record_collection, cycle["id"], "", {}, [], COUNTS),
           "owner_none": refused(s, s.programs.record_collection, cycle["id"], None, {}, [], COUNTS)}
    collect(s, cycle)
    out["second_collection_cycle_state_changed"] = refused(s, s.programs.record_collection, cycle["id"], cycle["owner"],
                                                           {}, [], COUNTS)
    t = system(api, ws)
    register(t)
    other = reserve(t)
    edit(t.store, api.BUCKET_PROGRAMS, R.PROGRAM, active_cycle=None)   # LABELLED row edit: the program no longer owns it
    out["cycle_not_active_labelled_row_edit"] = refused(t, t.programs.record_collection, other["id"], other["owner"], {},
                                                        [], COUNTS)
    return out


def local_candidate(api, ws):
    s = system(api, ws)
    register(s)
    cycle = reserve(s)
    recorded = collect(s, cycle, (LOCAL,))
    return {"candidate": recorded["candidate"], "tally": recorded["cycle"]["counts"], "reason": recorded["cycle"]["selection"]}


# ---- scope fixtures (M7 `tests/test_research_attempt_scope_program.py`; LABELLED synthetic rows) ----------------------------
POLICY_ID, POLICY_SHA = "policy-1", "5" * 64
STATUS, REASON = "failed", "store_timeout"
J_F0, S1 = "aibox-qual-b2-fault", "aibox-qual-b2-fault-s1"
HISTORICAL = ["hist-%02d" % i for i in range(1, 22)]
SCOPED, Q1 = HISTORICAL[:11], HISTORICAL[10]
SCOPE_SOURCE = {"topic": "storage", "continuation_policy": POLICY_ID, "continuation_policy_sha256": POLICY_SHA,
                "families": [J_F0], "project_ids": ["ops"], "reason_codes": [REASON]}
FAMILY_SOURCE = {"topic": "storage", "project_ids": ["ops"], "reason_codes": [REASON, "review_rejected"]}
T0, T_F0, T_R = "2027-12-31T00:00:00+00:00", "2028-01-01T00:00:00+00:00", "2028-01-01T00:10:00+00:00"
LEADS = [dict(LOCAL), dict(PGTOOL)]


def ids(api):
    i_f0, i_r = api.digest(["fixture-intent", "f0"]), api.digest(["fixture-intent", "r"])
    attempts = [{"job": J_F0, "evidence_sha256": "a" * 64}, {"job": S1, "evidence_sha256": "b" * 64}]
    return SimpleNamespace(cause=api.family_id(STATUS, REASON), i_f0=i_f0, i_r=i_r, scope=api.attempt_scope_id(i_r),
                           attempts=attempts)


def hexid(api, label):
    return api.digest(["fixture-intent", label])


def intent(identity, route, state, origin, evidence, created_at, family=J_F0):
    return {"id": identity, "route": route, "state": state, "policy_id": POLICY_ID, "policy_sha256": POLICY_SHA,
            "family": family, "origin_job": origin, "evidence_sha256": evidence, "created_at": created_at,
            "lane": "lane-1"}


def job(tx, job_id, project, status=STATUS, reason=REASON):
    tx.put("fleet_jobs", job_id, {"id": job_id, "status": status, "reason_code": reason})
    tx.put("portfolio_bindings", job_id, {"job_id": job_id, "project_id": project})


def family_dispatch(api, key, job_ids, program, state="resolved", result="failed", total=None, cause=(STATUS, REASON)):
    job_ids = sorted(job_ids)
    return {"schema": "urn:zeus:research-investigation-dispatch:1", "id": key, "investigation": api.family_id(*cause),
            "kind": "failure_family", "scope": None, "program": program, "cycle": program + ":001", "cycle_number": 1,
            "candidate": "inv-fixture", "state": state, "snapshot_sha256": "c" * 64, "family_status": cause[0],
            "reason_code": cause[1], "job_ids": job_ids, "job_ids_total": len(job_ids) if total is None else total,
            "job_ids_sha256": api.digest(job_ids), "run_id": program + ".c001", "manifest_sha256": "d" * 64,
            "result": result, "claimed_at": T0, "updated_at": T0}


def held_world(api, store, *, lineage=True, members=None):
    """The held lineage (prior failure F0 on J_F0, held research intent R on S1), their Fleet rows and bindings, the
    undecided cause row with 21 historical members (11 scoped) and, with `lineage`, the P1 history: four resolved family
    dispatches, a claimed recovery, two claimed successors, their head and 15 terminal programs."""
    x = ids(api)
    with store.transaction() as tx:
        tx.put("continuation_policies", POLICY_ID, {"id": POLICY_ID, "policy_sha256": POLICY_SHA})
        tx.put("continuation_intents", x.i_f0, intent(x.i_f0, "correction", "admitted", J_F0, "a" * 64, T_F0))
        tx.put("continuation_intents", x.i_r, intent(x.i_r, "research", "research_required", S1, "b" * 64, T_R))
        for held in (J_F0, S1):
            job(tx, held, "ops")
        for index, member in enumerate(HISTORICAL):
            job(tx, member, "ops" if index < 11 else "other")
        listed = list(HISTORICAL if members is None else members)
        tx.put("portfolio_investigations", x.cause, {
            "id": x.cause, "kind": "failure_family", "state": "research_required", "family_status": STATUS,
            "reason_code": REASON, "job_ids": listed, "count": len(listed)})
        if not lineage:
            return
        keys = [x.cause, x.cause + ".recovery-1", x.cause + ".recovery-2", x.cause + ".recovery-3"]
        for number, key in enumerate(keys):
            tx.put(api.BUCKET_DISPATCHES, key, family_dispatch(api, key, SCOPED[:4 + 2 * number],
                                                               "rp-hist-%02d" % (number + 1)))
        tx.put(api.BUCKET_RECOVERIES, x.cause, {
            "id": x.cause, "investigation": x.cause, "state": "claimed", "request_sha256": "6" * 64,
            "failed": {"program": "rp-hist-01", "cycle": "rp-hist-01:001"},
            "replacement": {"program": "rp-hist-02", "dispatch": keys[1], "cycle": "rp-hist-02:001"}})
        for version in (2, 3):
            tx.put(api.BUCKET_SUCCESSORS, x.cause + ":" + str(version), {
                "id": x.cause + ":" + str(version), "investigation": x.cause, "version": version, "state": "claimed",
                "predecessor": {"program": "rp-hist-%02d" % version}, "replacement": {
                    "program": "rp-hist-%02d" % (version + 1), "dispatch": keys[version]}})
        tx.put(api.BUCKET_HEADS, x.cause, {"id": x.cause, "investigation": x.cause, "version": 3,
                                           "successor": x.cause + ":3", "dispatch": keys[3]})
        for number in range(1, 16):
            tx.put(api.BUCKET_PROGRAMS, "rp-hist-%02d" % number, {
                "id": "rp-hist-%02d" % number, "state": "completed" if number % 2 else "blocked",
                "config": {"investigation_source": dict(FAMILY_SOURCE)}})


def launch(api, store, program=R.PROGRAM, cycle=1, intent_id=None, jobs=(J_F0, S1), state=None, investigation=None,
           family=J_F0) -> str:
    """The owner-actions `research_dispatch` row whose launch id the child reserves under (LABELLED: written through the
    owner's own row constructors, never through its coordinator)."""
    do = api.owner_actions
    intent_id = intent_id or ids(api).i_r
    state = do.RUNNING if state is None else state
    binding = do.research_dispatch_binding({"id": intent_id, "policy_id": POLICY_ID, "family": family},
                                           {"program_id": program}, investigation or api.attempt_scope_id(intent_id),
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
    return row.get("launch_id") or api.digest(["no-launch", row["id"]])


def scoped(api, ws, store, program=R.PROGRAM, token="0" * 32, source=None, clock=None, **overrides):
    s = system(api, ws, store=store, clock=clock, token=lambda: token)
    register(s, program, attempt_scope_source=dict(source or SCOPE_SOURCE), **overrides)
    return s


def family(api, ws, store, program="rp-fam", clock=None):
    s = system(api, ws, store=store, clock=clock)
    register(s, program, investigation_source=dict(FAMILY_SOURCE))
    return s


def collect_for(s, program=R.PROGRAM, items=(), counts=COUNTS):
    cycle = reserve(s, program)
    return collect(s, cycle, items, counts)


def claim_scope(api, ws, store, **kwargs):
    s = scoped(api, ws, store, token=launch(api, store), **kwargs)
    recorded = collect_for(s)
    return s, recorded


def swap(s, program, token):
    """The next cycle of a scoped program: a later launch row and its token (LABELLED)."""
    s.clock.value = LATER
    s.programs.token = lambda: token


def observe_collection(s, recorded):
    cycle = recorded["cycle"]
    return {"counts": (cycle.get("attempt_scope") or {}).get("counts"), "selection": cycle["selection"],
            "status": cycle["status"], "candidate": None if recorded["candidate"] is None else recorded["candidate"]["id"],
            "scope_receipt": {k: v for k, v in (cycle.get("attempt_scope") or {}).items() if k != "counts"}}


# ---- G4 --------------------------------------------------------------------------------------------------------------------
AUDIT = "audit-fixture-001"
PROGRESS_SOURCE = {"topic": "storage", "audit_ids": [AUDIT]}


def history(api, store):
    """Every pre-existing row a scoped tick must leave byte for byte: all but the program's own lifecycle rows, the
    council's run row and the new scope dispatch (M7 `history`)."""
    own = {api.BUCKET_PROGRAMS, api.BUCKET_CANDIDATES, api.BUCKET_CYCLES, api.RUNS}
    scope = api.BUCKET_DISPATCHES, ids(api).scope
    with store.transaction() as tx:
        rows = [[r["bucket"], r["id"], R.canonical_digest(r["body"])] for r in tx.records()
                if r["bucket"] not in own and (r["bucket"], r["id"]) != scope]
    return R.canonical_digest(rows)


def g4_scope_and_bridges(api, ws):
    results = {}
    results["investigations_bridge"] = investigations_bridge(api, ws)
    results["audit_progress_bridge"] = audit_bridge(api, ws)
    results["attempt_scope_bridge"] = scope_bridge(api, ws)
    results["scope_exclusions_select_nothing"] = {name: scope_exclusion(api, ws, make)
                                                  for name, make in sorted(exclusions(api).items())}
    results["owner_target_refusals"] = {name: target_refusal(api, ws, make, field)
                                        for name, (make, field) in sorted(target_cases(api).items())}
    results["target_is_immutable_through_collection"] = widened_scope(api, ws)
    results["another_held_scope_never_replaces_the_target"] = another_scope(api, ws)
    results["rival_programs"] = {state: rival(api, ws, state) for state in
                                ("paused", "active", "stopped", "mystery", "completed", "blocked")}
    results["scoped_rival_sharing_policy_and_a_root"] = scoped_rival(api, ws)
    results["second_program_and_repeated_tick_consume_nothing"] = second_program(api, ws)
    results["stale_cached_scope_snapshot_is_dropped"] = stale_snapshot(api, ws)
    results["claim_row_defence_rolls_back_whole"] = claim_defence(api, ws)
    results["fault_before_commit_rolls_back"] = fault_before_commit(api, ws)
    results["forward_overlap"] = {name: forward(api, ws, name) for name in sorted(forward_cases(api))}
    results["reverse_overlap_permanent_in_every_state"] = {
        "%s_%s" % (state, result): reverse(api, ws, state, result)
        for state, result in (("claimed", None), ("dispatched", None), ("resolved", "accepted"), ("resolved", "rejected"),
                              ("resolved", "failed"), ("resolved", "unknown"))}
    results["disjoint_family_and_truncated_same_cause"] = disjoint_and_truncated(api, ws)
    results["held_jobs_in_the_portfolio_alone_do_not_refuse"] = portfolio_membership(api, ws)
    results["legacy_cycle_has_no_scope_key"] = legacy_cycle(api, ws)
    results["recovery_successor_followup_scope_refusals"] = {
        "unreachable": "recover_dispatch, the successor and the follow-up requests (and `_refuse_scope_overlap`, which only "
                       "they reach) are the dispatch recovery family (pilot 60), not this family"}
    return results


# ---- the investigations bridge -----------------------------------------------------------------------------------------
def investigations_bridge(api, ws):
    out = {}
    key = api.family_id(*R.FAMILY)
    store = api.MemoryStore()
    R.portfolio(api, store)
    s = system(api, ws, store=store)
    register(s, max_cycles=3, max_adoptions=2, investigation_source=dict(R.SOURCE))
    cycle = reserve(s)
    recorded = collect(s, cycle, (PGTOOL,))
    out["claim"] = {"bridge": recorded["cycle"]["investigations"], "selection": recorded["cycle"]["selection"],
                    "candidate": recorded["candidate"], "dispatch": dispatch(s, key), "row": counters(s),
                    "tally": recorded["cycle"]["counts"]}
    out["accepted"] = settle(s, cycle, "accepted")["result"]
    out["accepted_dispatch"] = dispatch(s, key)
    out["accepted_status"] = {k: s.programs.status(R.PROGRAM)[k] for k in ("investigations", "adoptions", "candidates")}
    # a second program sees the claim and consumes nothing
    o = system(api, ws, store=store)
    register(o, "rp-002", max_cycles=3, max_adoptions=2, investigation_source=dict(R.SOURCE))
    other = collect_for(o, "rp-002", (PGTOOL,))
    out["second_program"] = {"bridge": other["cycle"]["investigations"], "selection": other["cycle"]["selection"],
                             "row": counters(o, "rp-002")}
    # opt-out: no portfolio bucket is read, the receipt is None
    q = api.MemoryStore()
    R.portfolio(api, q)
    p = system(api, ws, store=q)
    register(p)
    none = collect_for(p, items=(PGTOOL,))
    out["opt_out_reads_nothing"] = {"bridge": none["cycle"]["investigations"], "selection": none["cycle"]["selection"]}
    # a cached eligible candidate that stops being eligible is ignored, never run later
    t = api.MemoryStore()
    R.portfolio(api, t)
    c = system(api, ws, store=t)
    register(c, max_cycles=3, max_adoptions=2, investigation_source=dict(R.SOURCE))
    first = reserve(c)
    waiting = collect(c, first, (), {"this_host": 4, "all_hosts": 4})
    out["cached_while_headroom_is_short"] = {"selection": waiting["cycle"]["selection"], "bridge": waiting["cycle"]["investigations"],
                                             "candidates": cands(c), "row": counters(c)}
    c.programs.complete_cycle(first["id"], first["owner"])
    edit(t, api.BUCKET_INVESTIGATIONS, key, state="researched")   # LABELLED: the owner decided the investigation meanwhile
    c.clock.advance(3600)
    second = collect_for(c)
    stale = c.programs.candidate(R.PROGRAM, cands(c)[0]["id"]) if cands(c) else None
    out["ineligible_after_the_owner_decided"] = {"bridge": second["cycle"]["investigations"],
                                                 "selection": second["cycle"]["selection"], "candidate": stale,
                                                 "row": counters(c), "dispatches": scan(t, api.BUCKET_DISPATCHES)}
    return out


# ---- the audit_progress bridge -----------------------------------------------------------------------------------------
def progress_world(api, s, label="epoch-1", audit=AUDIT):
    """LABELLED synthetic audit-progress rows in the shape `AuditProgress` writes (the observer itself, the audit inventory,
    the tasks and the receipts are the audit.* families): one candidate of the epoch, its two comparable low-yield windows and
    the audit's current epoch row, under the policy digest this program has in force."""
    epoch = {"id": api.digest(["fixture-epoch", label]), "audit_id": audit}
    windows = [{"id": api.digest(["fixture-window", label, index]), "index": index, "epoch": epoch["id"],
                "comparable": True, "verdict": api.LOW_YIELD, "executions": 2,
                "members_sha256": api.digest(["fixture-members", label, index]), "members": ["task-001", "task-002"],
                "delta": {"semantic_paths": 0}, "closing": {"semantic_paths": 0}, "closed_at": R.BASE_CLOCK}
               for index in (0, 1)]
    candidate = api.progress_candidate_row(epoch=epoch, policy_sha256=s.programs.progress_policy_sha256,
                                           reason_code=api.LOW_YIELD, windows=windows, metrics={"distinct_ranges": 1},
                                           required_state=api.RESEARCH_REQUIRED, now=R.BASE_CLOCK)
    with s.store.transaction() as tx:
        for window in windows:
            tx.put(api.BUCKET_PROGRESS_WINDOWS, window["id"], window)
        tx.put(api.BUCKET_PROGRESS_STATE, audit, {"audit_id": audit, "epoch": epoch})
        tx.put(api.BUCKET_INVESTIGATIONS, candidate["id"], candidate)
    return SimpleNamespace(candidate=candidate, windows=windows, epoch=epoch)


def progress_program(api, ws, program=R.PROGRAM, store=None, source=None, label="epoch-1", **overrides):
    s = system(api, ws, store=store)
    register(s, program, audit_progress_source=dict(source or PROGRESS_SOURCE), **overrides)
    return s, progress_world(api, s, label)


def audit_bridge(api, ws):
    out = {}
    for how in ("accepted", "rejected", "failed_cycle"):
        s, world = progress_program(api, ws, max_cycles=3, max_adoptions=2)
        cycle = reserve(s)
        recorded = collect(s, cycle, LEADS)
        key = world.candidate["id"]
        entry = {"bridge": recorded["cycle"]["audit_progress"], "selection": recorded["cycle"]["selection"],
                 "candidate": recorded["candidate"], "dispatch": dispatch(s, key), "row": counters(s),
                 "tally": recorded["cycle"]["counts"], "candidate_row_untouched": get(
                     s.store, api.BUCKET_INVESTIGATIONS, key) == world.candidate}
        if how == "failed_cycle":
            entry["failed"] = brief(s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "fixture_stop"))
        else:
            entry["settled"] = settle(s, cycle, how)["result"]
        entry["dispatch_after"] = dispatch(s, key)
        entry["status"] = {k: s.programs.status(R.PROGRAM)[k] for k in ("audit_progress", "investigations", "adoptions",
                                                                         "state", "blocked_reason")}
        entry["candidate_row_untouched_after"] = get(s.store, api.BUCKET_INVESTIGATIONS, key) == world.candidate
        out[how] = entry
    out["forged_discovery_item_refused"] = forbidden_progress(api, ws)
    # exclusions by name: scope, state, policy, epoch, window, claimed
    for name in ("scope", "state", "policy", "epoch", "window", "claimed", "malformed"):
        s, world = progress_program(api, ws, source=PROGRESS_SOURCE if name != "scope" else {
            "topic": "storage", "audit_ids": ["another-audit"]})
        key = world.candidate["id"]
        if name == "state":
            edit(s.store, api.BUCKET_INVESTIGATIONS, key, state="researched")
        elif name == "policy":
            edit(s.store, api.BUCKET_INVESTIGATIONS, key, policy_sha256="0" * 64)
        elif name == "epoch":
            edit(s.store, api.BUCKET_PROGRESS_STATE, AUDIT, epoch={"id": "e" * 64})
        elif name == "window":
            edit(s.store, api.BUCKET_INVESTIGATIONS, key, window_sha256=["0" * 64, "0" * 64])
        elif name == "claimed":
            put(s.store, api.BUCKET_DISPATCHES, key, {"id": key, "investigation": key, "program": "other",
                                                      "state": "claimed", "kind": "audit_progress"})
        elif name == "malformed":
            edit(s.store, api.BUCKET_INVESTIGATIONS, key, windows=[])
        recorded = collect_for(s, items=(LOCAL,))
        out["excluded_" + name] = {"bridge": recorded["cycle"]["audit_progress"], "selection": recorded["cycle"]["selection"],
                                   "candidate": None if recorded["candidate"] is None else recorded["candidate"]["id"],
                                   "row": counters(s)}
    # a cached eligible candidate whose epoch moved on is ignored with its snapshot dropped
    s, world = progress_program(api, ws, max_cycles=3, max_adoptions=2)
    first = reserve(s)
    waiting = collect(s, first, (), {"this_host": 4, "all_hosts": 4})
    cached = cands(s)
    s.programs.complete_cycle(first["id"], first["owner"])
    edit(s.store, api.BUCKET_PROGRESS_STATE, AUDIT, epoch={"id": "e" * 64})
    s.clock.advance(3600)
    second = collect_for(s)
    out["cached_candidate_dropped_when_the_epoch_moves"] = {
        "waiting": {"selection": waiting["cycle"]["selection"], "bridge": waiting["cycle"]["audit_progress"],
                    "candidates": cached},
        "second": {"bridge": second["cycle"]["audit_progress"], "selection": second["cycle"]["selection"]},
        "candidate": s.programs.candidate(R.PROGRAM, "ap-" + world.candidate["id"][:24])}
    return out


def forbidden_progress(api, ws):
    s, world = progress_program(api, ws)
    cycle = reserve(s)
    forged = {"source": "investigation", "identity": world.candidate["id"], "id": "forged", "url": None,
              "title": "forged", "summary": "forged"}
    return refused(s, s.programs.record_collection, cycle["id"], cycle["owner"], {}, [forged], {})


# ---- the attempt-scope bridge ------------------------------------------------------------------------------------------
def scope_bridge(api, ws):
    out = {}
    x = ids(api)
    for how in ("accepted", "rejected", "failed_cycle"):
        store = api.MemoryStore()
        held_world(api, store)
        s = scoped(api, ws, store, token=launch(api, store))
        before = history(api, store)
        recorded = collect_for(s)
        cycle = recorded["cycle"]
        entry = {"observed": observe_collection(s, recorded), "candidate": recorded["candidate"],
                 "target": cycle["attempt_scope_target"], "dispatch": dispatch(s, x.scope), "row": counters(s),
                 "adoption_remaining": cycle["remaining"],
                 "key_and_identity": [recorded["candidate"]["key"], recorded["candidate"]["id"],
                                      len(recorded["candidate"]["id"])]}
        if how == "failed_cycle":
            entry["failed"] = brief(s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "fixture_stop"))
        else:
            entry["settled"] = settle(s, cycle, how)["result"]
        entry["dispatch_after"] = dispatch(s, x.scope)
        status = s.programs.status(R.PROGRAM)
        entry["status"] = {k: status[k] for k in ("attempt_scope", "investigations", "audit_progress", "adoptions",
                                                  "state", "blocked_reason")}
        entry["receipt"] = status["cycle_receipts"][0]["attempt_scope"]
        entry["history_unchanged"] = history(api, store) == before
        entry["leads_never_claimed"] = [c["claimed_cycle"] for c in cands(s) if c["source"] != "investigation"]
        out[how] = entry
    return out


def exclusions(api):
    x = ids(api)

    def set_(bucket, key, **fields):
        return lambda store: edit(store, bucket, key, **fields)
    return {
        "malformed": lambda st: put(st, "portfolio_bindings", "dup", {"job_id": S1, "project_id": "ops"}),
        "state": set_("continuation_intents", x.i_r, state="awaiting_owner"),
        "policy": set_("continuation_policies", POLICY_ID, policy_sha256="7" * 64),
        "family": set_("continuation_intents", x.i_r, family="another-root"),
        "receipted": lambda st: put(st, "continuation_research_receipts", x.i_r, {"id": x.i_r}),
        "insufficient_attempts": set_("continuation_intents", x.i_f0, state="refused"),
        "attempt_unavailable": lambda st: drop(st, "fleet_jobs", S1),
        "mixed": set_("fleet_jobs", S1, reason_code="other_reason"),
        "mixed_evidence": lambda st: put(st, "continuation_intents", hexid(api, "f0b"), intent(
            hexid(api, "f0b"), "correction", "admitted", J_F0, "c" * 64, "2028-01-01T00:05:00+00:00")),
        "reason_code": lambda st: [edit(st, "fleet_jobs", j, reason_code="unlisted_reason") for j in (J_F0, S1)],
        "project": set_("portfolio_bindings", S1, project_id="other"),
        "family_state": set_("portfolio_investigations", x.cause, state="researched"),
        "family_state_missing": set_("portfolio_investigations", x.cause, kind="audit_progress"),
        "claimed": lambda st: put(st, api.BUCKET_HEADS, x.scope, {"id": x.scope, "investigation": x.scope}),
        "overlap": lambda st: put(st, api.BUCKET_DISPATCHES, "foreign", family_dispatch(api, "foreign", [S1, "x-1"], "rp-x")),
        "overlap_unverifiable": lambda st: put(st, api.BUCKET_DISPATCHES, "sample", family_dispatch(
            api, "sample", ["x-1"], "rp-x", total=60)),
    }


def scope_exclusion(api, ws, mutate):
    """M7 `test_each_exclusion_after_reservation_selects_nothing_and_consumes_no_adoption`."""
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    s = scoped(api, ws, store, token=launch(api, store))
    reserved = s.programs.reserve_cycle(R.PROGRAM, REPO)
    mutate(store)
    recorded = collect(s, reserved["cycle"], LEADS)
    leads = [c for c in cands(s) if c["source"] != "investigation"]
    return {**observe_collection(s, recorded), "target": reserved["cycle"]["attempt_scope_target"]["scope"] == x.scope,
            "row": counters(s), "scope_dispatch": get(store, api.BUCKET_DISPATCHES, x.scope),
            "leads": [[c["status"], c["claimed_cycle"]] for c in leads],
            "complete_cycle": s.programs.complete_cycle(reserved["cycle"]["id"], reserved["cycle"]["owner"])["status"]}


def target_cases(api):
    x = ids(api)
    do = api.owner_actions

    def tampered(store):
        owner = launch(api, store)
        [row] = scan(store, "owner_actions")
        row["binding"]["attempts"] = [S1]
        put(store, "owner_actions", row["id"], row)
        return owner

    def twice(store):
        owner = launch(api, store)
        [row] = scan(store, "owner_actions")
        put(store, "owner_actions", "copy", {**row, "id": "copy"})
        return owner

    def receipted(store):
        put(store, "continuation_research_receipts", x.i_r, {"id": x.i_r})
        return launch(api, store)
    return {"no_owner_launch": (lambda st: "0" * 32, "cycle_owner"),
            "ambiguous_launch": (twice, "cycle_owner"),
            "intended": (lambda st: launch(api, st, state=do.INTENDED), "cycle_owner"),
            "completed": (lambda st: launch(api, st, state=do.COMPLETED), "owner_action"),
            "tampered_binding": (tampered, "owner_action"),
            "other_program": (lambda st: launch(api, st, program="rp-other"), "binding"),
            "other_cycle": (lambda st: launch(api, st, cycle=2), "binding"),
            "family_identity": (lambda st: launch(api, st, investigation=x.cause), "binding.intent_id"),
            "other_family": (lambda st: launch(api, st, family="another-root"), "binding.intent_id"),
            "not_held": (receipted, "binding.intent_id"),
            "partial_attempts": (lambda st: launch(api, st, jobs=(S1,)), "binding.attempts"),
            "wider_attempts": (lambda st: launch(api, st, jobs=(J_F0, S1, Q1)), "binding.attempts")}


def target_refusal(api, ws, make, expected_field):
    """M7 `test_a_missing_or_foreign_owner_target_refuses_before_anything_is_reserved`."""
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    owner = make(store)
    s = scoped(api, ws, store, token=owner)
    row = get(store, api.BUCKET_PROGRAMS, R.PROGRAM)
    result = refused(s, s.programs.reserve_cycle, R.PROGRAM, REPO)
    return {**result, "expected_field": expected_field, "program_row_unchanged": get(
        store, api.BUCKET_PROGRAMS, R.PROGRAM) == row, "cycles": len(scan(store, api.BUCKET_CYCLES))}


def widened_scope(api, ws):
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    s = scoped(api, ws, store, token=launch(api, store, state=api.owner_actions.LAUNCHING))
    reserved = s.programs.reserve_cycle(R.PROGRAM, REPO)
    target = reserved["cycle"]["attempt_scope_target"]
    put(store, "continuation_intents", hexid(api, "f1"), intent(hexid(api, "f1"), "correction", "admitted", "late-job",
                                                                  "c" * 64, "2028-01-01T00:05:00+00:00"))
    with store.transaction() as tx:
        job(tx, "late-job", "ops")
    recorded = collect(s, reserved["cycle"])
    return {**observe_collection(s, recorded), "target_kept": get(store, api.BUCKET_CYCLES, R.PROGRAM + ":001")[
        "attempt_scope_target"] == target, "scope_dispatch": get(store, api.BUCKET_DISPATCHES, x.scope),
            "row": counters(s)}


def another_scope(api, ws):
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    other_root, other_f, other_r = "other-root", hexid(api, "g0"), hexid(api, "g1")
    s = scoped(api, ws, store, token=launch(api, store), source={**SCOPE_SOURCE, "families": [J_F0, other_root]})
    reserved = s.programs.reserve_cycle(R.PROGRAM, REPO)
    with store.transaction() as tx:   # LABELLED: a second held lineage of another listed root becomes eligible meanwhile
        tx.put("continuation_intents", other_f, intent(other_f, "correction", "admitted", "g-0", "d" * 64, T_F0,
                                                       family=other_root))
        tx.put("continuation_intents", other_r, intent(other_r, "research", "research_required", "g-1", "e" * 64, T_R,
                                                       family=other_root))
        job(tx, "g-0", "ops")
        job(tx, "g-1", "ops")
    cycle = reserved["cycle"]
    both = collect(s, cycle)
    out = {"both_eligible": observe_collection(s, both)}
    s.programs.complete_cycle(cycle["id"], cycle["owner"])
    swap(s, R.PROGRAM, launch(api, store, cycle=2))
    reserve(s)
    put(store, "continuation_research_receipts", x.i_r, {"id": x.i_r})   # the target leaves; the other stays eligible
    alone = collect(s, get(store, api.BUCKET_CYCLES, R.PROGRAM + ":002"))
    out["target_left"] = observe_collection(s, alone)
    out["dispatches"] = scan(store, api.BUCKET_DISPATCHES)
    out["row"] = counters(s)
    return out


def rival(api, ws, state):
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    put(store, api.BUCKET_PROGRAMS, "rp-legacy", {"id": "rp-legacy", "state": state,
                                                  "config": {"investigation_source": dict(FAMILY_SOURCE)}})
    s = scoped(api, ws, store, token=launch(api, store))
    recorded = collect_for(s, items=LEADS)
    return {**observe_collection(s, recorded), "row": counters(s), "claimed": get(store, api.BUCKET_DISPATCHES, x.scope) is not None}


def scoped_rival(api, ws):
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    other = scoped(api, ws, store, program="rp-002")
    other.programs.pause("rp-002")
    s = scoped(api, ws, store, token=launch(api, store))
    return observe_collection(s, collect_for(s))


def second_program(api, ws):
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store)
    first, recorded = claim_scope(api, ws, store)
    second = scoped(api, ws, store, program="rp-002", token=launch(api, store, program="rp-002"))
    other = collect_for(second, "rp-002", LEADS)
    restarted = system(api, ws, store=store, token=first.programs.token)
    return {"first_claim": recorded["cycle"]["attempt_scope"]["claimed"], "other": observe_collection(second, other),
            "other_row": counters(second, "rp-002"), "restart": restarted.programs.reserve_cycle(R.PROGRAM, REPO)["reason"],
            "scope_dispatches": [d["id"] for d in scan(store, api.BUCKET_DISPATCHES) if d.get("kind") == "attempt_scope"],
            "scope_is_x": x.scope}


def stale_snapshot(api, ws):
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    s = scoped(api, ws, store, token=launch(api, store))
    cycle = s.programs.reserve_cycle(R.PROGRAM, REPO)["cycle"]
    first = collect(s, cycle, (), {"this_host": 10, "all_hosts": 10})   # LABELLED: no headroom, the target waits cached
    out = {"first": observe_collection(s, first), "cached": s.programs.candidate(R.PROGRAM, "as-" + x.i_r)["status"]}
    s.programs.complete_cycle(cycle["id"], cycle["owner"])
    swap(s, R.PROGRAM, launch(api, store, cycle=2))
    reserved = s.programs.reserve_cycle(R.PROGRAM, REPO)
    put(store, "continuation_research_receipts", x.i_r, {"id": x.i_r})   # the hold ends after the owner preflight
    second = collect(s, reserved["cycle"])
    stale = s.programs.candidate(R.PROGRAM, "as-" + x.i_r)
    out["second"] = observe_collection(s, second)
    out["dropped"] = {"status": stale["status"], "reason": stale["reason"], "snapshot": stale["snapshot"]}
    out["scope_dispatch"] = get(store, api.BUCKET_DISPATCHES, x.scope)
    return out


def claim_defence(api, ws):
    """M7 `test_a_stale_scope_candidate_hits_the_claim_row_and_rolls_back_whole`. LABELLED injected fault: eligibility forgets
    every lifecycle row; the claim defence must still refuse inside the transaction."""
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    first, recorded = claim_scope(api, ws, store)
    first.programs.fail_cycle(recorded["cycle"]["id"], recorded["cycle"]["owner"], "capture", "fixture")   # blocked: no rival
    forgetful = api.application.eligible_attempt_scopes
    second = scoped(api, ws, store, program="rp-002", token=launch(api, store, program="rp-002"))
    reserved = second.programs.reserve_cycle("rp-002", REPO)
    with R.replaced(api.application, "eligible_attempt_scopes", lambda **kw: forgetful(
            **{**kw, "dispatches": [], "recoveries": [], "heads": [], "successors": []})):
        refusal = refused(second, second.programs.record_collection, reserved["cycle"]["id"], reserved["cycle"]["owner"],
                          {}, [], COUNTS)
    return {"refusal": refusal, "cycle_status": get(store, api.BUCKET_CYCLES, "rp-002:001")["status"]}


def fault_before_commit(api, ws):
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    s = scoped(api, ws, store, token=launch(api, store))
    reserved = s.programs.reserve_cycle(R.PROGRAM, REPO)

    def crash(**kwargs):
        raise RuntimeError("LABELLED injected fault before commit")
    with R.replaced(api.application, "dispatch_row", crash):
        failure = refused(s, s.programs.record_collection, reserved["cycle"]["id"], reserved["cycle"]["owner"], {}, [],
                          COUNTS)
    replay = collect(s, reserved["cycle"])
    return {"failure": failure, "replay": observe_collection(s, replay), "row": counters(s),
            "dispatch": dispatch(s, x.scope)}


def forward_cases(api):
    x = ids(api)
    fd = lambda *a, **k: family_dispatch(api, *a, **k)  # noqa: E731
    return {
        "claimed": lambda st: put(st, api.BUCKET_DISPATCHES, "f", fd("f", [S1], "rp-x", state="claimed", result=None)),
        "dispatched": lambda st: put(st, api.BUCKET_DISPATCHES, "f", fd("f", [J_F0], "rp-x", state="dispatched",
                                                                         result=None)),
        "accepted": lambda st: put(st, api.BUCKET_DISPATCHES, "f", fd("f", [S1], "rp-x", result="accepted")),
        "rejected": lambda st: put(st, api.BUCKET_DISPATCHES, "f", fd("f", [S1], "rp-x", result="rejected")),
        "unknown": lambda st: put(st, api.BUCKET_DISPATCHES, "f", fd("f", [J_F0], "rp-x", result="unknown")),
        "pinned_followup": lambda st: put(st, api.BUCKET_SUCCESSORS, x.cause + ":2", {
            "id": x.cause + ":2", "investigation": x.cause, "version": 2, "state": "authorized",
            "members": {"job_ids": [J_F0, "x-1"], "sha256": api.digest([J_F0, "x-1"])}}),
        "truncated_sample": lambda st: put(st, api.BUCKET_DISPATCHES, "f", fd("f", ["x-1"], "rp-x", total=51)),
    }


def forward(api, ws, case):
    """M7 `test_forward_overlap_refuses_before_selection_and_again_at_the_claim`."""
    store = api.MemoryStore()
    held_world(api, store, lineage=False)
    forward_cases(api)[case](store)
    s = scoped(api, ws, store, token=launch(api, store))
    recorded = collect_for(s)
    out = {"before_selection": observe_collection(s, recorded)}
    forgetful = api.application.eligible_attempt_scopes   # LABELLED injected fault: the rule forgets every reservation
    s.programs.complete_cycle(R.PROGRAM + ":001", recorded["cycle"]["owner"])
    swap(s, R.PROGRAM, launch(api, store, cycle=2))
    reserved = s.programs.reserve_cycle(R.PROGRAM, REPO)
    with R.replaced(api.application, "eligible_attempt_scopes", lambda **kw: forgetful(
            **{**kw, "dispatches": [], "successors": []})):
        out["at_the_claim"] = refused(s, s.programs.record_collection, reserved["cycle"]["id"],
                                      reserved["cycle"]["owner"], {}, [], COUNTS)
    return out


def reverse_world(api, store, members=(J_F0, S1, "h-1", "h-2")):
    """No family history: the undecided cause holds the held pair plus two other scoped members."""
    held_world(api, store, lineage=False, members=list(members))
    with store.transaction() as tx:
        for member in members:
            if member not in (J_F0, S1):
                job(tx, member, "ops")


def reverse(api, ws, state, result):
    """M7 `test_a_scope_claim_in_any_state_blocks_the_family_and_its_recovery_replacement`: a member job held permanently."""
    x = ids(api)
    store = api.MemoryStore()
    reverse_world(api, store)
    claim_scope(api, ws, store)
    edit(store, api.BUCKET_DISPATCHES, x.scope, state=state, result=result)   # LABELLED: the scope claim's lifecycle
    put(store, api.BUCKET_RECOVERIES, x.cause, {"id": x.cause, "investigation": x.cause, "state": "authorized",
                                                 "failed": {"program": "rp-x"}, "request_sha256": "6" * 64,
                                                 "replacement": {"program": "rp-fam", "dispatch": x.cause + ".recovery-1"}})
    fam = family(api, ws, store)
    recorded = collect_for(fam, "rp-fam")
    out = {"bridge": recorded["cycle"]["investigations"], "candidate": recorded["candidate"], "row": counters(fam, "rp-fam")}
    forgetful = api.ResearchProgram._scope_held_families   # LABELLED injected fault: the pre-filter forgets the scope
    fam.programs.complete_cycle("rp-fam:001", recorded["cycle"]["owner"])
    fam.clock.value = LATER
    reserved = fam.programs.reserve_cycle("rp-fam", REPO)
    with R.replaced(api.ResearchProgram, "_scope_held_families", staticmethod(lambda *a: set())):
        out["at_the_claim"] = refused(fam, fam.programs.record_collection, reserved["cycle"]["id"],
                                      reserved["cycle"]["owner"], {}, [], COUNTS)
    out["the_pre_filter_is_restored"] = api.ResearchProgram._scope_held_families == forgetful
    return out


def disjoint_and_truncated(api, ws):
    x = ids(api)
    store = api.MemoryStore()
    many = ["m-%02d" % i for i in range(55)]
    reverse_world(api, store, members=many)   # the cause row never holds the pair, but its sample is truncated
    other = api.family_id("rejected", "review_rejected")
    with store.transaction() as tx:
        for member in ("r-1", "r-2"):
            job(tx, member, "ops", status="rejected", reason="review_rejected")
        tx.put("portfolio_investigations", other, {"id": other, "kind": "failure_family", "state": "research_required",
                                                    "family_status": "rejected", "reason_code": "review_rejected",
                                                    "job_ids": ["r-1", "r-2"], "count": 2})
    claim_scope(api, ws, store)
    fam = family(api, ws, store)
    recorded = collect_for(fam, "rp-fam")
    out = {"disjoint_selected": None if recorded["candidate"] is None else recorded["candidate"]["investigation"] == other,
           "bridge": recorded["cycle"]["investigations"]}
    second = family(api, ws, store, program="rp-fam2")
    reserved = second.programs.reserve_cycle("rp-fam2", REPO)
    with R.replaced(api.ResearchProgram, "_scope_held_families", staticmethod(lambda *a: set())):   # LABELLED fault
        out["truncated_at_the_claim"] = refused(second, second.programs.record_collection, reserved["cycle"]["id"],
                                                reserved["cycle"]["owner"], {}, [], COUNTS)
    out["scope_dispatch"] = dispatch(second, x.scope)
    return out


def portfolio_membership(api, ws):
    x = ids(api)
    store = api.MemoryStore()
    held_world(api, store, lineage=False, members=HISTORICAL + [J_F0, S1])   # the reconciler added them; no capture holds them
    s = scoped(api, ws, store, token=launch(api, store))
    recorded = collect_for(s)
    return {**observe_collection(s, recorded), "cause_row": get(store, "portfolio_investigations", x.cause)["job_ids"] == (
        HISTORICAL + [J_F0, S1])}


def legacy_cycle(api, ws):
    store = api.MemoryStore()
    R.portfolio(api, store)
    s = system(api, ws, store=store)
    register(s, investigation_source=dict(R.SOURCE))
    recorded = collect_for(s)
    cycle = get(store, api.BUCKET_CYCLES, R.PROGRAM + ":001")
    status = s.programs.status(R.PROGRAM)
    return {"keys_absent": ["attempt_scope" not in cycle, "attempt_scope_target" not in cycle,
                            "attempt_scope" not in recorded["cycle"], "attempt_scope" not in status],
            "selected": recorded["candidate"]["investigation"] == api.family_id(*R.FAMILY)}


# ---- G5 --------------------------------------------------------------------------------------------------------------------
def selected_cycle(api, ws, **overrides):
    """A program whose cycle 1 selected the local candidate (the cycle is `selected`)."""
    s = system(api, ws)
    cycles = overrides.pop("max_cycles", 4)
    register(s, max_cycles=cycles, max_adoptions=overrides.pop("max_adoptions", min(2, cycles)), **overrides)
    cycle = reserve(s)
    collect(s, cycle, (LOCAL,))
    return s, cycle


def observe_after(s, program=R.PROGRAM):
    return {"row": counters(s, program), "candidates": cands(s, program),
            "cycles": [brief(c) for c in sorted(scan(s.store, s.api.BUCKET_CYCLES), key=lambda c: c["number"])]}


def g5_capture_council(api, ws):
    results = {}
    results["capture_and_start_sequence"] = capture_sequence(api, ws)
    results["capture_refusals"] = capture_refusals(api, ws)
    results["council_start_refusals"] = start_refusals(api, ws)
    results["council_result_refusals"] = result_refusals(api, ws)
    results["owner_mismatch_on_every_record"] = owner_matrix(api, ws)
    results["verdicts"] = {name: verdict_case(api, ws, name, *plan) for name, plan in sorted({
        "accepted": ("accepted", "review_accepted", {}), "rejected": ("rejected", "review_rejected", {}),
        "failed": ("failed", "provider_failed", {}), "unknown": ("unknown", "run_row_missing", {}),
        "failed_no_reason": ("failed", None, {}), "failed_canary_reason": ("failed", "x:" + R.CANARY, {}),
        "unknown_unsafe_reason": ("unknown", "Bad Reason!", {}), "accepted_last_cycle": ("accepted", "fixture",
                                                                                          {"max_cycles": 1}),
        "failed_last_cycle": ("failed", "fixture", {"max_cycles": 1})}.items())}
    results["invalid_verdicts"] = invalid_verdicts(api, ws)
    results["dispatch_result_of_an_investigation_candidate"] = investigation_results(api, ws)
    return results


def capture_sequence(api, ws):
    s, cycle = selected_cycle(api, ws)
    out = {"selected": observe_after(s)}
    captured = s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    out["capture"] = {"cycle": brief(captured), "row": counters(s), "candidates": cands(s)}
    started = s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    out["council_start"] = {"cycle": brief(started), "row": counters(s), "candidates": cands(s)}
    out["no_dispatch_row_for_a_local_candidate"] = scan(s.store, api.BUCKET_DISPATCHES)
    return out


def capture_refusals(api, ws):
    out = {}
    s = system(api, ws)
    register(s, max_cycles=4)
    cycle = reserve(s)
    out["cycle_collecting"] = refused(s, s.programs.record_capture, cycle["id"], cycle["owner"], CAPTURE)
    out["unknown_cycle"] = refused(s, s.programs.record_capture, "rp-001:009", cycle["owner"], CAPTURE)
    collect(s, cycle, (LOCAL,))
    for label, owner in (("other", "someone-else"), ("empty", ""), ("none", None)):
        out["owner_" + label] = refused(s, s.programs.record_capture, cycle["id"], owner, CAPTURE)
    t = system(api, ws)
    register(t)
    other = reserve(t)
    collect(t, other, (LOCAL,))
    edit(t.store, api.BUCKET_PROGRAMS, R.PROGRAM, active_cycle=None)   # LABELLED row edit: the program no longer owns it
    out["cycle_not_active"] = refused(t, t.programs.record_capture, other["id"], other["owner"], CAPTURE)
    s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    out["captured_twice"] = refused(s, s.programs.record_capture, cycle["id"], cycle["owner"], CAPTURE)
    n = system(api, ws)
    register(n)
    nothing = reserve(n)
    collect(n, nothing, (UNRELATED,))
    out["no_selection_cycle"] = refused(n, n.programs.record_capture, nothing["id"], nothing["owner"], CAPTURE)
    return out


def start_refusals(api, ws):
    out = {}
    s, cycle = selected_cycle(api, ws)
    args = ("rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    out["before_capture"] = refused(s, s.programs.record_council_start, cycle["id"], cycle["owner"], *args)
    out["unknown_cycle"] = refused(s, s.programs.record_council_start, "rp-001:009", cycle["owner"], *args)
    s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    out["owner_mismatch"] = refused(s, s.programs.record_council_start, cycle["id"], "someone-else", *args)
    s.programs.record_council_start(cycle["id"], cycle["owner"], *args)
    out["started_twice"] = refused(s, s.programs.record_council_start, cycle["id"], cycle["owner"], *args)
    return out


def result_refusals(api, ws):
    out = {}
    s, cycle = selected_cycle(api, ws)
    verdict = {"result": "accepted", "reason_code": "fixture", "row_status": "accepted"}
    out["selected_not_started"] = refused(s, s.programs.record_council_result, cycle["id"], cycle["owner"], verdict)
    s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    out["captured_not_started"] = refused(s, s.programs.record_council_result, cycle["id"], cycle["owner"], verdict)
    s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    out["unknown_cycle"] = refused(s, s.programs.record_council_result, "rp-001:009", cycle["owner"], verdict)
    out["owner_mismatch"] = refused(s, s.programs.record_council_result, cycle["id"], "someone-else", verdict)
    s.programs.record_council_result(cycle["id"], cycle["owner"], verdict)
    out["recorded_twice"] = refused(s, s.programs.record_council_result, cycle["id"], cycle["owner"], verdict)
    return out


def owner_matrix(api, ws):
    """`_owned` for every record, with a foreign, an empty and an absent owner, at the status each record expects."""
    out = {}
    calls = {"record_collection": lambda s, c, o: s.programs.record_collection(c["id"], o, {}, [], COUNTS),
             "record_capture": lambda s, c, o: s.programs.record_capture(c["id"], o, CAPTURE),
             "record_council_start": lambda s, c, o: s.programs.record_council_start(c["id"], o, "rp-001.c001", MANIFEST_SHA,
                                                                                     MANIFEST_REF),
             "record_council_result": lambda s, c, o: s.programs.record_council_result(
                 c["id"], o, {"result": "accepted", "reason_code": "fixture", "row_status": "accepted"}),
             "complete_cycle": lambda s, c, o: s.programs.complete_cycle(c["id"], o),
             "fail_cycle": lambda s, c, o: s.programs.fail_cycle(c["id"], o, "capture", "fixture")}
    stage = {"record_collection": "reserved", "record_capture": "selected", "record_council_start": "captured",
             "record_council_result": "council", "complete_cycle": "no_selection", "fail_cycle": "selected"}
    for name, call_ in calls.items():
        s = system(api, ws)
        register(s)
        cycle = reserve(s)
        if stage[name] != "reserved":
            if stage[name] == "no_selection":
                collect(s, cycle, (UNRELATED,))
            else:
                collect(s, cycle, (LOCAL,))
            if stage[name] in ("captured", "council"):
                s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
            if stage[name] == "council":
                s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
        out[name] = {label: refused(s, lambda o=owner: call_(s, cycle, o))
                     for label, owner in (("other", "someone-else"), ("empty", ""), ("none", None))}
    return out


def verdict_case(api, ws, name, result, reason, options):
    s, cycle = selected_cycle(api, ws, **options)
    s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    recorded = s.programs.record_council_result(cycle["id"], cycle["owner"],
                                                {"result": result, "reason_code": reason, "row_status": result})
    out = {"cycle": brief(recorded), "after": observe_after(s)}
    out["status"] = {k: s.programs.status(R.PROGRAM)[k] for k in ("state", "stop_reason", "blocked_reason", "cycles",
                                                                    "adoptions", "candidates")}
    s.clock.advance(3600)
    reserved = R.call(ws, s.programs.reserve_cycle, R.PROGRAM, REPO)["value"]
    out["reserve_next"] = {k: reserved[k] for k in ("reserved", "reason", "state")}
    return out


def invalid_verdicts(api, ws):
    out = {}
    s, cycle = selected_cycle(api, ws)
    s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    for label, verdict in (("bogus_result", {"result": "bogus"}), ("none_result", {"result": None}),
                           ("running_result", {"result": "running"}), ("missing_result", {}),
                           ("uppercase_result", {"result": "Accepted"})):
        out[label] = refused(s, s.programs.record_council_result, cycle["id"], cycle["owner"], verdict)
    out["cycle_still_in_council"] = get(s.store, api.BUCKET_CYCLES, cycle["id"])["status"]
    return out


def investigation_results(api, ws):
    """M7 `_record_dispatch_result`: the outcome comes from the authoritative run row; the caller's verdict is kept as
    `reported_result` only (a missing, mismatched or running row stays unknown, never accepted)."""
    out = {}
    key = api.family_id(*R.FAMILY)
    plans = {"accepted_row": ("accepted", "accepted", {}), "rejected_row": ("rejected", "rejected", {}),
             "exhausted_row_is_failed": ("accepted", "exhausted", {}),
             "running_row_is_unknown": ("accepted", "running", {}),
             "mismatched_digest_is_unknown": ("accepted", "same", {"sha": "0" * 64}),
             "missing_row_is_unknown": ("accepted", None, {}),
             "reported_rejected_but_the_row_accepted": ("rejected", "accepted", {}),
             "reported_non_result_is_refused": ("Bad Code!", "accepted", {}),
             "reported_unknown_blocks_the_program": ("unknown", "unknown", {})}
    for name, (reported, status, extra) in sorted(plans.items()):
        store = api.MemoryStore()
        R.portfolio(api, store)
        s = system(api, ws, store=store)
        register(s, max_cycles=3, max_adoptions=2, investigation_source=dict(R.SOURCE))
        cycle = reserve(s)
        claimed = collect(s, cycle, (PGTOOL,))
        row_status = reported if status == "same" else status
        try:
            settled = settle(s, cycle, reported, run_status=row_status, **extra)
        except Exception as exc:  # the reported verdict "Bad Code!" is not a council result: the record refuses
            settled = {"raised": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None)}
        out[name] = {"claimed": claimed["cycle"]["investigations"], "settled": settled, "dispatch": dispatch(s, key),
                     "status": {k: s.programs.status(R.PROGRAM)[k] for k in ("investigations", "state", "blocked_reason")},
                     "receipt": s.programs.status(R.PROGRAM)["cycle_receipts"][0]["investigations"]}
    # dispatch_not_started: a dispatch row that never recorded its run (LABELLED row edit after the council start)
    store = api.MemoryStore()
    R.portfolio(api, store)
    s = system(api, ws, store=store)
    register(s, investigation_source=dict(R.SOURCE))
    cycle = reserve(s)
    collect(s, cycle, (PGTOOL,))
    s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    edit(store, api.BUCKET_DISPATCHES, key, run_id=None, manifest_sha256=None)
    done = s.programs.record_council_result(cycle["id"], cycle["owner"], {"result": "accepted", "reason_code": "fixture",
                                                                       "row_status": "accepted"})
    out["dispatch_not_started_is_unknown"] = {"cycle": brief(done), "dispatch": dispatch(s, key)}
    # another program's claim is never rewritten from this cycle
    store = api.MemoryStore()
    R.portfolio(api, store)
    s = system(api, ws, store=store)
    register(s, investigation_source=dict(R.SOURCE))
    cycle = reserve(s)
    collect(s, cycle, (PGTOOL,))
    s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    edit(store, api.BUCKET_DISPATCHES, key, program="rp-other")   # LABELLED row edit: the claim belongs to another program
    started = s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    out["another_programs_claim_is_never_rewritten"] = {"cycle": brief(started), "dispatch": dispatch(s, key)}
    return out


# ---- G6 --------------------------------------------------------------------------------------------------------------------
def g6_closing(api, ws):
    results = {}
    results["complete_cycle"] = complete_cases(api, ws)
    results["close_remaining_counts"] = close_counts(api, ws)
    results["fail_cycle"] = {name: fail_case(api, ws, name, *plan) for name, plan in sorted({
        "collecting_without_capture": ("collecting", "evidence", "git_failed", None),
        "selected_without_capture": ("selected", "capture", "capture_refused", None),
        "captured_capture_retained": ("captured", "manifest_derive", "derive_failed", None),
        "captured_with_recovery": ("captured", "manifest_file", "os_error", {"ref": R.CAPTURE_REF,
                                                                           "revision": CAPTURE["revision"]}),
        "council_start_failed_result_failed": ("council", "council_start", "start_failed", None),
        "council_with_recovery": ("council", "council_start", "start_failed", {"note": "retained"}),
        "unsafe_code_is_unknown": ("selected", "capture", "Bad Code!", None),
        "canary_in_the_code": ("selected", "capture", "x:" + R.CANARY, None),
        "no_code_is_unknown": ("selected", "capture", None, None)}.items())}
    results["fail_cycle_refusals"] = fail_refusals(api, ws)
    results["fail_cycle_of_an_investigation_dispatch"] = fail_dispatch(api, ws)
    results["blocked_program_stays_blocked"] = blocked_program(api, ws)
    results["status_candidates_monitor_are_read_only"] = read_only(api, ws)
    return results


def complete_cases(api, ws):
    out = {}
    s = system(api, ws)
    register(s, max_cycles=3)
    cycle = reserve(s)
    out["collecting"] = refused(s, s.programs.complete_cycle, cycle["id"], cycle["owner"])
    collect(s, cycle, (UNRELATED,))
    out["owner_mismatch"] = refused(s, s.programs.complete_cycle, cycle["id"], "someone-else")
    out["unknown_cycle"] = refused(s, s.programs.complete_cycle, "rp-001:009", cycle["owner"])
    before = counters(s)
    done = s.programs.complete_cycle(cycle["id"], cycle["owner"])
    out["completed"] = {"cycle": brief(done), "before": before, "after": counters(s)}
    out["completed_twice"] = refused(s, s.programs.complete_cycle, cycle["id"], cycle["owner"])
    t, picked = selected_cycle(api, ws)
    out["selected_cycle_is_never_a_collection_only_tick"] = refused(t, t.programs.complete_cycle, picked["id"],
                                                                     picked["owner"])
    return out


def close_counts(api, ws):
    s = system(api, ws)
    register(s, max_cycles=2, max_adoptions=2)
    out = []
    for round_, items in enumerate(((LOCAL,), (PGTOOL,)), 1):
        cycle = reserve(s)
        collect(s, cycle, items)
        settle(s, cycle, "accepted")
        closed = get(s.store, api.BUCKET_CYCLES, cycle["id"])
        out.append({"cycle": brief(closed), "row": counters(s)})
        s.clock.advance(3600)
    out.append({"reserve_after_the_cap": s.programs.reserve_cycle(R.PROGRAM, REPO)})
    out.append({"status": {k: s.programs.status(R.PROGRAM)[k] for k in ("state", "stop_reason", "cycles", "adoptions")}})
    return out


def fail_case(api, ws, name, at, stage, code, recovery):
    s, cycle = selected_cycle(api, ws) if at != "collecting" else (None, None)
    if at == "collecting":
        s = system(api, ws)
        register(s, max_cycles=4, max_adoptions=2)
        cycle = reserve(s)
    if at in ("captured", "council"):
        s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
    if at == "council":
        s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
    failed = s.programs.fail_cycle(cycle["id"], cycle["owner"], stage, code, recovery) if recovery is not None else \
        s.programs.fail_cycle(cycle["id"], cycle["owner"], stage, code)
    out = {"cycle": brief(failed), "after": observe_after(s), "failure_has_recovery_key": "recovery" in failed["failure"],
           "canary_in_the_record": R.CANARY in R.canonical_digest(failed) or R.CANARY in str(failed)}
    out["status"] = {k: s.programs.status(R.PROGRAM)[k] for k in ("state", "stop_reason", "blocked_reason", "cycles",
                                                                   "adoptions")}
    return out


def fail_refusals(api, ws):
    out = {}
    s, cycle = selected_cycle(api, ws)
    out["owner_mismatch"] = refused(s, s.programs.fail_cycle, cycle["id"], "someone-else", "capture", "fixture")
    out["unknown_cycle"] = refused(s, s.programs.fail_cycle, "rp-001:009", cycle["owner"], "capture", "fixture")
    s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "fixture")
    out["failed_twice"] = refused(s, s.programs.fail_cycle, cycle["id"], cycle["owner"], "capture", "fixture")
    n = system(api, ws)
    register(n)
    nothing = reserve(n)
    collect(n, nothing, (UNRELATED,))
    out["no_selection_cycle"] = refused(n, n.programs.fail_cycle, nothing["id"], nothing["owner"], "capture", "fixture")
    d = system(api, ws)
    register(d)
    done = reserve(d)
    collect(d, done, (LOCAL,))
    settle(d, done, "accepted")
    out["done_cycle"] = refused(d, d.programs.fail_cycle, done["id"], done["owner"], "capture", "fixture")
    return out


def fail_dispatch(api, ws):
    """A failed dispatch KEEPS its claim: nothing is released, retried or cleaned up."""
    out = {}
    key = api.family_id(*R.FAMILY)
    for at in ("selected", "council"):
        store = api.MemoryStore()
        R.portfolio(api, store)
        s = system(api, ws, store=store)
        register(s, max_cycles=3, max_adoptions=2, investigation_source=dict(R.SOURCE))
        cycle = reserve(s)
        collect(s, cycle, (PGTOOL,))
        if at == "council":
            s.programs.record_capture(cycle["id"], cycle["owner"], CAPTURE)
            s.programs.record_council_start(cycle["id"], cycle["owner"], "rp-001.c001", MANIFEST_SHA, MANIFEST_REF)
        failed = s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "capture_refused")
        status = s.programs.status(R.PROGRAM)
        out[at] = {"cycle": brief(failed), "dispatch": dispatch(s, key), "dispatches": s.programs.dispatches(R.PROGRAM),
                   "status": {k: status[k] for k in ("investigations", "state", "blocked_reason", "adoptions")},
                   "claim_kept_for_another_program": claim_count(api, ws, store)}
    return out


def claim_count(api, ws, store):
    o = system(api, ws, store=store)
    register(o, "rp-002", investigation_source=dict(R.SOURCE))
    other = collect_for(o, "rp-002", (PGTOOL,))
    return {"bridge": other["cycle"]["investigations"], "selection": other["cycle"]["selection"]}


def blocked_program(api, ws):
    s, cycle = selected_cycle(api, ws)
    s.programs.fail_cycle(cycle["id"], cycle["owner"], "capture", "capture_refused")
    s.clock.advance(3600)
    return {"row": counters(s), "reserve": R.guarded(ws, s, s.programs.reserve_cycle, R.PROGRAM, REPO),
            "resume": refused(s, s.programs.resume, R.PROGRAM), "pause": R.guarded(ws, s, s.programs.pause, R.PROGRAM),
            "candidate_stays_claimed": cands(s)}


def read_only(api, ws):
    out = {}
    s = system(api, ws)
    out["monitor_empty_store"] = R.guarded(ws, s, s.programs.monitor)
    register(s, max_cycles=3, max_adoptions=2)
    cycle = reserve(s)
    collect(s, cycle, (LOCAL, PGTOOL))
    settle(s, cycle, "accepted")
    out["status"] = R.guarded(ws, s, s.programs.status, R.PROGRAM)
    out["status_unknown_program"] = refused(s, s.programs.status, "nope")
    out["candidates"] = R.guarded(ws, s, s.programs.candidates, R.PROGRAM)
    out["candidates_unknown_program"] = R.guarded(ws, s, s.programs.candidates, "nope")
    out["candidate"] = R.guarded(ws, s, s.programs.candidate, R.PROGRAM, "local-note")
    out["candidate_absent"] = R.guarded(ws, s, s.programs.candidate, R.PROGRAM, "absent")
    out["monitor"] = R.guarded(ws, s, s.programs.monitor)
    for number in range(21):
        register(s, "rp-%03d" % (number + 10), resume=False)
    many = s.programs.monitor()
    out["monitor_bounded"] = {"truncated": many["truncated"], "listed": len(many["programs"]),
                              "keys": sorted(many), "first": many["programs"][0]["id"] if many["programs"] else None}
    out["monitor_read_only"] = R.guarded(ws, s, s.programs.monitor)
    out["status_is_bounded"] = {"cycle_receipts": len(s.programs.status(R.PROGRAM)["cycle_receipts"])}
    return out


# ---- the run -------------------------------------------------------------------------------------------------------------
GROUPS = (("g1_registration", g1_registration), ("g2_reservation", g2_reservation), ("g3_collection", g3_collection),
          ("g4_scope_and_bridges", g4_scope_and_bridges), ("g5_capture_council", g5_capture_council),
          ("g6_closing", g6_closing))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["cases_per_group"] = counts
        return result
    finally:
        ws.close()
