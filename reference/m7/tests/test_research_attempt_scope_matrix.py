"""INV-RESEARCH-ATTEMPT-SCOPE-001 (U2(b) PR-1): finite-matrix discriminators an adversarial review found missing
(FLEET-U2B-SPEC §1, §2 and §6).

* U2B-2 (new half): the strict `attempt_scope_source` block through `domain.research_program.validate_config`
  with the packaged provider policy - exact keys, non-dict, bounded distinct pattern-bound lists (families and
  project_ids <= 20, reason_codes <= 50), a declared topic, the policy id and its plain SHA-256 - each refused
  with its fixed code AND field name; exclusivity with each legacy source (`config_fields`); present-invalid is
  never read as absent. Pin: the absent-source config and the legacy dual-source combination keep their d71febf
  canonical bytes and registration digests.
* U2B-4: `eligible_attempt_scopes` with exactly one exclusion per case - a missing binding (`project`), the
  2..32 distinct-attempt bound at 32 and 33 (`insufficient_attempts`), a duplicate job row and a duplicate
  binding row (`malformed`: neither last- nor first-row-wins) - and the owner decision that shares the rule.
* Rivals (§1 "never narrowed by project"): `scope_rivals` and the owner decision treat a legacy program naming
  the reason for ANOTHER project, and a scoped program sharing the policy and any root family for other
  projects, as rivals in every non-terminal state; completed and blocked programs are not rivals, while the
  captures they stored still block overlaps.

LABELLED synthetic fixtures only: control-store rows are plain dictionaries carrying just the fields the rules
read, and the program config is the shared `test_research_program_fixtures.config` document. Only pure domain
functions run: no store, executor, provider, model, network or Git, and nothing here is evidence of a live run.
"""
from __future__ import annotations

import copy

import pytest
from test_research_program_fixtures import CANARY, config

from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.portfolio import family_id
from codex_harness.domain import owner_actions as do
from codex_harness.domain.continuation import attempt_scope_id
from codex_harness.domain.model import digest
from codex_harness.domain.research_attempt_scope import (
    EXCLUSIONS,
    SOURCE_FIELDS,
    eligible_attempt_scopes,
    scope_rivals,
    scope_snapshot,
    validate_scope_source,
)
from codex_harness.domain.research_program import (
    CONFIG_FIELDS,
    ProgramRefused,
    config_digest,
    validate_config,
)

HEAD = "a" * 40
POLICY = packaged_policy()
NAME = "attempt_scope_source"
POLICY_ID, POLICY_SHA = "policy-1", digest(["labelled-fixture-policy", "matrix"])
ROOT, OTHER_ROOT = "op-b2", "op-other"
STATUS, REASON = "failed", "worker_failed"
CAUSE = family_id(STATUS, REASON)
PROGRAM, RIVAL = "rp-scope", "rp-rival"
NOW = "2026-09-28T00:00:00+00:00"
SOURCE = {"topic": "storage", "continuation_policy": POLICY_ID, "continuation_policy_sha256": POLICY_SHA,
          "families": [ROOT], "project_ids": ["zeus"], "reason_codes": [REASON]}
LEGACY_SOURCE = {"topic": "storage", "project_ids": ["zeus"], "reason_codes": [REASON]}
PROGRESS_SOURCE = {"topic": "storage", "audit_ids": ["audit-1"]}
# Registration identities of the two legacy shapes, computed with this exact scenario at d71febf (before U2(b)).
LEGACY_DIGESTS = {"plain": "bae92c67bfcf89e6ba85dc18b7d2b93386bfb644ca274caef8fc7fbbe4b2375d",
                  "dual": "83dbbd468fde39e3cfca62c87aae8c3677351cf02266e21bbfe35e5f018abfdb"}


# ===== U2B-2: the strict optional source through validate_config ================================================
def refusal(**blocks) -> ProgramRefused:
    with pytest.raises(ProgramRefused) as info:
        validate_config(config(HEAD, **copy.deepcopy(blocks)), POLICY)
    assert CANARY not in str(info.value), "a refusal names a field, never a value"
    return info.value


