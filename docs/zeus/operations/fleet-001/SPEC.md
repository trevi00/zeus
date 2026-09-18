# Fleet 001 — durable parallel admission and team visibility

Owner: Codex, 2026-09-18. Base b398bb8ccce571e5c8205c8fb61fd8c419a483d3.
One delivery following accepted parallel-adoption-001, not a repeat of that pilot.

## Outcome, scope and completion

User authorizes advancing from two hand-launched lanes to reusable bounded unattended admission
and a combined team board. Codex owns this design, acceptance and release; actual Zeus Claude
workers implement. Reuse Operation, LocalCycle, six-W/Redis, evidence inspection, independent
review, isolated containers, machine CallBudget and existing SSOT. No new agent framework.
Git owns definitions; PG owns runtime. Do not touch existing dirty analysis files, auth or ledger.

Deliver a first-class `zeus fleet` control plane: register host lane definitions, enqueue explicit
goal-bound operation manifests, dispatch up to the fixed concurrency cap, persist ownership and
outcomes, pause future admissions, and show all teams in the existing read-only observatory.
Use one local machine, one control store/fleet, pre-provisioned lane PG schemas, Redis namespaces
and short D runtime roots. These namespaces are logical isolation, not DB privilege boundaries.
No generated backlog, automatic model retry, automatic merge/deploy, automatic authority increase,
automatic schema creation, remote-host scheduler, takeover of uncertain execution or new knowledge
promotion. Research/debate remain existing autonomous/council workflows; fleet v1 executes only
owner-designed Operation manifests, and does not pretend that an Operation v1 ran debate.

Complete when backend and UI candidates are independently reviewed, focused/full checks and CI
pass, actual dispatched isolated operation evidence is collected, team UI reflects persisted facts,
and the reusable service is installed idle with explicit pause/budget status. Reboot/logged-out
operation and whole asset absorption are not established by this delivery.

## Evidence and decisions

Facts: PostgresStore.transaction uses a transaction advisory lock (734219), so existing store
transactions can serialize admission/reservation; never hold that transaction across subprocesses.
LocalCycle refuses foreign active same-role/correlation tasks. Preserve it: one active job per lane,
with unique schema/Redis namespace/runtime. Existing Operation owns immutable ID, budgeted
provider calls, exact evidence and independent review; terminal `accepted` means reviewed candidate,
not merged completion. Machine budget is shared across all lanes and checkouts.

Observed pilot: two concurrent operations succeeded under separate namespaces. It did not implement
admission or aggregate monitoring. Existing monitor separates a privileged read-only collector from
an unprivileged HTTP reader. Extend its snapshot additively, do not give HTTP process DB credentials.
Sterk #89/#92 are historical UI references: adopt visible work state, ownership, freshness and unknown
values, not file-based runtime authority or untrusted raw error display.

Primary sources consulted 2026-09-18:
- PostgreSQL 18, https://www.postgresql.org/docs/current/explicit-locking.html : transaction advisory
  locks are released with the transaction. They serialize claims, not a long-running external action.
- Redis XREADGROUP https://redis.io/docs/latest/commands/xreadgroup/ : consumer group pending
  delivery/ack is not proof of successful business execution. Existing outbox/inbox/Operation remains
  authority; fleet does not treat queue emptiness/ACK as completion.

Inference: a durable central reservation plus existing per-lane operation ownership is sufficient for
local admission without removing single-lane safety. Unknown external effects must retain the lane
and path reservation. Unproven: crash-free continuous service, model efficacy of adopted guidance,
or cross-host budget coordination. Do not claim them.

## Complete path and contract INV-FLEET-001

Owner register -> strict host config -> PG fleet definition -> explicit enqueue validated Operation
and bound repository/base/goal -> queued job -> atomic admission (paused, capacity, lane, dependency,
path conflict) -> committed dispatching reservation with owner token -> child existing `zeus operate
run` with lane environment -> read exact durable lane Operation -> central terminal projection ->
read-only monitor snapshot -> team board. Child stdout alone never establishes acceptance.

