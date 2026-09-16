"""Research-bound design control (INV-DGE-001): packet/event validation, the operator-submitted
state machine on MemoryStore and the v2 operation claim gate. Every packet, event and clock here is
a labelled fixture; no model, git or provider runs."""
import json
import threading
from copy import deepcopy

import pytest

from codex_harness.adapters.providers import packaged_policy
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.dge import DebateSessions, DgeRefused
from codex_harness.application.operation import DesignGateRefused, Operation, OperationRefused
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.dge import (
    EventError,
    PacketError,
    packet_digest,
    source_binding,
    validate_event,
    validate_packet,
)
from codex_harness.domain.model import ContractError
from codex_harness.domain.operation import ManifestError, validate_manifest

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
REPO = "r"
PLAN = {"objective": "Implement the gate " + CANARY, "acceptance_criteria": ["focused tests pass", "ruff passes"],
        "allowed_paths": ["src/codex_harness/domain/dge.py"]}
FUTURE = "2030-01-01T00:00:00+00:00"
PAST = "2020-01-01T00:00:00+00:00"
T0 = "2026-09-16T10:00:00+00:00"


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


def event(role, version, round_number=1, payload=None, digest_value=None, event_id=None, **extra):
    payloads = {"proposer": {"summary": "bind approval to the exact plan", "claim_ids": ["c1"]},
                "attacker": {"findings": []},
                "arbiter": {"verdict": "accept", "rationale": "structure holds", "dispositions": [], "research_question": None}}
    return {"schema": "urn:zeus:debate-event:1", "id": event_id or f"{role}-{round_number}-{version}",
            "expected_version": version, "packet_digest": digest_value or DIGEST, "round": round_number, "role": role,
            "payload": payload if payload is not None else payloads[role], **extra}


VALID = validate_packet(packet())
DIGEST = packet_digest(VALID)
SOURCES = [{"id": "s1", "path": "docs/contracts.md", "sha256": "b" * 64, "bytes": 10}]  # fixture: Git-verified shape


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def sessions(store=None, clock=None):
    return DebateSessions(store or MemoryStore(), clock or Clock())


def registered(clock=None, doc=None):
    svc = sessions(clock=clock)
    valid = validate_packet(doc) if doc else VALID
    svc.register(valid, REPO, SOURCES)
    return svc, packet_digest(valid)


def finding(fid="f1", severity="minor", criterion="focused tests pass"):
    return {"id": fid, "criterion": criterion, "severity": severity, "scenario": "a stale row wins", "claim_ids": ["c1"]}


def arbiter(verdict, dispositions=(), question=None):
    return {"verdict": verdict, "rationale": "recorded operator decision", "dispositions": list(dispositions),
            "research_question": question}


