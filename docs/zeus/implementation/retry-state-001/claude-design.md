No files written. Read: `docs/tickets/FA-017.json`, `src/codex_harness/application/workflow.py`, `src/codex_harness/adapters/executor.py`.

## Defects confirmed

**Root comparison holds.** `submit/claim/complete/fail` all fetch the row and `.update()` in place, then `tx.put` the whole row (`workflow.py:78,94-104,137-142,174-176`). Zeus has no error-branch state *constructor*, so the upstream Stop failure mode (null cwd, 3/5→0/0) has no analogue here. The remaining gaps are narrower.

1. **Unpinned budget — real.** `max_attempts` is a call parameter only (`workflow.py:60,97`); nothing persists it. Two callers, or one restart under edited config, compare the same monotone `attempt` against different bounds. `attempt` itself is never decremented (`cancel` bumps generation, not attempt), so policy cannot *reset* attempts — it silently re-opens or closes an exhausted task. Same class, unfixed by your proposal: `executor.py:477` reads `POLICY.max_attempts` inline for decisions.
2. **Weak validation — real, low severity.** `require(lease_seconds > 0 and max_attempts > 0)` (`:62`) admits `True`, `2.5`, `inf`. A naive `now` passes and then raises `TypeError` at `:66` comparison, not a contract error. No external input path reaches these; it's hygiene, not exploitable.
3. **Failure redelivery — real.** `fail` → `_owned` requires `status == "running"` (`:115`); a committed failure left `status="retry", lease_owner=None`. Redelivery hits `ContractError` → `_lost_execution` → `{"status": "stale"}` (`executor.py:432`), which already special-cases `succeeded` but not just-committed failure. That is misreported, and it violates AC "같은 입력의 재전달은 중복 전이를 만들지 않으며".

## Critique of the proposal

- **"Explicit different value rejects" wedges the loop.** `claim` raising aborts the whole `for task in sorted(...)` scan, starving every other task of that agent. Reject per-task: record and `continue`.
- **It also makes AC 6 unimplementable.** Authorized exhausted-state recovery *must* raise the pinned budget. Model the pin as `retry_budget` + `retry_budget_authorization`, mutable only through a recorded transition that appends an attempt outcome — never through the implicit claim parameter. Otherwise a legitimate config change turns into a permanent unclaimable task.
- **The receipt must be a row, not an artifact.** `executor.py:443` writes the receipt via `self.artifacts.put`, outside PG. For `fail(transaction=tx)` (`workflow.py:168`, `nullcontext`), only `tx.put` gives you receipt-and-transition atomicity; caller rollback then correctly discards both. Consequence to state plainly: the receipt proves the failure was *committed*, never that it was *observed*.
- **Owner is unverifiable post-commit.** `fail` nulls `lease_owner` (`:175`), so the current row cannot re-match the owner in your key. Store the receipt reference on the row. Generation increments per claim, so owner is in practice redundant — keep it for audit, don't gate on it.
- **Staleness gate.** Dedup only when `status in {retry, failed}` **and** `generation == receipt.generation` **and** `attempt == receipt.attempt` **and** the recorded error/failure/retryability match; return the stored receipt *without writing*. Any later claim increments generation and a stale receipt correctly falls through to rejection — it cannot masquerade as current, and cannot overwrite an intervening `cancel`/`expired`. Note `_attempt_outcome` (`:54`) already dedups by attempt, so the no-write path is consistent with existing history.

## FA-017 is not closed by this

Remaining, unaddressed: clock-discontinuity deadline disposition (AC 5), authorized exhausted/time-exhausted recovery as a recorded transition (AC 6), terminal user notification reconciled against `outbox` after commit-then-crash (AC 3), and the real Windows/Linux/WSL process·PG matrix (AC 7). The ticket's own verification block already disclaims Windows/WSL and installed-host coverage; this proposal does not change that.