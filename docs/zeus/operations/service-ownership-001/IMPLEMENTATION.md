# Service ownership 001 — implementation notes (owned background service tree)

Frame: `SPEC.md` in this directory. Base revision `c945a72a12b8917d0c701b86f62e7d56843a0d5b`.
Worker host: Linux (WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`), Python 3.13.15, pytest 9.1.1.
The native Windows checks below were **not executed here** and are listed as the owner's.

Disposition: **reuse**. `adapters/process_tree.ProcessTree` is the authoritative ownership
mechanism (job object with `KILL_ON_JOB_CLOSE` on Windows, session process group on POSIX) and is
used unchanged — no edit to `process_tree.py`, no second Win32 binding, no upstream import. The new
`adapters/background_service.py` is the owner around it: spawn, wait, bounded cleanup, safe journal,
exit status. Nothing in providers, hooks, permissions or state contracts was touched.

Files (the three allowed, no others):

- `src/codex_harness/adapters/background_service.py` (new)
- `tests/test_background_service.py` (new)
- `docs/zeus/operations/service-ownership-001/IMPLEMENTATION.md` (this file)

## `run_owned(argv, *, cwd=None, env=None, journal) -> int`

`ProcessTree.spawn(argv, cwd=cwd, env=env, stdin/stdout/stderr=DEVNULL)`, then
`tree.process.wait()`, then in `finally` `tree.terminate(..., timeout=5.0, settle=5.0)` followed by
`tree.close()` — the close is attempted even when terminate failed or was itself interrupted,
because on Windows that close is the kill-on-close boundary. No `shell=True`, no process-name or
pid sweep, no retry of a failed start, no unbounded wait anywhere.

POSIX only and main thread only: `SIGTERM` is installed as a handler that raises a private
`_Terminated` (a `BaseException`, so a deliberate stop is not an `Exception`), which unwinds the
wait into the same `finally`; the previous handler is restored on the way out. Off the main thread
and on Windows nothing is installed and the run proceeds unchanged.

### Exit contract

| answer | when |
|---|---|
| child's own code | only after cleanup was confirmed and no owner-side error |
| 124 | cleanup unconfirmed (terminate said so, raised, or `TreeOwnershipLeak` at spawn) |
| 125 | owner-side failure: journal open, spawn, wait, or a journal write |
| 130 | `KeyboardInterrupt` reached the owner |
| 143 | POSIX `SIGTERM` reached the owner |

Precedence, as written in `_final_code`: **124 first** (an unproven tree may never read as a
finished run), then 130/143, then 125, then the child's code. A `TreeOwnershipLeak` from `spawn` is
124 rather than 125: `ProcessTree` created a process it could not prove gone, and a second start
would add a second one to it, so there is exactly one attempt.

### Journal

Rotating JSONL, 1 MiB, two backups (`logging.handlers.RotatingFileHandler`, the same mechanism
`codex_harness/monitor.py` uses). Fields are an allowlist — `timestamp`, `event`, `pid`,
`child_exit_code`, `final_exit_code`, `cleanup_confirmed`, `error_type` — and anything else a
caller passes is dropped rather than sanitized. Values must be `None`, a bool, an int or a short
token (`[A-Za-z0-9_.:-]{1,64}`). Never argv, env, exception text, or a raw `ProcessTree` receipt.

`logging` swallows write failures by default (it prints and carries on), so the handler's
`handleError` is replaced with one that raises `JournalWriteError` carrying only the failing class
name. Consequences: a journal that cannot be **opened** returns 125 and starts no child; a journal
that fails **later** cannot skip the cleanup and cannot report success — if the run would otherwise
have been 0 and the final `shutdown` entry does not reach the file, the answer is 125.

Events: `start_failed`, `start_leaked`, `start_interrupted` (no child running), then `startup`,
`child_exited`, `cleanup`, `shutdown`. `cleanup` and `shutdown` are this owner's own observations,
not the operating system's: an owner killed outright never writes them, and on Windows what ends
the tree then is the OS closing the job handle, which nothing on this side is alive to see. The
absence of `shutdown` is therefore not evidence of a failed cleanup, and the tests assert its
absence exactly where the owner was killed.

## Tests: `tests/test_background_service.py` (17 tests)

Every tree is real: a child takes an OS file lock, starts a grandchild that takes a second lock and
sleeps, and then exits or stays. **The released lock is the evidence** — a lock is free only when
its holder no longer exists, while a pid can be reused and `os.kill(pid, 0)` on Windows terminates
rather than asks. An unrelated sentinel process runs beside every tree and must be alive at the end.

Real runs on this host (portable):

- child exit code 0 and 7 preserved, with a grandchild that outlived its parent reclaimed
  (the observed defect in miniature), sentinel alive, four journal events in order;
- journal privacy: a canary environment value, the script name, the working directory and
  `sys.executable` are absent from the file, and every entry's keys are within the allowlist;
- a journal path that cannot be opened → 125 and no child ever ran (no readiness marker, lock free);
- a missing program → exactly one `Popen` attempt, 125, `start_failed` naming the class only and
  not the path;
- one child only, never through a shell, stdio `DEVNULL` (a `Popen` recorder that still starts the
  real child): "no arbitrary process scan or shell expansion".

Labelled fault injection (not OS failures; each is named as an injection in the test):

- `terminate` rewritten to answer `confirmed: False`, and `terminate` raising — both after the real
  cleanup ran, so nothing leaks. Both give 124, both still close the handle, and the recorded call
  is `(5.0, 5.0)`: the bounded waits are asserted, not assumed;
- `spawn` raising `TreeOwnershipLeak` → 124 and exactly one attempt;
- the journal stream refusing writes from `child_exited` on → 125, tree still reclaimed;
- the same refusal at `shutdown` only → 125 rather than the child's 0;
- `KeyboardInterrupt` injected into the wait with the whole tree up → 130, tree gone,
  `child_exit_code: null` in the receipt;
- SIGTERM handler restored after the run, and a run off the main thread installs nothing, does not
  fail, and still reclaims its tree.

Native POSIX (ran here), with `run_owned` in a **real owner process** so the owner can be stopped
the way an OS stops it:

- `SIGTERM` to that owner → owner exits 143, child and grandchild gone, both locks free, sentinel
  alive, `shutdown` records `final_exit_code: 143`, `cleanup_confirmed: true`;
- `SIGKILL` of that owner → the documented limit, shown rather than assumed: the tree survives, the
  grandchild's lock stays held, no `shutdown` entry. The test then ends that tree by its own process
  group and asserts the lock frees, which is also the positive control for the lock evidence used
  everywhere else in the file.

Native Windows (skipped here with the reason "job-object kill-on-close is a Windows fact" — a skip
is not a pass): the owner process is terminated with `TerminateProcess` while the tree is up; child
and grandchild locks must both become free, the sentinel must survive, no `shutdown` entry may
exist, and the next owner must then start and its child take the released lock (exit 0).

## Executed here and observed

```
python -m pytest tests/test_background_service.py tests/test_background_processes.py -q -p no:cacheprovider
```
33 passed, 4 skipped. The skips: 1 Windows-only test in the new file, 3 pre-existing Windows console
tests in `test_background_processes.py`.

```
python -m ruff check .
```
`All checks passed!`

## Not run by this worker

- The whole suite and repository CI (the task limited this worker to the two files above).
- Every native Windows check: the abrupt-owner-stop test in this file, the scheduled-task canary,
  and the deployment steps in the SPEC (`background-entry.pyw` importing `run_owned`, stopping the
  inventoried old trees, restart with fresh HTTP/PG snapshots). No service, Docker or Git command
  was run here.
- No mutation of the base tree to prove the portable tests fail without the fix; the POSIX SIGKILL
  test is the in-suite control that an unowned tree does survive and does keep the lock.

## Limits and deviations

- POSIX is not Windows parity and is not claimed to be: after `SIGKILL` of the owner nothing runs to
  signal the group, and a descendant that calls `setsid` has already left it. Both are in the module
  docstring and both are tested as limits.
- 124 reports what was true when cleanup was asked. The handle close that follows may still end
  members on Windows, but there is no handle left to observe it through, so the answer stays 124.
- One owner run per process: the journal is a single named logger, as in `monitor.py`. Each launch
  still owns its own job or group; nothing here can terminate another owner's tree.
- No contract ID was added to `docs/contracts.md` (outside the allowed paths); the code cites this
  SPEC by path instead.
