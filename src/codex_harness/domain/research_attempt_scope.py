"""Attempt-scoped research eligibility (INV-RESEARCH-ATTEMPT-SCOPE-001, U2(b), FLEET-U2B-SPEC).

A held research intent names the COMPLETE failed attempt set it was raised on (`research_attempts`). An
opted-in program (`attempt_scope_source`) may claim EXACTLY those attempt jobs under the intent's own identity
`attempt-scope.<intent id>` instead of a whole Portfolio failure family. Nothing historical, concurrent or later
in the family is captured, and the claim can never borrow or release a family's history.

Everything here is policy over dictionaries: no store, clock, Git, network or provider access, and nothing is
ever written from this module. The same functions serve the owner decision and the transactional claim, so the
two can never disagree. Unknown, malformed, ambiguous or truncated relevant rows refuse; they never read as
"eligible" or "disjoint". Values never enter refusal messages; field names do.
"""
from __future__ import annotations

import re

from codex_harness.domain.continuation import (
    ATTEMPT_SCOPE,
    RESEARCH,
    RESEARCH_REQUIRED,
    SHA256,
    TOKEN,
    attempt_scope_id,
    research_attempts,
)
from codex_harness.domain.model import ContractError, digest

SOURCE_NAME = "attempt_scope_source"
KIND = ATTEMPT_SCOPE
FAMILY_KIND = "failure_family"
SOURCE_FIELDS = {"topic", "continuation_policy", "continuation_policy_sha256", "families", "project_ids",
                 "reason_codes"}
SCOPE_SCHEMA = "urn:zeus:research-attempt-scope:1"
SNAPSHOT_SCHEMA = "urn:zeus:research-attempt-scope-snapshot:1"
SCOPE_FIELDS = {"schema", "intent_id", "continuation_policy", "policy_sha256", "family", "family_investigation",
                "attempts", "attempts_sha256"}
MAX_FAMILIES, MAX_PROJECTS, MAX_REASON_CODES = 20, 20, 50
MIN_ATTEMPTS, MAX_ATTEMPTS = 2, 32
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REASON_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
CANDIDATE_PREFIX = "as-"
# The fixed exclusion vocabulary, in the order the rule evaluates it: bounded counts only.
EXCLUSIONS = ("malformed", "state", "policy", "family", "receipted", "insufficient_attempts", "attempt_unavailable",
              "mixed", "reason_code", "project", "family_state", "claimed", "overlap", "overlap_unverifiable")
AUTHORIZED = "authorized"
TERMINAL_PROGRAMS = frozenset({"completed", "blocked"})
TRUST = ("the COMPLETE failed attempt set one held research intent was raised on, captured exactly; a shared "
         "symptom is a hypothesis, never a cause, an incident resolution or an approved repair")


