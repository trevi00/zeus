# Report + background 001 — bounded operating experience

Owner Codex, 2026-09-18. Base 440c2fe3ca20ce6f3185a7a2f502967d3ceaa8f5.

## Outcome / authority / completion

User requests invisible background CMD execution and the previously described picture-led report,
and confirms finite-budget operation. Codex analyzes/reviews/releases; actual Zeus Claude workers
implement two independent lanes. This delivery authorizes four additional provider calls (two Claude
implementations plus two Codex reviews), machine ceiling160 ->164, no retries or automatic increase.
Provider monetary flags remain declared controls, not a measured spend guarantee. Pause after this
finite batch. Existing authenticated user and DPAPI/ledger locations unchanged.

Complete when background child policy has real Windows console evidence, report shows actual fleet
goals/outcomes visually with truthful unknowns, targeted checks/frontend/browser/full CI pass, and
accepted code is merged/deployed with idle paused service and no unexpected calls. No new scheduling
framework, backlog invention, full asset absorption, arbitrary desktop window suppression, automatic
merge by workers, or logged-out/reboot guarantee. Preserve dirty main and all prior evidence.

## Facts, sources, inference

Actual localhost8788 report has numeric cards, category/status bars and generic capture diagram;
the explanation is collapsed and current fleet jobs are absent from pinned Report v3. Thus previous
"picture-first" implementation is not the requested goal/story explanation. Existing optional
sources.fleet contains goals, lane, status/reason, calls, dependencies and timestamps; it does NOT
contain individual evidence-stage timestamps, detailed reviewer findings, patches or measured
improvement baselines. Do not invent those. Existing pinned report/print/JSON is the SSOT to extend.

Windows tasks use hidden PowerShell, but commands.run_process uses CREATE_NEW_PROCESS_GROUP only,
and several piped host Git/Docker/provider subprocesses have no console policy. Monitor calls this
helper repeatedly. This is a reachable source of window creation, not proof every user-observed
flash came from Zeus. Owner must measure actual console handles/visible-window facts on fixed paths.

Primary docs consulted 2026-09-18:
- Python3.14.7 https://docs.python.org/3/library/subprocess.html : CREATE_NO_WINDOW is a Windows
  Popen creation flag; capture_output redirects streams but is not a console visibility policy.
- Microsoft https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags :
  CREATE_NO_WINDOW runs a console application without a console, and is ignored with NEW_CONSOLE
  or DETACHED_PROCESS. Preserve process groups/suspended creation/job ownership; do not add either
  conflicting flag. POSIX policy stays unchanged.
- Existing ELI5 reference pinned in report.ts is explanation-style provenance, not runtime evidence.

## Complete path and two disjoint assignments

### Backend lane: silent host children

Scheduled hidden PowerShell -> Python collector/fleet -> piped Git/Docker/process children ->
existing timeout/tree ownership -> captured logs/exit/outcome. Add a single reusable Windows-only
no-console kwargs/flags helper in commands.py (or small sibling). Apply it to piped/noninteractive
host subprocesses in commands.py (including taskkill), fleet_runtime.py, app_server.py (including
taskkill), isolated_worker.py, operation_cli.py, source_verification.py, source_execution.py,
process_tree.py, published_ports.py, port_diagnosis.py and audit_runner.py. Audit these complete
paths once; preserve existing flags, timeout, pipes, environment allowlists, process groups, Job
objects, suspended-start ordering and cleanup. Do not rewrite cancellation or introduce shell=True.
Tests may inject platform/creation calls to verify wiring, but at least one native Windows child
must report GetConsoleWindow()==0 and preserve UTF8 output/exit; owner executes Windows-only tests
if Linux worker cannot. Add targeted tests/test_background_processes.py and adjust directly affected
test assertions only when required. No broad file/test reformat. Add BACKEND.md factual results.

Host scheduled launchers are owner deployment configuration outside repo: use no-window creation
at their entry if required, not only a hidden window after creation; logs/exit remain observable.
Do not kill arbitrary cmd/PowerShell windows. Owner checks Zeus-owned descendants only.

### Interface lane: explain the actual goal and work in pictures

Extend lib/report.ts to capture optional fleet once from the same snapshot: a new version or clearly
additive compatible shape, detached from live mutable data. Reuse snapshot Fleet types and validation
approach. Preserve all prior report data/unknown semantics/print and download consistency.

