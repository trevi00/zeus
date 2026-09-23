# Durable conductor continuation (implementation record)

Frame: SPEC.md "Accepted primitive integration and final connection batch" (Durable conductor
continuation) and "Conductor continuation SSOT finding" (routing table). Contract:
`docs/contracts.md`, INV-CONTINUATION-001. Base revision 60f79586. This is an implementation
candidate for independent review; it is not deployed, enabled or qualified.

## Composition (reuse, not a second engine)

| Stage | Existing owner reused | Added connection |
| --- | --- | --- |
| Policy | Git pin via `GitSource`, strict JSON reader of the approved backlog | `urn:zeus:continuation-policy:1`, `zeus continuation register/identity` |
| Tick | `FleetRunner` optional hook, like the approved backlog | `ZEUS_CONTINUATION_POLICY`, pass after backlog, before admission |
| First item session | `WorkerSessions`, `Executor._run(task_session=...)` | lane `continuation_bindings`, `Operation.claim` attaches it, `execute_one` passes it (`max_handoffs=1`) and freezes the candidate |
| Rejection | executor's committed `review_lead` row, `WorkerSessions.record_review` | correction successor, same frame, `Fleet.enqueue` |
| Evidence refusal | Operation owner handoff | evidence-repair successor, candidate preserved, fresh handoff |
| Two distinct failures | Portfolio investigation (`researched` disposition) | family hold until researched |
| Unknown effects | ExecutionRecovery, termination markers | `recovery_required`, no call |
| Accepted lead | guarded `Executor.decide_one("conductor", expected=...)` | `zeus continuation conduct` in the lane environment (`LaneConductor`) |
| Release | Releases/ReleaseQueue rows the conductor decision writes | `host_delivery` handoff on the policy target; observes HostDelivery intents |
| Next item | approved backlog (`FleetBacklog`) | `next_item` handoff after `active` delivery |
| Workspace | `GitWorkspace.prepare` pinned base | `continue_workspace` at exact last candidate HEAD, clean, no live/blocked owner |

## Decisions and compatibility

- Successors are new finite operations (`cont-<24 hex>` of the intent id). No parked message is
  revived and no terminal operation row is rewritten. Legacy operations without a binding keep
  their exact row and assignment shape (tested).
- The lane binding, not the manifest, carries lineage: `domain/operation.py` (manifest schema) was
  outside the allowed paths, and the executor re-reads the lane row so a message cannot forge it.
- Evidence repair never resumes a session: the session is still `awaiting_review` with no review
  decision, so resuming it would relabel an unreviewed context. It gets the workspace and explicit
  references instead.
- The conductor child's timeout or any dispatch exception is an unknown effect
  (`recovery_required`), never relaunched. A `pending` conductor row with attempt 0 is provably not
  entered and may be dispatched again by the owner port.
- Delivery is a handoff: no production enabling, merge or host switch is performed by this
  controller. HostDelivery remains the owner of publish/merge/switch/rollback.
- `tests/test_operation.py` FakeExecutor now uses a valid 40-hex tree (`"7" * 40`) so the real
  session owner can freeze its candidate; no assertion depended on the old invalid value.

Rollback: unset `ZEUS_CONTINUATION_POLICY` (or register nothing); the runner, finite Operation and
executor paths are then exactly the previous ones. Recorded intents and bindings stay as evidence.

## Verification in this batch (worker, Linux container)

Focused files: `tests/test_continuation.py`, `tests/test_continuation_cli.py`, `tests/test_git.py`
plus the directly affected operation, local-cycle, fleet, backlog, monitoring, session and executor
suites; Ruff over the repository. See the worker result for exact commands and counts. Labelled
fixtures: FakeExecutor (worker/lead), ConductorFixture / GuardedDecider (conductor), a fixture
process runner for `LaneConductor`, injected lane/Fleet response loss. Real: MemoryStore flows,
Fleet, Operation, LocalCycle, Workflow, finalization, WorkerSessions archives, Portfolio, temporary
Git repositories.

## Not established here (owner qualification gates)

- Real PostgreSQL lane schemas and Redis delivery; the conductor's Redis stream message is handled
  from the operation's outbox row and stays unacknowledged in the stream (idempotent by inbox hash).
- A real two-turn model session through the isolated worker and the correction resume.
- A managed Fleet run with the policy enabled, actual HostDelivery consumption/rollback, and two
  useful unattended jobs.
- Native Windows execution of these tests.
