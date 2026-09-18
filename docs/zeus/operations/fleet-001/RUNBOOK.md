# Local fleet operation

The registered `zeus-local-fleet` has two lanes: harness and interface. PostgreSQL owns admission
and outcomes; existing per-lane Operation/executor owns execution, Redis delivery, evidence and
review. Registration and a fresh team snapshot are NOT service-liveness signals.

## This host

- Control repository: `C:\Users\rudtn\zeus` (existing compatibility exception).
- Clean lane source repository: `D:\workspaces\zeus\worktrees\fleet-001`.
- Lane schemas: `zeus_fleet_harness`, `zeus_fleet_interface` (no public fallback).
- Runtime roots: `D:\workspaces\zeus\artifacts\f2h` and `f2i`; retain evidence.
- Definition: `D:\workspaces\zeus\artifacts\fleet-001\fleet.json` (no secrets).
- Service launcher: `D:\workspaces\zeus\artifacts\fleet-001\launch-fleet.ps1`.
- Task to install after acceptance: `ZeusFleet-run`, current user interactive/logon, hidden window.
- Team view: existing observatory `http://127.0.0.1:8788`, **팀 작업** after release.

The launcher decrypts the existing DPAPI token only in memory, passes it through the child
environment, and emits only bounded event/type logs. It never creates or updates a model budget.
The package CLI is portable; this scheduled-task deployment is Windows/current-login specific.
Reboot, logged-out operation and multi-host scheduling have not been demonstrated here.

## Admit the next bounded goal

Use the main environment interpreter from the control repository:

```powershell
Set-Location C:\Users\rudtn\zeus
.\.venv\Scripts\python.exe -m zeus fleet status
```

The delivery ends paused with total ceiling160 and160 counted machine slots. A new operator-authorized
batch first needs an explicit grant. For example, **only after authorizing four further calls** and
verifying there are no queued/owned/unknown jobs:

```powershell
.\.venv\Scripts\python.exe -m zeus fleet authorize-budget --per-host 164 --total 164 --expected-total 160
```

This example is not executed by the runbook or dispatcher. The existing machine ledger is never
reset; a grant updates effective ceilings and records prior/new values, preserving old manifests.
Pause remains set. A stale expected total or any queued/dispatching/unknown job refuses the grant.

Create owner-reviewed operation manifests with that effective budget, explicit goal criterion,
the clean lane repository's exact base SHA and goal-file digest, and bounded disjoint allowed paths.
Use Operation v2 when a preexisting DGE-approved design is required; v1 does not claim debate.

```powershell
.\.venv\Scripts\python.exe -m zeus fleet enqueue --lane harness --file D:\path\harness-operation.json
.\.venv\Scripts\python.exe -m zeus fleet enqueue --lane interface --file D:\path\interface-operation.json
.\.venv\Scripts\python.exe -m zeus fleet resume
```

The running service admits explicit jobs only. `--after <operation-id>` is an execution prerequisite,
not an automatic merge or base update. Independent namespaces and nonconflicting write scopes may
run together. New goals come from the existing analysis/SSOT programme; the dispatcher invents none.
Never update/move the lane source while a job is active. Owner integration/release remains ordered.

## Pause, stop and diagnose

`fleet pause` persistently stops new admissions; current owners may finish. Before maintenance,
pause and wait for all lane `active_job` values to become null. Stop/restart the scheduled task only
when idle. Its existence/running Task Scheduler state is host process evidence, not proof all jobs
are healthy. `fleet run --once` is an alternative bounded drain, not needed alongside the service.

An interrupted dispatching job or unknown outcome retains its lane/capacity/path reservation.
Inspect the exact lane Operation, execution artifacts and owned container before recovery; no
automatic takeover, timeout lease, blind row deletion or model retry is provided. The service does
not synthesize success from stdout or an empty queue. Terminal accepted means candidate review
accepted, not merged or deployed. Any release/issue closure is still Codex's evidence-bound judgment.

The team board reads the central fleet projection (last100 jobs, truncation disclosed). Per-lane full
logs/artifacts remain in their original schemas/runtime roots; the legacy report denominators are
unchanged. Source observation time is not job heartbeat. Unknown, absent and zero stay distinct.