### Configuration and CLI (backend lane)

Add domain/fleet.py, application/fleet.py, adapters/fleet_cli.py and adapters/fleet_runtime.py; other
small fleet-specific helper modules allowed. Thin CLI wiring in cli.py. No policy duplication in shell.

Host config `urn:zeus:fleet:1`:
`{schema,id,max_parallel,budget:{per_host,total},lanes:[{id,team,repository,schema,redis_namespace,runtime}]}`.
1..4 lanes, max_parallel 1..lane count. Tokens strictly bounded ASCII. repository/runtime absolute
resolved paths; runtime roots distinct and not nested, separate from repositories. Schemas unique,
non-public safe identifiers; namespaces unique. No DSN/token fields. Single registered fleet per
control store; registration idempotent for identical canonical config, rejects mutation/replacement.
Store config digest and validated canonical config in `fleet_registry`; provision schemas externally.
Check current_schema() of every lane equals selected schema; never fallback to public. Environment
DSN comes only from host settings; sanitized display never includes credentials or environment.
Runtime child gets *both* ZEUS_/HARNESS_ overrides, configured repo/runtime/namespace and lane DSN.
Use psycopg.conninfo, never raw DSN concatenation. Existing Docker host settings inherited; require
docker isolation on fleet dispatch, no silent host fallback. Global ledger remains default home path.

Commands: `fleet register --file`, `fleet enqueue --lane --file [--after job-id repeated]`,
`fleet run [--once]`, `fleet pause`, `fleet resume`, `fleet status`.
Enqueue validates existing operation manifest and bind_goal/GitSource against configured repository;
budget must equal fleet ceiling, paths must remain canonical relative non-glob paths. Persist frozen
canonical manifest, its digest, lane, repository identity, dependencies, created/updated timestamps.
Same operation ID cannot map to two jobs/lanes; identical enqueue idempotent, changed binding refused.
Dependencies must already exist in same fleet; accepted means candidate accepted, not applied base.
Fixed bases stay fixed: a dependent job cannot silently consume an unmerged candidate.

Atomic admission is fleet-wide in one existing store transaction: at most max_parallel reservations,
one per lane; no conflicting allowed_paths for the same resolved repository (casefold and normalize
separators conservatively on both platforms; directory prefix conflicts too); dependencies all
accepted. Failed/rejected/unknown prerequisites block their dependents without blocking independent
lanes. Model budget enforcement remains CallBudget immediately before actual provider start; fleet
never reserves duplicate model slots or resets/increases ceilings. queued budget-exhausted work is
visible and stops admitting. Pausing stops NEW admissions; running work is allowed to finish.

States: queued -> dispatching (durable before spawn) -> accepted/rejected/failed/exhausted/unknown.
Dispatching contains fresh owner token; only that owner can finalize. Claim covers dispatching,
including the interval before process creation. A start/exit/PG read uncertainty leaves `unknown`
and RETAINS reservation/capacity/path exclusion; no automatic timeout lease or takeover. A definite
pre-spawn refusal may be failed. `accepted` requires child exit0 AND exact lane durable terminal
Operation id/manifest digest with accepted state. Nonzero/contradictory/missing evidence cannot be
promoted. Persist safe reason codes, call counts and operation ID, not raw process output.
Read-before-spawn on restarted service must never launch an existing dispatching/unknown job;
such jobs are reported as reconciliation_required. No operator command falsely clears them here.
An explicit follow-up recovery can use existing exact operation evidence; outside this delivery.

The runner retains bounded children (<=max_parallel), waits outside DB transactions, and completes
claimed jobs even if another run process races. `--once` drains runnable work then exits when no
progress is possible; normal run sleeps between scans and remains available for later enqueue.
Graceful stop closes admission and drains owned work, never kills arbitrary processes. Hard crash
retains uncertain ownership. Child execution is existing isolated provider's bounded ownership,
not a newly invented thread timeout/cancellation system. No shell commands from job manifests.

