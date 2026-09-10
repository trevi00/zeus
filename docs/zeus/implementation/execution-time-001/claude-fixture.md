**Bounded fix, but the new setup is inert — no regression in behavior, a small loss in what the test proves.**

`Workflow.claim` filters at workflow.py:101 on `status not in {"queued","running","retry"}`. After `fail_execution` (workflow.py:321) the row is `failed` with `lease_until=None`, so it is skipped before any lease/deadline evaluation. Consequently:

- The persisted `lease_until` 30 days in the past (test_usage_limit.py:177) is never read; `claim` returns `None` via the status filter alone.
- The `tx.get(...) == terminal` equality at line 181 holds trivially, since `claim` writes nothing on that row.

So the original guarantee (a terminal quota failure is never auto-retried) is still covered, and it's covered without host-clock injection — which was the point. What is no longer covered is the time-advanced dimension: that lease expiry and deadline passage don't resurrect a terminal row. That path is short-circuited by status, so it's low-risk, but the test no longer demonstrates it.

Suggested minimal strengthening (not applied): assert `terminal['status'] == 'failed'` explicitly, so the test states the actual mechanism rather than implying a lease-expiry check it doesn't reach.