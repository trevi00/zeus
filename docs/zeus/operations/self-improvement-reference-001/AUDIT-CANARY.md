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
