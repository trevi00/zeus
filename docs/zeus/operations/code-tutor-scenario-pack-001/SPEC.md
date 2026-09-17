# Code Tutor project guidance and scenario pack

2026-09-17. Owner Codex; implementation actual Zeus Claude; independent Codex review.
Continuation of PR119 selection. One bounded delivery, not an application rebuild.

## Outcome, scope, completion

Make selected local harness principles usable as a project-local pack through existing
Zeus Git-pinned project context and SDD consumers. Add a Code Tutor learning-loop draft,
human-readable review workflow, and real Git/contract integration checks. Acceptance is
pack delivery/contract compatibility, never product success, model compliance or human
approval. User's original app stays read-only; no application deployment or remote changes.

User authorized continuation and explicitly selected signup/login -> choose a problem
-> submit solution -> result and learning history on 2026-09-17. The selected intent
is confirmed; its detailed GWT and actual execution have not received human acceptance.
Samsung phone/tablet execution remains deferred. No additional approval gate for creating
the draft; do not fabricate completed device or human checks.

## Evidence and whole path

Reference repository trevi00/code-tutor-ai revision
0d48f06dd8860a9e9f731e7af434824779eaadd8, cloned read-only for this task to
D:/workspaces/code-tutor-ai/repo. SOURCE.json pins inspected files and selected Baldrix
source identities; it does not claim whole project review. Observed package declarations:
React 19, TypeScript 5.9, Vite, Lucide, React Query, Zustand; backend FastAPI/PostgreSQL/Redis.
These declarations are not an installed-environment receipt.

Owner inspected frontend/e2e/problem-solve.spec.ts: it drives run/submit and logs a
matching result string, but no expected pass count/status/history assertion follows.
Backend learning/interface/routes.py:208–297 creates submissions, guards get/evaluate
by owner/admin and lists current-user submissions. Static definitions are not executed
authorization or sandbox guarantees. No existing real acceptance is promoted from README.

SSOT: adapters/project_skills.py reads .harness/tech-stack.yaml and .harness/skills from
a Git revision; adapters/skill_routing.py handles score/budget/path identity. Existing
SDD validate_spec/gate_report/render_review own schema, eight stages and review-only
reports. Schema currently requires physical Samsung Android device profiles; retain
those future profiles explicitly pending. Do not weaken schema to call desktop proof
physical proof. Provenance promotion by autonomous run is about this implementation
and reviewer, not about execution of the drafted learning scenarios.

Pack files -> copy to a NEW project root (never overwrite existing .harness) -> commit ->
project_context at exact revision -> skill body/pointer records. Draft spec -> native
SDD validation -> existing view -> human review -> future real app execution. Git owns
definitions; PG may receive verified operation provenance only, not draft acceptance.

## One implementation batch

Only these worker files may change:
- examples/code-tutor-ai/.harness/tech-stack.yaml
- examples/code-tutor-ai/.harness/skills/typescript/react/experience-contract.md
- examples/code-tutor-ai/.harness/skills/typescript/5.x/runtime-contract.md
- examples/code-tutor-ai/.harness/skills/_common/real-acceptance.md
- examples/code-tutor-ai/sdd/learning-loop.spec.json
- examples/code-tutor-ai/README.md
- tests/test_code_tutor_pack.py

1. Canonical profile explicitly separates React framework version 19 and TS language
   version 5.9; include Python backend without pretending FastAPI version is measured.
   No global worker profile changes, no stages clone, no new loader/install CLI.
2. Three concise English skills (<=950 body characters each, UTF-8) with existing flat
   frontmatter name/description/keywords/min_score. Use specific keywords (including
   codetutor, learning, submission) so objective `codetutor learning submission` selects
   all three bodies. Targeted actual consumer tests decide this, not filenames alone.
   Experience: owner/lifetime of server vs draft/pending state; visible loading/empty/
   error/success, semantic tokens, Lucide, keyboard/focus/reduced motion; require actual
   stories and visual tests before claiming design complete.
   Runtime: use project's pinned compiler/config, schema+HTTP status+server ownership
   checks; no node20 moduleResolution recipe, no client role as authorization; cache
   reset/user isolation and canonical result before history success.
   Acceptance: stable requirement/scenario IDs and independently set expected outcomes;
   real service/data/browser core flow, no page.route/MSW/emulator as product evidence;
   run/build/data/reset identity, bounded timeouts, unknown result never success or blind
   resubmission; redact secrets; general/development/operations logs, human approval.
   Rewrite principles; don't copy entire upstream documents/private incident text.
