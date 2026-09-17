# Allow ordinary dot-prefixed project paths in operation manifests

2026-09-18 KST. Baseline fcff08fa95459fabf48b42d137b850dd3a856cb5.
Codex owns analysis/design/acceptance; Claude implements through the isolated Zeus
worker and supplies evidence; Codex independently reviews and integrates. User approved
fixing the path restriction after the real pre-provider refusal in ct-remote-ready-001
(Zeus issue131). Existing dirty main work and application repositories stay unchanged.

## Outcome, decisions and evidence

Allow owner-selected repository paths such as .github/workflows/ci.yml, .gitignore,
.config/settings.json and docs/.github/GOAL.md. Keep traversal, absolute/backslash,
unsafe character and Git metadata rejection. This changes manifest grammar, not GitHub
authentication, global permissions, provider tool grants or filesystem containment.
Do not present the manifest validator as protection against symlinks or hostile code.

Observed: domain.operation.SEGMENT starts with alphanumeric; safe_relative_path refuses
.github before a call. It feeds operation goal and allowed_paths, autonomous scope,
DGE source paths and shared validate_plan. isolated_worker.check_relative_path already
accepts ordinary dot paths, rejects .git case-insensitively, trailing dot/space and
Windows special names; tree bounds/import refuse symlinks, hardlinks and collisions.
No adapter rewrite is required. Existing non-hidden Windows reserved names remain the
adapter's restriction; this batch does not claim a complete portable filesystem grammar.

Primary docs opened 2026-09-18:
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
  requires workflow YAML under .github/workflows; supports treating .github as normal
  project content, not permission to publish or deploy it.
- https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
  documents case assumptions and warns against trailing period/space in file names;
  justifies rejecting dot-prefixed aliases rather than merely excluding literal .git.
Local code and issue131 supply the actual refusal evidence, not an upstream defect.

## Complete affected path and one implementation batch

Host manifest -> strict shared path grammar -> pinned goal blob/hash -> PG reservation
and Redis assignment -> existing isolated staging -> Claude allowed task -> candidate
import/evidence replay -> independent lead -> owner acceptance. No new owner or state.
Dot paths are explicit owner input; no auto-discovery/read of home credentials.

Claude allowed changes ONLY:
- src/codex_harness/domain/operation.py
- tests/test_operation_paths.py (new focused regressions)
- docs/contracts.md (INV-OPERATION-001 path grammar paragraph only)
- docs/zeus/operations/operation-dotpaths-001/IMPLEMENTATION.md

Implement one optional leading dot before an alphanumeric start in each path segment.
Preserve the existing ASCII character set after that start and total path cap1024;
segment length cap255 includes the optional dot. Reject empty segments, . and ..,
repeated leading dots, .git case-insensitively at ANY depth, slash roots, drives/UNC,
backslashes, whitespace, colon/ADS, control characters and non-string values.
Reject trailing periods on dot-prefixed segments (including .git. and .GIT..).
Keep existing non-hidden accepted grammar unchanged; no unrelated tightening/migration.
Use the single existing helper for callers, no separate allowlist of .github names.

Tests must cover direct helper boundaries (255/256 segments, 1024/1025 whole paths,
valid hidden/nested names and ordinary prior values), actual validate_manifest goal
and allowed_paths, validate_plan shared contract, and DGE/autonomous consumer seams.
Use existing fixtures where suitable and label fixture state-machine checks accurately.
Exercise real temporary Git/staging for .github and .gitignore through existing
isolated helpers where practical; no model starts in tests and no writes to real .git.
Demonstrate newly accepted paths fail on baseline by running the applicable regression
subset with baseline domain module in an isolated temporary copy; negative controls
may already pass and must not be described as newly fixed. No production network calls.

Worker verification: python -m pytest tests/test_operation_paths.py tests/test_operation.py
tests/test_operation_cli.py tests/test_dge.py tests/test_autonomous.py -q -p no:cacheprovider;
python -m ruff check . . Owner/CI owns full suite. Do not run git or extra lint commands,
install packages, start services/models, alter existing accepted runtime/profile or
write outside assigned paths. Legacy tests lists exact successful commands; diagnostics,
results and unrun work belong in summary. Reviewer reads the supplied isolated evidence
and scoped diff; no candidate execution on host or checkout writes.

## Fixed acceptance matrix and completion

| Boundary | Acceptance |
|---|---|
| Normal | .github workflow, .gitignore, nested hidden goal/plan/source paths accepted unchanged |
| Negative | Metadata case variants/aliases, traversal, absolute/ADS/backslash/wrong types refused |
| Limits | Optional dot included in255 segment budget;1024 path cap unchanged |
| Shared callers | Operation, DGE and autonomous consumers use same result; existing suites pass |
| Filesystem | Existing staging/import guards unchanged; actual benign dot-file task imports expected bytes |
| Failure/unknown | Refusal remains before call; no fallback or alias normalization |
| Timeout/restart/concurrency | No ownership changes; reuse accepted isolated-runtime evidence, no new stress loop |
| Platform | Focused Windows checks + Linux isolated tests + final Windows/Linux/integration CI |
| Logging/cleanup | Real worker/replay/lead receipts, profile/live hooks and zero owned leftovers; preserve failures |

Completion: accepted Claude implementation, owner scoped checks, rebuilt pinned image,
one actual small container task with a .github goal and .github/.gitignore allowed paths,
isolated fixed-file checks and independent acceptance WITHOUT owner file-copy workaround,
then final CI, PR merge and issue closure. Canary is a synthetic filesystem task, not
GitHub deployment or whole-product acceptance. Do not expand into unrelated CI/product work.

Machine ledger118 ->122 maximum: implementation/lead pair then canary/lead pair.
Implementation900s/declared USD4; canary600s/USD2; lead300s. No automatic retry/reset.
Preserve refusals and revise this SAME frame only for a material obstacle. Stop once
the fixed matrix passes; do not reopen already accepted runtime boundaries.

## Canary checkout-byte assumption: one corrected fixture

Actual first canary4b93d2f directly changed only the two assigned dot paths; both target
checks passed. Gate refused before lead because unchanged .github/KEEP.md was CRLF in
the host checkout copied into replay, while the fixed byte oracle requires LF. The
worker-stage check had passed. Git blob and scope are unchanged; the owner's fixture
omitted a checkout line-ending contract. Original c receipt/inspection is preserved,
not relabelled accepted. Ledger121; implementation acceptance remains intact.

One discriminating check is the preserved replay assertion b'unchanged\r\n' versus
b'unchanged\n', together with identical untouched Git blob. Add only .gitattributes
with '* text eol=lf' to the SAME original canary baseline. Tests, goal, task bytes and
allowed paths are unchanged; no newline normalization/relaxation of the oracle and no
global Git or runtime change. A fresh c2 operation uses the same tested image/runtime
code. One explicit replacement worker/lead pair, ceiling123 from121 (five total calls
instead of four). This is an owner fixture correction, not automatic retry or a fix to
the accepted path helper. No further expansion if the corrected fixture fails.

## Final local acceptance

Implementation and actual direct-dot-path canary accepted; owner baseline contrast,
Windows checks and exact candidate bytes passed. No owner-copy workaround. RESULT.md
and EVIDENCE.json preserve the complete batch and limits. The operation objective assigned
baseline reversion to the owner (not the worker). Final CI/merge/closure are the remaining
delivery gates; no new model calls or exploratory review are needed.
