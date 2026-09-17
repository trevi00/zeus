# Sterk reference adoption 001: implementation record

Worker: Zeus Claude implementation worker (Claude Fable 5.1), 2026-09-17, isolated checkout at
repository revision 3295ecb7ca6d781eba62dd950dd9741d3ed5a1ba. Scope: the fixed batch in SPEC.md.
Files changed: `src/codex_harness/resources/monitor.html`, `tests/test_monitoring.py`, this file.
No backend, schema, dependency, profile or executor change. The single-file offline UI, every
existing view, the loopback read-only HTTP adapter and the `harness-monitor.v1` envelope are
unchanged; the page still only reads `GET /api/status`.

## Contract read before changing the consumer

- Producer: `adapters/monitoring.py::collect` emits `{schema, collected_at, sources}` where each of
  `database`, `docker`, `redis` is `{status: ok|unavailable, observed_at, data, error?}`; failures
  are per source and carry `data: null`. `monitor.py` replaces `monitoring.json` atomically.
- Transport: `adapters/monitoring_web.py` serves the snapshot bytes with 200 or answers 503 when
  the file is missing, oversized or not JSON. It never mutates runtime state.
- Consumer: `monitor.html` fetch/render. The defects named in SPEC.md were confirmed by code
  inspection: `fresh()` accepted future timestamps, `refresh()` allowed overlapping fetches with
  no timeout, the 1s ticker overwrote a failed transport badge with a generic stale badge, and
  `render()` returned early when the database source had no data, hiding Docker/Redis.

## What changed in monitor.html (SPEC items 1-4)

1. Central `freshness(name)` predicate returns `fresh | stale | unavailable | invalid` with
   `observed_at` and `age`. Fresh requires source status `ok`, a finite parseable timestamp, and
   `0 <= age < 20000 ms`. Missing, unparseable and future timestamps are `invalid` with age null:
   never zero age, never fresh. A persistent strip under the toolbar shows all three sources plus
   the collector time with state badge, observed time, age in seconds and reason; it is
   recomputed every second. ISO fractional seconds are normalised to milliseconds before
   `Date.parse` because sub-millisecond digits are implementation-defined.
2. Live claims depend on `fresh('database')` only: operating status, running-execution count,
   agent execution badges and the current-work list become `확인 불가` when the database source is
   stale, unavailable or invalid. Retained tasks, releases, sessions, hooks, events, measurements
   and audits stay rendered from the last `ok` envelope, with a visible `보존 기록 · 현재 상태 아님`
   badge on every database-backed panel and the last observed time on the cards. The
   `succeeded` label now reads `실행 완료` and the work panel states that it is execution success,
   not review acceptance or deployment. Docker and Redis render independently through
   `renderSource`; a database outage no longer short-circuits them, and each shows current rows
   when fresh or labelled retained rows otherwise. Retained history is never deleted by a later
   failure; it is only replaced by a newer `ok` envelope of the same source.
3. Single-flight refresh: the manual button, the 5s timer and the visibility handler all call
   `refresh()`, which returns the in-flight promise instead of starting another request. Each
   request owns an `AbortController` with a 10s timer; `clearTimeout` runs in `finally`. The
   poll timer skips ticks while `document.hidden`; the `visibilitychange` handler refreshes on
   return to visible. No full-page reload. The search input, selected tab and open detail dialog
   are not touched by `render()`, so they survive automatic updates.
4. Transport state (`pending | ok | failed | timeout | invalid`) is written only by the request
   path and rendered into the header badge. The 1s ticker recomputes freshness and re-renders
   when any source state changes, but it never writes the transport badge. A failed transport
   keeps the previous snapshot and history on screen with an explicit notice; a recovered
   response restores the transport badge, and only fresh sources restore current-state claims.
   Restart is covered by construction: every accepted response replaces the snapshot and
   freshness is derived from its timestamps, with no monotonic revision comparison.

## Tests (SPEC item 5)

Added `test_collect_keeps_source_failures_independent`: with the database job failing and Docker
and Redis stubbed, `collect` still returns `harness-monitor.v1` with an `unavailable` database
envelope (`data: null`, `error: RuntimeError`) and `ok` envelopes with tz-aware `observed_at`
for the other two, bounded by `collected_at`. Extended the HTTP test with an invalid-JSON snapshot
(503 with the documented body) followed by a restored file (200), the server side of the
HTTP failure/recovery row. No static substring assertions about the HTML were added; the
browser matrix cannot be proven by Python tests.

Commands executed in this checkout, output read:

```
python -m pytest tests/test_monitoring.py -q -p no:cacheprovider   # 7 passed
python -m ruff check .                                             # All checks passed!
```

## Not run and remaining uncertainty

- Browser acceptance matrix (normal, stale, invalid/future, partial failure, HTTP failure and
  recovery, timeout/concurrency, UI state, restart, platforms, cleanup): not run by the worker.
  Owner follow-up on Windows Chromium per SPEC.md. WSL browser not claimed.
- Full test suite and CI: not run by the worker; verification was narrowed to the two commands
  above by the task.
- JavaScript syntax was self-reviewed only. A JS engine syntax check was blocked by the session
  tool policy, so a browser load is the first execution of the new script.
- Real sanitized `monitoring.json` was not available in this checkout; rendering was reasoned
  against the producer code, not against a live snapshot.
