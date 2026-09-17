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
