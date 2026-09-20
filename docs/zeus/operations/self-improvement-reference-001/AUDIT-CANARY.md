# Operator-assigned source audit: actual execution

This is evidence for SPEC.md, not a release approval or unattended-rollout claim.

## First attempt, 2026-09-20 UTC

Deployed code: `5cb0dc4ada51bb66412eb1f5b642fb793b286ce6`.
Ouroboros source: `f0e17b4b42cc06974f2afaf15606250939cd4f87`.
Verified 1,817 Git paths and original byte envelopes; registered 58 partitions without
semantic credit. All new raw artifacts are on D. Existing host paths were not moved.

- Audit: `4aaa63e9ef051be3f27d6b98c7e02252212ad701c51f02ae32f6f3e671fda68d`.
- Partition: `634f942b0628a65c35b2ac278cb50acf9f9929c790ef3145ebd265df44719d0e`.
- Task: `8cf37c35-e374-4e5b-8bb6-a980b40afaf2`.
- Redis entry: `1789904585753-0`, dedicated `zeus-reference-audit-canary-001` namespace.
- Actual path: Redis delivery/ack -> PG task -> Codex inspection plan -> inert runner
  reads -> Codex analysis -> domain rejection before checkpoint commit.
- Result: `ContractError: Unknown disposition`; generation 0 and 32 remaining paths
  preserved. No verified knowledge or adoption approval was created.
- The actual model result used `partial`, which the output schema allowed but the
  domain refused. The deterministic schema/domain comparison reproduces that mismatch.
- Two invocation reservations settled; transport confirmed `gpt-6-astra`. Transport
  reported total-token values 142,997 and 352,895. These are usage measurements, not
  monetary charges or successful-analysis metrics. Context efficiency is a follow-up
  observation, outside the fixed vocabulary correction.
- Observation collection: 70 inserted, 4 confirmed audit rows, zero sink failures,
  conflicts, corrupt records, refused records or unconfirmed audits.
- Operator preserved the original task row and cancelled retry eligibility through
  Workflow.cancel. The failed attempt is not rewritten as successful. No second
  analysis task was launched after this failure.

Evidence root: `D:/workspaces/zeus/artifacts/self-improvement-reference-001/audit-canary-001/`.
`registration.json`, `assignment-1.json`, `result-1.json`, `collection-1.json`,
`failed-task-before-stop.json`, `operator-stop.json`, `operator-events.jsonl`, and the
content-addressed `artifacts/` directory preserve the execution. Read snapshots are not
continuous liveness evidence. The earlier fleet snapshot helper reused a misleading
`fleet-before-continuation.json` name; it now writes timestamped snapshots and that old
file must not be treated as an immutable before-state artifact.

## Correction handoff

Fixed scope and acceptance are in SPEC.md at `c10f7c5`.
Fleet job `self-improvement-reference-001-vocabulary` was admitted on the harness lane.
Its worker task is `3822680c-6c63-5293-9aa8-ad2b19b16eef` and the actual isolated worker
run is `ef6bd617f8eb434494fd18fa12203346`. Admission and running are not acceptance.
Claude implements; existing independent Codex review follows. Owner verification and
a new explicit canary are required before claiming the checkpoint boundary repaired.

Automatic audit activation is still absent. This attempt exercised the authorized
manual analysis surface; source-code execution, adoption and deployment gates remain.

## Corrected runtime: two real sequential tasks

Candidate `df57361152ec249533631d17dbcba2aea189b15c` was accepted by the existing
independent Codex Fleet review, decision `50b8708c-1fef-4cdc-a0c9-8327a43a85e9`.
It constrains provider and packaged disposition vocabulary to existing domain values;
partial source inspection remains unreviewed, never coerced into completion.

| Actual task | Result | Persisted partition generation | Remaining paths | Observation records |
|---|---|---:|---:|---:|
| dc9a8efd-b9c1-46fc-9d50-c9262cd091e6 | succeeded, attempt 1 | 1 | 32 | 65 |
| 2c095b12-5cc2-4d79-b145-e0d45262d868 | succeeded, attempt 1 | 2 | 32 | 60 |

The parent started the second child process only after the first returned success.
The successor read generation 1 from PostgreSQL. Eight successful inert source-read
receipts bind the two tasks to the pinned source. The second task read controls.py and
watchdog.py from zero-based line 120, matching the predecessor's persisted next steps;
its checkpoint requests the next watchdog slice at line 240. This is actual continuation,
not merely an incremented generation. All source execution receipts are reads, not tests.

