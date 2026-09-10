## Verdict

One concrete blocker; everything else is arm-ready. The trial receipt and cutover ledger match the claims you made (unchanged-boot returns `waiting_…` with no workflow writes, cancel stopped both real workers then dropped the schema, both workers loaded hash `0a048aef…` matching state, `sequences: []` with an explicit `sequence_scope`, no reboot/sleep/clock claim anywhere).

### Blocker — `verify()` line 238 stale-owner shortcut can dead-end the one-shot evidence

```python
claimed = row if row['lease_owner'] == owner else w.claim(previous['agent'], owner, lease_seconds=120)
```

The shortcut tests only `lease_owner`, not liveness. If a verify run crashes/is interrupted after `w.claim` (line 238) and the 120 s lease then expires, every later verify run takes the shortcut again — `row['lease_owner']` is still `after-actual-restart-<run>` and the row is still `running` — so it never re-claims, and `w.complete(claimed, result)` (line 264) hits `_owned` → `require(active(...))` → `active` returns `until > now` = False → `ContractError: Stale or expired task execution`. Unhandled: the run is permanently unverifiable after a real restart, with cancel the only exit. 120 s is short enough that an operator closing the terminal or a Docker hiccup mid-verify reaches this. Fix is local: take the shortcut only when the lease is still live (`row.get('lease_until')` in the future, mirroring the line 217 check), otherwise fall through to `w.claim`, which is already checkpoint-safe.

### Two post-transition asserts that convert a real restart into an unrecoverable run

Both are pre-arm checks, not code changes, if you'd rather not touch the flow:

- **3-hour worker lifetime vs. line 223.** After the cap, workers write `status: 'stopped'`, and `assert last_worker['status'] == 'heartbeating'` is a hard `AssertionError` with no `inconclusive` path. The restart must happen within 3 h of prepare; state that in the operator instruction.
- **Container auto-start, lines 205–209.** `assert after['container_started_at'] != before` requires Docker Desktop to bring `zeus-ticket-ledger` back. The container policy is `unless-stopped` (`ledger-fixed-port.json`), but `host()` never records `RestartPolicy` and prepare never gates on Docker Desktop's start-on-login setting. Confirm that setting before arming; otherwise the boot marker changes and the proof is lost to an assert.

More generally, every check from line 203 to 209 is an assert evaluated *after* the irreversible event. That's defensible for genuine contradictions (runtime hash changed, container replaced), but it means any environmental surprise burns the restart. Returning a `status: 'inconclusive_requires_inspection'` dict there — the pattern you already use at line 240 — would preserve retryability.

### Non-blocking, worth knowing

- `command(..., timeout=30)` on the first post-boot verify: `wsl` cold start or a not-yet-running Docker Desktop raises `RuntimeError`/`TimeoutExpired` before any boot comparison. Safe to re-run — no writes occur first — but tell the operator to expect it and simply retry rather than treating it as failure.
- A backwards NTP correction at boot larger than `CLOCK_TOLERANCE_SECONDS` (5) makes `check_clock` raise `ClockDiscontinuity`, blocking the task inside `claim`, which then returns `None` → `inconclusive_requires_inspection`. Graceful, not silent acceptance — correct behavior, just a plausible outcome to anticipate.
- Cross-process monotonic is not compared (`DOMAIN` is a per-process uuid4, `elapsed is None` for a foreign domain), so the reboot itself cannot manufacture a false clock event. That's the right property here.
- Line 259 rebuilds `checkpoint` rather than reusing the stored one on the resume path, so `last_worker_observation` in the returned receipt is re-read rather than the write-once value. Cosmetic; the durable file is unchanged.

The schema-fallback test is sound as written: it drops `documents` in a disposable database, requires `UndefinedTable` from `probe.claim`, and asserts `tx.records()` unchanged against a real public canary.