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

## Recovery/relocation implementation handoff

### Consolidated correction 1

Owner inspected candidate 09cf363 and independent review
sha256:2fd9797de386942aa57b4bbea411b7e1ea4dafa0a91b5c9d8b059bbd450d5f13.
The following are reachable static code traces, not owner-executed reproductions. Prior 53 focused,
59 regression, 4 architecture checks and Ruff evidence remain accepted within their scope. Candidate
is carried into this work branch only to correct it; this is NOT release acceptance or deployment.

One correction batch, unchanged original completion matrix:

1. `_machine_slot` only selects supplied ID and returns status/outcome. Independently bind that slot
   to the actual operation task invocation using stored operation call-slot association and ledger
   purpose/provider/model where present, not caller assertions. Legacy incomplete binding refuses.
   Test unrelated settled slot alongside actual reserved slot and valid interrupted legacy evidence.
2. `_active_runs` consumes run_records on a missing root as zero. Verify source ownership evidence
   is readable and directory enumeration succeeded; missing/unavailable is refusal. Distinguish a
   genuinely empty accessible initialized run root. Do not create a missing source just to pass.
3. `verify_copy_manifest` credits None==None for missing destination and null digest. Enforce entry
   types, valid non-null SHA256 and byte lengths, successful bounded file reads, source/destination
   containment and relative-path correspondence to requested moves. Reject duplicate/unbound or
   escaped entries; no unrelated manifest can certify the moved runtime. Source unreadability does
   not erase a previously committed receipt, but first-time verification requires complete proof.
4. A->B->A aliases form a cycle and resolve differently depending on starting identity. Represent
   one canonical repository equivalence across repeated moves/rollback using existing immutable
   relocation receipts; historical jobs and new jobs must share path exclusion. Do not rewrite job
   manifests. Test A->B->A and A->B->C plus cross-lane dispatch exclusion with old frozen jobs.
5. Both CLI commands observe external state before returning existing receipts. Validate request
   identity then consult committed receipt FIRST; identical replay returns exact receipt without
   touching vanished source/container. Conflicting same-ID requests refuse. Test real CLI adapter
   path with external observer that would fail if called, not only application supplied-proof replay.

New tests must distinguish pre-fix failure from passing controls, keep faults labelled, and exercise
the exact owner CLI boundary. Only required focused pytest and Ruff claims go in legacy `tests`;
diagnostic/unavailable commands stay in summary so unrequested broad suites cannot block the defined
evidence gate. Owner will exercise actual Windows/Docker/PG cutover after independent acceptance.
Do not solve unrelated session retirement or change limits/authorization/automatic retries here.

### Status reconciliation — 2026-09-22 08:25 KST

This update supersedes stale current-state cells in the earlier sequencing table; it does not
change feature acceptance. PR176 is merged AND deployed to the C-backed Fleet CLI, with the live
journal and PG delivery receipt recorded above. Monitor collect/web and Fleet launcher/code paths
are on C; registered lane paths and remaining Audit/Desk/observation service migration are pending.
Backup restore, 15,226 artifact copies and interrupted work preservation are complete within their
recorded scope. Task fencing and invocation accounting are complete; Fleet reservation recovery is not.

Actual recovery/relocation operation ended lead_rejected; candidate implementation is not accepted
or deployed. Session-retirement-001 has its own SPEC and candidate
56520f999dda89647e1c34bccfcb04a8121a7147; its operation ended evidence_gate_refused at 02:30 KST:
five claims, two checked, one replay_failed, two not_checked. Independent model review did not run.
No existing Codex sessions have been deleted by this delivery. A failed evidence replay is not yet
an independently established runtime defect; inspect the recorded command/result before correction.

Live monitoring returns seven source reads ok, and Fleet remains paused. These observations do not
establish autonomous recovery or complete project coverage. Portfolio acceptance denominators:
local-absorption 0/3 accepted; sterk-migration 1/3 (project observability); research-improvement 1/3
(recurrence collection). Thus 2/9 registered high-level criteria are accepted, 7 pending. This is
NOT an overall implementation percentage, source-semantic coverage percentage or effort estimate.

