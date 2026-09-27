"""Proactive discovery pressure (INV-DISCOVERY-PRESSURE-001): pure rules, no IO.

Proactive external discovery (feed fetches that no current task needs) pauses while enough runnable work
already waits, and resumes once it has drained. W is the deduplicated runnable waiting work, C the effective
dispatch capacity (`max_parallel`, never "free slots"), and a hysteresis band keeps the state between the two
thresholds. The thresholds come from an explicit policy document labelled `suggested_unconfirmed` until the
user confirms them; nothing here holds a numeric default.

Every read is fail-closed for PROACTIVE discovery only: an unregistered or paused Fleet, a missing or invalid
policy, or an incomplete W (work that may be dispatchable but whose readiness this slice cannot prove) holds
proactive discovery with a named reason, and never reads as W = 0. The exempt intents (user requests,
incidents, results of existing work, research a current task needs) never consult pressure at all.
"""
from __future__ import annotations

import math

from codex_harness.domain.continuation import (
    ADMITTED,
    ADMITTING_ROUTES,
    CONDUCTOR,
    INTENDED,
    PUBLISHED,
)
from codex_harness.domain.fleet import QUEUED, RESERVING, held_units, job_blockers
from codex_harness.domain.fleet_backlog import ITEM_OPEN, ITEM_PENDING, ITEM_UNKNOWN, select
from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.usage_policy import exhausted, readable_counts

POLICY_SCHEMA = "urn:zeus:discovery-pressure-policy:1"
ROW_SCHEMA = "urn:zeus:discovery-pressure:1"
BUCKET = "discovery_pressure"
KEY = "proactive"
EVENT_CHANGED = "operations.discovery_pressure_changed"

PROACTIVE = "proactive"
EXEMPT_INTENTS = ("user_request", "incident", "existing_work_result", "task_required")
INTENTS = (PROACTIVE, *EXEMPT_INTENTS)
THRESHOLD_STATUSES = ("suggested_unconfirmed", "confirmed")

ACTIVE, PAUSED = "active", "paused"
ALLOW, HOLD = "allow", "hold"
# A queued job counts as waiting work only when nothing but its lane (or the fleet-wide capacity the caller
# checks) stands between it and admission; every other blocker excludes it.
WAITING_ONLY = frozenset({"lane_busy"})
# Continuation intents that will admit a Fleet operation once their own proofs hold, and a conductor review
# that will take a dispatch unit. This slice cannot prove their readiness read-only, so any of them makes W
# incomplete (T1b adds the readiness seams that turn them into counts).
CONTINUATION_OPEN = frozenset({INTENDED, PUBLISHED, ADMITTED})


class DiscoveryRefused(ContractError):
    """A fixed reason code, never a value."""

    def __init__(self, reason_code: str):
        super().__init__("discovery refused: " + reason_code)
        self.reason_code = reason_code


class DiscoveryPaused(ContractError):
    """Proactive discovery is held by the pressure decision; carries the safe decision only."""

    def __init__(self, decision: dict):
        super().__init__("discovery paused: " + str(decision.get("reason_code")))
        self.decision = decision
        self.reason_code = decision.get("reason_code")


def validate_intent(intent) -> str:
    """No default and no inference: a missing or unknown intent refuses before any IO."""
    if intent is None or intent == "":
        raise DiscoveryRefused("discovery_intent_required")
    if intent not in INTENTS:
        raise DiscoveryRefused("discovery_intent_invalid")
    return intent


def validate_policy(document) -> dict:
    """The explicit threshold document. Missing or invalid is a refusal the evaluator turns into a hold."""
    if not isinstance(document, dict) or document.get("schema") != POLICY_SCHEMA:
        raise DiscoveryRefused("policy_invalid")
    if set(document) != {"schema", "id", "k_pause", "k_resume", "threshold_status", "input_max_age_seconds"}:
        raise DiscoveryRefused("policy_invalid")
    k_pause, k_resume = document["k_pause"], document["k_resume"]
    numeric = all(type(value) in (int, float) and math.isfinite(value) for value in (k_pause, k_resume))
    if not (numeric and 0 <= k_resume < k_pause):
        raise DiscoveryRefused("policy_invalid")
    if document["threshold_status"] not in THRESHOLD_STATUSES:
        raise DiscoveryRefused("policy_invalid")
    age = document["input_max_age_seconds"]
    if not (type(document["id"]) is str and document["id"] and type(age) is int and age > 0):
        raise DiscoveryRefused("policy_invalid")
    return {**document, "digest": digest(document)}


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


def decide(prior: dict | None, observed: dict, policy: dict | None) -> dict:
    """The hysteresis state and the allow/hold decision for proactive discovery.

    The hysteresis memory changes only on a fresh, complete reading that crosses a boundary; a hold for an
    unknown or unavailable input keeps the memory, so a later complete in-band reading returns to it. The
    initial memory is `active` (the un-triggered side), but the first reading is still evaluated."""
    memory = (prior or {}).get("hysteresis_state") or ACTIVE
    if not observed.get("registered"):
        return {"hysteresis_state": memory, "decision": HOLD, "reason_code": "fleet_unregistered"}
    if observed.get("paused"):
        return {"hysteresis_state": memory, "decision": HOLD, "reason_code": "fleet_paused"}
    if policy is None:
        return {"hysteresis_state": memory, "decision": HOLD, "reason_code": "pressure_unknown"}
    capacity = observed.get("capacity")
    if not (type(capacity) is int and capacity > 0):
        return {"hysteresis_state": memory, "decision": HOLD, "reason_code": "pressure_unknown"}
    if not observed.get("complete"):
        return {"hysteresis_state": memory, "decision": HOLD, "reason_code": "pressure_unknown"}
    waiting = observed["waiting"]
    if waiting >= policy["k_pause"] * capacity:
        state = PAUSED
    elif waiting <= policy["k_resume"] * capacity:
        state = ACTIVE
    else:
        state = memory
    return {"hysteresis_state": state, "decision": HOLD if state == PAUSED else ALLOW,
            "reason_code": "pressure_high" if state == PAUSED else "pressure_ok"}


__all__ = ["ACTIVE", "ALLOW", "BUCKET", "DiscoveryPaused", "DiscoveryRefused", "EVENT_CHANGED", "EXEMPT_INTENTS",
           "HOLD", "INTENTS", "KEY", "PAUSED", "POLICY_SCHEMA", "PROACTIVE", "ROW_SCHEMA", "census", "decide",
           "validate_intent", "validate_policy"]
