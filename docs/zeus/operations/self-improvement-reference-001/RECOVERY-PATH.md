# Execution ownership and recovery — analysis tranche

Date: 2026-09-20. Scope: source comparison and existing local contract checks.
This is not a deployed recovery team, upstream runtime validation, or completed repository absorption.
Use SPEC.md as the single task frame; immutable source pins are in SOURCES.json.

## Decision

Enhance the existing Zeus recovery owner rather than introducing a second retry engine.
Upstream provides useful separation of cancellation, settlement and transition validation.
Zeus already fences executions and binds explicit recovery to a snapshot and receipt.
An automatic recovery proposer must not obtain authority merely by describing a repair.

## Source facts and limits

At the pinned Ouroboros revision:

- `persistence/write_settlement.py` (1–249): cancellation shields an admitted write and waits
  for settlement. The generic helper has no intrinsic deadline. Its SQLite-specific sibling
  uses a persistence deadline, interruption and cleanup, distinguishing committed writes from
  cleanup errors. This is source inspection, not proof of bounded behavior under all drivers.
- `persistence/event_store.py` (815–895): `append_durable` requires prior initialization,
  supplies the persistence deadline and rejects guarded lifecycle event families. Session-start
  writes use their own settlement wrapper. Do not generalize this deadline to every write API.
- `core/runtime_transition.py` (352–487): the pure evaluator checks revision, state, allowed
  transitions and terminal evidence references. An accepted evaluation is not itself an atomic
  database transition, authenticated authority, or evidence-content verification.

Zeus comparison at this analysis checkout:

- `application/workflow.py::_owned` compares execution identity, durable fence and active lease
  before owned writes. `execution_fence.py` rejects stale generations; recovery advances them.
- `application/execution_recovery.py::prepare/apply` binds an explicit conductor operation to
  snapshot/related-state hashes, evidence references and expiry. Apply checks eligibility and
  reconciliation; task change, receipt, event and notice share a transaction. Prior attempts
  are preserved. The trusted-local operator label does not prove human product acceptance.
- `application/fleet.py` (210–311): admission reserves an owner token; finalize checks it.
  Dispatching/unknown work remains reconciliation-required rather than silently relaunching.
  A visibility delivery record is not independent acceptance or deployment approval.

Design inference: recovery suggestions should feed this existing authority boundary, preserving
unknown external effects until reconciled. SQLite persistence is not a migration target for
Zeus PostgreSQL. Cross-process persistence and provider cancellation remain distinct contracts.

## Substep review log

| Step | Inspection and review | Outcome / limit |
|---|---|---|
| Source contract | Compare generic settlement with bounded append caller | Deadline claim narrowed to the specialized API; no upstream code executed |
| Zeus mapping | Trace fence check, recovery apply, Fleet owner finalization | Existing owner retained; no duplicate recovery dispatcher proposed |
| Verification | Run four existing contract test files with production integration environment removed | 75 passed, 63 skipped; PG/restart integration not established |
| Claim check | Separate code facts, inference, execution and missing evidence | No adoption, runtime deployment or whole-repository completion claimed |

These are Codex analysis/self-crosschecks, not an additional independent reviewer session.
Raw numbered source emissions are logged in the D-drive `read-ranges.jsonl`; an emission alone
does not count as semantic completion. Truncated output was not credited as a complete reading.

## Acceptance coverage for this tranche

| Path | Evidence / disposition |
|---|---|
| Normal ownership and explicit recovery | Existing local fence/recovery/identity/Fleet tests passed |
| Stale owner, invalid repair, replay | Covered within that selected suite; no blanket production claim |
| Timeout/cancellation | Upstream settlement and deadline source inspected; upstream execution unrun |
| Unknown external effect | Fleet retains reservation; automatic relaunch not inferred |
| Restart/concurrency | Local contracts only; skipped PG tests cannot prove database/process behavior |
| Platform and cleanup | Windows analysis execution only; no WSL/driver/resource-cleanup qualification |
| UI, deployment, model invocation | Not relevant to this source-analysis tranche; not executed |

## Executed evidence

Command: trusted local Python, `pytest tests/test_execution_fence.py
tests/test_execution_recovery.py tests/test_execution_identity.py tests/test_fleet.py -q
-p no:cacheprovider`, isolated basetemp and JUnit on D. No runtime source was changed.

Result: **75 passed, 63 skipped**, exit 0, pytest 2.48 seconds.
Artifacts: `D:/workspaces/zeus/artifacts/self-improvement-reference-001/recovery-001.{json,log,xml}`.
Log SHA-256: `11060ccc10de3bf66af8b549a4a9122feccf36c1553f909d71e60ee8ec2f5d5e`.
The runner strips ZEUS_/HARNESS_ variables; PostgreSQL integration is intentionally unavailable.

## Remaining within the existing frame

Trace restart routing and persistence lifecycle callers, then Hermes/OMH learning/recovery owners;
complete capability dispositions before issuing the consolidated Claude implementation specification.
These open analysis areas do not constitute new proven Zeus defects or reasons to stop unrelated
accepted operations. No new ticket, model call, production mutation or deployment was made here.