# ----- packet ---------------------------------------------------------------------------------
@pytest.mark.parametrize("field, value", [
    ("schema", "urn:zeus:research-packet:2"), ("id", "../x"), ("base_revision", "abc"), ("extra", 1), ("topic", ""),
    ("exclusions", "no merge"), ("plan.allowed_paths", []), ("plan.extra", 1), ("questions", []),
    ("questions", [{"id": "q1", "question": "x", "blocking": 1, "status": "answered", "claim_ids": ["c1"]}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": True, "status": "unknown", "claim_ids": []}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "answered", "claim_ids": []}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "answered", "claim_ids": ["c2"]}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "answered", "claim_ids": ["nope"]}]),
    ("questions", [{"id": "q1", "question": "x", "blocking": False, "status": "open", "claim_ids": ["c1"]}]),
    ("sources", []), ("sources", [{"id": "s1", "path": "../x", "sha256": "b" * 64, "locator": "l", "revision": "r", "read_scope": "s"}]),
    ("sources", [{"id": "s1", "path": ".git/config", "sha256": "b" * 64, "locator": "l", "revision": "r", "read_scope": "s"}]),
    ("sources", [{"id": "s1", "path": "docs/a.md", "sha256": "B" * 64, "locator": "l", "revision": "r", "read_scope": "s"}]),
    ("sources", [{"id": "s1", "path": "docs/a.md", "sha256": "b" * 64, "locator": "l", "revision": "r"}]),
    ("claims", [{"id": "c1", "kind": "fact", "text": "t", "source_ids": []}]),
    ("claims", [{"id": "c1", "kind": "fact", "text": "t", "source_ids": ["missing"]}]),
    ("claims", [{"id": "c1", "kind": "guess", "text": "t", "source_ids": ["s1"]}]),
    ("claims", [{"id": "c1", "kind": "fact", "text": "t", "source_ids": ["s1"]}, {"id": "c1", "kind": "fact", "text": "t", "source_ids": ["s1"]}]),
    ("limits.max_rounds", 0), ("limits.max_rounds", 5), ("limits.max_rounds", True), ("limits.max_rounds", "2"),
    ("limits.deadline", "2030-01-01T00:00:00"), ("limits.deadline", "soon"), ("limits.deadline", 1),
    ("supersedes", "sess-0"), ("research_reason", "why"), ("supersedes", "sess-1")])
def test_packet_refuses_schema_type_reference_boolean_digest_and_deadline_faults(field, value):
    document = packet()
    if field == "supersedes" and value == "sess-1":
        document["research_reason"] = "answers the prior question"
    else:
        outer, _, inner = field.partition(".")
        if inner:
            document[outer][inner] = value
        else:
            document[outer] = value
    with pytest.raises(PacketError) as info:
        validate_packet(document)
    assert CANARY not in str(info.value)


def test_packet_normalizes_deadline_to_utc_and_digest_is_deterministic():
    assert VALID["limits"]["deadline"] == "2030-01-01T00:00:00+00:00" and VALID["plan"] == PLAN
    assert packet_digest(validate_packet(packet())) == DIGEST
    assert packet_digest(validate_packet(packet(**{"limits.deadline": "2030-01-01T00:00:00Z"}))) == DIGEST, "same instant, same digest"
    assert packet_digest(validate_packet(packet(topic="other"))) != DIGEST
    assert validate_packet(packet(claims=[{"id": "c1", "kind": "inference", "text": "t", "source_ids": ["s1"]}]))["claims"][0]["kind"] == "inference"


def test_source_binding_requires_regular_blob_and_exact_bytes():
    import hashlib
    data = b"# contracts\n"
    source = {"id": "s1", "path": "docs/contracts.md", "sha256": hashlib.sha256(data).hexdigest()}
    assert source_binding(source, "100644", data) == {**source, "bytes": len(data)}
    for mode in ("120000", "040000", "160000", "100755", None):
        with pytest.raises(PacketError, match="not a regular"):
            source_binding(source, mode, data)
    with pytest.raises(PacketError, match="do not match"):
        source_binding(source, "100644", data + b"x")


# ----- register ---------------------------------------------------------------------------------
def test_register_is_idempotent_for_same_digest_and_refuses_conflict_expiry_and_unverified_sources():
    svc = sessions()
    first = svc.register(VALID, REPO, SOURCES)
    assert first["cached"] is False and first["session"]["state"] == "proposal" and first["session"]["version"] == 0
    assert first["session"]["origin"] == "operator_submitted" and first["session"]["round"] == 1
    assert svc.register(deepcopy(VALID), REPO, SOURCES)["cached"] is True
    with pytest.raises(DgeRefused, match="packet_conflict"):
        svc.register(validate_packet(packet(topic="changed")), REPO, SOURCES)
    with pytest.raises(DgeRefused, match="packet_conflict"):
        svc.register(VALID, "other-repository-digest", SOURCES)
    with pytest.raises(DgeRefused, match="source_verification_incomplete"):
        sessions().register(VALID, REPO, [])
    with pytest.raises(DgeRefused, match="source_verification_incomplete"):
        sessions().register(VALID, REPO, [{**SOURCES[0], "sha256": "c" * 64}])
    with pytest.raises(DgeRefused, match="packet_expired"):
        sessions().register(validate_packet(packet(**{"limits.deadline": PAST})), REPO, SOURCES)
    with pytest.raises(DgeRefused, match="unknown_session"):
        svc.status("nope")
    view = svc.status("sess-1")
    assert CANARY not in json.dumps(view) and view["packet_digest"] == DIGEST and view["phase"] == "proposer"
    assert view["counts"] == {"events": 0, "deferred": 0, "unresolved": 0, "sources_verified": 1}
    assert "not implemented" in view["remaining"] and "attestations" in view["trust"]


# ----- events -----------------------------------------------------------------------------------
@pytest.mark.parametrize("field, value", [
    ("schema", "x"), ("id", ""), ("expected_version", -1), ("expected_version", True), ("expected_version", "0"),
    ("packet_digest", "x"), ("round", 0), ("round", 5), ("role", "critic"), ("payload", []), ("extra", 1)])
def test_event_envelope_is_strict(field, value):
    with pytest.raises(EventError):
        validate_event(event("proposer", 0, **{field: value}) if field == "extra" else {**event("proposer", 0), field: value})


def test_three_events_approve_the_design_and_replays_are_idempotent():
    svc, _ = registered()
    first = svc.submit("sess-1", event("proposer", 0))
    assert first["status"] == "recorded" and first["outcome"] == {"state": "critique", "round": 1, "version": 1}
    replay = svc.submit("sess-1", event("proposer", 0))
    assert replay["status"] == "duplicate" and replay["event_digest"] == first["event_digest"]
    assert svc.status("sess-1")["version"] == 1, "the replay wrote nothing"
    with pytest.raises(DgeRefused, match="event_conflict"):
        svc.submit("sess-1", event("proposer", 0, payload={"summary": "different", "claim_ids": ["c1"]}))
    with pytest.raises(DgeRefused, match="stale_version"):
        svc.submit("sess-1", event("attacker", 0))
    svc.submit("sess-1", event("attacker", 1, payload={"findings": [finding("f1", "minor")]}))
    done = svc.submit("sess-1", event("arbiter", 2, payload=arbiter("accept", [
        {"finding_id": "f1", "decision": "deferred", "reason": "tracked follow-up"}])))
    assert done["outcome"]["state"] == "design_approved" and done["session"]["terminal"] is True
    view = svc.status("sess-1")
    assert view["counts"] == {"events": 3, "deferred": 1, "unresolved": 0, "sources_verified": 1}
    assert view["decision_event_id"] == "arbiter-1-2" and [h["role"] for h in view["history"]] == ["proposer", "attacker", "arbiter"]
    assert CANARY not in json.dumps(view) and "summary" not in json.dumps(view)
    with pytest.raises(DgeRefused, match="session_terminal"):
        svc.submit("sess-1", event("proposer", 3, round_number=2))
    with svc.store.transaction() as tx:
        rows = tx.scan("dge_events")
    assert [r["role"] for r in rows] == ["arbiter", "attacker", "proposer"] and all(r["origin"] == "operator_submitted" for r in rows)


@pytest.mark.parametrize("role, version, code", [
    ("attacker", 0, "role_out_of_order"), ("arbiter", 0, "role_out_of_order")])
def test_role_order_is_strict_from_the_first_event(role, version, code):
    svc, _ = registered()
    with pytest.raises(DgeRefused, match=code):
        svc.submit("sess-1", event(role, version))
    assert svc.status("sess-1")["version"] == 0


def test_proposer_cannot_skip_the_attacker_and_mismatched_digest_round_or_session_refuse():
    svc, _ = registered()
    svc.submit("sess-1", event("proposer", 0))
    with pytest.raises(DgeRefused, match="role_out_of_order"):
        svc.submit("sess-1", event("arbiter", 1))
    with pytest.raises(DgeRefused, match="packet_digest_mismatch"):
        svc.submit("sess-1", event("attacker", 1, digest_value="0" * 64))
    with pytest.raises(DgeRefused, match="round_mismatch"):
        svc.submit("sess-1", event("attacker", 1, round_number=2))
    with pytest.raises(DgeRefused, match="unknown_session"):
        svc.submit("sess-9", event("proposer", 0))
    with pytest.raises(EventError):
        svc.submit("sess-1", event("attacker", 1, payload={"findings": [finding(criterion="not a plan item")]}))
    with pytest.raises(EventError):
        svc.submit("sess-1", event("attacker", 1, payload={"findings": [{**finding(), "claim_ids": ["zz"]}]}))
    with pytest.raises(EventError):
        svc.submit("sess-1", event("attacker", 1, payload={"findings": [finding("f1"), finding("f1")]}))
    assert svc.status("sess-1")["version"] == 1, "no refused submission wrote"


@pytest.mark.parametrize("payload, match", [
    (arbiter("accept"), "exactly once"),  # omitted disposition
    (arbiter("accept", [{"finding_id": "f1", "decision": "resolved", "reason": "r"}, {"finding_id": "f1", "decision": "resolved", "reason": "r"}]), "exactly once"),
    (arbiter("accept", [{"finding_id": "f1", "decision": "deferred", "reason": "r"}]), "defer a critical"),
    (arbiter("accept", [{"finding_id": "f1", "decision": "blocking", "reason": "r"}]), "blocking finding"),
    (arbiter("revise", [{"finding_id": "f1", "decision": "resolved", "reason": "r"}], "why?"), "must be null"),
    (arbiter("needs_research", [{"finding_id": "f1", "decision": "blocking", "reason": "r"}]), "concrete research_question"),
    (arbiter("accept", [{"finding_id": "f1", "decision": "resolved", "reason": "r"}, {"finding_id": "zz", "decision": "resolved", "reason": "r"}]), "exactly once"),
    ({"verdict": "accept", "rationale": "r", "dispositions": [{"finding_id": "f1", "decision": "resolved", "reason": "r"}]}, "missing")])
def test_arbiter_refuses_omitted_dispositions_critical_deferral_blocking_accept_and_question_misuse(payload, match):
    svc, _ = registered()
    svc.submit("sess-1", event("proposer", 0))
    svc.submit("sess-1", event("attacker", 1, payload={"findings": [finding("f1", "critical")]}))
    with pytest.raises(EventError, match=match):
        svc.submit("sess-1", event("arbiter", 2, payload=payload))
    assert svc.status("sess-1")["state"] == "arbitration" and svc.status("sess-1")["version"] == 2


def test_revise_opens_the_next_round_and_the_cap_ends_exhausted_without_retry():
    svc, _ = registered()  # max_rounds 2 (fixture)
    svc.submit("sess-1", event("proposer", 0))
    svc.submit("sess-1", event("attacker", 1, payload={"findings": [finding("f1", "critical")]}))
    out = svc.submit("sess-1", event("arbiter", 2, payload=arbiter("revise", [{"finding_id": "f1", "decision": "blocking", "reason": "r"}])))
    assert out["outcome"] == {"state": "proposal", "round": 2, "version": 3} and svc.status("sess-1")["counts"]["unresolved"] == 1
    with pytest.raises(DgeRefused, match="round_mismatch"):
        svc.submit("sess-1", event("proposer", 3, round_number=1))
    svc.submit("sess-1", event("proposer", 3, round_number=2))
    svc.submit("sess-1", event("attacker", 4, round_number=2))
    out = svc.submit("sess-1", event("arbiter", 5, round_number=2, payload=arbiter("revise")))
    assert out["outcome"]["state"] == "exhausted" and svc.status("sess-1")["round"] == 2
    with pytest.raises(DgeRefused, match="session_terminal"):
        svc.submit("sess-1", event("proposer", 6, round_number=3))
    svc2, _ = registered()
    svc2.submit("sess-1", event("proposer", 0))
    svc2.submit("sess-1", event("attacker", 1))
    assert svc2.submit("sess-1", event("arbiter", 2, payload=arbiter("reject")))["outcome"]["state"] == "rejected"


def test_needs_research_stops_and_only_a_matching_replacement_keeps_linkage():
    svc, _ = registered()
    svc.submit("sess-1", event("proposer", 0))
    svc.submit("sess-1", event("attacker", 1, payload={"findings": [finding("f1", "critical")]}))
    out = svc.submit("sess-1", event("arbiter", 2, payload=arbiter(
        "needs_research", [{"finding_id": "f1", "decision": "blocking", "reason": "r"}], "Does PG serialize writers?")))
    assert out["outcome"]["state"] == "needs_research" and svc.status("sess-1")["research_question_present"] is True
    assert "Does PG" not in json.dumps(svc.status("sess-1"))
    answered = {"id": "q2", "question": "Does PG serialize writers?", "blocking": True, "status": "answered", "claim_ids": ["c1"]}
    unanswered = {**answered, "status": "unknown", "blocking": False, "claim_ids": []}

    def replacement(**over):
        base = packet(id="sess-2", supersedes="sess-1", research_reason="answers the blocking question",
                      questions=[packet()["questions"][0], answered])
        base.update(over)
        return validate_packet(base)
    with pytest.raises(DgeRefused, match="supersedes_unknown"):
        svc.register(replacement(supersedes="ghost"), REPO, SOURCES)
    with pytest.raises(DgeRefused, match="supersedes_question_unanswered"):
        svc.register(replacement(questions=[packet()["questions"][0], unanswered]), REPO, SOURCES)
    with pytest.raises(DgeRefused, match="supersedes_plan_mismatch"):
        svc.register(replacement(plan={**PLAN, "objective": "other"}), REPO, SOURCES)
    with pytest.raises(DgeRefused, match="supersedes_not_needs_research"):
        other, _ = registered()
        other.register(replacement(supersedes="sess-1"), REPO, SOURCES)  # prior still in proposal
    fresh = svc.register(replacement(), REPO, SOURCES)
    assert fresh["cached"] is False and fresh["session"]["supersedes"] == "sess-1" and fresh["session"]["version"] == 0
    assert fresh["session"]["round"] == 1 and fresh["session"]["max_rounds"] == 2, "own declared budget, no extension of the prior"
    assert svc.status("sess-1")["state"] == "needs_research" and svc.status("sess-1")["version"] == 3, "prior preserved"
    with pytest.raises(DgeRefused, match="supersedes_already_replaced"):
        svc.register(replacement(id="sess-3"), REPO, SOURCES)


def test_deadline_is_aware_utc_never_refreshed_and_expiry_is_persisted_on_the_refused_mutation():
    clock = Clock()
    svc, _ = registered(clock=clock)
    svc.submit("sess-1", event("proposer", 0))
    clock.now = "2030-01-01T08:59:59+09:00"  # one second before the UTC-normalized deadline (fixture)
    svc.submit("sess-1", event("attacker", 1))
    clock.now = "2030-01-01T00:00:00Z"
    with pytest.raises(DgeRefused, match="packet_expired"):
        svc.submit("sess-1", event("arbiter", 2))
    view = svc.status("sess-1")
    assert view["state"] == "expired" and view["terminal"] is True and view["deadline"] == "2030-01-01T00:00:00+00:00"
    assert view["version"] == 2 and view["history"][-1]["outcome"] == "expired" and view["history"][-1]["event_id"] is None
    clock.now = T0  # a clock that goes backwards does not reopen a terminal session
    with pytest.raises(DgeRefused, match="session_terminal"):
        svc.submit("sess-1", event("arbiter", 2))
    with svc.store.transaction() as tx:
        assert len(tx.scan("dge_events")) == 2


def test_restart_from_the_store_retains_phase_limits_and_version():
    store = MemoryStore()
    first = DebateSessions(store, Clock())
    first.register(VALID, REPO, SOURCES)
    first.submit("sess-1", event("proposer", 0))
    second = DebateSessions(store, Clock())
    view = second.status("sess-1")
    assert view["state"] == "critique" and view["version"] == 1 and view["max_rounds"] == 2 and view["round"] == 1
    with pytest.raises(DgeRefused, match="role_out_of_order"):
        second.submit("sess-1", event("proposer", 1))
    assert second.submit("sess-1", event("attacker", 1))["outcome"]["state"] == "arbitration"


def test_concurrent_submissions_on_memory_store_have_exactly_one_winner():
    svc, _ = registered()
    outcomes, barrier = [], threading.Barrier(4)

    def attempt(n):
        barrier.wait()
        try:
            outcomes.append(("recorded", svc.submit("sess-1", event("proposer", 0, event_id="race-" + str(n)))["status"]))
        except DgeRefused as exc:
            outcomes.append(("refused", exc.reason_code))
    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == [("recorded", "recorded"), ("refused", "stale_version"), ("refused", "stale_version"), ("refused", "stale_version")]
    assert svc.status("sess-1")["version"] == 1 and svc.status("sess-1")["counts"]["events"] == 1


# ----- operation v2 gate ------------------------------------------------------------------------
IDENTITY = {"repository": REPO, "runtime": "d", "runtime_policy": "p", "provider": {"policy_digest": "x", "config_digest": "y"}}
GOAL = {"path": "docs/zeus/operations/GOAL.md", "sha256": "b" * 64, "criterion": "research-bound design control",
        "rationale": "approved design gates generation"}
BOUND_GOAL = {**GOAL, "base_revision": BASE, "bytes": 3}


def manifest_v2(**overrides):
    document = {"schema": "urn:zeus:operation:2", "id": "op-v2", "base_revision": BASE, "goal": dict(GOAL),
                "plan": deepcopy(PLAN), "budget": {"per_host": 4, "total": 8},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2},
                "design": {"session_id": "sess-1", "packet_digest": DIGEST}}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        if inner:
            document[outer][inner] = value
        else:
            document[outer] = value
    return validate_manifest(document, packaged_policy())


class NeverExecutor:
    def execute_one(self, agent, expected=None):
        pytest.fail("provider entry during a refused claim")

    decide_one = execute_one


class NeverBudget:
    def reserve(self, **kwargs):
        pytest.fail("budget reservation during a refused claim")


def approved(clock=None):
    harness = Harness(MemoryStore(), organization())
    svc = DebateSessions(harness.store, clock or Clock())
    svc.register(VALID, REPO, SOURCES)
    svc.submit("sess-1", event("proposer", 0))
    svc.submit("sess-1", event("attacker", 1))
    svc.submit("sess-1", event("arbiter", 2))
    return harness, svc


def test_v2_manifest_is_strict_and_v1_canonical_form_is_unchanged():
    v2 = manifest_v2()
    assert v2["design"] == {"session_id": "sess-1", "packet_digest": DIGEST} and v2["schema"] == "urn:zeus:operation:2"
    v1 = validate_manifest({k: v for k, v in dict(manifest_v2(), schema="urn:zeus:operation:1").items() if k != "design"}, packaged_policy())
    assert "design" not in v1 and set(v1) == {"schema", "id", "base_revision", "goal", "plan", "budget", "claude"}
    for bad in ({"design.session_id": "../x"}, {"design.packet_digest": "X" * 64}, {"design": {"session_id": "s"}},
                {"design": {"session_id": "s", "packet_digest": DIGEST, "extra": 1}}):
        with pytest.raises(ManifestError):
            manifest_v2(**bad)
    with pytest.raises(ManifestError):
        validate_manifest({**manifest_v2(), "schema": "urn:zeus:operation:1"}, packaged_policy())  # v1 with design
    with pytest.raises(ManifestError):
        validate_manifest({k: v for k, v in manifest_v2().items() if k != "design"}, packaged_policy())  # v2 without design


def test_approved_design_binds_the_v2_claim_and_the_assignment_carries_the_reference():
    harness, _ = approved()
    claimed = Operation(harness).claim(manifest_v2(), IDENTITY, BOUND_GOAL)
    assert claimed["cached"] is False and claimed["row"]["design"]["session_id"] == "sess-1"
    assert claimed["row"]["design"]["packet_digest"] == DIGEST and claimed["row"]["design"]["decision_event_id"] == "arbiter-1-2"
    assert "not verified knowledge" in claimed["row"]["design"]["authority"]
    with harness.store.transaction() as tx:
        outbox = tx.scan("outbox")
        assert len(outbox) == 1 and outbox[0]["message"]["what"]["details"]["operation"]["design"] == {"session_id": "sess-1", "packet_digest": DIGEST}
        assert tx.get("local_cycles", "operation:op-v2") is not None
        assert tx.get("dge_sessions", "sess-1")["state"] == "design_approved", "the gate never mutates the session"
    view = Operation(harness).status("op-v2")
    assert view["design"]["session_id"] == "sess-1" and CANARY not in json.dumps(view)
    with pytest.raises(OperationRefused, match="running_residue"):
        Operation(harness).claim(manifest_v2(), IDENTITY, BOUND_GOAL)


@pytest.mark.parametrize("prepare, overrides, identity, code", [
    (lambda h, s: None, {"design.session_id": "ghost"}, IDENTITY, "design_missing"),
    (lambda h, s: None, {"design.packet_digest": "0" * 64}, IDENTITY, "design_digest_mismatch"),
    (lambda h, s: None, {}, {**IDENTITY, "repository": "elsewhere"}, "design_repository_mismatch"),
    (lambda h, s: None, {"base_revision": "c" * 40}, IDENTITY, "design_base_mismatch"),
    (lambda h, s: None, {"plan.objective": "a different plan"}, IDENTITY, "design_plan_mismatch"),
    (lambda h, s: None, {"plan.allowed_paths": ["docs/other.md"]}, IDENTITY, "design_plan_mismatch"),
    (lambda h, s: None, {"plan.acceptance_criteria": ["focused tests pass"]}, IDENTITY, "design_plan_mismatch")])
def test_mismatched_design_refuses_inside_the_claim_with_zero_writes_and_zero_calls(prepare, overrides, identity, code):
    harness, svc = approved()
    prepare(harness, svc)
    operation = Operation(harness, NeverExecutor(), None, None, NeverBudget(), None)
    with pytest.raises(DesignGateRefused, match=code) as info:
        operation.run(manifest_v2(**overrides), identity, BOUND_GOAL)
    assert isinstance(info.value, OperationRefused) and CANARY not in str(info.value)
    with harness.store.transaction() as tx:
        assert tx.scan("operations") == [] and tx.scan("local_cycles") == [] and tx.scan("outbox") == []


@pytest.mark.parametrize("stage, code", [
    ("proposal", "design_not_approved"), ("critique", "design_not_approved"), ("arbitration", "design_not_approved"),
    ("needs_research", "design_needs_research"), ("rejected", "design_not_approved"), ("exhausted", "design_not_approved"),
    ("expired", "design_not_approved")])
def test_unapproved_stale_or_expired_sessions_never_authorize_a_claim(stage, code):
    clock = Clock()
    harness = Harness(MemoryStore(), organization())
    svc = DebateSessions(harness.store, clock)
    svc.register(validate_packet(packet(**{"limits.max_rounds": 1})), REPO, SOURCES)
    digest_value = packet_digest(validate_packet(packet(**{"limits.max_rounds": 1})))
    if stage != "proposal":
        svc.submit("sess-1", event("proposer", 0, digest_value=digest_value))
    if stage not in {"proposal", "critique"}:
        findings = [finding("f1", "critical")] if stage == "needs_research" else []
        svc.submit("sess-1", event("attacker", 1, digest_value=digest_value, payload={"findings": findings}))
    if stage == "needs_research":
        svc.submit("sess-1", event("arbiter", 2, digest_value=digest_value, payload=arbiter(
            "needs_research", [{"finding_id": "f1", "decision": "blocking", "reason": "r"}], "which lock?")))
    elif stage == "rejected":
        svc.submit("sess-1", event("arbiter", 2, digest_value=digest_value, payload=arbiter("reject")))
    elif stage == "exhausted":
        svc.submit("sess-1", event("arbiter", 2, digest_value=digest_value, payload=arbiter("revise")))
    elif stage == "expired":
        clock.now = "2031-01-01T00:00:00+00:00"
        with pytest.raises(DgeRefused, match="packet_expired"):
            svc.submit("sess-1", event("arbiter", 2, digest_value=digest_value))
    assert svc.status("sess-1")["state"] == stage
    operation = Operation(harness, NeverExecutor(), None, None, NeverBudget(), None)
    with pytest.raises(DesignGateRefused, match=code):
        operation.run(manifest_v2(**{"design.packet_digest": digest_value}), IDENTITY, BOUND_GOAL)
    with harness.store.transaction() as tx:
        assert tx.scan("operations") == [] and tx.scan("outbox") == []


def test_approved_design_past_its_deadline_refuses_new_claims_but_a_finished_operation_replays():
    harness, svc = approved()
    row_before = Operation(harness).claim(manifest_v2(), IDENTITY, BOUND_GOAL)["row"]
    with harness.store.transaction() as tx:  # the operation reached a terminal receipt (fixture)
        row = tx.get("operations", "op-v2")
        row.update(status="accepted", lead_accepted=True)
        tx.put("operations", "op-v2", row)
        session = tx.get("dge_sessions", "sess-1")
        session["deadline"] = "2020-01-01T00:00:00+00:00"  # fixture: the debate deadline has passed
        tx.put("dge_sessions", "sess-1", session)
    replay = Operation(harness, NeverExecutor(), None, None, NeverBudget(), None).run(manifest_v2(), IDENTITY, BOUND_GOAL)
    assert replay["cached"] is True and replay["design"] == row_before["design"], "terminal replay is not re-gated"
    with pytest.raises(DesignGateRefused, match="design_expired"):
        Operation(harness).claim(manifest_v2(id="op-v2-later"), IDENTITY, BOUND_GOAL)
    with harness.store.transaction() as tx:
        assert tx.get("dge_sessions", "sess-1")["state"] == "design_approved", "no expiry is written past completion"


def test_v1_manifest_keeps_the_ungated_path():
    harness = Harness(MemoryStore(), organization())
    v1 = validate_manifest({**{k: v for k, v in manifest_v2().items() if k != "design"}, "schema": "urn:zeus:operation:1"}, packaged_policy())
    claimed = Operation(harness).claim(v1, IDENTITY, BOUND_GOAL)
    assert claimed["cached"] is False and claimed["row"]["design"] is None
    with harness.store.transaction() as tx:
        assert "design" not in tx.scan("outbox")[0]["message"]["what"]["details"]["operation"]
    with pytest.raises(ContractError):
        Operation(harness).status("absent")
