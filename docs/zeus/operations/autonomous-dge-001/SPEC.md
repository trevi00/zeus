# Autonomous research, DGE and verified promotion

Owner: Codex. Implementer: actual Zeus Claude worker. Date: 2026-09-17.
Base inspected: c0d18c6875509c631e407df35637a412d4a0f755.

## Outcome and fixed boundary

One command takes a pinned goal and authorized implementation scope through SSOT research,
an immutable meeting packet, independent proposer/attacker/arbiter executions, existing Claude
implementation and Codex verification, then explicit transactional knowledge promotion. The owner
will run one real small documentation improvement through this complete path. Fixtures do not count
as the real canary. No automatic merge, release, ticket closure, unlimited rework, recursive research,
product acceptance or claim of full local-asset absorption. The user authorizes this construction.

Research and design belong to Codex; implementation belongs to Claude. Review and synthesis do not
authenticate semantic truth: record exactly the execution, scope and evidence supporting a claim.

## SSOT research and decisions already made

- Reuse application/dge.py and domain/dge.py for packet validation, fixed plan binding, debate
  order, carried findings and deadline. Existing inputs are operator attestations, not real roles.
- Reuse Executor.execute_one, its leases, _run, execution artifacts, checkpoints, invocation
  accounting, failure blocking and host provider selection. Add one dedicated action `dge_role`.
  Do not invoke provider CLIs from a new script or call _run without the claimed task lease.
- Reuse Workflow, six-W envelope, durable outbox, RedisBus receive/handle/ACK. Existing action
  `research` is feed discovery, not SSOT research. Existing `plan` automatically assigns a worker,
  so neither is the new pre-implementation role action.
- Reuse GitWorkspace.review_workspace at the pinned commit for each design role, assert clean
  HEAD before and after. Distinct task IDs and stages, separate role agents/checkpoints; never
  resume another role's provider session. Add four lead agents under conductor (researcher,
  proposer, attacker, arbiter), using default Codex design routing (Astra). Claude worker routing
  stays unchanged. No tools or arbitrary host commands selected by the model output.
- Reuse Operation.run v2 for implementation/review and its actual evidence inspection gate.
  No conductor review/merge action is executed. Its accepted receipt alone is insufficient for
  promotion: re-read exact succeeded task, review decision/output and inspection bindings.
- Reuse existing knowledge_nodes/knowledge_edges tables. `index_python` and `project_runtime`
  describe code/runtime observations; neither is formal verified knowledge. Keep knowledge=False
  throughout model execution. New promoted namespace must remain visibly distinct.
- Machine CallBudget counts executor starts, while _run may do up to four context handoffs.
  Report those as distinct quantities. New autonomous role executions MUST cap provider entries
  to one per role (no implicit handoff retry); retain existing invocation accounting. The complete
  canary has six executor starts (research + three debate roles + implement + review). Set a fixed
  per-run maximum of six; record actual invocation count independently, never call slots dollars.

Primary sources opened 2026-09-17:
- https://redis.io/docs/latest/commands/xreadgroup/ : group processing requires explicit ACK;
  pending delivery is not proof of completed application processing. Reuse current Redis 7.4
  compatible commands; no new 8.x features. PG deduplication remains necessary.
- https://www.postgresql.org/docs/17/tutorial-transactions.html : transaction writes are atomic.
  Use ONE existing store transaction for promotion receipt plus graph nodes/edges, not independent
  commits. These docs establish mechanism, not application correctness.

Selected Baldrix reference was previously pinned at cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2
(commands/harness-debate.md, agents/harness-critic.md, scripts/lib/debate_convergence.py).
Borrow bounded role separation, NOT its any-credible-failure blocker rule. That is superseded by
the user's critical-only rule below. Selected-source review is not whole-repository absorption.

## Contract and flow

Add `zeus autonomous run --file MANIFEST` and `zeus autonomous status ID`. Domain/application
remain stdlib. Thin CLI wires the existing services. Strict versioned manifest reuses validated
operation goal/plan/budget/claude fields, plus aware absolute deadline and topic/questions/search
scope. Operator supplies the goal, criteria and allowed paths, NOT role answers or a ready-made
debate. Use one fixed round in this version: revise/needs_research/reject stops with residuals;
no implicit second round, automatic repair loop or changed acceptance criteria.

1. Validate input, pinned goal, host identity and budgets. Atomically claim immutable run ID.
   Same terminal request returns cached receipt; changed config or interrupted in-flight owner
   refuses without takeover or more calls. Deadline is not reset by restart. Every transition
   records its expected prior state. Admission remains exclusive under the PG store lock.
