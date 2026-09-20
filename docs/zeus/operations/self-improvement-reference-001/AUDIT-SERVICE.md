# Operating connection: the existing source audit scheduler on this host

Purpose. This note records what the `zeus audit-service` implementation does, which existing owners
it reuses, what it deliberately does not do, and which checks were actually run. It implements the
SPEC section "Operating connection handoff (same frame)" and nothing else. Owner: Codex design and
release/scheduled-task wiring; Claude implementation. Authoritative rule text: INV-AUDIT-SERVICE-001
in `docs/contracts.md`; this note explains and bounds it, it does not compete with it.

## When to read this

Before running the host service, before reviewing the candidate, or when `status` reports a stop or
a block and the next operator action has to be decided.

## Complete affected path

`zeus audit-service run --audit-id <id>` -> host lock -> read-only activation/graph gate ->
`build_observer` / `build_executor` (existing) -> `schedule_audits(audit_id=...)` (existing
scheduler, optional filter) -> correlation-scoped outbox relay -> Redis stream of `worker:github`
-> `Workflow.handle/submit` -> `Executor.execute_one(expected=...)` -> `AuditExecution.execute`
(existing) -> `ResearchAudits.checkpoint` (existing) -> `Workflow.complete` -> observation
collection -> narrow `audit_service` state row -> `zeus audit-service status`.

Files: `src/codex_harness/adapters/audit_service.py` (the whole adapter), `src/codex_harness/cli.py`
(registration and exit codes), `src/codex_harness/application/scheduling.py` (the optional
`audit_id` filter), `src/codex_harness/domain/observation.py` (four declared event types),
`tests/test_audit_service.py`, `tests/test_research_audits.py` (the filter's scheduler test).

## What is reused, not rebuilt

| Responsibility | Existing owner |
|---|---|
| Release activation and its pause/rollback containment | `application.releases.Releases.reconcile_audits` |
| Assignment creation and generation deduplication | `application.scheduling.schedule_audits` |
| Publication | `application.outbox.relay` through `Harness.flush_outbox` (correlation scoped) |
| Transport | `adapters.bus.RedisBus` with the existing consumer-group semantics |
| Acceptance, claim guard, lease, completion, failure | `application.workflow.Workflow` |
| Analysis and the model contract | `adapters.audit_execution.AuditExecution` (unchanged) |
| Scope arithmetic and evidence | `application.research.ResearchAudits.checkpoint` (unchanged) |
| Logs and their allow-lists | `application.observations.Observer`, `domain.observation` |
| Child processes on a signal | the existing process-tree owner |

The adapter adds: the host lock, the read-only run gate, the selection of one assignment, the
durable narrow service state, and the loop that binds one task at a time.

## Prerequisites the run gate checks (and refuses)

`audit_service_lock_busy` (another owner holds this runtime), `activation_inactive` (no active
research activation), `activation_stale` (the activation names no release, or not the current
active one - legacy rows included), `revision_mismatch` (this checkout is not the activated
revision), `graph_mismatch` (the organization graph changed), `unknown_audit`, `audit_not_partitioned`,
`audit_id_invalid`, `max_tasks_invalid`. Each of them returns before an observer, an executor, a
transport or any provider exists, so a refused start runs zero providers.

## Stop reasons and the operator action for each

| Reason | Meaning | Operator action |
|---|---|---|
| `max_tasks_reached` | finite acceptance mode finished; successors stay queued | rerun when ready (exit 0) |
| `task_failed` / `task_retry` / `task_blocked` / `task_expired` / `task_cancelled` / `task_superseded` | the attempt did not succeed; it is never retried here | read the task and its evidence, then use the existing `zeus execution-recovery` or `zeus cancel`; the block lifts when that row succeeds or its execution generation advances |
| `task_unresolved` / `unknown_execution` | a bound attempt's outcome is not proven | reconcile the execution and the observation terminations first; this service starts nothing meanwhile |
| `claim_guard_refused` | the claim policy would have taken another row | let that work drain or handle it in its own service; nothing was claimed here |
| `executor_exception` | the attempt's outcome is unknown to this service | reconcile as above; the durable binding is kept on purpose |
| `message_missing` / `message_not_delivered` / `message_invalid` / `message_refused` / `publication_incomplete` | the assignment exists durably but its delivery is not proven | inspect Redis and the outbox; the record is retained and nothing is re-executed |
| `scheduler_unavailable` | the store or the scheduler failed | fix the store; no partial admission happened |

`status` reports the same reasons in `stop_reason` and `admission_blocked`, plus the current task,
the predecessor result, the checkpoint generation and remaining counts, the assignment states and
the last collection health (including a collection failure's exception type).

## Limits, explicitly

- Only `audit_partition` is executed. `audit_discovery`, `audit_acquire`, `audit_propose` and
  adoption assignments stay durably queued; `status.supported_actions` says so. This service does
  not claim ingestion or proposal automation.
- Remaining counts are scope arithmetic from the partition record. They are not semantic review,
  and a checkpoint that advances a generation with no coverage is an honest, expected outcome.
- The historical failed manual canary task stays exactly as it is; it is outside this service's
  operation boundary and is never rewritten, retried or counted here.
- Delivery uses the existing consumer-group semantics. A foreign entry this service reads while
  looking for its own assignment is counted and left unacknowledged for its owner; the bounded read
  budget (8 entries per tick) means a stream full of foreign work ends the tick with
  `message_not_delivered` instead of consuming anything.
- Monitoring wiring (`adapters/monitoring.py` `DatabaseFacts`) was NOT changed: it is outside the
  assigned paths. The `audit_service` row is readable through `zeus audit-service status` and
  `zeus inspect audit_service`; adding it to the monitor's bucket list is a separate change.
- The `run` gate requires an already reconciled active activation. This command never writes
  `research_control`; `schedule_audits` keeps calling the existing `Releases.reconcile_audits`.

## Evidence and verification

Worker checks (container, this candidate): `python -m pytest tests/test_audit_service.py
tests/test_research_audits.py tests/test_audit_output_vocabulary.py tests/test_observation_contract.py
tests/test_observation_boundaries.py tests/test_monitoring.py`, the full `python -m pytest` suite and
`python -m ruff check .`; the observed results are reported with the candidate.

Every executor, bus, collector, release and audit in `tests/test_audit_service.py` is an injected
fixture over `MemoryStore`. No model call, Redis connection, PostgreSQL connection or host service
start happened in these checks. The actual host canary (real Redis, PostgreSQL, Codex and an active
release) is the owner's step after review and CI, exactly as the SPEC section states; nothing in
this note is evidence that the service has run in operation.
