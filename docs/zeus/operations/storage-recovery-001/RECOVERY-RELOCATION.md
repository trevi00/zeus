# Recovery/relocation implementation — delivered code and what it does not prove

Implements the "Recovery/relocation implementation handoff" section of `SPEC.md` and nothing else.
No staging cleanup, ontology, model routing, generic migration framework or live recovery is
included here, and no host cutover was performed from this checkout.

## What was added

| File | Change |
| --- | --- |
| `domain/fleet_recovery.py` | New. Evidence/request/proof/receipt grammar and the two policy gates. |
| `domain/fleet.py` | `resolve_repository`; `blocking_reason`/`select_admission` take an optional alias map. |
| `application/fleet.py` | `Fleet.reconcile_interrupted`, `Fleet.recovery`, `Fleet.relocate`, `Fleet.relocations`, alias folding in `admit_one`; buckets `fleet_recovery_receipts`, `fleet_relocations`. |
| `adapters/fleet_recovery.py` | New. Lane reads, run-record and Docker state reads, journal read, checkout identity, copy-manifest verification. |
| `adapters/fleet_cli.py` | `fleet reconcile-interrupted --file [--docker]`, `fleet relocate --file --journal [--docker]`. |
| `docs/contracts.md` | INV-FLEET-001 extended with both operations. |
| `tests/test_fleet_recovery.py`, `tests/test_fleet_relocation.py` | Focused tests (70). |

Existing owners were reused rather than duplicated: `validate_config` decides the new lane paths,
`operation_finalization.owner` decides the lane operation association and its `_lease_live` decides
lease liveness, `isolated_worker.run_records`/`_docker` read the retained runs and container state,
`service_entry`'s journal answers whether the runner stopped, `operation_cli.GitSource` reads the
pinned base and goal bytes, and `CallBudget` answers for the machine slot. The machine ledger, the
lane schemas, the Redis namespaces, the budgets and the provider authority are untouched.

## Documents the owner supplies

* `urn:zeus:fleet-recovery-evidence:1` — job id, operator, expected status/owner token/lane/
  registered config digest, lane operation id + `operation:<id>` correlation + task id + advanced
  generation, container run id/role/name/id, invocation reservation id + closed status, machine
  slot id + outcome, timezone-aware `recorded_at`.
* `urn:zeus:fleet-relocation:1` — fleet id, operator, expected config digest, `moves[]` of
  `{lane, repository: {from,to}|null, runtime: {from,to}|null}`, `copy_manifest` of
  `{path, sha256, entries}`, `recorded_at`. The manifest file itself is
  `urn:zeus:copy-manifest:1` with `entries[] = {source, destination, sha256, bytes}`.

`fleet relocate` also needs `--journal`, the service lifecycle journal of the Fleet CLI. It is
required: an absent or unreadable journal is `runner_state_unknown`, not an assumed idle host.

The copy manifest is read as evidence about THIS cutover, so each `entries[]` row must be a file
below a path the request moves, at the same relative path below the stated source, with a non-null
sha256 and byte length that the destination actually reads back to. An entry that is elsewhere, a
duplicate, a renamed destination or a missing file refuses, and a moving runtime target with no
entry at all is `copy_manifest_incomplete`. A manifest of copies made for another purpose therefore
cannot certify this move; scope the manifest to the paths being moved, or relocate them separately.

## Consolidated correction 1 (2026-09-22)

The five findings the owner raised against candidate 09cf363 are corrected here, and nothing else
changed: the original completion matrix in `SPEC.md`, the prior accepted behaviour and the two
commands' contracts stand as they were.

1. `_machine_slot` now binds the named call slot to the operation through records the host wrote
   itself - the ledger slot's own `purpose` (`operation:<id>:<kind>`) or the lane `operations`
   row's recorded `calls.slots[]`, agreeing on the provider where both exist. A purpose naming
   other work is `machine_slot_foreign`; a legacy row with neither record is `machine_slot_unbound`;
   the policy gate refuses an observation that states no binding. The ledger fixture now holds an
   unrelated settled slot of other work beside this operation's slot, because the two are
   indistinguishable by id.