2. Assign researcher through conductor -> dedicated lead, Redis and claimed task. Researcher
   reads the pinned source and returns structured sources/claims/questions plus SSOT findings:
   searched paths/symbols, authoritative definition, callers, relevant tests/operating evidence,
   unknowns, reuse/improve/migrate/new decision and rationale. Existing implementations require
   compatibility/transition/rollback/retirement consideration. An unfound symbol is not absence.
   Unresolved consequential user/product choices stop as needs_user; do not repeatedly ask about
   ordinary implementation choices. A packet requires real pinned source bytes, not citations
   invented from a README summary. Host validates source paths, modes and hashes via GitSource.
3. Freeze the researcher output as a packet using existing validator; host can add deterministic
   envelope IDs/deadline/plan/hash, but never author or repair missing role conclusions. Bind
   packet to researcher succeeded task generation/attempt, actual stored execution output and
   basis revision. Missing/mismatched proof stops; operator-submitted sessions cannot satisfy
   this autonomous gate. The packet is then immutable for all debate roles.
4. Execute proposer, attacker, arbiter in that order as fresh independent tasks/sessions, each
   receiving the same packet digest and exact prior outputs. Reuse debate transition rules.
   Bind role answer to the persisted output itself (task/generation/attempt/agent/stage/base,
   output content and execution_ref), not just an existing file or a model-supplied role label.
   Operator dge submit cannot add trusted events to autonomous-owned sessions. Distinct origin
   `executor_bound`; document that provenance is not proof of citation truth.
5. Attacker must identify only material blockers: concrete reachable trigger, cited packet/source
   evidence, affected fixed criterion, material impact (data loss, unauthorized authority/effects,
   unbounded cost/execution, failed core outcome), minimal mitigation or migration path. Styling,
   optional refactoring and unsupported hypotheticals are minor backlog items, never blockers.
   Arbiter judges materiality independently and may explicitly resolve/refute an unsupported
   critical allegation with cited reasoning. Do not silently discard findings or carry blockers
   by omission. Minor findings must not prevent accept. Stop on actual unresolved critical risk.
6. Approved exact plan launches existing Operation v2 and actual Claude implementer/Codex reviewer.
   Autonomous run requires this authenticated design; legacy operate v1/v2 remains explicitly
   manual/maintenance only, never a fallback for autonomous failure. Document migration: callers
   seeking unattended work move to autonomous; historical operator receipts stay historical.
7. Only after accepted independent review and all_checked actual inspection, promote a bounded
   typed graph in a `verified:<run>` namespace: goal, research, design, candidate and verification
   nodes with derived_from/implements/verified_by edges and immutable refs. This is VERIFIED
   EXECUTION/REVIEW PROVENANCE with explicit verification scope, not universal truth of prose,
   not merged/deployed code. No arbitrary model-proposed knowledge is auto-approved. Validate
   exact current records and actual artifact answer bindings before same-tx promotion. A rollback
   writes neither graph nor receipt; identical retry is idempotent, conflicting content refused.
   Add a small graph-write transaction port on Memory/Postgres transactions or injected adapter,
   keeping SQL out of application. Do not let raw project_runtime erase promoted namespace.
8. Return safe read-only status: state, execution IDs, source/debate/plan/candidate/inspection and
   promotion digests, stage durations, reserved/settled starts, invocation counts, critical/minor
   residuals, promotion state. General/development/operations logs reuse Observer, with bounded
   failure codes and no raw exceptions/credentials. Unknown, failed settlement, provider boundary
   failure, deadline or interrupted owner stops further dispatch and promotion.

No full rewrite of LocalCycle: role dispatch may factor/reuse its delivery semantics into a bounded
helper, but preserve existing worker/reviewer behavior and authorization. No manually inserted
role outputs or success rows in the actual pilot. Deterministic fixtures/fault injection in tests
must be labelled and do not count as independent model debate.

## Fixed acceptance matrix

| Boundary | Required evidence |
|---|---|
| Normal | Actual canary: six roles, Redis/PG chain, Claude candidate, independent review, atomic graph |
| SSOT | Existing implementation found -> reasoned reuse/improve/migrate; unknown stays unknown |
| Debate | Immutable packet, exact order and output provenance; critical supported; minor nonblocking |
| Authority | Forged/unrelated/stale/operator-submitted output cannot approve or promote |
| Failure | Rejected review, failed inspection/settlement/graph commit -> no promotion or next provider |
| Deadline/budget | Fixed deadlines, finite starts, role invocation cap, no replenishment/handoff loop |
| Restart/concurrency | Duplicate cached; different config refused; in-flight residue stops; no double dispatch |
| Knowledge | Same-tx rollback, idempotency, exact candidate/review/inspection; raw observations stay separate |
| Platforms | Focused tests plus Windows/Linux CI, actual owner PG; no claim of device/product acceptance |
| Cleanup/logs | Clean read-only role checkouts; evidence retained on D; no secret/raw-exception output |