Create a prominent report-story component BEFORE aggregate metrics, never behind a disclosure.
Use existing shadcn/Lucide/tokens and CSS/SVG, no extra dependency or generated bitmap needed.
User reads: "무엇을 하려는가 -> 어느 팀이 수행했는가 -> 어떤 판정인가 -> 무엇이 남았는가".
Show actual job goal criteria and short IDs on connected team swimlanes or a step diagram; status
and reason/call facts annotated directly at nodes; no giant prose card masquerading as a diagram.
An accepted durable operation supports a review-accepted terminal badge, NOT independently measured
timestamps/completion for every conceptual step and NOT deployment. Label conceptual stages and
unobserved details clearly. For missing/empty/stale/unavailable fleet show that state in place.

Add a visible bounded-operation strip: finite call ceilings, active lanes/concurrency, paused state,
"explicit jobs only / owner grants next budget". Do not label budget ceilings as actual remaining
money/calls: fleet contains ceilings but lacks machine ledger count. Sample job reserved counts are
not the machine total. Show samples/truncation and source time independently from heartbeat.

Show "결과와 잔여" visually per job: accepted -> candidate accepted (merge unknown), queued ->
recorded reason/awaiting, unknown -> owner reconciliation, failure/rejection -> reason + owner next
decision. Missing dependencies remain unknown. Add a before/after explanation of this REPORT change
(previous aggregate-only vs current goal/team/result linkage) explicitly as UI design comparison,
not measured operational improvement; no invented source-code change summary or root cause.
Keep older chart/detail sections available below story, simple human Korean and accessible labels.
At390px stack without horizontal overflow; dark theme and print readable. JSON includes same captured
story/fleet and limits. No runtime requests, model calls or authority controls in browser.

Allowed UI edits: report.ts, report.tsx, new report-story.tsx, report-visual-summary.tsx, index.css
only if needed, UI.md. No shared backend edits. Owner packages compiled assets after build.

## Acceptance matrix and one batch

Normal: finite fleet two jobs display actual criteria/outcomes; child exit/output retained without
console. Failure: nonzero exit/timeout remain failures, no window-only success claim; report refusal
and unavailable remain explicit. Timeout/cancel: preserve process tree ownership and existing tests.
Unknown: missing source, absent evidence steps, old snapshots and truncated dependencies never turn
green/zero. Concurrency/restart: existing fleet matrix already accepted; no new reservation changes;
two disjoint lanes use existing164 ceiling, pause after finish. Platform: Windows real console probe,
Linux helper no Windows kwargs; CI Windows/Linux. Cleanup: no orphan own children, no foreign kill,
no token output; main dirty hashes preserved. Report before/after performance measurement irrelevant:
none requested/provided; do not fabricate. Full model efficacy and reboot outside this delivery.

Worker backend runs focused new background tests plus commands/process-tree/fleet-runtime tests and
Ruff. UI runs Ruff only (owner supplies Node build/lint/browser). Reviewer inspects fixed assigned
matrix and material reachable failures only; no expanding speculative nitpicks. Owner integrates only
accepted candidates, runs full tests with skip reasons (-ra) and CI, verifies live deployment, then
closes issue. If a candidate is rejected or calls exhausted, preserve it and hand off one consolidated
remaining report rather than adding a hidden retry or silently raising164.

## Owner disposition of noncritical review (same frame)

UI candidate a12afdd7334e60aa53640079cdec4c3a50777169 received a static P2 rejection:
an unregistered fleet's stale capture keeps its timestamp but lacks an inline stale badge. Preserve
the operation's rejected status and reviewer evidence. This is a real presentation recommendation,
not a provider/admission/ownership failure. The current registry is registered and immutable under
the v1 API; registered stale captures already carry a warning. Source time and capture qualification
are displayed even for unregistered snapshots. It does not block this current-host delivery under
the user's explicit critical-only blocking policy. No extra calls, correction loop or authority
change is justified. Owner may integrate this reviewed candidate for the fixed frontend acceptance
checks and accept the release with this disclosed residual; never rewrite machine review to accepted.
This qualifies the earlier "only accepted" wording: final owner judgment is distinct from the
automated review disposition. Other material findings still block; all prior matrix checks remain.
