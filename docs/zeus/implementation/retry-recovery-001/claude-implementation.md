## Independent review — execution recovery (read-only)

Design intent (conductor at trusted local boundary, non-cryptographic operator label, canonical prepare/apply, exact-row CAS, bounded grant) is implemented faithfully: `expected_hash`/`related_hash` are re-derived inside the mutating transaction (`execution_recovery.py:121-124`), the packet window is bounded, attempts are never reset, and receipts are keyed by `digest(packet)` so a legitimate re-prepare after success cannot collide. Blockers below.

### 1. Recoverable-state set has holes (highest impact)
`_eligible` (`:24-37`) admits only two shapes. Reachable states with *no* recovery path:
- **Deadline-expired before a budget was ever pinned.** `claim` evaluates the deadline (`workflow.py:105-113`) *before* `retry_limit`, so such a row is `expired` with `retry_budget` absent. `resume` requires `isinstance(budget, dict)`; `migrate` requires `status == 'blocked'`. Permanently stuck. `test_expired_task_retains_original_message` hides this by starting from `exhausted()`, which pins a budget first.
- **`blocked` / `InvalidRetryBudget` and `blocked` / `InvalidExecutionDeadline`** from `block_execution` — exercised by `test_retry_state.py:207-224` — match neither branch (budget is a dict but status isn't failed/expired; or budget is corrupt, not `None`).

Fix: make `resume` accept `expired` with `budget is None` (treating it as a pin, `origin='resume'`), and add a third operation (`repair`) for `blocked` with `InvalidRetryBudget`/`InvalidExecutionDeadline`, keyed on the exact `error` string as `migrate` already does.

### 2. Aggregate isolation is only implemented for one phase
`_related` (`:39-50`) returns `None` for any `decisions_pending` row whose `phase != 'threshold_review'`, yet `prepare` accepts every phase. `review_*`, `diagnose`, `audit_review` all have downstream aggregates (candidate/release/audit rows) that may already be terminal; resuming silently re-runs a decision against state that has moved on, and `related_hash` is `digest(None)` so nothing is fenced. Fix: allowlist phases with an explicit coupling handler and reject the rest ("no recovery handler for phase X") rather than defaulting to no coupling.

### 3. Threshold restore does not revalidate the request binding
Restoration (`:136-141`) resets `status` and drops `failure`/`failed_decision` but never checks `digest(self._row(tx, request['row_id'])) == request['binding']`, which `ThresholdReviews._prepare` will demand (`threshold_reviews.py:64`). If the assessed row changed while the request was failed, recovery revives a request that can only fail again — spending the whole newly granted budget on guaranteed-failing attempts. Fix: require binding equality in `_related` for the `failed` case and fold the underlying row into `related_hash`.

### 4. Replay fences the execution row but not the related aggregate
Both replay branches (`:96-101`, `:113-116`) compare only `digest(row) == receipt['result_hash']`. The threshold request can be mutated afterwards (e.g. re-failed by `ThresholdReviews.exhausted` on a later exhaustion, which leaves the decision row it re-fails — but a *sibling* decision id — untouched), and replay still reports success. Fix: store `result_related_hash` in the receipt and re-check it on replay.

### 5. Packet field types are validated too late
`apply` checks only key set, `version`, `actor`, `authority` (`:86-91`) before computing `digest(packet)` and calling `tx.get('execution_recoveries', identity)` / `_row(tx, packet['bucket'], ...)`. `bucket`/`task_id` of arbitrary type reach the store adapter on the receipt branch (`_row`'s bucket guard runs, but `task_id` does not); `Infinity` round-trips through `parse_json` into `max_attempts`. Fix: type-check `bucket` ∈ allowlist, `task_id`/`reason`/`operator`/`deadline` as `str|None`, `max_attempts` as `int`, `evidence_refs` as a list of `sha256:` refs, before any digest or store access.

### Smaller
- `row.update(...)` clears `error`/`failure`/`failure_receipt` but leaves a stale `result` from a prior partial completion (`:129-133`).
- Missing evidence raises `FileNotFoundError`, not `ContractError` (`test_execution_recovery.py:144`); the CLI (`cli.py:396`) surfaces a traceback. Wrap in `_evidence`.
- `prepare` computes `now`/`due` outside the transaction; harmless today, but the freshness check should use the transaction clock.

No writes, no execution, no issues filed.