Owner will run focused actual PostgreSQL checks and full CI. Worker runs meaningful focused tests,
ruff, architecture tests. Do not run full multi-minute suite repeatedly in the worker. Exact executed
commands only in `tests`, outcomes/skips in summary. Independent reviewer checks only critical
acceptance failures and changed boundaries; preserve already accepted predecessor behavior.

## Delivery and budgets

Bootstrap implementation uses existing maintenance operate v1 because the new path does not exist
yet. This is explicitly NOT the autonomous canary. Initial worker+review pair: machine ledger
35 -> ceiling 37, Claude timeout 1200s and declared max USD 8. No automatic retries. Owner may
create one bounded consolidated correction after reading actual results; never silently replenish.
The real six-start canary gets a separate explicit manifest after the implementation is accepted.
No completion claim until that canary and relevant owner/CI checks pass. Residual minor work is
reported with a revisit trigger; no speculative scope expansion or broad environment investigation.

## Incomplete draft continuation (same frame)

Initial worker stopped at provider budget, not an accepted candidate: task
ae1d7bfc-4675-55cd-9149-c203910b2117, error_max_budget_usd, provider estimate USD 8.1429005
(not a billed amount). Draft preserved as 45f6fe2; 1 slot reserved/settled, no reviewer called.
Owner ran its currently written test file: 5 passed, 1 failed (budget refusal wrongly `failed`
instead of `exhausted`). Do not pretend other tests or the real canary ran.

Complete the same delivery, preserving that draft. Consolidated required work:

1. Finish the acceptance-matrix tests, CLI/role/PG tests and documentation. Run focused checks and
   architecture/ruff; do not spend this call on full-suite repetition or unrelated code.
2. Authority: role_binding currently hashes the task result without loading any execution artifact.
   _promote similarly checks verdict rows but not actual persisted reviewer answers. Owner fixture
   completes/promotion succeeds with no execution artifacts at all. This violates the fixed SPEC.
   Add an injected evidence verification port wired to FileArtifacts plus authoritative invocation
   records; verify content hash, actual stored answer, reservation -> task/generation/attempt/stage,
   basis/context/packet and independent role identity. Reuse existing invocation and artifact
   structures. No requirement for a new crypto system or generalized attestation framework.
   Application may use an injected port, not adapter imports. Same artifacts/provenance must be
   revalidated for promotion; accepted row or matching revision alone cannot substitute. A fixture
   must create meaningful evidence (or explicitly inject failure); tests that omit evidence must
   refuse, not certify execution. Missing/corrupt/unrelated artifact and mismatched verdict regressions.
3. Deadline: owner injected fixture advances the clock after the review returns, beyond the fixed
   deadline. Draft still returns accepted and promotes. Propagate the remaining absolute deadline
   into child implementation/review dispatch (without resetting it); check before each provider
   and in promotion transaction. Late success must not authorize promotion. Reuse existing lease/
   invocation timeout policy; do not build another process supervisor.
4. Preserve all stage durations (current implementation replaces them using initial stale row),
   actual provider labels in call ledger (BudgetedExecutor currently labels every task Claude,
   including Codex dge roles), and full invocation counts including implementation/review. These
   are direct reporting corrections, not a new metric system. Budget refusal maps exhausted.

Owner probes live at D:/workspaces/zeus/artifacts/autonomous-dge-001/draft-boundaries.py; they are
labelled injected fixtures, zero actual model calls. Full delivery still includes real six-start
canary. The owner-authorized continuation is ONE further Claude/reviewer pair, machine ledger
36 -> ceiling 38, timeout 1200s, declared Claude max USD 8. No automated retry or hidden reset.

## Independent review: one completion defect

Candidate 6bcb739, actual Codex review 4f340394-7575-4443-b232-fc1380b807ed rejected one P1.
At application/autonomous.py promotion reviewer artifact validation uses manifest base_revision,
but the independent review executes at candidate revision. Configured project skills cause that
binding to be recorded. The reviewer's labelled fixture reproduced accepted review ->
evidence_basis_mismatch after six starts (zero nodes), while the control promoted. Its focused
tests: 56 passed/1 PG skipped, lint/diff passed, checkout clean. Owner independently ran actual
isolated PG chain/5 nodes/4 edges/atomic rollback/concurrent claim and 154 focused PG tests passed.

One bounded correction: validate reviewer evidence against the exact reviewed candidate revision,
keep the implementation bound to its actual execution base, add a regression with the real
executor's project-skill context binding shape. Preserve other accepted boundaries. Run relevant
autonomous + operation tests and ruff; no broad refactor or repeated full suite. Missing separate
test filenames are not themselves blockers: owner actual CLI/schema/PG checks and the real canary
will establish wiring. Do not remove tests or weaken provenance to make it pass.

Owner authorizes this specifically reproduced correction and review, ceiling 38 -> 40, Claude
timeout 600s / declared USD 2. The autonomous canary is still unexecuted and remains required.
