"""discovery_census: the census read projection of proactive discovery pressure.

Layer: domain
Context: coordination
Owns: the census read projection of INV-DISCOVERY-PRESSURE-001 (W, C, occupancy from Fleet, continuation and backlog rows)
Does not own: the pressure policy and decision (research.domain.discovery_pressure)
Entry points: census
Contracts: INV-DISCOVERY-PRESSURE-001

Split out of M7 `domain/discovery_pressure.py` (SOURCE e38aa722) through named rules (DESIGN-s8 V2e, A/evidence/rebuild/s8/domain-moves-c/transcribe.py): `census` and the two constants it uses are M7's verbatim; only the import lines and this header differ. Research -> coordination is not an edge, so the policy half stays in research and receives the census through a port.
"""
from __future__ import annotations

from codex_harness.coordination.domain.continuation import (
    ADMITTED,
    ADMITTING_ROUTES,
    CONDUCTOR,
    INTENDED,
    PUBLISHED,
)
from codex_harness.coordination.domain.fleet import QUEUED, RESERVING, held_units, job_blockers
from codex_harness.intake.domain.backlog import ITEM_OPEN, ITEM_PENDING, ITEM_UNKNOWN, select
from codex_harness.kernel.usage import exhausted, readable_counts

# A queued job counts as waiting work only when nothing but its lane (or the fleet-wide capacity the caller
# checks) stands between it and admission; every other blocker excludes it.
WAITING_ONLY = frozenset({"lane_busy"})
# Continuation intents that will admit a Fleet operation once their own proofs hold, and a conductor review
# that will take a dispatch unit. This slice cannot prove their readiness read-only, so any of them makes W
# incomplete (T1b adds the readiness seams that turn them into counts).
CONTINUATION_OPEN = frozenset({INTENDED, PUBLISHED, ADMITTED})


def census(*, config, control, jobs: dict, units, plans, intents, continuation_intents, aliases=None,
           ledger=None) -> dict:
    """W, C and the occupancy from ONE consistent read of the authoritative rows (never a monitor list).

    Deduplication: a job is the single identity of its work; a backlog item or continuation intent that
    already names a job contributes nothing of its own. `unknown` counts work that may be dispatchable but
    whose readiness this slice cannot prove; any unknown makes W incomplete. `ledger` is the call-ledger counts
    read just before the transaction (the Fleet runner's own admission input), or None when unreadable."""
    if config is None:
        return {"registered": False}
    capacity = config["max_parallel"]
    paused = bool((control or {}).get("paused"))
    queued = [job for job in jobs.values() if job.get("status") == QUEUED]
    excluded: dict = {}
    waiting = 0
    for job in queued:
        blockers = set(job_blockers(job, jobs, config, aliases))
        if blockers <= WAITING_ONLY:
            waiting += 1
        else:
            for reason in blockers - WAITING_ONLY:
                excluded[reason] = excluded.get(reason, 0) + 1
    backlog_unknown = 0
    for row in plans:
        plan = row.get("plan") or {}
        if not plan.get("enabled"):
            continue
        by_item = {intent["item_id"]: intent for intent in intents if intent.get("plan_id") == plan.get("plan_id")}
        decision = select(plan, by_item, jobs, False)
        for view in decision["progress"]:
            if view["state"] == ITEM_OPEN and view.get("job_id") in jobs:
                continue  # an interrupted enqueue whose job exists: the job is its single identity
            if view["state"] == ITEM_UNKNOWN or (
                    view["state"] in (ITEM_PENDING, ITEM_OPEN) and view["item_id"] not in decision["blocked"]):
                backlog_unknown += 1
    continuation_unknown = 0
    for intent in continuation_intents:
        route, state = intent.get("route"), intent.get("state")
        successor = intent.get("successor_job")
        if isinstance(intent.get("hold"), dict):
            continue  # held (authority drift, a paused family): not dispatchable now, so not waiting work
        if route in ADMITTING_ROUTES and state in CONTINUATION_OPEN and not (successor and successor in jobs):
            continuation_unknown += 1
        elif route == CONDUCTOR and state == INTENDED:
            continuation_unknown += 1
    # Admission also consults the call ledger (outside this transaction) in BOTH accounting modes: finite
    # exhaustion, and under subscription an unreadable ledger refuses admission. The same reading the Fleet runner
    # uses decides it here: unreadable makes W incomplete while jobs wait; exhausted means the waiting jobs are
    # admission-blocked, so they leave W with a named exclusion.
    budget_unknown = 0
    if waiting:
        if not readable_counts(ledger):
            budget_unknown = 1
        elif exhausted(config["budget"], ledger):
            excluded["budget_exhausted"] = waiting
            waiting = 0
    unknown = {"backlog": backlog_unknown, "continuation": continuation_unknown, "budget": budget_unknown}
    return {"registered": True, "paused": paused, "capacity": capacity, "waiting": waiting,
            "complete": not any(unknown.values()), "unknown": unknown, "excluded": excluded,
            "occupancy": {"jobs_reserving": sum(1 for job in jobs.values() if job.get("status") in RESERVING),
                          "units_held": len(held_units(units))}}
