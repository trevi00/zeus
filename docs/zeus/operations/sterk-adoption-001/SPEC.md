# Sterk reference adoption 001: trustworthy monitor freshness

## Outcome and boundary

Codex analysis/design, 2026-09-18. Baseline Zeus 8d1eec6d12f0db03ccf305c4fecd183e6e047ca4.
The operator can tell current observations from retained history, even when collection or HTTP
fails. Reuse the existing read-only monitor; no new dashboard, runtime authority or release gate.
User authorized useful sterk-reference adoption and actual isolated Claude implementation with
independent Codex review. One implementation/review pair; machine ledger starts 123, ceiling 125.
No automatic retry, self-promotion, external messages or reference-service writes.

Completion: assigned changes implemented by Zeus Claude worker, isolated checks and independent
review accepted, owner browser matrix passed, CI passed, PR merged with reference dispositions.
Reference catalogue issues are not automatically closed by adopting a subset.

## Evidence, existing path and decision

Reference: trevi00/zeus issues labelled sterk-reference, #74–#100, captured locally 2026-09-18.
Their historical observations concern sterk-control HTML/JSON collected 2026-09-15, not source
implementation. This is pattern adaptation, not upstream code import or whole-repository review.
No source checkout/license was supplied: copy no reference HTML/CSS/code/assets. Issue body hashes
and updatedAt are in source-manifest.json; full JSON stays on D. Some issue proposals incorrectly
assume Zeus runtime JSONL/file authority. PostgreSQL runtime and Git definitions remain SSOT.
The usage-page synchronous aggregation cause is inference, not a measured implementation fact.

Current path: PG/Docker/Redis -> adapters.monitoring.collect (parallel source envelopes) ->
monitor.collect atomic monitoring.json replacement -> loopback monitoring_web GET /api/status ->
monitor.html fetch/render. HTTP reads sanitized snapshots and cannot mutate runtime. Existing
Measurements already carries definition/reason/window/evidence; GoalProgress already counts only
verified ticket closures; initiatives separates implementation, review, canary and deployment.
Keep those authorities. Do not duplicate their state machines or add a second metrics store.

Concrete gap (code inspection): fresh() only checks age <20s, so future timestamps pass; refresh
allows overlapping fetches; connection success can hide stale collection; DB stale live counts,
agent execution states and current-work rows remain presented as current. Source failures also
cause early return hiding independent healthy Docker/Redis facts. These are reachable with a
stopped collector, delayed request or one unavailable source, without model behavior assumptions.

Adopt #75/#76/#99/#100: source age, honest unknown, bounded single-flight partial refresh.
Do not add revision endpoint: single-flight fetch prevents completion-order races at this scale.
Do not compare timestamps as monotonic revisions: clock corrections/collector restarts are possible.
Keep last valid snapshot on failed HTTP, prominently as historical evidence; never delete records.

Primary browser references read 2026-09-18 (living docs, no pinned library dependency):
- https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static : timeout can abort
  fetch; active-time semantics are not an OS/suspended-tab wall-clock guarantee. Prefer explicit
  AbortController + clearTimeout for owned request timer cleanup.
- https://developer.mozilla.org/en-US/docs/Web/API/Document/visibilitychange_event : hidden state
  can suspend polling, visible event resumes. This proves API behavior, not our implementation.

## Fixed implementation batch

Allowed: resources/monitor.html, tests/test_monitoring.py, and IMPLEMENTATION.md beside this spec.
No backend schema, auth, profile, executor, dependencies, CSS redesign or unrelated refactor.

1. Central freshness predicate: source status ok, finite parseable timestamp, age >=0 and <20000ms.
   Show all three source names, observed time/age and fresh/stale/unavailable/invalid state in a
   persistent strip. Missing/invalid/future timestamps are unknown, never zero age or fresh.
2. Stale/unavailable database: current-running count and current-work/agent live states must be
   unknown; retained tasks/releases/metrics remain accessible and explicitly labelled historical.
   Keep source-specific failures independent; healthy Docker/Redis still render without DB data.
   Existing succeeded task is execution success, not independent acceptance or deployed status.
3. At most one /api/status request in flight (manual and timer share owner). Abort after 10s,
   clear timer in finally. Hidden tabs do not start automatic requests; return-visible refreshes.
   No full-page reload. Search text, selected tab and open detail survive automatic updates.
