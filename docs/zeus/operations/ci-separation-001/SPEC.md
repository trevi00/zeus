# CI separation: same coverage, less duplicate work

2026-09-16. User authorized the agreed CI step. Codex analyzes/designs/reviews; actual Zeus Claude implements. Base17e9291. This resolves the operating efficiency residual; no runtime provider, replay environment or corrupt-record fixes here.

## Facts and design

validation.yml currently triggers unrestricted push and pull_request, each four OS/Python jobs plus one integration job. PR110 head d783cf8 ran duplicate35093122050/35093126192, both attempt1. Main branch protection API says Branch not protected and rulesets is empty; do NOT alter repository policy in this task. A final workflow gate is not a claim that GitHub administratively requires it.

Official sources checked 2026-09-16: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax (multiple events yield separate runs; branches/concurrency/job conditions); https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs (skipped required workflows can remain Pending). Keep the workflow always triggered for supported events, condition jobs instead. No third-party changed-path action/API truncation.

## Fixed implementation

Allowed files ONLY .github/workflows/validation.yml, scripts/ci_scope.py, tests/test_ci_scope.py, docs/zeus/operations/ci-separation-001/OPERATIONS.md. No dependencies, runtime code, broad lint exclusions, branch-protection edits or renamed existing matrix jobs.

1. Trigger pull_request (all current default activity types), push branches:[main], workflow_dispatch (manual full). Same-PR outdated runs cancel through concurrency; use event/ref-or-PR-specific group. Main runs never cancel each other, include run_id in main group. contents:read retained; do not use pull_request_target.
2. An always-running `changes` job checks out full history and uses trusted event JSON fields (read GITHUB_EVENT_PATH from Python, not shell interpolated PR title/branch content) to select range. For PR use merge-base(base.sha,head.sha)..head.sha; for main push before..after; validate SHAs, get objects via existing full checkout, use git argv without shell. Missing/zero/invalid base, unknown/manual event, git errors, empty/ambiguous diff -> full (or failing classifier; gate must fail). Never docs success from uncertainty. Print decision and reason; write mode=docs/full via GITHUB_OUTPUT, changed path count and summary via GITHUB_STEP_SUMMARY. Do not use truncated GitHub changed-file lists.
3. Narrow allowlist: only regular Markdown file changes strictly under docs/zeus/operations/ qualify for docs, all other paths full. Check rename old AND new paths (git --no-renames diff is acceptable), file mode/symlink changes go full, deleted allowed docs can use their old mode. Parse NUL-delimited Git data so whitespace/newlines in paths do not split records. Do not treat all docs/ or all .md as safe: contracts, research data, JSON, schemas, scripts, workflows and unknown paths remain full. Current source search found no executable consumer of this operations Markdown (one test docstring SPEC reference only). This is a conservative scope rule, not general dependency analysis.
4. `docs` job runs only mode docs, performs lightweight stdlib check on changed existing allowlisted Markdown (UTF-8 decoding, no NUL, regular file; removed Markdown is explicit). No uv sync, pytest full, Docker. Reuse script subcommand to read event/range again and refuse if mode not docs. A new docs-only PR should run changes/docs/gate and skip all four matrix jobs and integration.
5. Existing `test` and `integration` jobs run only mode full, depending on changes; preserve all commands, OS/Python matrix, fail-fast false, packaging/smoke checks, Docker cleanup always. No splitting test selection yet. A code-containing PR stays full even when its latest commit changes only docs.
6. Final `gate` job named `CI gate`, if always(), needs changes/docs/test/integration. Explicitly validate needs JSON: changes success; mode docs requires docs success and test/integration skipped; mode full requires test+integration success and docs skipped. Unknown/missing mode, failure/cancelled/skipped required jobs -> fail. Use stdlib Python helper in ci_scope.py with needs JSON passed via env, not raw shell interpolation. Ensure checkout/setup works even after dependencies fail; no continue-on-error or silent default success. Gate should emit mode and evaluated results.

Use Python installed by setup-python for changes/docs/gate, no new package dependencies. Scripts/cli tests may load module with importlib. Focused worker checks: python -m pytest tests/test_ci_scope.py -q; python -m ruff check . . Do not run entire suite in model session; owner owns full PG/Redis and actual Actions.

## Acceptance matrix

- Real temp Git histories: docs-only, runtime, mixed, prior-code/latest-docs PR, rename from code into docs, deletion, Unicode/space/newline names, symlink/mode changes. No fake actual Actions claim.
- Full fallback on malformed/missing SHAs/events/unknown paths, missing object/diff failure and empty change list. A failed classifier cannot produce green gate.
- Gate normal docs/full; matrix/integration failed or cancelled; classifier failed; missing output; unexpected skipped required jobs; no type/coercion fallback success.
- YAML trigger/dependency/gate wiring and preserved matrix/commands checked (use existing PyYAML where available; note YAML1.1 on parsing). Doc checker invalid UTF8/NUL/symlink and deletion path. Tool failures visible, no provider/DB calls.
- Windows/Linux tests through existing matrix; real Actions run for implementation PR must be full with only PR event (no branch push duplicate). After merge, owner opens one docs-only evidence follow-up to actually observe lightweight route. Main push remains independent verification. Measure run/job counts and elapsed/job-duration observations, distinguish scheduling variation; do not claim guaranteed speedup or prior CI runtime improvements.

One implementation/review batch, no recursive new optimization. Existing full suite remains required for workflow/script changes. No need to research caches/sharding or third-party actions. Root independently reviews fail-closed routing and preserves failures.

## Execution budget

Prior24 machine slots retained; one real Claude implementation (900s, declared USD5 option, not spending guarantee) plus one Codex review (300s), cumulative cap26. New ci-separation-001 cycle/schema, max2. Budget increases from previous task follow the user's new work authorization; no automatic extension/retry inside this batch. Source/evidence on D, persistent PG/Redis unchanged. A failed batch remains recorded; no fabricated acceptance.
