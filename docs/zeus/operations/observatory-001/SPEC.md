# Zeus Observatory — one bounded operating visibility delivery

Owner: Codex (analysis/design/acceptance); implementation: actual isolated Zeus Claude worker.
Date: 2026-09-18. Base: 6c6d6e824f97dcbcc5c40f0ea2acf20c70bdbdbb.

## Outcome, scope, authority, finish

User wants a trustworthy operating monitor, debug/development/operations visibility ordered by
material importance, a readable report, and an actual shadcn/ui + Lucide design system.
Authorized: local source, isolated Claude implementation and independent review, tests, GitHub PR,
merge after acceptance, replace only the owned localhost:8788 monitor. No external report sends.
Finish: real stored observations and collection limitations visible in the new UI, report export
matches that same snapshot, responsive accessible design, existing detailed views remain available,
targeted checks/full CI and real browser acceptance pass, deploy the accepted revision.
Excluded: new telemetry platform, historical isolated schema import, model routing changes,
instrument every module, SLO claims, external alert integrations, unbounded reference absorption.

## Evidence and complete path

Facts: domain/observation.py defines general/development/operations and separate debug/info/warning/
error/critical severity. application/observations.py stores append-only audit, deduplicated events,
collections, quarantine, alerts and terminations. Producers write runtime/observations spool;
existing Collector drains it to PostgreSQL. monitor.py is read-only and must stay so.
Current monitor snapshot has database/docker/redis, measurements, task/stage projections; it does
not expose observation buckets or collection health. UI is one static HTML, no React/components.json.
Local read-only audit at 02:39 UTC: observations 253 (development 177, operations 76, general 0),
debug 223/info 30; audits 10, collections 5, terminations 5 closed, alerts/quarantine 0. These are
stored facts, NOT proof every expected event was emitted or that current failure rate is zero.
Raw evidence D:/workspaces/zeus/artifacts/observatory-001/audit-before.json (initial root-only file
count does NOT inspect nested spool). Follow-up through existing SpoolDirectory read methods:
one spool segment, 1024 unacknowledged bytes, zero pending alert groups, one health record dated
01:32:44 UTC, sink available at THAT time. Do not claim current completeness. Prior automated operation failed
evidence inspection despite task success: task success must never become whole-operation success.

Path: producers -> durable spool / same-transaction audit -> existing collector -> PG -> read-only
monitor projection (+ read-only local spool health) -> atomic snapshot -> loopback HTTP -> React
screen / downloadable report. Source generation time, event time and collection time remain separate.
Owner-run build generates packaged static resources, Node is build-time only. Legacy detailed HTML
remains /legacy. No writes/reconciliation/provider startup from monitoring or export.

Primary docs consulted 2026-09-18 (web docs mutable; dependency versions pinned by lockfile):
- https://ui.shadcn.com/docs/installation/vite — React/TypeScript + Tailwind Vite integration and
  owned component installation. Does not prove our accessibility or build.
- https://ui.shadcn.com/docs/theming — semantic CSS variables for reusable theme tokens.
- https://lucide.dev/guide/react — typed React SVG icon imports, tree-shakable individual imports.
- https://opentelemetry.io/docs/specs/otel/logs/data-model/ — severity and observed/event timestamps
  are distinct fields. We retain Zeus contract rather than claiming OTel export compatibility.

## Design / acceptance contract

1. Add observation read model in adapters/monitoring_observations.py. Use existing buckets and
   status concepts; no duplicate collector or business policy. Merge audit and collected events
   by event_id, collected record wins without double count. Deterministic sort severity descending,
   then category operations/development/general, then event observed_at and event_id. Thus critical
   development outranks info operations. Invalid severity/category/time explicit unknown count.
   Human label general = 일반·디버깅 (debug remains a severity, never reclassify stored category).
2. Projection uses a declared bounded sample (entries paging capped e.g. 2000/bucket), reports
   scanned/limit/truncated/selection and retained scope honestly. Totals describe sampled stored
   records, never lifetime totals on a truncated sample; high severity list is from this sample.
   Include safe allow-listed fields: event_id/type/category/severity/outcome/observed_at/collected_at,
   task/attempt/process identity, evidence_refs (opaque refs only); never raw attributes/prompts.
   Apply existing domain redaction to strings at public boundary, bound lengths/list sizes.
