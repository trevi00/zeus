# Implementation: ordinary dot-prefixed project paths (operation-dotpaths-001)

Worker: Claude, isolated Zeus worker, Linux. Base revision ada758883bf85eb90fd73d69261b35a28577ceb6
(the assignment's `base_revision`; the SPEC names fcff08fa as its analysis baseline). Frame: SPEC.md
in this directory, followed as fixed. Owner/CI keep the full suite, the baseline-reversion evidence
and the actual canary, per the assignment objective.

## Authority searched and disposition

- Authoritative definition: `safe_relative_path` and `SEGMENT` in `src/codex_harness/domain/operation.py`.
- Callers (all reuse the one helper, none changed): `validate_manifest` (goal.path, allowed_paths via
  `validate_plan`), `domain/dge.py` `_sources` and `validate_plan(document["plan"], PacketError)`,
  `domain/autonomous.py` research `search_scope` and the delegated operation manifest.
- Sibling adapter grammar, unchanged: `adapters/isolated_worker.py` `check_relative_path` (already accepted
  ordinary dot paths, refuses `.git` case-insensitively, trailing period/space, Windows reserved names).
- Existing tests touching the grammar: `tests/test_operation.py` refusal table (`.git/config.md`,
  traversal, drive), `tests/test_dge.py` source `.git/config`, `tests/test_isolated_worker.py`
  `test_unsafe_paths_refuse`. Search of `tests/` for `.github`, `.gitignore`, `.config`, `.GIT` and
  `safe_relative_path`: no existing test expected a dot-prefixed project path to be refused.
- Disposition: improve the existing helper in place. No new allowlist, no second path grammar, no
  adapter change. Rollback is reverting the single regex/helper edit; the old ordinary grammar is a
  strict subset of the new one, so previously accepted manifests keep their canonical bytes.

## Change

`src/codex_harness/domain/operation.py`
- `SEGMENT` now matches either the unchanged ordinary segment (`[A-Za-z0-9][A-Za-z0-9._-]{0,254}`) or
  one leading dot followed by the same grammar with `{0,253}`, so the dot counts toward the 255 budget.
- `safe_relative_path` keeps the type, empty, 1024, backslash and leading-slash refusals, then per segment
  requires the regex, refuses `s.lower() == ".git"` at any depth, and refuses any dot-prefixed segment
  ending in a period (`.git.`, `.GIT..`, `.x.`). The dead `startswith(".git/")` segment test (segments
  never contain a slash) is dropped; the case-insensitive equality supersedes the old exact `.git` check.
- Trailing periods on non-dot segments (`trailing.`) remain accepted, as before: no unrelated tightening.

`docs/contracts.md`: INV-OPERATION-001 gains one path-grammar passage stating the shared helper, the
segment and whole-path caps, the accepted dot-prefixed examples, the refusal list and that the grammar is
manifest validation, not filesystem containment.

`tests/test_operation_paths.py` (new): helper matrix (normal hidden/nested, ordinary prior values,
metadata aliases, traversal/roots/drives/UNC/backslash, whitespace/colon/ADS/control/non-ASCII, structure,
wrong types), 255/256 segment and 1024/1025 whole-path boundaries for plain and dot-prefixed segments,
`validate_manifest` goal.path and allowed_paths acceptance/refusal, `validate_plan` with both error
classes, research packet sources/plan, autonomous search_scope/plan, and one real temporary Git
repository under `tmp_path` staged, standalone-initialized, edited and imported through the existing
`isolated_worker` helpers (`stage_source`, `init_standalone_git`, `plan_import`, `apply_import`) with
`.github/workflows/ci.yml` and `.gitignore` bytes verified in the candidate. No executor, provider or
model starts; the real checkout's `.git` is never touched.

## Verification actually run (Linux, this worker)

```
python -m pytest tests/test_operation_paths.py tests/test_operation.py tests/test_operation_cli.py tests/test_dge.py tests/test_autonomous.py -q -p no:cacheprovider
python -m ruff check .
```

Final run: 255 passed, 1 skipped (`tests/test_operation.py:350`, "Integration environment required",
pre-existing PostgreSQL integration skip, unrelated to this change). Ruff: all checks passed.

Diagnostic attempts before the final run (preserved, not hidden):
1. First run: my staging test asserted the adapter refuses `..x`; it does not (`check_relative_path`
   only refuses exact `.` and `..`). The manifest grammar is stricter there and runs first; the test
   now records that as an observation instead of claiming agreement. Ruff also asked for the long
   import to be wrapped.
2. Second run: my `git` test helper strips the whole `git status --porcelain` output, which removed the
   leading status space of the first line; the import itself was correct. The assertion now compares
   stripped lines. Two single-test `-k hidden_files -vv` runs were used to read the full diff.

## Not run by this worker (owner/CI)

- Full suite, Windows focused checks, integration CI.
- Baseline-reversion evidence (running the new regression subset against the baseline domain module in an
  isolated copy): assigned to the owner by the task objective; git commands are outside this worker's grant.
  The direct-helper and manifest acceptance tests in `tests/test_operation_paths.py` are the applicable
  subset; the negative controls already passed on baseline and are not newly fixed.
- Image rebuild, actual container canary, PR, merge, issue closure.

## Observations outside scope (no change made)

- `isolated_worker.check_relative_path` accepts repeated leading dots (`..x`) and the manifest grammar
  refuses them. Not a defect for this batch (the manifest refusal is earlier); noted for the owner.
- Windows reserved names (`CON`, `aux`, ...) stay the adapter's restriction only, as the SPEC states.
