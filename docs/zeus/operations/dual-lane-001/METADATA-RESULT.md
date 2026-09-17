# Worker metadata residual — actual operating result, 2026-09-17

Issue124's missing worker packaging capability is resolved in two actual bounded Zeus operations.
Claude implemented both candidates; independent Codex sessions accepted both. The owner did not
edit the canary profile text or digest. Original `dual-lane-001-harness` remains failed; the
earlier accepted product and overlapping-run evidence in RESULT.md remain valid. This replaces
the outstanding harness acceptance, not the historical claim of two simultaneous successes.

| Operation | Runtime | Candidate | Receipt | Calls |
|---|---|---|---|---|
| profile-metadata-124-bootstrap | 70b580b | ef01046e52245473ee717b6d31cac2de73d7742e | accepted / lead_accepted | 2 reserved, 2 settled |
| profile-metadata-124-canary | ef01046 | 1d0e67095ad78d7e8a299bd04a5590dc92599351 | accepted / lead_accepted | 2 reserved, 2 settled |

Bootstrap ran08:20:11–08:28:56 UTC; canary ran08:29:48–08:35:13 UTC. Fresh PG schemas,
Redis namespaces and artifact/workspace directories were used for each. Machine ledger91->95,
no automatic retries or further calls. Claude USD4 per invocation was a declared CLI limit;
this run is not a measurement of its enforcement. Collection:107+90 records, zero sink failures,
corrupt records or refused observations. No new container or service was created for these runs.

## Complete-path acceptance

The adapter reuses loader hash/normalization/limit. Fixed bounded input files, safe errors,
stale/oversize computed output, exact permission and replay grants are covered by subprocess
regressions. The owner verified the bootstrap adds only one manifest permission; all previous
manifest fields and document bytes are identical. Root checked the complete scoped diff and
the fixed matrix; no blocking finding remains in this batch.

Canary runner-captured tool events show nine exact metadata-command executions: the original
matching profile, six stale/overlong observations, then two successful final observations.
One compound command with `echo` was permission-denied and did not execute; the permitted bare
command worked. Intermediate exit1 results are preserved, not rewritten as passing tests.
Final document is5998 characters, SHA256
`25b1fe9450cec6000b23f0c03e97085f29c10bf39d579dfe44c4c5314dc10e14`.
Claude used Edit for both text and manifest. Other Markdown sections and other manifest fields
are byte/structurally unchanged. Two characters of headroom remain; future edits must measure.

The canary evidence gate checked all three claimed commands, including metadata, without
mismatch/unknown/failure. Independent reviewer checked the actual execution artifact events98–101,
the final loader binding and guidance preservation. It observed49 passed/1 skipped and lint
passing; Windows file-symlink creation was unavailable, directory-junction escape passed.
Bootstrap reviewer observed59 passed/2 skipped/1 deselected plus a separate real replay probe
using in-memory artifacts and bytecode suppression to keep its review checkout clean.

Raw receipts, task/reviewer records, runner execution artifacts, observed command extraction,
host verification and hashes are on D under `zeus/artifacts/dual-lane-001/metadata-*`.
METADATA-EVIDENCE.json pins selected files; raw content-addressed artifacts stay external.
The extraction helper initially encountered a string event message and console encoding;
its final output handles both. These were owner evidence-export errors, not provider reruns.

## Verification and integration

Owner bootstrap full suite at ef01046:1876 passed,446 skipped,514.84 seconds; ruff passed.
After integrating the unchanged canary candidate1d0e670, owner metadata/ruff passed and all
three affected test files passed60/2 skipped in13.33 seconds. The skips are file-symlink
privilege and unavailable local integration environment. Final full Windows/Linux/integration
CI outcomes are recorded in the scoped PR. Integration accepts candidate commits unchanged;
no owner metadata repair.
Only issue124 is eligible for closure after those checks pass. Earlier source-analysis dirty
files, old failed receipts and unrelated goals remain untouched.

## Operating limits

These sessions are native Windows CLI processes, not per-session containers. Separate Git
workspaces, runtime namespaces, tool settings, budgets and Windows Job Object process ownership
are execution controls, not a container filesystem/network boundary. PostgreSQL and Redis are
existing Docker services. Session containerization is outside this delivery and is not claimed.
No continuous scheduler, automatic merge/deployment, knowledge promotion, complete reference
absorption or Linux-provider qualification follows from these two receipts.
