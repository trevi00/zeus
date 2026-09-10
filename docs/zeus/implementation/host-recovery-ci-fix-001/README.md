# Compose compatibility correction

The first CI run for c651ac4 (34434173814) passed the main integration suite
(1208 passed, 8 skipped), but the separate Docker step failed two new PostgreSQL
restart cases at `compose start --wait` (13 passed, 1 skipped). Local Windows and
Ubuntu use Compose 5.4.0; the exact GitHub runner image declares Compose 2.38.2.
Its start command lacks the wait option. The adapter masks subprocess stderr,
so the failed log records only the start operation; the compatibility diagnosis
is supported by the published implementations and runner inventory.

Root proposed the correction and the real local Claude CLI reviewed it. Root
replaced the restart command with `up -d --no-recreate --wait postgres`, retaining
the fixture's working health-wait path. Both tests now also assert the container
ID remains identical and record it in evidence. Assertions run after cleanup,
preserving primary failure reporting. No assertion was removed or case skipped
to hide the failure. CI prints its Compose version. Application source and the
Windows boot probe did not change.

The original evidence bundle remains historical. This directory records validation
of the compatibility fix. Host restart, sleep/resume and isolated real OS clock-step
acceptance remain unmeasured. Issue #18 stays open.

Primary sources:

- [Exact runner inventory](https://github.com/actions/runner-images/blob/ubuntu24/20260907.300/images/ubuntu/Ubuntu2404-Readme.md)
- [Compose 2.38.2 start](https://github.com/docker/compose/blob/v2.38.2/cmd/compose/start.go)
- [Compose 5.4.0 start](https://github.com/docker/compose/blob/v5.4.0/cmd/compose/start.go)
- [Compose 2.39.4 up](https://github.com/docker/compose/blob/v2.39.4/cmd/compose/up.go)

Local corrected-source validation: Windows targeted 66 passed; native Ubuntu interruption tests 6 passed. Windows full suite: 911 passed, 305 skipped. Final CI is recorded separately. The real Claude review is retained in `../host-recovery-001/claude-ci-fix.md` with its raw output and session receipt.
