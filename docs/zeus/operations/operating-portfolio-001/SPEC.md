# Operating portfolio and bounded failure learning

Owner Codex; implementation Zeus Claude workers; 2026-09-20.

## Outcome and authority
Continue real operation while gathering minor defects. Make the three authorized goals visible,
bind actual Fleet work explicitly, and persist repeated-failure investigation candidates. Do not
hold operation until every reference asset is absorbed. Existing independent acceptance and
promotion remain mandatory; no automatic retry, merge, deployment or root-cause assertion.
This is one delivery: backend and view share the wire contract below. Scope excludes full asset
absorption itself, arbitrary web-request execution, recursive research agents, and redesign of
accepted isolation/readiness/profile code. Session two-strike from #160 stays unchanged.

Completion: both components independently checked, actual jobs linked to goals, historical
failures reconciled into a durable candidate queue without rewriting outcomes, live project
view verified, one actionable candidate given an owner disposition with evidence. Existing
remaining work is displayed, not silently declared done. Investigations may finish deferred
with a named evidence gap; a candidate is not a confirmed incident or verified knowledge.

## Evidence and decisions
Observed: runtime c375f95, Fleet resumed, harness/interface idle, zero queued (2026-09-20).
Git definitions; existing generic PG buckets/transactions for runtime; Fleet status is sampled
at 100 jobs, so portfolio aggregation must scan the underlying rows, not that sample.
Fleet finalize owns terminal writes; monitor collect/readers are read-only. FleetRunner admission
already has parallelism and path exclusion; no replacement scheduler is needed.
Sterk #77 is a reference analysis, not verified upstream implementation: adopt goal/step drilldown
and freshness, reuse current React/shadcn/Lucide. Upstream local captures aren't on this PC.
Primary sources opened 2026-09-20: PostgreSQL 18 tutorial-transactions (transaction changes become
visible together, rollback discards them); ui.shadcn.com/docs/components/card (header/content/footer
composition). These do not prove Zeus concurrency or UI behavior; our tests must do that.
Unknown: same status/reason across jobs need not be the same root cause. Grouping below is a
coarse triage family only. Current session-hook counted_failures is receipt observations, not
unique failures; never use it here. ResearchProgram's feed action is not arbitrary error research.

## Backend batch (harness lane)
Add application/portfolio.py, adapters/portfolio.py and focused tests/test_portfolio.py. Reuse
PostgresStore/MemoryStore buckets; no DDL or external services. Definitions are owner-written
resources/operating-portfolio-v1.json, loaded by adapter via importlib.resources and passed into
Portfolio(store, definitions). Domain/application must not read files. Validate the full shape,
unique project/criterion IDs, bounded text, relative source paths; errors name fields only.

Definitions shape: {schema:'urn:zeus:portfolio-definitions:1',projects:[{id,title,outcome,
source_ref,criteria:[{id,text}]}]}. Definitions are not runtime completion assertions.

Owner-only Python methods, no web writes or extra CLI needed in this batch:
- bind(job_id,project_id,criterion_id): require existing fleet_jobs row and defined target.
  Immutable PG portfolio_bindings row keyed by job_id; identical replay cached, conflict refused.
  Do not guess binding from titles/paths. No modifications to Fleet manifests or task rows.
- accept(project_id,criterion_id,evidence_refs): nonempty bounded opaque evidence refs; immutable
  owner record in portfolio_acceptances; same replay idempotent, different record refused.
  This trusted-owner record is the sole criterion-completion source; not inferred from job status.
- reconcile(): one serialized store transaction scans ALL fleet_jobs. For terminal failed/rejected
  jobs with nonempty safe reason_code, group by (status,reason_code), unique job IDs only. Missing
  reason excluded with count. Each >=2 family creates one durable portfolio_investigations row
  keyed deterministic sha256 of family; state research_required, job_ids sorted, count, timestamps.
  Existing candidate gains new distinct job IDs, never resets owner disposition. No raw errors,
  prompts, commands, credentials; do not use error_type. Do not count accepted/unknown/dispatching
  or replay as failures. `unknown` retains existing reconciliation semantics.
- disposition(candidate_id,state,evidence_refs): trusted owner, state researched/deferred,
  immutable first decision; same replay cached, conflict refused; refs mandatory. No root-cause
  promotion. New failures after disposition remain visible via current count; no automatic retry.
- status(): read-only complete bounded projection defined below. Definitions include all 3 goals
  even before any binding. Status never calls reconcile or put. PG unavailable propagated so
  collector returns unavailable, not zero. No mutable object aliasing.

Wire contract `sources.portfolio` uses existing status/observed_at/data envelope. data:
{schema:'urn:zeus:portfolio-status:1',definition_sha256:string,
 projects:[{id,title,outcome,source_ref,criteria:[{id,text,status:'pending'|'accepted',evidence_refs:[]}],
 jobs:[{id,criterion_id,lane,status,reason_code:string|null,updated_at}],
 counts:{criteria_total,criteria_accepted,jobs_total},jobs_truncated:boolean}],
 investigations:[{id,family_status,reason_code,state:'research_required'|'researched'|'deferred',
 count,job_ids:string[],evidence_refs:string[],updated_at}],
 investigations_truncated:boolean,unbound_jobs:number,unclassified_failures:number}.
Each project's jobs latest50 deterministic updated_at/id ordering, counts from ALL rows.
Investigations latest50; job_ids latest50, count all (UI must not assume job_ids exhaustive).
Criterion statuses ONLY explicit owner records. Unknown code/job values never become success.
No raw Fleet manifest, filesystem paths, credentials. definition_sha256 is canonical JSON digest.