3. Native zeus.sdd.v1 draft, target kind unconfigured, null build/alpha URL, code-tutor-ai
   app_id. Two required Samsung future device profiles with explicit deferred conditions.
   Exactly five active scenario IDs:
   SCN.ct.learning-loop — signup/login -> choose known seeded problem -> submit correct
   solution -> expected ACCEPTED/result counts and own history survive reload.
   SCN.ct.wrong-answer — known wrong solution -> WRONG_ANSWER and no false solved state.
   SCN.ct.ownership — second real account cannot read/evaluate first account submission;
   deny response and unchanged owner record; logout/account switch clears private UI cache.
   SCN.ct.interruption — timeout/network loss/reload cannot become success; reconcile
   known submission identity before any retry, do not duplicate effect blindly.
   SCN.ct.ui-states — loading/empty/error/success are visible/keyboard accessible, focus
   and reduced motion covered; pending UI never canonical approval.
   Requirements cover all five; use critical for ownership/interruption, normal otherwise.
   Each GWT has concrete independent then outcomes and both device profile references.
   bindings=[] for every scenario: selectors were not measured. Do not invent replay.
   Reset contract: isolated disposable dataset/accounts, seed digest and initial DB state
   checked; no deletion of production/shared data, no raw credentials in receipts.
   Design names current React/Tailwind/Lucide facts and proposed semantic tokens/stories;
   do not claim shadcn/Storybook already installed. At least the five visible-state story
   requirements represented (loading, empty, error, success, pending).
4. Korean README: scope/SSOT/provenance links to SOURCE.json/PR119, non-overwrite onboarding
   steps for PowerShell and bash (documented not executed host equivalence), commit before
   consumption, existing `zeus sdd inspect/view` commands, eight-stage completion checklist,
   mock-vs-real denominator, human/device/bindings/target remaining. Do not write executable
   E2E skeletons that appear green or invent deployment/service credentials. Rollback is
   reverting only this pack's committed project files; migrate an existing project profile
   by reviewing its diff, never replace user-authored authority blindly.
5. Meaningful tests using real temporary Git and FileArtifacts, no mocked app/backend:
   native spec validation and all eight stages blocked with execution/acceptance zero;
   actual HTML render contains scenario IDs and no granted release; actual project_context
   selects all three full bodies for the declared objective, hashes bind Git artifacts;
   mutate working-tree skill/profile after commit and prove pinned context unaffected;
   out-of-stack unrelated skill never delivered. Label these contract tests, not E2E.
   Reuse existing helpers/patterns without modifying runtime or existing tests.

## Matrix and acceptance

| Boundary | Required result |
|---|---|
| Normal | 7 allowed files, profile and 3 bodies route; 5 GWT scenarios validate |
| Missing evidence | target/bindings/device/human stay pending; report never PASS/release |
| Failure/unknown | timeout, wrong answer, ownership and cache cross-user covered by desired oracles, not claimed executions |
| Revision/authority | Git-pinned consumer ignores uncommitted changes; unrelated stack excluded |
| Restart/concurrency | runtime unchanged; scenario requires identity reconciliation rather than blind retry |
| Platforms | real Windows owner tests + Windows/Linux CI; shell steps unexecuted until target onboarding |
| Cleanup | temporary Git fixtures only, raw on D; no app stack, credentials or main dirty files touched |

Worker commands: `python -m pytest tests/test_code_tutor_pack.py -q` and
`python -m ruff check .`. Exact commands only in tests output, results in summary.
Owner repeats targeted tests plus existing project/SDD contract lane as appropriate;
CI owns full suites. Independent reviewer uses this fixed matrix, critical concrete
blockers only. Unrelated source/framework defects do not expand the assignment.

## Execution bounds and finish

Shipped autonomous six-stage path: research -> proposer/attacker/arbiter -> Claude ->
independent Codex review. One cycle, max6 executor starts, machine ledger58->ceiling64,
Claude declared USD4/timeout900s; absolute deadline60min. No automatic retry, merge,
deployment or issue closure. On failure preserve evidence and reframe the same task.
Completion: accepted implementation/review, owner checks, final CI, PR merge and results
including actual usage/logs and limits. Full absorption and product acceptance stay open.
