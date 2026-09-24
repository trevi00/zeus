"""INV-MESSAGE-001: isolate poison records, retain at-least-once delivery evidence."""
import inspect
from uuid import uuid4

from codex_harness.domain.model import ContractError, digest, require, utcnow
from codex_harness.ports import MessageDeliveryError, TransportChanged

BASE_COUNTS = ("published", "quarantined", "quarantined_existing", "retry", "skipped", "legacy_sent", "error")
# Ordered read page of the scoped selection walk; it bounds memory per read, never the batch itself.
SELECTION_PAGE = 500


def _quarantine(tx, identity, item, source_hash, reason, delivery, audit=None):
    key = digest({"id": identity, "source_hash": source_hash})
    if tx.get("outbox_quarantine", key) is None:
        tx.put("outbox_quarantine", key, {"id": key, "source_id": identity, "source_hash": source_hash,
               "source": item, "reason": reason, "at": utcnow()})
        tx.put("events", key, {"type": "outbox.quarantined", "outbox_id": identity,
               "evidence_id": key, "error_type": reason, "at": utcnow()})
        if audit is not None:
            # INV-OBSERVATION-001: the quarantine is recorded in the same transaction; the
            # observation carries the reason and identities, never the poison source bytes.
            audit(tx, "general.message_quarantined", "blocked", identity=["outbox_quarantine", key],
                  reason_code=reason, attributes={"outbox_id": identity, "reason": reason, "quarantine_id": key})
    tx.put("outbox_delivery", identity, {**delivery, "id": identity, "status": "quarantined",
           "source_hash": source_hash, "quarantine_id": key, "updated_at": utcnow()})
    return "quarantined", None


def _message_facts(item):
    message = item.get("message") if isinstance(item, dict) else None
    if not isinstance(message, dict):
        return {}
    who = message.get("who") if isinstance(message.get("who"), dict) else {}
    facts = {"message_type": message.get("type"), "recipient": who.get("recipient"),
             "correlation_id": message.get("correlation_id"), "causation_id": message.get("message_id")}
    return {k: v for k, v in facts.items() if type(v) is str and v}


def _correlation(item):
    message = item.get("message") if isinstance(item, dict) else None
    correlation = message.get("correlation_id") if isinstance(message, dict) else None
    return correlation if type(correlation) is str else None


def _in_scope(item, scope):
    """A scoped batch touches only records of exactly this correlation; anything else is left as it
    is (not published, not marked sent, not quarantined) for the default global relay."""
    return scope is None or _correlation(item) == scope


def _selectable(item, scope):
    return isinstance(item, dict) and item.get("sent") is False and _correlation(item) == scope


def _bind_transport(bus):
    """(binding, unavailable error type), read OUTSIDE any transaction (research-dispatch-recovery-001).
    A bus without `transport()`, or whose `publish` cannot take the binding back for its recheck (an
    override with the old signature), is legacy: (None, None), its attempts stay unbound rather than
    claiming a transport nobody rechecked. A binding-capable bus whose identity cannot be read yields
    no binding and the error type: nothing is published."""
    identify = getattr(bus, "transport", None)
    if not callable(identify):
        return None, None
    try:
        rechecks = "transport" in inspect.signature(bus.publish).parameters
    except (TypeError, ValueError):
        rechecks = False
    if not rechecks:
        return None, None
    try:
        binding = identify()
    except MessageDeliveryError as exc:
        return None, type(exc).__name__
    if not (isinstance(binding, dict) and binding and all(value is not None for value in binding.values())):
        return None, "TransportIdentityUnavailable"
    return binding, None


def _failure_evidence(tx, item, identity, attempt, result, audit):
    tx.put("events", attempt["id"], {"type": "outbox." + result, "outbox_id": identity,
           "evidence_id": attempt["id"], "error_type": attempt["error_type"], "at": attempt["finished_at"]})
    if audit is not None:
        facts = _message_facts(item)
        audit(tx, "general.message_delivery_" + result, "failed" if result == "retry" else "unknown",
              identity=["outbox_attempt", attempt["id"], result], severity="warning" if result == "retry" else "error",
              correlation_id=facts.get("correlation_id"), causation_id=facts.get("causation_id"),
              reason_code=attempt["error_type"], attributes={"outbox_id": identity, "attempt_id": attempt["id"],
                                                             "attempt_number": attempt["number"],
                                                             "error_type": attempt["error_type"]})


