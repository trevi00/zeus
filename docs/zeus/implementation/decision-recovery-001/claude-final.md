## Review — decision recovery source

Scope: `decision_recovery.py`, `execution_recovery.py`, and the four consumer call sites. Read only; nothing executed.

**The fixes landed as described.** Conductor now reads `release['policy']` from the store instead of re-deriving it, and identity is re-pinned in both branches via `release_id == digest({'candidate', 'policy'})` plus `policy_hash` (`decision_recovery.py:61-74`). Replay in `apply` compares execution *and* related hashes before returning `replayed` (`execution_recovery.py:184-189`, `201-204`). `validate_decision` pins packet hash, `recovery_ref`, sequence `+1` and strictly increasing generation (`:94-105`). `AttributeError/IndexError/RecursionError` map to `ContractError`, and since `ContractError` subclasses `ValueError` the explicit re-raise at `:60` is what keeps genuine contract failures from being masked — correct as written, and load-bearing. Blocked/inspection-blocked paths guard in all three places (`executor.py:555,564`; `audit_execution.py:191,202`). Non-blocked audit success needs no guard: `_eligible` only admits `blocked/failed/expired`, so recovery cannot race a `running` row.

### Remaining blockers

1. **`RecoveryContextChanged` is a terminal dead end** (`executor.py:476` → `block_execution` sets `status='blocked'`, `error='RecoveryContextChanged'`). No `_eligible` operation accepts it: `migrate` demands `UnverifiedLegacyRetryBudget`, `repair` only `{InvalidRetryBudget, InvalidExecutionDeadline}`, `resume` only `failed/expired`. A recovered decision whose context drifts once is permanently unrecoverable, with no operator route back. This is reachable through ordinary drift — e.g. a release acquiring reviews, or `improvement_loops` reaching `stagnated` (`decision_recovery.py:87`) — not only through tampering. Either add a `repair`/`re-recover` route for this error or block to a distinct non-terminal state.

2. **Blocked-outcome paths omit the effect-input pin.** `_commit_decision` verifies `actor`/`phase`/`effect_input == current['input']` for recovered rows (`executor.py:583-586`), but the `inspection_blocked` and `blocked` commits do not. They still write a terminal status and a model-authored `result` onto the row. Same guard should apply.

3. **Validated row is discarded in both blocked paths.** `executor.py:554-557` and `563-566` call `_owned`, validate `current`, then overwrite `current = tx.get(...)` and mutate that. Whether this is benign depends on whether `tx.get` returns the identical object or a fresh copy — if a copy, the object being written was never ownership- or recovery-checked. `audit_execution.py:190-193` does it correctly; make the executor match.

4. **Minor:** the duplicated `receipt['packet'] == packet and digest(...) == result_hash` conjunct in both replay blocks (`:184` then `:187`, `:201` then `:203`) is dead weight and reads as a merge artifact.

(1) and (2) are worth fixing before the CLI-process work; (3) needs a look at the store's `get` semantics.