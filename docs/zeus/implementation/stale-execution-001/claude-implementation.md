## Implementation review — execution rejections

**Root scope is preserved.** `reconcile()` runs in one fresh transaction after the business transaction has rolled back (`_fail_task` exits its `with` before the `except ContractError` body; `execute` calls `fail_execution` which owns its own transaction). Identity comparison is strict-typed both directions (`type(observed[k]) is type(value)`), so the reproduced PG case — gen1 lease reading a gen2 `succeeded` row — falls to `execution_identity_changed` and cannot borrow success. Rejection + event are digest-keyed and written in the same transaction, matching the existing `execution_budget` idiom. DB errors propagate (no bare `except`), and the valid-unexpired-lease branch rethrows before any write.

### Blockers / findings

1. **`_fail_task` passes the wrong error (executor.py:449).** It forwards `exc` (the ownership `ContractError`) rather than the original business `error`. Consequences: the recorded `error_type`/`error` describes the commit-time invariant, not the failure; and on the valid-owner rethrow path the original `error` is discarded entirely while the failure transaction has already rolled back — the task stays `running` until lease expiry with no record of why it failed. The decision path (:570–572) has the same shape, but there `exc` *is* the propagated failure. Recommend threading the business error through and attaching the contract error as context.

2. **`digest(request)` includes `str(error)`.** Any error text carrying a uuid, path or timestamp yields a different rejection id per redelivery, so "one deterministic record" holds only for byte-identical messages. The two-process test passes because both children raise a fixed literal. Suggest keying on `bucket + submitted + observed + reason_code` and keeping the error text in the body only.

3. **Reason-code coverage gap.** `workflow.cancel` bumps `generation`, so the second half of the rollback test exercises `execution_identity_changed`. `execution_lease_expired`, `invalid_execution_lease`, `execution_missing` and `execution_not_running` have no test at all — notably the expired-lease case, which is the ordinary fencing path.

4. **The PG test is cross-process replay, not a race.** `PostgresStore.transaction` takes a global advisory xact lock and `communicate` is sequential, so the two children serialize. It is strong evidence for the borrowed-success invariant; it is not evidence about concurrent rejection writes — worth stating in the ledger rather than implying contention coverage.

Minor: rollback injection only fires on the last (`events`) put; a failure on the `execution_rejections` put is untested. A same-identity row already in `failed` returns the synthetic stale dict rather than the row, asymmetric with the `succeeded` branch (low impact — callers only emit it).

No FA017 completion claim implied.