Add portfolio_facts in adapters/monitoring.py, additive source independent of legacy four sources.
Add bounded reconciliation into FleetRunner.tick (inspect exact method): once per tick before
admission, separate transaction, via adapter wiring preferred to preserve application dependency.
If easiest, Portfolio reconciliation doesn't depend on definitions and can be a standalone
application function used by runner. Errors must not block unrelated Fleet operation: record
fixed unavailable state via existing logger if available, not raw exception. Do not nest tx.
Owner does initial historical reconcile and dispositions with this same API after verification.

## Frontend batch (interface lane)
Only App.tsx, lib/snapshot.ts, new views/projects.tsx and optional pure parser in lib/portfolio.ts;
add focused frontend tests if existing framework supports it. Backend paths owned by other lane.
Add 프로젝트 tab; optional sources.portfolio Envelope in Snapshot. Keep SOURCE_NAMES and pinned
report contract unchanged. View consumes exact wire above; unknown/missing/malformed/stale is not
empty or 0. Follow fleet freshness (20s, future tolerance5s) and explicit timestamp reporting.
Render three goal cards, honest accepted criteria/total progress bar, full outcome and expandable
criteria + actual jobs; count separately from displayed job sample. Keyboard-native details/summary
or buttons. Show research_required/deferred/researched queue with family reason, independent job
count, evidence refs and warning '유사 증상 조사 후보 · 원인 확정 아님'. No write/retry buttons.
Reuse existing Card/StatusBadge/Lucide/tokens, Korean copy, mobile wrapping, visual flow
목표 → 작업 → 검토 → 수용 기준. No fabricated projects or fixture fallback in production.
Do not imply accepted job=deployed or criterion=entire source absorbed. Show unbound jobs.
Worker lacks Node: report build unrun; owner builds/checks browser. No dependency installation.

## Matrix and verification
| Path | Acceptance |
| normal | 3 definitions visible; exact binding; one explicit criterion acceptance |
| failure/rejection | two distinct terminal jobs one durable investigation |
| replay/restart/concurrent | same binding/candidate/decision cannot duplicate or overwrite |
| active/timeout/unknown | unknown and active not recurrence; unchanged Fleet ownership |
| unavailable | independent envelope unavailable; unrelated admission remains enabled |
| privacy | raw errors/canary never in projection or new records |
| complete/sample | counts all rows, bounded sample labeled; no invented progress |
| view | real collected API to cards/drilldown, keyboard and narrow viewport |
| platform/cleanup | existing stdlib/store portable path; no filesystem deletion or reboot |
| research | owner evidence-based disposition; candidate != executed fix/promotion |

Workers focused checks and concise answer; owner clean candidate review, relevant integration,
ruff/full suite via CI, frontend build/browser, then authorized merge and hidden runtime switch.
Minor findings deferred against goal; critical blocker requires real violated criterion evidence.

## Consolidated owner integration review (same frame)
Actual parallel jobs ended: backend provider error_max_structured_output_retries (not timeout),
UI returned successfully but had no executable frontend evidence and the gate refused. Both
failed Fleet outcomes remain unchanged. Drafts were preserved at 3091171 (backend) and 440da12
(UI). Owner frontend build passed; isolated real PG checks passed: 4 concurrent reconciliation
calls produce one candidate for 120 distinct jobs, 50-row projection retains count120, immutable
binding conflicts refuse, explicit acceptance only, restart preserves disposition, unknown excluded,
status read-only. Synthetic PG rows never entered production. Focused checks:40 pass,2 fail.

Observation -> assumption: the runner callback was implemented but adapter wiring was outside
the original allowed paths. A callback-only fixture passed; actual fleet_cli.run still constructs
FleetRunner without it. Update the SAME batch with the missing adapter path, not another subsystem.

One completion correction, Claude scope:
1. adapters/fleet_cli.py: pass portfolio_reconciler(service.store) into real FleetRunner construction.
   Add a test entering fleet_cli.run with the actual FleetRunner and a no-admission fixture launcher,
   seed two failed jobs in isolated MemoryStore and assert durable candidate after once. Do not
   merely replace FleetRunner with a spy or directly call a callback. No model/production calls.
2. Existing source-set assertions need the additive portfolio envelope: tests/test_monitoring.py
   source_state count7 (was6) and source names; tests/test_monitoring_observations.py legacy source
   set. Preserve read-only and independent-unavailable assertions. These are expected contract
   updates, not evidence of a service defect. Include them in focused checks.
3. application/fleet.py: reconciliation failure currently only changes a summary returned when
   the long-running service stops. Emit a fixed, credential-free warning on transition into
   unavailable, and a recovery log on transition back to ok (stdlib logger sufficient). Suppress
   repeated identical failures; no traceback, raw exception or arbitrary type text. Preserve
   continuing unrelated admission. Test caplog against repeated failure and recovery.

Owner frontend lint/build and browser cover UI; do not add more UI requirements during this
correction. Keep optional numeric/inconsistent-data hardening as later improvements unless real
collector output violates the view. Evidence references are supplied only by the trusted owner;
stronger reference grammar can follow later, without exposing web write authority now.

Finish concise terminal JSON matching supplied response schema. `tests` only exact commands
actually executed, no status strings in it. No arbitrary Python diagnostics, git config mutation,
or rollback experiments. Existing APIs and accepted PG checks remain intact.
