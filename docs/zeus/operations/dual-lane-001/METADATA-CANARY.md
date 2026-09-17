# Metadata canary record (issue 124)

Worker record of actions and observations for the actual canary paragraph at the end of
`SPEC.md`. It is not an approval: replay and independent review decide acceptance, and
`worker_profile.load_profile` decides validity of the final bytes.

Base revision `ef01046e52245473ee717b6d31cac2de73d7742e`, Windows, task
`40101074-0857-57ba-a58f-3fcf01256e8a`. Files changed: `worker-profile-v1.md` (Environment
section only), `worker-profile-v1.json` (`document_sha256` only), this file.

## Change

- Environment section: added one bullet telling a worker who edits the profile to run
  `python -m codex_harness.adapters.worker_profile_metadata`, Edit its digest into the
  manifest and rerun.
- Condensed the other two bullets of the same section. Kept: `python` on PATH is the verified
  interpreter; `PYTHONPATH` is the checkout `src` when present; test and lint commands; no
  other interpreter except host `project_evidence` commands run verbatim; Bash for these
  commands and read-only git; other tool policy unchanged. Wording dropped: "the harness's",
  "already", "inspection" after "read-only git". No other section was edited.
- Manifest: `document_sha256` `2cbf9684…0c5d` -> `25b1fe94…0e14`, by the Edit tool from the
  command's output. No other manifest field changed.

## Metadata command runs (all `python -m codex_harness.adapters.worker_profile_metadata`)

| # | State | Exit | characters | status | document_sha256 |
|---|-------|------|-----------|--------|-----------------|
| 1 | untouched baseline | 0 | 5999 | ok | 2cbf9684…0c5d |
| 2 | first wording | 1 | 6099 | mismatch, over limit | 8fd494ad…8c7a |
| 3 | condensed | 1 | 6053 | mismatch, over limit | ae2cbc0f…1776 |
| 4 | condensed | 1 | 6025 | mismatch, over limit | 1f822ab3…d7fc |
| 5 | condensed | 1 | 6004 | mismatch, over limit | fb0abb45…b07c |
| 6 | reworded (grew) | 1 | 6008 | mismatch, over limit | 3343c4ec…4093 |
| 7 | final document, stale manifest | 1 | 5998 | mismatch, within limit | 25b1fe94…0e14 |
| 8 | after manifest Edit | 0 | 5998 | ok, digest_matches true | 25b1fe94…0e14 |

Runs 2-7 are the expected stale/overlong diagnostics used to size the wording; each reported
computed facts with exit 1. One earlier invocation that appended `; echo "exit=$?"` was denied
by the permission policy and did not execute; the exact bare command was used afterwards.
No hash was computed by any other means.

## Other checks

See the worker's structured report for the focused pytest and ruff results observed after this
file was written. The full suite and CI were not run by the worker; the owner owns them.
