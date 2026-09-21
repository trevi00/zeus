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
| `tests/test_fleet_recovery.py`, `tests/test_fleet_relocation.py` | Focused tests (53). |

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

## What is verified here, and what is not

Verified by the focused tests in this checkout (`python -m pytest tests/test_fleet_recovery.py
tests/test_fleet_relocation.py -q -p no:cacheprovider`, 53 passed; `python -m ruff check . --no-cache`
clean): the grammars and their refusals, the proof gates, the compare-and-swap and idempotency
rules, replay and conflict, the path-exclusion alias after a move, and the relocation filesystem
checks against actual temporary Git checkouts, actual copied files and an actual journal.

NOT verified here, and left to the owner and CI:

* The real interrupted job. This checkout has no Fleet registry, no lane PostgreSQL schema, no
  Docker daemon and no machine call ledger, so the recovery tests replace the lane store, the
  Docker answers and the call ledger with labelled fixtures and injected faults. `LaneReader`'s
  actual PostgreSQL path and `docker_state`'s actual daemon path were never executed.
* Windows behaviour. The symlink escape case skips with its reason where the OS refuses to create
  a symlink; a Windows junction expresses the same escape and needs the same refusal, unexecuted
  here. Path comparison is the existing casefolded/separator-normalized `normalize_path`.
* The full test suite was not run from this worker (the frame limits it to the two focused files).
* The cutover itself. Copying is the owner's preparation step; these commands move, delete and
  rewrite nothing, and a successful relocation is a registry change plus a receipt, not evidence
  that the new paths have executed work.

## Ordering for the owner

1. `fleet pause` (already paused) and stop the Fleet runner so its journal shows an `exit`.
2. `fleet reconcile-interrupted --file <evidence>` for the fenced job. This settles it `failed`
   with `interrupted_unknown`; the unknown usage and the whole history stay as they are.
3. `fleet relocate --file <request> --journal <journal>` once the copies are verified.
4. Re-register nothing: the old configuration is now `registration_conflict` by design, and the new
   one is idempotent. Resume only after the owner accepts the receipts.
