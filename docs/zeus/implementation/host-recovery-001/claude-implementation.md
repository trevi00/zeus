## Read-only review — host-recovery-001

### Blocking (false acceptance)

**1. `search_path` includes `public` on the real ledger** (`scripts/host_cycle.py:80`). The probe schema is isolated only as long as every table resolves inside it. Any table missing from `host_probe_*` (partial `migrate()`, a table created outside the migration path) silently falls through to production `public`, and `w.claim(agent, owner)` at line 136/210 is **not id-targeted** — it selects whatever is claimable for that agent. On a live ledger that is a path to claiming and completing a real task. Use `options=-c search_path=<schema>` with no `public` fallback, and assert post-migrate that the required relations exist in the probe schema.

**2. The Windows gate cannot distinguish restart from shutdown/power-on** (`host_cycle.py:172-175`). `root-decisions.md:26` says shutdown/power-on is not to be labelled Restart, but `LastBootUpTime` changing is the only test, and it advances on hybrid-shutdown power-on too. The result is still emitted as `verified_actual_windows_restart`. Either capture an event-log discriminator or rename the status to what is actually measured (host boot transition).

**3. The WSL boot gate is non-evidentiary and probably unreachable.** `command(['wsl','-d','Ubuntu',...])` *starts* the distro if it is down, so `after['wsl_boot'] != before['wsl_boot']` (line 176) is satisfied by any `wsl --shutdown`, not by a host restart. Separately, the ledger is bound to `127.0.0.1:63556` on the Windows host (`ledger-fixed-port.json:5`); under default WSL2 NAT that address is not reachable from inside Ubuntu, so the WSL heartbeat worker will fail to connect at `prepare`. Confirm reachability before treating "two real workers" as satisfied.

**4. Resume path can deadlock verification.** Line 205-207: on the `succeeded` branch the resumed run asserts `row['lease_owner'] == owner`. If `complete()` clears `lease_owner`, verify can never finish and the checkpoint is unusable. Line 210's `claimed = row if row['lease_owner'] == owner else w.claim(...)` has the same dependency, and if the task landed terminal (`blocked`/`expired` — the native-pause test at `tests/test_host_interruption.py:139` shows both are reachable) `w.claim` returns nothing and `assert claimed` fails permanently. The pre-check loop (lines 187-191) only waits for *live* leases, not terminal states.

**5. Re-entry duplicates rejections.** Interruption between `write(checkpoint_path…)` (225) and `w.complete(claimed, result)` (226) causes a second `reconcile`, and the checkpoint is overwritten with a new `rejection_id`, discarding the first. Make the checkpoint write-once and skip reconcile when it exists.

### Cleanup

- **No schema drop anywhere.** `prepare`'s failure path (159-163), `cancel`, and `verify` all leave `host_probe_*` on the production ledger; only `verify` documents retention deliberately. Cancelled/failed runs accumulate.
- **FileLock covers only `verify`** (254). Concurrent `prepare` calls both pass the unfinished-cycle check (106-109) and overwrite `current.json`, orphaning workers and a schema. `cancel` is likewise unserialized.
- `status`/`cancel` read `current.json` unguarded (257) → traceback before any run exists; `cancel` doesn't wait for worker exit.
- Readiness loop (150-154) falls through to `read(...)` on timeout/child exit → `FileNotFoundError` instead of the captured stderr.
- `after['volumes'] == before['volumes']` (179) compares list order from two `docker inspect` calls; compare as a set.

### Evidence gaps in the completed migration

- `ledger-backup-verified.json` compares only `documents`/`knowledge_nodes`/`knowledge_edges` per schema. Task, lease, outbox and `execution_*` tables are absent, so "identical data restored" is verified for three table families only.
- `"sequences": []` makes `same_data_and_sequences: true` in `ledger-fixed-port.json` vacuous — nothing was compared. If the schema uses identity/serial columns, sequence positions are unverified.
- `rollback_container` shares `zeus-ticket-ledger-data` with the replacement, so it is a config rollback, not a data rollback, and starting it without stopping the replacement violates the one-postmaster rule in `root-decisions.md:35`.
- No post-cutover snapshot hash is recorded — only a boolean.

### Tests

Scoping and the "not host sleep" framing are consistent. Two weaknesses: the native-pause test accepts `status in {expired, blocked}` and records `reason` without asserting it (139-147), unlike the outage test's `deadline_exceeded` assertion; and three of four tests skip unless `ZEUS_TEST_DOCKER=1`, so acceptance needs the run log proving they executed.