def _prepare(tx, identity, org, bus, audit=None, scope=None, binding=None, unavailable=None):
    item = tx.get("outbox", identity)
    if not _in_scope(item, scope):
        # Re-read inside the transaction: the scope cannot change between selection and preparation.
        return "out_of_scope", None
    delivery = tx.get("outbox_delivery", identity) or {}
    source_hash = digest(item)
    if delivery.get("status") == "quarantined" and delivery["source_hash"] == source_hash:
        return "quarantined_existing", None
    reason = "InvalidOutboxRecord"
    try:
        require(isinstance(item, dict) and type(item.get("sent")) is bool, "InvalidOutboxRecord")
        # Historical sent flags are not retroactively certified as transport receipts.
        if item["sent"] and not delivery:
            return "legacy_sent", None
        reason = "SchemaInvalid"
        message = bus.validate(item.get("message"))
        reason = "OutboxMessageIdentityMismatch"
        require(message["message_id"] == identity, "OutboxMessageIdentityMismatch")
        reason = "UnauthorizedRoute"
        org.authorize(message)
        message_hash = digest(message)
        reason = "AttemptedMessageIdentityReused"
        require(not delivery.get("bound_message_hash") or delivery["bound_message_hash"] == message_hash,
                "AttemptedMessageIdentityReused")
    except ContractError:
        # Schema errors can contain arbitrary source text; retain that only in the source copy.
        return _quarantine(tx, identity, item, source_hash, reason, delivery, audit)
    if delivery.get("delivered_entry_id"):
        tx.put("outbox", identity, {**item, "sent": True})
        tx.put("outbox_delivery", identity, {**delivery, "status": "delivered", "updated_at": utcnow()})
        return "skipped", None
    # Commit intent before any network call, including the first attempt's content binding.
    attempt_id, at = str(uuid4()), utcnow()
    attempt = {"id": attempt_id, "outbox_id": identity, "message_hash": message_hash,
               "number": delivery.get("attempts", 0) + 1, "started_at": at, "status": "started"}
    delivery = {**delivery, "id": identity, "bound_message_hash": message_hash,
                "source_hash": source_hash, "attempts": attempt["number"], "updated_at": at,
                "last_attempt_id": attempt_id, "status": "publishing"}
    if binding is not None:
        # research-dispatch-recovery-001: the transport this attempt WILL use is committed with the
        # intent, before the network call. Each attempt keeps its own binding; the delivery row keeps
        # the FIRST one, so a later attempt elsewhere is its own record, never a rewrite of history.
        attempt["transport"] = binding
        delivery.setdefault("transport", binding)
    if unavailable is not None:
        # The identity could not be read: nothing is handed to any transport by this attempt.
        attempt.update(status="transport_unavailable", error_type=unavailable, finished_at=at)
        tx.put("outbox_attempts", attempt_id, attempt)
        tx.put("outbox_delivery", identity, {**delivery, "status": "retry"})
        _failure_evidence(tx, item, identity, attempt, "retry", audit)
        return "retry", None
    tx.put("outbox_attempts", attempt_id, attempt)
    tx.put("outbox_delivery", identity, delivery)
    return "prepared", {"identity": identity, "source_hash": source_hash, "attempt_id": attempt_id}


def _publish(tx, prepared, bus, audit=None, scope=None):
    identity, attempt_id = prepared["identity"], prepared["attempt_id"]
    item = tx.get("outbox", identity)
    delivery = tx.get("outbox_delivery", identity)
    attempt = tx.get("outbox_attempts", attempt_id)
    # The content binding already covers a changed correlation; the scope is rechecked explicitly so
    # a scoped publisher can never hand a foreign record to its own transport.
    if delivery["last_attempt_id"] != attempt_id or digest(item) != prepared["source_hash"] or not _in_scope(item, scope):
        tx.put("outbox_attempts", attempt_id, {**attempt, "status": "superseded_before_publish", "finished_at": utcnow()})
        if delivery["last_attempt_id"] == attempt_id:
            tx.put("outbox_delivery", identity, {**delivery, "status": "retry", "updated_at": utcnow()})
        return "skipped", None
    fatal, bound = None, attempt.get("transport")
    try:
        entry_id = bus.publish(item["message"]) if bound is None else bus.publish(item["message"], transport=bound)
        require(isinstance(entry_id, str) and bool(entry_id), "MissingTransportReceipt")
        attempt.update(status="delivered", entry_id=entry_id)
        delivery.update(status="delivered", delivered_entry_id=entry_id)
        tx.put("outbox", identity, {**item, "sent": True})
        result = "published"
    except TransportChanged as exc:
        # The publisher refused before writing: this attempt handed nothing to any transport.
        attempt.update(status="transport_changed_before_publish", error_type=type(exc).__name__)
        delivery.update(status="retry")
        result = "retry"
    except MessageDeliveryError as exc:
        attempt.update(status="retry", error_type=type(exc).__name__)
        delivery.update(status="retry")
        result = "retry"
    except Exception as exc:
        # Unexpected failures are recorded, then re-raised after this transaction commits.
        # Do not label an uncertain post-publish failure as permanently invalid input.
        attempt.update(status="error", error_type=type(exc).__name__)
        delivery.update(status="error")
        result, fatal = "error", exc
    attempt["finished_at"] = utcnow()
    tx.put("outbox_attempts", attempt_id, attempt)
    tx.put("outbox_delivery", identity, delivery)
    if result != "published":
        _failure_evidence(tx, item, identity, attempt, result, audit)
    elif audit is not None:
        # INV-OBSERVATION-001: a transport acknowledgement (stream entry id) is a delivery fact,
        # recorded with the attempt in the same transaction; it is never a task completion.
        facts = _message_facts(item)
        audit(tx, "general.message_published", "succeeded", identity=["outbox_attempt", attempt_id, "published"],
              correlation_id=facts.get("correlation_id"), causation_id=facts.get("causation_id"),
              attributes={"outbox_id": identity, "attempt_id": attempt_id, "attempt_number": attempt["number"],
                          "stream_entry_id": entry_id,
                          **{k: facts[k] for k in ("message_type", "recipient") if k in facts}})
    return result, fatal


