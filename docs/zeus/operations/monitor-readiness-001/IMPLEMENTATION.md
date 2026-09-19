# Implementation: monitor readiness (monitor-readiness-001)

Worker: Claude, isolated Zeus worker, Linux. Base revision
`eb274f93ebe6d430f29d989540124d2c4220afd0` as supplied with the task; Git commands were out of
scope here, so the revision is carried forward, not re-observed. Frame: `SPEC.md` in this
directory, read in full and followed as fixed. Owner keeps the full suite, CI, deployment and the
real stale/recovery observation against a running collector.

## Authority searched and disposition

- Snapshot contract (producer): `adapters/monitoring.py` `collect` — `schema:
  "harness-monitor.v1"`, `collected_at`, `scope`, and one envelope per source through `sample`
  (`status` `ok`/`unavailable`, aware `observed_at`, `data`, `error` as an exception class name).
  Required names `database`, `docker`, `redis`; additive `fleet` and `research_programs` always
  present in `collect`, `observations` only when the CLI passes a runtime directory. This is why
  the endpoint treats the first three as required and the other three as known optional.
- Consumer contract already accepted: `frontend/monitor/src/lib/snapshot.ts` `envelopeFreshness`
  — `FRESH_MS = 20_000`, `FUTURE_TOLERANCE_MS = 5_000`, non-`ok` status is `unavailable` whatever
  its timestamp says, unparsable time is `invalid`, future beyond tolerance is `invalid`, a small
  negative age clamps to zero. The server-side rules are that same accepted policy restated for a
  machine reader, not new tuning. The frontend is unchanged: this is a second reader of the same
  contract, not a duplicated freshness policy of its own.
- Transport: `adapters/monitoring_web.py` `handler` — Host allow-list, `respond` (no-store,
  nosniff, CSP), `do_POST` 405. Reused as is; `/health` and `/api/status` are untouched.
- Strict JSON reading siblings: `adapters/sdd.py` `load_json`/`parse_json` (bounded stream read,
  duplicate-key refusal) and `application/artifact_query.py` `_parse_json` (duplicate keys,
  `parse_constant`, `RecursionError` caught). `sdd.load_json` was not called directly because it
  decodes `utf-8-sig` (a BOM would be accepted) under a 1 MiB budget and raises `ContractError`;
  this boundary needs strict UTF-8, the 5 MB snapshot budget and a total, non-raising result. The
  idiom is reused, the defect surface is not copied.
- Disposition: one new module (no existing pure readiness assessment exists — searched
  `adapters/`, `application/`, `frontend/monitor/src/lib` for readiness/ready endpoints and found
  none) plus one additive route. No existing file's behaviour changes.

## Change

- `adapters/monitoring_readiness.py` (new, pure and total): `readiness(snapshot_path, *,
  now=None)` returns the fixed `urn:zeus:monitor-readiness:1` dictionary. One `open` and one
  `read(MAX_SNAPSHOT_BYTES + 1)`; the extra byte only detects an oversized file. `parse` decodes
  strict UTF-8 and refuses duplicate object keys and `NaN`/`Infinity`; deep nesting is refused by
  the interpreter's recursion guard, which is caught with the other input errors. `elapsed`
  implements the timestamp rule (aware ISO 8601 only; `age < -5` invalid, `-5 <= age < 0` clamps
  to `0.0`, `0 <= age < 20` fresh, `age >= 20` stale; ages rounded to milliseconds). `snapshot_state`
  maps every structural failure to a state and empty `sources`; a structurally valid snapshot with
  a broken `collected_at` still assesses every envelope. `envelope_state` never looks inside
  `data`. Constants: `MAX_SNAPSHOT_BYTES = 5_000_000`, `FRESH_SECONDS = 20`,
  `FUTURE_TOLERANCE_SECONDS = 5`. No network, database, Docker, process or provider call; no
  write; nothing retained between calls; `now` defaults to aware UTC and a naive `now` raises
  (caller error, never a snapshot state).
