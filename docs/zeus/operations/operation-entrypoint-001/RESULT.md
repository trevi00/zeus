# Operating entry point: acceptance and limits

2026-09-16. Implementation [PR #113](https://github.com/trevi00/zeus/pull/113),
candidate `7462486dafd792d9213baf251228c3257cb09f72`, merge `88ff43f`.
Goal and fixed acceptance matrix: [SPEC.md](SPEC.md). Usage: [RUNBOOK.md](RUNBOOK.md).

## Delivered behavior

`zeus --repository ROOT operate run --file OPERATION.json` owns one fixed operation in PG,
queues its six-W assignment through the transactional outbox/Redis path, runs Claude once,
checks the actual bound evidence-inspection row, and only then runs one Codex review.
It returns an explicit terminal outcome and never runs the conductor, merges, deploys or
automatically retries. Completed IDs return cached results; changed identity/configuration and
running residue are refused. Machine call slots remain counted across processes and failures.
`operate status ID` reads the stored receipt without building a provider or observer.

## Storage and knowledge authority

The user's sequence is plan -> generate -> verify -> accept -> explicitly reflect accepted
knowledge. Execution state, budget reservations, logs and verification decisions are written to PG
during execution for recovery; those are audit records, not semantic truth. Candidate worktrees and
artifacts remain provisional evidence. This entry point explicitly uses `knowledge=False` and has
neither graph query nor graph write capability. An accepted review does not promote knowledge.

The existing general executor can still index work-in-progress on rotation through its default
knowledge adapter. This change does not claim to fix every old entry point. A formal staged-to-
accepted ontology/topology promotion contract remains separate work; do not infer it from the
word `accepted` in an operation receipt.

## Actual operating pilot

The owner supplied host connection settings and a JSON manifest; the checked-in CLI performed all
assignment, worker, evidence, reviewer and receipt transitions without an operator relay script.
Host: Windows 11; real PostgreSQL/Redis, Claude and Codex. Pilot ID `entrypoint-pilot-001`.

| Observation | Result |
| --- | --- |
| Worker task | succeeded, `1847a1fe-8998-55c8-a433-d66ddcf00974` |
| Bound PG inspection | `all_checked`, `32076753b7b1fb4abbb8e66f5b6dea74bfbd3150f51c3c607ff644734104ed03` |
| Codex review | succeeded and accepted, `837c3b3f-71f1-4290-b218-2b4dd445d9b6` |
| `operate run` | exit 0, accepted, two slots reserved and settled; ledger 29 -> 31 |
| Same command in a fresh process | exit 0, accepted, cached=true; ledger 31 -> 31 |
| Read-only status in a fresh process | accepted; ledger 31 -> 31 |
| Observation collection | 51 records, sink failures/corrupt/refused all 0 |
| Release queue | 0 |
| Pilot schema knowledge_nodes / knowledge_edges | 0 / 0 |

Pilot candidate `94f59f306b43c03c85884397ebadfbda7a46bd05` changed only [PILOT.md](PILOT.md).
Its document was cherry-picked unchanged onto merged main for this evidence follow-up; the original
review remains bound to the original candidate. A Git content diff confirmed identical document bytes.

A separate real-PG ownership probe (synthetic plan/identity; no provider calls) raced two claims:
one claimed, one refused running_residue, exactly one operation/cycle/outbox row. A fresh process
also refused that running residue. This is not a killed-provider, reboot or WSL live-pilot test.

## Implementation verification and preserved failures

- First draft `43455d4`: owner reproduced first-slot settlement failure still allowing a reviewer
  call. The draft also wired the default writable knowledge adapter. Both were corrected; effective
  runtime-directory identity was added. One consolidated correction batch, no repeated new scope.
- Original evidence inspection remains incomplete (1 checked, 2 verified_mismatch). The old parent
  framework omitted PROGRAMDATA before replaying the new required Windows assertion. The correction
  ran with the candidate runtime imported and independently reached all_checked. No historical
  inspection or failed output was rewritten.
- Correction worker: focused 52 passed, 1 isolated-PG fixture skip; Ruff clean. The worker's summary
  speculated about the skip reason; owner distinguishes the PG fixture skip from Windows key generation.
- Actual Codex review accepted R1-R3 and their direct interactions: 44 selected tests, lint and
  constructor/identity checks passed. Root reviewed the complete fixed operating path.
- Owner full Windows suite with real PG/Redis: **2051 passed, 21 skipped, 1 teardown error**.
  All 53 new operation/CLI/environment cases passed with no skips, including real Windows
  ssh-keygen and the PG ownership fixture.
  The existing goal-progress test body passed; fixture cleanup connection raised Windows
  `Address already in use` (10048). One targeted rerun of
  `tests/test_goal_progress.py::test_row1_pending_then_local_close_resolves_exact_denominator[postgres]`
  in a new disposable stack passed (1 passed), including cleanup. Cause remains unconfirmed;
  the initial full run is not described as green and this PR does not claim an environment fix.
- [Actions 35103100253](https://github.com/trevi00/zeus/actions/runs/35103100253): attempt 1,
  all seven executed jobs passed, including Windows/Linux matrices and PG/Redis integration;
  docs skipped. No duplicate branch-push workflow.

Owner accepts this bounded feature using the reproduced fixes, actual pilot/re-entry, CI and targeted
cleanup recheck, with the original environment failure recorded. Large raw logs remain local; they may
contain disposable test connection details and are not public source artifacts.

## Budget and stopping point

Five calls in this delivery: initial worker, one correction worker, final reviewer, pilot worker,
pilot reviewer. Prior26 retained, final31/31. The original incomplete cycle was stopped without a
review; the correction cycle ended awaiting_operator at2/2. No further model calls or pilot retries.
Implementation observation collections were 110 + 68 + 39 records with zero sink failures; the
pilot's 51 records are a separate run, not an inflated count of accepted work.

This completes the one-start limited-operation milestone on this host. It does not complete full
asset absorption, formal knowledge promotion, product/human acceptance, device tests, reboot recovery
or long-running unattended reliability. Manifest paths currently use a conservative ASCII segment
allowlist (leading-dot paths are refused); future work needing other path classes must explicitly
extend that contract. Broad issues #13/#20 remain open. No new work was automatically selected.

## Local evidence manifest

Root: `D:\workspaces\zeus\artifacts\operation-entrypoint-001`. Hashes below identify local evidence;
they do not mean raw files are uploaded to GitHub.

| Relative evidence | SHA-256 |
| --- | --- |
| `worker-001/receipt.json` | `4703e6619320439538c80eacbf5da9f278ef89c8b1c1e874c823c5cfa55deed4` |
| `first-inspections.json` | `7ec826ae9f6bdb26d524e486ff55b32b5164d8ad809eb2943c182b2653cbdc3f` |
| `review-boundaries.json` | `ee54fa33a23457ef2cf46c5a2d25e316d78667148cfc55dd069d440282c5038d` |
| `worker-002/receipt.json` | `f6501bc533220ab49461881feb120ac1545c91ff578b86a4ba69995be060ee43` |
| `lead-review-001/receipt.json` | `d8a1eb50a037fb859e3aa59d107b59152fe47a8881af47d4baa6bbafbc2c3d9a` |
| `acceptance.json` | `1e7d0baeb9ca3010bfdc1340553aec96ed187cb06e6229b48bd69d465d5ddec5` |
| `independent-checks/result.json` | `19a46c18be3b532fb864b199643133dc8bc069428c55ec98fc228b146e872ebc` |
| `independent-checks/junit.xml` | `af3a7073b35d2126a14415ceefb708f0e20ea2766ee7f2e42cac603adcaa016f` |
| `independent-checks/pytest.log` | `8e8b849b0786dd1794affdafe81fdc7f5783bc037f6ce380921337d00631f166` |
| `targeted-check/result.json` | `c81111557e36c8f7b03e6128c4b73e185a9ec9b8a87a305c0073f183210dc99c` |
| `targeted-check/junit.xml` | `a46852ed6f981da2096fc92dfd36988a78574c79d9c9cc676c3ac5f6f7fc7291` |
| `ci-35103100253.json` | `9e6357b2a72ae5cb7be6b54502672f11b82405ea125d9302dadc35a18f01665f` |
| `claim-probe-result.json` | `7bb4d00c4970c8a9869dca2e9894f87262424de2350fcd800ed8c109133d2b8c` |
| `pilot-001/operation.json` | `5ca5d43fa6b6efc18495903dfe8d4ec831ba74416557834cabdfff7b574ba3e6` |
| `pilot-001/owner-receipt.json` | `d5297d035dd0ba0c9cec27dd0dd684351545caeb0b7c43e8688529e50b2be832` |
| `pilot-001/run.stdout` | `131bb89db82b6950399b1b94569a08982c95071202025c3551bc3f1bc549e351` |
| `pilot-001/repeat.stdout` | `b412fa8ec7fe2bbaae0800cb362bce81179d2603720711f34ba243104205b0a7` |
| `pilot-001/status.stdout` | `51e69373454e9d54d85919884393b9048198722bf73f78adb748aa39ffbe4c3e` |
| `pilot-001/verified-evidence.json` | `fd7514eb38033c0194855a873ed92e6e4357f39104114cab0370983af97378db` |