3. Include alerts/quarantine counts, pending/unconfirmed termination count, last collection time,
   collection lag and local pending alert/health/drop/corrupt indicators where readable. Missing
   runtime/unreadable data is unknown/unavailable, not zero. Keep separate from DB envelope failure.
   Never call mutating pruning/collector functions. No promise of complete logging from empty queues.
   Include actual operation state read from operations bucket, separate from task state.
4. Extend collector snapshot additively. Existing three sources and tests remain valid. Observation
   failure must not erase working Docker/Redis or task data. Optional runtime argument to collect;
   monitor.py passes actual runtime. HTTP only reads snapshot; safe fixed assets, no traversal,
   strict MIME, same loopback Host check/read-only behavior. /legacy serves previous monitor.html.
5. New frontend/monitor: React + TS + Vite + Tailwind, actual shadcn/ui source components and Lucide
   icons; reusable Button/Card/Badge/Table/Tabs/Alert/Input/Separator at least where appropriate.
   Neutral slate/zinc palette with teal accent, semantic success/warning/error/unknown tokens,
   spacing 4/8/12/16/24/32, consistent 10px card radius, local/system font (no CDN dependency).
   Korean-first interface with concise labels. Desktop sidebar/header + spacious content; phone
   responsive navigation. Overview, logs, reports, design-system specimen views. Never dummy numbers.
   Overview: source freshness, priority attention, actual operations and task distinction, service
   resources, collection coverage. Logs: category/severity/text filters, priority ordering, event
   identity and timestamp details, empty vs unavailable vs truncated. Legacy detail link prominent.
   All icons accessible label or decorative. Keyboard controls and visible focus.
6. Preserve accepted refresh semantics: one in-flight request, 5s timeout, hidden-page polling paused,
   retain last good snapshot with conspicuous stale/unavailable state, avoid UI reset on refresh.
   Freshness max 20s, reject invalid/future (>5s) timestamps. Source states independent. Report/export
   captures one snapshot including scope, generated_at, source times, completeness limits, critical
   events, operation outcomes, next actions and evidence IDs. HTML print/PDF via browser and JSON
   download are local only. Escape data; do not claim global health, SLO or automatic acceptance.
7. Build output under src/codex_harness/resources/observatory (small compiled app tracked for Python
   packaging); locked dependencies. Build must be deterministic enough to check tracked output drift.
   Separate frontend CI workflow (npm ci/typecheck/build plus git diff artifact check) required on
   frontend changes; Python validation unchanged. No runtime npm/network/CDN dependency.

## Fixed acceptance matrix / single batch

| Path | Deciding check |
|---|---|
| Real normal | PG audit + actual HTTP/browser: stored counts, operations vs tasks, sources and links |
| Priority/dedup | Focused Python test mixed category/severity, audit/event duplicate, invalid row |
| Missing/truncated/failure | Bounded paging tests, unavailable local source, empty data explicitly labelled |
| Timeout/hidden/restart | Browser request failure/held response/visibility controlled test, preserved last-good data |
| Concurrency/read-only | Existing monitor tests + no put or artifacts from projection; same snapshot report |
| Security | Redaction canary and script-like label tests, asset traversal/Host/mutation checks |
| Windows/Linux | Owner Windows build/tests + full existing CI platform matrix + frontend CI |
| Mobile/accessibility | Actual browser desktop + 390px screenshot, keyboard filter/navigation, no horizontal overflow |
| Reports | Actual JSON export + print view with same counts/time/scope and limitations |
| Cleanup | Only owned monitor processes replaced using stop-owned.ps1; no worker/verifier remains |

