# Sterk adoption 001: live monitor deployment, implementation record

Worker: Zeus Claude implementation worker (Claude Fable 5.1), 2026-09-18, isolated Linux checkout
at base revision 254301962bfa8c53e1c35d4737889e9c1c51ab8c. Scope: only "Continuation: live monitor
deployment" in SPEC.md. Files changed: `src/codex_harness/adapters/monitoring.py`,
`src/codex_harness/monitor.py`, `src/codex_harness/resources/monitor.html`,
`tests/test_monitoring.py`, this file. No dependency, schema, profile, executor, launcher or
Windows task change; the owner deploys the scheduled tasks, PG/Redis/Docker and browser checks.

## Contract read before the batch

Producer `adapters/monitoring.py::collect` -> `monitor.py` atomic `monitoring.json` -> loopback
`monitoring_web.py` -> `monitor.html`. Existing envelope `{schema, collected_at, sources{database,
docker, redis}}` is unchanged; one top-level `scope` object is added. `application/measurements.py`
(`Measurements.collect`) still writes `metric_observations` rows and evidence artifacts for its
other callers; the monitor no longer calls it.

## What changed

1. Read-only collection (`monitoring.py`). `ReadOnlyStore`/`ReadOnlyTransaction` delegate get,
   scan, entries and records; `put` and `graph` raise `ContractError`. `ReadOnlyArtifacts` exposes
   bounded reads (`_body`, document, text, read, inspect, search) and refuses `put`. `read_only()`
   wraps the service and reader for `collect`. The database job no longer runs git or
   `Measurements.collect`; it reads `persisted_measurements(store)`: latest row per `metric_id`
   from `metric_observations`, chosen by a timezone-aware parseable `observed_at` (naive, missing
   or unparseable timestamps and empty metric ids are skipped), keeping every stored field
   (definition, window, evidence refs, original `observed_at`) plus `source:
   persisted_observation` and a raw `age_seconds` at collection time. No rows means `[]`.
2. Collector entry (`monitor.py`). `run_collector` builds only `bootstrap.build()` and a
   `FileArtifacts` reader, both wrapped read-only; `build_executor`, provider/isolation/OAuth
   preflight and knowledge adapters are never imported. Lock and atomic replace are unchanged.
   A rotating `monitor-collector.log` (1 MiB, 2 backups) under the runtime directory records
   `startup` (mode, once, scope kind, container count), `source_state` only when a source's
   status/error type changes, `snapshot_write_failed`, `startup_refused` (lock busy or invalid
   container config) and `shutdown` (once, interrupt, failure with exception type). Field names
   are whitelisted and string values must match `[A-Za-z0-9_.:-]{1,64}`, so DSNs, env values,
   payloads, the scope label and raw exception text cannot be written.
3. Named container scope. `container_scope(value)` parses `ZEUS_MONITOR_CONTAINERS` (alias
   `HARNESS_` via existing settings aliases): unset/blank keeps Compose; otherwise a JSON list of
   1..32 unique names `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`; anything else raises `ValueError`, the
   collector logs `startup_refused` and exits rather than silently monitoring Compose scope.
   Named mode runs `docker ps --all --format {{json .}} --filter name=...` and `docker stats
   --no-stream` only, keeps rows whose returned `Names` equals a requested name (unrelated and
   substring matches dropped, stopped containers kept), and raises when any requested name is
   absent so the source is `unavailable`, never success-empty. No `docker inspect`.
4. Scope label. `scope_label()` passes `ZEUS_MONITOR_SCOPE` through `safe_text` (200 chars),
   default `repository <name>`. `collect` emits `scope: {label, docker: named|compose,
   containers}`. The page shows it in the existing toolbar through `textContent` only.
5. Page (`monitor.html`). Measurement rows now derive current/historical/invalid from the row's
   own `observed_at` against a 120 s window (the domain evidence freshness) and only show the
   stored status/reason when the database source is fresh and the row is current; otherwise
   `확인 불가` with "stored observation", the original observed time in a new column and a stale
   evidence reason. The 1 s ticker also re-renders when a metric row crosses that window. All
   accepted freshness, single-flight, timeout, transport and retention logic is untouched.

## Tests (`tests/test_monitoring.py`)

