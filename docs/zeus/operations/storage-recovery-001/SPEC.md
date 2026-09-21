# Durable staging and storage recovery

2026-09-21. User authorizes replacing D-dependent work storage with durable staging and promoting
verified results before temporary-copy cleanup. This supersedes the old D-only placement rule for
this delivery: use C:/workspaces/zeus; preserve the existing dirty C home repository and D originals.
Codex owns analysis, design and acceptance; Claude implements. Current Fleet remains paused.

## Outcome and affected path

Resume without depending on the unreliable D device, retaining interrupted work and audit evidence.
Do not confuse a temporary lifecycle with PostgreSQL TEMP/UNLOGGED or RAM-only storage. Existing
ledger uses Docker named volume zeus-ticket-ledger-data; Docker's data VHDX is under C:/Users/rudtn/
AppData/Local/Docker/wsl/disk/docker_data.vhdx. C has approximately 274 GB free. D is My Passport;
pre-reboot Event153 mapped to that physical disk. Volume Healthy after reboot is not a hardware test.

Git definitions -> durable task/checkpoint staging -> independent execution/evidence review ->
existing promotion transaction -> durable receipt and retained evidence -> retention-aware temporary
copy cleanup. application/promotion.py already atomically writes graph and receipt and rejects
conflicting retries. Reuse it and its caller's evidence gates. FileArtifacts currently resides on
filesystem; moving metadata to PG cannot preserve files that remain solely on D.

Use ordinary logged staging tables/buckets in the existing PostgreSQL database initially, separately
namespaced and permission-scoped. A second physical database adds a cross-database commit boundary
without removing disk dependence. Keep runtime facts/failures separate from verified knowledge.
Never delete task ledger, invocation accounting, failed attempts or accepted evidence as cache.
Code remains Git; large artifacts are retained on healthy storage with hashes/references in PG.

Source: PostgreSQL CREATE TABLE documentation, accessed 2026-09-21,
https://www.postgresql.org/docs/current/sql-createtable.html . TEMP is session-lifetime;
UNLOGGED is not crash-safe. These semantics support ordinary logged staging, not a claim of measured
local durability or successful restoration. Docker placement was observed locally, not inferred.

## One delivery batch and state boundaries

1. Establish independent C checkout and ledger backup with digest/archive readability; preserve D.
2. Inventory exact active runtime, artifact references, interrupted worker checkout, launcher paths
   and authentication locations. Copy only required owned paths with manifests and hash verification;
   do not globally replace D strings or migrate unrelated projects. Recreate environment if needed.
3. Extend existing staging/promotion ownership: run+attempt+generation identity, checkpoints, staged
   artifact manifest, review binding, promotion receipt, cleanup eligibility and idempotent cleanup.
   State staged -> verified -> promoted -> cleanup_eligible -> cleaned. Failed/cancelled/unknown
   work remains recoverable under explicit retention. An executable cleanup must recheck reference
   ownership and active leases; no worktree shared with active writers may be removed.
4. Switch approved service paths only after copy verification and interrupted invocation reconciliation.
   Auth/global configs/machine call ledger stay at home. Preserve rollback paths, no stale model replay.
5. Verify real controlled restart, promotion and cleanup using disposable records, then resume only
   reconciled work. Do not require another physical PC reboot or copy all historical bulk evidence
   before unrelated work can progress; still refuse deleting unpreserved originals.

## Acceptance matrix

| Boundary | Required result |
| --- | --- |
| Normal | Verified exact staged revision promotes once; receipt survives process restart. |
| Failed review | No verified-graph promotion or cleanup; diagnostic history retained. |
| Crash before/after commit | Retry reads durable receipt; no duplicate promotion or premature deletion. |
| Missing/corrupt artifact | Explicit unavailable/refused, no evidence credit or cleanup. |
| Concurrency | Lease/version checks prevent cleanup of active or replaced attempts. |
| Partial copy/storage outage | Source retained, failed paths/digests reported, operation cannot claim complete. |
| Platforms | Windows native paths and Linux container mount paths validated independently. |
| Cleanup | Only unreferenced temporary copies; audit/checkpoint policy and recovery targets preserved. |
| Restore | Archive readability is preliminary; disposable restore plus representative ledger reads required. |

Completion requires deployed C-backed execution/evidence paths, reconciled interrupted job, actual
staging/promotion/cleanup verification and fresh monitoring. Current preparation is not that completion.
Unrelated ontology acceptance, PR176 rollout and token routing stay on their existing frames.

## Preparation evidence

Independent C checkout created without Git alternates/hardlinks to D; dirty home checkout preserved.
Ledger pg_dump custom archive: 16,837,262 bytes, SHA256
4efcbc1bc071932f9653307c71b52d3ff9292a586bd0de6b0e4b9ce6623a02ff.
Actual disposable pg_restore completed exit0, catalog found 74 documents tables, disposable drop
exit0. This establishes archive restoration and catalog presence, not all application invariants.
Evidence under C:/workspaces/zeus/artifacts/storage-recovery-001/ (backup and restore receipts).

Interrupted worker's actual container-mounted workspace contains five modified tracked files;
the outer task checkout being clean did not imply no work existed. Preserved those five files,
binary Git diff, hook evidence and run metadata: 35 files copied to C with source/destination SHA256
matching. Manifest records base and original paths. No originals deleted, no edits accepted and no
model re-executed. Full runtime/artifact migration and durable staging implementation remain pending.
