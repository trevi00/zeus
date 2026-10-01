"""Shared S8 scenario steps (`research.dge`): M7 `application/dge.py` (`DebateSessions`, `DgeRefused`, `_by_status`,
`design_gate`), characterized BEFORE the dge module moves (DESIGN-s8 §2 row `research.council_dge`, the DGE half, and §6 V11;
the branch table `branch-table-research.txt` section `application/dge.py`: 19 raises, every one covered).

- **g1_packet_event**: the M7 `tests/test_dge.py` tests that exercise `domain.dge` (the packet refusals, the deadline
  normalization and the digest, `source_binding`, the event envelope): the validators `register` and `submit` stand on.
- **g2_register**: `register` (a valid packet, the identical cached replay, the replay past the deadline, the conflicts, the
  source verification, the expiry, the clock read inside the transaction), the owner/origin/binding variants, and
  `_check_replacement` (every `supersedes_*` refusal, the order of the checks, the replacement that links).
- **g3_submit_apply**: `submit`/`_submit` (every refusal and the order of the checks, the duplicate and the conflict, the
  executor-owned session, the persisted expiry) and `_apply` for each role and verdict (the carried findings, the findings
  registry, the round cap, the restart, the concurrent winner), with the store digest before and after every refusal.
- **g4_status**: `status` and `_safe` for every session state, the unknown session, a legacy row, `_by_status`.
- **g5_design_gate**: `design_gate` (and `design_gate_reason` through it) for approved, failing and missing sessions, the
  repository/base/plan bindings, the order of the reasons, and that the session is never written.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`, the object a reference (later a
target) driver builds. A packet, an event, a source and a clock are LABELLED fixtures mirroring `tests/test_dge.py`; the
clock is the labelled settable `R.Clock` (M7's `Clock`, `value` for `now`). A session row that no honest call path writes
(a legacy row, an approved row carrying an unresolved finding, a deadline that is not text) is LABELLED where it is edited.
No model, Git, provider, network, process or PostgreSQL is touched. The M7 tests that need `Operation`/`Harness`
(`test_v2_manifest_...`, `test_approved_design_binds_...`, the operation side of the gate tests) belong to the operation
family; their gate side is characterized here through `design_gate`. For every refusal the digest of the whole store before
and after is recorded (nothing written, except the persisted `expired` state, which is itself evidence)."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import s8_research_program as R

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
REPO = "r"
PLAN = {"objective": "Implement the gate " + CANARY, "acceptance_criteria": ["focused tests pass", "ruff passes"],
        "allowed_paths": ["src/codex_harness/domain/dge.py"]}
FUTURE = "2030-01-01T00:00:00+00:00"
PAST = "2020-01-01T00:00:00+00:00"
T0 = "2026-09-16T10:00:00+00:00"
SOURCES = [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "bytes": 10}]   # LABELLED: the Git-verified shape


# ---- builders (M7 tests/test_dge.py) ------------------------------------------------------------------------------------
def packet(**overrides):
    document = {"schema": "urn:zeus:research-packet:1", "id": "sess-1", "base_revision": BASE,
                "topic": "research-bound gate", "objective": "decide the gate design " + CANARY, "exclusions": ["no merge"],
                "plan": deepcopy(PLAN),
                "questions": [{"id": "q1", "question": "Is PG authoritative?", "blocking": True, "status": "answered",
                               "claim_ids": ["c1"]}],
                "sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "locator": "git:docs/contracts.md",
                             "revision": BASE, "read_scope": "INV-OPERATION-001 section"}],
                "claims": [{"id": "c1", "kind": "fact", "text": "PG is authoritative for runtime records", "source_ids": ["s1"]},
                           {"id": "c2", "kind": "unknown", "text": "contention under load is unmeasured", "source_ids": []}],
                "limits": {"max_rounds": 2, "deadline": "2030-01-01T09:00:00+09:00"},
                "supersedes": None, "research_reason": None}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        if inner:
            document[outer][inner] = value
        else:
            document[outer] = value
    return document


def system(api, ws, doc=None, clock=T0, store=None, register=True, **options):
    """A `DebateSessions` over a `MemoryStore` (or the given store) with the labelled clock; `doc` is the packet document
    (validated here), registered under the M7 `SOURCES` unless `register` is False; `options` go to `register`."""
    store = store or api.MemoryStore()
    clock = R.Clock(clock)
    valid = api.validate_packet(doc if doc is not None else packet())
    s = SimpleNamespace(api=api, ws=ws, store=store, clock=clock, svc=api.DebateSessions(store, clock), valid=valid,
                        digest=api.packet_digest(valid))
    if register:
        s.svc.register(valid, REPO, SOURCES, **options)
    return s


def event(s, role, version, round_number=1, payload=None, digest_value=None, event_id=None, **extra):
    payloads = {"proposer": {"summary": "bind approval to the exact plan", "claim_ids": ["c1"]},
                "attacker": {"findings": []},
                "arbiter": {"verdict": "accept", "rationale": "structure holds", "dispositions": [], "research_question": None}}
    return {"schema": "urn:zeus:debate-event:1", "id": event_id or f"{role}-{round_number}-{version}",
            "expected_version": version, "packet_digest": digest_value or s.digest, "round": round_number, "role": role,
            "payload": payload if payload is not None else payloads[role], **extra}


def finding(fid="f1", severity="minor", criterion="focused tests pass"):
    return {"id": fid, "criterion": criterion, "severity": severity, "scenario": "a stale row wins", "claim_ids": ["c1"]}


def arbiter(verdict, dispositions=(), question=None):
    return {"verdict": verdict, "rationale": "recorded operator decision", "dispositions": list(dispositions),
            "research_question": question}


def disposition(finding_id, decision, reason="r"):
    return {"finding_id": finding_id, "decision": decision, "reason": reason}


def put(store, bucket, key, body):
    with store.transaction() as tx:
        tx.put(bucket, key, body)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def scan(store, bucket):
    with store.transaction() as tx:
        return tx.scan(bucket)


def edit(s, session_id="sess-1", **fields):
    """LABELLED row edit: a state no honest call path reaches."""
    row = get(s.store, s.api.SESSIONS, session_id)
    row.update(fields)
    put(s.store, s.api.SESSIONS, session_id, row)


def at_stage(api, ws, stage):
    """M7 `test_unapproved_stale_or_expired_sessions_never_authorize_a_claim`: a one-round session driven to `stage`
    (`proposal`, `critique`, `arbitration`, `needs_research`, `rejected`, `exhausted`, `expired`, `design_approved`)."""
    s = system(api, ws, packet(**{"limits.max_rounds": 1}))
    if stage != "proposal":
        s.svc.submit("sess-1", event(s, "proposer", 0))
    if stage not in {"proposal", "critique"}:
        found = [finding("f1", "critical")] if stage == "needs_research" else []
        s.svc.submit("sess-1", event(s, "attacker", 1, payload={"findings": found}))
    if stage == "needs_research":
        s.svc.submit("sess-1", event(s, "arbiter", 2, payload=arbiter(
            "needs_research", [disposition("f1", "blocking")], "which lock?")))
    elif stage == "rejected":
        s.svc.submit("sess-1", event(s, "arbiter", 2, payload=arbiter("reject")))
    elif stage == "exhausted":
        s.svc.submit("sess-1", event(s, "arbiter", 2, payload=arbiter("revise")))
    elif stage == "design_approved":
        s.svc.submit("sess-1", event(s, "arbiter", 2))
    elif stage == "expired":
        s.clock.value = "2031-01-01T00:00:00+00:00"
        R.call(ws, s.svc.submit, "sess-1", event(s, "arbiter", 2))
    return s


def carried_session(api, ws, store=None, clock=T0):
    """M7 `carried_session`: round 1 critical f1 and minor f2 both blocking, verdict revise -> round 2 proposal."""
    s = system(api, ws, store=store, clock=clock)
    s.svc.submit("sess-1", event(s, "proposer", 0))
    s.svc.submit("sess-1", event(s, "attacker", 1, payload={"findings": [finding("f1", "critical"), finding("f2", "minor")]}))
    s.svc.submit("sess-1", event(s, "arbiter", 2, payload=arbiter("revise", [
        disposition("f1", "blocking", "no fix yet"), disposition("f2", "blocking", "needs a scenario")])))
    s.svc.submit("sess-1", event(s, "proposer", 3, round_number=2))
    return s


# ---- observations -----------------------------------------------------------------------------------------------------
def obs(s, fn, *args, **kwargs):
    """One call: its value or refusal, and the digest of the whole store before and after."""
    before = R.store_digest(s.store)
    result = R.call(s.ws, fn, *args, **kwargs)
    after = R.store_digest(s.store)
    return {**result, "store_before": before, "store_after": after, "nothing_written": before == after}


def leak(result):
    """Whether a refusal message holds a value (a refusal names a code or a field, never a value)."""
    return CANARY in str(result.get("message", ""))


def brief(s, session_id="sess-1"):
    """The projection a case reads after a call: the session phase, version and counts, the events count, and the digests."""
    row = get(s.store, s.api.SESSIONS, session_id)
    if row is None:
        return None
    return {"state": row["state"], "round": row["round"], "version": row["version"], "findings": [
        [f["id"], f["status"]] for f in row.get("findings") or []], "events": len(scan(s.store, s.api.EVENTS)),
        "history": len(row["history"]), "row": R.canonical_digest(row), "store": R.store_digest(s.store)}


def refused(s, fn, *args, **kwargs):
    """A refusal case: the call's outcome with the leak flag, and the session brief after it."""
    result = obs(s, fn, *args, **kwargs)
    result["leaks_value"] = leak(result)
    result["brief"] = brief(s)
    return result


