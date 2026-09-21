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
`audit_id` filter), `src/codex_harness/domain/observation.py` (four declared event types and the
analysis vocabularies), `src/codex_harness/adapters/audit_execution.py` (the assigned output shape
and the analysis outcome boundary), `tests/test_audit_service.py`,
`tests/test_audit_analysis_outcomes.py`, `tests/test_research_audits.py` (the filter's scheduler
test).

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

## Rejected analysis is retained work, not a stopped execution (this batch)

After the explicit recovery of `d1133291-1151-4ffd-987a-6671cd0f34bd` succeeded on attempt 2 and
the normal task `4a1e49fc-a59f-472a-ad12-694e3082728f` also succeeded, the normal task
`6975f930-7633-4f4b-b083-e002d04776b7` failed with `ContractError: Missing generator/original
link`. Its receipts and its observation collection succeeded and the partition kept generation 0
with all 32 paths. The discriminating fact is that the typed validator refused generated content
while the execution itself did not fail: schema and identity fixes made drafts well-shaped, not
always valid, and another mandatory-field patch would repeat that family. The service equated a
refused draft with a failed execution; this batch changes that explicit outcome boundary only and
keeps every accepted schema, identity, receipt, ownership and evidence safeguard as it is. It does
not retroactively accept either failed canary.

The boundary, in `adapters/audit_execution.py`:

- The trusted stored partition is validated BEFORE any generated content is decoded, so a stale or
  corrupt assignment is an ownership failure and never a rejected draft.
- An execution failure is not always a raised exception: `Executor._run` RETURNS an
  `inspection_blocked` envelope (`accepted` false, a stored `execution_ref`, a host reason). Both
  the planning turn and the semantic turn are classified for that envelope BEFORE the pure content
  boundary, and refused with the fixed error `Execution inspection blocked`; the returned reason is
  never read, quoted, logged or projected. Blocked wins even when the same result also carries
  otherwise valid content, and a refused planning turn runs no inspection command and no semantic
  turn. This is returned-failure versus content routing, not a new mandatory model field.
- `AuditExecution.proposed_checkpoint` is the ONE recoverable rejection boundary: it decodes paths,
  subsystems, cursor and open questions into the proposed checkpoint and touches no store, lease,
  runner, artifact or provider. Only a `ContractError` from that call is caught - not arbitrary
  exceptions, not message substrings, and not a programmer error, which is not a `ContractError`.
- On rejection the executor-owned `execution_ref` is inspected OUTSIDE that catch and a versioned
  `analysis_rejected` result is returned: task id, task generation and attempt, audit, partition,
  partition generation, that reference, the fixed reason code `analysis_content_rejected`, and the
  refusal's type with a digest of its message. `Workflow.complete` persists it through its existing
  ownership and commit path. Nothing of the refused batch is checkpointed, no generation advances,
  no scope is dropped and no knowledge is written; the raw draft stays in its immutable artifact.
- Valid content still uses the unchanged `ResearchAudits.checkpoint` and the returned task result
  carries an `analysis_checkpointed` marker with the same binding. The persisted canonical
  checkpoint is untouched. A checkpoint is partial progress, not semantic acceptance.
- The marker binds to the executor-owned reference, so an answer that carries none (an injected or
  legacy one; `Executor._run` always supplies it) still checkpoints and stays unclassified rather
  than asserting an outcome it cannot bind. Rejection is stricter: with no retained evidence there
  is nothing to review later, so a missing, unreadable or modified reference is a failure.

In `adapters/audit_service.py` and `domain/observation.py`: the step, the run summary, the durable
`audit_service` row, the `operations.audit_service_task` observation (new closed `analysis_outcome`
attribute and the fixed reason code) and `status` report the execution status and the analysis
outcome as two separate facts, read from the execution's own durable result. `--max-tasks` counts
every settled execution including rejected drafts. `status` counts the outcomes and lists each held
current-generation partition with its task, evidence reference and reason code.

Explicitly not done here: a held draft is NOT retried, reassigned or repaired by this service. The
existing same-generation schedule key holds its partition, and a future recovery or reassignment is
an explicit, reviewed operator decision; no repair endpoint or retry loop was invented, the
historical failed task `6975f930-7633-4f4b-b083-e002d04776b7` is unchanged, and no service
registration, release activation, model invocation or operational mutation happened in this batch.

