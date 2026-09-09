## Approve — no blocker.

**`application/outbox.py`**
- Reason tokens (`26,32,34,36,39`) are fixed, code-controlled strings assigned before each guarded step, and the handler at `42` no longer touches the exception object. `_quarantine` writes `reason` into both the quarantine record and the event, so `SchemaInvalid` (the only path carrying validator text) is distinguishable from `InvalidOutboxRecord`, `OutboxMessageIdentityMismatch`, `UnauthorizedRoute`, `AttemptedMessageIdentityReused` without exposing payload text. Raw text survives only in `source`, which no projection reads.
- The `legacy_sent` early return at `30-31` exits before any `reason` is consumed — correct.
- Non-`ContractError` escapes remain possible in principle from `bus.validate`, but `validate_message(None)` yields schema errors rather than raising, so `item.get("message")` absent still quarantines.
- `advance()` (`108-115`) preserves the `owns_cursor` / `expected_cursor` compare-and-set exactly as before, now called once per item: inside the prepare transaction when nothing was prepared (`119-121`), inside the publish transaction otherwise (`128`). The extra transaction per legacy/quarantined row is gone. Cursor still advances before `raise fatal`, matching the prior semantics.
- Both `except MessageDeliveryError` and the recorded-then-reraised `except Exception` are unchanged; still no swallowing.

**`resources/monitor.html`**
- `render()` at `:38` pushes the attention condition into the persistent `#notice` banner alongside stale-source warnings — top of page, not tab-local, and driven by durable `outbox_delivery` counts rather than batch recency, so it does not clear on a later clean batch.
- `:48` renders label/count pairs only for the five delivery statuses; no `source`, no `error_type` text, no message bodies. The panel header at `:12` states the send record is a bus enqueue response and not receiver completion; the footnote says the counts differ from total queue depth. No approval or consumption claim.

One non-blocking note: `status_counts` scans all of `outbox_delivery` per monitor read, which grows without bound. Fine for now; worth a retention decision later.

Fault-injection and corrected-content runs on isolated PG/Redis remain root's to execute; I ran nothing.