# Goal-bound progress and work admission

2026-09-16. Codex owns analysis/design/acceptance; Claude implements via Zeus. User requires progress to resolve explicit goal residuals, not a chain of interesting tasks, and requires this principle in the harness and self-improvement metrics.

## Outcome and evidence-backed design

At base 9d503d0, Tickets.dispatch already pins ticket revision/hash and performs atomic dispatch/outbox writes. TicketLifecycle.close requires criterion evidence, merged revision and signed authority, and writes ticket_closures plus a hash-linked lifecycle event. LocalCycle/handoff supports bounded execution and read-only continuation. Recent operation-handoff-002 completed real Claude -> replay -> real Codex acceptance, 2/2 awaiting_operator. There is no aggregate goal denominator or goal-bound dispatch today. Sources are the existing application/tickets.py, ticket_lifecycle.py, local_cycle.py and their tests at this base; no external API/new library is introduced.

Use existing ticket authority, not a second completion mechanism. Implement an OPT-IN goal manifest/report and goal-bound ticket dispatch. Existing unbound dispatch stays compatible and is NOT claimed to enforce goal discipline. Goal reports observe durable closure records, not a new signature verification, provider permission, deploy approval, or proof that an arbitrary manifest is the user's complete goal.

## Definition and report

Add application/goal_progress.py with validated manifest, transaction-level evaluation and GoalProgress(store).report(manifest). Strict manifest fields: version=1, id, objective, non_goals (list of strings), criteria (nonempty max 50). Each criterion has exactly id, acceptance (nonempty text), ticket_id, revision (positive int, not bool), content_hash (64 lowercase hex). Reject duplicate criterion IDs and duplicate ticket_id bindings so the same ticket cannot inflate the denominator. Definition hash is domain.model.digest of the entire validated manifest. JSON stays in Git; no new authority DB or migration.

Read all needed records in ONE transaction. For each criterion: missing ticket/revision -> missing; mismatched current revision/hash -> stale; valid matching current open/dispatched ticket -> pending (or reopened if valid history contains a close); closed ticket counts as resolved ONLY if existing verify_chain passes, current last event is closed at matching ticket revision/hash/sequence, packet_ref/proof_ref are nonempty sha256 references, and ticket_closures[packet_ref].event_id matches current lifecycle_event. Validate ticket_revisions content with digest. Invalid/corrupted purported closure -> unverified, never resolved. Do not emit raw record contents/errors. Store connection/read errors propagate (not zero/empty success). Hash chain is not cryptographic signature re-verification; trusted existing close path remains authority.

Report schema urn:zeus:goal-progress:1, authority=observation_only, goal_id, definition_hash, objective, criteria (id/acceptance/ticket binding/status and closure event/packet/proof refs if resolved), metrics={total,resolved,remaining,reopened,missing,stale,unverified,completion_ratio}, where remaining=total-resolved, ratio=resolved/total. Never count tasks, commits, PRs, review votes or test totals as completion. Reports of different definition hashes are not comparable improvement denominators. Add pure compare_reports(before,after): validate schema/hash/goal and criterion identities/bindings, derive resolved sets from criterion statuses (not supplied metrics), return gained IDs, regressed IDs, net_resolved. Label comparison observation_only, not authority; reject changed definition/duplicates/invalid statuses. No persisted snapshot or signing claim.

## Work admission and CLI

Tickets.dispatch accepts optional goal_manifest=None, criterion_id=None, both required together. Validate goal and selected criterion inside its EXISTING transaction before writes; selected ticket id/revision/hash must match dispatch and criterion must be pending/reopened. Missing/stale/unverified/resolved/unmapped selections refuse without outbox/task/dispatch writes. Add goal_binding={id,definition_hash,criterion_id} to plan details and returned dispatch. Goal-bound dispatch id includes this binding plus existing ticket binding so it cannot reuse a prior unbound/different-goal dispatch. Preserve unbound key/output behavior. No new recursive binding validator or downstream global authority claims in this task.

CLI `zeus goal report <manifest-file>` and `zeus goal compare <before-file> <after-file>` emit JSON; no provider/executor/Redis/observer construction. Existing `zeus ticket dispatch ...` gains --goal-manifest and --criterion options. File parsing belongs to CLI, validation to application. Existing goal-bound admission changes only plan dispatch, not autonomous selection, merge/deploy or provider budgets.

## Fixed acceptance matrix and limits

1. Normal pending -> existing valid close -> resolved with exact denominator; repeated report unchanged and no writes.
2. Review vote/remote issue CLOSED/task succeeded without local close does not count. Missing/stale/corrupt closure explicit non-resolved. A real lifecycle close fixture from existing tests demonstrates compatible record shape; fixture signatures are not human/product evidence.
3. Reopen loses completion and reports regression; revision/manifest changes cannot silently reset the comparison denominator.
4. Goal-bound dispatch valid/idempotent; unmapped/resolved/stale rejected before writes; previous unbound dispatch cannot suppress goal binding; different goals stay distinct. Existing ticket tests unchanged in meaning.
5. Invalid/duplicate/empty goal and unknown compare shapes rejected. Store failures propagate. No new timers/background workers/resources: timeout, subprocess cancellation and cleanup are unchanged/out of scope. Transaction behavior tested with existing store fixture; no new cross-process scheduler claims.
6. CLI wires report/compare and dispatch options without provider side effects. Windows/Linux path behavior covered by normal CLI fixtures/CI; real provider operation this host only.

Allowed paths: src/codex_harness/application/goal_progress.py; src/codex_harness/application/tickets.py; src/codex_harness/cli.py; tests/test_goal_progress.py; docs/contracts.md (INV-GOAL-PROGRESS-001); docs/zeus/operations/goal-progress-001/OPERATIONS.md. No lifecycle close authority changes, global policy changes, extra assets, retry/merge automation or runtime daemon. Focused worker commands: python -m pytest tests/test_goal_progress.py tests/test_tickets.py -q; python -m ruff check . . Exact executed commands in tests array; results/skips in summary. Codex owns full PG/Redis suite and CI. Reviewer fixed matrix only, stdout frame, clean checkout; no expanding to unrelated existing defects.

## Bounded execution and completion

One real Claude call (900s, declared USD3 option not spending guarantee) plus one real Codex review (300s). Keep all prior 21 call slots; cumulative cap 23. New schema/cycle goal-progress-001 max_executions=2, persistent PG/Redis retained. No automatic model retry or budget extension. On accepted candidate, owner verifies full suite, records actual read-only report of pinned real tickets (open means zero completion), publishes PR and makes merge judgment. Failure remains recorded and batch stops. This completes the goal-metric/admission residual, not the remaining operator-script automation or whole-asset adoption.