4. Separate transport state from source freshness. Every tick updates freshness even if no new
   response; timer must not overwrite a failed transport badge with a generic stale badge.
   A recovered response restores transport state; only fresh sources restore current-state claims.
5. Report executed tests honestly. Worker: python -m pytest tests/test_monitoring.py -q -p no:cacheprovider;
   python -m ruff check . . Full suite/CI and browser behavior checks belong to owner, not worker.
   Do not add static substring tests pretending to prove browser concurrency/timing.

## Acceptance matrix

| Path | Decisive check / owner |
|---|---|
| Normal | Actual browser reads current snapshot through real local HTTP; all source ages shown |
| Stale/unknown | Stop updating test snapshot, wait >20s; live claims become unknown, history kept |
| Invalid/future | Controlled input timestamps; unknown explicitly, no fresh status |
| Partial failure | DB unavailable but Docker/Redis fresh: independent source views remain visible |
| HTTP failure/recovery | Remove/restore isolated snapshot file; retain old history, distinguish transport |
| Timeout/concurrency | Controlled delayed local HTTP; manual+timer one request, abort releases busy |
| UI state | Search, selected tab, open detail survive polling; hidden/visible lifecycle checked |
| Restart | New collector timestamp accepted; page fresh state derives from current data, no old revision lock |
| Platforms | Existing Windows/Linux CI tests; owner Windows Chromium UI. WSL browser not claimed |
| Cleanup | Only owned local server/browser stopped; no runtime/DB mutations from monitor |

Injected snapshots/delays test rendering contracts, not real operating throughput or failure rates.
Also open the actual sanitized monitor snapshot if available; if absent report that limit rather
than manufacture live operational evidence. No Samsung/human product acceptance claimed.

## Catalogue triage (proposal-level, not full semantic verification)

| Issues | Disposition / revisit trigger |
|---|---|
| #74 | Reference index; link this adaptation and keep remaining catalogue visible |
| #75 #76 | Adapt freshness/refresh now; graph avatars, lazy paging later when measured scale requires |
| #77 #97 | Existing GoalProgress/initiatives authority; goal drill-down later for multiple active goals |
| #78 #96 | Defer unified question inbox until actual unanswered-question bottleneck; required approval never defaults |
| #79 #81 | Reuse ticket lifecycle/operation queue; defer UI intake/dependency view until multi-job operation needs it |
| #80 #82 | Next candidate: cycle result/residual report using existing cycle receipts, not a second file SSOT |
| #83 #84 #85 | Defer document/search/graph interfaces; verified knowledge authority must remain PG |
| #86 #89 #91 | Existing session/work/release monitor; stale live distinction now, richer drilldown later |
| #87 #90 | Next candidate: effective worker profile provenance versus declarations, reuse packaged profile digest |
| #88 | Preserve existing verification/promotion gate; do not import numeric confidence or human-only policy blindly |
| #92 #93 | Existing Measurements definition/reason/window/evidence; comparative cost views need real denominator |
| #94 #95 #98 | Keep existing policy/scheduling authority; defer writable web controls, do not execute reference forms |
| #99 #100 | Adapt source freshness/partial refresh now; existing loopback read-only snapshot architecture retained |

Other unknowns are backlog, not acceptance blockers. No claim that all 27 issues are absorbed.

## Consolidated owner acceptance / bounded correction

2026-09-18, candidate da3ed8ef. Isolated worker/replay: monitoring 7 passed, lint passed.
Independent lead rejected one concrete defect: transport.ok_at is numeric but date()/parseTime()
accept strings, so last successful response time always reads as invalid. No other rejection.
Owner Chromium 153 actual local HTTP checks passed fresh, stale, future, invalid, independent
Docker/Redis during DB failure, retained search/tab/dialog, HTTP failure persistence/recovery,
8 joined refresh callers with timeout (~9.5s remaining on existing request), and subsequent recovery.
Input/delay injection is labelled; it is not operational throughput evidence. No operational
monitoring.json exists at the configured runtime path. Owner driver initially hit cp949 output
encoding (not page failure); UTF-8 rerun preserved the failed driver's JSON separately.

One explicit correction batch, not automatic retry: ledger 125 -> ceiling 127, one Claude + one
independent review. Fix only receipt timestamp representation: store transport.ok_at as ISO string
(or narrowly format its numeric type without relaxing source timestamp checks). Preserve all
accepted behavior. Update IMPLEMENTATION.md, run the same two exact checks. Reviewer covers this
delta and directly affected success/failure/recovery clock display only; no new speculative review.
Owner will verify response time display during success -> failure -> recovery and finish the
remaining lifecycle/aging checks, then CI/merge. This amendment does not erase the rejected receipt.

