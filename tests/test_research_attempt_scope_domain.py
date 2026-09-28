"""INV-RESEARCH-ATTEMPT-SCOPE-001 domain reservations: which existing rows reserve job membership or make a cause
unverifiable. Labelled synthetic FIXTURE rows only; nothing runs."""
from codex_harness.domain.research_attempt_scope import reservations

FAMILIES = [{"id": "fam-a", "family_status": "failed", "reason_code": "evidence_gate_refused"},
            {"id": "fam-b", "family_status": "failed", "reason_code": "other_reason"}]


def test_a_read_only_successor_without_pinned_members_makes_only_its_own_cause_unverifiable():
    found = reservations(dispatches=[], successors=[{"state": "authorized", "investigation": "fam-b"}],
                         recoveries=[], families=FAMILIES)
    assert found == {"reserved": set(), "unverifiable": {("failed", "other_reason")}}, "never every cause"


def test_pinned_members_reserve_and_a_claimed_successor_reserves_nothing_new():
    found = reservations(dispatches=[{"kind": "failure_family", "job_ids": ["j1"], "job_ids_total": 1}],
                         successors=[{"state": "authorized", "investigation": "fam-a", "members": {"job_ids": ["j2"]}},
                                     {"state": "claimed", "investigation": "fam-a", "members": {"job_ids": ["j3"]}}],
                         recoveries=[], families=FAMILIES)
    assert found == {"reserved": {"j1", "j2"}, "unverifiable": set()}


def test_truncated_captures_and_authorized_recoveries_are_unverifiable_for_their_cause():
    found = reservations(dispatches=[{"kind": "failure_family", "job_ids": ["j1"], "job_ids_total": 60,
                                      "family_status": "failed", "reason_code": "evidence_gate_refused"},
                                     {"kind": "audit_progress", "job_ids": None}],
                         successors=[], recoveries=[{"state": "authorized", "investigation": "fam-b"},
                                                    {"state": "claimed", "investigation": "fam-a"}],
                         families=FAMILIES)
    assert found == {"reserved": set(), "unverifiable": {("failed", "evidence_gate_refused"), ("failed", "other_reason")}}


def test_a_fenced_recovery_mid_authorization_makes_its_cause_unverifiable_like_an_authorized_one():
    """FLEET-U2B-SPEC §2 step 6 includes recoveries: a fenced row (assignment quarantined, transport proof pending)
    may still become authorized and recapture its family's current members, so it is never read as disjoint."""
    for state in ("fenced", "authorized"):
        found = reservations(dispatches=[], successors=[], recoveries=[{"state": state, "investigation": "fam-b"}],
                             families=FAMILIES)
        assert found == {"reserved": set(), "unverifiable": {("failed", "other_reason")}}, state
    for state in ("claimed", "refused"):
        found = reservations(dispatches=[], successors=[], recoveries=[{"state": state, "investigation": "fam-b"}],
                             families=FAMILIES)
        assert found == {"reserved": set(), "unverifiable": set()}, state


def test_scope_holdings_read_members_only_from_readable_claims_and_name_the_cause_of_every_unreadable_one():
    """The owner layer's reverse-overlap rule as one pure helper: a scope claim whose job ids are not a list of
    non-empty strings holds its whole cause and contributes no invented job (a string never becomes characters)."""
    from codex_harness.domain.research_attempt_scope import held_jobs, scope_holdings

    cause, other = ("failed", "evidence_gate_refused"), ("failed", "other_reason")
    rows = [{"kind": "attempt_scope", "job_ids": ["j1", "j2"], "family_status": cause[0], "reason_code": cause[1]},
            {"kind": "attempt_scope", "job_ids": "j3", "family_status": other[0], "reason_code": other[1]},
            {"kind": "attempt_scope", "job_ids": [None], "family_status": other[0], "reason_code": other[1]},
            {"kind": "failure_family", "job_ids": ["j9"], "family_status": cause[0], "reason_code": cause[1]}]
    assert scope_holdings(rows) == {"held": {"j1", "j2"}, "unreadable": {other}, "causes": {cause, other}}
    assert held_jobs(rows) == {"j1", "j2"}
    assert scope_holdings([rows[-1]]) == {"held": set(), "unreadable": set(), "causes": set()}, "no scope claim"
