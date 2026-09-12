"""INV-MESSAGE-001: isolate poison records, retain at-least-once delivery evidence."""
from uuid import uuid4

from codex_harness.domain.model import ContractError, digest, require, utcnow
from codex_harness.ports import MessageDeliveryError


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


def _prepare(tx, identity, org, bus, audit=None):
    item = tx.get("outbox", identity)
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
    tx.put("outbox_attempts", attempt_id, attempt)
    tx.put("outbox_delivery", identity, delivery)
    return "prepared", {"identity": identity, "source_hash": source_hash, "attempt_id": attempt_id}


def _publish(tx, prepared, bus, audit=None):
    identity, attempt_id = prepared["identity"], prepared["attempt_id"]
    item = tx.get("outbox", identity)
    delivery = tx.get("outbox_delivery", identity)
    attempt = tx.get("outbox_attempts", attempt_id)
    if delivery["last_attempt_id"] != attempt_id or digest(item) != prepared["source_hash"]:
        tx.put("outbox_attempts", attempt_id, {**attempt, "status": "superseded_before_publish", "finished_at": utcnow()})
        if delivery["last_attempt_id"] == attempt_id:
            tx.put("outbox_delivery", identity, {**delivery, "status": "retry", "updated_at": utcnow()})
        return "skipped", None
    fatal = None
    try:
        entry_id = bus.publish(item["message"])
        require(isinstance(entry_id, str) and bool(entry_id), "MissingTransportReceipt")
        attempt.update(status="delivered", entry_id=entry_id)
        delivery.update(status="delivered", delivered_entry_id=entry_id)
        tx.put("outbox", identity, {**item, "sent": True})
        result = "published"
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
        tx.put("events", attempt_id, {"type": "outbox." + result, "outbox_id": identity,
               "evidence_id": attempt_id, "error_type": attempt["error_type"], "at": attempt["finished_at"]})
    if audit is not None:
        # INV-OBSERVATION-001: a transport acknowledgement (stream entry id) is a delivery fact,
        # recorded with the attempt in the same transaction; it is never a task completion.
        facts = _message_facts(item)
        common = {"outbox_id": identity, "attempt_id": attempt_id, "attempt_number": attempt["number"]}
        if result == "published":
            audit(tx, "general.message_published", "succeeded", identity=["outbox_attempt", attempt_id, "published"],
                  correlation_id=facts.get("correlation_id"), causation_id=facts.get("causation_id"),
                  attributes={**common, "stream_entry_id": entry_id,
                              **{k: facts[k] for k in ("message_type", "recipient") if k in facts}})
        else:
            audit(tx, "general.message_delivery_" + result, "failed" if result == "retry" else "unknown",
                  identity=["outbox_attempt", attempt_id, result], severity="warning" if result == "retry" else "error",
                  correlation_id=facts.get("correlation_id"), causation_id=facts.get("causation_id"),
                  reason_code=attempt["error_type"], attributes={**common, "error_type": attempt["error_type"]})
    return result, fatal


def relay(store, org, bus, limit=100, audit=None):
    require(type(limit) is int and 1 <= limit <= 1000, "Outbox batch limit must be 1..1000")
    counts = dict.fromkeys(("published", "quarantined", "quarantined_existing", "retry", "skipped", "legacy_sent", "error"), 0)
    with store.transaction() as tx:
        control = tx.get("outbox_control", "relay") or {"cursor": ""}
        expected_cursor = control["cursor"]
        rows = tx.entries("outbox", expected_cursor, limit)
        if not rows:
            rows = tx.entries("outbox", "", limit)
    owns_cursor = True
    def advance(tx, identity):
        nonlocal expected_cursor, owns_cursor
        control = tx.get("outbox_control", "relay") or {"cursor": ""}
        if owns_cursor and control["cursor"] == expected_cursor:
            expected_cursor = identity
            tx.put("outbox_control", "relay", {"cursor": expected_cursor, "at": utcnow()})
        else:
            owns_cursor = False
    for row in rows:
        with store.transaction() as tx:
            result, prepared = _prepare(tx, row["id"], org, bus, audit)
            if not prepared:
                counts[result] += 1
                advance(tx, row["id"])
        if not prepared:
            continue
        fatal = None
        with store.transaction() as tx:
            result, fatal = _publish(tx, prepared, bus, audit)
            counts[result] += 1
            advance(tx, row["id"])
        if fatal:
            raise fatal
    # These are last-batch counters, not a complete queue census or proof of consumption.
    with store.transaction() as tx:
        tx.put("health", "outbox", {"id": "outbox", "at": utcnow(), "scope": "last_batch",
               "status": "attention" if counts["quarantined"] or counts["quarantined_existing"] or counts["retry"] else "observed",
               "examined": len(rows), "limit": limit, **counts})
    return {"examined": len(rows), "limit": limit, **counts}