### Monitoring wire contract (backend and UI lanes share this exact shape)

Add `sources.fleet` envelope using existing `{status,observed_at,error?,data}` semantics.
When unregistered: data `{schema:'urn:zeus:fleet-status:1',registered:false,lanes:[],jobs:[]}`.
Registered data:
`{schema,registered:true,id,paused,max_parallel,budget:{per_host,total},
 lanes:[{id,team,active_job:null|string}],
 jobs:[{id,lane,team,status,reason_code:null|string,operation_id,goal:{path,criterion},
 dependencies:[],calls:{reserved:null|number,settled:null|number},created_at,updated_at}],
 truncated:boolean}`.
Projection only: no full manifest/objective/repository paths/schema names/DSNs/raw errors.
Bound jobs to last 100; show truncation and never claim totals beyond the sample. `active_job` is
derived from owned dispatching/unknown reservations (including those outside sample). Status reads
PG only, never constructs executor, writes rows, reserves budget or connects to providers.
Collector source failures remain unavailable. Observation time is read time; job updated_at is the
last recorded execution fact, not heartbeat/liveness. Fleet registration is not service health.
No cross-schema full log merger: central outcomes/call counts are lane-qualified projections;
existing general/development/operations observation stores remain their original evidence authority.

UI lane: add optional fleet envelope typing without making older snapshots invalid. Add `팀 작업`
navigation/view using existing shadcn/Lucide tokens. Show conceptual owner->lane->review flow,
pause/max concurrency/budget ceiling (not remaining money), team cards and job states/criterion,
dependencies/reason/last update/call counts. Unknown/unavailable/stale/empty/truncated distinct;
unknown isn't zero and `accepted` label says review accepted, not deployed. Include paused admission
and ownership warning. No HTTP mutation controls. Mobile390px and dark supported. Keep existing
report fixed schema and behavior unchanged; don't silently include fleet into old report denominators.

## Acceptance matrix and one delivery batch

| Boundary | Deciding checks |
|---|---|
| strict admission | invalid config/identity/path/budget rejected; no writes/provider |
| normal | two independent queued jobs overlap via reusable dispatcher; exact receipts displayed |
| duplicate/concurrent | same enqueue stable; two dispatchers cannot double-claim; capacity/lane/path exclusion |
| dependency | waiting until accepted, failed dependency explicit, independent work continues |
| pause/budget | persistent pause blocks new, active drains; shared CallBudget caps actual starts |
| crash/unknown | durable pre-spawn ownership retained on restart; missing receipt/exit mismatch not accepted |
| terminal | accepted bound to durable ID/digest/exit; failure precise; no automatic retry/merge |
| logs/read path | central safe records; collector failures explicit; HTTP read-only; no credentials in snapshots |
| UI | real PG projection and synthetic unknown/empty/truncated;390px/dark; unchanged pinned reports |
| platform/cleanup | Windows local full suite, Windows/Linux CI; own child/container cleanup, dirty main preserved |

Two disjoint implementation operations: Backend owns Python/CLI/tests/contracts/backend notes;
UI owns App.tsx/snapshot.ts/new fleet view/UI notes only. Worker focused tests + ruff; owner npm
build/lint/browser/full suite/real PG and CI. Synthetic tests are explicitly labeled, not production
executions. Independent reviewer covers this matrix/direct interactions, only concrete material
acceptance failures block. Integrate once; do not broaden into unrelated reference analysis.

Owner execution budget: current machine ledger152. Implementation two Claude +two reviews, ceiling156;
Claude declared USD8/operation, timeout1800s if packaged policy accepts. After code acceptance, at
most two small real dispatched canary jobs plus reviews, total ceiling160. No automatic retries or
ceiling escalation. Any setup/implementation failure is recorded; revise this SAME frame if material.
Canary jobs are real bounded absorption notes with disjoint paths, not simulated model outcomes.
Service deployed paused/idle after canary until new explicit jobs are admitted. User does not authorize
the service to invent further tasks or unlimited spending.
