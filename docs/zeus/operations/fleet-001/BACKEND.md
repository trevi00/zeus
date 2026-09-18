# Fleet 001 — backend lane notes

Frame: SPEC.md (unchanged). Contract: INV-FLEET-001 in docs/contracts.md. Disposition: reuse.
`Operation`/`zeus operate run` (child process), `validate_manifest`, `bind_goal`/`GitSource`,
`PostgresStore.transaction` (advisory lock 734219 serializes admission), `CallBudget.counts`,
`load_isolation`, the monitor envelope sampler and the generic `documents` store buckets are reused.
No DDL: `fleet_registry`, `fleet_control`, `fleet_jobs` and `fleet_budget_grants` are buckets of the
existing table.

## Modules and interfaces

- `domain/fleet.py`: `validate_config`, `config_digest`, `sanitized_config`, `effective_config`,
  `validate_grant`, `validate_job_manifest`, `new_job`, `binding`, `select_admission`,
  `classify_outcome`, `projection` (`urn:zeus:fleet-status:1`).
- `application/fleet.py`: `Fleet.register/registered/enqueue/pause/resume/authorize_budget/
  budget_grants/admit_one/finalize/status/reconciliation_required`; `FleetRunner(fleet,
  launcher).run(once)`; `LaunchRefused`.
- `adapters/fleet_runtime.py`: `lane_dsn` (psycopg.conninfo, `search_path=<schema>`),
  `lane_environment` (both `ZEUS_`/`HARNESS_` aliases; refuses without Docker isolation),
  `verify_lane_schema` (current_schema and provisioned `documents`, never creates), `read_receipt`,
  `LaneLauncher.launch/wait/outcome/budget_exhausted`.
- `adapters/fleet_cli.py` + `cli.py`: `zeus fleet register|enqueue|run|pause|resume|authorize-budget|status`.
- `adapters/monitoring.py`: additive `sources.fleet` envelope from the read-only store.

## Invocation examples

```
zeus --repository C:\Users\rudtn\zeus fleet register --file D:\workspaces\zeus\fleet.json
zeus --repository C:\Users\rudtn\zeus fleet enqueue --lane experience --file D:\workspaces\zeus\jobs\op-a.json
zeus --repository C:\Users\rudtn\zeus fleet enqueue --lane visual --file D:\workspaces\zeus\jobs\op-b.json --after op-a
zeus --repository C:\Users\rudtn\zeus fleet run --once
zeus --repository C:\Users\rudtn\zeus fleet pause
zeus --repository C:\Users\rudtn\zeus fleet status
zeus --repository C:\Users\rudtn\zeus fleet authorize-budget --per-host 4 --total 12 --expected-total 8
```

Fleet file (`urn:zeus:fleet:1`): `{schema,id,max_parallel,budget:{per_host,total},lanes:[{id,team,
repository,schema,redis_namespace,runtime}]}`; paths absolute and already resolved (Windows
backslashes as printed by `Path.resolve()`), runtime roots distinct, not nested, outside repositories.
Job manifests are ordinary `urn:zeus:operation:1|2` files whose `budget` equals the *effective*
fleet budget (the registered one until a grant).

## Queued reasons (correction 1)

`admit_one` persists every observed blocking reason on its queued job inside the same admission
transaction: `paused`, `budget_exhausted`, `budget_stale`, `capacity`, `lane_busy`,
`dependency_missing|waiting|rejected|failed|exhausted|unknown`, `path_conflict`. A row and its
`updated_at` change only when the recorded reason differs from the observed one, so a repeated poll
is not a heartbeat; the claimed job's reason is cleared (`null`) at admission. Precedence is the
reviewed one: pause, then ledger exhaustion, then fleet capacity, then the job's own facts. So a job
that waited on a `path_conflict` is re-recorded as `capacity` once every slot is held, and a queued
job that is admissible but not first in age shows `capacity` until the next admission call. The
reasons survive `fleet status` and the monitor envelope unchanged.

## Effective budget and operator grant (correction 3)

