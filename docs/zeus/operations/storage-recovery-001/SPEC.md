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

## Consolidated delivery ledger — 2026-09-22

User requests recording and resolving the full briefing. This is the single sequencing ledger;
feature-specific acceptance remains in its original frame. Do not silently equate a queued job,
accepted candidate, merge or healthy source read with deployed, operating success.

| Order | Delivery | Current state | Completion evidence |
| --- | --- | --- | --- |
| 1 | C-backed code, artifacts and service paths | C checkout and backup restored; deployment pending | Verified copy manifest, actual C process paths, fresh collection |
| 2 | Interrupted decision-feedback reconciliation | Five edits and 35 evidence files preserved | Termination/call settlement and explicit successor ownership |
| 3 | Service diagnostics PR176 | Merged c4660cf9465cd632a3627ca3a180deced07ce447 | Live lifecycle journal and delivery receipt still required |
| 4 | Resume decision-feedback correction | Paused, old dispatch retained | Actual resumed bounded work and independent verdict |
| 5 | Ontology explorer | Candidate; scoped checks passed, other residuals open | Packaged build, PG read-only tests, review/browser/CI/deploy |
| 6 | Investigation-to-repair ownership | Detection and manual binding only | Owner + successor + review + deployment provenance visible |
| 7 | Durable staging/promotion/cleanup | Designed, not implemented | Fixed restart/concurrency/retention matrix above |
| 8 | Parallel local/reference absorption | Partial; semantics coverage incomplete | Source ledger, selected migration, independent acceptance |
| 9 | Astra-to-Sol task qualification | Designed, not active | Same quality oracle plus total-token measurements and scoped activation |

Immediate bottlenecks are D path dependency, stale interrupted ownership, capability/spec mismatch
for frontend packaging, and incomplete accepted-to-deployed handoff. No broad historical failure
closure or blind retries. Code Tutor remains the subsequent product project, not a dependency for
infrastructure recovery. Physical Samsung acceptance remains deferred. No promise of zero failure.

## Executed recovery batch — 2026-09-22 00:25–00:36 KST

- PR176 merged at c4660cf9465cd632a3627ca3a180deced07ce447 after exact-head CI recheck.
  C:/workspaces/zeus/worktrees/runtime-176 is the clean detached release checkout.
- Monitor collect/web scheduled actions now use C-only launcher/code/snapshot paths. Previous action
  XML retained in artifacts/storage-recovery-001/monitor-services. Fresh snapshot and seven source
  reads checked after actual restart. This does not migrate all observation producers or lane paths.
- Fleet owner/launcher/runtime now execute from C; the new PR176 CLI lifecycle journal recorded real
  start run 728078ed931e4347bf19bd1ca7141b36. Fleet remains paused, no model call. An initial owner
  script had an extra closing parenthesis, failed before startup, was corrected and restarted; keep
  this failure distinct from accepted package behavior. Owner delivery recorded in PG with reference
  sha256:f830a0fd92b815f5d6692a7764161f9b1a097fef4aae0c59793839293c43358c.
- Copied live/r/artifacts, f2h/artifacts and f2i/artifacts to corresponding C roots: 15,226 files,
  248,843,723 bytes. Every copied file was SHA256-compared, no original deleted. Full manifest is
  C:/workspaces/zeus/artifacts/storage-recovery-001/evidence-copy-manifest.json.
- Verified old container exited255, fenced task92b13b20-f8cb-5bb2-9549-fae70c63a164 through Workflow
  cancel (generation1->2), and reclaimed its sole reservation through InvocationLedger.reclaim.
  Usage remains unknown/null; no success fabricated. Machine slot7884c429a6da4ce09e2caea55a4aca3a
  settled as used/interrupted_unknown with preserved count and recovery evidence; ledger stayed home.

Next material constraint: Fleet.register deliberately refuses all changed configurations, including
new C lane repository/runtime paths. Historical interrupted Fleet reservation also retains ownership
even after task cancellation. Existing APIs do not provide an idle relocation/reconciliation
transaction. Do not rewrite registry rows or replace D with a filesystem alias to disguise this.
Before new work, specify and implement an owner-only, evidence-bound recovery/relocation path with
paused admission, exact old config hash, dead process/lease evidence, preserved invocation history,
verified copied artifacts and rollback receipt. Source repository and pending manifest identities
must remain pinned; changed runtime identity must never silently resume the old operation. This is
the current blocking implementation boundary, not missing user permission or a model-call ceiling.

Still pending: lane relocation/Fleet reservation disposition, Audit/Desk and remaining observation
producer path switches, durable staging cleanup feature, successor worker/review, ontology acceptance,
and broader absorption/model-transfer deliveries. No unattended completion claim is made.
