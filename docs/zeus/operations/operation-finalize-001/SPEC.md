# Operation finalization and message observability — one delivery frame

2026-09-18, Codex design/acceptance; Claude implementation through actual Zeus isolated worker.
Base main022571d. User says proceed after observatory-001 named these two operating residuals.

## Outcome, authority, completion

An ordinary failed/rejected bounded operation must not require an owner to manually cancel its
unstarted rework/diagnose before the next independent operation. Preserve its actual failed/rejected
outcome and evidence. Record receive/ledger handling/ACK/outbox publication as distinct general
observations on operate/cycle/autonomous paths, using the existing durable observation pipeline.
Existing approval authority, model budgets, uncertain-effect blocking, conductor release/merge,
and accepted evidence are unchanged. No automatic model retry, diagnosis, merge or deployment.

One implementation/review batch; two model calls initially reserved (ledger141->143), Claude USD8,
1200s. Owner performs full tests/real PG+Redis fault-path verification and CI; worker focuses on
the fixed matrix. Product edits belong to Claude. No runtime cleanup by ad-hoc owner scripts as a
substitute for implementation. Completion = matrix satisfied, CI passed, merged, local runtime
updated, real message/log evidence and dispositions visible; unresolved running/unknown-effect
records intentionally remain operator-owned. Not a claim of complete unattended operation.

## Actual architecture and evidence

`Operation.run -> LocalCycle.step -> RedisBus.receive/decode -> Workflow.handle -> outbox flush
-> XACK -> guarded execute_one/decide_one -> Operation._finish -> observation collection/receipt`.
Workflow may create rework after rejected lead review; executor failure can leave retry and pending
diagnose records. The bounded operation correctly stops, but leaves those rows/messages eligible.
LocalCycle then refuses the next correlation through foreign_queue/foreign_correlation.
This happened repeatedly in observatory-001; original receipts and explicit owner dispositions are
under D:/workspaces/zeus/artifacts/observatory-001 and bound by its evidence indexes.

cli.serve emits existing general message events; LocalCycle has no observer and calls
flush_outbox without audit. operation_cli/autonomous already own observers but do not pass them
through Operation/LocalCycle. The current monitor reads these observation buckets generically.
PostgresStore.transaction uses pg_advisory_xact_lock(734219); MemoryStore uses one RLock+draft.
Claims, Workflow state transitions and operation finalization therefore share transaction ordering.

Primary docs opened 2026-09-18 (local compose Redis7.4):
- https://redis.io/docs/latest/commands/xack/ — ACK removes a consumer-group PEL entry, not proof
  of business success. Therefore commit durable handling/parking before ACK; do not use XDEL.
- https://redis.io/docs/latest/commands/xautoclaim/ — idle pending ownership may move and be
  redelivered. Therefore durable idempotence and same-ID/different-body rejection are required.
These docs support transport semantics, not correctness of our implementation. No new research
is needed; no Kafka/broker replacement, queue-wide deletion or timeout increase.

## Complete design and ownership boundaries

### A. Terminal operation policy in one application module

Add `application/operation_finalization.py` (or equivalent one module, avoid cycles). A message/row
is operation-owned only when its exact `operation:<id>` correlation resolves to an existing
operations row with that same correlation and cycle/assignment identity, and its role is exactly
worker:implementation or lead:improvement. Non-operation, absent, malformed, or active operations
keep existing behavior. Never infer ownership from a free-text task description or prefix alone.

At Operation._finish, inside the SAME transaction that makes the operation terminal, retire only
owned non-running tasks queued/retry and lead decisions pending/retry. Preserve source message,
result, error/failure/attempt history and candidate/evidence. Write an append-only disposition
(stable ID and before hash/state/generation) and mark current row cancelled with retirement metadata;
advance existing execution generation fence and clear inactive lease metadata. Do not manufacture
an execution or successful outcome; do not send cancellation notices that recursively make work.
Already terminal rows are untouched. Conductor decisions/release messages are untouched.

Running rows, live owners/leases, blocked or unconfirmed/pending_reconciliation termination markers
are NOT retired or resolved. Record unresolved IDs/reasons in the finalization summary, emit a
warning, and retain existing execution protections. A failed DB transaction cannot leave terminal
success or an ACK without durable disposition. Unknown/in-flight operation cases are not converted
to completed cleanup. The operation outcome is immutable evidence, separate from cleanup summary.