- `adapters/monitoring_web.py`: `/ready` only — `200` when `ready` is true, otherwise `503`,
  `application/json; charset=utf-8`, through the existing `respond` (no-store, nosniff, CSP) and
  behind the existing Host guard and `do_POST` 405. `/`, `/legacy`, `/assets/<file>`,
  `/api/status`, `/health` and the 404 fallback are byte-for-byte unchanged. The response is
  serialized without further sanitizing because the assessment emits only fixed strings, booleans,
  finite numbers and null.

## Fixed reason codes

| snapshot state | reason | meaning |
|---|---|---|
| fresh | `current` | `collected_at` within 20 s |
| stale | `older_than_window` | `collected_at` 20 s or older |
| invalid | `timestamp_missing` / `timestamp_unparsable` / `timestamp_naive` / `timestamp_in_future` | `collected_at` absent or not an aware moment, or more than 5 s ahead |
| invalid | `too_large` / `undecodable` / `not_an_object` / `schema_unexpected` / `sources_unexpected` | over 5 MB; not strict UTF-8 JSON (BOM, duplicate keys, `NaN`/`Infinity`, truncation, excessive nesting); root not an object; `schema` not `harness-monitor.v1`; `sources` not an object |
| unavailable | `file_missing` / `file_unreadable` | no snapshot file; the path could not be opened |

Source states use `current`, `older_than_window`, the four timestamp codes, plus
`envelope_missing` (required name absent), `envelope_invalid` (not an object) and
`collection_failed` (`status` is not `ok`). `age_seconds` is a number only for fresh and stale,
otherwise null. Unknown source names are ignored, so no snapshot key is echoed.

## Verification

Run here, with the output read:

- `python -m pytest tests/test_monitor_readiness.py tests/test_monitoring.py -q -p no:cacheprovider`
  — 67 passed. New file: the fixed contract over real HTTP; optional envelopes present/absent; the
  19.999 / 20 / 20.001 / -5 / -5.001 boundaries; collector-versus-source independence; broken
  required envelopes; 17 malformed snapshot payloads (empty, truncated, BOM, invalid UTF-8,
  duplicate key, `NaN`, `Infinity`, 20 000-deep nesting, wrong root, wrong schema, wrong `sources`)
  each 503 with no sources and no handler failure; missing file and directory path; the 5 MB limit
  at and over the boundary; `/health` and `/api/status` unchanged with a stale or missing snapshot;
  payload content (exited container, unregistered fleet, empty task list) never read as health;
  stale to fresh to stale recovery on one running server; no reflection of secrets, keys, paths,
  collector errors or raw timestamps; no file created or modified; Host 403, POST 405, `/ready/`
  404, query string ignored; four threads polling while the file is atomically replaced 20 times
  (40 responses, every one a complete fresh-or-stale answer, `ready` always matching the status).
- `python -m ruff check .` — All checks passed.

Not run by me, by instruction: the full suite, CI, any Git, Docker or service command, and any
deployed-collector observation. The concurrency test's atomic replacement retries briefly on
`PermissionError` so it stays portable to Windows sharing behaviour; the test suite itself was
executed on Linux only, and the exact interpreter version was not recorded because arbitrary
interpreter invocation was denied in this session (`pyproject.toml` requires >= 3.12).

## Limits, unknowns and follow-ups

- Readiness answers observation freshness only. It is not task progress, job acceptance,
  system-wide health, an SLO or restart authority, and a `503` here must not be wired to an
  automatic restart: the SPEC's Kubernetes reference is adapted for the liveness/readiness
  distinction only.
- Operational benefit and readiness-failure incidence remain unmeasured. Nothing here proves the
  deployed monitor is healthy; only the owner's real HTTP stale/recovery observation can show the
  endpoint behaving against a running collector.
- The reader assumes a local regular file. A snapshot path on hung storage or a FIFO can block the
  request; there is no timeout promise, matching the SPEC.
- Follow-up (outside the allowed paths, not done): `docs/contracts.md` has no entry for this
  endpoint, so the module cites `monitor-readiness-001` rather than an `INV-` identifier; the owner
  may want a contract ID and a line in the monitor runbook. The frontend does not consume `/ready`
  and was deliberately left unchanged.
