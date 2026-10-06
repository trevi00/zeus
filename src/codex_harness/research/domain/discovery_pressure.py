"""discovery_pressure: the discovery pressure policy, intent and policy validation, sample freshness, the hold rules and the hysteresis decision (`decide`).

Layer: domain
Context: research
Owns: the discovery pressure policy, intent and policy validation, sample freshness, the hold rules and the hysteresis decision (`decide`)
Does not own: the census read projection (coordination.domain.discovery_census, DESIGN-s8 V2e)
Entry points: DiscoveryRefused, DiscoveryPaused, validate_intent, validate_policy, sample_fresh, unrecorded_hold, decide
Contracts: INV-DISCOVERY-PRESSURE-001

Moved from M7 `domain/discovery_pressure.py` (SOURCE e38aa722) through named rules (DESIGN-s8 V2e, A/evidence/rebuild/s8/domain-moves-c/transcribe.py); only the import lines, this header, `census` with its two constants (moved to coordination) and its `__all__` entry differ, every other body is M7's. M7 module docstring:
Proactive discovery pressure (INV-DISCOVERY-PRESSURE-001): pure rules, no IO.

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
from datetime import datetime

from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import digest

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


def sample_fresh(sampled_at, evaluated_at, max_age_seconds) -> bool:
    """Whether an input read BEFORE the transaction is still current once it holds (the Fleet writer lock may
    have made it wait). An unparseable, naive or backwards time is unverifiable, so not fresh."""
    try:
        sampled, evaluated = datetime.fromisoformat(sampled_at), datetime.fromisoformat(evaluated_at)
    except (TypeError, ValueError):
        return False
    # Two naive times subtract without error in Python, so awareness is checked explicitly (only a mixed pair raises).
    if sampled.utcoffset() is None or evaluated.utcoffset() is None:
        return False
    age = (evaluated - sampled).total_seconds()
    return 0 <= age <= max_age_seconds


# census: coordination.domain.discovery_census (DESIGN-s8 V2e); the research application receives it through a port.


def unrecorded_hold(detail: str) -> dict:
    """The hold for an evaluation that could not complete (a store read, a malformed registry, the mandatory
    audit or the commit failed): proactive discovery waits as unknown pressure, and nothing is claimed as
    recorded because the transaction rolled back."""
    return {"schema": ROW_SCHEMA, "recorded": False, "decision": HOLD, "reason_code": "pressure_unknown",
            "detail": detail, "hysteresis_state": None, "waiting": None}


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
           "HOLD", "INTENTS", "KEY", "PAUSED", "POLICY_SCHEMA", "PROACTIVE", "ROW_SCHEMA", "decide",
           "sample_fresh", "unrecorded_hold", "validate_intent", "validate_policy"]
