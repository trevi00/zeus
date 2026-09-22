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
| `tests/test_fleet_recovery.py`, `tests/test_fleet_relocation.py` | Focused tests (83). |

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
Correction 2 below adds that each row's stated source and destination must PHYSICALLY resolve to
their own root's file at that relative path, so a link cannot lend either side unrelated storage.
Correction 3 below decides that physical question with platform-native path operations on the
components the request actually spelled, and rejects any link component under either root as such.

## Consolidated correction 3 (2026-09-22): platform-native physical containment

The one retained correction-2 issue is corrected here and nothing else. The original completion
matrix in `SPEC.md`, the four accepted correction-1 boundaries, correction 2's ownership principle
and both commands' contracts stand as they were; scheduling identity, the compare-and-swap,
invocation accounting, receipt replay and the alias/rollback equivalence are untouched.

The invalid assumption was that the ownership check could reuse `_relative`/`normalize_path`. Those
casefold on purpose, for scheduling identity - which is not a filesystem rule. The owner EXECUTED
the POSIX case in a network-disabled disposable Linux container with distinct `new/rt` and `new/RT`
directories, `new/rt/artifacts` symlinked to `new/RT/artifacts` and synthetic equal bytes:
`verify_copy_manifest` answered `bound=true` and `ownership=resolved_paths` although
`Path.is_relative_to` proved the escape (`case-repro-001/{repro.py,result.json}`). No production
path was changed and the container was removed.

`_owned_copy` now answers the physical question with concrete, platform-native path operations, and
`normalize_path` itself is unchanged:

* `_declared_parts` takes the components an entry states below its own root with `Path.relative_to`
  - this platform's own rule, case sensitive on POSIX and case insensitive on Windows - so a
  case-distinct sibling is outside the root it claims (`copy_entry_escaped`) and no real path name
  is lowercased anywhere in the check;
* `_own_chain` walks those stated components under the root and inspects each one with `lstat`,
  never following it, so a symlink, junction or other reparse point ANYWHERE below either root is
  `copy_entry_link_refused` - intermediate directory or leaf, source side or destination side, and
  whether or not it happens to escape. That is the already specified no-child-redirection rule
  applied to a link that resolves inside the same root and to a link that points at a contained
  file: a redirected child is not the file this request moves, wherever it points. A component that
  cannot be inspected is `copy_entry_unresolved`; only a destination's own leaf may be absent, and
  the bounded read then keeps its accepted `copy_unreadable`;
* the strictly resolved path must still sit below the strictly resolved root at exactly those
  components, and the two sides must state the same components, compared as paths rather than as
  lowercased text (`copy_entry_escaped`, `copy_entry_unbound`).

Reason codes that changed: a child link, a destination leaf link and a source-side link were
`copy_entry_escaped` under correction 2 and are `copy_entry_link_refused` now, because the link
component itself is the refusal and no longer needs to escape to be one. The result - refused, no
receipt, no registry change - is the same, and `copy_entry_escaped` stays reachable for a name that
is not natively below the root it claims. A root that is itself a link keeps `copy_entry_link_refused`.

What this does NOT establish: no Windows junction or reparse point was created from this checkout,
so the POSIX cases are the executed proof and the owner reruns the retained Windows junction
reproducer AND the Linux `case-repro-001` reproduction at this candidate before cutover; the
case-distinct cases cannot exist on a case-folding filesystem and skip there with that reason; a
reparse point that resolves to its own name (some Windows tags) is refused by construction by the
`lstat` walk but was not executed here; hard links are not reparse points and are not detected; no
host cutover, real interrupted job, PostgreSQL, Docker or production path was executed here; and
hostile concurrent OS-level filesystem mutation between the check and the read remains explicitly
excluded from what path checks can decide.

Pre-fix detection was executed in this checkout by temporarily restoring the correction-2 predicate
in `adapters/fleet_recovery.py` (the casefolded comparison, with `_own_chain` and the native
component checks disabled), running the focused pair, and restoring the corrected code: the four
correction-3 cases (the plain case-distinct sibling, the owner's case-distinct symlink reproduction
and both contained-file child links) DID NOT RAISE at all, and the three correction-2 link cases
still refused with their old reason code. That probe is not in the delivered tree; the focused pair
passes 83 on the restored code. Each new case also carries its own labelled in-test control that
neutralizes `_owned_copy` and asserts the remaining rules answer `verified=1`/`bound=True`, plus the
casefolded predicate answering the declared relative path for the redirection.

## Consolidated correction 2 (2026-09-22): actual filesystem ownership

The one retained correction-3 issue is corrected here and nothing else: the original completion
matrix in `SPEC.md`, the four accepted correction-1 boundaries and both commands' contracts stand
as they were. The invalid assumption was that normalized absolute names establish physical
containment. `verify_copy_manifest` compared names (`normalize_path`) only, so a child junction
`new-runtime/artifacts -> old-runtime/artifacts` gave a destination name below the new root, at the
right relative path, that read back to the declared digest and length because it WAS the source
file - the owner's Windows receipt `link-repro-001/result.json` (`verified=1`, `bound=true`).

