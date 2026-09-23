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
| Accepted lead | guarded `Executor.decide_one("conductor", expected=...)` | `zeus continuation conduct` as an owned, polled child (`ConductorProcesses`, `ProcessTree`) |
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
- (Superseded by the correction below.) The first candidate ran the conductor child synchronously
  with `subprocess.run` inside the tick and treated any dispatch exception as `recovery_required`.
- Delivery is a handoff: no production enabling, merge or host switch is performed by this
  controller. HostDelivery remains the owner of publish/merge/switch/rollback.
- `tests/test_operation.py` FakeExecutor now uses a valid 40-hex tree (`"7" * 40`) so the real
  session owner can freeze its candidate; no assertion depended on the old invalid value.

Rollback: unset `ZEUS_CONTINUATION_POLICY` (or register nothing); the runner, finite Operation and
executor paths are then exactly the previous ones. Recorded intents and bindings stay as evidence.

## Consolidated correction (SPEC 2026-09-23, review 7416beb6 of 77dbb04f)

The rejected candidate 77dbb04f is the base of this change and is kept, not recreated. One design:
the continuation is a restartable, nonblocking, identity-bound effect owner.

| Finding | Change | Deciding regressions |
| --- | --- | --- |
| R1 no transition for persisted `intended`/`returned` | `domain.continuation.RESUME`: one action per open (route, state); `_advance` dispatches by it. `intended` conductor resumes through the guard to a launch; `returned` completes from the committed outcome held on the intent (`decision` for the conductor) | `test_every_open_route_state_has_exactly_one_resume_action...`, `test_conductor_restart_after_each_commit...` (intended, dispatched, started-response-lost, returned), `test_successor_restart_after_each_commit...` (intended, published, enqueued-response-lost, returned) |
| R2 delivery chosen by `release_id` only | `bind_delivery`: the one plan of the policy target for the exact release AND accepted candidate revision, cross-checked with the `releases` record; `delivery_binding` tuple on the intent, re-validated each observation; foreign/stale/ambiguous/mismatch are named waits with no write | `test_delivery_is_bound_to_the_policy_target_and_the_exact_release_candidate` (two targets on one release, intended one pending, foreign rollback), `test_bind_delivery_selects_only...` |
| R3 synchronous `subprocess.run` in the Fleet tick | `adapters/continuation_process.py`: `ConductorProcesses.start/poll` over `ProcessTree`; launch identity committed before start; `lock`/`claim`/`exit.json` evidence reconciles without a handle; fenced launches never enter; timeout ends the owned tree; `ContinuationPass` gives the runner `owned/unresolved/drain`; conductors take a `max_parallel` slot, count in the heartbeat and keep stop/`--once` draining; `LaneConductor` removed | `tests/test_continuation_process.py` (real sleeping children: owned poll, restart reconciliation, fence, two owners, spawn failure, timeout, FleetRunner with a second family), `test_runner_counts_a_pending_conductor...` |
| R4 runtime checked only when binding/observing | `_authorize`: registered digest + `check_scope` + stored `authorization` vs current, before every bind/enqueue/start incl. resumed and re-dispatched work; drift records a `hold` once and refuses; reconciliation needs no guard; pin changed/unreadable -> `drain` only | `test_drift_during_an_outage...` (image/profile/archive), `test_conductor_drift_after_an_outage...`, `test_drift_while_the_child_runs...`, `test_changed_runtime_after_a_lost_dispatch_response...` |

Decisions: an exited child whose row is still `pending` attempt 0 may be followed by a NEW launch
identity, bounded by `MAX_LAUNCHES` = 3 (`conductor_launch_exhausted`), because the expected-row
guard - not the launch count - bounds model calls. A drift `hold` is a note on an open intent, not a
terminal `refused`, so the owner restoring the authorized binding resumes the SAME intent; nothing
adopts the changed binding. Intents written by 77dbb04f lack `authorization`/`delivery_binding`: a
new effect of one is held (`authorization_unknown`) and its delivery is a named wait
(`delivery_binding_changed`) rather than a guess; no such rows are known to exist outside tests. POSIX limit (documented in the module): a wrapper killed on its own
releases its lock while the command may still run; its row then stays `running` and becomes recovery
work, never a relaunch. Windows job-object behaviour of these children was not executed here.

## Verification in this batch (worker, Linux container)

Focused files: `tests/test_continuation.py`, `tests/test_continuation_cli.py`, `tests/test_git.py`
plus the directly affected operation, local-cycle, fleet, backlog, monitoring, session and executor
suites; Ruff over the repository. See the worker result for exact commands and counts. Labelled
fixtures: FakeExecutor (worker/lead), ConductorFixture / GuardedDecider (conductor), a fixture
`ProcessTree.spawn` recorder, injected lane/Fleet response loss and `Crash` process deaths at exact
commit boundaries, and controlled sleeping children standing in for the conduct command. Real:
local child processes, locks and launch files of `ConductorProcesses`, MemoryStore flows,
Fleet, Operation, LocalCycle, Workflow, finalization, WorkerSessions archives, Portfolio, temporary
Git repositories.

## Not established here (owner qualification gates)

- Real PostgreSQL lane schemas and Redis delivery; the conductor's Redis stream message is handled
  from the operation's outbox row and stays unacknowledged in the stream (idempotent by inbox hash).
- A real two-turn model session through the isolated worker and the correction resume.
- A managed Fleet run with the policy enabled, actual HostDelivery consumption/rollback, and two
  useful unattended jobs.
- Native Windows execution of these tests.
