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

## Consolidated correction, 2026-09-19

First candidate d37368b is not accepted: owner Windows focused run produced66 passes and2 setup/
teardown errors before the deep-nesting test body. Pytest includes its >40k bytes parameter in the
test ID; PYTEST_CURRENT_TEST exceeds Windows32767-character environment value limit. This is a
test portability failure, not a demonstrated endpoint crash. Keep the full20,000-depth input and
assertions; assign concise explicit IDs to the malformed-input parametrization. Do not reduce or
skip the input. Native acceptance requires the actual test body to run successfully.

Independent Zeus Codex also identified that rounding age to milliseconds before comparison turns
19.9996 seconds into20, causing an early stale response. The roughly0.5ms window is not treated as
a critical production incident or a reason for a broader review. Correct it in the same small batch:
classify the unrounded/clamped age against20, and preserve numerical age without rounding so the
reported age and state agree. Add cases19.9996 and19.999999 for snapshot and source, retain20 and
future tolerance controls. This is an exact contract correction, not changed threshold policy.

One corrective Claude implementation + independent review pair; same four allowed paths and no
new architecture or scope. Preserve accepted HTTP/security/optional-source/recovery checks and
first failed evidence; no full suite was run after the failed focus gate. First code CI was cancelled
by the owner after the deterministic Windows failure, not reported as green. Run the final candidate's
focused/full checks and CI. Update IMPLEMENTATION with these failures and actual correction results.

## Portable input acceptance clarification, 2026-09-19

Observation: CI35446193663 Linux Python3.14 failed only the deep-nesting fixture reason assertion:
it safely returned503, invalid/sources_unexpected, rather than invalid/undecodable. The test used
a20,000-deep array in sources. Other observed environments refused during JSON decode. No handler
crash or false200 occurred. Exact interpreter/runtime cause is not established and not needed to
accept either safe refusal. Source data payloads remain outside semantic inspection.

Affected assumption: this and the Windows test-ID failure share a portability family: test-runner
and parser representation details were mistaken for the endpoint's required safety behavior.
The discriminating CI receipt shows parsing can reach structural validation. Acceptance is the
fixed HTTP503, ready=false, invalid state, no sources, no payload disclosure and responsive server;
the parser may reject first (undecodable) or structure may reject next (sources_unexpected).
This clarifies the original deep-nesting refusal requirement. No independent numerical nesting-depth
threshold was specified; do not invent one or change the runtime parser. Deep valid data may be
decoded within the byte bound and is not evaluated as health. Correct prior prose claiming all deep
input hits the interpreter recursion guard on every platform.

One test/documentation-only correction through Claude and independent review. Allowed paths ONLY
tests/test_monitor_readiness.py and IMPLEMENTATION.md beside this SPEC. Keep all17 payload bytes,
short IDs, test count and other reason expectations unchanged. Only deep-nesting may accept the two
documented reasons, retaining all other assertions. No runtime, threshold, route, skip, dependency,
workflow or global setting changes. Run the same focused command and ruff; owner rechecks this exact
change and CI. Preserve native/full/HTTP evidence already executed; this is not a new review topic.

## Complete portable concurrency matrix, 2026-09-19

CI35446996683 Windows3.12: all40 HTTP reads completed and HTTP/ready consistency passed, but one
or more snapshot states were outside fresh/stale. The old test discarded reasons, so the exact CI
state/cause is unknown. All other CI jobs passed. Do not call this CI green or rerun until green.
Owner's one predeclared native Windows experiment (four readers x250 requests,200 replacements,
one run, actual temp files/HTTP) recorded612 fresh200,366 stale503,22 unavailable/file_unreadable503,
zero request errors. Receipt: artifacts/monitor-readiness-001/concurrency-probe.json. This establishes
safe read unavailability during the local scenario; it does not prove the hidden CI reason.
Microsoft CreateFileW documentation read2026-09-19,
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew explains incompatible
open/delete sharing modes can refuse an open. It supports possibility, not historical CI causality.

Reframe the full test matrix: successful read -> complete fresh or stale snapshot; refused read ->
unavailable503 with file_missing/file_unreadable, null age and empty sources; partial/invalid decoded
snapshot -> test failure in this controlled publication scenario; request/JSON failure -> test failure;
after writers/readers finish and fresh publication succeeds -> ready200 recovery. This supersedes
the earlier concurrency row's implicit always-readable assumption. Snapshot publication integrity
and availability of an open handle are different facts. Runtime already implements these states.

One consolidated test/documentation-only delivery: same two allowed paths as prior correction.
Keep40 actual requests,20 replacements, valid fresh/stale payloads, bounded joins/cleanup and existing
writer-only sharing retry. Retain complete safe JSON responses (not just state triples) and include
them in assertion diagnostics. Validate each successful read as the complete old/new semantic view;
permit only the named unavailable503 alternatives above (never as200), not arbitrary invalid states.
Assert recovery after publication ends. No HTTP retry, no skip, no runtime changes or global timeout
increase. Update IMPLEMENTATION's concurrency claims and preserve the prior failure plus measured
counts. All other acceptance rows and accepted evidence stay fixed; exact cause of CI's hidden
state stays unknown. Owner focused checks and final CI determine completion, then deploy/observe.
