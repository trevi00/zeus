# Service ownership 001 — implementation notes (owned background service tree)

Frame: `SPEC.md` in this directory, including its "Consolidated correction, 2026-09-19". First
candidate `27bd6ec`, base revision of this corrective pass `5597c81315a8086faa270cdb9e72f60aa9d5d773`
(the first candidate's own base was recorded as `c945a72a12b8917d0c701b86f62e7d56843a0d5b`).
Worker host: Linux (WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`), Python 3.13.15, pytest 9.1.1.
The native Windows checks below were **not executed here** and are listed as the owner's.

## What this pass changed, and what it is correcting

The first candidate was rejected on three confirmed findings, none of them a missing feature. They
are facts from executions, recorded in `SPEC.md` and in `artifacts/service-ownership-001/`
(`boundary-rprddrh5`, `boundary-wpcjq60r`); those were fault-injection runs, not production
incidents, and every probe-owned process was reclaimed.

1. **Opening a journal was taken as proof it writes.** Independent review found the gap and the
   owner reproduced it on Windows and on WSL: a journal that opens and then refuses writes let the
   child start anyway, so a service ran that no receipt accounted for. Corrected: the `starting`
   line is written **before** `ProcessTree.spawn`, and a failure there is 125 with zero spawns.
2. **The SIGTERM handler raised.** The owner reproduced an actual SIGTERM at the spawn handoff on
   WSL: the `_Terminated` unwind left the handoff with the processes already created and the
   ownership object not yet held — a 143 reported beside a live tree. Corrected: the handler records
   a flag and returns; nothing unwinds out of a signal at spawn, handoff, cleanup or final logging.
3. **A failed final receipt kept a nonzero child code.** Only `final == 0` was rewritten, so a child
   7 whose `shutdown` entry never reached the file still answered 7 — an unaccounted run reported as
   the child's own. Corrected: the same precedence is recomputed (124, then 130/143, then 125).

Accepted behaviour from the first candidate is preserved unchanged: the ProcessTree reuse, the exit
contract, the journal allowlist, the bounded 5 s + 5 s cleanup, and the native Windows tests.

Disposition: **reuse**. `adapters/process_tree.ProcessTree` is the authoritative ownership
mechanism (job object with `KILL_ON_JOB_CLOSE` on Windows, session process group on POSIX) and is
used unchanged — no edit to `process_tree.py`, no second Win32 binding, no upstream import. The new
`adapters/background_service.py` is the owner around it: spawn, wait, bounded cleanup, safe journal,
exit status. Nothing in providers, hooks, permissions or state contracts was touched.

Files (the three allowed, no others):

- `src/codex_harness/adapters/background_service.py` (new in the first candidate, corrected here)
- `tests/test_background_service.py` (new in the first candidate, regressions added here)
- `docs/zeus/operations/service-ownership-001/IMPLEMENTATION.md` (this file)

## `run_owned(argv, *, cwd=None, env=None, journal) -> int`

A successful `starting` entry, then
`ProcessTree.spawn(argv, cwd=cwd, env=env, stdin/stdout/stderr=DEVNULL)`, then the child wait, then
in `finally` `tree.terminate(..., timeout=5.0, settle=5.0)` followed by `tree.close()` — the close
is attempted even when terminate failed or was itself interrupted, because on Windows that close is
the kill-on-close boundary. No `shell=True`, no process-name or pid sweep, no retry of a failed
start, no unbounded wait anywhere.

### The deferred POSIX stop

POSIX only and main thread only: the `SIGTERM` handler sets `_Pending.stop_code` and returns. It
raises nothing, anywhere, so no stop can arrive in the middle of a spawn, a handoff, a cleanup or
the final entries. The owner then acts on it in its own code:

- immediately after `spawn` returns, before waiting — a signal delivered while the tree was being
  acquired is answered with the tree in hand, and the tree is reclaimed before 143 is returned;
- inside the wait, which is `process.wait(timeout=0.2)` in a loop (`WAIT_POLL`) while there is a
  flag to watch, so a service asleep for ten minutes is stopped one step after the signal rather
  than at the end of its sleep. With nothing to watch (Windows, off the main thread) it stays a
  single blocking `wait()` and costs no wakeups.

The previous handler is restored on the way out. A stop that arrives **after** the child's exit was
recorded, i.e. during cleanup or the final entries, does not change the answer: that run finished
and was accounted for, and the tree is reclaimed either way. This reading is tested. SIGKILL and a
descendant that calls `setsid` are outside the promise, as before, and Windows installs nothing.

### Exit contract

| answer | when |
|---|---|
| child's own code | only after cleanup was confirmed and no owner-side error |
| 124 | cleanup unconfirmed (terminate said so, raised, or `TreeOwnershipLeak` at spawn) |
| 125 | owner-side failure: journal open, the pre-spawn `starting` write, spawn, wait, or any later journal write |
| 130 | `KeyboardInterrupt` reached the owner |
| 143 | POSIX `SIGTERM` reached the owner |

Precedence, as written in `_final_code`: **124 first** (an unproven tree may never read as a
finished run), then 130/143, then 125, then the child's code. A `TreeOwnershipLeak` from `spawn` is
124 rather than 125: `ProcessTree` created a process it could not prove gone, and a second start
would add a second one to it, so there is exactly one attempt.

The same function decides twice. When the final `shutdown` entry does not reach the file, the code
is **recomputed** with that failure as the owner error, instead of the first candidate's rewrite of
`0` alone. So a child 7 with no final receipt is 125, while an unproven tree is still 124 and a
deliberate stop is still 130/143. Both of those are tested as controls beside the 0 and 7 cases.

### Journal

Rotating JSONL, 1 MiB, two backups (`logging.handlers.RotatingFileHandler`, the same mechanism
`codex_harness/monitor.py` uses). Fields are an allowlist — `timestamp`, `event`, `pid`,
`child_exit_code`, `final_exit_code`, `cleanup_confirmed`, `error_type` — and anything else a
caller passes is dropped rather than sanitized. Values must be `None`, a bool, an int or a short
token (`[A-Za-z0-9_.:-]{1,64}`). Never argv, env, exception text, or a raw `ProcessTree` receipt.

`logging` swallows write failures by default (it prints and carries on), so the handler's
`handleError` is replaced with one that raises `JournalWriteError` carrying only the failing class
name. Consequences: a journal that cannot be **opened** returns 125 and starts no child; a journal
that opens but refuses its **first line** also returns 125 and starts no child, because opening a
file is not writing to it — that assumption is exactly what was reproduced as a defect on Windows
and WSL; and a journal that fails **later** cannot skip the cleanup and cannot report success.

Events: `starting` first, written before anything is spawned; then either `start_failed`,
`start_leaked` or `start_interrupted` (no child running), or `startup`, `child_exited`, `cleanup`
and `shutdown`. Only `startup` carries a pid, which still follows ownership rather than preceding
it. `cleanup` and `shutdown` are this owner's own observations,
not the operating system's: an owner killed outright never writes them, and on Windows what ends
the tree then is the OS closing the job handle, which nothing on this side is alive to see. The
absence of `shutdown` is therefore not evidence of a failed cleanup, and the tests assert its
absence exactly where the owner was killed.

## Tests: `tests/test_background_service.py` (25 collected)

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
- **new** — the `starting` receipt is read out of the journal file by a `Popen` recorder *at the
  moment of the spawn*: the observed events there are exactly `["starting"]`, so the order is
  observed rather than inferred from the finished file, and the `startup` pid follows it;
- a missing program → exactly one `Popen` attempt, 125, `start_failed` naming the class only and
  not the path;
- one child only, never through a shell, stdio `DEVNULL` (a `Popen` recorder that still starts the
  real child): "no arbitrary process scan or shell expansion".

Labelled fault injection (not OS failures; each is named as an injection in the test):

- `terminate` rewritten to answer `confirmed: False`, and `terminate` raising — both after the real
  cleanup ran, so nothing leaks. Both give 124, both still close the handle, and the recorded call
  is `(5.0, 5.0)`: the bounded waits are asserted, not assumed;
- `spawn` raising `TreeOwnershipLeak` → 124 and exactly one attempt;
- **new** — a journal that opens and then refuses its first line → 125 with **zero** `Popen`
  attempts recorded, no readiness marker, the child lock free and the file with no entries at all;
- the journal stream refusing writes from `child_exited` on → 125, tree still reclaimed;
- **new** — the same refusal at `shutdown` only, for a child that exited **0 and 7**: 125 in both
  cases, with `child_exited` showing the child's real code and `cleanup` confirmed. Two controls
  beside it: the same failed `shutdown` with an injected unconfirmed `terminate` is still 124, and
  with an injected `KeyboardInterrupt` is still 130;
- `KeyboardInterrupt` injected into the wait with the whole tree up → 130, tree gone,
  `child_exit_code: null` in the receipt;
- SIGTERM handler restored after the run; the installed handler is then **called directly** and has
  to return `None` rather than raise; and a run off the main thread installs nothing, does not fail,
  and still reclaims its tree.

Native POSIX with real signals (ran here). Three of these deliver an actual `SIGTERM` with
`os.kill` into this process while `run_owned` is running — only the moment of delivery is chosen,
and each refuses to signal unless the owner's own handler is installed:

- **new** — at the spawn handoff: the whole tree is up, the real `ProcessTree.spawn` has produced
  it, the signal is delivered, and the wrapper still reaches its own next statement (proof that
  nothing unwound out of the signal). Answer 143 **after** both locks are free and the child pid is
  gone, sentinel alive, handler restored, `shutdown` with `cleanup_confirmed: true` and
  `child_exit_code: null`. This is the WSL reproduction, in the suite;
- **new** — during an ordinary wait on a child that sleeps 600 s: the owner's own wait call is
  recorded and its timeout is finite (`0.2`), the run answers 143 in seconds rather than waiting the
  sleep out, locks free, sentinel alive, handler restored;
- **new** — during cleanup, after the child's 5 was already recorded: nothing raises through the
  cleanup and the answer stays the child's 5 with the tree gone. That is the documented reading of
  a stop that arrives once the run is finished and accounted for;

and, with `run_owned` in a **real owner process** so the owner can be stopped the way an OS stops it:

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

## Executed here and observed (this corrective pass)

```
python -m pytest tests/test_background_service.py tests/test_background_processes.py -q -p no:cacheprovider
```
**41 passed, 4 skipped** in about 14 s, run twice with the same result. The skips are unchanged:
1 Windows-only test in the new file, 3 pre-existing Windows console tests in
`test_background_processes.py`. The first candidate's run of the same command was 33 passed,
4 skipped; the 8 additional passes are the new regressions listed above (the two journal-order
tests, the 0/7 parametrisation and its two precedence controls, and the three real-signal tests).

```
python -m pytest tests/test_background_service.py -q -p no:cacheprovider
```
24 passed, 1 skipped, and the same file run with `-v` to confirm by name that each new test ran
rather than was skipped.

```
python -m ruff check .
```
`All checks passed!`

## Not run by this worker

- The whole suite and repository CI (this worker was limited to the two commands above).
- Every native Windows check: the abrupt-owner-stop test in this file, the scheduled-task canary,
  and the deployment steps in the SPEC (`background-entry.pyw` importing `run_owned`, stopping the
  inventoried old trees, restart with fresh HTTP/PG snapshots). No service, Docker or Git command
  was run here. The owner's Windows evidence for the **first** candidate — 35 focused passes with
  2 POSIX skips, and the scheduled-task canary passing twice with held owner/child/grandchild
  handles, a released lock, sentinel survival and no manual recovery — is the owner's, recorded in
  `SPEC.md`; it is not restated here as a worker observation, and it predates the three changes
  above, so the owner's native re-run at the final candidate is still required.
- **No execution of the new regressions against the pre-correction module.** The intended check was
  a disposable copy of `src/` outside the working tree with the three changes reverted; the
  command was denied by this session's tool policy (no approval surface), and no second route was
  attempted, since writing such a copy inside the repository would leave files outside the three
  allowed paths. What the new tests would observe against the old code is therefore reasoning, not
  an observation: the old code wrote nothing before `spawn` (so `at_spawn == [[]]`), raised
  `_Terminated` out of the handoff, waited with no timeout (so the recorded timeout is `None`) and
  answered `7` for the failed final receipt. A reviewer with shell access can run that check.
- No mutation of the base tree in any other form; the POSIX SIGKILL test remains the in-suite
  control that an unowned tree does survive and does keep the lock.

## Limits and deviations

- POSIX is not Windows parity and is not claimed to be: after `SIGKILL` of the owner nothing runs to
  signal the group, and a descendant that calls `setsid` has already left it. Both are in the module
  docstring. Only the **SIGKILL** limit is executed as a test; the `setsid` escape is a documented
  limit that no test in the first submission or in this one exercises. The earlier wording, "both
  are tested as limits", overstated that and is corrected here.
- The deferred stop is what a POSIX signal can be relied on to do, and no more. It needs the main
  thread (`signal.signal`), so an off-main-thread run installs nothing and says so; Windows installs
  nothing and relies on the job handle instead; and a stop that arrives after the child's exit was
  recorded is answered as the finished run it is, not as a 143.
- What the tests observe about processes is scoped to the processes they started: the locks, the
  readiness markers, the owner's own child pid from its `startup` entry and one sentinel of their
  own. There is no host-wide pid or process-name inventory anywhere in the tests or in the module,
  so nothing here says anything about other processes on the machine.
- 124 reports what was true when cleanup was asked. The handle close that follows may still end
  members on Windows, but there is no handle left to observe it through, so the answer stays 124.
- One owner run per process: the journal is a single named logger, as in `monitor.py`. Each launch
  still owns its own job or group; nothing here can terminate another owner's tree.
- No contract ID was added to `docs/contracts.md` (outside the allowed paths); the code cites this
  SPEC by path instead.
- `process_tree.py` is untouched, as required, and no probe or experimental code from the reproduction
  runs was carried into the module. The only new module-level constant is `WAIT_POLL = 0.2`.