## Continuation: live monitor deployment (2026-09-18)

User requested the remaining work after PR135 merged at cda05da. Preserve prior UI acceptance.
Outcome: the existing monitor continuously serves real bounded-operation records on this Windows
host, with correct source identity, durable local startup/recovery and no per-refresh DB/artifact
writes. This is the live-deployment remainder, not the deferred reports/profile/whole-catalog work.
No new external exposure, no historical-schema merge, no worker privilege change, no reboot.

### Observations and complete path

- Current .env PG points to local zeus DB port63556; public has34 tickets but no tasks. Prior real
  operations live in separate explicit schemas. Redis .env port56379 is stale; actual existing
  zeus-local-ops-redis publishes63589. Existing Zeus containers were created without Compose labels.
- start_monitor.ps1 already launches collect/web and can register HKCU logon startup. Nothing is
  currently listening on8787 and no monitoring.json exists. Current collector builds a full
  execution adapter and Measurements.collect writes observations/artifact bytes every iteration.
- Existing UI is a sanitized snapshot consumer. Keep its freshness/request behavior accepted.
- New actual operations for this deployment use existing public PG + Redis namespace zeus and
  fixed D:/workspaces/zeus/artifacts/live/r. This is normal assigned work, not an import of
  past schemas or a synthetic completed record. Historical schemas stay untouched and are excluded
  from this monitor's named scope. The public ticket rows are preserved.

Path: owner deployment configuration -> read-only service/artifact reader -> PG facts and persisted
measurement observations, named Docker containers, scoped Redis -> atomic D monitoring.json ->
loopback web -> browser. Owner schedules the two existing entrypoints for current-user Windows
logon with bounded restart and no simultaneous instances. Operator logs/startup definitions stay
on D; home credentials/call ledger and existing C repository stay at their current locations.

Primary references read 2026-09-18: Docker container ls reference
https://docs.docker.com/reference/cli/docker/container/ls/ documents --all, JSON formatting and
name filtering (substring matching, so application must check exact returned names). Microsoft
New-ScheduledTaskSettingsSet reference (WindowsServer2025 PowerShell view) documents restart and
MultipleInstances settings. Installed cmdlets are present. Documentation is not reboot evidence.

### One Claude implementation batch

Allowed files: adapters/monitoring.py, monitor.py, resources/monitor.html, tests/test_monitoring.py,
and LIVE-IMPLEMENTATION.md in this directory. Codex owns this design/deployment; Claude implements.
One implementation/review pair, ledger127 ->129. No automatic model retries.

1. Make monitor collection read-only: never call Measurements.collect or put artifacts/PG rows.
   Read already persisted metric_observations from the same store instead, select latest per
   metric_id by valid timezone-aware observed_at, keep definition/window/evidence and original time.
   No stored observations means empty list, not fabricated zeroes. Do not weaken the original
   Measurements use case used elsewhere. Current-source freshness must not make an old metric
   observation current: show original observed_at and historical/unknown status when stale.
2. monitor.py collect builds only build() service and FileArtifacts reader, not build_executor.
   No provider/isolation/OAuth preflight or knowledge writes just to view state. Atomic snapshot
   replacement and collector lock remain. Add bounded rotating local operational log (1MiB,2
   backups) for startup/source-state transitions/shutdown or failures, sanitized event/type/time
   only; never DSN, env values, payloads, raw exceptions or repeated every-tick identical logs.
3. Optional ZEUS_MONITOR_CONTAINERS (alias HARNESS) is a JSON list of1..32 unique exact Docker names
   (alphanumeric first, then alphanumeric/underscore/dot/dash, <=128chars). Unset keeps old Compose
   scope. Named mode uses only read-only ps/stats commands; exact-filter returned names, unrelated
   containers excluded, any missing requested name makes Docker unavailable (not success-empty).
   Preserve stopped container visibility and no mutation commands. No docker inspect env payloads.
4. Optional ZEUS_MONITOR_SCOPE safe_text label emitted at snapshot scope and rendered with textContent
   in existing toolbar (default repository scope). Label observation scope, not a global autonomy
   success claim. Owner label: 'Zeus 고정 운영 원장 · 과거 격리 실행 제외'. Preserve accepted UI logic.
