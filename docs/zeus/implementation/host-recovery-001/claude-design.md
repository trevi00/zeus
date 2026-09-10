## Read‑only design review — host/service interruption acceptance for GH18

### What the code already guarantees (no new test needed)

Two independent bases exist. Wall deadline (`execution_time.py:38`) is domain‑free and survives any process death; the monotonic budget (`:40`, `:71`) is subtracted **only** within `DOMAIN`, so a new PID gets `elapsed is None` and falls back to UTC — exactly the `utc_foreign_or_legacy` basis asserted at `test_execution_time.py:175`. Injected wall time cannot buy budget (`workflow.py:90`, `pin_clock` overwrites `now`), so mock‑clock proofs are structurally impossible here — good. Stale resume is fenced by `_same_execution` (`workflow.py:182`) plus `active()`, and reclaim bumps `generation`/`attempt` (`:168`).

### True remaining safety gaps (not "approval‑only")

1. **Suspend semantics differ per OS and are unmeasured.** Windows `time.monotonic()` (QPC) keeps advancing while a child is suspended; Linux `CLOCK_MONOTONIC` stops across host suspend‑to‑RAM. On WSL after a real sleep, `elapsed < delta_wall` by the sleep duration ⇒ `abs(delta_wall - elapsed) > 5` ⇒ `ClockDiscontinuity` ⇒ `blocked` needing operator repair. Fail‑safe direction, but an unmeasured availability behaviour on the target host.
2. **Store has no reconnect policy.** `store.py:89` opens a fresh connection per transaction, `connect_timeout=5`, no retry; a container stop mid‑workflow surfaces as `OperationalError`, which is **not** a `ContractError`/`ExecutionTimeError`, so `_execution_transaction` does not contain it. Whether any partially‑applied state can exist is unproven.
3. **A pure IO stall must never mint a clock event.** `test_real_pg_lock_wait_is_not_a_clock_step` covers lock waits only; container pause/unpause exceeding `lock_timeout` is the harder case and is untested.
4. **Resume of a genuinely suspended lease holder** is untested; restart‑of‑new‑process is (`:137`).

### Minimal finite acceptance for single‑host use

A dedicated disposable container (own name + volume, never `zeus-ticket-ledger`) with its own fixture — do not extend `isolated_pgstore`, whose `DROP SCHEMA` teardown (`conftest.py:36`) will itself fail once the container is stopped; the new fixture must own container lifecycle and tolerate a dead server at teardown.

Then four observations, each ending in a **new process** re‑reading the row: (a) container stop/start across a real short deadline → row `expired`, `result is None`, exactly one time event/notice; (b) pause/unpause shorter and longer than `lock_timeout` → no `execution_time_events` when the deadline was not crossed; (c) native Windows child suspend/resume across a real deadline → resumed child's `complete`/`heartbeat` rejected; (d) WSL child `SIGSTOP`/`SIGCONT`, same assertions, recording whichever of `deadline_exceeded` / `ClockDiscontinuity` actually occurs rather than asserting a preferred reason. Label all four **process/service interruption** — they are not sleep, reboot, or VM‑resume evidence.

### Host‑cycle fixture (arm now, verify after a real restart)

Persist outside `tmp_path`: task id, `generation`, `attempt`, `recovery_sequence`, artifact ref, DSN/container id, plus before/after boot ID (`/proc/sys/kernel/random/boot_id`; Windows `LastBootUpTime`), UTC wall, and `time.monotonic()`. Verification must **skip, not pass**, when the recorded boot ID is unchanged — that is what stops a fake proof. Nothing should shut down WSL/Docker or restart the PC.

### Clock step

Docker shares the host `CLOCK_REALTIME`; `SYS_TIME` mutates the host, and there is no realtime namespace. Only a Hyper‑V VM with time sync disabled would be proof. Recommendation: keep `test_clock_comparison_contract` and the record‑perturbation test as *contract* coverage, and state plainly in GH18 that an OS‑level clock step has **not** been observed on this host.