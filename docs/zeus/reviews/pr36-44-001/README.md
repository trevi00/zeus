# Independent review of Claude PRs 36–44

Root reviewed each PR at the head recorded in its numbered JSON, traced implementation
and tests, and ran targeted tests in separate worktrees. PostgreSQL tests use isolated
schemas; no host restart, clock change, live model, or production acceptance is claimed.

| PR | Independent targeted tests | Decision | Reason |
|---|---:|---|---|
| 36 | 42 passed | Changes requested | Identical bytes with a new observed/pinned basis collide and cannot be recorded. |
| 37 | 122 passed, 1 skipped | Changes requested | Restoring only an old running row bypasses the newer durable fence on heartbeat/complete; reproduced on real PostgreSQL too. |
| 38 | 4 passed | Changes requested | A delayed fourth process breaks the fixed-sleep negative control on real PostgreSQL. |
| 39 | 72 passed | Changes requested | Replaying the old approval overwrites its sequence and revives adoption after a later rejection. |
| 40 | 21 passed | Merged | Explicit missing-reference status/events; corrupt referenced content still fails before deletion. |
| 41 | 58 passed | Merged | Deterministic major-version routing and nested packaged-skill selection. |
| 42 | 4 passed | Merged, limited scope | Direct-read assertion heuristic only; variable/alias blind spot is disclosed and independently confirmed. |
| 43 | 71 passed | Changes requested | Open partition questions coexist with whole_analysis_complete=true while proposal admission refuses. |
| 44 | 37 passed | Changes requested | YAML keys that collide after whitespace normalization silently overwrite metadata. |

Passing submitted tests did not negate the additional counterexamples. Numbered
counterexample receipts and the independent probe source record the failures. These
use controlled fault inputs/fixtures; they are not model or operational acceptance.
The #38 delay models one slow scheduled interpreter, not measured production load.

The combined #40/#41/#42 tree passed Ruff and **927 passed / 306 skipped** in Windows
ordinary regression. PostgreSQL cases were separately exercised in targeted tests.
All ten PR/push CI checks for each accepted head succeeded. The actual merged main
tree was compared with the independently tested tree and matched exactly:
`8d9c4274c4f2b7de3856a68eed5a8a2bce391695`.

GitHub refused formal Request changes because the login and PR author are the same
account. Each blocking finding was therefore posted as an explicit change-request
review comment, and those six PRs remain unmerged. This is not a formal approval or
deployment decision. No issue was automatically closed. The related ticket revisions
and implementation acceptance remain separate from their lifecycle closure gates.

The #42 counterexample confirms its disclosed limitation. Its zero-offender result
must not be represented as proof that every test executes behavior or that no wiring
assertions exist. Actual source activation, full upstream absorption and deferred host
measurements are not implied by this batch review.
