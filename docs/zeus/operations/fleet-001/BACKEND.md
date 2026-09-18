# Fleet 001 — backend lane notes

Frame: SPEC.md (unchanged). Contract: INV-FLEET-001 in docs/contracts.md. Disposition: reuse.
`Operation`/`zeus operate run` (child process), `validate_manifest`, `bind_goal`/`GitSource`,
`PostgresStore.transaction` (advisory lock 734219 serializes admission), `CallBudget.counts`,
`load_isolation`, the monitor envelope sampler and the generic `documents` store buckets are reused.
No DDL: `fleet_registry`, `fleet_control` and `fleet_jobs` are buckets of the existing table.

## Modules and interfaces

- `domain/fleet.py`: `validate_config`, `config_digest`, `sanitized_config`, `validate_job_manifest`,
  `new_job`, `binding`, `select_admission`, `classify_outcome`, `projection` (`urn:zeus:fleet-status:1`).
- `application/fleet.py`: `Fleet.register/enqueue/pause/resume/admit_one/finalize/status/
  reconciliation_required`; `FleetRunner(fleet, launcher).run(once)`; `LaunchRefused`.
- `adapters/fleet_runtime.py`: `lane_dsn` (psycopg.conninfo, `search_path=<schema>`),
  `lane_environment` (both `ZEUS_`/`HARNESS_` aliases; refuses without Docker isolation),
  `verify_lane_schema` (current_schema and provisioned `documents`, never creates), `read_receipt`,
  `LaneLauncher.launch/wait/outcome/budget_exhausted`.
- `adapters/fleet_cli.py` + `cli.py`: `zeus fleet register|enqueue|run|pause|resume|status`.
- `adapters/monitoring.py`: additive `sources.fleet` envelope from the read-only store.

## Invocation examples

```
zeus --repository C:\Users\rudtn\zeus fleet register --file D:\workspaces\zeus\fleet.json
zeus --repository C:\Users\rudtn\zeus fleet enqueue --lane experience --file D:\workspaces\zeus\jobs\op-a.json
zeus --repository C:\Users\rudtn\zeus fleet enqueue --lane visual --file D:\workspaces\zeus\jobs\op-b.json --after op-a
zeus --repository C:\Users\rudtn\zeus fleet run --once
zeus --repository C:\Users\rudtn\zeus fleet pause
zeus --repository C:\Users\rudtn\zeus fleet status
```

Fleet file (`urn:zeus:fleet:1`): `{schema,id,max_parallel,budget:{per_host,total},lanes:[{id,team,
repository,schema,redis_namespace,runtime}]}`; paths absolute and already resolved (Windows
backslashes as printed by `Path.resolve()`), runtime roots distinct, not nested, outside repositories.
Job manifests are ordinary `urn:zeus:operation:1|2` files whose `budget` equals the fleet budget.

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

Executed here: `python -m pytest tests/test_fleet.py tests/test_fleet_runtime.py -q -p no:cacheprovider`
and `python -m ruff check .`. Tests use MemoryStore, a real subprocess of a labeled stub script
(argv/env/cwd/exit observed), injected fake PostgreSQL connections and fixture launchers; none is
a real `operate run`, model call or PostgreSQL schema. Not run by this worker: full suite, real
PG lane schemas, Docker isolation preflight, model canary, Windows CI.

Known follow-up outside allowed paths: `tests/test_monitoring.py` asserts three sources
(`test_collect_keeps_source_failures_independent`) and four `source_state` journal events
(`test_collector_entrypoint_is_read_only_and_needs_no_executor`); the additive `fleet` source
makes those four and five. Owner decision: update those two assertions.
Graceful stop uses SIGINT/SIGTERM (SIGBREAK on Windows); children run in their own session or
process group and are never signalled. A hard crash leaves `dispatching` rows for reconciliation.