Collection totals: 125 records, eight confirmed audit writes, zero sink failures,
conflicts, corrupt/refused records or unconfirmed audits. See r2-assignment-*.json,
r2-result-*.json, r2-collection-*.json and r2-progress-detail.json under the evidence root.
All 32 paths remain unreviewed; no complete semantic audit, knowledge promotion or
reference adoption is claimed. The bounded two-task round ended; no successor is queued.

## Owner regression findings

Full candidate suite: 12 failed, 2618 passed, 476 skipped, 951.80 seconds. The outer
operator wrapper timed out at 900 seconds; the original pytest continued and wrote its
complete JUnit/log. Its process exit code was not observed, so that run is not a pass.
Raw failed evidence is retained in vocabulary-verification-001.

A discriminating run in vocabulary-verification-002 found eleven of the same file-access
failures on unchanged baseline code with the long Windows temporary path. All eleven pass
on the candidate using a short D temporary path. The twelfth is the historical schema
equality test, which has not accounted for the intended enum constraint. Its bounded
test-only amendment is specified in SPEC.md and assigned as Fleet job
`self-improvement-reference-001-baseline`. No unrelated runtime repair is authorized.

## Test-only amendment and automation boundary

Worker task `96cfbf34-3fe6-53a6-bdf4-26bae6ebf3fd` produced candidate
`784bc8eb8a3400203f8c3d449a5042fbb43e0b55`, changing only tests/test_output_schema.py.
The exact disposition node is asserted against PATH_DISPOSITIONS; only that enum is
removed from a deep-copy for the retained historical schema comparison. Production
code is byte-identical to the already reviewed and exercised correction.

The isolated worker reported 128 passed, one failed: git could not read the historical
commit in the worker snapshot. It did not claim all checks passed. Fleet stopped with
evidence_gate_refused and cancelled the lead-review decision. This remains a FAILED
Fleet job, not an automatic review success. The worker container was removed and its
inner_result.json retained with sha256
`d145ccdcddb2b24523141ceb33a8e259c697e696b0db83c8687d2a967f27e0e9`.

Codex owner's independent review finds the exact specified test amendment, no runtime
change, no removal of unrelated protections, and no temporary worker probes in the
candidate. Final host verification in vocabulary-verification-003 passed:
2,630 passed, 476 skipped, zero failures/errors in 780.18 seconds; pytest exit 0,
ruff exit 0, CLI help exit 0. The candidate stayed clean. The full-suite log sha256 is
`3fade50957e26979ec8d5422dde49f71b306e5f9de8566bf8ee0e96971b96925`;
receipt.json records all commands, exit codes, immutable revision and log digests.

This suite did not enable service integration or disposable Docker tests: 403 skips
require integration environment and 28 explicitly require HARNESS_INTEGRATION=1;
other skips include platform and opt-in Docker cases. These are not new PostgreSQL,
Redis, Docker or WSL full-suite results. The two actual audit tasks separately exercised
the real PostgreSQL/Redis/Codex/checkpoint/observation path described above.

Owner verdict: ACCEPT the bounded vocabulary correction and exact test amendment.
Runtime equality between the live-canary commit and final candidate was checked by
git diff --exit-code on src. Both changes are integrated into the existing task branch;
no main merge, release activation or deployment was performed. The failed amendment
Fleet job remains failed; this owner acceptance does not relabel it.

The bounded delivery is complete. No analysis successor or worker container from these
jobs remains active. Automatic research activation is still absent. Next operational
scope is a legitimate release/activation and bounded scheduling decision, retaining
all unreviewed scope; it must not be inferred from these canary successes.

Operational lessons (recorded, not claimed as deployed hooks):

- Bind provider output vocabularies to domain contracts before using model output to
  advance a durable checkpoint. Unknown output must not gain semantic-review credit.
- Declare historical Git objects as test prerequisites before assigning work to a
  snapshot-only worker. Do not repeatedly call models to rediscover missing prerequisites.
- Use short D-drive test roots on this Windows host. Preserve failing long-path evidence;
  changing the path does not establish universal Windows long-path support.
- A command wrapper owns its subprocess tree through completion or confirmed termination.
  Losing the wrapper deadline does not establish that the test process stopped.
- A bounded successful continuation is not proof that the global scheduler is active,
  that all source paths are reviewed, or that a candidate has been deployed.
