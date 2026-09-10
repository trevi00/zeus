Read-only review; nothing executed or edited.

## Fixes confirmed
`pin_clock` now samples wall+monotonic together on the host (execution_time.py:85-87), killing the injected-`now` discontinuity (finding 1). Containment identity is semantic (execution_time.py:116-117), so `observation`-bearing and `observation=None` paths collapse to one row per reason/execution and first evidence wins (finding 2). Decisions get a real deadline producer at executor.py:534-537, pinned once and reset only by `ExecutionRecovery.apply` — `_ceiling` (execution_recovery.py:134) blocks silent removal (finding 3).

## Blockers
**1. `row['attempt']` is hard-indexed (execution_time.py:116).** `generation` and `recovery_sequence` use `.get(..., 0)` precisely because this module is meant to tolerate legacy rows (`utc_validation_legacy`, observe_domain:109). A running row without `attempt` raises `KeyError` inside the `except ExecutionTimeError` handler in `running()` (:148-149), escaping containment and aborting the whole scan — the exact starvation that test_execution_time.py:70 exists to prevent. Use `row.get('attempt', 0)`.

**2. `pin_clock` re-samples wall but the lease it pins was computed from the caller's `now` (execution_time.py:84-98 with workflow.py:149-158, executor.py:533-545).** `lease_seconds = until - host_now` where `until` derives from the injected clock. `claim(now=+30s)` inflates the monotonic lease budget by 30s (test:19 only asserts the wall pin, not `lease_seconds`); an injected past `now` clamps it to `max(0, …) == 0`, so `active()` (:48) returns False on the first poll and `_owned` rejects the fresh lease as "Stale or expired" — silent, uncontained, no event. Clamp or reject `now` outside `CLOCK_TOLERANCE_SECONDS` of the host reading, or derive `until` from the host sample.

## Not blockers
- `require(... 'Conflicting execution time event')` (:121) is unreachable: `old` is built from the same `event` that produced the digest. Harmless, but the digest — not this check — is the sole protection.
- 5s tolerance vs. Linux `CLOCK_MONOTONIC` excluding suspend (and NTP steps) durably blocks running rows pending an operator packet (:72-76). Policy choice, worth documenting.
- Accepted as stated: UTC-only validation across process domains; no retention for `execution_time_events` (unbounded `cli inspect`); queue time consuming the pinned decision budget; `remaining_seconds` not subtracting its own commit latency.