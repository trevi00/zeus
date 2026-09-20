# Current project status and explicit follow-up links

Codex frame, 2026-09-20. User outcome: tell current active work, queued work, unresolved historical
failures and unstarted scope apart. Preserve all failed receipts. Existing research-dispatch recovery
runs independently; this batch must not touch its files, provider, evidence adapters or contracts.md.

Observed: portfolio.status reads jobs, bindings and owner acceptances in one transaction; its latest-50
sample mixes old failures and accepted follow-ups with no explicit relationship. Project criteria
remain pending until owner acceptance. Monitor API showed local-absorption missing accepted
local-absorption-001-utf8 and worker-handoff-002 bindings. UI already uses local shadcn cards, status
badges and Lucide. No new dependency or component installation is needed. Reference: existing
application/portfolio.py, frontend/monitor/src/lib/portfolio.ts and views/projects.tsx at base 5313772.

Design: extend existing portfolio, not Fleet scheduling or model prompts. Add owner-only immutable
`Portfolio.follow_up(failed_job_id, successor_job_id, evidence_refs)` and PG bucket
`portfolio_followups`, one row per failed job. Validate both jobs exist, original is failed/rejected/
exhausted, successor accepted, distinct IDs, both explicitly bound to SAME project and criterion,
nonempty evidence refs using existing validator. Exact replay is cached, conflicting rewrite refused.
Unknown/queued/running successor never resolves history. This says "owner linked accepted follow-up",
NOT incident fixed, criterion accepted, merged or deployed. No automatic relation from names or dates.

Projection: optional follow_up on each sampled historical job, only when current rows and bindings
still support it; report invalid links as unknown, never resolved. Add per-project `activity` with
full-population counts (before sampling): running=dispatching, queued, unknown, accepted jobs,
unresolved_failed (failed/rejected/exhausted without valid follow-up), historical_failed (valid link).
Derive mode unknown if unknown jobs exist, otherwise running, queued, needs_attention for unresolved
failures, idle for jobs with none active, not_started for zero jobs. These are activity labels, never
criterion completion; pending acceptance is shown separately. Running projects may still have old
unresolved failures, so display both counts. Missing optional fields from older collectors mean
"activity summary unavailable"; do not infer totals from a truncated sample. Failed history remains
available in a labelled collapsible area; current attention section includes active/queued/unknown
and unresolved jobs. Accepted prior work remains visible. Show original ID -> successor ID and owner
evidence links/identifiers without interpreting evidence as current deployment proof.

UI: reuse existing shadcn/Card/StatusBadge/Lucide. Show concise Korean labels: 진행 중, 배정 대기,
확인 필요, 조치 필요, 현재 실행 없음, 미착수. Distinguish historical processing from acceptance.
Keep stale/unavailable source behavior, sample/truncation notices, mobile wrapping and keyboard
accessibility. Do not change snapshot source-set, navigation, shared telemetry or bundled assets;
owner builds packaged assets after review. Additive backend/schema/parser changes only.

Acceptance matrix: normal bound job and linked follow-up; unknown successor refused; cross-project or
criterion refused; exact replay/conflict; accepted follow-up later unavailable -> unknown; >50 jobs
counts full population; concurrent writes use existing serialized store; old collector fields absent;
stale/unavailable envelope; zero-job project; running plus historical failures; escaped text and
mobile/keyboard use. No new subprocess or timeout policy: reuse collector bounds and existing store.
Test MemoryStore and existing isolated pgstore fixture for link/atomicity behavior. Keep existing
portfolio tests valid, add focused tests. No claims that fixtures prove live visual behavior.

Claude implementation: application/portfolio.py; tests/test_portfolio.py and optional
tests/test_portfolio_followups.py; frontend/monitor/src/lib/portfolio.ts, lib/snapshot.ts,
views/projects.tsx and existing frontend test files. No broad refactor or full pytest suite. Run
`python -m pytest tests/test_portfolio.py tests/test_portfolio_followups.py` if the new file exists,
`python -m ruff check .`, and `python -m codex_harness.adapters.monitor_frontend_checks` exactly.
Record unsupported checks as not_run. Codex owns exact-revision review, CI, live browser acceptance,
deployment and evidence-backed data links. Stop when matrix passes; unrelated redesign is follow-up.

Existing data repair: bind accepted local-absorption-001-utf8 and worker-handoff-002 to
local-absorption/adoption after checking exact goal and status. This is attribution, not project
acceptance. Other unmatched jobs are not guessed into projects. Existing current/historical
relations will be seeded only after the new API is available and evidence verified.

## Requested extension: agent execution cards (2026-09-20)

User requested agent status inside each project. The already-dispatched portfolio-status-001 manifest
remains immutable at 2d7b24b; this extension is NOT part of that worker's current assignment. Integrate
against its accepted candidate before a follow-up handoff, retaining its successful evidence. This
prevents two workers from concurrently changing the same project view or guessing the other's schema.

Observed path: monitoring.DatabaseFacts already projects agents/sessions and task execution_progress
from its own store. Fleet jobs run in separate registered lane schemas, and fleet_facts projects job
state, not provider liveness. Reuse registered lane identity and the read_receipt schema-validation
pattern. Never join a host-level `worker:implementation` row to a lane job merely by agent name.

Read-only projection ownership: host adapter observes the registered lane through a bounded, read-only
query; application/domain policy binds observation to the exact Fleet job/operation, task or decision
ID, generation, attempt and execution owner. Only then expose an optional agent_execution envelope
for that job. Do not expose DSNs, lane schema names, raw session tokens, prompts, reasoning, tool
arguments or output. Progress belonging to an earlier generation/attempt must not appear current.
Read receipt alone is not enough: distinguish recorded operation status from fresh execution evidence.

Cards show role and agent ID, provider/model only when actually recorded (otherwise unknown), current
observed stage, attempt, last progress timestamp and its age, recorded lease expiry, and fixed safe
wait/failure code. Stages distinguish implementation, evidence replay and independent review so a
completed provider is not displayed as still coding during host checks. Do not fabricate a percentage
complete or label a process alive based on `running` alone. An expired lease is a warning, not an
automatic claim that the process has exited. Display observation time/freshness independently of last
progress time. No selected agent or incomplete binding is explicit unknown, not idle or success.

Use existing observation events, not a new logging stream or per-card poller. Shared monitor collection
publishes bounded per-lane observations and a total time budget; one unavailable lane does not erase
other lanes or freeze the dashboard. Hard bounds must cover connection and SQL waits. A failed lane
read returns unavailable with a safe code. Recheck active operation identity around lane reads or bind
the projection to its original job and time; never attach an older observation to a newer active job.
No writes, retries, execution admission or worker control are added to the page.

Extension acceptance matrix: exact identity normal path; two lanes with identical role names; stale
attempt/restart; active job changes during collection; progress missing; lane unavailable; expired
lease; provider exit followed by host verification; terminal accepted/rejected; collector timeout;
unknown model; old API without envelope; keyboard/mobile and retained project-history views. Tests
exercise the lane observer and projection, not just a mocked UI badge. Live acceptance must observe
an actual assigned worker and its transition to verification/result. No live transition observed means
that criterion stays unverified. Schema/UI implementation is deferred until the predecessor candidate
is available; no new job is claimed queued or running for this extension yet.