Late delivery/restart: in the SAME Workflow.submit/handle transaction as any potential new queued
task/decision, recognize proven terminal-operation messages for the two roles and persist an
idempotent `operation_message_dispositions` record with original validated six-W message, digest,
operation ID and fixed reason. Return a parked receipt, without creating runnable work. Reject
same message ID with a conflicting digest. Preserve notice evidence too; never produce follow-up
work from parking. Authorization is checked first. Conductor recipient messages bypass parking.
Already stored records are handled by finalization; late messages are handled by the same policy.

LocalCycle._deliver may consume a foreign message ONLY when this terminal policy has durably
parked it. Then ACK and continue within existing MESSAGE_DRAIN bound, allowing the next live
correlation to be reached. Unproven/active foreign messages keep existing refusal and no ACK.
No unbounded drain; no raising reclaim speed for another active consumer. A replay after PG commit
but before ACK returns the identical disposition, and no model call occurs for the old operation.

Do not change the Redis namespace or consumer-group identity. Do not mutate historical operation
receipts to say accepted. `operate status` remains read-only. Add a safe finalization summary to
receipt projection (counts/IDs/reason codes, not raw payload/error). No blanket historical sweeper.

### B. Existing observation path, explicitly wired

Pass optional observer through operation_cli -> Operation -> LocalCycle and autonomous -> Operation,
plus CLI cycle. No hidden second observer/spool. Emit existing general.message_received after
validated decode, general.message_accepted only after durable handling, acknowledged only after
ACK returned; rejected after invalid/unauthorized handling with sanitized type only. Parked is a
durable disposition, never a successful task; make it explicit via an operations finalization/
parking event with allowlisted identifiers/counts/reason code. Log foreign refusal as blocked,
not dead-lettered. Route all affected outbox flushes through observer.audit_system, preserving
existing same-transaction audit behavior. Observer absent preserves existing test callers.
No raw message, prompt, token, exception string or credentials in observation attributes.

Expose summary through existing operate receipt and generic operations observation logs; no new UI
or notification channel is required. Collect after finalization emits when practical so the receipt
does not claim later events were collected earlier. Distinguish failed collection from clean zero.

## Fixed acceptance matrix

| Path | Required evidence |
|---|---|
| Normal accepted | current task/lead result preserved; conductor release unchanged; distinct general events; no extra calls |
| Worker retry + diagnose | finalization retires owned non-running rows atomically; history/failure kept; next independent cycle progresses |
| Lead rejected + rework | rejected operation stays rejected; pending rework parked before ACK; next cycle reaches its own assignment |
| Late/repeated message | terminal fence prevents new runnable work in submit AND handle; identical replay idempotent; conflicting body refused |
| Commit/ACK gap | real PG+Redis with injected ACK failure: durable disposition first, PEL retained, redelivery acknowledged without execution |
| Wrong owner/active foreign | no retirement/ACK, refusal unchanged; no conductor consumption |
| Running/unconfirmed | unchanged protected state + explicit unresolved summary; no fence reset or reconciliation |
| Concurrency/restart | PG transaction ordering, claim-vs-finish and submit-vs-finish races; only one safe ordered outcome; after restart late message remains parked |
| Logging failure/privacy | no false ACK/success; existing observation health reports failure; logs do not serialize synthetic canary secrets |
| Bounds | existing message drain retained; oversized residue not reported wholly drained |
| Platforms | Windows and Linux CI full suite; real host PG+Redis checks; no WSL platform redesign |
| Cleanup | test-owned schema/namespace only, production existing rows untouched by tests, call budget unchanged in no-provider tests |

Tests can inject a deterministic failure at a boundary and use explicitly synthetic six-W inputs,
but must exercise actual Workflow/LocalCycle/Operation transactions. At least the PG+Redis cases
use actual services and inspect PEL/DB rows, not a fake bus pretending to establish those facts.
Do not describe synthetic fixtures as real model execution or actual production outage.

Allowed implementation: application/{operation_finalization,operation,local_cycle,workflow,autonomous}.py,
adapters/operation_cli.py, cli.py, domain/observation.py and its schema if required; focused tests
and docs/contracts.md, this task IMPLEMENTATION.md. Owner can widen only for a concrete changed
boundary. No UI, provider, authentication, skill evaluator, generic scheduler or configuration churn.

Worker runs exact commands: `python -m pytest tests/test_operation_finalization.py tests/test_operation.py
tests/test_local_cycle.py tests/test_observation_wiring.py tests/test_workflow.py tests/test_autonomous.py -q
-p no:cacheprovider` (one line), and `python -m ruff check .`. Integration skips in worker are
explicit; owner/CI runs full suite and real integration. Do not run full suite inside the model call.
Owner independently reviews this complete matrix once, then only directly affected corrections.
