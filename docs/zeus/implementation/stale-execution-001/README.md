# Fenced execution rejection (FA-017 / GitHub #18)

The original executor returned any current `succeeded` row before checking which
execution completed it. The real isolated PostgreSQL baseline reproduced generation
1 receiving generation 2's success, with zero rejection receipts (`baseline.json`).

The root and actual Claude CLI independently inspected the path and agreed on a
fix before implementation (`claude-design.md`). Root implemented the change.
Reconciliation now compares aggregate, task, generation, attempt, owner, actor and
recovery sequence with strict scalar types. Only the same execution may reconcile
its already committed success. A still-valid owner retains its original exception.

Other outcomes produce a deterministic `execution_rejections` receipt and safe
event. Observation and writes share a fresh transaction after the business
transaction has unwound. No task, review, diagnosis or outbox record is changed by
rejection. Repeat observations reuse the receipt. Storage failures propagate and
roll back the receipt/event together. `zeus inspect execution_rejections` exposes
the durable observations; they are informational, not workflow authority.

Final targeted Windows verification passed **82 tests**, including real isolated
PostgreSQL and two concurrent child processes replaying an old lease after a real
successor completion. Other cases exercise identity differences, bool/integer
distinction, valid-owner error propagation, and injected write failure rollback.
These application/process checks do not invoke a model or constitute human
acceptance. The test source distinguishes real service/process tests from unit
failure injection. No new issue or production deployment is created by this slice.

Implementation review requested retaining the original business error alongside
the ownership rejection, making rejection identity independent of changing error
text, and covering each reason code. Root accepted these changes. The two child
processes are launched before either is awaited; the real store's advisory lock
serializes their transactions. This proves cross-process idempotency using that
lock, not unconstrained simultaneous database writes or a full execution race.

The final Claude review (`claude-resolution.md`, session
`fd8362a0-feff-47c9-ade5-47468b2eb2c4`) found no remaining blockers in this scope.
It confirms original/guard error preservation and error-independent deduplication.
The first observation's error text remains in the replay response by design;
different observed successor identities produce distinct observations.

The first full/target runs preceded the error-preservation changes and are retained
as `superseded-*`. A later tool interruption has its own `interrupted-target-*`
receipt. After a user-reported reboot, the surviving target process was confirmed
live but still used the ledger's obsolete published port. Root stopped only that
test process, retained `pre-reconnect-target-*`, restarted the existing Zeus ledger
container and updated the ignored local `.env` to its actual published port.
The successful `target-tests.*` run followed that reconnection. Database credentials
are not included in evidence. Existing non-Zeus containers were not started.

Final Windows full regression: **833 passed, 250 skipped** (`full-tests.log`),
with Ruff passing. Skipped integration cases are not counted as executed by the
ordinary suite; the separate 82-test target run enabled real PostgreSQL fixtures.

This addresses the executor's stale-result observation path, not every direct
internal Workflow API exception. The full FA-017 matrix, including clock-change
disposition and remaining recovery/reconciliation cases, remains incomplete.
