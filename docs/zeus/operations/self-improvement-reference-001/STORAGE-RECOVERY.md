# Recovery execution and learning storage

2026-09-20; continuation of SPEC.md. Source pins: SOURCES.json. Codex analysis, not implementation.

## Decision

Reuse Zeus recovery, skill import/history and promotion owners. Add reason-specific recovery
preconditions and complete package change evidence to the consolidated design; do not add a second
learning database or treat an offline replay as the user's required real-browser/device evidence.

## Inspected paths and source facts

| Source | Inspected range | Fact and limit |
|---|---|---|
| OMH `coding/cause_recovery.py` | 457–630 | Recovery plan checks live markers, cause-specific requirements and changed conditions. Boolean observations are inputs; this function does not authenticate their producer or probe the environment. A marker is explicitly not proof of liveness. |
| OMH `coding/dispatch_failure_recovery.py` | 1–130,781–867 | Classifications distinguish pre-spawn refusal, process exit and text-shaped auth/quota signals. The child wrapper calls the actual dispatch boundary; introductory prose saying the module never spawns is insufficient to describe this later path. |
| OMH `coding/fanout_dispatch.py` | 2940–3048 | Recovery uses the unit worktree, refuses a missing directory and supplies admission binding/launch gate. The selected helper was traced through its alias. Child process ownership and all choice callers remain outside this slice. |
| Hermes `tools/skill_ledger.py` | 365–401,434–511 | Mutation recording is best effort. Rollback checks required blobs and records current touched files before restoration; ordinary file writes follow. This is not a database transaction or proof of atomic multi-file rollback. Removal errors are logged. |
| Hermes `hermes_cli/curator.py` | 460–501 | CLI rollback locates an entry and asks for confirmation unless `yes` is supplied, then calls the ledger rollback. It is an operator action, not autonomous repair evidence. |
| OMH `workflows/browser_workflow_learning_store.py` | 1–230 | Trace creation binds local Git root identity, locks writes, detects digest collisions, approves an exact digest, persists stale/quarantine and retry history, and bounds JSON reads. Root identity is a hash of local path, not a cross-machine repository identity. |
| OMH `workflows/browser_workflow_learning.py` | 130–192 | Replay explicitly simulates a stored fixture. Source success fields/digests are structurally checked here; no real browser is driven in this function. |
| OMH `commands/browser_workflow_learning.py` | 1–85 | CLI exposes record/inspect/approve/replay with offline wording. Supplying a digest to this CLI is not independent human product acceptance. |

These are code observations at immutable pins, not executed upstream behavior. Initial combined
output was truncated; only the ranges listed above receive inspection credit. Search matches alone
are navigation, not review. No upstream rollback, child, browser, installer or model was run.

## Complete path and adaptation boundaries

Recovery: failed unit -> classified symptom -> proposed repair and unmet conditions -> authorized
choice -> named unit worktree/admission -> child result -> verification. Zeus already owns the
last execution identity, unknown-effect reconciliation and independent review. Proposed condition
fields must be bound to host evidence and the old attempt, rather than trusting model-supplied
`credential_repaired: true`. Quota/auth text remains a classification, not a proven cause.

Learning: observed source -> scoped candidate -> approval of exact material -> package change ->
independent checks -> provenance promotion. Useful upstream ideas are complete before/after package
references and invalidation when a trace no longer matches. Preserve failure history and separate
selection/import telemetry from effectiveness, successful execution and semantic truth.

Browser replay: stored trace -> fixture simulation -> lifecycle update. This may inform internal
contract tests, but it cannot close Samsung phone/tablet or actual user E2E acceptance. No extra
device work is opened by this analysis; that remains the existing product evidence track.

## Zeus comparison

- `application/skill_history.py` (full): manifest/context references, immutable skill identity,
  transactional observation deduplication and bounded history already exist. A low selection score
  is not proof of a harmful skill, and selection history is not a package backup.
- `application/skill_import.py` (full, overlapping reads): source artifact binds input bytes;
  cursor/prefix and parser version prevent silently rewriting imported history. Audit explicitly
  reports historical skill version unknown. Reuse this boundary for eligible legacy observations;
  do not reinterpret an imported event as current execution evidence.
- Package mutation/rollback proposals belong in Git changes and existing candidate review. Required
  promotion audit remains transactional; Hermes best-effort ledger is not a replacement.

## Substep review / acceptance matrix

| Boundary | Reviewed outcome | Evidence limit |
|---|---|---|
| Normal dispatch | Recovery helper and real alias caller connected | Child process implementation not qualified |
| Failure/unknown | Preconditions differ by symptom; unknown producer cannot authorize retry | No root cause proved from text |
| Cancel/restart | Existing execution owner retained; no new automatic retry introduced | This tranche did not run a child or reboot |
| Concurrent storage/replay | Locks/digest checks inspected; Zeus history/import suite run | PG test skipped; upstream lock behavior unrun |
| Rollback/cleanup | Required blobs and safety snapshot precede restore | No claim of atomic multi-file restore or guaranteed cleanup |
| Platform | Local Windows contract tests | No WSL or upstream filesystem compatibility claim |
| Browser/acceptance | Offline fixture replay explicitly separated | Cannot substitute for actual browser/device acceptance |
| Claim review | Facts, candidate design and unknowns separated | Codex self-crosscheck; not a second reviewer session |

## Executed evidence

Trusted local Python ran `pytest tests/test_skill_history.py tests/test_skill_import.py
tests/test_skill_audit.py -q -p no:cacheprovider`, with ZEUS_/HARNESS_ environment removed and
D-drive basetemp/JUnit. **44 passed, 1 skipped**, exit 0, pytest 0.36 seconds.
No production logs imported or global skills changed. Test data is temporary contract data.

Receipt/log/JUnit: `D:/workspaces/zeus/artifacts/self-improvement-reference-001/storage-001.{json,log,xml}`.
Log SHA-256: `70fa31f88b63472d880dd36563e1812543fdec0cdb8c73c84271b1df1a4a8a0f`.

## Disposition and remaining work

Accept as design candidates: cause-specific unmet conditions, attempt-bound recovery, package-level
before/after evidence, exact-material approval and explicit stale/quarantine state. Do not copy:
model-authorized recovery flags, best-effort mandatory audit, local-path identity across machines,
or offline replay represented as real E2E. These are migration choices, not newly proved Zeus bugs.

The selected storage/recovery comparison is recorded. Full provider/child ownership, upstream
storage tests and remaining Ouroboros capability/path dispositions remain open in the same frame.
Do not claim whole-source analysis, complete absorption or deployed self-improvement from this
tranche. No additional ticket, implementation handoff, production mutation or model call issued.
