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
