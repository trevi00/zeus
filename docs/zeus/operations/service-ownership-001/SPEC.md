# Service ownership001: finish the observed restart gap

## Outcome and authorization

User authorized PR154 merge/deployment and the next bounded improvement, then explicitly prioritized
the reported problems. PR154 merged as a66a049507a6aaefc7c7c2cb55252e201ab0b0f8; its tree equals
accepted e16abdc. Deploy that change together with the accepted service ownership fix, avoiding two
maintenance restarts. Preserve the previous local-absorption001 acceptance; this is a new bounded
delivery, not a reopened BOM review. Claude Opus5 implements; Codex designs and independently accepts.
Subscription accounting remains unchanged. One implementation + one independent review, then pause.
Owner may merge/deploy the independently accepted fix after native checks/full suite/CI pass, within
the user's instruction to fix the observed operational problem. No automatic worker merge, extra
model retries, unrelated adoption, global hooks, credential/ledger movement or reboot.

Complete: existing ProcessTree owns background launcher descendants; native abrupt-owner-stop and
normal-exit checks pass; an owned temporary scheduled-task stop releases its descendants and lock;
actual services restart with fresh HTTP/PG snapshots and old known service processes absent; report,
CI and candidate provenance recorded; Fleet paused/idle, no model containers. If the one model batch
fails, preserve the failure and stop; do not silently expand into repeated calls.

## Evidence, SSOT and source-backed decision

Observed last batch: six old monitor descendants survived prior task restarts and retained the
collector lock. Exact process identities and manual cleanup are retained under
D:/workspaces/zeus/artifacts/local-absorption-001/retired-old-monitors.json and deployment.json.
The outer background-entry.pyw uses subprocess.run with no ownership object. Killing that Python
owner need not kill PowerShell or its children. This reachable boundary explains a mechanism;
the earlier process inventory traversal hang has no proven cause and is not part of this fix.

Local asset: docs/full-analysis/baldrix-gsd-runtime-001/resolution.md distinguishes parent lifetime,
descendant reaping and real cleanup evidence. That is prior analysis, not a fresh source execution.
Reuse the already implemented Zeus adapters/process_tree.py ownership mechanism; do not import
upstream code or duplicate Win32 bindings. A separate scan showed application/skill_history.py already
transactionally deduplicates observation IDs; the older domain-only trace is not a reachable new
duplication defect under that writer contract, so it is not selected as speculative work.

Primary source read2026-09-19: Microsoft Job Objects (last updated2025-07-14),
https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects . By default CreateProcess
descendants join the job; last-handle close with KILL_ON_JOB_CLOSE ends members; nested jobs exist
since Windows8. Existing ProcessTree creates suspended, assigns and resumes, uses no-console flags,
and keeps a non-inheritable kill-on-close job handle. These facts do not prove our scheduled-task
wiring; owner native tests must do so. POSIX process groups do not guarantee cleanup after owner
SIGKILL or escaped setsid descendants; document this limit rather than claim Windows parity.

## Complete path and implementation boundary

Windows scheduled task -> pythonw background-entry -> reusable background_service.run_owned ->
existing ProcessTree.spawn -> hidden PowerShell -> Python Fleet/monitor/observe -> owned descendants.
Normal child exit, exception or graceful interruption -> bounded tree termination/confirmation ->
close handle -> safe journal/exit. Windows abrupt owner death closes the sole job handle in the OS.
Do not touch authoritative tasks, leases, Redis, PG, provider boundaries or source file ownership.

Implement only:
- src/codex_harness/adapters/background_service.py: run_owned(argv, *, cwd=None, env=None, journal)
  returning an integer. No shell=True or process-name/PID sweep. Reuse ProcessTree unmodified;
  redirect stdin/stdout/stderr to DEVNULL because existing service launchers own output logs.
  Preserve child's normal exit code after confirmed cleanup. Use125 for startup/wait/journal errors,
  124 for unconfirmed cleanup (takes precedence), 130 for KeyboardInterrupt and143 for POSIX SIGTERM.
  Install/restore a SIGTERM handler only in the main thread on POSIX; cleanup in finally on every
  acquired-tree path, including journal failure. Always close the owned handle even if terminate
  fails. Reuse its finite terminate timeout5s + settle5s; do not add an unbounded cleanup wait.
  Before spawning, establish a rotating JSONL journal (1MiB, two backups). Allowed facts: event,
  timestamp, pid, child_exit_code, final_exit_code, cleanup_confirmed, error_type. Never serialize
  argv, env, exception text, raw ProcessTree receipt or credentials. Startup logging failure starts
  no child. Later journal failures must not bypass cleanup or report success. Hard owner kill cannot
  write a final receipt; distinguish owner-side observation from a journal shutdown entry.
- tests/test_background_service.py: actual subprocess/temporary-file tests and explicitly labeled
  fault injection for startup/cleanup/journal failures. Real Windows owner kill must demonstrate
  child and grandchild gone plus release of a FileLock, then successful next owner acquisition;
  preserve an unrelated sentinel process. Use bounded waits and finally cleanup only owned handles.
  Normal root exit with a surviving child must also be reclaimed. Native Windows checks skip
  explicitly elsewhere; portable normal-exit and safe-log checks run on Linux as well. Faults may
  inject ProcessTree methods/logger failures but do not label those actual OS failures.