Implementation one batch: backend projection + frontend + packaging/CI + tests/doc. Claude's isolated
image has Python and Node but host evidence v1 only replays Python; worker MUST run ONLY:
`python -m pytest tests/test_monitoring.py tests/test_monitoring_observations.py -q -p no:cacheprovider`
and `python -m ruff check .`. Do NOT run full suite/npm/git/model/service commands. Owner explicitly
owns npm install/build, browser, full CI, deployment. Worker tests list contains only the two actual
commands, not result prose or unexecuted checks. Summaries label frontend build/browser not run.
Owner installs official shadcn scaffold/dependencies before assigning; Claude edits product source.
Scaffold: shadcn 4.21.0 radix-nova, Lucide React 1.47.0, React 19.2.8, Vite 8 / Tailwind 4;
exact resolved dependencies in frontend/monitor/package-lock.json. Existing scaffold is disposable
sample content, replace its App.tsx completely. Installed real UI primitives remain source-owned.
One implementation + one independent review call initially; reserve at most one correction pair
only for a material failed acceptance condition, no automatic retry of a failed operation.
Unknown unrelated deficiencies get follow-up notes and do not silently extend this matrix.

## Owner review — one completion correction (2026-09-18)

First actual Claude call hit provider budget USD6 before final response. Its 22 changed files were
preserved and copied byte-for-byte for owner review (recovered-files.json). Operation remains
failed/execution_retry; no candidate/automated acceptance was invented. Owner ran Python targeted
28 passed + ruff clean. Vite-only compilation for PREVIEW succeeded, but the required complete
build/typecheck and ESLint failed. Actual live read-only preview at localhost:8790 displayed the
current PG logs/operations and Docker/Redis with no browser errors. Accepted backend and HTTP
boundaries are retained; do not rewrite them during the correction.

One consolidated frontend correction:
- R1 / required build: npm run build fails App.tsx:73 StatusBadge title prop not supported.
  npm run lint fails helper exports in status-badge.tsx, standard generated shadcn variants in
  button/badge/tabs, and Math.random row key in overview. Support correct props, use stable keys,
  move own helpers to a library module. A narrowly documented eslint exemption for the GENERATED
  UI variants is fine; do not disable lint broadly. Owner runs npm, worker does not.
- R2 / phone: real 390x844 browser report view has document.scrollWidth 437. Scope badge uses
  unbreakable text; constrain/wrap the header and content so BODY never overflows (tables/nav may
  scroll inside their own bounded containers). Desktop 1440x960 is already legible; preserve it.
- R3 / report truth and stability: owner injected ONLY the browser observations envelope as
  unavailable/ControlledTestFailure while other actual sources stayed ok. The report still said
  '샘플 안에 치명·오류 이벤트 없음' because missing source became empty critical_events. Distinguish
  unknown from an observed empty list, in rendered report AND JSON. Report currently rebuilds every
  1s tick / poll (useMemo(snapshot,now)); pin one report at explicit generation or view entry, with
  an explicit regenerate action. Print/JSON must describe that pinned object, including generation
  time, and must retain a transport failure notice if capture occurred after request failure.
  A report that was correctly captured earlier stays a historical report, labelled with its time.

Owner follows this correction with actual build/lint/browser fixed matrix and full CI. No unrelated
redesign, new logging platform or automatic retry. One correction worker + reviewer pair ceiling
135 (machine count now133); implementation timeout900s, USD3 ceiling. Existing partial source is
the base; finish these three boundaries only and keep tests list restricted to assigned commands.

### Final R3 print seam

Candidate 812e6f4: owner npm build and lint pass; real browser overview/report at 390px both have
scrollWidth390 (previous437). Independent review accepted R1 and found exactly one directly
affected R3 seam: window.print includes App's live SourceStrip and footer outside pinned report.
No new investigation scope. Final implementation is limited to adding no-print around SourceStrip
and to footer in App.tsx, using existing print CSS; no report/data/backend redesign. Owner verifies
PDF content and same-report JSON after actual refresh. Keep prior accepted checks. One final tiny
worker/reviewer pair ceiling137 (current135), USD1.5 worker ceiling, 600s. This explicit extension
finishes the same unmet print acceptance condition; no automatic retry loop or new criteria.
# User extension — illustrated explanations (2026-09-18)

The user explicitly requested DreambigOu/ELI5 as a reference, explanatory diagrams, easy Korean
explanations and access in the webpage. PR #140's accepted backend/read-only/source/frozen-report
results remain accepted. This is one bounded presentation extension, not a reopening of those
reviews. Codex designs/accepts; one actual Zeus Claude implementation plus independent Codex review.
Reserve at most two additional model calls, machine ledger 137 -> 139, Claude USD4/900s; stop at
the bound and preserve a failed result. No extra provider calls to generate report explanations.