def _without(key: str) -> dict:
    return {k: v for k, v in SOURCE.items() if k != key}


def _field(field: str, value, code: str = "config_invalid", suffix: str = "") -> tuple:
    return ({**SOURCE, field: value}, code, NAME + "." + field + suffix)


INVALID = {
    # present but not a mapping: never "absent", never the legacy config
    "none": (None, "config_invalid", NAME), "false": (False, "config_invalid", NAME),
    "zero": (0, "config_invalid", NAME), "empty_string": ("", "config_invalid", NAME),
    "empty_list": ([], "config_invalid", NAME), "list_of_block": ([dict(SOURCE)], "config_invalid", NAME),
    "string": ("storage", "config_invalid", NAME),
    # exact keys
    "empty_mapping": ({}, "config_fields", NAME),
    **{"missing_" + key: (_without(key), "config_fields", NAME) for key in sorted(SOURCE)},
    "unknown_key": ({**SOURCE, "note": CANARY}, "config_fields", NAME),
    "legacy_shape": (dict(LEGACY_SOURCE), "config_fields", NAME),
    # the topic must be one this program declares
    "topic_undeclared": _field("topic", "undeclared-" + CANARY),
    "topic_none": _field("topic", None), "topic_list": _field("topic", ["storage"]),
    # the continuation policy id (the existing TOKEN) and its plain SHA-256 representation (never a prefixed form)
    "policy_empty": _field("continuation_policy", ""), "policy_wildcard": _field("continuation_policy", "*"),
    "policy_spaced": _field("continuation_policy", "policy " + CANARY),
    "policy_leading_dash": _field("continuation_policy", "-policy-1"),
    "policy_too_long": _field("continuation_policy", "p" * 101), "policy_int": _field("continuation_policy", 1),
    "digest_short": _field("continuation_policy_sha256", "5" * 63),
    "digest_long": _field("continuation_policy_sha256", "5" * 65),
    "digest_upper": _field("continuation_policy_sha256", "A" * 64),
    "digest_prefixed": _field("continuation_policy_sha256", "sha256:" + "5" * 64),
    "digest_none": _field("continuation_policy_sha256", None),
    "digest_value": _field("continuation_policy_sha256", CANARY),
    # families: nonempty, <= 20, distinct, TOKEN
    "families_empty": _field("families", []), "families_none": _field("families", None),
    "families_string": _field("families", ROOT),
    "families_over_bound": _field("families", ["op-%02d" % i for i in range(21)]),
    "families_wildcard": _field("families", ["*"], suffix="[]"),
    "families_non_string": _field("families", [7], suffix="[]"),
    "families_spaced": _field("families", ["op " + CANARY], suffix="[]"),
    "families_duplicate": _field("families", [ROOT, ROOT], "config_duplicate"),
    # project_ids: nonempty, <= 20, distinct, the existing project id pattern
    "projects_empty": _field("project_ids", []), "projects_none": _field("project_ids", None),
    "projects_over_bound": _field("project_ids", ["p-%02d" % i for i in range(21)]),
    "projects_wildcard": _field("project_ids", ["*"], suffix="[]"),
    "projects_too_long": _field("project_ids", ["p" * 65], suffix="[]"),
    "projects_null_member": _field("project_ids", [None], suffix="[]"),
    "projects_duplicate": _field("project_ids", ["zeus", "zeus"], "config_duplicate"),
    # reason_codes: nonempty, <= 50, distinct, the existing reason pattern
    "reasons_empty": _field("reason_codes", []), "reasons_none": _field("reason_codes", None),
    "reasons_over_bound": _field("reason_codes", ["r-%02d" % i for i in range(51)]),
    "reasons_spaced": _field("reason_codes", ["worker " + CANARY], suffix="[]"),
    "reasons_too_long": _field("reason_codes", ["r" * 81], suffix="[]"),
    "reasons_duplicate": _field("reason_codes", [REASON, REASON], "config_duplicate"),
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_a_present_invalid_scope_source_is_refused_by_code_and_field_and_never_read_as_absent(case):
    """U2B-2 (new): each case breaks exactly one fact of a valid block. The field name (never `root`, never a
    value) proves the block was validated as the attempt-scope source, not rejected as an unknown key."""
    block, code, field = INVALID[case]
    refused = refusal(attempt_scope_source=block)
    assert (refused.reason_code, refused.field) == (code, field), case


@pytest.mark.parametrize("field, values", [("families", ["op-%02d" % i for i in range(20)]),
                                           ("project_ids", ["p-%02d" % i for i in range(20)]),
                                           ("reason_codes", ["r-%02d" % i for i in range(50)])])
def test_each_list_accepts_exactly_its_bound(field, values):
    """U2B-2 (new): the refusal one past each bound is the bound, not a smaller one."""
    block = {**SOURCE, field: values}
    assert validate_config(config(HEAD, attempt_scope_source=copy.deepcopy(block)), POLICY)[NAME] == block


def test_a_valid_scope_source_is_its_own_canonical_block_and_a_new_registration_identity():
    """U2B-2 (new): exact keys in, exact keys out; everything else is the legacy canonical config. List order is
    kept exactly as the legacy `investigation_source` keeps it (FLEET-U2B-SPEC §2 canonical consistency)."""
    plain = validate_config(config(HEAD), POLICY)
    block = {**SOURCE, "families": [OTHER_ROOT, ROOT], "project_ids": ["zeus", "alpha"],
             "reason_codes": [REASON, "a_reason"]}
    opted = validate_config(config(HEAD, attempt_scope_source=copy.deepcopy(block)), POLICY)
    assert opted[NAME] == block and set(opted[NAME]) == SOURCE_FIELDS
    assert {k: v for k, v in opted.items() if k != NAME} == plain
    assert config_digest(opted, "repo-1") != config_digest(plain, "repo-1"), "opting in is a new identity"
    legacy = validate_config(config(HEAD, investigation_source={
        "topic": "storage", "project_ids": ["zeus", "alpha"], "reason_codes": [REASON, "a_reason"]}), POLICY)
    for key in ("project_ids", "reason_codes"):
        assert opted[NAME][key] == legacy["investigation_source"][key], key


EXCLUSIVE = {"investigation": {"investigation_source": LEGACY_SOURCE},
             "audit_progress": {"audit_progress_source": PROGRESS_SOURCE},
             "both": {"investigation_source": LEGACY_SOURCE, "audit_progress_source": PROGRESS_SOURCE}}


@pytest.mark.parametrize("block", [SOURCE, None, {}], ids=["valid", "none", "empty"])
@pytest.mark.parametrize("others", sorted(EXCLUSIVE))
def test_the_scope_source_cannot_coexist_with_either_legacy_source(others, block):
    """U2B-2 (new): a valid, a null and an empty scope block beside either (or both) legacy sources each refuse
    `config_fields` on the scope source; a present key is never skipped as absent to accept the legacy half."""
    refused = refusal(attempt_scope_source=block, **EXCLUSIVE[others])
    assert (refused.reason_code, refused.field) == ("config_fields", NAME)


def test_pin_the_absent_source_and_the_legacy_dual_source_configs_are_unchanged():
    """U2B-2 pin (K): no scope source means no new key and the d71febf registration digest; the legacy
    investigation + audit-progress combination is still accepted, byte for byte, with no scope key added."""
    plain = validate_config(config(HEAD), POLICY)
    assert set(plain) == CONFIG_FIELDS and config_digest(plain, "repo-1") == LEGACY_DIGESTS["plain"]
    dual = validate_config(config(HEAD, **copy.deepcopy(EXCLUSIVE["both"])), POLICY)
    assert dual == {**plain, "investigation_source": LEGACY_SOURCE, "audit_progress_source": PROGRESS_SOURCE}
    assert NAME not in dual and config_digest(dual, "repo-1") == LEGACY_DIGESTS["dual"]


# ===== U2B-4: eligibility, one isolated exclusion per case ======================================================
CANONICAL = validate_scope_source(copy.deepcopy(SOURCE), {"storage"})


def intent(n: int, route: str, state: str, job: str, family: str = ROOT) -> dict:
    return {"id": digest(["labelled-fixture-intent", family, n]), "route": route, "state": state,
            "policy_id": POLICY_ID, "policy_sha256": POLICY_SHA, "family": family, "origin_job": job,
            "evidence_sha256": digest(["labelled-fixture-evidence", job]), "lane": "a",
            "created_at": "2026-09-27T00:00:%02d+00:00" % n}


def world(count: int = 2) -> tuple:
    """`count` failed attempts on distinct jobs: `count - 1` admitted corrections, then the held research intent
    raised on the last one, i.e. the COMPLETE attempt set. Every job is failed/worker_failed and bound to `zeus`;
    the undecided cause row lists unrelated historical members only (its membership is never the capture).
    Returns (the pure rule's rows, the held intent, the attempt job ids)."""
    jobs = ["job-%02d" % n for n in range(1, count + 1)]
    intents = [intent(n, "correction", "admitted", j) for n, j in enumerate(jobs[:-1], start=1)]
    held = intent(count, "research", "research_required", jobs[-1])
    rows = {"policies": [{"id": POLICY_ID, "policy_sha256": POLICY_SHA}], "intents": [*intents, held],
            "receipts": [], "jobs": [{"id": j, "status": STATUS, "reason_code": REASON, "lane": "a"} for j in jobs],
            "bindings": [{"job_id": j, "project_id": "zeus"} for j in jobs],
            "investigations": [{"id": CAUSE, "kind": "failure_family", "state": "research_required",
                                "family_status": STATUS, "reason_code": REASON, "job_ids": ["job-h1", "job-h2"]}],
            "dispatches": [], "recoveries": [], "heads": [], "successors": []}
    return rows, held, jobs


def eligible(rows: dict) -> dict:
    return eligible_attempt_scopes(source=CANONICAL, **rows)


def only(counts: dict, name: str | None) -> None:
    """Exactly one scanned intent and exactly the named exclusion (or eligibility): no other count moves."""
    expected = {"scanned": 1, "eligible": 0 if name else 1, **{n: 0 for n in EXCLUSIONS}}
    if name:
        expected[name] = 1
    assert counts == expected


def _drop_binding(rows, jobs):
    rows["bindings"] = [b for b in rows["bindings"] if b["job_id"] != jobs[-1]]


def _duplicate(bucket: str, key: str, index: int, **fields):
    """A second row with the same id (optionally different): which copy is "right" is unknowable."""
    def change(rows, jobs):
        rows[bucket].append({**next(r for r in rows[bucket] if r[key] == jobs[index]), **fields})
    return change


def _first_row(bucket: str, key: str, index: int, **fields):
    """The duplicate goes FIRST and differs, so a first-row-wins reader would see the changed copy."""
    def change(rows, jobs):
        original = next(r for r in rows[bucket] if r[key] == jobs[index])
        rows[bucket].insert(0, {**original, **fields})
    return change


ISOLATED = {
    "binding_missing": (_drop_binding, "project"),
    "job_row_duplicate_identical": (_duplicate("jobs", "id", -1), "malformed"),
    "job_row_duplicate_other_cause_last": (_duplicate("jobs", "id", 0, reason_code="other_reason"), "malformed"),
    "job_row_duplicate_other_cause_first": (_first_row("jobs", "id", 0, reason_code="other_reason"), "malformed"),
    "binding_row_duplicate_identical": (_duplicate("bindings", "job_id", -1), "malformed"),
    "binding_row_duplicate_other_project_last": (_duplicate("bindings", "job_id", 0, project_id="elsewhere"),
                                                 "malformed"),
    "binding_row_duplicate_other_project_first": (_first_row("bindings", "job_id", 0, project_id="elsewhere"),
                                                  "malformed"),
}


def test_the_ready_pair_is_eligible_with_no_exclusion():
    rows, held, jobs = world()
    found = eligible(rows)
    only(found["counts"], None)
    assert [c["investigation"] for c in found["candidates"]] == [attempt_scope_id(held["id"])]


@pytest.mark.parametrize("case", sorted(ISOLATED))
def test_a_missing_binding_or_a_duplicate_job_or_binding_row_is_one_isolated_exclusion(case):
    """U2B-4 (new): a missing binding for one attempt job is `project`; a repeated job or binding row is
    `malformed` whichever copy comes first and whether or not the copies agree (never last/first-row-wins)."""
    change, name = ISOLATED[case]
    rows, held, jobs = world()
    change(rows, jobs)
    found = eligible(rows)
    assert found["candidates"] == []
    only(found["counts"], name)


def test_exactly_32_distinct_attempts_are_eligible_and_captured_whole():
    """U2B-4 (new): the upper bound is inclusive; the snapshot is the complete set, never a truncated sample."""
    rows, held, jobs = world(32)
    found = eligible(rows)
    only(found["counts"], None)
    [candidate] = found["candidates"]
    assert candidate["job_ids"] == sorted(jobs) and len(candidate["attempts"]) == 32
    assert [a["job"] for a in candidate["attempts"]] == sorted(jobs)
    document = scope_snapshot(candidate=candidate, program_id=PROGRAM, cycle_number=1, topic="storage",
                              observed_at=NOW)
    assert (document["job_ids_total"], document["job_ids_truncated"]) == (32, False)


def test_33_distinct_attempts_are_insufficient_attempts_never_a_truncated_scope():
    rows, held, jobs = world(33)
    found = eligible(rows)
    assert found["candidates"] == []
    only(found["counts"], "insufficient_attempts")


# ----- the owner decision shares the rule ----------------------------------------------------------------------
BUCKETS = {"policies": "continuation_policies", "intents": "continuation_intents",
           "receipts": "continuation_research_receipts", "jobs": "fleet_jobs", "bindings": "portfolio_bindings",
           "investigations": "portfolio_investigations", "dispatches": "research_investigation_dispatches",
           "recoveries": "research_dispatch_recoveries", "heads": "research_dispatch_heads",
           "successors": "research_dispatch_successors"}


def program(config_: dict | None = None, **fields) -> dict:
    row = {"id": PROGRAM, "state": "paused", "cycles": 0, "next_cycle": 1, "active_cycle": None, "adoptions": 0,
           "last_tick_at": None,
           "config": config_ or {"interval_seconds": 3600, "max_cycles": 2, "max_adoptions": 1,
                                 "budget": {"per_host": 10, "total": 20}, NAME: copy.deepcopy(CANONICAL)}}
    row.update(fields)
    return row


def decide(rows: dict, held: dict, jobs: list, *, programs: tuple = ()) -> dict:
    control = {BUCKETS[name]: value for name, value in rows.items()}
    control["research_programs"] = [program(), *programs]
    return do.research_decision(program_id=PROGRAM, investigation=attempt_scope_id(held["id"]),
                                attempts=sorted(jobs), rows=control, room={"ok": True, "remaining": 5}, now=NOW,
                                family_investigation=CAUSE)


@pytest.mark.parametrize("case, count, name", [
    ("binding_missing", 2, "project"), ("job_row_duplicate_identical", 2, "malformed"),
    ("binding_row_duplicate_identical", 2, "malformed"),
    ("binding_row_duplicate_other_project_last", 2, "malformed"),
    ("binding_row_duplicate_other_project_first", 2, "malformed"), ("thirty_three", 33, "insufficient_attempts"),
])
def test_the_owner_decision_names_the_same_isolated_exclusion(case, count, name):
    """U2B-4 (new): the RO-1 scoped decision reaches the shared rule and reports its count, acting on nothing."""
    rows, held, jobs = world(count)
    if case in ISOLATED:
        ISOLATED[case][0](rows, jobs)
    decision = decide(rows, held, jobs)
    assert (decision["act"], decision["reason"]) == (False, "research_scope_not_eligible"), decision
    only(decision["detail"]["counts"], name)


def test_the_owner_decision_acts_on_exactly_32_attempts():
    rows, held, jobs = world(32)
    assert decide(rows, held, jobs)["reason"] == "research_ready_resume_then_tick"


# ===== Rivals: never narrowed by project ========================================================================
def rival(state: str, config_: dict) -> dict:
    return {"id": RIVAL, "state": state, "cycles": 0, "adoptions": 0, "active_cycle": None, "config": config_}


RIVAL_CONFIGS = {
    # a legacy program naming the reason, authorized for a DIFFERENT project only
    "legacy_other_project": {"investigation_source": {"topic": "storage", "project_ids": ["elsewhere"],
                                                      "reason_codes": ["other_reason", REASON]}},
    # a scoped program sharing the policy and the root family, for other projects only
    "scoped_other_projects": {NAME: {**SOURCE, "project_ids": ["elsewhere", "another"]}},
    # sharing the policy and ANY one root family is enough, whatever its projects and reasons
    "scoped_any_root": {NAME: {**SOURCE, "families": [OTHER_ROOT, ROOT], "project_ids": ["elsewhere"],
                               "reason_codes": ["other_reason"]}},
}
LIVE = ["active", "paused", "stopped", "a-state-no-release-knows"]
TERMINAL = ["completed", "blocked"]


@pytest.mark.parametrize("state", LIVE)
@pytest.mark.parametrize("kind", sorted(RIVAL_CONFIGS))
def test_a_live_rival_for_other_projects_is_still_a_rival(kind, state):
    """Rival rule (new, FLEET-U2B-SPEC §1): paused, active, stopped and unknown programs are conservative
    rivals, and a disjoint project list never exempts one - in `scope_rivals` and in the owner decision."""
    other = rival(state, copy.deepcopy(RIVAL_CONFIGS[kind]))
    assert scope_rivals([program(), other], program_id=PROGRAM, reason=REASON, source=CANONICAL) == [RIVAL]
    rows, held, jobs = world()
    decision = decide(rows, held, jobs, programs=(other,))
    assert (decision["act"], decision["reason"]) == (False, "research_competing_program")
    assert decision["detail"]["programs"] == [RIVAL]


@pytest.mark.parametrize("state", TERMINAL)
@pytest.mark.parametrize("kind", sorted(RIVAL_CONFIGS))
def test_a_completed_or_blocked_program_is_no_rival_but_its_stored_capture_still_blocks(kind, state):
    other = rival(state, copy.deepcopy(RIVAL_CONFIGS[kind]))
    assert scope_rivals([program(), other], program_id=PROGRAM, reason=REASON, source=CANONICAL) == []
    rows, held, jobs = world()
    assert decide(rows, held, jobs, programs=(other,))["reason"] == "research_ready_resume_then_tick"
    rows["dispatches"].append({"id": "f" * 64, "investigation": "f" * 64, "kind": "failure_family",
                               "state": "resolved", "family_status": STATUS, "reason_code": REASON,
                               "job_ids": [jobs[-1], "job-h1"], "job_ids_total": 2, "job_ids_truncated": False,
                               "result": "accepted", "program": RIVAL})
    decision = decide(rows, held, jobs, programs=(other,))
    assert decision["reason"] == "research_scope_not_eligible"
    only(decision["detail"]["counts"], "overlap")


def test_the_program_is_never_its_own_rival():
    assert scope_rivals([program()], program_id=PROGRAM, reason=REASON, source=CANONICAL) == []