- docs/zeus/operations/service-ownership-001/IMPLEMENTATION.md: exact commands, observed results,
  unrun Windows checks, deviations and limits. No guessed counts or runtime claims.

Owner deployment only, after acceptance: keep auth/control repo at C; use pinned D runtime; change
existing background-entry.pyw to import run_owned and call it for the same four existing argv lists.
Update only code roots in entry and observation launcher. Retain launchers before mutation; no task
definition changes needed. For this one migration, stop only the inventoried current owned service
trees while their parent identity remains observable; do not repeat a broad ancestor traversal.

## Fixed acceptance matrix and one batch

| Boundary | Acceptance |
|---|---|
| Normal success/nonzero | Child code preserved; descendants reclaimed before success |
| Abrupt Windows owner stop | Native held process handles signal; child/grandchild gone; lock reacquired |
| Graceful POSIX stop | SIGTERM handled and bounded cleanup; SIGKILL/setsid escape explicitly excluded |
| Start failure | No second start; sanitized failure, no orphan from acquired tree |
| Cleanup unknown/failure |124, handle close always attempted, no false success |
| Journal failure | Before spawn no child; after spawn cleanup still runs and no success |
| Isolation/scope | Unrelated sentinel survives; no arbitrary process scan or shell expansion |
| Visibility/privacy | Existing CREATE_NO_WINDOW preserved; no argv/env/canary in JSONL |
| Integration | Native temporary scheduled task Stop -> owned children gone -> next start gets lock |
| Deployment |154 + accepted fix pinned; fresh monitor, no old inventoried service PIDs; paused Fleet |
| Parallel/restart | Each launch owns its own job; no cross-owner termination or auto retry |

Worker runs focused tests/test_background_service.py tests/test_background_processes.py and ruff;
no whole suite or OS/service/Docker commands. Owner runs native focused tests, scheduled-task canary,
required full suite and repository CI. Preserve dirty C files, immutable evidence and previous
acceptance. Denied worker shell requests are protection events, not a request to weaken permissions.
Other asset absorption resumes after this observed restart problem is addressed.

## Consolidated correction, 2026-09-19

First operation ended rejected; counts229->231, no automatic retry. Candidate27bd6ec remains
evidence, not an accepted release. Owner Windows focused35 passed/2 POSIX skips and the actual
scheduled-task canary passed twice with held owner/child/grandchild handles, released lock, sentinel
survival and no manual recovery. The existing venv pythonw action worked in both trials; do not
change its executable on speculation. Preserve those accepted ownership observations.

One consolidated review adds no new feature. Independent Codex found the pre-spawn logging gap and
nonzero shutdown error precedence. Owner reproduced the logging gap on Windows and WSL, and an
actual SIGTERM at the spawn handoff on WSL. Raw injected receipts are in artifacts/service-ownership-001/
boundary-rprddrh5 and boundary-wpcjq60r. These are fault-injection executions, not production incidents.
Every probe-owned process was reclaimed. The assumption that opening a log proves it writable, and
that a raising cancellation handler is safe while an ownership object is being acquired, is false.

One corrective implementation/review pair is authorized within the same requested outcome. The
previous one-pair stop was a batch boundary, not a reason to leave this confirmed problem unresolved;
the rejected operation stays stopped, and a separately named corrective job supplies clear accounting.
Same three allowed paths, same runtime policy, no ProcessTree change and no added features.

Complete state design:
1. Establish and successfully write a safe `starting` receipt BEFORE ProcessTree.spawn. If that
   write fails, return125 with zero spawns. A pid-bearing startup record still follows ownership.
2. POSIX main-thread SIGTERM handler records cancellation; it MUST NOT raise during spawn/handoff,
   cleanup or final logging. After acquiring the tree, observe pending cancellation and use a
   bounded-poll wait (for example process.wait(timeout=0.2)) so a sleeping service responds promptly.
   Always reclaim the acquired tree before143. Restore the prior signal handler; off-main-thread
   and Windows ownership limits remain explicit. A signal between successful spawn and its return
   must not create a143 answer beside a live child. Do not extend POSIX guarantees to SIGKILL/setsid.
3. Recompute final error precedence for failed shutdown logging: unconfirmed cleanup124, explicit
   interruption130/143, owner/journal error125, otherwise child's original code. A child7 plus failed
   shutdown receipt must be125, not7. Preserve124 and130/143 when those already apply.

Regression: zero-spawn opened-but-unwritable journal; successful pre-spawn receipt and ordinary
events; real signal at a wrapped actual spawn return on POSIX with proven cleanup; ordinary waiting
SIGTERM/restoration; final-write failure with child0 and7 plus cleanup-unknown/interruption controls.
Retain native Windows tests and document owner scheduled-task evidence accurately. The independent
reviewer's missing-held-handle concern is covered by the owner canary, not an invented worker run.
Correct IMPLEMENTATION prose: opening alone was insufficient; raw PID/lock observations have the
scope tested; setsid escape is a documented limit, not a test executed in the first submission.
Do not add the root's experimental probe code to production. Run focused tests and lint; owner
rechecks affected interactions and whole suite/CI at the final candidate. No speculative new review
round after these explicit conditions pass.