Checks actually run for this batch, in the worker container: `python -m pytest
tests/test_audit_analysis_outcomes.py tests/test_audit_service.py tests/test_audit_output_identity.py
tests/test_audit_output_vocabulary.py tests/test_research_audits.py -q` and `python -m ruff check .`.
`tests/test_audit_analysis_outcomes.py` carries the acceptance matrix; every model turn in it is
INJECTED over the real store, artifacts, `ResearchAudits.checkpoint`, `schedule_audits`, `Workflow`
and observation contract, with `FixtureRunner` receipts. It is not evidence that a provider, Redis,
PostgreSQL or a host service ran, and no model was provoked to obtain a rejection sample. Its
control for the previous behaviour is `test_an_execution_failure_still_stops_the_service`: the same
refused content with no retained evidence is an ordinary execution failure that stops the service.
`test_a_returned_inspection_refusal_is_never_a_rejected_draft` and
`test_a_returned_inspection_refusal_stops_the_service_after_one_task` cover the returned envelope
from both turns, including a semantic envelope that also carries checkpointable content: zero
checkpoint and coverage, one task then a stopped service, no semantic turn after a refused planning
turn, and the canary reason in no step, log, published message or `status`. Those envelopes are
INJECTED fixtures; no bubblewrap, runner, host or provider inspection actually failed here.
The full suite, the history checks and any new host canary stay with the owner and CI.

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

## Whole-checkpoint reframe: candidate claims versus execution integrity (2026-09-21)

Why this batch exists. The explicitly authorized recovery of `6975f930-7633-4f4b-b083-e002d04776b7`
stopped again on attempt 2 with `ContractError: Unknown generator/original path`, while the actual
response `sha256:777c874c1d99b3c44f814cfe526cdda87f4361dbfdb632384cad5d8dacbf117f` carried three
human-readable links whose Base64 encodings each name an existing inventory path. The files WERE
present: the defect was representation against the contract, not missing source, a storage fault or
a database failure. A model draft can therefore pass type validation and still fail relationship
and evidence-claim validation, so the earlier pure-only restriction is superseded here: treating
every checkpoint refusal as infrastructure failure repeats the family after each schema correction.
Both failed attempts stay unchanged in the task history, and no provider was called to inspect this
evidence.

What the boundary is now. Two owners raise a recoverable rejection, and TYPE decides - never a
message substring, never a broad catch:

| Boundary | Disposition | Owner |
|---|---|---|
| Model output shape and pure typed records | Retained `analysis_rejected`, as already implemented | `AuditExecution.proposed_checkpoint` |
| Candidate record relationships and its own remaining-work reconciliation | `AuditDraftRejected`; the whole checkpoint transaction rolls back, then the draft is retained | `ResearchAudits.checkpoint` |
| A model-named artifact body that is absent AND unanchored | Unverifiable candidate evidence -> `AuditDraftRejected`, never acceptance | `ResearchAudits._claimed_evidence` |
| Returned `inspection_blocked`, runner/provider exception, invalid or stale task or partition ownership, immutable scope mutation, source or receipt corruption, a missing authoritative artifact, permission or other IO error, DB read/write/commit and continuation-authorization failure | Ordinary execution failure; never converted | the existing trusted owners |

`AuditDraftRejected` is a `ContractError` subtype in `domain/research.py` with a `reject()` helper,
so every existing caller, message and `pytest.raises(ContractError)` expectation is unchanged and a
rejection is never a relaxation. The candidate-claim checks it replaces keep their exact wording;
`require()` still owns ownership, leases, trusted scope, stored anchors and the store itself.

In `application/research.py`: `checkpoint` validates ownership, the assignment, the current
generation and the immutable trusted scope BEFORE it classifies any relationship. `_anchors` reads
this audit's authoritative artifact references from trusted records only - `source.manifest_ref`,
the verified inventory `artifact_ref`s, the evidence its partitions and checkpoints already retain,
and the stored runner `output_ref`s. `_claimed_evidence` then inspects what the draft NAMES: an
anchored reference is trusted input whose every read failure is hard, and for an unanchored one
only `FileNotFoundError` becomes a draft rejection. A modified body, invalid or missing metadata, a
permission error and every other IO failure stay hard failures, because those say the artifact
store is damaged rather than that the draft is wrong. This is a classification of existing records,
not a new provenance grant: an unanchored reference whose body is readable is as acceptable as
before. No path is encoded, decoded, normalized or deduplicated anywhere on this path.