# ---- G1 --------------------------------------------------------------------------------------------------------------------
PACKET_FAULTS = [
    ("schema", "urn:zeus:research-packet:2"), ("id", "../x"), ("base_revision", "abc"), ("extra", 1), ("topic", ""),
    ("exclusions", "no merge"), ("plan.allowed_paths", []), ("plan.extra", 1), ("questions", []),
    ("questions", [{"id": "q1", "question": "x", "blocking": 1, "status": "answered", "claim_ids": ["c1"]}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": True, "status": "unknown", "claim_ids": []}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "answered", "claim_ids": []}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "answered", "claim_ids": ["c2"]}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "answered", "claim_ids": ["nope"]}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "open", "claim_ids": ["c1"]}]),
    ("sources", []),
    ("sources", [{"id": "s1", "path": "../x", "sha256": "b" * 64, "locator": "l", "revision": "r", "read_scope": "s"}]),
    ("sources", [{"id": "s1", "path": ".git/config", "sha256": "b" * 64, "locator": "l", "revision": "r", "read_scope": "s"}]),
    ("sources", [{"id": "s1", "path": "docs/a.md", "sha256": "B" * 64, "locator": "l", "revision": "r", "read_scope": "s"}]),
    ("sources", [{"id": "s1", "path": "docs/a.md", "sha256": "b" * 64, "locator": "l", "revision": "r"}]),
    ("claims", [{"id": "c1", "kind": "fact", "text": "t", "source_ids": []}]),
    ("claims", [{"id": "c1", "kind": "fact", "text": "t", "source_ids": ["missing"]}]),
    ("claims", [{"id": "c1", "kind": "guess", "text": "t", "source_ids": ["s1"]}]),
    ("claims", [{"id": "c1", "kind": "fact", "text": "t", "source_ids": ["s1"]},
                {"id": "c1", "kind": "fact", "text": "t", "source_ids": ["s1"]}]),
    ("limits.max_rounds", 0), ("limits.max_rounds", 5), ("limits.max_rounds", True), ("limits.max_rounds", "2"),
    ("limits.deadline", "2030-01-01T00:00:00"), ("limits.deadline", "soon"), ("limits.deadline", 1),
    ("supersedes", "sess-0"), ("research_reason", "why"), ("supersedes", "sess-1")]

EVENT_FAULTS = [("schema", "x"), ("id", ""), ("expected_version", -1), ("expected_version", True), ("expected_version", "0"),
                ("packet_digest", "x"), ("round", 0), ("round", 5), ("role", "critic"), ("payload", []), ("extra", 1)]


def g1_packet_event(api, ws):
    out = {}
    s = system(api, ws, register=False)
    # M7 test_packet_refuses_schema_type_reference_boolean_digest_and_deadline_faults (33 parameters; the M7 test asserts
    # the canary is never in the message).
    faults = []
    for field, value in PACKET_FAULTS:
        document = packet()
        if field == "supersedes" and value == "sess-1":
            document["research_reason"] = "answers the prior question"
        else:
            outer, _, inner = field.partition(".")
            if inner:
                document[outer][inner] = value
            else:
                document[outer] = value
        result = R.call(ws, api.validate_packet, document)
        faults.append({"field": field, "value": value, **result, "leaks_value": leak(result)})
    out["packet_faults"] = faults
    # M7 test_packet_normalizes_deadline_to_utc_and_digest_is_deterministic
    valid = s.valid
    out["packet_normalization"] = {
        "deadline": valid["limits"]["deadline"], "plan_equal": valid["plan"] == PLAN, "digest": s.digest,
        "digest_stable": api.packet_digest(api.validate_packet(packet())) == s.digest,
        "same_instant_same_digest": api.packet_digest(api.validate_packet(packet(**{"limits.deadline": "2030-01-01T00:00:00Z"}))) == s.digest,
        "other_topic_other_digest": api.packet_digest(api.validate_packet(packet(topic="other"))) != s.digest,
        "inference_claim_kind": api.validate_packet(packet(claims=[{"id": "c1", "kind": "inference", "text": "t",
                                                                    "source_ids": ["s1"]}]))["claims"][0]["kind"],
        "normalized": valid}
    # M7 test_source_binding_requires_regular_blob_and_exact_bytes
    import hashlib
    data = b"# contracts\n"
    source = {"id": "s1", "path": "docs/contracts.md", "sha256": hashlib.sha256(data).hexdigest()}
    out["source_binding"] = {
        "regular_blob": api.source_binding(source, "100644", data) == {**source, "bytes": len(data)},
        "refused_modes": {str(mode): R.call(ws, api.source_binding, source, mode, data)
                          for mode in ("120000", "040000", "160000", "100755", None)},
        "refused_bytes": R.call(ws, api.source_binding, source, "100644", data + b"x")}
    # M7 test_event_envelope_is_strict (11 parameters)
    envelope = []
    for field, value in EVENT_FAULTS:
        document = event(s, "proposer", 0, **{field: value}) if field == "extra" else {**event(s, "proposer", 0), field: value}
        envelope.append({"field": field, "value": value, **R.call(ws, api.validate_event, document)})
    out["event_envelope_faults"] = envelope
    out["event_envelope_valid"] = {"digest": api.event_digest(api.validate_event(event(s, "proposer", 0)))}
    out["vocabulary"] = {"ORIGIN": api.ORIGIN, "PHASE_ROLE": api.PHASE_ROLE, "TERMINAL": sorted(api.TERMINAL), "TRUST": api.TRUST,
                         "SESSIONS": api.SESSIONS, "EVENTS": api.EVENTS, "STATUS_SCHEMA": api.STATUS_SCHEMA}
    out["dge_refused"] = {"is_contract_error": issubclass(api.DgeRefused, api.ContractError),
                          "instance": {"reason_code": api.DgeRefused("x").reason_code, "message": str(api.DgeRefused("x"))}}
    return out


# ---- G2 --------------------------------------------------------------------------------------------------------------------
def g2_register(api, ws):
    out = {}
    s = system(api, ws, register=False)
    out["register_valid"] = obs(s, s.svc.register, s.valid, REPO, SOURCES)
    out["register_valid_brief"] = brief(s)
    out["register_exact_replay_is_cached"] = obs(s, s.svc.register, deepcopy(s.valid), REPO, SOURCES)
    out["register_packet_conflict_other_topic"] = refused(s, s.svc.register, api.validate_packet(packet(topic="changed")), REPO, SOURCES)
    out["register_packet_conflict_other_repository"] = refused(s, s.svc.register, s.valid, "other-repository-digest", SOURCES)
    # M7 test_register_is_idempotent... : the refusals on a fresh service, and the status reading
    for name, sources in (("none", []), ("other_sha", [{**SOURCES[0], "sha256": "c" * 64}]),
                          ("extra_source", SOURCES + [{"id": "s2", "path": "docs/x.md", "sha256": "d" * 64, "bytes": 1}]),
                          ("duplicate_source", SOURCES + SOURCES)):
        t = system(api, ws, register=False)
        out["register_source_verification_incomplete_" + name] = refused(t, t.svc.register, t.valid, REPO, sources)
    t = system(api, ws, register=False)
    out["register_source_missing_fields_after_verification"] = refused(t, t.svc.register, t.valid, REPO, [{"id": "s1", "sha256": "b" * 64}])
    t = system(api, ws, packet(**{"limits.deadline": PAST}), register=False)
    out["register_packet_expired"] = refused(t, t.svc.register, t.valid, REPO, SOURCES)
    out["register_view_after_register"] = s.svc.status("sess-1")
    out["register_unknown_status"] = refused(s, s.svc.status, "nope")
    view = s.svc.status("sess-1")
    out["register_view_flags"] = {"leaks_canary": CANARY in json.dumps(view), "phase": view["phase"], "counts": view["counts"],
                                  "remaining_says_not_implemented": "not implemented" in view["remaining"],
                                  "trust_says_attestations": "attestations" in view["trust"]}
    # the deadline boundary: now == deadline is expired, one second before is registrable
    for name, now in (("at_deadline", FUTURE), ("one_second_before", "2029-12-31T23:59:59+00:00"),
                      ("offset_form_one_second_before", "2030-01-01T08:59:59+09:00"), ("offset_form_at_deadline", "2030-01-01T09:00:00+09:00")):
        t = system(api, ws, clock=now, register=False)
        out["register_deadline_boundary_" + name] = refused(t, t.svc.register, t.valid, REPO, SOURCES)
    # two sources: the verified list is stored in the order given (not the packet's)
    two = packet(sources=[packet()["sources"][0], {"id": "s2", "path": "docs/other.md", "sha256": "c" * 64, "locator": "l",
                                                   "revision": BASE, "read_scope": "s"}])
    t = system(api, ws, two, register=False)
    reverse = [{"id": "s2", "path": "docs/other.md", "sha256": "c" * 64, "bytes": 3}, SOURCES[0]]
    t.svc.register(t.valid, REPO, reverse)
    out["register_sources_order_independent"] = {"sources_verified": [x["id"] for x in get(t.store, api.SESSIONS, "sess-1")["sources_verified"]]}
    # the default clock is the kernel's `utcnow` (the harness's fake clock)
    store = api.MemoryStore()
    default = api.DebateSessions(store)
    row = default.register(s.valid, REPO, SOURCES)["session"]
    out["register_default_clock"] = {"registered_at": row["registered_at"], "updated_at": row["updated_at"], "cached": False}
    # M7 test_registration_reads_the_clock_inside_the_transaction_after_waiting_for_the_lock
    store, clock = api.MemoryStore(), R.Clock(T0)
    holding, release = threading.Event(), threading.Event()

    def hold():
        with store.transaction():
            holding.set()
            release.wait()
    holder = threading.Thread(target=hold)
    holder.start()
    holding.wait()

    class Contended:
        """LABELLED: the deadline passes while register waits for the lock (M7's `Contended`)."""

        def transaction(self):
            clock.value = FUTURE
            release.set()
            return store.transaction()
    contended = R.call(ws, api.DebateSessions(Contended(), clock).register, s.valid, REPO, SOURCES)
    holder.join()
    out["register_reads_the_clock_inside_the_transaction"] = {**contended, "sessions": scan(store, api.SESSIONS)}
    # M7 test_exact_registration_replay_after_the_deadline_returns_the_historical_row_without_reauthorizing
    r = system(api, ws)
    before = r.svc.status("sess-1")
    r.clock.value = "2031-01-01T00:00:00+00:00"
    replay = obs(r, r.svc.register, deepcopy(r.valid), REPO, SOURCES)
    out["replay_after_deadline"] = {"cached": replay["value"]["cached"], "nothing_written": replay["nothing_written"],
                                    "status_unchanged": r.svc.status("sess-1") == before}
    out["replay_after_deadline_conflict"] = refused(r, r.svc.register, api.validate_packet(packet(topic="changed")), REPO, SOURCES)
    out["replay_after_deadline_new_id_expired"] = refused(r, r.svc.register, api.validate_packet(packet(id="sess-late")), REPO, SOURCES)
    out["replay_after_deadline_submit_persists_expiry"] = refused(r, r.svc.submit, "sess-1", event(r, "proposer", 0))
    after = r.svc.status("sess-1")
    out["replay_after_deadline_final"] = {"state": after["state"], "deadline_kept": after["deadline"] == before["deadline"],
                                          "history": after["history"], "finished_at": after["finished_at"]}
    # owner, origin and binding variants (INV-AUTONOMOUS-001)
    v = system(api, ws, register=False)
    binding = {"researcher": "fixture-run", "model": "labelled"}
    out["register_owned_origin_binding"] = obs(v, v.svc.register, v.valid, REPO, SOURCES, origin="researcher", owner="run-9", binding=binding)
    out["register_owned_replay_ignores_owner_origin"] = obs(v, v.svc.register, deepcopy(v.valid), REPO, SOURCES, origin="other", owner="run-10")
    out["register_owned_status"] = v.svc.status("sess-1")
    w = system(api, ws, register=False)
    out["register_default_owner_origin"] = {k: w.svc.register(w.valid, REPO, SOURCES)["session"][k]
                                            for k in ("origin", "owner", "research_binding")}
    # _check_replacement: every refusal, in order, and the replacement that links
    out.update(g2_replacement(api, ws))
    return out


def g2_replacement(api, ws):
    out = {}
    s = system(api, ws)
    s.svc.submit("sess-1", event(s, "proposer", 0))
    s.svc.submit("sess-1", event(s, "attacker", 1, payload={"findings": [finding("f1", "critical")]}))
    s.svc.submit("sess-1", event(s, "arbiter", 2, payload=arbiter("needs_research", [disposition("f1", "blocking")],
                                                                  "Does PG serialize writers?")))
    out["replacement_prior_state"] = brief(s)
    answered = {"id": "q2", "question": "Does PG serialize writers?", "blocking": True, "status": "answered", "claim_ids": ["c1"]}
    unanswered = {**answered, "status": "unknown", "blocking": False, "claim_ids": []}

    def replacement(**over):
        base = packet(id="sess-2", supersedes="sess-1", research_reason="answers the blocking question",
                      questions=[packet()["questions"][0], answered])
        base.update(over)
        return api.validate_packet(base)
    out["replacement_supersedes_unknown"] = refused(s, s.svc.register, replacement(supersedes="ghost"), REPO, SOURCES)
    out["replacement_question_unanswered"] = refused(s, s.svc.register, replacement(questions=[packet()["questions"][0], unanswered]), REPO, SOURCES)
    out["replacement_answers_another_question"] = refused(
        s, s.svc.register, replacement(questions=[packet()["questions"][0], {**answered, "question": "Something else?"}]), REPO, SOURCES)
    out["replacement_plan_mismatch_objective"] = refused(s, s.svc.register, replacement(plan={**PLAN, "objective": "other"}), REPO, SOURCES)
    out["replacement_plan_mismatch_paths"] = refused(
        s, s.svc.register, replacement(plan={**PLAN, "allowed_paths": ["docs/other.md"]}), REPO, SOURCES)
    out["replacement_packet_objective_mismatch"] = refused(s, s.svc.register, replacement(objective="a different objective"), REPO, SOURCES)
    # the order: unknown, state, plan, question, already replaced
    out["replacement_order_plan_before_question"] = refused(
        s, s.svc.register, replacement(plan={**PLAN, "objective": "other"}, questions=[packet()["questions"][0], unanswered]), REPO, SOURCES)
    out["replacement_order_expiry_before_supersedes"] = refused(
        s, s.svc.register, replacement(supersedes="ghost", **{"limits": {"max_rounds": 2, "deadline": PAST}}), REPO, SOURCES)
    other = system(api, ws)
    out["replacement_not_needs_research_prior_in_proposal"] = refused(other, other.svc.register, replacement(supersedes="sess-1"), REPO, SOURCES)
    for stage in ("critique", "arbitration", "rejected", "exhausted", "expired", "design_approved"):
        t = at_stage(api, ws, stage)
        t.clock.value = T0   # the replacement is registered before its own deadline (an expired prior moved the clock on)
        out["replacement_not_needs_research_prior_" + stage] = refused(t, t.svc.register, replacement(supersedes="sess-1"), REPO, SOURCES)
    fresh = obs(s, s.svc.register, replacement(), REPO, SOURCES)
    out["replacement_registers"] = fresh
    out["replacement_registers_flags"] = {
        "cached": fresh["value"]["cached"], "supersedes": fresh["value"]["session"]["supersedes"], "version": fresh["value"]["session"]["version"],
        "round": fresh["value"]["session"]["round"], "max_rounds": fresh["value"]["session"]["max_rounds"],
        "research_reason": fresh["value"]["session"]["research_reason"], "prior_preserved": brief(s)}
    out["replacement_already_replaced"] = refused(s, s.svc.register, replacement(id="sess-3"), REPO, SOURCES)
    out["replacement_exact_replay_is_cached"] = obs(s, s.svc.register, replacement(), REPO, SOURCES)
    out["replacement_status"] = s.svc.status("sess-2")
    return out


# ---- G3 --------------------------------------------------------------------------------------------------------------------
def g3_submit_apply(api, ws):
    out = {}
    out.update(g3_walk(api, ws))
    out.update(g3_order(api, ws))
    out.update(g3_payloads(api, ws))
    out.update(g3_rounds(api, ws))
    out.update(g3_owned_expiry_restart(api, ws))
    return out


def g3_walk(api, ws):
    """M7 test_three_events_approve_the_design_and_replays_are_idempotent, with the row after every event."""
    out = {}
    s = system(api, ws)
    first = obs(s, s.svc.submit, "sess-1", event(s, "proposer", 0))
    out["walk_proposer"] = first
    out["walk_proposer_brief"] = brief(s)
    out["walk_proposer_row"] = get(s.store, api.SESSIONS, "sess-1")
    out["walk_proposer_replay_is_duplicate"] = obs(s, s.svc.submit, "sess-1", event(s, "proposer", 0))
    out["walk_proposer_event_conflict"] = refused(
        s, s.svc.submit, "sess-1", event(s, "proposer", 0, payload={"summary": "different", "claim_ids": ["c1"]}))
    out["walk_attacker_stale_version"] = refused(s, s.svc.submit, "sess-1", event(s, "attacker", 0))
    out["walk_attacker"] = obs(s, s.svc.submit, "sess-1", event(s, "attacker", 1, payload={"findings": [finding("f1", "minor")]}))
    out["walk_attacker_row"] = get(s.store, api.SESSIONS, "sess-1")
    done = obs(s, s.svc.submit, "sess-1", event(s, "arbiter", 2, payload=arbiter("accept", [disposition("f1", "deferred", "tracked follow-up")])))
    out["walk_arbiter_accept"] = done
    out["walk_final_row"] = get(s.store, api.SESSIONS, "sess-1")
    view = s.svc.status("sess-1")
    out["walk_final_view_flags"] = {"counts": view["counts"], "decision_event_id": view["decision_event_id"],
                                    "roles": [h["role"] for h in view["history"]],
                                    "leaks": CANARY in json.dumps(view) or "summary" in json.dumps(view)}
    out["walk_terminal_refuses"] = refused(s, s.svc.submit, "sess-1", event(s, "proposer", 3, round_number=2))
    rows = scan(s.store, api.EVENTS)
    out["walk_event_rows"] = {"roles_in_scan_order": [r["role"] for r in rows], "origins": sorted({r["origin"] for r in rows}), "rows": rows}
    out["walk_duplicate_after_terminal_is_still_idempotent"] = obs(s, s.svc.submit, "sess-1", event(s, "proposer", 0))
    out["walk_conflict_after_terminal"] = refused(
        s, s.svc.submit, "sess-1", event(s, "proposer", 0, payload={"summary": "different", "claim_ids": ["c1"]}))
    # M7 test_role_order_is_strict_from_the_first_event
    for role in ("attacker", "arbiter"):
        t = system(api, ws)
        out["role_order_first_event_" + role] = refused(t, t.svc.submit, "sess-1", event(t, role, 0))
    # M7 test_proposer_cannot_skip_the_attacker_and_mismatched_digest_round_or_session_refuse
    t = system(api, ws)
    t.svc.submit("sess-1", event(t, "proposer", 0))
    out["skip_arbiter_after_proposer"] = refused(t, t.svc.submit, "sess-1", event(t, "arbiter", 1))
    out["digest_mismatch"] = refused(t, t.svc.submit, "sess-1", event(t, "attacker", 1, digest_value="0" * 64))
    out["round_mismatch"] = refused(t, t.svc.submit, "sess-1", event(t, "attacker", 1, round_number=2))
    out["unknown_session"] = refused(t, t.svc.submit, "sess-9", event(t, "proposer", 0))
    out["attacker_criterion_not_a_plan_item"] = refused(
        t, t.svc.submit, "sess-1", event(t, "attacker", 1, payload={"findings": [finding(criterion="not a plan item")]}))
    out["attacker_unknown_claim"] = refused(
        t, t.svc.submit, "sess-1", event(t, "attacker", 1, payload={"findings": [{**finding(), "claim_ids": ["zz"]}]}))
    out["attacker_duplicate_finding_ids"] = refused(
        t, t.svc.submit, "sess-1", event(t, "attacker", 1, payload={"findings": [finding("f1"), finding("f1")]}))
    out["no_refused_submission_wrote"] = brief(t)
    return out


def g3_order(api, ws):
    """The order of `_submit`'s checks: a submission that breaks several rules at once reports the first."""
    out = {}
    # event validation first, even for an unknown session (the envelope has no session context)
    s = system(api, ws, register=False)
    out["order_envelope_before_unknown_session"] = refused(s, s.svc.submit, "nope", {**event(s, "proposer", 0), "role": "critic"})
    out["order_unknown_session_before_everything"] = refused(s, s.svc.submit, "nope", event(s, "proposer", 0))
    t = system(api, ws)
    t.svc.submit("sess-1", event(t, "proposer", 0))
    # owner before duplicate/conflict: an owned-session probe with an existing event id
    out["order_session_owned_before_duplicate"] = refused(t, t.svc.submit, "sess-1", event(t, "proposer", 0), owner="run-1")
    # duplicate before digest, round, version, role, payload
    out["order_duplicate_before_other_checks_none"] = obs(t, t.svc.submit, "sess-1", event(t, "proposer", 0))
    # digest mismatch before round mismatch before stale version before role
    out["order_digest_before_round"] = refused(
        t, t.svc.submit, "sess-1", event(t, "proposer", 0, round_number=2, digest_value="0" * 64, event_id="x1"))
    out["order_round_before_stale"] = refused(t, t.svc.submit, "sess-1", event(t, "proposer", 0, round_number=2, event_id="x2"))
    out["order_stale_before_role"] = refused(t, t.svc.submit, "sess-1", event(t, "proposer", 0, event_id="x3"))
    out["order_stale_future_version"] = refused(t, t.svc.submit, "sess-1", event(t, "attacker", 5, event_id="x4"))
    out["order_role_before_payload"] = refused(t, t.svc.submit, "sess-1", event(t, "proposer", 1, event_id="x5", payload={"nonsense": 1}))
    out["order_payload_error_last"] = refused(t, t.svc.submit, "sess-1", event(t, "attacker", 1, event_id="x6", payload={"nonsense": 1}))
    # terminal before expiry; expiry before digest mismatch
    a = at_stage(api, ws, "design_approved")
    a.clock.value = "2031-01-01T00:00:00+00:00"
    out["order_terminal_before_expiry"] = refused(a, a.svc.submit, "sess-1", event(a, "proposer", 3, event_id="y1"))
    b = system(api, ws)
    b.clock.value = "2031-01-01T00:00:00+00:00"
    out["order_expiry_before_digest_mismatch"] = refused(b, b.svc.submit, "sess-1", event(b, "attacker", 9, digest_value="0" * 64, round_number=3))
    out["order_expired_row"] = get(b.store, api.SESSIONS, "sess-1")
    out["order_expired_view"] = b.svc.status("sess-1")
    out["order_expired_events_written"] = len(scan(b.store, api.EVENTS))
    # a duplicate is still idempotent after the deadline (it is answered before the expiry check)
    c = system(api, ws)
    c.svc.submit("sess-1", event(c, "proposer", 0))
    c.clock.value = "2031-01-01T00:00:00+00:00"
    out["order_duplicate_before_expiry"] = obs(c, c.svc.submit, "sess-1", event(c, "proposer", 0))
    out["order_conflict_before_expiry"] = refused(
        c, c.svc.submit, "sess-1", event(c, "proposer", 0, payload={"summary": "different", "claim_ids": ["c1"]}))
    out["order_after_duplicate_no_expiry_written"] = brief(c)
    return out


ARBITER_FAULTS = [
    ("omitted", arbiter("accept")),
    ("duplicate_disposition", arbiter("accept", [disposition("f1", "resolved"), disposition("f1", "resolved")])),
    ("defer_a_critical", arbiter("accept", [disposition("f1", "deferred")])),
    ("accept_with_blocking", arbiter("accept", [disposition("f1", "blocking")])),
    ("revise_with_question", arbiter("revise", [disposition("f1", "resolved")], "why?")),
    ("needs_research_without_question", arbiter("needs_research", [disposition("f1", "blocking")])),
    ("unknown_finding", arbiter("accept", [disposition("f1", "resolved"), disposition("zz", "resolved")])),
    ("missing_question_field", {"verdict": "accept", "rationale": "r", "dispositions": [disposition("f1", "resolved")]}),
    ("unknown_verdict", arbiter("approve", [disposition("f1", "resolved")])),
    ("empty_rationale", {**arbiter("accept", [disposition("f1", "resolved")]), "rationale": " "}),
    ("dispositions_not_a_list", {**arbiter("accept"), "dispositions": "none"}),
    ("unknown_decision", arbiter("accept", [disposition("f1", "waived")])),
    ("empty_reason", arbiter("accept", [disposition("f1", "resolved", "")])),
    ("disposition_extra_field", arbiter("accept", [{**disposition("f1", "resolved"), "extra": 1}])),
    ("needs_research_blank_question", arbiter("needs_research", [disposition("f1", "blocking")], "  "))]


def g3_payloads(api, ws):
    """Every payload refusal (the per-role validators run inside `_submit`), each with the store digest before and after."""
    out = {}
    # M7 test_arbiter_refuses_omitted_dispositions_critical_deferral_blocking_accept_and_question_misuse
    arbiter_faults = {}
    for name, payload in ARBITER_FAULTS:
        s = system(api, ws)
        s.svc.submit("sess-1", event(s, "proposer", 0))
        s.svc.submit("sess-1", event(s, "attacker", 1, payload={"findings": [finding("f1", "critical")]}))
        arbiter_faults[name] = refused(s, s.svc.submit, "sess-1", event(s, "arbiter", 2, payload=payload))
    out["arbiter_faults"] = arbiter_faults
    proposer_faults = {}
    for name, payload in (("empty_summary", {"summary": "", "claim_ids": ["c1"]}), ("extra_field", {"summary": "s", "claim_ids": ["c1"], "x": 1}),
                          ("missing_claims", {"summary": "s"}), ("empty_claims", {"summary": "s", "claim_ids": []}),
                          ("unknown_claim", {"summary": "s", "claim_ids": ["zz"]}),
                          ("duplicate_claims", {"summary": "s", "claim_ids": ["c1", "c1"]}),
                          ("claims_not_a_list", {"summary": "s", "claim_ids": "c1"})):
        s = system(api, ws)
        proposer_faults[name] = refused(s, s.svc.submit, "sess-1", event(s, "proposer", 0, payload=payload))
    out["proposer_faults"] = proposer_faults
    attacker_faults = {}
    for name, payload in (("findings_not_a_list", {"findings": "none"}), ("extra_field", {"findings": [], "x": 1}),
                          ("finding_extra_field", {"findings": [{**finding(), "x": 1}]}),
                          ("bad_severity", {"findings": [{**finding(), "severity": "major"}]}),
                          ("empty_scenario", {"findings": [{**finding(), "scenario": ""}]}),
                          ("bad_id", {"findings": [{**finding(), "id": "../f"}]}),
                          ("empty_claims", {"findings": [{**finding(), "claim_ids": []}]})):
        s = system(api, ws)
        s.svc.submit("sess-1", event(s, "proposer", 0))
        attacker_faults[name] = refused(s, s.svc.submit, "sess-1", event(s, "attacker", 1, payload=payload))
    out["attacker_faults"] = attacker_faults
    return out


def g3_rounds(api, ws):
    out = {}
    # M7 test_revise_opens_the_next_round_and_the_cap_ends_exhausted_without_retry
    s = system(api, ws)
    s.svc.submit("sess-1", event(s, "proposer", 0))
    s.svc.submit("sess-1", event(s, "attacker", 1, payload={"findings": [finding("f1", "critical")]}))
    revise = obs(s, s.svc.submit, "sess-1", event(s, "arbiter", 2, payload=arbiter("revise", [disposition("f1", "blocking")])))
    out["revise_opens_round_two"] = revise
    out["revise_row_after_round_one"] = get(s.store, api.SESSIONS, "sess-1")
    out["revise_old_round_refuses"] = refused(s, s.svc.submit, "sess-1", event(s, "proposer", 3, round_number=1))
    s.svc.submit("sess-1", event(s, "proposer", 3, round_number=2))
    s.svc.submit("sess-1", event(s, "attacker", 4, round_number=2))
    out["cap_ends_exhausted"] = obs(s, s.svc.submit, "sess-1", event(s, "arbiter", 5, round_number=2, payload=arbiter(
        "revise", [disposition("f1", "blocking", "still open")])))
    out["cap_final_row"] = get(s.store, api.SESSIONS, "sess-1")
    out["cap_view_counts"] = {"round": s.svc.status("sess-1")["round"], "counts": s.svc.status("sess-1")["counts"]}
    out["cap_terminal_refuses_next_round"] = refused(s, s.svc.submit, "sess-1", event(s, "proposer", 6, round_number=3))
    t = system(api, ws)
    t.svc.submit("sess-1", event(t, "proposer", 0))
    t.svc.submit("sess-1", event(t, "attacker", 1))
    out["reject_ends_rejected"] = obs(t, t.svc.submit, "sess-1", event(t, "arbiter", 2, payload=arbiter("reject")))
    out["reject_row"] = get(t.store, api.SESSIONS, "sess-1")
    u = system(api, ws, packet(**{"limits.max_rounds": 1}))
    u.svc.submit("sess-1", event(u, "proposer", 0))
    u.svc.submit("sess-1", event(u, "attacker", 1))
    out["revise_at_a_one_round_cap_is_exhausted_at_once"] = obs(u, u.svc.submit, "sess-1", event(u, "arbiter", 2, payload=arbiter("revise")))
    # verdict x state table, one fresh session per verdict, at max_rounds 3 (revise advances twice, then the cap)
    transitions = {}
    for verdict in ("accept", "reject", "needs_research", "revise"):
        v = system(api, ws, packet(**{"limits.max_rounds": 3}))
        steps = []
        for round_number in (1, 2, 3):
            base = (round_number - 1) * 3
            v.svc.submit("sess-1", event(v, "proposer", base, round_number=round_number))
            v.svc.submit("sess-1", event(v, "attacker", base + 1, round_number=round_number))
            question = "which?" if verdict == "needs_research" else None
            steps.append(v.svc.submit("sess-1", event(v, "arbiter", base + 2, round_number=round_number,
                                                      payload=arbiter(verdict, question=question)))["outcome"])
            if v.svc.status("sess-1")["terminal"]:
                break
        transitions[verdict] = {"outcomes": steps, "row": get(v.store, api.SESSIONS, "sess-1")}
    out["verdict_transitions"] = transitions
    # M7 test_unresolved_findings_carry_into_the_next_round_and_silent_omission_never_approves
    c = carried_session(api, ws)
    out["carried_state"] = {"view": c.svc.status("sess-1"), "row": get(c.store, api.SESSIONS, "sess-1")}
    c.svc.submit("sess-1", event(c, "attacker", 4, round_number=2, payload={"findings": []}))
    out["carried_attacker_omits_findings_unresolved"] = c.svc.status("sess-1")["counts"]
    carried_faults = []
    for payload in (arbiter("accept"), arbiter("accept", [disposition("f1", "resolved")]),
                    arbiter("accept", [disposition("f1", "blocking"), disposition("f2", "resolved")]),
                    arbiter("accept", [disposition("f1", "deferred"), disposition("f2", "resolved")]),
                    arbiter("revise", [disposition("f1", "blocking")])):
        carried_faults.append(refused(c, c.svc.submit, "sess-1", event(c, "arbiter", 5, round_number=2, payload=payload)))
    out["carried_arbiter_faults"] = carried_faults
    done = obs(c, c.svc.submit, "sess-1", event(c, "arbiter", 5, round_number=2, payload=arbiter("accept", [
        disposition("f1", "resolved", "explicit fix recorded in round 2 proposal"), disposition("f2", "deferred", "minor, tracked")])))
    out["carried_accept"] = done
    row = get(c.store, api.SESSIONS, "sess-1")
    out["carried_final"] = {"view": c.svc.status("sess-1"), "row": row,
                            "round1_arbitration_preserved": row["rounds"]["1"]["arbitration"]["dispositions"][0]["decision"],
                            "round2_carried": row["rounds"]["2"]["arbitration"]["carried"],
                            "decisions_f1": [d["decision"] for d in row["findings"][0]["decisions"]],
                            "leaks_reason_text": "explicit fix" in json.dumps(c.svc.status("sess-1"))}
    # M7 test_finding_id_reuse_cannot_replace_or_downgrade_a_recorded_finding
    d = carried_session(api, ws)
    reuse = []
    for findings in ([finding("f1", "minor")], [finding("f1", "critical")], [finding("f2", "minor")],
                     [finding("f3", "minor"), finding("f1", "minor")]):
        reuse.append(refused(d, d.svc.submit, "sess-1", event(d, "attacker", 4, round_number=2, payload={"findings": findings})))
    out["reuse_refusals"] = reuse
    d.svc.submit("sess-1", event(d, "attacker", 4, round_number=2, payload={"findings": [finding("f3", "minor")]}))
    out["reuse_current_only_omits_carried"] = refused(d, d.svc.submit, "sess-1", event(d, "arbiter", 5, round_number=2, payload=arbiter(
        "accept", [disposition("f3", "resolved")])))
    out["reuse_all_three_resolved"] = obs(d, d.svc.submit, "sess-1", event(d, "arbiter", 5, round_number=2, payload=arbiter(
        "accept", [disposition("f1", "resolved"), disposition("f2", "resolved"), disposition("f3", "resolved")])))
    row = get(d.store, api.SESSIONS, "sess-1")
    out["reuse_registry"] = {"ids": [f["id"] for f in row["findings"]], "first_severity": row["findings"][0]["severity"],
                             "counts": d.svc.status("sess-1")["counts"]}
    e = system(api, ws, packet(**{"limits.max_rounds": 3}))
    e.svc.submit("sess-1", event(e, "proposer", 0))
    e.svc.submit("sess-1", event(e, "attacker", 1, payload={"findings": [finding("f1", "minor")]}))
    e.svc.submit("sess-1", event(e, "arbiter", 2, payload=arbiter("revise", [disposition("f1", "deferred")])))
    e.svc.submit("sess-1", event(e, "proposer", 3, round_number=2))
    out["reuse_of_a_deferred_id_refused"] = refused(e, e.svc.submit, "sess-1", event(e, "attacker", 4, round_number=2, payload={
        "findings": [finding("f1", "critical")]}))
    out["reuse_deferred_counts"] = e.svc.status("sess-1")["counts"]
    out["reuse_deferred_row"] = get(e.store, api.SESSIONS, "sess-1")
    # M7 test_needs_research_stops_and_only_a_matching_replacement_keeps_linkage (the stop; the replacement is g2)
    n = system(api, ws)
    n.svc.submit("sess-1", event(n, "proposer", 0))
    n.svc.submit("sess-1", event(n, "attacker", 1, payload={"findings": [finding("f1", "critical")]}))
    stop = obs(n, n.svc.submit, "sess-1", event(n, "arbiter", 2, payload=arbiter(
        "needs_research", [disposition("f1", "blocking")], "Does PG serialize writers?")))
    out["needs_research_stops"] = stop
    out["needs_research_row"] = get(n.store, api.SESSIONS, "sess-1")
    out["needs_research_view_flags"] = {"present": n.svc.status("sess-1")["research_question_present"],
                                        "leaks_question": "Does PG" in json.dumps(n.svc.status("sess-1"))}
    # M7 test_concurrent_submissions_on_memory_store_have_exactly_one_winner
    k = system(api, ws)
    outcomes, barrier = [], threading.Barrier(4)

    def attempt(n_):
        barrier.wait()
        try:
            outcomes.append(("recorded", k.svc.submit("sess-1", event(k, "proposer", 0, event_id="race-" + str(n_)))["status"]))
        except api.DgeRefused as exc:
            outcomes.append(("refused", exc.reason_code))
    threads = [threading.Thread(target=attempt, args=(n_,)) for n_ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out["concurrent_one_winner"] = {"outcomes": sorted(outcomes), "version": k.svc.status("sess-1")["version"],
                                    "events": k.svc.status("sess-1")["counts"]["events"]}
    return out


def g3_owned_expiry_restart(api, ws):
    out = {}
    # the executor-owned session (INV-AUTONOMOUS-001)
    o = system(api, ws, register=False)
    o.svc.register(o.valid, REPO, SOURCES, origin="researcher", owner="run-9", binding={"researcher": "fixture-run"})
    out["owned_operator_submit_refused"] = refused(o, o.svc.submit, "sess-1", event(o, "proposer", 0))
    out["owned_other_owner_refused"] = refused(o, o.svc.submit, "sess-1", event(o, "proposer", 0), owner="run-10")
    out["owned_submit"] = obs(o, o.svc.submit, "sess-1", event(o, "proposer", 0), owner="run-9", binding={"step": 1})
    out["owned_event_row"] = scan(o.store, api.EVENTS)
    out["owned_replay_is_duplicate"] = obs(o, o.svc.submit, "sess-1", event(o, "proposer", 0), owner="run-9", binding={"step": 2})
    out["owned_replay_by_operator_refused"] = refused(o, o.svc.submit, "sess-1", event(o, "proposer", 0))
    p = system(api, ws)
    out["operator_session_owner_submit_refused"] = refused(p, p.svc.submit, "sess-1", event(p, "proposer", 0), owner="run-9")
    out["operator_session_binding_without_owner"] = obs(p, p.svc.submit, "sess-1", event(p, "proposer", 0), binding={"note": "x"})
    out["operator_event_row"] = scan(p.store, api.EVENTS)
    # M7 test_deadline_is_aware_utc_never_refreshed_and_expiry_is_persisted_on_the_refused_mutation
    s = system(api, ws)
    s.svc.submit("sess-1", event(s, "proposer", 0))
    s.clock.value = "2030-01-01T08:59:59+09:00"
    out["deadline_one_second_before_records"] = obs(s, s.svc.submit, "sess-1", event(s, "attacker", 1))
    s.clock.value = "2030-01-01T00:00:00Z"
    before = R.store_digest(s.store)
    out["deadline_expiry_refusal"] = refused(s, s.svc.submit, "sess-1", event(s, "arbiter", 2))
    out["deadline_expiry_wrote_the_state"] = {"store_changed": R.store_digest(s.store) != before}
    view = s.svc.status("sess-1")
    out["deadline_expired_view"] = view
    s.clock.value = T0
    out["deadline_backwards_clock_stays_terminal"] = refused(s, s.svc.submit, "sess-1", event(s, "arbiter", 2))
    out["deadline_events_after"] = len(scan(s.store, api.EVENTS))
    # M7 test_restart_from_the_store_retains_phase_limits_and_version
    store = api.MemoryStore()
    first = system(api, ws, store=store)
    first.svc.submit("sess-1", event(first, "proposer", 0))
    second = SimpleNamespace(api=api, ws=ws, store=store, svc=api.DebateSessions(store, R.Clock(T0)), digest=first.digest)
    view = second.svc.status("sess-1")
    out["restart_view"] = {k: view[k] for k in ("state", "version", "max_rounds", "round")}
    out["restart_role_out_of_order"] = refused(second, second.svc.submit, "sess-1", event(second, "proposer", 1))
    out["restart_attacker_records"] = obs(second, second.svc.submit, "sess-1", event(second, "attacker", 1))
    # LABELLED legacy row: a session written without `findings` and `owner` (the code reads both defensively)
    legacy = system(api, ws)
    row = get(legacy.store, api.SESSIONS, "sess-1")
    del row["findings"], row["owner"]
    put(legacy.store, api.SESSIONS, "sess-1", row)
    out["legacy_status"] = legacy.svc.status("sess-1")
    legacy.svc.submit("sess-1", event(legacy, "proposer", 0))
    out["legacy_attacker_creates_the_registry"] = obs(legacy, legacy.svc.submit, "sess-1", event(legacy, "attacker", 1, payload={
        "findings": [finding("f1", "minor")]}))
    out["legacy_row_after"] = get(legacy.store, api.SESSIONS, "sess-1")
    return out


# ---- G4 --------------------------------------------------------------------------------------------------------------------
def g4_status(api, ws):
    out = {}
    views, phases = {}, {}
    for stage in ("proposal", "critique", "arbitration", "needs_research", "rejected", "exhausted", "expired", "design_approved"):
        s = at_stage(api, ws, stage)
        view = s.svc.status("sess-1")
        views[stage] = view
        phases[stage] = {"state": view["state"], "phase": view["phase"], "terminal": view["terminal"], "version": view["version"]}
        out["status_never_writes_" + stage] = obs(s, s.svc.status, "sess-1")["nothing_written"]
    out["status_views"] = views
    out["status_phases"] = phases
    s = system(api, ws)
    out["status_unknown_session"] = refused(s, s.svc.status, "nope")
    empty = system(api, ws, register=False)
    out["status_unknown_session_empty_store"] = refused(empty, empty.svc.status, "nope")
    out["status_schema"] = s.svc.status("sess-1")["schema"] == api.STATUS_SCHEMA
    c = carried_session(api, ws)
    out["status_carried_blocking"] = c.svc.status("sess-1")
    c.svc.submit("sess-1", event(c, "attacker", 4, round_number=2, payload={"findings": [finding("f3", "minor")]}))
    out["status_carried_with_current_findings"] = c.svc.status("sess-1")
    out["status_owned"] = (lambda o: (o.svc.register(o.valid, REPO, SOURCES, origin="researcher", owner="run-9"), o.svc.status("sess-1"))[1])(
        system(api, ws, register=False))
    # `_safe` shows identities and counts only
    out["safe_direct"] = {"keys": sorted(api.DebateSessions._safe(get(c.store, api.SESSIONS, "sess-1")))}
    out["safe_history_keys"] = sorted({k for h in c.svc.status("sess-1")["history"] for k in h})
    # _by_status
    findings = [{"id": "f1", "round": 1, "severity": "critical", "status": "blocking"},
                {"id": "f2", "round": 1, "severity": "minor", "status": "deferred"},
                {"id": "f3", "round": 2, "severity": "minor", "status": "resolved"},
                {"id": "f4", "round": 2, "severity": "minor", "status": "open"},
                {"id": "f5", "round": 2, "severity": "critical", "status": "blocking"}]
    out["by_status"] = {status: api._by_status(findings, status) for status in ("blocking", "deferred", "resolved", "open", "none")}
    out["by_status_empty"] = api._by_status([], "blocking")
    out["by_status_does_not_mutate"] = {"unchanged": findings == deepcopy(findings)}
    return out


# ---- G5 --------------------------------------------------------------------------------------------------------------------
NOW = "2026-09-16T11:00:00+00:00"


def gate(s, design=None, repository=REPO, base_revision=BASE, plan=None, now=NOW):
    """`design_gate` inside one store transaction (as the operation claim runs it); the session row is read back by digest."""
    design = {"session_id": "sess-1", "packet_digest": s.digest} if design is None else design
    before = R.store_digest(s.store)
    try:
        with s.store.transaction() as tx:
            value = s.api.design_gate(tx, design, repository=repository, base_revision=base_revision,
                                      plan=deepcopy(PLAN) if plan is None else plan, now=now)
        result = {"value": value}
    except Exception as exc:  # the refusal is the characterized result
        result = {"raised": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:200]}
    after = R.store_digest(s.store)
    return {**result, "leaks_value": leak(result), "nothing_written": before == after}


def g5_design_gate(api, ws):
    out = {}
    s = at_stage(api, ws, "design_approved")
    out["gate_approved"] = gate(s)
    out["gate_approved_row_digest"] = R.canonical_digest(get(s.store, api.SESSIONS, "sess-1"))
    # M7 test_mismatched_design_refuses_inside_the_claim... (the gate side)
    out["gate_missing_session"] = gate(s, {"session_id": "ghost", "packet_digest": s.digest})
    out["gate_digest_mismatch"] = gate(s, {"session_id": "sess-1", "packet_digest": "0" * 64})
    out["gate_repository_mismatch"] = gate(s, repository="elsewhere")
    out["gate_base_mismatch"] = gate(s, base_revision="c" * 40)
    out["gate_plan_mismatch_objective"] = gate(s, plan={**PLAN, "objective": "a different plan"})
    out["gate_plan_mismatch_paths"] = gate(s, plan={**PLAN, "allowed_paths": ["docs/other.md"]})
    out["gate_plan_mismatch_criteria"] = gate(s, plan={**PLAN, "acceptance_criteria": ["focused tests pass"]})
    out["gate_plan_equal_is_by_value"] = gate(s, plan=json.loads(json.dumps(PLAN)))
    # M7 test_unapproved_stale_or_expired_sessions_never_authorize_a_claim (every stage)
    stages = {}
    for stage in ("proposal", "critique", "arbitration", "needs_research", "rejected", "exhausted", "expired"):
        t = at_stage(api, ws, stage)
        stages[stage] = {"state": get(t.store, api.SESSIONS, "sess-1")["state"], "gate": gate(t)}
    out["gate_by_state"] = stages
    # M7 test_carried_findings_resolved_in_a_later_round_authorize_the_claim_and_unresolved_rows_never_do
    c = carried_session(api, ws)
    c.svc.submit("sess-1", event(c, "attacker", 4, round_number=2, payload={"findings": []}))
    out["gate_carried_unresolved_session_not_approved"] = gate(c)
    c.svc.submit("sess-1", event(c, "arbiter", 5, round_number=2, payload=arbiter("accept", [
        disposition("f1", "resolved"), disposition("f2", "resolved")])))
    out["gate_carried_resolved_authorizes"] = gate(c)
    # Defence in depth (LABELLED injected fixture, not a reachable state): an approved row still carrying an unresolved finding.
    edit(c, unresolved=[{"round": 1, "finding_id": "f1", "severity": "critical"}])
    out["gate_approved_row_with_unresolved_finding"] = gate(c)
    # M7 test_approved_design_past_its_deadline_refuses_new_claims...: the gate side (the deadline in the session row)
    d = at_stage(api, ws, "design_approved")
    out["gate_now_before_deadline"] = gate(d, now="2029-12-31T23:59:59+00:00")
    out["gate_now_at_deadline"] = gate(d, now=FUTURE)
    out["gate_now_after_deadline"] = gate(d, now="2031-01-01T00:00:00+00:00")
    out["gate_now_offset_form"] = gate(d, now="2030-01-01T08:59:59+09:00")
    edit(d, deadline=PAST)
    out["gate_row_deadline_in_the_past"] = gate(d)
    out["gate_never_writes_expiry"] = {"state": get(d.store, api.SESSIONS, "sess-1")["state"]}
    # LABELLED injected rows: a deadline that is not text, a missing deadline
    e = at_stage(api, ws, "design_approved")
    edit(e, deadline=None)
    out["gate_deadline_none_is_expired"] = gate(e)
    edit(e, deadline=1)
    out["gate_deadline_int_is_expired"] = gate(e)
    # the order of the reasons: digest, needs_research, not approved, unresolved, repository, base, plan, expired
    f = at_stage(api, ws, "needs_research")
    out["order_digest_before_state"] = gate(f, {"session_id": "sess-1", "packet_digest": "0" * 64})
    out["order_needs_research_before_repository"] = gate(f, repository="elsewhere")
    g = at_stage(api, ws, "proposal")
    out["order_not_approved_before_repository"] = gate(g, repository="elsewhere", base_revision="c" * 40)
    h = at_stage(api, ws, "design_approved")
    edit(h, unresolved=[{"round": 1, "finding_id": "f1", "severity": "critical"}])
    out["order_unresolved_before_repository"] = gate(h, repository="elsewhere")
    i = at_stage(api, ws, "design_approved")
    out["order_repository_before_base"] = gate(i, repository="elsewhere", base_revision="c" * 40)
    out["order_base_before_plan"] = gate(i, base_revision="c" * 40, plan={**PLAN, "objective": "other"})
    out["order_plan_before_expiry"] = gate(i, plan={**PLAN, "objective": "other"}, now="2031-01-01T00:00:00+00:00")
    # a design reference without its fields is a KeyError, not a refusal
    out["gate_design_without_session_id"] = gate(i, {"packet_digest": i.digest})
    out["gate_design_without_digest"] = gate(i, {"session_id": "sess-1"})
    # an executor-owned session is authorized the same way and the reference carries the origin
    o = system(api, ws, register=False)
    o.svc.register(o.valid, REPO, SOURCES, origin="researcher", owner="run-9")
    for role, version in (("proposer", 0), ("attacker", 1), ("arbiter", 2)):
        o.svc.submit("sess-1", event(o, role, version), owner="run-9")
    out["gate_owned_approved"] = gate(o)
    # M7 operation-side tests: the Operation/Harness claim is the operation family
    out["m7_v2_manifest_is_strict_and_v1_canonical_form_is_unchanged"] = {
        "unreachable": "needs validate_manifest and the operation manifest schema (the operation family); the gate side is above"}
    out["m7_approved_design_binds_the_v2_claim_and_the_assignment_carries_the_reference"] = {
        "unreachable": "needs Operation.claim over a Harness (outbox, local_cycles); design_gate_approved is the gate's return"}
    out["m7_mismatched_design_refuses_inside_the_claim_with_zero_writes_and_zero_calls"] = {
        "unreachable": "needs Operation.run with NeverExecutor/NeverBudget; each reason code is gate_* above with the store unchanged"}
    out["m7_unapproved_stale_or_expired_sessions_never_authorize_a_claim_operation_side"] = {
        "unreachable": "Operation.run (the operation family); the reason per state is gate_by_state"}
    out["m7_approved_design_past_its_deadline_refuses_new_claims_but_a_finished_operation_replays"] = {
        "unreachable": "the terminal-receipt replay is Operation.run; the deadline refusal is gate_row_deadline_in_the_past"}
    out["m7_v1_manifest_keeps_the_ungated_path"] = {"unreachable": "Operation.claim of a v1 manifest (the operation family)"}
    out["tests_test_dge_postgres"] = {"unreachable": "needs PostgreSQL (PgStore, the disposable fixture is the PG scenarios); the memory-store logic is g2/g3"}
    out["tests_test_dge_cli"] = {"unreachable": "S10 CLI (the dge command and its adapter); the use case it calls is characterized here"}
    return out


GROUPS = (("g1_packet_event", g1_packet_event), ("g2_register", g2_register), ("g3_submit_apply", g3_submit_apply),
          ("g4_status", g4_status), ("g5_design_gate", g5_design_gate))


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