`_owned_copy` now decides ownership by concrete resolution, the same principle `isolated_worker`
already applies to its own roots (Python 3.14 `pathlib` separates pure path computation from
`Path.resolve`, read 2026-09-22):

* each move root is resolved, and a root that is itself a link is `copy_entry_link_refused`;
* both ends of every entry are resolved before any byte is counted, and the resolved path must sit
  below its own resolved root at exactly the relative path the request moves - a child link,
  junction or reparse redirection therefore answers `copy_entry_escaped` instead of being followed
  for credit, on the source side as well as the destination side;
* missing, unreadable and looping paths are `copy_entry_unresolved`; a destination whose directory
  chain resolves but whose file was never written keeps its accepted `copy_unreadable`;
* the observation states `copy_manifest.ownership: resolved_paths`, and `check_relocation_proof`
  refuses a `bound` manifest observation without it, so the commit boundary cannot be reached with
  a name-only check.

Consequences the owner should know: a manifest row whose source no longer exists now refuses at
first-time verification (a committed receipt still replays without reading any source), and a copy
that preserved a symlink as a symlink is refused rather than credited - scope the manifest to
regular files, or relocate those paths separately.

What this does NOT establish: no Windows junction was created from this checkout, so the POSIX
symlink cases are the executed proof and the owner's retained Windows reproducer must be rerun at
this candidate before cutover; no host cutover, real interrupted job, PostgreSQL, Docker or
production path was executed here; and hostile concurrent filesystem mutation between the check and
the read is explicitly not excluded.

Each redirection test carries a labelled pre-fix control that neutralizes `_owned_copy` and asserts
the remaining (old) rules answer `verified=1`/`bound=True` for the redirected fixture, so what the
correction changes is visible in the test itself. The two resolution cases (a stated source that
does not exist, a looping destination chain) are refusals whose reason codes are new; pre-fix the
loop case already refused as `copy_unreadable` and the missing source was not checked at all.

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
tests/test_fleet_relocation.py -q -p no:cacheprovider`, 83 passed, 0 skipped on this Linux host;
`python -m ruff check . --no-cache`
clean): the grammars and their refusals, the proof gates, the call-slot binding, the enumerated run
source, the copy-manifest entry rules, the physical ownership rules against real temporary symlinks
and real case-distinct sibling directories, the mixed-case nested copy that verifies and relocates,
the compare-and-swap and idempotency rules, replay and
conflict through the real CLI entrypoints, the path exclusion across A->B->A and A->B->C, and the
relocation filesystem checks against actual temporary Git checkouts, actual copied files and an
actual journal.

NOT verified here, and left to the owner and CI:

* The real interrupted job. This checkout has no Fleet registry, no lane PostgreSQL schema, no
  Docker daemon and no machine call ledger, so the recovery tests replace the lane store, the
  Docker answers and the call ledger with labelled fixtures and injected faults. `LaneReader`'s
  actual PostgreSQL path and `docker_state`'s actual daemon path were never executed.
* Windows behaviour. Every link case skips with its reason where the OS refuses to create a
  symlink, and the case-distinct cases skip where the filesystem folds case; a Windows junction
  expresses the same redirection and needs the same refusal, unexecuted here, so the owner reruns
  the retained junction reproducer at this candidate. Entry-to-move binding is still the existing
  casefolded/separator-normalized `normalize_path`, and so is every scheduling and admission
  comparison; ownership is the platform-native component and resolution check beside it.
* The full test suite was not run from this worker (the frame limits it to the two focused files).
* The pre-fix behaviour was not re-executed from a second checkout: this host denies ad-hoc
  interpreter and file-copy commands, so the old code could not be restored in a disposable copy.
  Correction 3's probe was therefore run by temporarily restoring the old predicate in this tree and
  then removing it (see that section for what it showed). Each correction also carries a labelled
  control assertion inside its own test - the unrelated
  settled slot that the id alone would have accepted, `run_records` answering `[]` for the removed
  root, `_hash_file` answering `None` beside the entry's null digest, the raw receipt edges
  resolving A and B differently, and the redirected copies that the rules without `_owned_copy`
  still count as verified - so what the correction changes is visible in the test itself.
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
   unreadable one refuses rather than reading as an idle lane. Both ends of every row must be
   reachable ordinary files of their own root at the stated relative path: a stated source that D
   can no longer read refuses at first-time verification, and so does any symlink, junction or
   other reparse point at any component below either root, including one that stays inside the
   root. Spell each row's path the way the filesystem holds it; nothing is casefolded here.
4. Re-register nothing: the old configuration is now `registration_conflict` by design, and the new
   one is idempotent. Resume only after the owner accepts the receipts.
