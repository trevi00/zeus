## Final resolution review — no remaining blockers

Verified against `execution_rejections.py:1-64`, `executor.py:420-449, 568-572`, and `tests/test_execution_rejections.py`.

**Confirmed fixes hold**
- `_fail_task` and `decide_one` both catch the guard as `ContractError` and pass `(original, guard)` into `reconcile`; the business error is never replaced. Both call sites run *after* the failing `with store.transaction()` block has exited, so reconcile never nests inside the rolled-back transaction (`executor.py:431-449`).
- `execution_rejections.py:42-44` rethrows the original with the guard as `__cause__` only while the lease is still valid and owned — the correct non-stale path.
- `request` (`:45-47`) carries bucket, submitted/observed identity, observed status and reason only; no error text or type, so a changed error on a repeat observation hits `old` and returns the identical receipt (`:49-52`), matching the test at `test_execution_rejections.py:34`.
- Success is preserved before any write (`:28-29`), and `require(old['request'] == request)` keeps dedup honest.
- Test matrix covers missing/not-running/expired/invalid lease across memory and PG, bool-vs-int identity typing, rollback on interrupted event write, and original+guard capture.

**Scope statement is accurate**
Both children are spawned before either `communicate()`, so PG's advisory lock genuinely serializes two processes. This demonstrates cross-process idempotency of reconciliation, not a full execution race — the docs say exactly that.

**Non-blocking notes**
- Each distinct successor identity yields a new receipt; growth is bounded by successor generations but not by the stale caller.
- The returned `result['error']` is the first observer's text; a later caller sees an error string other than the one it passed. Consistent with the accepted design, worth a docstring line.