# Implementation: Zeus Observatory (observatory-001)

Worker: Claude, isolated Zeus worker, Linux, Python 3.13. Base revision
b9610a105774a491287f5635e91ab9cb7b05c9d1. Frame: SPEC.md in this directory, followed as fixed.
Owner keeps npm install/build, packaged output generation, browser acceptance, full CI and deploy.

## Authority searched and disposition

- Observation contract: `domain/observation.py` (categories, severities, `redact_text`, `REFERENCE`);
  stored buckets and their row shapes: `application/observations.py` (`observation_audit`,
  `observations`, `observation_alerts`, `observation_quarantine`, `observation_collections`,
  `observation_terminations`); local files: `adapters/observation_spool.py` `SpoolDirectory` read
  methods. Operation rows: `application/operation.py` bucket `operations` (`status`, `reason_code`,
  `task_id`, `decision_id`, `lead_accepted`, `goal.criterion`).
- Monitor authority reused, not duplicated: `adapters/monitoring.py` `collect` envelopes and
  `ReadOnlyTransaction.entries` paging; `monitoring_web.py` Host check and `respond` headers;
  `monitor.py` collector loop. `status_report` in `application/observations.py` was not reused
  because it scans whole buckets unbounded and calls `live_runs` (a lock probe); the projection
  reads bounded pages and only pure read methods.
- Disposition: new read model module `adapters/monitoring_observations.py` (justified: no existing
  bounded read-only projection of these buckets), additive fourth `observations` source envelope,
  additive HTTP routes, frontend product source replacing the disposable scaffold sample.

## Change

- `adapters/monitoring_observations.py`: `scan_bounded` (2000 rows/bucket, 500 per page, reports
  scanned/limit/truncated), `merge_events` (audit + collected by `event_id`, collected wins,
  record kinds counted), `sort_key` (severity desc, then operations/development/general, then
  observed_at, event_id; unknown severity/category/time sort last and are counted), allow-listed
  `project_event` (no attributes, refs must match `REFERENCE`, at most 8, strings redacted and
  bounded), collection receipts (last time, lag), alerts/quarantine/termination counts,
  `operations` rows separate from tasks, `local_facts` (runtime missing → `unavailable`, directory
  missing → `unavailable`, otherwise segments, unacknowledged bytes, health records with drop
  counters, pending alert files, local pending/unreadable terminations). Never calls prune,
  reclaim, acknowledge, `writer_alive` or `live_runs`.
- `adapters/monitoring.py`: `collect(..., runtime=None)`; with a runtime the `observations` job is
  added as an independent envelope (`sample` wrapper unchanged). Without a runtime the three legacy
  sources are exactly as before, so the pre-existing tests stay valid unchanged.
- `monitor.py`: passes the runtime directory to `collect`.
- `adapters/monitoring_web.py`: `/` serves packaged `resources/observatory/index.html` when it
  exists, else the legacy page (no placeholder); `/legacy` serves `monitor.html`; `/assets/<name>`
  serves only exact names matching `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}` with a `.js/.css/.svg/.woff2/
  .woff` MIME allow-list, no directories, 5 MB cap; query strings are ignored for routing; Host
  check, no-store, nosniff, CSP and read-only POST behaviour unchanged (CSP gains `font-src 'self'`
  and `img-src 'self' data:`).
- `frontend/monitor`: `vite.config.ts` builds into `src/codex_harness/resources/observatory`
  (hashed assets, no sourcemaps, no preload polyfill); `index.html` Korean title; `index.css` Zeus
  tokens (slate/zinc neutrals, teal primary, success/warning/error/unknown, 10px radius, system
  fonts, print rules); `src/lib/snapshot.ts` contract types + freshness (20s window, invalid or
  future >5s never fresh); `src/lib/use-snapshot.ts` single-flight fetch, 5s timeout, 5s poll paused
  when hidden, visibility resume, retained last-good envelope per source; `src/lib/report.ts`
  one-snapshot report (scope, generated_at, source times, completeness limits, critical events,
  operation outcomes, next actions, evidence ids) with local JSON download; views `overview`,
  `logs` (category/severity tabs, text filter, priority order, expandable identity/timestamps,
  empty vs unavailable vs truncated), `report` (print + JSON from the same object), `design-system`
  specimen; `App.tsx` sidebar (desktop) / horizontal nav (phone), header with transport state,
  refresh button, prominent `/legacy` link. Uses the installed `button/card/badge/table/tabs/alert/
  input/separator` primitives and Lucide icons only; no new dependency.
- `.github/workflows/frontend.yml`: `npm ci`, typecheck, lint, build, then a git diff drift check
  on the tracked output; triggered by frontend, packaged output or workflow changes.