Next bounded sequence: (1) consolidate and fix recovery/relocation rejection, verify actual idle
cutover and finish required C service paths; (2) resume preserved feedback correction and verify
failure->owner->successor->review->delivery linkage; (3) finish PG staging/retention and independently
validate session retirement before controlled deletion; (4) accept ontology packaging/PG/browser,
then resume parallel absorption and scoped model qualification. Existing useful source research,
worker isolation, transport, evidence gates and monitor components are retained. Full local/reference
absorption, graphical reports, model qualification and Code Tutor product acceptance are not complete.

The immediate bottleneck is accepted-to-operational delivery and recovery ownership, not another
unbounded reference investigation. Completion is determined by evidence-backed checklist items;
no overall percentage or calendar promise is inferred from elapsed time or test counts.

One bounded batch, Claude implementation and independent Codex review. Add trusted owner CLI
`fleet reconcile-interrupted` and `fleet relocate`, sharing existing Fleet store and contracts.
Neither command calls models, retries, grants budget, resumes admission or records success.

Reconcile accepts an explicit versioned evidence document, expected job owner/config identity and
operator ID. Adapter verifies exact lane operation/task association from stored assignment/cycle,
task cancelled with advanced generation, no live lease, exact owned container record and Docker
inspect stopped state, and matching settled machine invocation slot. Missing/unreadable/ambiguous
proof refuses. A container name supplied without recorded task/run binding is insufficient. Preserve
unknown usage and original operation/history. Under paused Fleet and compare-and-swap on current job
status/owner, record one immutable recovery receipt and terminal interrupted failure, clearing only
that reservation. Identical receipt replay is idempotent, changed evidence conflicts. Cross-store
proof is captured with identities and reread directly before commit; document that this is an
owner-controlled recovery with worker services stopped, not a distributed atomic transaction.

Relocation accepts expected current config hash, exact source->target path map, verified copy
manifest and operator ID. Only lane repository/runtime paths may change; schema, Redis namespace,
lane ID/team, concurrency, budgets and provider authority remain unchanged. Require paused Fleet,
no dispatching/unknown reservations, no running lane executions and the runner stopped for cutover.
Do not trust a user-supplied idle boolean: adapter inspects available host/runtime ownership facts;
if the platform cannot establish them, refuse with a bounded reason. Inspect original adapter and
run records before choosing a supported process check. Keep the contract practical and explicit.

Target repositories must be real independent Git checkouts, include required pinned queued bases
and goal blobs, and match the source identity. Runtime target must be writable and copied evidence
hashes verified. Reject symlink/junction escapes, invalid roots, source/target overlap and differing
destination files. Copying is an owner preparation step; command does not move/delete bulk files.
Write revised registry and immutable migration receipt in one store transaction with expected-hash
CAS. Repeating exact migration returns its receipt, conflicting requests refuse. Do not rewrite
historical manifests, operation identities, provenance paths or artifact content references.
Future jobs use new paths; old operations are never silently resumed with changed runtime identity.

Acceptance adds source failure/unavailable proof, live container/lease, wrong task/slot, duplicate and
concurrent reconciliation, non-idle relocation, stale config, missing queued commit, changed goal,
corrupt copied artifact, target path escape, restart receipt replay and no provider invocation.
Use actual temporary Git/files for filesystem tests and controlled labelled faults for unreachable
Docker/PG. Windows/POSIX capability differences explicit. Existing failed operation is not marked
accepted. No background reaper, schema reset, force flags or direct operator SQL mutation.

Allowed paths: domain/fleet.py, application/fleet.py, adapters/fleet_cli.py, new
adapters/fleet_recovery.py and domain/fleet_recovery.py if needed, focused
tests/test_fleet_recovery.py, tests/test_fleet_relocation.py, docs/contracts.md, and this task folder.
Exact worker checks: python -m pytest tests/test_fleet_recovery.py tests/test_fleet_relocation.py -q -p no:cacheprovider
and python -m ruff check . --no-cache. Full-suite/real host cutover belongs to owner/CI. Legacy tests
answer lists only successful executed focused commands; failures/unrun checks go in summary.

Bootstrap exception: because the old Fleet paths cannot yet be changed by its API, this one repair
operation uses existing `zeus operate run` from C with an existing isolated lane schema and C runtime.
It does not replace registered Fleet configuration or resume it. Original interrupted task is fenced
and call slots accounted before bootstrap. No second dispatcher, raw Claude invocation or bypass of
isolation/evidence/independent review. Record bootstrap identity and result separately from Fleet jobs.
