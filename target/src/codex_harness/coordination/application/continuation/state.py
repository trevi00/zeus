"""Continuation state shared by its objects: bucket names, route vocabulary, the lost-race exception and
the two pure pass helpers.

Layer: application
Context: coordination
Owns: bucket names and read-only helpers (no writes)
Does not own: any write (each object owns its buckets)
Entry points: IntentChanged, policy_frame, guarded
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.domain.continuation import ContinuationRefused, goal_frame, migrated_goals
from codex_harness.kernel.errors import ContractError

# The intake bucket continuation reads (its writer is intake; R4, the S5 read precedent).
BUCKET_BINDINGS = "portfolio_bindings"
BUCKET_POLICIES = "continuation_policies"
BUCKET_INTENTS = "continuation_intents"
BUCKET_PROGRESS = "continuation_progress"
LANE_BINDINGS = "continuation_bindings"
FLEET_JOBS = "fleet_jobs"
FLEET_UNITS = "fleet_units"
BUCKET_RESEARCH_RECEIPTS = "continuation_research_receipts"
BUCKET_RESEARCH_SUPPLEMENTS = "continuation_research_supplements"
BUCKET_CAPACITY_GRANTS = "continuation_capacity_grants"
BUCKET_REQUALIFICATIONS = "continuation_requalifications"
PROMOTIONS = "promotions"
INVESTIGATIONS = "portfolio_investigations"
RESEARCH_DISPATCHES = "research_investigation_dispatches"
RESEARCH_RECOVERIES = "research_dispatch_recoveries"
RESEARCH_SUCCESSORS, RESEARCH_HEADS = "research_dispatch_successors", "research_dispatch_heads"
MAX_LINEAGE = 1000
RESEARCH_RUNS = "autonomous_runs"
EVENT_TRANSITION = "operations.continuation_transition"
EVENT_BLOCKED = "operations.continuation_blocked"
TERMINAL_JOBS = frozenset({"accepted", "rejected", "failed", "exhausted", "unknown"})
MARKERS = frozenset({"unconfirmed", "pending_reconciliation"})
DELIVERY_ACTIVE = "active"
DELIVERY_HALTED = frozenset({"rolled_back", "failed", "blocked"})
# The owner withdrew the bound HostDelivery plan (INV-HOST-DELIVERY-001): a named wait for the owner's
# requalification document, never a pause, a completion or a re-plan of the same candidate.
WITHDRAWN_STAGE = "withdrawn"


class IntentChanged(ContractError):
    """Another controller (or a restart replay) moved the intent first; nothing was written here."""


def policy_frame(tx, row):
    """The registered policy as membership reads it, in the caller's transaction: the pinned goals
    plus the goal migrations of this policy digest's intact stored requalifications (`goal_frame`)."""
    if not isinstance(row, dict):
        return None
    return goal_frame(row["policy"], migrated_goals(row["id"], row["policy_sha256"],
                                                    tx.scan(BUCKET_REQUALIFICATIONS)))


def guarded(result, subject, action) -> str | None:
    """One subject's work; a lost race or a named refusal is recorded, never raised past the tick,
    so one family's outage never stops another family's progress. Returns the skip reason code."""
    try:
        done = action()
    except IntentChanged:
        result["skipped"].append({"subject": subject, "reason_code": "intent_changed"})
        return "intent_changed"
    except ContinuationRefused as exc:
        result["skipped"].append({"subject": subject, "reason_code": exc.reason_code, "next_owner": exc.owner})
        return exc.reason_code
    except Exception as exc:  # a lane store, Git or Fleet outage: the intent stays for the next tick
        result["skipped"].append({"subject": subject, "reason_code": "unavailable",
                                  "error_type": type(exc).__name__})
        return "unavailable"
    if isinstance(done, dict) and "history" in done:
        # A stored intent row is never printed: only its identity, state and route leave.
        done = {"subject": done["id"], "effect": done["state"], "route": done["route"]}
    if done:
        result["actions"].append(done)
    return None
