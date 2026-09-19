# Monitor readiness001: Guardian experience adapted to existing monitoring

## Outcome, scope and completion

2026-09-19. User authorized the next local harness asset adoption through Zeus. Codex owns this
design and acceptance; isolated Claude Opus5 implements; independent Zeus Codex reviews. One job,
one implementation/review pair, subscription accounting preserved. No Fable, auto retry, reboot,
credential movement, global hooks, new framework or unrelated repair. Source baseline ce9329f.
Finish with accepted candidate, focused/full checks and CI, merged local deployment, real HTTP
fresh/stale/recovery observations, evidence report, and Fleet paused/idle. If review fails, consolidate
material findings in this same frame before deciding a corrective batch; do not widen the topic.

## Evidence and decision

Local asset: docs/full-analysis/guardian/review.md, pinned Guardian e7ced4a632a38726dca44e84fa0a00b8e1f0b6f4.
Its health analysis separates process presence from expected work and actual result. Prior source
review is evidence of design experience, not a fresh upstream execution or a license to copy code.
Zeus already distinguishes frontend freshness (20 seconds, 5 seconds future tolerance), reports
per-source failure and retains history. Keep those accepted paths. monitoring_web.py /health
intentionally returns liveness200 without reading the snapshot; /api/status serves valid JSON even
if old. Neither is a bug under its current contract. The missing capability is a machine-readable
readiness answer for current observation delivery. This adoption implements only that dimension,
not task progress, system-wide health, job acceptance, SLO or automatic restart.

Primary sources read2026-09-19: Kubernetes v1.37 documentation
https://kubernetes.io/docs/concepts/workloads/pods/probes/ distinguishes liveness from readiness
and warns that misconfigured restart probes can cause cascading failure. We adapt the distinction,
not Kubernetes control-plane behavior. Python3.14.7 datetime documentation
https://docs.python.org/3/library/datetime.html says aware timestamps identify moments while naive
timestamps lack timezone context; use aware UTC comparison. Neither source validates our wiring.
Unknown: readiness failure incidence and operational benefit have not been measured; do not claim
an outage fixed or all Guardian assets incorporated.

## Complete path, states and ownership

Existing collector -> sanitized atomic monitoring.json -> loopback HTTP handler -> new GET /ready
-> a small derived JSON status. Git defines this contract; existing PG remains runtime authority.
The endpoint reads a bounded snapshot once per request, computes at one UTC now, retains nothing,
writes nothing, starts no processes and makes no PG/Redis/Docker/provider/network calls.
Existing /health, /api/status, frontend/static assets, Host guard and POST refusal stay unchanged.
Owner deploys the accepted pinned module using existing hidden owned launchers, only while Fleet idle.

Implement only:
- src/codex_harness/adapters/monitoring_readiness.py (pure assessment + bounded file reader)
- src/codex_harness/adapters/monitoring_web.py (new route only, reuse Host/security headers)
- tests/test_monitor_readiness.py
- docs/zeus/operations/monitor-readiness-001/IMPLEMENTATION.md

Expose readiness(snapshot_path, *, now=None) returning the response dictionary; default now is aware
UTC datetime, tests may supply an aware datetime. Constants: MAX_SNAPSHOT_BYTES=5_000_000,
FRESH_SECONDS=20, FUTURE_TOLERANCE_SECONDS=5, matching current frontend policy (not new tuning).
Read at most MAX+1 bytes through one opened regular snapshot stream. Missing/read-denied ->
snapshot unavailable; oversized, invalid UTF-8/JSON, non-object, wrong schema, non-object sources ->
snapshot invalid. Reject duplicate JSON object keys, NaN/Infinity and excessive nesting safely;
these are invalid input, never HTTP handler crashes. Do not echo raw errors or raw field values.
Require schema harness-monitor.v1. Do not inspect source data payloads or infer health from them.

Response fixed contract:
{schema: "urn:zeus:monitor-readiness:1", service: "harness-monitor",
 ready: boolean, basis: "observation_freshness", checked_at: UTC ISO,
 freshness_seconds: 20, future_tolerance_seconds: 5,
 snapshot: {state: fresh|stale|invalid|unavailable, reason: fixed_code, age_seconds: number|null},
 sources: {fixed_known_name: {state, reason, age_seconds}}}
HTTP200 iff ready true, otherwise503, application/json; no-store/security headers as existing.
No arbitrary source keys, timestamps, payloads, source errors, credentials or file paths reflected.
checked_at is our clock. Fixed reason codes can be chosen by implementer and documented.

Timestamp rule for collected_at and each observed_at: nonempty ISO8601 datetime string with explicit
timezone, parse and normalize UTC; absent/malformed/naive/overflow -> invalid. Age<-5 invalid;
-5<=age<0 clamps to0; 0<=age<20 fresh; age>=20 stale. No mtime fallback. Compute each independent
component even when another is stale. Ready requires fresh snapshot and every evaluated source fresh.
Required source envelopes: database, docker, redis. Missing/non-object required -> unavailable.
Optional known envelopes: observations, fleet, research_programs; absent omitted, present validated
identically. Unknown source names ignored (forward compatibility and no key disclosure). Envelope
status must equal ok, otherwise unavailable regardless of timestamp; then assess observed_at.
Fleet paused/unregistered, empty task list or stopped container data do not change freshness status.
If snapshot cannot be structurally decoded, sources is empty and ready false. Structurally valid
snapshot with malformed collected_at still evaluates its known envelopes.

## Acceptance matrix and one delivery batch

| Boundary | Check |
|---|---|
| Normal | Real temp snapshot, /ready200, expected fixed schema and ages; optional absent/present |
| Stale/future | exact20 stale,19.999 fresh,-5 fresh,-5.001 invalid; source stale vs fresh collector |
| Unknown | missing/unreadable file, oversized, malformed/BOM UTF8, duplicate keys, NaN, nested JSON, wrong shapes/timezones ->503, no crash |
| Independence | /health stays200 with stale/missing file; /api/status existing bytes/status unchanged; data payload not read as health |
| Recovery/restart | Atomically replace stale snapshot with fresh -> same server recovers without restart; no cached readiness |
| Isolation | Host403 and POST405 preserved; malicious error/key/time values never reflected; no write or external call |
| Concurrency | Request is one immutable read view; old or new complete atomic file acceptable, never success from partial JSON |
| Platform | real file and HTTP tests portable Windows/Linux; owner native checks, required CI |
| Cleanup | test HTTP threads/sockets joined/closed in finally; no long-lived background worker introduced |
| Cancel/timeout | no provider/task cancellation or retries; bounded read/CPU input, local regular file assumption, no promise for hung storage |

Worker runs exactly python -m pytest tests/test_monitor_readiness.py tests/test_monitoring.py -q -p no:cacheprovider
and python -m ruff check . . No full suite, shell service commands, Git commands or model calls.
Owner reviews complete changed path, runs required full suite and CI once at final candidate and
real deployed HTTP stale/recovery observation by stopping only collector briefly then restarting it.
Actual snapshot may be nonready for source failures; preserve that result rather than forcing green.
Owner raw evidence stays on D with hashes; C dirty analysis preserved. No UI changes or visual
rendering claim; no bootstrap/reboot or autonomous recovery claim. Report prior source vs implemented
behavior vs actual operation separately. No next asset job automatically admitted.
