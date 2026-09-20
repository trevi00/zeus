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
| Analysis and the model contract | `adapters.audit_execution.AuditExecution` (assigned output shape corrected below; the rest unchanged) |
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

## The admission guard (checked again, not trusted from startup)

The gate above is not only a startup check. `AuditServiceRunner._admission_gate` re-reads the
observed stop and the SAME read-only activation/release/graph gate at every new admission and again
immediately before `Executor.execute_one`, because delivery blocks and the release can change while
a message is in flight. A paused, rolled back or stale release, a changed revision or graph, a gate
read that fails (`activation_unavailable`: unknown is not permission), or a stop (`service_stopped`,
the method the signal handler calls) binds no task, enters no executor and starts zero work; the
task remains queued and the reason is recorded in `stop_reason` and the durable row. Delivery may
already have published the outbox and acknowledged this assignment before that second gate;
the gate itself does not undo delivery or claim execution. The guard governs admission only: an attempt already
inside the executor keeps its binding and is never killed, retried or reinterpreted by it, and the
existing reconciliation then decides that attempt on the next start.

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
| `activation_inactive` / `activation_stale` / `revision_mismatch` / `graph_mismatch` | the release gate stopped admitting mid-run (pause, rollback, a new active release, a changed revision or graph) | decide the release first; rerun when the activation matches this checkout again (exit 1) |
| `activation_unavailable` | the gate itself could not be read, so admission is unknown | fix the store, then rerun; nothing was admitted on an unknown gate (exit 1) |
| `service_stopped` | an operator stop (signal) was observed at an admission point | rerun when ready; the assignment stayed queued and nothing was bound (exit 0) |

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
  looking for its own assignment is claimed into THIS consumer's pending list by the read itself -
  it is not literally unconsumed - and is then counted and left unacknowledged there, so the
  existing consumer-group recovery (idle reclaim) returns it to its owner; it is never acknowledged,
  dead-lettered, submitted, rewritten or published here. The bounded read budget (8 entries per
  tick) means a stream full of foreign work ends the tick with `message_not_delivered` instead of
  handling anything. Dedicated routing for this serial, explicitly selected audit is a separate
  change, not a blocker for it.
- Monitoring wiring (`adapters/monitoring.py` `DatabaseFacts`) was NOT changed: it is outside the
  assigned paths. The `audit_service` row is readable through `zeus audit-service status` and
  `zeus inspect audit_service`; adding it to the monitor's bucket list is a separate change.
- The `run` gate requires an already reconciled active activation. This command never writes
  `research_control`; `schedule_audits` keeps calling the existing `Releases.reconcile_audits`.

## Unique result ownership in assigned partition output (this batch)

The first real two-task host canary stopped at its first task
`d1133291-1151-4ffd-987a-6671cd0f34bd` with `retry/ContractError: Duplicate coverage`: the model's
output artifact `sha256:0b573a6e14db5bd4534f4cdfb3f6f790722259e5e731eb0988073d0f412c43f4` held five
`PathDisposition` rows, two of them for the identity
`ZG9jcy9jb250cmlidXRpbmcvcmV2aWV3LWNvbnZlbnRpb25zLm1k` (`docs/contributing/review-conventions.md`).
No second task was started; the partition kept generation 0 and all 32 paths, and 64 observations
were collected with no sink failure. That is observed duplicate identity in provider output, not a
PostgreSQL, scheduler or service failure, and the existing checkpoint duplicate guard correctly
refused the whole checkpoint.

The affected assumption was that an enum-constrained array binds ownership. It binds membership
only. The one revised boundary is provider output -> decoded canonical records -> the unchanged
checkpoint:

- `AuditExecution.partition_schema(partition)` now returns `paths` and `subsystems` as closed
  objects keyed by the immutable assigned identities. Every assigned key is required exactly once
  and is `null` (not analyzed; the identity stays in remaining work) or one record body derived
  from the existing definition minus its `path`/`name` field (`AssignedPathDisposition`,
  `AssignedSubsystemAnalysis`). An empty assignment is `{}`. `partition_schema()` with no partition
  keeps the generic legacy array shape for inspection compatibility; actual execution is always
  scoped.
