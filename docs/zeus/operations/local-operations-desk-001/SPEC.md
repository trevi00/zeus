# Local operations desk 001 — one operating frame

Owner Codex, 2026-09-19, base e67842a10c7400fc63a866b83391c672e39f53b9.

## Outcome, authority, completion

User asks to operate unattended and to converse through one dedicated session in the local
observatory. Explicitly selected local-only, not access from other devices. Claude implements;
Codex owns design, independent acceptance and integration. Existing subscription accounting stays;
provider calls are recorded, not gated by the obsolete 192 migration number. No reboot, remote bind,
new credentials, automatic merge/deploy by workers, unbounded retries or unrelated asset work.

One delivery has successive bounded parts: (A) truthful live/report presentation; (B) durable local
front-door conversation and its conductor handoff; (C) real browser-to-result acceptance and release.
Do not describe a queued request as an executed job or a stored model answer as an accepted change.
Success is a real local request surviving reload, reaching the existing controlled execution path,
and displaying its resulting answer/status; plus corrected accounting and history labels. Existing
GitHub/deployment evidence must be connected through explicit owner records, never inferred from
`accepted`. Work finishes on those criteria; minor visual refinements stay outside this batch.

## Existing complete path and observations

Owner inspected actual runtime-157 on localhost8788: monitor collector -> atomically replaced
sanitized JSON -> loopback HTTP -> React snapshot -> live fleet view or pinned report/print/JSON.
PG is runtime authority; Git is definition authority. Fleet admission owns capacity, path exclusion
and durable operation IDs; lane processes use Redis six-W assignments, Workflow, isolated Claude,
host evidence inspection and independent Codex. No web conversation adapter exists. Existing web
server is read-only and POST405, so a browser form alone cannot fulfill the requested session.

Observed: sources.fleet.data.accounting_mode and budget.mode say subscription, but both frontend
decoders discard mode and render192/192 as an active ceiling. Overview puts sampled historical
critical/error events under priority action; these records do not prove unresolved incidents.
Fleet contains candidate verdicts, not owner merge/deployment facts. Keep that unknown until an
explicit bound record exists. Actual pending termination count1 must not be hidden or relabelled
resolved just because its event is old. Recent accepted monitor-readiness job has been merged and
deployed, evidenced outside this projection. This is a missing integration, not permission to fake it.

## Sources and decisions

