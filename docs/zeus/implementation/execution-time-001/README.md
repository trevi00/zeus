# Execution time contract (FA-017 / GitHub #18)

The actual isolated PostgreSQL baseline accepted a heartbeat and successful result
after the durable deadline (`baseline.json`). Root and the actual Claude CLI
independently confirmed claim-only deadline enforcement and unguarded global lease
parsing (`claude-design.md`). Root implements; Claude reviews read-only.

Time has two different contracts. Python's monotonic clock is suitable for elapsed
intervals and is not affected by wall-clock steps; its reference origin must not
be treated as a portable timestamp. PostgreSQL distinguishes transaction-start time
from the current wall time returned by `clock_timestamp()`. Changing to a database
wall timestamp alone would not establish a monotonic elapsed-time contract.
Sources: [Python time documentation](https://docs.python.org/3/library/time.html),
[PostgreSQL time functions](https://www.postgresql.org/docs/16/functions-datetime.html).

The implementation centralizes deadline/lease checks at claim, heartbeat and owned
effects. New leases are capped at the durable deadline. The model runtime receives
the remaining bounded duration and its tick callback rechecks execution ownership.
A rejected effect transaction rolls back before a separate transaction rechecks
identity and atomically records containment, the time event and its notice.
Bad running leases are isolated before global concurrency counts are evaluated.

New lease pins retain UTC observation, monotonic sample, lease duration, remaining
deadline and a process-domain UUID. Only the same domain subtracts monotonic
samples. A wall/elapsed divergence beyond five seconds, or backwards monotonic
progress, produces `ClockDiscontinuity`; explicit existing recovery CAS is required.
Renewal cannot replenish the same-domain monotonic deadline. Clock observations
used to contain a discontinuity are retained in `execution_time_events`.

Foreign process domains and legacy rows use UTC validation and retain an explicit
`execution.clock_domain_observed` event. **This does not infer an unobserved forward
clock jump while a host was offline, synchronize multiple hosts, or establish a
trusted time authority.** A real operating-system clock-change/VM-resume matrix is
still required before full FA-017/pilot acceptance. The host clock is not changed by
these tests. Pure sample matrices and deliberately corrupted persisted observations
are distinguished from actual PostgreSQL and child-process deadline tests.

No original Claude/codex-harness deployment is replaced. No new issue is created.

Claude's first implementation review identified excessive database checks per
notification, startup requests outside the runtime budget, weak containment
identity, lost clock observations, a dead helper and batch rollback hazards.
Root addressed these and independently found that sampling wall time before a
PostgreSQL lock wait can falsely disagree with a later monotonic observation.
Production paths now sample after acquiring the transaction/read and again before
granting leases. A real child process holds the PostgreSQL advisory lock for six
seconds to verify this does not contain an otherwise healthy execution.

The next review (`claude-resolution.md`) prompted three further changes. Clock pins
sample the actual host wall clock even when a caller injects scheduling time.
Containment identity excludes volatile observations and retains the first exact
observation per execution/reason. Decision first claim pins a durable window of
remaining attempts multiplied by the per-decision runtime limit; retries retain
that deadline, while an explicit recovery can establish a new window. Global
historical event archival remains outside this change; deduplication prevents
repeated observations from amplifying one containment into unbounded rows.

The runtime deadline starts before hook discovery, thread setup and turn startup;
each startup request receives its remaining budget. Ownership checks during model
polling are throttled to five seconds; effect commits still independently fence
ownership and time. The actual installed Codex app-server was initialized with an
empty temporary CODEX_HOME and an already exhausted startup budget. It sent only
`initialize` and `initialized`, then its owned process was terminated during
cleanup (exit code 1). This verifies no thread/turn request was sent in that case;
it is neither a model execution nor human acceptance (`native-codex-startup.json`).
Protocol reference: [official App Server documentation](https://learn.chatgpt.com/docs/app-server).

The final review (`claude-final.md`) additionally found a missing-attempt legacy
row could escape containment and that large injected scheduling offsets could
inflate or immediately exhaust a lease. Claims now reject offsets beyond the
five-second host tolerance before any transaction. Missing attempt counters remain
unknown (`null` in time evidence); no attempt history is fabricated. The existing
notice quarantine retains the malformed source and an observable error event while
healthy work proceeds. Tests cover both invalid-lease and expired-deadline paths
against memory and actual PostgreSQL stores. Suspend-induced divergence is treated
as a discontinuity requiring investigation, not silently replenished elapsed time.

`claude-followup.md` confirmed both fixes and found one existing quota test used a
30-day future clock injection. Its failure is preserved in
`pre-usage-fixture-full-tests.log`. The test now persists a lease expired 30 days
ago, verifies a current-time claim does not alter the terminal row, and retains
the distinct occurrence and authorized new-task recovery assertions. This is an
explicit input fixture, not a claim of observing a 30-day host clock transition.
`source-manifest.json` records local Windows source/test file bytes; Git checkout
line-ending normalization can differ on Linux.

The bounded fixture review (`claude-fixture.md`) confirms the terminal quota row
is excluded by status before time evaluation. Root agrees this test demonstrates
terminal-state exclusion, not elapsed-time observation. The old injected-time
version reached the same status filter, so neither version demonstrated an actual
clock transition. Real deadline passage is covered separately by the PostgreSQL
child-process test, not inferred from this quota fixture.

Windows validation: Ruff passed; full suite 861 passed / 265 skipped;
actual PostgreSQL/Redis targeted suite 220 passed / 7 skipped. Skipped tests are
not acceptance evidence. Raw failed/superseded logs retain their original bytes,
including diagnostic trailing whitespace; source and prose whitespace are checked
separately. WSL and CI receipts will be attached against the committed source.