In `adapters/audit_execution.py`: the checkpoint call is wrapped in a catch of ONLY
`AuditDraftRejected`, OUTSIDE `checkpoint`'s own transaction, so the exception has already left
that transaction and every staged coverage, history, checkpoint, partition and outbox write of the
refused batch has rolled back before the handler runs. The existing `rejected_analysis` then
inspects the executor-owned output and returns the same versioned binding, with `error_type`
naming the family and only a digest of the message. The semantic-turn instructions now state the
path-reference contract once for keys, links and subsystem trace paths; the instructions are
guidance and the validation above stays authoritative.

Explicitly not done: no new scheduler, retry policy, PG schema, repair API, provider loop,
knowledge promotion, process or socket lifecycle, and no reclassification of historical failures.
The outcome code stays `analysis_rejected` with the fixed reason `analysis_content_rejected`.

Checks actually run for this batch, in the worker container: `python -m pytest
tests/test_audit_checkpoint_outcomes.py tests/test_audit_analysis_outcomes.py
tests/test_audit_service.py tests/test_audit_output_identity.py
tests/test_audit_output_vocabulary.py tests/test_research_audits.py -q` and
`python -m ruff check .`. `tests/test_audit_checkpoint_outcomes.py` carries this matrix. Every
model turn in it is INJECTED over the real store, artifacts, `ResearchAudits`, `Workflow`,
`schedule_audits` and observation contract, with `FixtureRunner` receipts; the permission and
store-write faults are injected too. It is not evidence that a provider, Redis, PostgreSQL or a
host service ran, and no model was provoked to obtain a rejection sample. Its controls are
`test_execution_integrity_failures_are_never_retained_as_a_rejected_draft` (a missing ANCHORED body
is hard where an invented reference is a rejection),
`test_an_ordinary_contract_error_with_a_candidate_message_is_not_an_analysis_outcome` (same text,
other type, still a failure), `test_trusted_anchor_failures_stay_ordinary_execution_failures` and
`test_an_unbindable_refused_candidate_still_stops_the_service`.
`test_a_late_reconciliation_rejection_rolls_back_rows_it_already_staged` is the rollback case with
rows actually staged first. The rollback and store-failure regressions run on BOTH stores through
`rollback_store`: the `memory` parameter ran here, and the `postgres` parameter uses the existing
`isolated_pgstore` fixture in a per-test schema with no production rows. That PostgreSQL parameter
SKIPPED in this container (no `HARNESS_INTEGRATION=1`), so nothing here proves it on PostgreSQL;
the owner and CI must run it without skips. The discriminating control for the whole batch was run
by temporarily making `reject()` raise a plain `ContractError`: 19 of the new regressions failed
and the integrity and acceptance controls kept passing. The full suite, the history checks and any
new host canary stay with the owner and CI.

## Trusted guard ordering correction (2026-09-21 KST)

The independent Fleet lead's P2 static finding is now corrected in `application/research.py`: the
`Duplicate coverage` reject is inside `checkpoint`'s transaction, AFTER `_owned`, the assignment,
the stored generation, the immutable scope and the known-audit check, and BEFORE the anchors,
claimed evidence and every other candidate relationship check. Nothing else moved: the exception
types, the artifact taxonomy, the transaction semantics, the catch in `adapters/audit_execution.py`,
the scheduler and the retention rules are unchanged, and the stale "ONE recoverable boundary"
comments in `adapters/audit_execution.py` were corrected to name both halves, with no behavior
change. The owner's earlier verdict that the keyed decoder cannot emit duplicates and that
completion still fences ownership stands: no false coverage or operational failure was
demonstrated, and this is an entry-contract alignment, not a defect repair.

Checks actually run for this correction, in the worker container:
`python -m pytest tests/test_audit_checkpoint_outcomes.py -q` (40 passed, 3 skipped) and
`python -m ruff check .`. The 3 skips are the `postgres` parameters of `rollback_store` without
`HARNESS_INTEGRATION=1`; those cases are unchanged by this correction and the owner already ran
them 3/3 at the previous candidate. No other suite, no full suite, no model call and no host
service ran here. The new regressions are
`test_a_duplicate_draft_from_an_untrusted_execution_fails_as_execution_integrity`
(duplicate coverage combined with spent ownership, a stale generation, a changed scope or a
foreign assignment: each must stay an ordinary `ContractError` carrying the trusted message) and
`test_a_valid_owner_submitting_duplicates_is_still_a_typed_rejection_that_commits_nothing` (the
control: with every trusted guard passing, duplicates on either record kind stay
`AuditDraftRejected`, commit nothing and leave the lease usable). The discriminating control was
run by temporarily restoring the pre-transaction ordering in the same file: all four combined-fault
cases failed with `AuditDraftRejected('Duplicate coverage')` and the valid-owner control passed
under both orderings. A disposable checkout copy was not available in this container, so that
control ran in the working tree and the ordering was restored before the final run above.

