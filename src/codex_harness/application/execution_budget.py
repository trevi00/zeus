"""Persist observed retry limits; claim parameters cannot rewrite an existing pin."""
from datetime import datetime, timezone

from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.policy import POLICY


def positive_integer(value, name):
    require(type(value) is int and value > 0, name + " must be a positive integer")
    return value


def aware_time(value=None):
    value = datetime.now(timezone.utc) if value is None else value
    require(isinstance(value, datetime) and value.utcoffset() is not None, "Timezone-aware execution time required")
    return value


def deadline_time(value):
    if value is None:
        return None
    require(isinstance(value, str) and bool(value), "Deadline must be a timezone-aware ISO timestamp")
    try:
        return aware_time(datetime.fromisoformat(value))
    except (ValueError, OverflowError) as exc:
        raise ContractError("Deadline must be a timezone-aware ISO timestamp") from exc


def retry_limit(tx, row, bucket, requested, now):
    if requested is not None:
        positive_integer(requested, "Retry limit")
    budget = row.get("retry_budget")
    if budget is None:
        if row["attempt"] > 0:
            block_execution(tx, row, bucket, "UnverifiedLegacyRetryBudget", now)
            return None
        limit = requested if requested is not None else POLICY.max_attempts
        positive_integer(limit, "Retry limit")
        budget = {"max_attempts": limit, "bound_at": now.isoformat(), "version": 1,
                  "origin": "first_claim"}
        row["retry_budget"] = budget
        tx.put(bucket, row["id"], row)
    require(isinstance(budget, dict) and type(budget.get("version")) is int and budget["version"] > 0,
            "Invalid persisted retry budget")
    limit = positive_integer(budget.get("max_attempts"), "Persisted retry limit")
    if requested is not None and requested != limit:
        event = {"type": "execution.retry_budget_conflict", "bucket": bucket, "task_id": row["id"],
                 "budget_version": budget["version"], "pinned": limit, "requested": requested}
        identity = digest(event)
        if tx.get("events", identity) is None:
            tx.put("events", identity, {**event, "at": now.isoformat()})
        return None
    return limit


def block_execution(tx, row, bucket, reason, now):
    event = {"type": "execution.state_blocked", "bucket": bucket, "task_id": row["id"], "reason": reason}
    identity = digest(event)
    if tx.get("events", identity) is None:
        tx.put("events", identity, {**event, "at": now.isoformat()})
    row.update(status="blocked", error=reason)
    tx.put(bucket, row["id"], row)