- `AuditExecution.decode_assigned` validates the shape before the domain decode: the result map
  must carry exactly the assigned keys, a body must be an object and must not repeat its own
  identity field, and the identity is injected from the trusted key. Nulls are omitted. Nothing is
  deduplicated, merged, reordered, retried or normalized; `parse_record` and
  `ResearchAudits.checkpoint` are untouched, so the duplicate-coverage, scope, receipt and
  evidence guards remain authoritative and independent.
- The model objective now states null/one result per identity. The domain vocabulary, the evidence
  conditions, the receipt rules, the checkpoint guards and every historical array record and
  artifact are unchanged; no migration of stored records, PostgreSQL schema or six-W messages.

Primary source, opened 2026-09-21 KST:
<https://developers.openai.com/api/docs/guides/structured-outputs> (all fields required, nullable
unions for optional values, `additionalProperties: false`, nested `anyOf` and definitions). That
supports this closed nullable object shape; it is not evidence that the local provider (Codex CLI
0.153.4) accepted this exact schema. The actual canary after CI remains the compatibility check.

Checks actually run for this batch, in the worker container:
`python -m pytest tests/test_audit_output_vocabulary.py tests/test_research_audits.py
tests/test_output_schema.py tests/test_output_validation.py tests/test_audit_output_identity.py -q`
and `python -m ruff check .`. `tests/test_audit_output_identity.py` carries the acceptance matrix
(one partial record plus nulls, path-only/subsystem-only/empty assignments, missing, foreign, inner
identity and legacy repeated-row arrays refused before the checkpoint, and the old assigned schema
reconstructed as the control that does accept two rows for one identity). Its execution tests mock
only the model turn and run the real `MemoryStore` `ResearchAudits.checkpoint` with `FixtureRunner`
receipts: no provider, Redis, PostgreSQL or host service was involved. `test_output_schema.py::
test_baseline_reconstruction_and_semantic_preservation` fails in this snapshot before and after the
change because `git show` refuses the checkout (`detected dubious ownership`, a global git
configuration this worker does not change); the historical-checkout check belongs to CI/the owner,
as does the full suite and any new host canary.

## Evidence and verification

Worker checks (container, the first candidate): `python -m pytest tests/test_audit_service.py
tests/test_research_audits.py tests/test_audit_output_vocabulary.py tests/test_observation_contract.py
tests/test_observation_boundaries.py tests/test_monitoring.py`, the full `python -m pytest` suite and
`python -m ruff check .`; the observed results are reported with the candidate. That full snapshot
suite had one git-ownership/history failure and 51 missing-`ssh-keygen` errors, which are missing
snapshot prerequisite failures. A baseline countercheck was not completed, so they are not
claimed to be independently proven pre-existing; the historical checkout CI owns the full check.

Admission-guard correction (this batch): the allocated worker checks are exactly
`python -m pytest tests/test_audit_service.py tests/test_research_audits.py -q` and
`python -m ruff check .`; the whole-suite check in a historical checkout belongs to the owner/CI,
and no full-suite, historical-schema or signing run was repeated for it. The two owner probes are
carried here as `test_a_paused_or_stale_release_after_the_first_step_admits_nothing_further` and
`test_a_stop_observed_during_delivery_binds_nothing_and_keeps_the_queued_work`, with
`test_an_active_release_admits_the_next_step_unchanged` as the active control and
`test_a_gate_read_failure_after_startup_is_unknown_and_admits_nothing` for the unreadable gate.
They pass against the guarded implementation here; the failing observation against the unguarded
candidate is the owner's own probe run, not a result reproduced in this container.

Every executor, bus, collector, release and audit in `tests/test_audit_service.py` is an injected
fixture over `MemoryStore`. No model call, Redis connection, PostgreSQL connection or host service
start happened in these checks. The actual host canary (real Redis, PostgreSQL, Codex and an active
release) is the owner's step after review and CI, exactly as the SPEC section states; nothing in
this note is evidence that the service has run in operation.