- Tests: `tests/test_monitoring_observations.py` (priority/dedup/unknown rows, bounded paging and
  truncation, redaction canary + script-like labels, collection/alerts/quarantine/terminations/
  operations separation and empty store, local spool read-only with unreadable health, collect
  opt-in + independent observation failure, read-only store); `tests/test_monitoring.py` (CLI now
  journals four sources and includes the observations envelope, `/legacy`, asset traversal/MIME/
  Host checks, index fallback without build output).

## Not done here / owner follow-up

- `npm install`, `npm run build`, packaged output under `resources/observatory`, browser checks
  (desktop + 390px, keyboard, hidden-tab/timeout behaviour), real PostgreSQL data, full CI and
  deployment: not run by the worker (assignment restricts the worker to the two Python commands).
  The TypeScript sources were written without a typecheck run; the frontend CI job is the first
  check. `public/vite.svg` and `src/assets/react.svg` from the scaffold were left in place (unused).
- Sample order is store id order (deterministic, not time order); a sample cut at 2000 rows per
  bucket is labelled `truncated` and the UI/report say totals are sampled.

## Completion correction (2026-09-18, base 4e799631d2b47d606c548e9e5ead8a9868b13244)

Scope: only R1/R2/R3 from the owner review at the end of SPEC.md. Backend, HTTP and tests untouched.
Files: `frontend/monitor/eslint.config.js`, `src/App.tsx`, `src/components/{status-badge,
source-strip,stat-card}.tsx`, `src/lib/{report,tones(new)}.ts`, `src/views/{overview,logs,report}.tsx`.

- R1 build/lint: `StatusBadge` now takes `React.ComponentProps<"span">` and spreads them to the
  generated `Badge`, so `title` (App.tsx:73) and `aria-live` type-check. `severityTone`,
  `freshnessTone`, `statusTone` moved to `src/lib/tones.ts` (callers updated) so the component file
  exports only a component. The overview operations table keys by `row.id ?? row-<index>` instead
  of `Math.random()`. ESLint: one override limited to `src/components/ui/**/*.tsx` turns off
  `react-refresh/only-export-components` for the generated shadcn variant exports; no other rule
  changed, product code stays under the full rule set.
- R2 phone overflow: the generated Badge is `whitespace-nowrap shrink-0`; `StatusBadge` overrides
  it to `h-auto min-h-5 max-w-full min-w-0 whitespace-normal break-words`, so scope/transport/
  source badges wrap inside their container instead of widening the body. Sinks fixed: header rows
  and main get `min-w-0`; the desktop grid and `KeyValue` use `minmax(0,1fr)` columns; source cards
  and report rows get `break-words`/`break-all` on ids; log filter tabs scroll inside their own
  `max-w-full overflow-x-auto` Tabs root (nav and tables already scroll in bounded containers). No
  body-level clip was added, so the owner's scrollWidth measurement stays meaningful. Desktop
  classes are unchanged except the grid column min.
- R3 report truth and pinning: `Report` schema is `zeus-observatory-report.v2` (no Python consumer
  of v1 exists in the repository; grep on `zeus-observatory-report`/`critical_events` only hit the
  frontend and the stale packaged bundle). `critical_events` and new `critical_events_total` are
  `null` when the observations envelope is not `ok` (unknown), an empty list only when the source
  was ok and returned none; new `observations {available,status,error,freshness}` and
  `transport {state,detail,last_ok_at}` record the capture conditions. `buildReport` takes the
  transport state. `ReportView` pins the report in `useState` at view entry (mount) and rebuilds
  only on the new "보고서 재생성" button; the 1s tick and polls no longer rebuild it. Rendered page
  (also printed) shows "고정 보고서 · 생성 <time>", a destructive alert when capture happened in a
  non-ok transport state (with detail and last ok time), an explicit "확인 불가 (비어 있음 아님)"
  alert and per-card text when observations were unavailable, "확인 불가" instead of "—" for null
  counts, and a screen-only hint when a newer snapshot exists. JSON download and print describe the
  same pinned object.

Verification run here: `python -m pytest tests/test_monitoring.py tests/test_monitoring_observations.py
-q -p no:cacheprovider` and `python -m ruff check .` (results in the worker summary). Not run by
the worker, owner-owned: `npm run build`, `npm run lint`, browser 390x844 / 1440x960 checks,
packaged asset regeneration, controlled unavailable-observations injection, full CI.

## Print seam follow-up (2026-09-18, base 1a86898256ed1e25f5515b09c29578b3c23298d2)

Reviewer finding: the live `SourceStrip` and the live-time footer in `src/App.tsx` printed
alongside the pinned report, mixing live chrome into a document that claims to be frozen.
Fix: `SourceStrip` is wrapped in `<div className="no-print">` and the footer gets `no-print`;
the existing `@media print { .no-print { display: none !important } }` rule in `src/index.css`
hides both. Screen rendering, report capture and export logic are unchanged. Not run by the
worker, owner-owned: `npm run build`, `npm run lint`, browser print check, asset regeneration.