def _scoped_rows(tx, scope, limit):
    """At most `limit` UNSENT records of exactly this correlation, independent of the global cursor
    and of unrelated sent history.

    The whole bucket is walked in ordered `entries` pages, so the read cost grows with the size of
    the outbox table. That is acceptable for one bounded batch of a current run; it is not a claim
    of indexed or million-row scalability, and no index change is part of this path.
    """
    rows, after = [], ""
    while len(rows) < limit:
        page = tx.entries("outbox", after, SELECTION_PAGE)
        if not page:
            break
        after = page[-1]["id"]
        for row in page:
            if _selectable(row["body"], scope):
                rows.append(row)
                if len(rows) == limit:
                    break
    return rows


def _scoped_backlog(tx, scope):
    """Every unsent record still in scope after the batch: truthful remaining evidence, uncapped."""
    remaining, after = 0, ""
    while True:
        page = tx.entries("outbox", after, SELECTION_PAGE)
        if not page:
            return remaining
        after = page[-1]["id"]
        remaining += sum(1 for row in page if _selectable(row["body"], scope))


def relay(store, org, bus, limit=100, audit=None, correlation_id=None):
    """Publish one bounded batch of outbox records through the existing prepare/publish transactions.

    `correlation_id` is optional. None keeps the default global background batch: one page from the
    shared cursor, the cursor advance and the `health/outbox` last-batch row. A non-empty
    correlation selects only this run's own UNSENT intents (assignments, results and workflow
    commands), never reads or advances the global cursor, never publishes, marks sent or
    quarantines a foreign record, and returns `remaining`/`unfinished`/`complete` so the caller can
    fail safely on a backlog or a failed delivery instead of treating `examined` as published.
    """
    require(type(limit) is int and 1 <= limit <= 1000, "Outbox batch limit must be 1..1000")
    scope = correlation_id
    if scope is not None:
        require(type(scope) is str and bool(scope.strip()), "Outbox scope must be a non-empty correlation id")
    counts = dict.fromkeys(BASE_COUNTS + (("out_of_scope",) if scope is not None else ()), 0)
    if scope is None:
        with store.transaction() as tx:
            control = tx.get("outbox_control", "relay") or {"cursor": ""}
            expected_cursor = control["cursor"]
            rows = tx.entries("outbox", expected_cursor, limit)
            if not rows:
                rows = tx.entries("outbox", "", limit)
    else:
        with store.transaction() as tx:
            rows = _scoped_rows(tx, scope, limit)
        expected_cursor = None
    # Read once per batch outside every transaction; each publish rechecks it against the bus.
    binding, unavailable = _bind_transport(bus) if rows else (None, None)
    owns_cursor = True
    def advance(tx, identity):
        nonlocal expected_cursor, owns_cursor
        if scope is not None:
            return  # a scoped batch owns no global position; the background relay keeps its cursor
        control = tx.get("outbox_control", "relay") or {"cursor": ""}
        if owns_cursor and control["cursor"] == expected_cursor:
            expected_cursor = identity
            tx.put("outbox_control", "relay", {"cursor": expected_cursor, "at": utcnow()})
        else:
            owns_cursor = False
    for row in rows:
        with store.transaction() as tx:
            result, prepared = _prepare(tx, row["id"], org, bus, audit, scope, binding, unavailable)
            if not prepared:
                counts[result] += 1
                advance(tx, row["id"])
        if not prepared:
            continue
        fatal = None
        with store.transaction() as tx:
            result, fatal = _publish(tx, prepared, bus, audit, scope)
            counts[result] += 1
            advance(tx, row["id"])
        if fatal:
            raise fatal
    if scope is not None:
        # No health row: a scoped batch is one run's own publication, never the global queue's
        # last-batch observation, and must not overwrite it.
        with store.transaction() as tx:
            unfinished = sum(1 for row in rows if _selectable(tx.get("outbox", row["id"]), scope))
            remaining = _scoped_backlog(tx, scope)
        return {"examined": len(rows), "limit": limit, "correlation_id": scope, **counts,
                "unfinished": unfinished, "remaining": remaining, "complete": remaining == 0}
    # These are last-batch counters, not a complete queue census or proof of consumption.
    with store.transaction() as tx:
        tx.put("health", "outbox", {"id": "outbox", "at": utcnow(), "scope": "last_batch",
               "status": "attention" if counts["quarantined"] or counts["quarantined_existing"] or counts["retry"] else "observed",
               "examined": len(rows), "limit": limit, **counts})
    return {"examined": len(rows), "limit": limit, **counts}
