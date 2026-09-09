No writes or execution. Read the final `execution_budget.py`, `workflow.py:69-136`, `executor.py:435-497`, `tests/test_retry_state.py`, `test_threshold_reviews.py:147-155`, `root-design.md`.

## All five findings are closed

Pinning now sits inside the `else` branch after deadline, terminal-dependency and unsatisfied-dependency checks (`workflow.py:118-125`), and `test_dependency_wait_does_not_pin_a_budget` asserts the waiting row has no `retry_budget` and that the budget binds to the *later* claimer's value. Malformed stored deadline (`:104-108`) and malformed persisted budget (`:119-123`) each block one row with a deduplicated `execution.state_blocked` event while a sibling task is still claimed — parametrised over four corruption shapes including `max_attempts: True`, which `positive_integer`'s `type(value) is int` correctly rejects. Legacy attempted rows are blocked as `UnverifiedLegacyRetryBudget` and, per `test_legacy_attempt_does_not_invent_its_original_budget`, `max_attempts=99` neither pins nor claims. Decisions take the identical path (`executor.py:479-485`). The artifact put now sits under the `tx.get(... ) is None` guard (`executor.py:443-445`), and the replay test monkeypatches `artifacts.put` to fail outright plus asserts `tx.records()` unchanged — that closes the "read-only in PG, not overall" gap properly. The threshold fixture comment states the pin is modelled, not guessed. root-design.md now says the recovery/migration procedure is required and *not* implemented here.

## Concrete blockers

None that block this kernel. Two things to carry into the recovery work, both consequences of the design rather than defects in it:

1. **Deployment halts in-flight retries.** Every existing row with `attempt > 0` and no pin becomes `blocked` on first claim after upgrade. That is the deliberate choice over guessing, and the doc says so, but it means the versioned recovery procedure is a prerequisite for deploying this — not a follow-up. Worth stating in that sequencing form.
2. **`block_execution` overwrites `error`** (`execution_budget.py:61`), so the prior failure reason survives only in `attempt_outcomes`. Recovery tooling should read the outcome list, not `row["error"]`, when reconstructing why a blocked row stopped.

`budget["version"]` is still always 1; that is now correctly framed as the hook for versioned recovery rather than dead metadata.

I did not run the suite, so the added tests' pass status is your report.