## User extension: illustrated explanations (2026-09-18, base 2cc604110c0c6a80b7c97db3455f9ea86c506dd3)

Scope: the "User extension — illustrated explanations" section at the end of SPEC.md only. Files:
`frontend/monitor/src/lib/report.ts`, new `src/components/report-explainer.tsx`,
`src/views/report.tsx`, this note. Backend, HTTP, tests, dependencies and packaged assets untouched.

- Authority searched: `zeus-observatory-report` has no Python consumer (grep over the checkout hit
  only `report.ts`, SPEC/IMPLEMENTATION and the stale packaged bundle), so the schema moves to
  `zeus-observatory-report.v3` additively: every v2 field is unchanged and one `explanation`
  object is added. Operation status vocabulary comes from `application/operation.py`
  (`accepted/failed/rejected/exhausted/running/unknown`); the projection in
  `adapters/monitoring_observations.py` counts `by_status` over the whole bounded operations sample
  and `total` is its denominator, so bars sum to the denominator by construction.
- `report.ts`: `buildExplanation(snapshot, observations, sources, transport, generated_at)` runs
  inside `buildReport` at capture and uses only those arguments (no clock, fetch, storage or model
  call). Output is JSON-serializable: `summary` (fixed Korean sentences chosen by the captured
  state), `flow` (label `구조 설명 · 개별 실행을 추적한 증거가 아님`, four steps record → collection
  → read-only snapshot → pinned report, each with its own units and `known` flag per fact, plus a
  note that the boxes are different populations and not a funnel), `operations` (`state`
  `unknown|empty|observed`, `denominator` null when observations were unusable and `0` for an
  observed empty sample, Korean labels for the six known statuses with zero rows kept as `0`,
  arbitrary status values kept raw and marked `known_status:false`, scope from the operations
  bucket scan and truncation, a note that pending is not inferred from `lead_accepted=false`),
  `guide` (severity vs category, priority rule, zero ≠ complete collection, 확인 불가 vs 0,
  task vs operation, ELI5 named as design reference only), `caveats` (transport state, every
  non-fresh source with its state and error, truncated buckets, row limits, unknown-value counts,
  unreadable local spool, missing collection receipts; one explicit "no warnings" line otherwise),
  `provenance` (generated/collected/observation times, observation status, transport state,
  `computed_by`, ELI5 repo/commit/role). No global health, cause, ETA, success rate or retry
  advice is generated in any branch.
- `report-explainer.tsx`: renders `report.explanation` only. shadcn Card/Separator, `StatusBadge`
  tones, Lucide `Lightbulb/BookOpen/AlertTriangle/ArrowRight/ArrowDown` (all `aria-hidden`; step
  order is carried by the numbered titles). Flow is an `<ol>` in a single column on phones and a
  four-box CSS grid with arrows from `md`. Distribution bars are plain `div`s with inline width,
  `aria-hidden`, and the exact `n건 / N건` text next to a tone badge and the raw status, so no
  meaning is colour-only and print keeps the numbers. Unknown state renders "확인 불가 … (0건 아님)",
  empty state renders "0건 (비어 있음)". All text containers use `min-w-0 break-words`.
- `report.tsx`: `<ReportExplainer explanation={report.explanation} />` inserted after the capture
  alerts and before the existing "범위와 시각" card; every previous card stays below unchanged.
  Print and JSON download already describe the pinned object, so they include the explanation
  without further change.

Verification run here: `python -m pytest tests/test_monitoring.py tests/test_monitoring_observations.py
-q -p no:cacheprovider` and `python -m ruff check .` (results in the worker summary; neither
touches the TypeScript). Not run by the worker, owner-owned: `npm run build`/typecheck/lint,
browser checks at 1440px and 390px, regenerate/pin/JSON/PDF equality, controlled unavailable or
stale observations injection, packaged asset regeneration, CI.

## Status membership correction (2026-09-18, base 356291777f642f420456e511de7daf954ffa4a87)

Reviewer finding: `operationBars` in `frontend/monitor/src/lib/report.ts` dropped any own
`by_status` key that is also an inherited property name of a plain object (`constructor`,
`toString`, `__proto__`, ...). The `in` operator walks the prototype chain, so such a status was
neither in the six known bars nor in the extra list; the owner reproduced denominator 1 with 0
bars displayed. Fix: the extra-status filter uses `Object.hasOwn(OPERATION_STATUS_LABELS, status)`
(ES2022, within the project's ES2023 lib) instead of `status in OPERATION_STATUS_LABELS`. One
line changed; the six known bars, ordering, labels, `known_status` flags and counts are unchanged.
Verification run here: the two Python commands above (results in the worker summary; neither
executes the TypeScript). Not run by the worker, owner-owned: typecheck/build/lint, browser and
print checks, packaged asset regeneration, CI.
