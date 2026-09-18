# operation-finalize-001 — implementation note

Worker: Claude (isolated Zeus worker), 2026-09-18. Base `0a061c4b`; correction batch on `beea02a1`
(SPEC "Consolidated acceptance review 1"). Contract: INV-OPERATION-FINALIZATION-001 in `docs/contracts.md`.

## Change (original delivery)

- `application/operation_finalization.py` (new): exact ownership (`owner`, `terminal_owner`), same-transaction
  `retire` (dispositions, cancelled rows, fence advance, unresolved summary) and `park` (idempotent
  `operation_message_dispositions`, conflict refusal, parked receipt).
- `application/workflow.py`: `submit` and `handle` (reports and execution notices) park terminal-operation
  messages in the transaction that would queue work; conductor recipients bypass.
- `application/local_cycle.py`: optional `observer`; foreign messages are ACKed only after a durable parked
  receipt, otherwise the existing refusal; shared `flush_outbox`/`observe_*` helpers; drain bound unchanged.
- `application/operation.py`: optional `observer`; `_finish` retires inside the terminal transaction, adds
  `finalization` to the receipt, emits `operations.operation_finalized` after commit. Collection still runs
  before the terminal transaction; the summary says `observed_after_collection: true`.
- `application/autonomous.py`, `adapters/operation_cli.py`, `cli.py`: observer passed through; message and
  publication events on the autonomous delivery path.
- `domain/observation.py`: two new registry entries (`operations.operation_finalized`,
  `operations.operation_message_parked`).
- `tests/test_operation.py`: the evidence-gate case expects the never-started review decision retired.

## Correction batch (consolidated acceptance review 1)

1. **Terminal replay / identity.** One ordering in `Workflow.submit`/`handle` (assignments, reports, notices):
   authorize; validate the exact message against the existing task `input_hash` / `workflow_inbox` hash
   (existing errors); `park` (which re-checks those bindings via `require_identity` and the parked digest);
   only then return the old task / inbox result or follow the normal path. A previously handled or queued
   message of a terminal operation is therefore parked (old row untouched) and `LocalCycle` can ACK it; a
   changed body under the same id raises the existing `ContractError` / `ParkedMessageConflict` and writes
   nothing, and the original replay still parks afterwards. `LocalCycle._park` turns a `ContractError` from
   the workflow into the existing refusal (no ACK, stop `foreign_correlation`, refusal type in the receipt).
2. **Protected effects / evidence.** `retire` reads `observation_terminations` once and reports any row with an
   `unconfirmed` or `pending_reconciliation` record of any attempt (same bucket/task) as unresolved before
   touching row or fence. Retired rows keep `error`, `failure` and `attempt_outcomes` untouched; retirement
   metadata is the separate `retirement` field (no `error=operation_terminal`, no invented cancelled
   attempt). The `... or True` assertion was removed. Contract text updated accordingly.
3. **Integration tests exercise the real contracts.** One `late()` message object per test (deepcopies for
   replays). `_race` runs two real PostgreSQL transactions that overlap on the store's advisory lock with
   events (`GatedStore` holds the finish transaction, or the claim / submit transaction, open while the
   other side has started and blocks; timed `join` asserts the block), parametrized for both orderings of
   claim-vs-finish and submit-vs-finish, plus restart replay and the conflicting body. Real Redis
   commit-before-ACK: injected ACK failure, PEL inspected, test-owned `XCLAIM ... IDLE 120000` makes the
   pending entry eligible for the unchanged reclaim policy, the same disposition is returned without an
   executor call, and the observation order (parked before acknowledged, no acknowledged after the fault)
   is checked. Rollback before the terminal / disposition commit is covered on MemoryStore and PostgreSQL
   (no status, disposition, fence or `operations.operation_finalized` event).

## Final identity-guard correction (SPEC "Remaining identity guard")

- `require_identity` now reads the `tasks` binding by `message_id` for every incoming type (before: only
  `task.assign`); the hash comparison, inbox check and parking checks are unchanged. A differently typed
  message reusing a task id is refused with the existing `Conflicting task identity` error and no parked
  digest is written under that id.
- One regression in `tests/test_operation_finalization.py`
  (`test_a_differently_typed_message_reusing_the_task_id_is_refused_and_the_assignment_still_parks`):
  accepted operation, genuine `task.result` copied with the assignment's id, `handle` refuses, no
  disposition, task row untouched; the unchanged assignment replay then parks and the poisoned copy is
  still refused afterwards. Verification: the two commands below, rerun on this correction.

## Verification actually run (correction batch, this worker)

```
python -m pytest tests/test_operation_finalization.py tests/test_operation.py tests/test_local_cycle.py tests/test_observation_wiring.py tests/test_workflow.py tests/test_autonomous.py -q -p no:cacheprovider
python -m ruff check .
```

Result: 150 passed, 17 skipped; ruff clean. The 17 skips are the `isolated_pgstore` / `HARNESS_INTEGRATION`
cases, including the six PostgreSQL/Redis cases of this file (claim-vs-finish x2, submit-vs-finish x2, PG
rollback, real Redis ACK gap): written, not executed here (no services in this worker). The owner runs them
with real PG+Redis. Full suite and CI were not run by this worker. No git commands or model calls were run.

## Limitations

- Concurrency cases rely on the existing single advisory-lock transaction ordering; no new lock was added.
- Unsent outbox messages of a terminal operation are not rewritten; they are parked when a consumer receives them.
- The redis-py `xclaim(..., idle=)` keyword in the Redis test follows the library's documented signature; it
  could not be executed in this worker (no ad-hoc Python or services allowed), so the owner's real run is the
  first execution of that call.
