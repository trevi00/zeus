## Design review — `_lost_execution` stale rejection (FA017)

### Root cause confirmed
`executor.py:427-428` returns `current` whenever `current["status"] == "succeeded"`, **before** the generation/owner comparison at `:429-432`. A fenced-out executor whose successor (generation N+1) completed the task therefore returns the successor's `succeeded` row as its own outcome. Callers treat that as authority: `cli.py:108-112` emits `{"execution": result}` and flushes the outbox; `_fail_task` (`:457`) and `decide_one` (`:580`) both return it upward. The `{"status": "stale"}` branch (`:433`) is a bare in-memory marker — no durable receipt anywhere, so FA017's "recorded" half is unmet for every stale path.

### Bounded fix — agreed, with these constraints
1. In one `store.transaction()`, read `current` and decide. Reconcile-as-success only when identity matches: same bucket (`_bucket`), `id`, `generation`, `attempt`, and actor (`agent`/`actor`); `lease_owner` may legitimately still be the completing owner, so compare it only when identity otherwise matches. This preserves `test_task_failure_atomicity.py` `failure == "completed"` (same generation/owner self-completion → `succeeded`).
2. Otherwise append a rejection receipt in **the same tx as the comparison**, keyed by `digest({bucket, id, generation, attempt, owner, observed_status, observed_generation})` so redelivery is idempotent, with a `require(existing == new)` conflict check like `execution_notices.py:80-82`. Read-then-write in separate transactions would race a concurrent successor.
3. That tx must be opened **after** the business tx unwound. `_fail_task:439-457` and `decide_one:577-580` already satisfy this — the `with` block exits (rollback) before `except` runs. Keep it that way; do not pass `transaction=tx` in.
4. No business or outbox authority: rejections must not write `tasks`/`decisions_pending`/`outbox`. If you emit an `events` row, use the same deterministic id, not `uuid4()` (contrast `workflow.py:191`).
5. Catch only `ContractError`/`KeyError`/`TypeError`/`ValueError` when building the receipt body; let storage/DB errors propagate — never a state-only success. Do not widen `_fail_task`'s `except ContractError`; the `raise error` at `:434` for a still-valid lease must remain.
6. Add `execution_rejections` to `cli.py:212` inspect choices; no schema change (single `documents` table).

### Edge cases
Successor already `retry`/`failed`/`cancelled`/`superseded`/`expired`; row deleted (`current is None`); attempt advanced but generation equal; recovered rows (`recovery_sequence`); the `fail()` replay `require` at `workflow.py:222-227` reaching `_lost_execution` as a *false* stale.

### Recommended tests
Extend `test_task_failure_atomicity.py` with `replaced_then_succeeded` asserting `status == "stale"`, exactly one rejection receipt, zero outbox rows; a redelivery case asserting the receipt is not duplicated; a `decide_one` double-fault case; a DB-error case asserting propagation and no receipt. Add a real-PostgreSQL concurrency test with actual child processes (`multiprocessing`, as `test_sdd.py:235` and `test_reverse_progress.py:139` do) against `isolated_pgstore`: two executors on one task, expect exactly `["stale", "succeeded"]` and one receipt.