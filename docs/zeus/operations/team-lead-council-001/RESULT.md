# Topic-bound council implementation

Runtime candidate:426e41399d9ef556288e4d7a9df682198737a7cb. Owner acceptance is for
the opt-in implementation with the explicit noncritical residual below; full CI
and final merge outcome are recorded on the PR. Existing v1 behavior remains available.

## Delivered path

`urn:zeus:autonomous:2` runs pinned research, a bounded read-only PG snapshot, actual
lead:dba report, lead:research proposal, lead:improvement constructive alternative,
and conductor arbitration through the existing six-W/outbox/Redis/task executor.
The improvement proposal carries reuse/improve/migrate/new, rationale and transition
details, not just objections. One round, seven starts maximum, one absolute deadline.

Both leads use the same frozen report identities. Snapshot integrity/freshness is
checked before dependent roles and implementation. Missing selected rows differ
from unavailable DB or malformed fields. The new conductor self-loop is confined
to dge_role arbitration. Implementation and independent review still precede PG
provenance promotion; DBA/snapshot/report provenance is rechecked in that transaction.
See RUNBOOK.md for input, identities, residual limits and rollback.

## Verification and precise scope

- Owner existing/new contract lane:198 passed,1 skipped; ruff passed.
- Actual isolated PostgreSQL17.11:1 test passed, exercising found/missing state,
  concurrent writer with repeatable reads, server-side read-only write refusal,
  changed-row digest, source preservation and bounded unavailable-server handling.
- Independent Zeus Codex review:65 focused tests and changed-file lint passed;
  reviewer returned accepted=false for the P2 below. The owner agrees with the
  defect but accepts it as a nonblocking residual under the user's stated policy.
- Council orchestration tests use labelled model/transport fixtures. This batch
  did NOT run seven actual new council model sessions. Actual model execution here
  was two Claude implementation calls and one Codex implementation review.
- Source rationale: PostgreSQL17 transaction isolation and SET TRANSACTION docs,
  opened2026-09-17. Read-only Repeatable Read is one PG transaction snapshot, not
  atomicity with Git or proof of current topic-wide completeness.

## Accepted noncritical residual

Synthetic operation row `{status: running}` lacking lead_accepted is observed as
found with lead_accepted:null rather than unknown. Explicit null is valid, absence
should be distinct. Reproduced by owner; no claim that this boundary passes. This
overstates field completeness, but null is not approval and the snapshot cannot
authorize implementation/review acceptance or promotion. Fix presence checking in
the next snapshot-maintenance batch; revisit immediately if incomplete real topic
rows are observed or snapshot coverage is proposed as an authorization condition.

The machine reviewer rejection is NOT overwritten. Run-002 remains rejected;
owner Git acceptance does not manufacture accepted execution or verified knowledge.

## Execution and failure history

Run-001 timed out at the provider after writing12 unfinished files. Those bytes
were preserved at271e1ab. Owner preflight measured53 passed/6 failed, one real PG
classification failure and one lint failure. No reviewer ran. A same-frame bounded
continuation fixed those measured boundaries, added regression coverage and docs,
and produced426e413. Run-002 implementation succeeded and independent review ran.
Total actual starts3, machine ledger64->67; no further model loop or automatic retry.

Owner's first PG invocation lacked a DSN. A corrected isolated run reproduced the
classification defect. The owner reused the PG output filename at final verification;
the initial failure is preserved as a labelled tool-transcript excerpt, not claimed
as original raw-log bytes. Final PG output is separately archived as owner-pg.log.

Run-001/run-002 observation counts133/164; audit counts2/4. Final collections reported
zero sink failures, corruption or conflicts, with no live writers, pending terminations
or orphaned invocations. Each collector's own1,021 bytes remain durable/unacknowledged.
Failed and rejected receipts, model review, original source hashes and owner checks
are retained on D with EVIDENCE.json references. Pending diagnostic messages are not
permission to replay or promote the failed run.

The next operational step is one concrete topic with explicit PG record selection,
pinned research scope, bounded model allowance and the new v2 manifest. That live
council measurement, whole local-asset absorption and product/device acceptance are
separate from this implementation delivery. No broad issue is closed here.
