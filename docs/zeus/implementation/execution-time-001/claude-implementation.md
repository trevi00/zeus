## Review — execution_time.py and integration

Read-only; no edits or runs. Design (process-UUID domain, wall-only for foreign/legacy, per-row containment) is sound. Concrete blockers, by severity:

**1. Unthrottled DB round-trip in `on_tick` (executor.py:220-223 × app_server.py:182-187).** `observe(None)` now calls `remaining_seconds`, which opens a full transaction. The runtime loop is `on_tick(); event = notifications.popleft() if notifications else _receive(...)` — when the deque is non-empty it spins with **no blocking**, so this is one `psycopg.connect` + global `pg_advisory_xact_lock(734219)` **per notification**. With `max_active_executions=2` both executors contend on that single lock under `lock_timeout='10s'`; a timeout raises `ContractError` inside `on_tick`, escapes `run`, and becomes an execution failure rather than a contained time event. The deadline enforcer consumes the deadline. Throttle it like `last_beat`, or capture an absolute monotonic deadline once and check it locally.

**2. Startup sits outside the monotonic budget.** `remaining_seconds` is taken at executor.py:258, but `run` sets `deadline = time.monotonic() + timeout` at app_server.py:168 — *after* `thread/start` and `turn/start`, each up to 30s via `request`. A task with 10s remaining still commits a turn before the first tick fires. Pass an absolute deadline (or re-check right after `turn/start`).

**3. `contain_time` fencing is weaker than `reconcile`'s** (workflow.py:174 vs execution_rejections.py:27). It uses bare `!=` on `generation/attempt/lease_owner`; `reconcile` deliberately adds `type(observed[k]) is type(value)`. A corrupt `generation: True` matches `1` and gets contained. Also omits `recovery_sequence` (currently masked by the generation bump). Reuse `_identity`.

**4. `execution_time_events` silently drops contradictory observations** (execution_time.py:120-125). The key is `{bucket, task_id, generation, recovery_sequence, reason}` — no `attempt`, no observation — and the guard is `if not tx.get(...)` rather than `require(old['request'] == request, ...)` as in `execution_rejections`. Two different ClockDiscontinuity observations in one generation collapse to the first with no conflict detection, which undercuts the "exact observation" durability claim.

**5. `contain()`'s non-deadline branch (lines 114-116) is dead and unsafe if reached.** Every non-deadline reason routes to `block_execution`; this branch blocks with no event, no notice, and a state repairable only by error-string match. Delete it or delegate.

**6. `claim` re-evaluates `active` outside containment (workflow.py:99).** `running()` already contained bad rows in the same tx, but line 99 re-runs `active` with a fresh `time.monotonic()`. Crossing `deadline_remaining` in that window raises `ExecutionTimeError` out of `claim`, rolling back the containment and notices `running()` just wrote **for every other row**. Wrap in try/except → `contain_with_notice`.

**7. Minor:** `contain_time` calls `aware_time()` three times (180, 182), so the stored `at` differs from `observation['wall']`; decision ticks pass `POLICY.task_seconds` (900) as the cap instead of `decision_seconds`.

Rollback containment via `_execution_transaction` is correct — the inner `with` exits before the `except`, so no nested transaction against the reentrant `MemoryStore.lock`. The `fail(transaction=...)` path bypasses it but is recovered by `_fail_task`'s `except ContractError → _lost_execution → contain_time`.