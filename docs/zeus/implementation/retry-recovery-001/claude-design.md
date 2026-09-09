## Files inspected
`application/workflow.py`, `application/execution_budget.py`, `adapters/executor.py`, `cli.py:168-170,452-454`, `tests/test_retry_state.py`; `Organization` lives in `domain/model.py:52-86` (built by `bootstrap.organization()`), not `domain/organization.py`.

## Authorization fit — the weakest concrete point
`Organization` only knows `conductor|lead|worker` agents (`model.py:60`) and `org.actor()` raises "Unknown actor" for anything else. There is no operator principal to name. `cancel` doesn't consult roles at all: CLI hardcodes `"conductor"` (`cli.py:453`) and `cancel` accepts `actor in {"conductor", message sender}` (`workflow.py:238`). So "operator identity/role allowed by organization" reduces to either (a) `org.actor(operator).role == "conductor"` — the honest mirror of `cancel`, recommended — or (b) a new role vocabulary requiring `Organization.validate` changes, which is scope creep. Either way it is a label: any local process that can open the store calls `Workflow` directly with no gate. State that in the packet and audit event; don't let the word "authorized" imply enforcement.

## Invalid states / preconditions
- Excluding `running/succeeded/cancelled/superseded` is insufficient. `blocked` is overloaded: `InvalidExecutionDeadline` (`workflow.py:107`), `InvalidRetryBudget` (`:122`) and `UnverifiedLegacyRetryBudget` (`execution_budget.py:35`) all produce it. Migrate must key on `error == "UnverifiedLegacyRetryBudget"` **and** `"retry_budget" not in row` exactly — status alone silently migrates corrupt-budget rows.
- Resume-terminal is `failed` with `error == "attempt budget exhausted"` (`:127`) or `expired` (`:113`). Nothing else.
- `decisions_pending` rows carry budgets too (`executor.py:480`, `_bucket` in `fail`/`_owned`). Decide explicitly: support both buckets like `fail` does, or state decisions are unrecoverable. Silence here is the invalid-state risk.
- Reject `running` even with an expired lease; require `lease_owner`/`lease_until` cleared post-apply.

## CAS / atomicity / idempotency
- `Workflow.snapshot()` digests *all* tasks+sessions (`:343`) — unusable as CAS; any unrelated concurrent write invalidates the packet. Digest exactly the target row.
- Fencing works via generation: a stale executor's `fail` hits `_owned` (`:143`) → ContractError → `_lost_execution` returns `"stale"`. Correct, and `test_committed_failure_cannot_replay_after_cancellation` is the template — add the recovery variant.
- Make the audit event key `digest(packet)`, content-addressed like `block_execution` (`:58`), **not** `uuid4()` like `task.succeeded` (`:185`), and have re-apply of an identical packet return the row unchanged — mirror the `fail` receipt comparison (`:216-222`). Put row + budget-v(n+1) + prior snapshot + event in one `store.transaction()`.
- Ceiling: `retry_limit` returns the pin and only writes when absent. A recovery budget with `max_attempts <= attempt` fails instantly at `:126`; your ">attempts" rule is right. But subsequent `claim(..., max_attempts=…)` now emits `execution.retry_budget_conflict` and returns `None`, skipping the task forever — document that operators must stop passing `--max-attempts`, or the recovery is self-defeating.

## Deadline override
Correct instinct: deadline is read only at `:105` from `message["when"]["deadline"]`, and mutating the message breaks `input_hash` identity (`:48`). A separate `execution_deadline` row field preserves it — but it must be read in `claim` *and* in the recovery precondition, or resume can revive a row that immediately re-expires. Require the new deadline strictly future at apply time.

## Test fix
`created_at = '2000-01-01T00:00:00+00:00'` (`test_retry_state.py:214`) is correct against sort key `(created_at, id)` (`:86`) and removes the Windows clock-resolution flake. But it also removes tie coverage: add equal-`created_at` cases that force both UUID orderings by controlling the ids (corrupt row's id lexically before and after the good row), asserting the good row is claimed either way.

Scope note: this is critique only — no files written, nothing executed.