## Review: pending decision recovery

Read: `decision_recovery.py`, `execution_recovery.py`, `executor.py:458-640`, `research.py:292-310`, `threshold_reviews.py:53-117`, `releases.py`, `tests/test_decision_recovery.py`. No writes.

### Concrete bugs

**1. `review_conductor` release identity is recomputed, not read — compat break.** `decision_recovery.py:59-62` derives `policy = release_review_policy(candidate)` and requires `data['release_id'] == digest({'candidate','policy'})`. `Releases.propose` (`releases.py:53`) accepts *any* policy dict, and its only content guard is `bool(policy.get("checks"))`. Any `review_conductor` decision whose release was proposed with a different policy (audit-lifecycle candidates, any pre-helper release, any future policy field) can never be recovered — `prepare` fails, permanently. Safer: read `release = tx.get('releases', data['release_id'])` and bind `release['policy_hash']`, using `release_review_policy` only as the *proposal* input in `executor.py:609`.

**2. Whole-record binding on the review path (asymmetry with `diagnose`).** Line 81 returns the full `source`, `inbox`, `release`, `hook`, `loop` rows, so `result_related_hash` breaks on any benign field change (a `loop['reworks']` bump from a sibling rejection, a `release['checks']` write, ticket/archival edits on the succeeded source row) → `RecoveryContextChanged` and permanent `block_execution` at `executor.py:476`. Line 31 already does the right thing for `diagnose` by projecting `('id','agent','input_hash')`. Project the review path too: `source` → id/status/result/actor, `release` → id/policy_hash/status/reviewer set, `loop` → status only. This is the highest-yield fix; it is over-restriction, not under-restriction, but it converts recoveries into dead rows.

**3. `apply()` replay computes `_related` before the hash comparison** (`execution_recovery.py:171-174`, `186-188`). Once the recovered decision has committed its native effect, `context` raises the domain error ("Diagnosis occurrence already recorded", "Audit review already recorded", "Release already queued") instead of the intended `Stale recovery retry after execution changed`. An operator retrying a lost `apply()` response gets a misleading message about the *decision*, not the recovery. Compare `digest(current) == receipt['result_hash']` first, then `_related`.

**4. `blocked` / `inspection_blocked` commits skip `validate_decision`** (`executor.py:553-566`). A recovered decision whose context changed after claim can still write a terminal result. No release/incident effects, so impact is low, but it silently consumes the recovery.

**5. `_related` exception net is narrow** (`:61`): `AttributeError`, `IndexError`, `RecursionError` escape. Inside `decide_one`'s claim transaction the only handler is `except ContractError` (`:474`), so a malformed stored row aborts the *entire* claim loop for all agents rather than blocking one row. Add `Exception`-minus-`ContractError`, or at least `AttributeError`/`IndexError`.

**6. Receipt is not bound to the current recovery generation.** `validate_decision:87-92` checks bucket/task_id/related hash only. Also assert `row['retry_budget'].get('recovery_ref') == row['recovery_receipt']` and `receipt['packet']['bucket'] == 'decisions_pending'` consistency, so a stale/hand-edited `recovery_receipt` pointer can't be honored.

### Correct as designed

Guard placement is right: claim (`executor.py:473`), native commit (`:580`, `research.py:298`, `threshold_reviews.py:57` — reached from both `prepare` and `complete`'s write tx), always *before* the effect, never a global `_owned` recheck, so own writes aren't rejected. Threshold restore (`:213-218`) correctly rehashes `restored`, so restored requests validate. `research_lead`/`proposal` deferral (`:19`) is unreachable-by-construction. Phase coverage is complete against all seven producers; `:46` fails closed on unknown phases.

### Tests

- `test_review_recovery_...` asserts only `pytest.raises(ContractError)` on the second commit; that error almost certainly comes from `workflow._owned` (row now `succeeded`), not the recovery guard — the test doesn't demonstrate what its name claims. Match on the message.
- No coverage for: bug 1's policy divergence, `apply()` replay after related change, hook-binding change, `release_queue` already queued, and — notably — **no regression test that pre-existing `threshold_review` recovery still validates through the new `_related` route**.
- `exhaust()`/`lease()` fabricate budgets and leases directly, so exhaustion and lease semantics are never exercised end-to-end.
- The `system` fixture parametrizes memory/postgres; verify `isolated_pgstore` skips rather than errors when no PG is present.