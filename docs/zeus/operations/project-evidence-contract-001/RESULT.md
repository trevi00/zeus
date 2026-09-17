# Project execution/evidence contract — owner result

2026-09-17. PR #123. Runtime candidate `c7e9fd07dfa9e90100433390256ca863894b837a`.

## Outcome and authority

The host now names required checks and their project execution contexts. Claude receives
the matching interpreter, working directory, source path and narrowly scoped command
permissions. Structured worker observations are independently replayed; missing checks,
reported failures, context drift and aggregate timeout cannot become successful evidence.
The existing evidence gate and owner merge/promotion authority remain intact. Legacy
operations without a project profile retain their previous contract.

The actual Code Tutor canary completed: Claude implementation, host replay and independent
Codex review all succeeded. Owner accepted its documentation-only candidate `dd83cb9` by
fast-forward into the local Code Tutor repository. No product code or prior acceptance
record changed. No remote Code Tutor publication, deployment or ontology promotion occurred.

## Actual operations

Raw root: `D:\workspaces\zeus\artifacts\project-evidence-contract-001`.
The adjacent manifest binds selected receipts and evidence by SHA-256. Raw artifacts are
local; their hashes do not make them available on another computer.

| Run directory | Model calls | Outcome |
| --- | ---: | --- |
| bootstrap | 0 | Redis endpoint was stale; pre-provider failure preserved |
| bootstrap-002 | 0 | Shared schema contained foreign outbox correlation; stopped, preserved |
| bootstrap-003 | 2 | Candidate `784e6f9` rejected by independent reviewer; R1–R3 consolidated in SPEC |
| correction-001 | 2 | Runtime `dabb976` accepted by independent reviewer |
| integration-repair-001 | 2 | Import-only repair `c7e9fd0` accepted by independent reviewer |
| live-001 | 2 | Code Tutor candidate `dd83cb9` accepted by independent reviewer |

Each later operation used a fresh PostgreSQL schema and Redis namespace. Eight model
calls consumed the explicitly recorded machine ceiling, from 80 to 88; no further call
or retry is authorized by this result. Per-operation settled slots, rather than overlapping
before/after global snapshots, identify each operation's two calls.

Live operation `codetutor-project-replay-001` ran from 06:02:26 to 06:05:44 UTC.
Its profile digest is `31396902183a0c0c4cf165cd1a60b0ea20f9dce7fb39b54b4275b3df7daf8983`.
Inspection `9c1d3465bf902f192f7e8410be63239fcd9703398f1c4c1c3d6062dc9161b1c0`
reported `all_checked`, 1/1 required check. Decision
`00ba366a-a1c8-4225-a734-c233593b0a0d` accepted it.

The worker ran `backend-execution-unit`: 47 passed, 22 deprecation warnings, exit 0.
Host replay and the independent reviewer ran the same named check against their candidate
contexts. The reviewer independently observed 47 passed and a clean checkout. These are
unit tests with fixtures, not new browser, database, Docker or human product acceptance.
The earlier product evidence in Code Tutor's RESULT.md remains separate.

Actual worker hook receipts recorded one SessionStart and one PostToolUse, with zero
unreadable records. The initial command augmented with an exit-printing suffix was denied;
the delivered verbatim command then ran. A worker git-status attempt was also denied.
These observations establish this run's delivery and execution, not universal permission
matching or full policy compliance. Owner/reviewer cleanliness checks supplied the missing
worker cleanliness observation.

## Validation and preserved failures

- Initial runtime `784e6f9`: owner Windows PostgreSQL/Redis full suite **2251 passed,
  22 skipped**, disposable Docker **44 passed**, Ruff passed. The disposable stack was
  removed. This is initial-runtime evidence, not a claim of final-runtime integration.
- Corrected runtime: independent reviewer ran 22 focused cases, lint, synthetic aggregate
  deadline checks and actual Git-shell commands preserving exits 0 and 1; accepted R1–R3.
- Owner's first final `uv run pytest` failed collection because new sibling test imports
  used `tests.*` while this directory is not a package. `python -m pytest` had masked it.
  The import-only correction follows existing repository convention; the failed log remains.
- Final runtime `c7e9fd0`: owner `uv run ruff check .` passed; exact `uv run pytest -q
  -p no:cacheprovider` completed **1846 passed, 444 skipped in 501.70 seconds**. This run
  did not enable integration fixtures; the real-service checks belong to CI. Git's `usr/bin`
  was added to this process's PATH so the new real-shell delivery regression ran on Windows.
- Final GitHub CI is required on the final PR head; its result is recorded in the PR and
  merge record rather than predicted here.

The actual live canary resolves the corrected runtime review's explicit remaining question
about Claude command delivery. A separate owner Git-shell preflight also ran the check:
47 passed. The first preflight could not locate `sh` on PowerShell PATH and did not execute;
the second used the verified Git installation path. No global PATH change was made.

## Limits and remaining work

Profile v1 supports host-declared Python pytest and Ruff checks only. It does not provision
dependencies. Interpreter bytes and dependency-file digests bind declared inputs; they do
not prove all installed dependency bytes immutable. This run exercised Windows/Git sh;
Linux CI tests are not a live Linux Claude-provider operation.

No additional autonomous debate/council run or PostgreSQL ontology promotion is claimed.
The exact criterion enum regression covers the producer/consumer mismatch in this scope.
The legacy no-profile replay timeout implementation is unchanged. Product human/device
acceptance, AI behavior and deployment remain separate work. Broad issues #1 and #20 are
not closed by this bounded delivery. Failed and rejected runtime records remain unchanged.