2. `_active_runs` reads through `listed_runs`, which refuses `lane_runtime_unavailable`,
   `lane_runs_unavailable` or `lane_runs_unreadable` instead of consuming a missing or unreadable
   run root as zero, and counts zero only for a root that was enumerated and is genuinely empty.
   No missing source is created.
3. `verify_copy_manifest` no longer credits `None == None`: entry types, a non-null sha256, a byte
   length, absolute resolved paths, containment in a moved pair with matching relative path, no
   duplicate, a bounded read back to that digest and length, and coverage of every moving runtime.
4. Repeated moves and rollbacks fold into one equivalence class per repository
   (`canonical_repositories`), so A->B->A and A->B->C answer the same canonical identity from
   either side and the cross-lane path exclusion against old frozen jobs survives both.
5. Both CLI commands take the observation as a callback. `Fleet.reconcile_interrupted` and
   `Fleet.relocate` consult the committed receipt first, so an identical replay returns the exact
   receipt without reading a lane schema, a container, a journal, a checkout or a copied file, and
   a conflicting request for the same identity refuses there.

What that correction does NOT establish is unchanged from the section below: no host cutover, no
real interrupted job, no PostgreSQL, Docker or Windows path was executed from this checkout, and
the operation's earlier `lead_rejected` outcome is not reversed by these tests passing.

## What is verified here, and what is not

Verified by the focused tests in this checkout (`python -m pytest tests/test_fleet_recovery.py
tests/test_fleet_relocation.py -q -p no:cacheprovider`, 70 passed; `python -m ruff check . --no-cache`
clean): the grammars and their refusals, the proof gates, the call-slot binding, the enumerated run
source, the copy-manifest entry rules, the compare-and-swap and idempotency rules, replay and
conflict through the real CLI entrypoints, the path exclusion across A->B->A and A->B->C, and the
relocation filesystem checks against actual temporary Git checkouts, actual copied files and an
actual journal.

NOT verified here, and left to the owner and CI:

* The real interrupted job. This checkout has no Fleet registry, no lane PostgreSQL schema, no
  Docker daemon and no machine call ledger, so the recovery tests replace the lane store, the
  Docker answers and the call ledger with labelled fixtures and injected faults. `LaneReader`'s
  actual PostgreSQL path and `docker_state`'s actual daemon path were never executed.
* Windows behaviour. The symlink escape case skips with its reason where the OS refuses to create
  a symlink; a Windows junction expresses the same escape and needs the same refusal, unexecuted
  here. Path comparison is the existing casefolded/separator-normalized `normalize_path`.
* The full test suite was not run from this worker (the frame limits it to the two focused files).
* The pre-fix behaviour was not re-executed from a second checkout: this host denies ad-hoc
  interpreter and file-copy commands, so the old code could not be restored in a disposable copy.
  Each correction instead carries a labelled control assertion inside its own test - the unrelated
  settled slot that the id alone would have accepted, `run_records` answering `[]` for the removed
  root, `_hash_file` answering `None` beside the entry's null digest, and the raw receipt edges
  resolving A and B differently - so what the correction changes is visible in the test itself.
* The cutover itself. Copying is the owner's preparation step; these commands move, delete and
  rewrite nothing, and a successful relocation is a registry change plus a receipt, not evidence
  that the new paths have executed work.

## Ordering for the owner

1. `fleet pause` (already paused) and stop the Fleet runner so its journal shows an `exit`.
2. `fleet reconcile-interrupted --file <evidence>` for the fenced job. This settles it `failed`
   with `interrupted_unknown`; the unknown usage and the whole history stay as they are.
3. `fleet relocate --file <request> --journal <journal>` once the copies are verified. The manifest
   must cover the moving runtime targets and nothing outside the stated moves, and each moving
   lane's current `<runtime>/isolated-worker/runs` root must be present and readable - an
   unreadable one refuses rather than reading as an idle lane.
4. Re-register nothing: the old configuration is now `registration_conflict` by design, and the new
   one is idempotent. Resume only after the owner accepts the receipts.
