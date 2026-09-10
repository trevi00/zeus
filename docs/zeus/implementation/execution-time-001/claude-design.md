Read-only review; no edits or execution.

## FA017 — time contract design review

### Confirmed bugs

**1. Durable deadline unenforced after claim.** `workflow.py:107,114` and `executor.py:485,489` check `execution_deadline` only at claim. `_owned` (`workflow.py:143`) and `heartbeat` (`:155`) check only `lease_until`. `Executor._run` renews every 20s via `observe` (`executor.py:221`), so a task claimed one second before its deadline runs and renews indefinitely. The durable deadline is advisory once execution starts — the central defect, and no aware-timestamp fix touches it.

**2. Unguarded `lease_until` parsing in global scans.** `workflow.py:84,90,151` and `executor.py:456,462` call `datetime.fromisoformat(row["lease_until"])` bare. Null or malformed values raise `TypeError`/`ValueError`, not `ContractError`, from inside the transaction — before the per-row `try` blocks, so `block_execution` is unreachable. One poisoned row in `tasks` or `decisions_pending` stalls claim and `decide_one` for *every* agent. Note the asymmetry: `deadline_time` (`execution_budget.py:19`) guards exactly this and returns a typed error; leases don't.

**3. Wall-clock rollback extends ownership.** `lease_until` is pure UTC wall clock. A backward step (NTP correction, VM snapshot restore, WSL2 clock drift after Windows sleep/resume) keeps `lease_until > now` true beyond real elapsed lease time — a dead owner looks live, and a live owner's effective lease silently grows. A forward step does the inverse: spurious `lease_expired` outcome plus generation bump (`workflow.py:105,134`) while the prior process still holds file handles. Nothing observes the discontinuity.

**4. Two unreconciled clocks.** `app_server.py:123,168,182` correctly use `time.monotonic()` — immune to steps — but its `timeout=240` budget and `_run`'s `elapsed_seconds` (`executor.py:249,263`) are wholly independent of `execution_deadline` and of `lease_seconds`. Neither bounds the other.

**5. Rollback coupling.** Both stores commit all-or-nothing (`store.py:40-44`, advisory-locked Postgres tx at `:88`). Fencing writes and their `execution_notice`/`events` records are correctly atomic, but a raise anywhere in the loop discards the whole batch. Digest-keyed event IDs make replay idempotent, so this is survivable — provided bug 2 is fixed so the raise stops being routine.

### Proposed boundaries

**`ExecutionClock` port** exposing `wall() -> aware UTC` and `elapsed() -> monotonic float`, plus `host_id`/`boot_id`. Inject into `WorkflowService` and `Executor`; every `now` argument becomes explicit clock use. Tests supply a fake clock that can step wall and monotonic independently — that is the only way to test discontinuity; fixtures pinning `utcnow` cannot.

**Lease value object:** `{owner, lease_until, lease_epoch, granted_wall, granted_monotonic, host_id, boot_id}`. Validity is asymmetric and must stay so: the *owner* validates via monotonic elapsed (authoritative, step-immune); a *foreign claimant* validates via wall clock only, because monotonic is meaningless across hosts or reboots. Trust `granted_monotonic` only when `host_id` and `boot_id` match the current process.

**Discontinuity handling:** on each heartbeat compare Δwall against Δmonotonic; beyond tolerance, emit `execution.clock_discontinuity`, **refuse renewal**, and require re-acquisition through CAS on `(generation, lease_epoch)` — reuse `execution_recovery`'s existing CAS shape (`execution_recovery.py:220`), don't invent a second one.

**Isolation:** add `lease_time()` mirroring `deadline_time`; malformed → treat as expired and `block_execution` that row only.

**`_owned` must also re-check `execution_deadline`**, terminating in-flight work at expiry.

**Legacy:** rows lacking `lease_epoch`/`granted_monotonic` → epoch 0, wall-only validation, no block.