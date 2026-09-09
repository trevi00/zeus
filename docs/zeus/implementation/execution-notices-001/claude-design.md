## Scope note

Your instructions conflict: "First implement and verify via real PostgreSQL/Redis … before commit" versus "No writes/execution/new issues." I honored the terminal constraint — nothing was implemented, run, or committed, and the child-kill matrix is **unverified**. Below is the critique from reading the code.

## Real integration gaps

**1. Deterministic identity fights the outbox's reuse guard.** `outbox.py:35` requires `message["message_id"] == identity`, so a digest-derived id works as the outbox key. But `_prepare` also enforces `AttemptedMessageIdentityReused` (`outbox.py:40`) against `digest(message)`. `envelope()` (`model.py:89`) stamps `utcnow()` into `when.created_at` and a `uuid4()` id. If the notice is rebuilt on a replay path with a fresh timestamp and re-put under the same key, relay **quarantines** it instead of deduplicating. The notice envelope must be byte-deterministic — `created_at` derived from the persisted transition record, not the clock. `envelope()` cannot be reused as-is.

**2. `block_execution` cannot express "distinct notice after repair."** `execution_budget.py:57-60` derives the event identity from `{type, bucket, task_id, reason}` only, and suppresses on `tx.get("events", identity) is None`. A context block, a `repair` recovery, and a second identical block collapse to one row. Your requirement forces adding `generation`/`recovery_sequence` to that identity — which silently changes existing event-dedupe semantics for `execution.state_blocked` and `execution.retry_budget_conflict`. That is a behavior change to an existing invariant, not an additive feature.

**3. "Same tx writes status + failure receipt + notice" is false for most of the roots.** Only `fail()` writes `execution_failures` (`workflow.py:230`). The claim-time terminals — `expired` (`:113`), `cancelled` on terminal dependency (`:115`), `attempt budget exhausted` (`:127`) — and `cancel()` (`:241`) and `decide_one`'s equivalents (`executor.py:496,507`) write status with **no receipt at all**. Delivering the proposal means inventing receipts for five paths, in a loop that currently `continue`s over many tasks per transaction.

**4. `fail()` replay already satisfies "never adds a notice"** — `workflow.py:213-222` returns before any write. But it takes an external `transaction=`, so notices would inherit the executor's tx; `executor.py:455` catches `ContractError` into `_lost_execution`, which would swallow notice-construction contract failures.

**5. `Organization.authorize` is open by default.** `model.py:80-86` only checks actor existence for unknown types; the route checks are an if/elif chain with no else. A new `execution.notice` is *implicitly* authorized today. Strictness must be added explicitly, and the root case needs a carve-out: conductor has `parent is None`, so self-routing violates the `sender.parent == recipient.id` shape used for reports. Also `message.schema.json` is a closed enum with `additionalProperties: false` — the type must be added there and in `handle`'s allow-list (`workflow.py:268`), or the CLI dead-letters it (`cli.py:102`).

## Where the design is right

The at-least-once story already works: `workflow_inbox` (`workflow.py:270-273, 332`) is written in the effect transaction and keyed by `message_id` with a hash-conflict check; `bus.ack` follows `flush_outbox` (`cli.py:97-98`). Kill-before-ack replays into the dedupe; kill after `xadd` before the delivery commit (`outbox.py:75-77`) leaves the attempt `publishing` and republishes. One inbox effect holds — *provided* the notice's handler writes nothing but the inbox row.

## Authority and retention

The "durable notice record" validation is a same-database join, not cross-service proof — agents share one store. The notice's value is therefore a wake-up signal, not evidence; treat it as strictly non-authoritative and keep it out of any `status == "succeeded"` predicate. Retention is the unaddressed cost: `relay` scans `outbox` per batch (`outbox.py:104`) and nothing prunes `outbox`, `outbox_attempts`, `execution_failures`, or `events`. Emitting a notice per failure, expiry, exhaustion, and block adds unbounded rows to a table already scanned linearly. Raw model text stays correctly confined to artifacts (`executor.py:444`); the notice should carry only `failure_receipt`.