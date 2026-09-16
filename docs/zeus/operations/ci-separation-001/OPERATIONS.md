# CI separation: operations

Implements `SPEC.md` in this directory. Files: `.github/workflows/validation.yml`,
`scripts/ci_scope.py`, `tests/test_ci_scope.py`, this note. No runtime code, dependencies or
repository policy changed. Branch protection was not touched; `CI gate` is a workflow verdict, not a
GitHub administrative requirement.

## Routing matrix

| Event | Range | Result |
| --- | --- | --- |
| `pull_request` (default activity types) | `merge-base(base.sha, head.sha)..head.sha` | docs or full |
| `push` to `main` | `before..after` | docs or full |
| `workflow_dispatch` | none | full |
| missing, zero or malformed SHA; unknown event; git error; empty diff; rename/copy record | none | full |

`docs` needs every changed path to be a regular-file (`100644`) add, edit or delete of a `.md`
file strictly under `docs/zeus/operations/`. Anything else (other `docs/` Markdown such as
`docs/contracts.md`, JSON, scripts, workflows, symlinks, mode changes, type changes, unknown
paths) is full. Renames are read with `--no-renames`, so the old and new path are both judged.
Paths are parsed from NUL-delimited `git diff --raw -z` output; a PR that touched code earlier
stays full even when its latest commit is docs-only, because the range starts at the merge base.

The classifier reads only `GITHUB_EVENT_NAME` and SHA fields from `GITHUB_EVENT_PATH`, runs Git
as an argv list, and writes `mode` and `changed` to `GITHUB_OUTPUT` plus a summary to
`GITHUB_STEP_SUMMARY`. A routing uncertainty prints `fallback (...)` and mode=full. An unexpected
exception fails the `changes` job, which leaves no mode and fails the gate.

## Jobs and gate

- `changes` always runs (full history checkout, setup-python 3.13, `ci_scope.py classify`).
- `docs` runs only when mode is docs. It re-classifies, refuses any other mode, and checks each
  changed existing Markdown file: regular file, not a symlink, no NUL byte, valid UTF-8. Removed
  files are reported as removed. No uv sync, pytest or Docker.
- `test` (unchanged matrix: ubuntu/windows x 3.12/3.14, fail-fast false, same commands) and
  `integration` (unchanged commands, Docker cleanup always) run only when mode is full.
- `CI gate` (`if: always()`, needs all four) receives `toJSON(needs)` in `CI_NEEDS` and compares
  exact result strings: docs requires changes+docs success and test+integration skipped; full
  requires changes+test+integration success and docs skipped. Missing or unknown mode, any
  failure, cancelled or unexpectedly skipped required job, or unparseable needs fails the gate.
  It prints the mode and every evaluated result.

Concurrency: pull request runs share a per-PR group with cancel-in-progress; main pushes and
manual runs use `run_id` in the group and never cancel each other. `contents: read` retained;
`pull_request_target` is not used.

## Verification recorded by the implementer (2026-09-16, base 74d72c3)

Windows 11 host, Python 3.14, Git for Windows. `python -m pytest tests/test_ci_scope.py -q`: all
passed, one skipped (`test_docs_check_rejects_symlink_and_missing_file` skips symlink creation when
the host denies it). `python -m ruff check .`: clean. Windows Git refuses control characters in
index paths, so the newline/tab path history case only runs on Linux; a synthetic parser test
covers the NUL parsing on every host. The full suite and real Actions runs were not run here; the
owner runs the full PG/Redis suite and observes the implementation PR (full route, PR event only)
and one later docs-only follow-up (lightweight route). No speedup is claimed.