The registered config and its digest in `fleet_registry` are immutable. `fleet_control.admission`
holds `{paused, budget, updated_at}`; `budget` is the effective ceiling (registration seeds it, an
older row without it means the registered ceilings). `pause`/`resume` rewrite only the flag.
`zeus fleet authorize-budget --per-host N --total N --expected-total OLD` is the only ceiling change
and is invoked by the operator alone, never by the dispatcher or a model run. In one store
transaction it requires: registered fleet; `--expected-total` equal to the current effective total
(`budget_expected_mismatch`, so two competing grants cannot both apply); valid ceilings
(`config_invalid`), nondecreasing (`budget_decrease`) with at least one increase
(`budget_no_increase`); and no `queued`, `dispatching` or `unknown` job (`fleet_not_idle`): queued
work carries frozen ceilings and reserving work still owns the machine ledger. It then writes the
control budget beside the untouched pause flag (no automatic resume) and an immutable
`fleet_budget_grants` record `{id,fleet,config_sha256,prior,budget,expected_total,granted_at}`.
`registered()`, `status` and the monitor `budget` show the effective ceilings; `enqueue` validates
manifests against them (`budget_mismatch` for a manifest with the old ceilings); admission blocks a
queued job whose frozen manifest budget differs from the effective one (`budget_stale`, a guard for
a control row changed outside the CLI grant). `FleetRunner` re-reads the effective config before
every admission scan, so a grant made while the service sleeps applies to its next scan. The same
original `register` stays idempotent (`cached`) and cannot undo a grant; a register file with the new
ceilings is `registration_conflict`. Historical jobs, their manifests and the machine ledger stay
unchanged; the machine `CallBudget` still decides actual provider starts.

Child: `<sys.executable> -m codex_harness.cli --repository <lane repo> operate run --file
<lane runtime>/fleet/<job id>/operation.json`, cwd the lane repository, stdout/stderr to
`stdout.log`/`stderr.log` beside the manifest (never stored in PG). The child inherits the host
settings (Docker isolation, executable, token name) and the machine CallBudget at its default
home path; the fleet only counts that ledger before admitting and never reserves or resets it.

## States and boundaries

queued -> dispatching (durable, owner token, before spawn) -> accepted | rejected | failed |
exhausted | unknown. `accepted` = child exit 0 AND lane `operations` row with this operation id,
manifest digest and status accepted (review accepted, not merged). Reason codes: `child_refused`
(nonzero exit, no row), `receipt_missing`, `receipt_mismatch`, `exit_contradicts_receipt`,
`lane_read_uncertain`, `lane_operation_not_terminal`, `spawn_uncertain`, `outcome_uncertain`,
`isolation_required`, `lane_schema_mismatch`, `lane_schema_unprovisioned`, `lane_unavailable`,
`runtime_unwritable`, `spawn_failed`. `unknown` and `dispatching` keep the lane, capacity slot and
path exclusion; `fleet status` lists them as `reconciliation_required`; nothing relaunches or clears
them. Pause blocks new admission only. Dependencies must be `accepted`; a rejected/failed/
exhausted/unknown prerequisite blocks only its dependents. Bases stay fixed: no rebase onto candidates.

## Verification and limits

Executed for the correction (Linux worker, base 602edd2):
`python -m pytest tests/test_fleet.py tests/test_fleet_runtime.py tests/test_monitoring.py -q -p no:cacheprovider`
(on the base: 2 failed, 30 passed, exactly the two monitor assertions; after: 36 passed) and
`python -m ruff check .` (clean). Tests use MemoryStore, a deterministic ticking clock fixture, a
real subprocess of a labeled stub script (argv/env/cwd/exit observed), injected fake PostgreSQL
connections and fixture launchers; the `budget_stale` test edits the control row directly as a
labeled fixture. None is a real `operate run`, model call or PostgreSQL schema. Not run by this
worker: full suite, real PG lane schemas, Docker isolation preflight, model canary, Windows CI. Not
possible here: running the new tests against the base source in a disposable copy (the sandbox
denied the copy/`git show` command), so "new tests fail on old code" is asserted from the diff, not
observed.

Correction 2 updated exactly the two old monitor assertions (`test_collect_keeps_source_failures_independent`:
four sources, fleet `unavailable` with `data: null` under the broken store;
`test_collector_entrypoint_is_read_only_and_needs_no_executor`: five `source_state` events, fleet
`ok` with the fixed unregistered shape, store unchanged, no executor).
Graceful stop uses SIGINT/SIGTERM (SIGBREAK on Windows); children run in their own session or
process group and are never signalled. A hard crash leaves `dispatching` rows for reconciliation.
