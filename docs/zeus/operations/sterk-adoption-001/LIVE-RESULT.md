# Fixed-scope live monitor — owner acceptance

The monitor is running on Windows at http://127.0.0.1:8788. Its fixed scope is PostgreSQL public,
Redis namespace `zeus`, `zeus-ticket-ledger` and `zeus-local-ops-redis`. Historical isolated schemas
are excluded explicitly, not silently imported. Existing harness-console retains port8787.

Runtime: `D:/workspaces/zeus/artifacts/live/r`. Code was deployed for acceptance from candidate
`93d928deac790dec8c96a5bf3711425768e16376` (runtime implementation `9bc1f18`); final main promotion
and CI evidence are recorded in the PR. The active C repository and its ticket artifact paths
remain in place. Credentials and the machine call ledger were not moved.

## Completed acceptance

- Two actual Zeus assignments: isolated Claude implementation and independent Codex review,
  followed by one test-contract correction/review pair. Both operations accepted; four calls,
  ledger127 ->131. No automatic retry, fabricated completion, GitHub authority granted to workers,
  or provider call from the monitor.
- Owner ran the corrected monitoring/measurement tests: **35 passed** on Windows Python3.14.
  Independent review preserved the first runtime acceptance and checked the correction seam.
- Real PG, Redis and named Docker sources return `ok`. The browser displays actual assigned work
  and reviews. `flexday-pg` and transient worker containers are outside the named scope.
- Real owned-process termination: collector PID5560 ->4900 in26.84s; web PID4616 ->12632 in17.99s.
  One launcher and one actual Python leaf per role after recovery. Venv forwarding processes are
  not counted as additional collectors. Scheduler's recurring trigger/restart settings provided
  recovery; this does not isolate which scheduler mechanism fired first.
- Browser observed collection become stale/unknown after collector termination, then fresh again.
  Actual Chromium screen and HTTP API verified. No browser runtime errors observed. A separately
  labelled controlled renderer input confirmed a2020 metric remains historical despite fresh
  source state; no synthetic metric was written to PG or the live snapshot.
- Deliberately nonexistent named-container read returns Docker unavailable while actual PG/Redis
  remain ok. This used read commands only and changed no containers.
- Repeated live collection left all875 public document bodies, zero metric observations, all282
  artifact bodies and machine call count unchanged (hashes, not merely file counts). Snapshot
  timestamps advanced. Existing621 ticket-related records also retained their original hashes.
- Current-user Windows tasks `ZeusMonitor-collect` and `ZeusMonitor-web` have logon triggers,
  IgnoreNew, no execution time limit, three one-minute failure restarts and a one-minute recurring
  trigger. Logs/snapshots and task definitions are on D. Startup succeeds with provider auth env
  removed. Collector log rotates at1MiB with two backups; only state changes and safe event fields
  are written.

## Failures and limits

The first scope omitted an existing test that expected the monitor to manufacture observations.
Owner reproduced its failure, expanded the same frame by that test file, and obtained one correction.
The original Measurements producer remains available and independently tested.

The owner wrapper's final secret scan hit the active collector lock and raised PermissionError
after the correction operation had already accepted and settled both slots. The original partial
wrapper receipt remains intact. A separate postprocessing receipt scanned21970 files with zero
exact-token matches, excluded only the active collector lock and made no model call. This is
postprocessing recovery, not a replay of work. The earlier draft scan excluded all `.lock` files;
the retained final scan narrows that exclusion to the actual locked collector file.

Actual logoff/reboot was not performed. Current-user tasks require a logged-on user and reachable
Docker services. This is persistent monitoring of the fixed operating scope, not a claim that all
historical work is visible or that unrestricted unattended execution/promotion is enabled. No
deployment-health row exists; the screen correctly says that operating health is unknown.

## Operator paths

Launcher: `D:/workspaces/zeus/artifacts/monitor-live-001/launch-monitor.ps1`.
Registration: same directory's `register-monitor.ps1`. They use the existing C repository for
configuration, process-only runtime/Redis overrides, and no credential copies. After merge, use
the accepted main source path as CodeRoot. No global `.env` runtime rewrite was made because old
ticket artifact references may still rely on its original runtime directory.

To pause this deployment, disable and stop only `ZeusMonitor-collect` and `ZeusMonitor-web`.
To resume, enable/start those two tasks. Preserve the D runtime/evidence. Rollback never requires
deleting PG rows, Redis messages, old schemas or unrelated harness tasks. Recovery was executed;
full deployment rollback was documented but not executed.

Small evidence summaries/hashes: `live-evidence-summary.json`. Raw evidence stays on D. CI and
exact merge/main promotion results are recorded in the PR and implementation issue #136.