class ScopeRefused(ContractError):
    """A fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("attempt scope refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _list(values, limit: int, pattern, field: str) -> list:
    if not (isinstance(values, list) and 1 <= len(values) <= limit):
        raise ScopeRefused("config_invalid", field)
    for value in values:
        if type(value) is not str or pattern.fullmatch(value) is None:
            raise ScopeRefused("config_invalid", field + "[]")
    if len(set(values)) != len(values):
        raise ScopeRefused("config_duplicate", field)
    return list(values)


def validate_scope_source(document, topic_ids) -> dict:
    """The optional `attempt_scope_source` block of `urn:zeus:research-program:1`: exact keys, bounded, distinct,
    pattern-bound. Present-invalid refuses; it never reads as absent."""
    name = SOURCE_NAME
    if not isinstance(document, dict):
        raise ScopeRefused("config_invalid", name)
    if set(document) != SOURCE_FIELDS:
        raise ScopeRefused("config_fields", name)
    if type(document["topic"]) is not str or document["topic"] not in set(topic_ids):
        raise ScopeRefused("config_invalid", name + ".topic")
    policy, sha = document["continuation_policy"], document["continuation_policy_sha256"]
    if type(policy) is not str or TOKEN.fullmatch(policy) is None:
        raise ScopeRefused("config_invalid", name + ".continuation_policy")
    if type(sha) is not str or SHA256.fullmatch(sha) is None:
        raise ScopeRefused("config_invalid", name + ".continuation_policy_sha256")
    return {"topic": document["topic"], "continuation_policy": policy, "continuation_policy_sha256": sha,
            "families": _list(document["families"], MAX_FAMILIES, TOKEN, name + ".families"),
            "project_ids": _list(document["project_ids"], MAX_PROJECTS, PROJECT_ID, name + ".project_ids"),
            "reason_codes": _list(document["reason_codes"], MAX_REASON_CODES, REASON_CODE, name + ".reason_codes")}


def candidate_identity(intent_id: str) -> str:
    """`as-<full intent id>`: the full id, never a shortened second identity (67 characters for a 64-hex id)."""
    attempt_scope_id(intent_id)     # validates
    return CANDIDATE_PREFIX + intent_id


def _index(rows, key: str):
    """id -> row, or None when an id repeats or a row is malformed (never last-row-wins)."""
    index = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get(key)) is not str:
            return None
        if row[key] in index:
            return None
        index[row[key]] = row
    return index


def _members(row):
    """The complete captured job set of one dispatch or pinned successor, or None when it cannot be proven
    complete (malformed, or a truncated sample)."""
    ids = row.get("job_ids") if isinstance(row, dict) else None
    if not isinstance(ids, list) or not all(type(j) is str and j for j in ids):
        return None
    total = row.get("job_ids_total", len(ids))
    if type(total) is not int or total != len(ids) or row.get("job_ids_truncated"):
        return None
    return set(ids)


def reservations(*, dispatches, successors, recoveries=(), families=()) -> dict:
    """Job membership that is already reserved by a claim, forward direction: every dispatch capture in ANY
    state and kind, plus the pinned members of every authorized, not yet claimed successor. Rows whose
    membership cannot be proven complete are returned by cause (family status, reason) as `unverifiable`;
    a kind without job membership (audit progress) reserves nothing and is never an invented conflict."""
    reserved, unverifiable = set(), set()
    for row in dispatches:
        if not isinstance(row, dict):
            unverifiable.add(None)
            continue
        if row.get("job_ids") is None and row.get("kind") not in (None, FAMILY_KIND, KIND):
            continue    # audit progress and other membership-free kinds
        members = _members(row)
        if members is None:
            unverifiable.add((row.get("family_status"), row.get("reason_code")))
        else:
            reserved |= members
    # An authorized, not yet claimed family recovery will recapture its family's CURRENT members when claimed:
    # that future membership is unknown now, so its cause is unverifiable (never assumed disjoint).
    causes = {row.get("id"): (row.get("family_status"), row.get("reason_code")) for row in families
              if isinstance(row, dict)}
    for row in recoveries:
        if isinstance(row, dict) and row.get("state") == AUTHORIZED:
            unverifiable.add(causes.get(row.get("investigation")))
    for row in successors:
        if not isinstance(row, dict) or row.get("state") != AUTHORIZED:
            continue
        members = row.get("members")
        if members is None:
            # A read-only successor (no pinned set) recaptures its family's current members when claimed, like
            # a recovery: its OWN cause is unverifiable, never every cause.
            unverifiable.add(causes.get(row.get("investigation")))
            continue
        pinned = members.get("job_ids") if isinstance(members, dict) else None
        if not isinstance(pinned, list) or not all(type(j) is str and j for j in pinned):
            unverifiable.add(causes.get(row.get("investigation")))
        else:
            reserved |= set(pinned)
    return {"reserved": reserved, "unverifiable": unverifiable}


def held_jobs(dispatches) -> set:
    """Every job any attempt-scope claim holds, in ANY state (resolved, rejected, failed and unknown included):
    permanently excluded from family, recovery, successor and follow-up claims (risk 3, FLEET-U2B-SPEC §1)."""
    held = set()
    for row in dispatches:
        if isinstance(row, dict) and row.get("kind") == KIND:
            held |= set(row.get("job_ids") or [])
    return held


def scope_claimed(scope: str, *, dispatches, recoveries, heads, successors) -> bool:
    """Any lifecycle row keyed by or naming this scope identity claims it forever."""
    for rows in (dispatches, recoveries, heads, successors):
        for row in rows:
            if isinstance(row, dict) and scope in (row.get("id"), row.get("investigation")):
                return True
    return False


def eligible_attempt_scopes(*, source: dict, policies, intents, receipts, jobs, bindings, investigations,
                            dispatches, recoveries, heads, successors) -> dict:
    """The deterministic attempt-scope rule over ONE consistent read of authoritative rows, with bounded
    exclusion counts in `EXCLUSIONS` order. A candidate is exactly one held intent's complete 2..32 distinct
    attempt jobs, each with one evidence digest, one shared authorized (status, reason) and an immutable
    binding to an allowed project; the matching failure-family row must exist, be unique and undecided (its
    membership is NOT required and never captured); no lifecycle row may exist at the scope identity; and no
    member may be reserved by any existing capture or pinned successor. Nothing is modified."""
    counts = {"scanned": 0, "eligible": 0, **{name: 0 for name in EXCLUSIONS}}
    candidates = []
    policy_rows = [p for p in policies if isinstance(p, dict) and p.get("id") == source["continuation_policy"]]
    job_rows, binding_rows = _index(jobs, "id"), _index(bindings, "job_id")
    intent_rows = [row for row in intents if isinstance(row, dict)]
    ids = [row.get("id") for row in intent_rows]
    receipted = {row.get("id") for row in receipts if isinstance(row, dict)}
    families = [row for row in investigations if isinstance(row, dict) and row.get("kind", FAMILY_KIND) == FAMILY_KIND]
    reserved = reservations(dispatches=dispatches, successors=successors, recoveries=recoveries, families=families)
    for intent in intent_rows:
        if intent.get("route") != RESEARCH or intent.get("policy_id") != source["continuation_policy"]:
            continue    # another route or policy: not this rule's population
        counts["scanned"] += 1

        def exclude(name):
            counts[name] += 1

        if (type(intent.get("id")) is not str or SHA256.fullmatch(intent["id"]) is None or ids.count(intent["id"]) != 1
                or job_rows is None or binding_rows is None):
            exclude("malformed")
            continue
        if intent.get("state") != RESEARCH_REQUIRED:
            exclude("state")
            continue
        if not (len(policy_rows) == 1 and policy_rows[0].get("policy_sha256") == source["continuation_policy_sha256"]
                == intent.get("policy_sha256")):
            exclude("policy")
            continue
        if intent.get("family") not in set(source["families"]):
            exclude("family")
            continue
        if intent["id"] in receipted:
            exclude("receipted")
            continue
        same_policy = [row for row in intent_rows if row.get("policy_id") == intent["policy_id"]]
        try:
            attempts = research_attempts(same_policy, intent)
        except (KeyError, TypeError):
            exclude("malformed")
            continue
        members = [a["job"] for a in attempts]
        if len(set(members)) != len(members):
            exclude("mixed")    # one job with two evidence digests is never collapsed into a smaller set
            continue
        if not MIN_ATTEMPTS <= len(members) <= MAX_ATTEMPTS:
            exclude("insufficient_attempts")
            continue
        if not all(job in job_rows for job in members):
            exclude("attempt_unavailable")
            continue
        causes = {(job_rows[job].get("status"), job_rows[job].get("reason_code")) for job in members}
        if len(causes) != 1:
            exclude("mixed")
            continue
        status, reason = next(iter(causes))
        if type(status) is not str or type(reason) is not str or reason not in set(source["reason_codes"]):
            exclude("reason_code")
            continue
        projects = [(binding_rows.get(job) or {}).get("project_id") for job in members]
        if not all(project in set(source["project_ids"]) for project in projects):
            exclude("project")
            continue
        cause = [row for row in families if row.get("family_status") == status and row.get("reason_code") == reason]
        if len(cause) != 1 or cause[0].get("state") != RESEARCH_REQUIRED or type(cause[0].get("id")) is not str:
            exclude("family_state")     # missing, ambiguous or dispositioned: never "undecided"
            continue
        scope = attempt_scope_id(intent["id"])
        if scope_claimed(scope, dispatches=dispatches, recoveries=recoveries, heads=heads, successors=successors):
            exclude("claimed")
            continue
        if set(members) & reserved["reserved"]:
            exclude("overlap")
            continue
        if (status, reason) in reserved["unverifiable"] or None in reserved["unverifiable"]:
            exclude("overlap_unverifiable")
            continue
        counts["eligible"] += 1
        candidates.append({"investigation": scope, "intent_id": intent["id"],
                           "continuation_policy": intent["policy_id"], "policy_sha256": intent["policy_sha256"],
                           "family": intent["family"], "family_investigation": cause[0]["id"],
                           "family_status": status, "reason_code": reason, "attempts": attempts,
                           "job_ids": sorted(members), "projects": sorted(set(projects))})
    return {"candidates": sorted(candidates, key=lambda c: c["investigation"]), "counts": counts}


def scope_document(candidate: dict) -> dict:
    """The exact `scope` the claim row carries: what was captured and why, digests included."""
    return {"schema": SCOPE_SCHEMA, "intent_id": candidate["intent_id"],
            "continuation_policy": candidate["continuation_policy"], "policy_sha256": candidate["policy_sha256"],
            "family": candidate["family"], "family_investigation": candidate["family_investigation"],
            "attempts": [dict(a) for a in candidate["attempts"]], "attempts_sha256": digest(candidate["attempts"])}


def scope_snapshot(*, candidate: dict, program_id: str, cycle_number: int, topic: str, observed_at: str) -> dict:
    """The immutable bounded source snapshot the council receives for one scope: the exact complete member
    set (never truncated: at most MAX_ATTEMPTS), its digest, the fixed cause codes and the scope binding."""
    ids = sorted(candidate["job_ids"])
    return {"schema": SNAPSHOT_SCHEMA, "kind": KIND, "investigation": candidate["investigation"],
            "program": program_id, "cycle": cycle_number, "topic": topic,
            "family_status": candidate["family_status"], "reason_code": candidate["reason_code"],
            "projects": list(candidate["projects"]), "job_ids": ids, "job_ids_total": len(ids),
            "job_ids_sha256": digest(ids), "job_ids_truncated": False, "scope": scope_document(candidate),
            "observed_at": observed_at, "trust": TRUST}


def scope_rivals(programs, *, program_id: str, reason: str, source: dict) -> list:
    """Other programs that could take the same work: any program not completed or blocked (so paused, active,
    stopped and unknown states are conservative rivals) whose legacy `investigation_source` names the reason,
    or whose `attempt_scope_source` shares the continuation policy and any root family. Never narrowed by
    project. Their historical claims still block overlaps through `reservations` regardless of state."""
    rivals = []
    for row in programs:
        if not isinstance(row, dict) or row.get("id") == program_id or row.get("state") in TERMINAL_PROGRAMS:
            continue
        config = row.get("config") or {}
        legacy = (config.get("investigation_source") or {}).get("reason_codes") or []
        scoped = config.get(SOURCE_NAME) or {}
        if reason in legacy or (scoped.get("continuation_policy") == source["continuation_policy"]
                                and set(scoped.get("families") or []) & set(source["families"])):
            rivals.append(row.get("id"))
    return sorted(str(r) for r in rivals)


def check_scope_capture(dispatch, *, intent_id: str, attempts: list) -> bool:
    """Whether one stored claim is exactly the scope of this intent and these current attempt pairs (the owner
    outcome and the receipt both use it): kind, derived identity, bound intent, attempts and full membership."""
    if not isinstance(dispatch, dict) or dispatch.get("kind") != KIND:
        return False
    scope = dispatch.get("scope")
    members = sorted(a["job"] for a in attempts)
    return (dispatch.get("investigation") == dispatch.get("id") == attempt_scope_id(intent_id)
            and isinstance(scope, dict) and set(scope) == SCOPE_FIELDS and scope.get("intent_id") == intent_id
            and scope.get("attempts") == [dict(a) for a in attempts] and scope.get("attempts_sha256") == digest(attempts)
            and dispatch.get("job_ids") == members and dispatch.get("job_ids_total") == len(members)
            and dispatch.get("job_ids_sha256") == digest(members))


__all__ = ["CANDIDATE_PREFIX", "EXCLUSIONS", "KIND", "SCOPE_FIELDS", "SCOPE_SCHEMA", "SNAPSHOT_SCHEMA", "SOURCE_NAME",
           "ScopeRefused", "candidate_identity", "check_scope_capture", "eligible_attempt_scopes", "held_jobs",
           "reservations", "scope_claimed", "scope_document", "scope_rivals", "scope_snapshot",
           "validate_scope_source"]