Added: read-only store/reader refuse writes while two collections succeed and neither store rows
nor artifact files change; latest-per-metric selection with naive/invalid/empty rows skipped and
empty store -> `[]`; container scope rejects nine invalid configurations; unset keeps Compose
while named mode is exact, drops substring/unrelated containers, keeps a stopped container,
reports a missing name as `RuntimeError` and issues only ps/stats commands; the `zeus-monitor
collect --once` entry point runs twice against a `MemoryStore` with `build_executor` patched to
fail, no credential env, writes the snapshot with the sanitized label and old metric age, leaves
store/artifacts unchanged, writes only whitelisted log fields (no secret, URL or label text) and
refuses an invalid container list with a logged `startup_refused`. The existing failure-
independence test now injects a failing store instead of a failing git call. All injected
faults and fixtures are labelled as such in the test source.

Commands executed in this checkout, output read:

```
python -m pytest tests/test_monitoring.py -q -p no:cacheprovider
python -m ruff check .
```

## Outside the allowed paths at the time, corrected below

`tests/test_measurements.py::test_monitor_collects_measurements_via_use_case` asserted that the
monitor evaluates three measurements from an empty store. That contradicted SPEC item 1 (no
`Measurements.collect`, empty store -> empty list) and was outside the first batch's allowed
files. The owner reproduced the failure; the correction batch below replaced the test.

## Not run

Full suite, CI, real PostgreSQL/Redis/Docker, Windows scheduled tasks, logon startup and the
browser matrix are owner/CI work. The page script was self-reviewed only; no JS engine ran here.

## Correction batch: measurement/monitor seam test (2026-09-18)

Worker: Zeus Claude implementation worker (Claude Fable 5.1), isolated Linux checkout at base
revision d1501fb30ace22f089a34c01cb2b7820d434d4b0, SPEC section "Live continuation acceptance
seam". Files changed: `tests/test_measurements.py` and this file only. No runtime, dependency,
profile or other test change.

Contract read before the change: producer `application/measurements.py::Measurements.collect`
(writes `metric_observations` rows keyed by result digest plus one evidence artifact and its
receipt through `FileArtifacts.put`) and consumer `adapters/monitoring.py::collect` ->
`persisted_measurements(store)` behind `read_only()` (`ReadOnlyStore`, `ReadOnlyArtifacts`).
The row shape the consumer relies on is `metric_id`, timezone-aware `observed_at`, and the stored
`value`, `promotion_approval`, `evidence_refs` fields, which it returns unchanged plus `source`
and `age_seconds`.

Reproduced first: the focused command below failed only on the obsolete test (`assert 0 == 3`).

Change: `test_monitor_collects_measurements_via_use_case` is replaced by
`test_monitor_reads_persisted_measurements_without_evaluating_or_writing`, which:

- collects through `read_only()` with `run_process` replaced by an injected fault (labelled in the
  test) that fails if the monitor runs git or any process; Docker/Redis sources are stubbed empty;
- asserts an empty store yields database status `ok` with `measurements == []`, no store rows and
  an empty artifact directory (no fabricated evaluations);
- persists three observations with the real `Measurements.collect` at the fixed test time, then
  records a deep copy of the store data and the artifact directory listing (one evidence body
  plus one receipt);
- collects twice and asserts the three rows come back sorted by `metric_id` with `source:
  persisted_observation`, the original `observed_at`, `age_seconds` above the 120 s freshness
  window, `promotion_approval` false, the capacity metric at value 0 with the producer's evidence
  reference, and the evidence readable through the read-only reader;
- asserts the store data and artifact listing are unchanged and `metric_observations` still holds
  exactly three rows after both refreshes (no new store or artifact writes).

The independent `Measurements` use-case tests (`test_observations_reproduce_and_retain_original_inputs`
and the domain `evaluate` tests) are untouched.

Commands executed in this checkout, output read, both exit 0 (35 passed; "All checks passed!"):

```
python -m pytest tests/test_monitoring.py tests/test_measurements.py -q -p no:cacheprovider
python -m ruff check .
```

Not run in this batch: the full suite, CI, real services, browser checks (owner/CI). A disposable
run showing the new test failing against a per-refresh writing monitor was not performed: the
worker's file tools are confined to the checkout and the allowed paths exclude a scratch test, so
that detection rests on the deep-copied store/artifact before-and-after assertions above.
