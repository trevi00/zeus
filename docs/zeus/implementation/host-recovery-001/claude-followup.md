## Verdict

No concrete correctness blockers. The four fixes are correct as implemented, and I checked the paths they touch against the runtime rather than by inspection alone.

**Fixes confirmed**

- `live_owned` (`scripts/host_cycle.py:250`) now requires `lease_owner == owner` **and** `status == 'running'` **and** a future `lease_until` — exactly the liveness predicate `_owned` → `active()` enforces (`workflow.py:195-198`), so the dead-end I flagged is closed: an expired self-owned lease now falls through to `w.claim`.
- Per-generation checkpoints (`:243`, `:258`) make the resume path sound. Write-before-complete ordering (`:278-280`) means a crash after `complete` still finds the checkpoint, and `complete` does not clear `lease_owner` (`workflow.py:277`), so the succeeded-branch assert `row['lease_owner'] == owner` (`:247`) holds on re-run.
- Re-running reconciliation after a fresh claim is safe: `reconcile` keys on `digest(request)` including `observed`, so a new generation yields a new rejection row rather than the `Conflicting execution rejection` require (`execution_rejections.py:51-54`), and `reason_code` stays `execution_identity_changed`.
- `assert claimed['generation'] > previous['generation'] and claimed['attempt'] > previous['attempt']` is compatible with a resumed run; budget exhaustion surfaces as `claim → None → inconclusive_requires_inspection`, not an assert.

**Two things I checked because they would have been blockers, and are not**

- Concurrency: `claim` returns `None` if two executions are live, but `running()` counts only rows whose lease is still *active* (`execution_time.py:145-150`), and verify already gates on pre-restart lease expiry (`:227-229`). Both keys can claim.
- Deadlines: `envelope` sets `when.deadline = None` and `submit` never sets `execution_deadline`, so `deadline` is `None` at `workflow.py:144` — an arbitrarily long gap between prepare and restart does not expire the probe tasks.

**One operating limit, not a defect**

With `POLICY.max_attempts = 3` and prepare consuming attempt 1, you get two post-restart claim attempts. A second interrupted verify leaves the row `failed` and every later run returns `inconclusive_requires_inspection`. Retryable-but-finite by design; worth telling the operator to run `verify` to completion.

Boot, sleep, and clock-step behavior remains unobserved — this is review, not execution.