Consulted2026-09-19: OWASP CSRF Prevention Cheat Sheet (living documentation,
https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
sections on custom headers, rejecting simple content types, and exact origin verification: a local
state-changing web adapter must validate origin and use non-simple JSON requests; loopback alone
does not establish intent. MDN Using Fetch (living Web API documentation,
https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch): HTTP failure status is not
a rejected fetch; frontend checks status and preserves an uncertain submission ID for safe retry.
These support transport choices, not end-to-end security certification. Reuse installed React19,
shadcn source components, Lucide and existing tokens. No new UI framework or cloud service.

## Part A — first actual Claude assignment (UI only)

Read producer domain/fleet.py plus both frontend decoders, report builders and consumers. Add one
shared accounting interpretation used in live fleet and pinned report: explicit finite/subscription
must agree when both wire fields exist; absent legacy mode means finite; malformed/contradictory
explicit modes are unknown, never silently finite. Keep migration numbers only as metadata in JSON;
subscription UI says `구독 사용량 기록` and `호출 수 상한 미적용`, not192/192 active ceiling, unlimited
provider quota, free usage, remaining money or remaining calls. Finite mode retains true ceilings.
Update control-strip explanations and report before/after explanatory text to avoid stale assertions.
Pinned report/print/JSON use the same captured interpretation; poll must not mutate it.

Separate historical critical/error and alert totals from current known action conditions on overview
and report. Label stored samples as history with outcome unresolved/unknown unless a current explicit
state proves otherwise. Current pending termination, local pending alerts/unreadable files and unknown
freshness remain actionable/unknown with their source and sample bounds. No history deletion, no
automatic reconciliation, no conversion of absent values to zero, no incident-state inference by age.
Remove unsupported `미확정 종료 => all execution blocked` global wording: scope is affected execution.

For delivery display in this first assignment keep `검토 수락` separate and explicitly say owner
delivery evidence is not connected yet. Do NOT hardcode #157/deployment facts, invent report links,
or add a second source of truth. Part B's owner-record boundary is required before claiming closure.

Allowed A: frontend/monitor/src/lib/snapshot.ts, new lib/accounting.ts, lib/report.ts,
views/fleet.tsx, views/overview.tsx, views/report.tsx, components/report-story.tsx,
components/report-visual-summary.tsx, components/report-explainer.tsx, and UI.md beside this SPEC.
No dependencies, API/backend, compiled assets, lockfile, broad reformat or root policy edits.
Worker may run exactly `python -m ruff check .` (backend unchanged). Worker environment does not
authorize npm; explicitly leave TypeScript/build/browser verification to owner, do not claim it.
Finish the allowed change rather than adding a test framework. Owner runs npm lint/build and real
browser observations plus controlled browser-only finite/subscription/conflict fixtures.

## Acceptance matrix and ownership

| Path | Acceptance | Owner |
|---|---|---|
| Normal A | subscription accurately displayed in live and pinned report; finite stays finite | Claude + owner browser |
| Unknown A | mode conflict/invalid is unknown; stale/missing source is not healthy or zero | Claude + owner synthetic browser fixtures |
| History A | old event visible as history; explicit pending count retained separately | Claude + owner actual snapshot |
| Normal B | persisted session/request ID, explicit conductor ownership, answer bound to request | next backend/UI assignment in same frame |
| Failure/timeout B | no false sent/succeeded; stable retry identity, no extra provider invocation | backend tests + owner |
| Concurrency/restart B | duplicate same content idempotent, conflicting identity refused; recovery explicit | backend tests + owner |
| Browser authority B | loopback Host and exact Origin, JSON/custom-header POST, bounded input, escaped output | real HTTP/browser |
| Delivery | owner-recorded merge/deploy with provenance; review accepted never auto-upgraded | owner adapter + UI |
| Platform/cleanup | existing Windows/Linux contracts; no leaked browser/worker containers or C changes | CI + owner |

B's exact wire/authority design is finalized here after tracing the existing executor, before its
implementation is queued. This is an integration dependency, not an invitation to recursively add
tasks. No unknown outside this matrix blocks the current UI assignment. A completes as accepted
candidate; the whole delivery does not complete until B/C and actual operating evidence are done.

## Part B — exact local front-door backend contract

Decision after tracing bootstrap.build_executor, Workflow, RedisBus, scoped flush_outbox and
BudgetedExecutor: reuse those owners. Do not start a separate raw provider CLI or a model inside an
HTTP request. Add `lead:frontdesk` as a lead of conductor (team control); no organization rule change.
Trusted web intake creates conductor -> lead:frontdesk `task.assign`, action `frontdesk`, six-W v1.
The originator is separately `local_user` in request metadata, never fabricated as a model message.
Conductor intake/routing here is deterministic; the responding conversational lead is actual Codex.
Do not label this as autonomous conductor reasoning, debate, implementation or independent approval.

New application FrontDesk persists buckets desk_sessions, desk_requests, desk_events in existing PG
Store transactions. Session and request IDs are client-generated UUIDs. Session creation is idempotent
by ID/title. A submission contains session_id, request_id, intent (`consult` or `request`), text
(1..6000 chars), with an overall encoded body <=32KiB. Same request ID/content returns same row;
conflicting content/session is409. At most one queued/dispatching request per session; second different
request409 until terminal, to freeze conversation order. Bound each session to100 requests; never
silently discard user history. List up to50 sessions, detail returns explicit bounded history and
state. Persist user message and outbox assignment together before202. No PG =>503, no local fallback.
Carry a bounded prior conversation (last10 completed turns, <=24000chars; report omitted count),
plus current request and sanitized fleet snapshot as model evidence. No file path/model/provider/
command/base/budget from browser; base is owner's configured full Git revision, captured per request.

Lifecycle: queued -> dispatching (durable owner token before external work) -> answered | needs_spec |
failed | needs_reconciliation. `consult` successful result is answered; `request` successful result
is needs_spec: accepted request/proposed goal, NOT an implementation dispatched. The answer can
contain questions, an objective and acceptance criteria. A model answer is unverified context and
must NOT become ontology/knowledge, approval or a new operation manifest. Execution of a new free-text
goal still requires Codex-owned fixed specification and existing Fleet admission; no raw-text-to-shell.
This v1 lets the user converse and submit requests from the web, not approve arbitrary generated code.

Runner: new `zeus desk run --revision <40hex> [--once]` owns a runtime FileLock and processes one
request at a time. Default loop continues for future local messages, with interrupt shutdown and
no automatic retry of failed/uncertain requests. Startup: queued remains queued; dispatching with a
matching succeeded task can be finalized without another provider call, otherwise mark uncertainty
and retain evidence. Never take over a running provider, clear termination marks, or reserve twice.
Use scoped outbox publication; receive only the dedicated frontdesk stream and validate exact expected
message ID/correlation/body before Workflow.handle and ACK. Foreign/malformed input fails this turn,
not an arbitrary other actor's queue. Use guarded Executor.execute_one for exactly its queued task.
Use BudgetedExecutor with the CURRENT Fleet effective accounting mode and explicit Codex model label
from existing routing, max provider handoffs1, task deadline180s/max_attempts1. Ledger settlement
failure means needs_reconciliation, not answered. Preserve reused execution/audit/termination gates.
Result sent to conductor by normal Workflow outbox; flush this correlation before recording completed
frontdesk turn. Store task_id/execution_ref and safe fixed error code; no raw exception or credential.
Use observer + collector; log intake/dispatch/terminal metadata (IDs/status, not conversation text).
Session text is user data stored in PG, not operational log content. Diagnostics never print it.

Executor: additive action branch delegates to adapter frontdesk execution helper. A clean
git.review_workspace(request base, task id), read-only `_run`, workload design, one handoff, fixed
output JSON `{answer:string, objective:string|null, acceptance_criteria:string[], questions:string[]}`.
Bound output fields in consumer as well. Before/after clean tree and exact HEAD checks; prior turns
are context, not instructions overriding host policy. Prompt Korean plain-language answer, SSOT-first,
facts vs unknowns, ask only decisions that change scope, do not recursively invent follow-up work.
No knowledge adapter writes and no model-selected provider. Reuse bootstrap with knowledge=False.

HTTP opt-in: existing `handler(snapshot_path)` stays fully read-only unless injected desk service;
production monitor web enables it only when ZEUS_DESK_REVISION is configured as a valid full revision.
GET /api/desk -> `{schema:'urn:zeus:desk:1',sessions:[...]}`.
GET /api/desk/session/<uuid> -> session and ordered request rows, safe answer/provenance/status.
POST /api/desk/sessions `{session_id,title}` ->201 or200 replay.
POST /api/desk/messages `{session_id,request_id,intent,text}` ->202 or200 replay.
All response objects use schema above, and fixed errors `{schema,error:<code>}`.
Host must match existing exact loopback authority. Every POST requires exact matching
`Origin: http://<Host>`, `Content-Type: application/json` (optional charset=utf-8),
`X-Zeus-Desk: 1`, one valid Content-Length <=32768, no Transfer-Encoding; read timeout5s.
Missing/foreign/null origin refused403, length missing411/too large413, bad input400/conflict409,
disabled503. No CORS grants. GET and old routes unchanged, unrelated POST405. No body/exception echo.
Local OS user/processes are the trust boundary; not multi-user authentication or remote-safe exposure.

## Owner delivery records (B, separate from conversation)

Add `zeus fleet record-delivery --job <id> --file <json>` trusted owner CLI only. Immutable PG
fleet_delivery records, no web/model writer. Document `{schema:'urn:zeus:owner-delivery:1',job_id,
candidate_revision,merge_revision,deployed_revision,recorded_at,evidence_refs,report_url}` with
40hex revisions (deployed nullable), aware timestamp, nonempty sha256 refs, https github repo report
URL or null. Existing accepted fleet job required. This is explicitly owner-reported evidence, not
independent GitHub/network verification. Same complete document replay idempotent, conflicting record
refused; never alter job status or grant authority. Optional safe `delivery` in Fleet job projection:
document fields + `authority:'owner_recorded'`. Missing remains unknown. Frontend displays source
label and revisions, distinguishes merged vs deployed. Do not infer delivery from another job's
timestamp or goal. Owner records actual #157 facts after verifying bindings from preserved receipt;
worker must not seed production state. This record is for visibility, not a release approval gate.

## B tests and concrete handoff

Normal actual HTTP/PG persistence and outbox; same-ID replay/conflict, concurrent duplicate request,
session ordering, invalid bounds, unavailable store, old readonly handler, origin/header/body gates,
provider success/timeout/settlement failure, interrupted ownership with no extra call, result binding,
foreign message refusal, owner delivery conflict/nonaccepted job/projection. Use MemoryStore and
existing optional real-PG fixture; label injected provider failures, do not claim a fixture calls AI.
No frontend or compiled asset edits in B. Focused pytest plus ruff only; owner performs full CI and
actual browser -> Redis -> PG -> Codex -> response, refresh persistence, and existing UI checks.
Allowed: new domain/frontdesk.py, application/frontdesk.py, adapters/frontdesk.py,
adapters/frontdesk_cli.py, adapters/frontdesk_http.py; adapters/executor.py additive branch;
resources/organization.json; cli.py thin parser/dispatch; monitor.py and adapters/monitoring_web.py
opt-in only; application/fleet.py, domain/fleet.py, adapters/fleet_cli.py for owner delivery;
tests/test_frontdesk.py, tests/test_frontdesk_http.py, tests/test_fleet_delivery.py, BACKEND.md.
No schema migration needed: existing documents store. No control over fleet pause/budget via web.

## Preserved-draft completion batch (2026-09-20)

Both 900-second Claude turns timed out after source export, without acceptance. UI draft 4ece013
and backend draft 39c69cd are preserved and integrated, not accepted. Owner A typecheck/lint passed;
B 97 focused tests + ruff passed. An initial B test command omitted PYTHONPATH and loaded the old
compatibility checkout; that collection error is not a product defect. Production is unchanged.
Reuse these drafts. Final independent review covers the whole feature relative to e67842a, not only
follow-up diff. No expanded feature scope or blank-slate retry.

### B completion

1. execute_frontdesk always receives snapshot=None. Connect bounded sanitized owner-runtime
monitoring.json facts to that actual adapter path: capture/freshness, source states, fleet status/
accounting and pending observation counters. No paths, credentials, task bodies or raw logs.
Missing/stale/invalid snapshot is explicit unknown, never silently current or a provider failure.
Test the actual execution helper, not only evidence(snapshot=...).
2. recover currently finalizes succeeded tasks without settlement or publication proof. Persist a
per-turn accounting receipt containing only newly created wrapper slots after call and before final
status. Recovery requires durable settled receipt, bound task/result and successful scoped flush;
otherwise needs_reconciliation without a call. Crash between settle and receipt is unknown, not
success. Previous-turn slots must not contaminate later outcomes. Do not edit machine ledger.
3. Collect observations after turns/recovery. Bound process summary memory. Dispatch exceptions end
in safe uncertainty where storage works; unavailable store leaves dispatching for startup, no retry.
Release observer/lock even if wiring fails. Reuse metadata-only events. Keep host policy/deadline/
read-only/outbox scope. Focused regressions + ruff only; BACKEND.md <=35lines, no long narrative.

### C frontend completion

Add views/desk.tsx, lib/desk.ts and App navigation '대화 창구', using exact implemented API above.
Installed shadcn/tokens/Lucide only, no packages. Desktop session-list/thread; mobile stacked layout.
Create/select session, consult/request intent, send, durable pending/answer/failure/reconciliation/
needs_spec states and provenance. Escaped plain text. Request is proposed goal, not implementation.
Show a simple flow 사용자 -> 창구 -> 지휘자 검토 -> 명세 -> 팀원 작업, marking only actual stages.

Client checks HTTP status/schema/shape, aborts timed-out requests, polls selected session only while
visible, prevents overlapping/stale-selection writes. Persist selected session and uncertain
submission UUID+body locally until authoritative outcome; retry identical identity/body, never a
fresh call on network uncertainty. Stable creation IDs too. Disable double send, explicit retry,
surface409/503, retain prior history with stale indication. Reload PG history; max6000chars. No
model/base/command controls, no user text in console. Keep existing views and accessibility.

Accounting: only one explicit mode uses it; both absent legacy finite; conflicting explicit modes
or malformed present values unknown. Subscription migration numbers secondary, never active ceiling.
Short human explanation; hide wire details. Keep historical errors separate from pending counters.
Decode optional owner delivery in live Fleet AND pinned report; label owner-recorded, separate merge
and deploy, missing unknown. No hardcoded PR facts or independent-verification claim. UI.md <=35lines.
Worker ruff only (node absent); owner npm typecheck/lint/build/browser and full preserved-A review.

Finish original matrix, exactly two predeclared real browser turns, replay without extra call, no
automatic implementation, CI, pinned release and hidden local desk service. Broad redesign and
autonomous approvals remain excluded.

## Consolidated browser-boundary acceptance repair

Owner and independent review of de1514a agree on a single browser-state repair, not new features.
Owner npm build actually fails TS2367 in fleet.tsx277/278; lint fails desk.tsx153/156 refs during
render and194/199 effect state updates. Fix source patterns, no lint exceptions. npm typecheck alone
did not exercise referenced application build; final npm build is required.

The client-boundaries owner probe (injected Fetch responses, not a real model) confirms 503 becomes
refused and stalled response.json is still pending after8.3s with signal not aborted. Keep deadline
and external cancellation active through reading/parsing, handle already-aborted signals, always
cleanup in outer finally. A fixed503/5xx error is uncertainty: server transaction commit response may
be lost. Do not claim 'not stored', clear its ID, or allow new identity. Only explicit4xx validation/
conflict is definite refusal. Persist/freeze the complete pending creation (UUID+title) as well as
message (UUID+body), before POST. Reload/retry must reuse it; no erase-unresolved button. If storage
cannot persist, refuse before POST with plain explanation (not a silent memory-only fallback).

Serialize ALL history reads (poll/manual/post-send), or monotonically guard every response, and
prevent old same-session responses from replacing newer history. Selection check alone is not enough.
Unmount cancels and prevents state writes. Keep React ref updates in handlers/effects, not render.
Create-state title stays frozen while uncertain. All plain-text states stay truthful. Concise UI copy:
user sees actions and outcomes; keep receipt IDs/authority/wire jargon inside details, no new redesign.

Implementation limited to existing desk client/view, fleet type error and UI.md<=35lines. Worker
ruff only; owner executes npm lint/build, deterministic503/body-timeout and browser replay/reload/
selection tests. Preserve accepted accounting, report diagrams and delivery. Repair review is scoped
to these changed boundaries, not another exploratory pass.
