Agreed on scope, ticket revision, and the QEMU correction. Concerns worth fixing before code:

**1. "Single-thread child" is the weakest link.** A .NET/JVM child is never single-threaded (GC, finalizer, timer pools), so `SuspendThread` on the main thread leaves heartbeats running and the test silently proves nothing. Use a tiny native exe (or suspend every thread enumerated for that PID). Also: suspend counts are recursive, so the watchdog must `ResumeThread` in a `finally` *and* kill — an aborted run otherwise leaves a wedged thread. Keep the `GetProcessIdOfThread` owner check as the guard against TID reuse; that part is right.

**2. WSL boot ID is not host-reboot evidence.** `/proc/sys/kernel/random/boot_id` rotates on a bare `wsl --shutdown` or VM idle-collapse. It must be conjoined with, never substituted for, `LastBootUpTime`. Related: on Win11 fast startup, a *shutdown+power-on* may not advance `LastBootUpTime`; only a **Restart** reliably does. Document that the manual step is "restart", or the fixture will read as "waiting" and fail its own criterion.

**3. Old-lease rejection is trivially satisfiable.** Any real reboot burns minutes, so if the lease TTL is shorter, expiry alone explains the rejection and the test says nothing about fencing. Either set the fixture lease TTL longer than the expected downtime, or assert on the fencing token/owner-epoch mismatch specifically, and record which mechanism rejected it.

**4. 12s proves duration, not suspension semantics.** Fine as designed, but the manifest should state in-band that 2/12s are *not* sleep evidence, so revision-1 style reuse can't happen. Also the lease TTL under test must be low enough that 12s actually crosses a deadline — otherwise both durations are the same test.

**5. Handshake race.** "After DB tx released" needs the connection actually returned to the pool and the handshake file flushed/closed before the signal, or the suspender can land mid-commit. Assert on observable release (pool count / tx state), not on method return. Watchdog bound must exceed pause + startup slack, else it becomes the flake.

**6. PG restart test.** Requires a *named* volume (anonymous volume + `docker stop/start` masks the persistence claim), and rediscovery must run through production port-resolution code — if the test re-reads the mapped port itself, it validates the test harness only.

**7. Fixture hygiene.** Credential file outside tmp must be gitignored and label-disjoint from the disposable suite, or cleanup will cross-delete.

No auto reboot/sleep/`wsl --shutdown` — agreed.