## Goal-progress feedback: consolidated frame (2026-09-21 KST)

Why this batch exists. Successful executions currently mask semantic yield: at runtime-171 the
selected audit still had 1813 of 1817 paths remaining after 55 settled executions, while receipts
and continuation offsets kept accumulating. That is low yield, NOT a crash, a stall, an infinite
loop or a cause. This batch makes the unattended path notice it and submit ONE evidence-bound
research topic through the paths that already exist. Authoritative rule text: INV-AUDIT-PROGRESS-001
in `docs/contracts.md`; this note explains and bounds it.

What was added, and what was deliberately not. Added: `domain/audit_progress.py` (policy, epoch,
window arithmetic, verdicts, the candidate row, the eligibility rule, the council snapshot),
`application/audit_progress.py` (the observer use case and its two narrow buckets), the packaged
`resources/audit-progress-policy-v1.json`, the observer wiring plus `progress` facts, the declared
`operations.audit_progress_observed` event and the `status` projection in
`adapters/audit_service.py`, the opt-in `audit_progress_source` and the second candidate kind in
`domain/research_program.py`, `domain/research_investigations.py`,
`application/research_program.py` and `adapters/research_program.py`, and the kind-aware portfolio
projection in `application/portfolio.py`. NOT added: a second scheduler, a daemon, a retry, an
automatic patch, merge or adoption, a model call, a new permission, a new UI, an external
notification channel, a runtime-editable threshold or any weakening of an existing guard.

| Responsibility | Existing owner it reuses |
|---|---|
| What a reviewed path or subsystem is | `application.research.ResearchAudits._coverage` / `_observed` (unchanged) |
| Evidence bodies and their integrity | `adapters.artifacts.FileArtifacts` (read only, outside any transaction) |
| The owner's undecided candidate state and disposition | `application.portfolio` (`research_required`, `Portfolio.disposition`) |
| Claim, capture, council, result authority and blocking | `application.research_program` + `adapters.research_program` (unchanged) |
| Logs and their allow-lists | `application.observations.Observer`, `domain.observation` |

Operator reading. `zeus audit-service status --audit-id <id>` gains `progress` (observed, epoch,
policy digest, baseline and counted executions, windows completed, current window index, streak,
candidate id, last verdict, the last observation and the bounded metrics) and `last_progress` (what
the running service last recorded). `observed: false` means no observation exists - never that
progress is zero. A `degraded` observation names its fixed reason (`unknown_audit`,
`audit_not_partitioned`, `state_changed`, `observation_failed`, `observer_failed`,
`unreadable_evidence`, `malformed_evidence`) and leaves the audit's own execution result alone; the
operator action is to look at the named prerequisite, never to retry an execution. A recorded
candidate is a research topic for the existing program and an owner decision (`researched` or
`deferred`) through the existing portfolio disposition; it is not an incident, a fix or an approved
change.

Delivery obstacle carried in the same batch. The first Fleet job for this frame failed
`execution_stale`: preparation of 5212 files finished after the lease it was reserved under had
already expired, and the container was stopped on the immediate stale heartbeat. The cause of that
preparation delay is unknown and remains a follow-up; the narrow correction here is that
`stage_source` now calls the caller's EXISTING `on_tick` lease heartbeat as it makes progress
(passed down from `IsolatedClaudeRuntime.run`), so a long preparation renews and re-checks the same
lease it already owned, and a lease that ends mid-preparation refuses before any container exists
with the run record retained as `refused`/`preparation_cancelled`. No watchdog, no thread, no longer
deadline, no weakened ownership check and no change to the exported bytes, paths or cleanup.

Checks actually run for this batch, in this worker container: `python -m pytest
tests/test_audit_progress.py tests/test_isolated_worker_preparation.py tests/test_audit_service.py
tests/test_research_program.py tests/test_research_investigations.py tests/test_portfolio.py
tests/test_isolated_worker.py -q` and `python -m ruff check .`; the observed results are reported
with the candidate. PostgreSQL (`HARNESS_INTEGRATION=1`), the full suite, CI and any host canary
were NOT run here and belong to the owner. No model call, provider, Redis, PostgreSQL connection or
host service start happened in these checks, and nothing in this note is evidence that the observer
has run in operation: the natural live threshold and its council outcome remain pending until
actually observed.
