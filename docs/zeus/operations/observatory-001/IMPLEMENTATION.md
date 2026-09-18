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
