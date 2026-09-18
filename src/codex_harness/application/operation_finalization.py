"""Terminal-operation policy: retire owned unstarted follow-ups, park late messages (INV-OPERATION-FINALIZATION-001).

A bounded operation (INV-OPERATION-001) that ends failed, rejected, exhausted or unknown can leave
runnable residue under its own correlation: a `retry` worker task, a pending `diagnose` decision, a
rework `task.assign` still in the outbox or the bus. That residue makes the next independent cycle
refuse (`foreign_queue` / `foreign_correlation`). This module owns the one policy for both sides:

* `retire(tx, operation)` runs inside the SAME transaction that makes the `operations` row terminal
  and retires only rows the operation provably owns and that never started (tasks queued/retry,
  lead decisions pending/retry for the two fixed roles). Each retirement is an append-only
  disposition plus a `cancelled` row whose message, result, error, failure and attempt history stay
  byte-for-byte as they were (retirement metadata is a separate field; no cancelled attempt is
  invented), advances the durable fence and clears inactive lease metadata. Running rows, live
  leases, blocked rows, rows with an unconfirmed or pending_reconciliation termination marker of
  any attempt (INV-OBSERVATION-001) and rows whose fence moved ahead are reported as unresolved,
  never touched.
* `park(tx, message)` runs inside the Workflow.submit/handle transaction that would otherwise queue
  new work, AFTER the caller validated the message against every older immutable binding of the
  same id (task input hash, inbox hash; `require_identity`). A message for the two roles whose
  exact `operation:<id>` correlation resolves to a terminal operation is persisted as an
  idempotent `operation_message_dispositions` record (same id with another digest is refused) and
  answered with a parked receipt that is never runnable work, regardless of whether the id was
  handled or queued before the operation ended: the old row is evidence, never a reason to make
  the message runnable again or to leave it in the queue.

Ownership is never inferred from free text: the correlation must be exactly `operation:<id>`, the
`operations` row under that id must carry that same correlation, cycle and assignment identity.
No notice, retry, diagnosis, merge, deployment or conductor decision is produced here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from codex_harness.application.execution_fence import advance as advance_fence
from codex_harness.domain.model import ContractError, digest, require, utcnow
from codex_harness.domain.operation import LEAD, WORKER

OPERATIONS = "operations"
DISPOSITIONS = "operation_dispositions"
MESSAGE_DISPOSITIONS = "operation_message_dispositions"
SUMMARY_SCHEMA = "urn:zeus:operation-finalization:1"
PARKED_SCHEMA = "urn:zeus:operation-parked-message:1"
PREFIX = "operation:"
ROLES = frozenset({WORKER, LEAD})
TERMINAL = frozenset({"accepted", "rejected", "failed", "unknown", "exhausted"})
REASON = "operation_terminal"
RETIRABLE = {"tasks": ({"queued", "retry"}, "agent"), "decisions_pending": ({"pending", "retry"}, "actor")}
PROTECTED = {"running": "running", "blocked": "blocked"}
TERMINATIONS = "observation_terminations"
MARKERS = frozenset({"unconfirmed", "pending_reconciliation"})
PARKABLE_TYPES = frozenset({"task.assign", "task.result", "review.result", "hook.required", "execution.notice"})
IDENTITY_ERRORS = {"task.assign": "Conflicting task identity", "execution.notice": "Conflicting execution notice delivery"}


class ParkedMessageConflict(ContractError):
    """The same message id was parked before with different bytes."""


# ----- ownership --------------------------------------------------------------------------
def operation_id(correlation) -> str | None:
    if type(correlation) is not str or not correlation.startswith(PREFIX) or len(correlation) <= len(PREFIX):
        return None
    return correlation[len(PREFIX):]


def owner(tx, correlation) -> dict | None:
    """The `operations` row that owns this exact correlation, or None (absent, malformed, foreign)."""
    key = operation_id(correlation)
    if key is None:
        return None
    row = tx.get(OPERATIONS, key)
    if not (isinstance(row, dict) and row.get("id") == key and row.get("correlation_id") == correlation
            and row.get("cycle_id") == correlation and type(row.get("assignment_message_id")) is str):
        return None
    return row


def terminal_owner(tx, correlation) -> dict | None:
    row = owner(tx, correlation)
    return row if row is not None and row.get("status") in TERMINAL else None


def _correlation(row) -> str | None:
    message = row.get("message") if isinstance(row, dict) else None
    return message.get("correlation_id") if isinstance(message, dict) else None


def _lease_live(row, now: datetime) -> bool | None:
    """True for a lease still in the future, False for none/expired, None when unparsable."""
    until = row.get("lease_until")
    if until is None:
        return False
    try:
        parsed = datetime.fromisoformat(until)
    except (TypeError, ValueError):
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed > now


# ----- finalization (same transaction as the terminal transition) -------------------------
def retire(tx, operation: dict, at: str | None = None) -> dict:
    """Retire owned, never-started rows of a terminal operation; report what stays unresolved.

    Called by Operation._finish after the row was put terminal in `tx`. Raises only on a store
    failure, so a failed transaction leaves neither the terminal status nor any disposition.
    """
    require(isinstance(operation, dict) and operation.get("status") in TERMINAL, "Finalization needs a terminal operation")
    at = at or utcnow()
    now = datetime.fromisoformat(at)
    now = now if now.utcoffset() is not None else now.replace(tzinfo=timezone.utc)
    correlation = operation["correlation_id"]
    summary = {"schema": SUMMARY_SCHEMA, "authority": "cleanup_summary; not the operation outcome",
               "operation_id": operation["id"], "reason_code": REASON, "at": at,
               "retired": {"tasks": [], "decisions_pending": []}, "disposition_ids": [],
               "unresolved": [], "already_terminal": 0, "observed_after_collection": True}
    markers = _termination_markers(tx)
    for bucket, (retirable, role_key) in RETIRABLE.items():
        for row in tx.scan(bucket):
            if _correlation(row) != correlation or row.get(role_key) not in ROLES:
                continue  # foreign, conductor or non-operation rows are never touched
            status = row.get("status")
            if status in PROTECTED:
                summary["unresolved"].append({"bucket": bucket, "id": row["id"], "reason_code": PROTECTED[status]})
                continue
            if status not in retirable:
                summary["already_terminal"] += 1
                continue
            marker = markers.get((bucket, row["id"]))
            if marker is not None:
                # INV-OBSERVATION-001: an attempt whose provider effects are unconfirmed or awaiting
                # reconciliation keeps its row and fence exactly as they are; only an operator resolves it.
                summary["unresolved"].append({"bucket": bucket, "id": row["id"], "reason_code": marker})
                continue
            live = _lease_live(row, now)
            if live is not False:
                summary["unresolved"].append({"bucket": bucket, "id": row["id"],
                                              "reason_code": "live_lease" if live else "lease_unparsable"})
                continue
            generation = row.get("generation") if type(row.get("generation")) is int else 0
            try:
                advance_fence(tx, bucket, row["id"], generation + 1)
            except ContractError:
                summary["unresolved"].append({"bucket": bucket, "id": row["id"], "reason_code": "fence_ahead"})
                continue
            disposition_id = digest(["operation_disposition", operation["id"], bucket, row["id"], generation, status])
            before = {"status": status, "generation": generation, "attempt": row.get("attempt"), "sha256": digest(row)}
            if tx.get(DISPOSITIONS, disposition_id) is None:
                tx.put(DISPOSITIONS, disposition_id, {
                    "id": disposition_id, "operation_id": operation["id"], "operation_status": operation["status"],
                    "bucket": bucket, "row_id": row["id"], "reason_code": REASON, "before": before, "at": at,
                    "authority": "retirement_evidence; not an execution or outcome"})
            # `error`, `failure` and `attempt_outcomes` are the execution's own evidence and stay
            # untouched; no attempt ran here, so none is recorded. Retirement is its own field.
            row.update(status="cancelled", generation=generation + 1, lease_until=None, lease_owner=None,
                       retirement={"disposition_id": disposition_id, "operation_id": operation["id"],
                                   "reason_code": REASON, "before": before, "at": at})
            tx.put(bucket, row["id"], row)
            summary["retired"][bucket].append(row["id"])
            summary["disposition_ids"].append(disposition_id)
    return summary


def _termination_markers(tx) -> dict:
    """(bucket, task_id) -> marker status for every unconfirmed / pending_reconciliation record, any attempt."""
    markers = {}
    for record in tx.scan(TERMINATIONS):
        if not isinstance(record, dict) or record.get("status") not in MARKERS or type(record.get("task_id")) is not str:
            continue
        key = (record.get("bucket", "tasks"), record["task_id"])
        # pending_reconciliation is the stronger claim (the provider was entered); keep it over unconfirmed.
        if markers.get(key) != "pending_reconciliation":
            markers[key] = record["status"]
    return markers


# ----- late messages (same transaction as Workflow.submit / handle) -----------------------
def require_identity(tx, message: dict) -> dict | None:
    """Validate this exact message against every older immutable binding of its id, before parking.

    A task row (assignments) or a workflow inbox row (reports, notices) that was created for this
    id is the original input evidence; a different body under the same id is refused with the
    workflow's existing error, and a parked digest can never override it. Returns the old row of
    the message's own bucket (task or inbox row) so the caller can answer with the old result.
    """
    identity = digest(message)
    # The tasks binding is checked for every type: a differently typed message reusing a task id
    # must not establish a parked digest under that id (INV-OPERATION-FINALIZATION-001).
    old = tx.get("tasks", message["message_id"])
    if old is not None:
        require(old.get("input_hash") == identity, IDENTITY_ERRORS["task.assign"])
    inbox = tx.get("workflow_inbox", message["message_id"])
    if inbox is not None:
        require(inbox.get("hash") == identity, IDENTITY_ERRORS.get(message.get("type"), "Conflicting report identity"))
    return old if old is not None else inbox


def park(tx, message: dict) -> dict | None:
    """Park a validated, authorized message of a terminal operation; None when the policy does not apply.

    Conductor recipients, non-operation correlations, unknown or active operations and other
    message types keep the existing workflow path. The stored record holds the original six-W
    message and its digest; a replay returns the identical receipt; a different body under the
    same id is refused. Whether the id was queued or handled before the operation ended does not
    matter: the older row stays untouched and the message is parked so a consumer can ACK it.
    """
    who = message.get("who") if isinstance(message.get("who"), dict) else {}
    if who.get("recipient") not in ROLES or message.get("type") not in PARKABLE_TYPES:
        return None
    operation = terminal_owner(tx, message.get("correlation_id"))
    if operation is None:
        return None
    require_identity(tx, message)  # the older binding always wins over a new parked digest
    key = digest(["operation_message_disposition", operation["id"], message["message_id"]])
    body = digest(message)
    existing = tx.get(MESSAGE_DISPOSITIONS, key)
    if existing is not None:
        if existing.get("digest") != body:
            raise ParkedMessageConflict("Conflicting parked message identity: " + message["message_id"])
        return _receipt(existing)
    record = {"id": key, "schema": PARKED_SCHEMA, "operation_id": operation["id"], "operation_status": operation["status"],
              "message_id": message["message_id"], "message_type": message["type"], "recipient": who["recipient"],
              "correlation_id": message["correlation_id"], "digest": body, "message": message,
              "reason_code": REASON, "at": utcnow(), "authority": "parked_evidence; never runnable work"}
    tx.put(MESSAGE_DISPOSITIONS, key, record)
    return _receipt(record)


def _receipt(record: dict) -> dict:
    return {"parked": True, "authority": "parked_no_work", "schema": PARKED_SCHEMA, "disposition_id": record["id"],
            "operation_id": record["operation_id"], "message_id": record["message_id"],
            "message_type": record["message_type"], "reason_code": record["reason_code"]}


def is_parked(result) -> bool:
    return isinstance(result, dict) and result.get("parked") is True and type(result.get("disposition_id")) is str


def parkable(store, message: dict) -> dict | None:
    """Read-only preflight for a consumer: the terminal owner of this message, or None."""
    who = message.get("who") if isinstance(message.get("who"), dict) else {}
    if who.get("recipient") not in ROLES or message.get("type") not in PARKABLE_TYPES:
        return None
    with store.transaction() as tx:
        return terminal_owner(tx, message.get("correlation_id"))
