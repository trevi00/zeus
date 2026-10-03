"""The invocation-capacity refusal, observed (OWNER-DECISIONS-S10 #18(b)).

Layer: composition
Owns: CapacityObservingLedger
Does not own: the reservation rows and the refusal (execution), the event catalog and the Observer (observation)
Entry points: CapacityObservingLedger
Contracts: OWNER-DECISIONS-S10 #18(b), OBSERVABILITY-COVERAGE-20261002
"""

from __future__ import annotations

# The ledger's capacity refusal text (`invocation_ledger.py:83`); RunTask maps the same prefix (`run_task.py:84`).
CAPACITY_REFUSAL = "Invocation capacity is reserved by other executions"

EVENT = "operations.capacity_refused"
ATTRIBUTES = {"scope": "invocation_budget", "refusal_reason": "budget_exhausted", "retry_after_seconds": None}


class CapacityObservingLedger:
    """An InvocationLedger that emits `operations.capacity_refused` on the capacity refusal and re-raises the
    SAME exception object; every other exception and every success passes through with no event. No lease, task,
    path or message text enters the attributes. Composition passes the catalog-checking observer."""

    def __init__(self, ledger, observer):
        self.ledger, self.observer = ledger, observer

    @property
    def capacity(self):
        return self.ledger.capacity

    def reserve(self, lease, *, request, budget_seconds, guard=None, stage=None, audit=None):
        try:
            return self.ledger.reserve(lease, request=request, budget_seconds=budget_seconds, guard=guard,
                                       stage=stage, audit=audit)
        except Exception as exc:
            if str(exc).startswith(CAPACITY_REFUSAL):
                self.observer.emit(EVENT, "blocked", attributes=dict(ATTRIBUTES), severity="warning")
            raise

    def reclaim(self):
        return self.ledger.reclaim()

    def settle(self, reservation_id, *, outcome, usage, evidence_ref=None, audit=None):
        return self.ledger.settle(reservation_id, outcome=outcome, usage=usage, evidence_ref=evidence_ref,
                                  audit=audit)

    def abandon(self, reservation_id, reason, audit=None):
        return self.ledger.abandon(reservation_id, reason, audit=audit)

    def summary(self):
        return self.ledger.summary()