5. Focused tests: read-only store refuses put and reader refuses artifact.put while collection still
   works; empty/stale persisted metrics; exact container selection, missing/invalid names, Compose
   compatibility; existing HTTP/freshness contract. Fault injection is labelled. Run exactly
   python -m pytest tests/test_monitoring.py -q -p no:cacheprovider and python -m ruff check . .
   Owner/CI owns full suite, actual Docker/PG/Redis/Windows scheduler/browser evidence.

### Fixed deployment acceptance matrix

| Boundary | Evidence required |
|---|---|
| Normal | Actual Claude+review rows in public displayed; PG, Redis, named Docker snapshots fresh |
| Scope | Explicit scope label; old schemas unmodified/excluded, unrelated flexday container absent |
| Read-only | Repeated monitor collection does not grow metric_observations or artifact count |
| Auth unavailable | Collector startup succeeds without worker OAuth env, no model calls by monitor |
| Missing source | Named nonexistent container reports unavailable; no data invented |
| Metric history | Old stored metric stays old/unknown despite a fresh source snapshot |
| Restart/concurrency | Owner terminate only monitor-owned process; scheduled restart, one live instance |
| Startup | Registered current-user logon triggers inspected; actual reboot/logoff not performed |
| Logs/storage | Atomic snapshot + bounded logs on D; no secrets in logs; no unrelated process cleanup |
| Platforms | Existing Linux/Windows CI; current Windows runtime/browser actual, no Linux service claim |

Completion: code independently accepted + focused/CI checks pass, real services/browser and
owned-process recovery pass, PR merged, startup configured, implementation issue closed with
receipt. Residual logoff/reboot verification and older schema browsing are documented limits,
not reasons to rerun unrelated environment research. No required person approval defaults to yes.
### Live continuation acceptance seam (2026-09-18)

Post-merge owner transition: Stop-ScheduledTask left venv child processes on this Windows host.
Source-byte equality was insufficient to prove promotion. Revised operator acceptance: disable
the exact owned tasks, validate/inventory command plus PID creation identity, terminate only owned
monitor children, prove zero, start main-configured tasks, then verify new process ownership and
stable one-instance state across scheduled ticks. Implemented in the local stop-owned.ps1; this
corrects deployment procedure, not runtime architecture. Preserve the earlier process-crash recovery
evidence and record the premature promotion claim separately.

Final test-only run ended `evidence_gate_refused`: requested pair/focused40/lint claims replayed successfully, but unrequested full-suite claim timed out and two unrelated commands had mismatched expected exits. Preserve failed operation; no retry, status rewrite or relaxed gate. Owner Codex independently reviewed the five-line environment ownership change and executed focused40 successfully. Accept this test-only candidate for the normal manual PR+full-CI route; this is not automatic operation acceptance. Calls used127 ->132 (the third run's reviewer was never invoked). Report scope overrun and free-text evidence extraction as follow-up observations in this frame, not new blockers for the accepted runtime.

Full CI run35293839664 exposed test isolation: the new collector CLI test invokes `select_repository`, which updates both ZEUS_REPOSITORY and HARNESS_REPOSITORY, but the test does not register either with monkeypatch teardown. Owner reproduced with only collector entrypoint test followed by supervisor runtime test (1 passed,1 failed). Preserve runtime/live acceptance. One final test-only batch owns/restores both aliases before the real CLI invocation (do not mock select_repository or change supervisor). Scope: tests/test_monitoring.py and LIVE-IMPLEMENTATION.md. Run monitoring+measurements+supervisor together and ruff. Ledger131 ->133, one Claude/reviewer pair, no automatic retries. Full CI must pass on the resulting head.

Deployment observation supersedes the earlier idle-port check: the existing `harness-console` task served port8787 when the browser opened. Preserve it; the Zeus monitor uses loopback8788. This changes local deployment configuration only. Actual recovery acceptance remains the same.

The first actual implementation/review pair accepted candidate 9bc1f18 within its five-file scope. Owner executed the existing measurement/monitor integration test: it fails because it expects three fabricated observations from an empty store. The original allowed paths omitted this directly affected test. Extend the same batch to `tests/test_measurements.py` and the live implementation note only: replace that obsolete expectation with empty/persisted read-only collection assertions, retaining the independent Measurements use-case tests. No runtime redesign. One corrective Claude/reviewer pair is authorized in this frame, machine ledger 129 to 131; no automatic retries. Owner deployment and full CI remain the final acceptance checks.
