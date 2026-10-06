"""Claim one pending lead/conductor decision for an actor: fence, lease and clock pin before any provider.

Layer: application
Context: coordination
Owns: claim_decision (M7 `Executor.decide_one`'s claim transaction, moved in S4 unchanged: lead decision Option A;
    per REBUILD-DESIGN-v2 §2.4/§2.6 coordination claims and ReviewDecisions receives the claimed lease)
Does not own: running the decision (review.ReviewDecisions), recovery evidence (injected `recovery`), ticket
    binding (intake, injected), threshold-review exhaustion (research, injected)
Entry points: claim_decision
Contracts: INV-EXECUTION-IDENTITY-001, INV-LOCAL-CYCLE-001, INV-TICKET-001

The owner id is the caller's (M7 drew it with uuid4 at the start of decide_one); clocks are injected (R-D).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from codex_harness.coordination.application.execution_budget import (
    aware_time,
    block_execution,
    deadline_time,
    retry_limit,
)
from codex_harness.coordination.application.execution_fence import advance as advance_fence
from codex_harness.coordination.application.execution_notices import record as execution_notice
from codex_harness.coordination.application.execution_time import (
    ExecutionTimeError,
    active,
    contain_with_notice,
    pin_clock,
    running,
)
from codex_harness.coordination.application.workflow import check_expected, require_expected
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.policy import POLICY


def _no_threshold_reviews(tx, row):
    raise ContractError("Threshold review exhaustion is not wired")


def claim_decision(store, org, agent: str, owner: str, expected: dict | None = None, *, recovery, ticket_binding,
                   TicketSuperseded, threshold_exhausted=_no_threshold_reviews, clock=None, monotonic=None):
    """The claimed decisions_pending row (status running, fenced, pinned), or None when nothing is claimable."""
    now = aware_time(clock=clock)
    decision = None
    with store.transaction() as tx:
        check_expected(tx, "decisions_pending", expected)
        live = running(tx, org, clock=clock, monotonic=monotonic)
        if len(live) >= POLICY.max_active_executions or any(row.get("agent", row.get("actor")) == agent for row in live):
            return None
        for row in tx.scan("decisions_pending"):
            if row["actor"] != agent or row["status"] not in {"pending", "running", "retry"}:
                continue
            now = aware_time(clock=clock)
            if row['status'] == 'running':
                try:
                    if active(row, 'decisions_pending', now, monotonic=monotonic):
                        continue
                except ExecutionTimeError as exc:
                    contain_with_notice(tx, org, row, 'decisions_pending', exc.reason, now, exc.observation)
                    continue
            try:
                recovery.validate_decision(tx, row)
            except ContractError:
                block_execution(tx, row, 'decisions_pending', 'RecoveryContextChanged', now, org)
                continue
            try:
                ticket_binding(tx, row["input"])
            except TicketSuperseded as exc:
                row.update(status="superseded", error=str(exc), completed_at=utcnow(clock))
                tx.put("decisions_pending", row["id"], row)
                execution_notice(tx, org, row, 'decisions_pending', 'ticket_superseded', now.isoformat())
                continue
            try:
                deadline = deadline_time(row.get('execution_deadline'))
            except ContractError:
                block_execution(tx, row, 'decisions_pending', 'InvalidExecutionDeadline', now, org)
                continue
            if deadline is not None and deadline <= now:
                row.update(status='expired', error='deadline exceeded')
                tx.put('decisions_pending', row['id'], row)
                execution_notice(tx, org, row, 'decisions_pending', 'deadline_exceeded', now.isoformat())
                continue
            try:
                limit = retry_limit(tx, row, "decisions_pending", None, now, org)
            except ContractError:
                block_execution(tx, row, "decisions_pending", "InvalidRetryBudget", now, org)
                continue
            if limit is None:
                continue
            if row["attempt"] >= limit:
                row.update(status='failed', error='attempt budget exhausted')
                tx.put("decisions_pending", row["id"], row)
                execution_notice(tx, org, row, 'decisions_pending', 'budget_exhausted', now.isoformat())
                if row['phase'] == 'threshold_review':
                    threshold_exhausted(tx, row)
                continue
            now = aware_time(clock=clock)
            if deadline is None:
                # Pin the remaining retry window once; restarts do not replenish it.
                deadline = now + timedelta(seconds=POLICY.decision_seconds * (limit - row['attempt']))
                row['execution_deadline'] = deadline.isoformat()
            if deadline is not None and deadline <= now:
                contain_with_notice(tx, org, row, 'decisions_pending', 'deadline_exceeded', now)
                continue
            require_expected(row, expected)  # before the fence, the lease and any provider entry
            try:
                advance_fence(tx, 'decisions_pending', row['id'], row.get("generation", 0) + 1, owner, clock=clock)
            except ContractError:
                block_execution(tx, row, 'decisions_pending', 'ExecutionGenerationRegressed', now, org)
                continue
            row.update(status="running", owner=owner, attempt=row["attempt"] + 1,
                       lease_owner=owner, generation=row.get("generation", 0) + 1,
                       lease_until=min(now + timedelta(seconds=1200), deadline).isoformat()
                       if deadline is not None else (now + timedelta(seconds=1200)).isoformat())
            pin_clock(row, 'decisions_pending', now, datetime.fromisoformat(row['lease_until']), clock=clock,
                      monotonic=monotonic)
            tx.put("decisions_pending", row["id"], row)
            decision = row
            break
    return decision