## Reference facts and decisions

Read 2026-09-18: https://github.com/DreambigOu/ELI5 at
`a766623b062331fdde53467001379b4ddf3acc2f`, README, skills/eli5/SKILL.md and LICENSE (MIT).
It is an audience-adapted explanation skill, not a diagram renderer. Relevant principles:
purpose first, familiar language, layered detail, consequences relevant to the reader.
The repository's suggested age-5 default and tolerance of lower accuracy are NOT adopted:
the audience is an adult Korean operator, and numbers, uncertainty and evidence remain exact.
No source code/skill text is copied or globally installed; independently authored design is
informed by the linked reference. Diagrams are our requested UI extension, not a claimed feature
of that repository. No additional research is needed for this presentation decision.

## Complete path and single delivery

Existing sanitized `/api/status` -> existing `buildReport` fixed capture -> a deterministic,
JSON-serializable `explanation` field in report schema v3 -> one new `ReportExplainer` component
inside the report view -> identical screen/JSON/PDF capture. No timer, fetch, model, storage mutation,
remote image, Mermaid renderer or CDN is added. Existing technical details remain below.

Implement only frontend/monitor/src/lib/report.ts, new components/report-explainer.tsx,
views/report.tsx and an IMPLEMENTATION.md note. Reuse shadcn Cards/Badges and existing Lucide,
semantic tokens, CSS grid/flex/HTML bars. Owner builds tracked assets and verifies in the browser.

Required output:
1. A top section `한눈에 이해하기`: short respectful Korean summary of observed operation results,
   error/critical count and data limitations, distinguishing work completion from accepted operation.
   No global all-clear, presumed root cause, predicted ETA, invented success rate or advice to retry.
2. Three/four boxes connected as a conceptual log-to-report flow (record -> durable storage/collection
   -> fixed report). Label it `구조 설명 · 개별 실행을 추적한 증거가 아님`. Display only relevant
   captured counts/units and explicitly avoid portraying different populations as a funnel.
3. An observed operation-status distribution with labeled HTML bars and exact counts (accepted,
   failed, rejected, exhausted/running/unknown/other). Translate known status labels into Korean;
   unknown values remain visible. Keep null/unavailable distinct from genuine zero/empty. Label
   sample/truncation and denominator. Do not infer pending from false acceptance.
4. Short plain-language reading guide: severity vs general/development/operations categories;
   a development error outranks informational operations, zero doesn't prove complete collection.
   Include ELI5 reference as design inspiration, not endorsement or data source.
5. JSON stores the same summary, diagram labels/counts, limitations and provenance as the view.
   All are derived at capture. Source/transport freshness remains explicit even with retained data.

## Acceptance matrix and completion

Normal: actual fixed PG data -> diagram/counts match report JSON; refresh leaves all explanatory
content pinned; explicit regenerate updates the whole capture. Missing observations/no snapshot:
unknown counts/diagram values and no zero-success claims. Stale/invalid/unavailable source or failed
transport: show limitations without interpreting old values as current. Empty and mixed states:
known zero stays zero; arbitrary status labels/counts retained. Sample truncation: lower scope
visible, no global conclusion. No concurrency/restart changes: reuse accepted singleflight/frozen
report implementation. Platform: Chrome at desktop and390px; keyboard/print reading; HTML text
equivalents and labels, no color-only meaning. Cleanup: no new service, assets, queues or auth flow.

Worker runs only existing focused Python monitoring tests + ruff (regression); no npm in worker,
no full suite, no git/model calls. Exact executed commands only in worker's test claims. Owner runs
TypeScript/lint/build and actual browser report capture cases above, PDF render check, final required
CI. Finish by merging/deploying this frontend extension, updating #139 with evidence and closing it.
Do not broaden to upstream skill evaluation, runtime LLM explanation, backend logging gaps or a
general visualization engine. Existing RESULT/evidence remain frozen; add a separate extension
section/artifact manifest without overwriting them.
