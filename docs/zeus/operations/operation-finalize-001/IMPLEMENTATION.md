# operation-finalize-001 — implementation note

Worker: Claude (isolated Zeus worker), 2026-09-18. Base `0a061c4b`. Contract: INV-OPERATION-FINALIZATION-001 in `docs/contracts.md`.

## Change

- `application/operation_finalization.py` (new): exact ownership (`owner`, `terminal_owner`), same-transaction
  `retire` (dispositions, cancelled rows, fence advance, unresolved summary) and `park` (idempotent
  `operation_message_dispositions`, conflict refusal, parked receipt).
- `application/workflow.py`: `submit` and `handle` (reports and execution notices) park terminal-operation
  messages in the transaction that would queue work; conductor recipients and handled messages bypass.
- `application/local_cycle.py`: optional `observer`; foreign messages are ACKed only after a durable parked
  receipt, otherwise the existing refusal; shared `flush_outbox`/`observe_*` helpers; drain bound unchanged.
- `application/operation.py`: optional `observer`; `_finish` retires inside the terminal transaction, adds
  `finalization` to the receipt, emits `operations.operation_finalized` after commit. Collection still runs
  before the terminal transaction; the summary says `observed_after_collection: true`.
- `application/autonomous.py`, `adapters/operation_cli.py`, `cli.py`: observer passed through; message and
  publication events on the autonomous delivery path.
- `domain/observation.py`: two new registry entries (`operations.operation_finalized`,
  `operations.operation_message_parked`).
- `tests/test_operation.py`: the evidence-gate case now expects the never-started review decision retired
  (cancelled with retirement metadata) instead of left pending.

## Verification actually run

```
python -m pytest tests/test_operation_finalization.py tests/test_operation.py tests/test_local_cycle.py tests/test_observation_wiring.py tests/test_workflow.py tests/test_autonomous.py -q -p no:cacheprovider
python -m ruff check .
```

Result: 140 passed, 13 skipped; ruff clean. Skips are the integration cases (`isolated_pgstore`, `HARNESS_INTEGRATION`),
including the two new ones: PG claim-vs-finish / submit-vs-finish / restart and the real Redis commit-before-ACK gap
with an injected ACK failure. Those two were written but not executed here (no services in this worker); the owner runs
them with real PG+Redis. Full suite and CI were not run by this worker.

## Limitations

- Concurrency cases rely on the existing single advisory-lock transaction ordering; no new lock was added.
- Unsent outbox messages of a terminal operation are not rewritten; they are parked when a consumer receives them.
- `LocalCycle` ACKs a foreign message only on a fresh parked receipt; a foreign message whose inbox result predates
  finalization keeps the existing refusal (operator-owned).
