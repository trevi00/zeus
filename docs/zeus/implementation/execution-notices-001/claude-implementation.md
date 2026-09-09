## Read-only review: execution notices

### Blocking

**1. A notice failure aborts the transaction that was recording state.** `record` raises `ContractError` on unknown actor (`execution_notices.py:14`), missing `row['attempt']` (:17), or non-int counters (:20). Every call site mutates state *then* records, inside the caller's transaction, with no guard:

- `workflow.py:97` — `ticket_binding` failure is caught, but the notice for it is not; a single row whose `agent` was removed from the org makes `claim` raise instead of returning `None`, and rolls back the `blocked` write plus **every other row** the loop already fixed in that pass. Same for `:131`, `:139`, `:237`, `:249` and `executor.py:501,516`.
- Worse, `block_execution` (`execution_budget.py:56-65`) now records *inside* the handler for `except ContractError`; a raise there escapes the `except` in `workflow.py:109/124` and `executor.py:493/506`. Corrupt-control rows become an unrecoverable claim-path outage rather than a contained `blocked` state — the opposite of the intent, since `execution_recovery` can only repair a row that actually reached `blocked`.

This is the single defect I'd fix before merge: decide explicitly whether the notice is best-effort (record failures as an event, keep the state write) or mandatory (validate actor/counters *before* mutating).

**2. Identity is only deterministic on two of six paths.** `transition_ref` defaults to `digest(row)` (:19) — the whole post-mutation row, including `lease_until`, `error` text and `attempt_outcomes[].at`. So the claim/cancel/expiry notices' identity is a hash of a wall-clock-bearing snapshot, not of the transition. `fail` (receipt id) and `block_execution` (event id) are properly derived; the other four should be too, otherwise "deterministic transition identity" doesn't hold under retry-after-rollback, and the `Conflicting execution notice identity` check at :26 can never fire meaningfully.

### Design concerns

**3. Retention makes published notices poison.** `receive` requires the `execution_notices` row to still exist and to match byte-for-byte (`:46-47`). There is no TTL or compaction today, so the design silently depends on `execution_notices` outliving the Redis stream forever; any pruning, or a DB restore predating publication, yields a message that can never be handled and therefore never acked. Also, full-envelope equality means a `schema_version` bump or any read-path normalization invalidates every in-flight notice. Consider proving against `digest(transition)` + a bounded envelope subset instead.

**4. Sender identity is borrowed.** Notices are authored by the workflow but signed as the worker/actor (`:14`, `model.py:83-85`); a consumer cannot distinguish system-observed transitions from worker-authored ones. Containment rests entirely on `receive`'s persistence proof, which is sound but undocumented as the load-bearing control. For `decisions_pending` rows with `actor == 'conductor'`, recipient collapses to the conductor itself — a self-addressed stream write worth confirming is intended.

**5. Terminal-path coverage is incomplete.** No notice for `complete`'s `superseded` branch (`workflow.py:173-176`), which is terminal and is exactly the `ticket_binding_changed` condition that *does* notify at claim. `retry_limit`'s budget-conflict path (`execution_budget.py:46-52`) returns `None` after an event only, so the task stalls indefinitely with nothing on the bus; `require_adoption` failure (`workflow.py:102`) is likewise silent. Either state the notice set covers only *state-changing* transitions, or close these.

**6. Schema is permissive.** `execution.notice` is added to the type enum only; nothing requires `notice_id`, `authority` or the counters in `what.details`, so `validate_message` can't catch a malformed notice. The `REASONS` allowlist does keep raw error text off the bus — that part holds, and `fail`'s receipt short-circuit (`:218-227`) does return before any write, as claimed.

### Tests

Boundaries and instrumentation are genuine (real PG/Redis, real `publish`, kill after the real call). Gaps: raw-text absence is only asserted on `MemoryStore`; nothing exercises a notice raising inside a state mutation (issue 1) or a missing `execution_notices` row on `receive` (issue 3); `after_consume` recovery relies on a differently-named consumer reclaiming, which is asserted only via final `xpending`.