Read all three. Confirming the correction and the guard.

## The missed branch — your finding stands

`fail()` `workflow.py:307-315` returns `current` on receipt hit having checked only `request` equality, `failure_receipt`, `generation`, `attempt`, `status`, `error`, `failure`. It never reaches `_owned`, so `_same_execution` never runs. `request` covers `bucket/task_id/generation/attempt/owner/error/retryable/failure` — so `agent`, `actor`, `recovery_sequence` are unconstrained on that path, exactly the three "accepted" rows in `identity-postgres-baseline.json`. My AC4 write-up asserted fencing is applied in `fail` (`claude-design.md:14`); that is true only of the non-receipt path. The claim was wrong as written.

## Guard adequacy

`_same_execution({**current, 'lease_owner': receipt['request']['owner']}, task)` is correct, and for a reason worth recording: `owner` is inside the digest, so an altered owner misses the receipt entirely and falls through to `_owned`. The substitution therefore does not weaken anything — `receipt['request']['owner']` is provably `task['lease_owner']` once `receipt["request"] == request` holds, so that key compares trivially true and only `id`/`agent`/`actor`/`recovery_sequence` do new work (`generation`/`attempt` are redundant with the existing conjunction, harmless). Digest input unchanged, so archived receipt ids stay valid.

Two conditions for no false rejection: (a) `.get(key, default)` symmetry must hold for buckets where `agent`/`actor` is absent — both sides absent → both `None`, fine; (b) `recovery_sequence` must never move without `generation` moving, which `execution_recovery.py:221-228` satisfies. Put it inside the same `require`, keeping the message `"Stale failure retry after execution changed"`.

## Regression cases I'd require

1. Per field `agent`/`actor`/`recovery_sequence` altered on replay → `ContractError`; row byte-identical, no new `execution_failures` key, no second notice, no appended `attempt_outcome`. Both aggregates, memory + real PG.
2. Type confusion: `recovery_sequence` `0` vs `False` vs `0.0` → rejected (`type(left) is not type(right)`).
3. Absent-key symmetry accepted — the anti-over-rejection case; without it the guard silently breaks idempotency for `tasks` rows with no `actor`.
4. True redelivery: byte-identical dict twice → same row, exactly one receipt, one notice.
5. Altered `owner` → digest miss → `_owned` rejection (documents the two distinct mechanisms).
6. Pre-recovery receipt replayed post-recovery → still rejected.
7. Pinned digest constant for a fixed request, proving the fix changed no receipt id.
8. Child-process matrix: tied `created_at`, shared + nested UTF-8 cwd, one child replays altered identity → sibling rows unchanged.

## Agreed

Per-row containment for `claim()`'s ordering key (`InvalidExecutionOrder`) and `running()`'s missing `status` (`InvalidExecutionState`) — same idiom as the existing poison-row degradation; whole-queue abort is the wrong blast radius. AC5 bounded by an explicit normative contract naming unmeasured OS-step/VM-resume as an unverified condition, no host clock mutation, no claim that offline rollback is always detected.

## My claims to strike

- **Samsung devices**: not in any GH18 criterion. `claude-design.md:83` invented it; delete.
- **Evidence age**: "spanning days" (`:82`) was assumed from run ids. It must be computed from actual `observed_at` values against the 86400 s bound before it drives sequencing.
- **AC7**: forbids substituting exit 0 or self-report for human acceptance. It does not mandate new unrelated device QA.
- **Retrospective / `project_context.cwd`**: fixture-extension preservation state only — document as such; invent no Zeus-side feature to match Baldrix.

Root implements; I've made no edits.