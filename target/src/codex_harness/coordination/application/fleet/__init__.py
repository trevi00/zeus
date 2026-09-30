"""The Fleet control plane (INV-FLEET-001), split by responsibility (DESIGN-s5 §F):
registry, admission, pause, recovery, state and runner. M7 module docstring:

Fleet control plane: registry, enqueue, atomic admission, finalization and the runner (INV-FLEET-001).

Every admission is one existing store transaction (PostgresStore serializes it with the control
advisory lock; MemoryStore with its lock): at most `max_parallel` reserving jobs, one per lane,
no allowed-path conflict within a repository, all dependencies accepted, no pause and no exhausted
machine ledger. Every observed blocking reason of a queued job is persisted in that same
transaction (timestamps move only when the reason changes) and cleared on admission. The claim is
durable as `dispatching` with a fresh owner token before any process exists; only that owner
finalizes. The runner waits on children outside every transaction, never relaunches a
dispatching/unknown job after a restart, never retries or merges. The only ceiling change is the
explicit operator `authorize_budget` (compare-and-swap, idle fleet only, immutable grant record);
the dispatcher and the model never invoke it. Execution itself is the existing `zeus operate run`
in a lane environment, behind a launcher port.
"""
