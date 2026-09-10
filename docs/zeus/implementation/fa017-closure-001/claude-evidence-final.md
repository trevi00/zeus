## Verified in these six documents

**Source–time boundary holds.** criterion-1/2/3/6 all carry `observed_at` `2026-09-10T02:29:16.685062+00:00` and their `sources` lists contain only `target-tests.*`, `wsl/*`, both native-process roots, and both kill matrices. No `full-tests.*` and no `docs/zeus/ci/34429521115.json` appear in any criterion. Those two later artifacts appear only in `environment.json`, whose `observed_at` is `02:32:31Z` — after the CI job completions it cites (latest `02:32:31Z`), so nothing is cited before it existed.

**Counts match scope.** Criteria expose `windows_target`, `wsl_target`, `wsl_full` only; `windows_full` (911/299) appears solely in `environment.json`. `count_scope` is present on all five and distinguishes local Windows from CI, and no criterion asserts a CI count.

**Source roots/hashes.** Every criterion sets `source_roots` to `native-processes/` and `wsl/native-processes/`, and lists raw sha256 for `nested.json`/`shared.json` under both roots (distinct hashes per root). This supersedes my earlier claim that the WSL native files were ephemeral-only; that claim was wrong.

**Imports consistency.** `imports.json` per-file `observed_at` matches each document exactly (02:29:16.685062 for criteria 1–6; 02:32:31Z for criterion-7 and environment), `imported_at` 02:37:00 postdates all. `authority: unverified_observation_only`, `ticket_status: open`, `human_acceptance_granted: false`, `signing_packet_prepared: false` — matched by `human_acceptance_granted: false` in all five read documents. criterion-6 explicitly states an operator label is not a cryptographic approval.

## Residual gaps (not blockers to the correction itself)

- `wsl_full` is inside the boundary only if the WSL full run finished before 02:29:16; that ordering is asserted in `wsl/receipt.json`, which I did not read.
- `content_hash` `b39225a6…` is identical across criteria 1/2/3/6 and `environment.json`, while `imports.json` refs differ per file, so it is a bundle-level, not per-document, digest.
- Superseded bytes in `superseded-acceptance-timestamps/` were not read here.

No blockers.