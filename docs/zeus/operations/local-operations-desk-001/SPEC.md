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
