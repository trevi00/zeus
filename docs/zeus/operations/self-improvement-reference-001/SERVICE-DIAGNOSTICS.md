# Fleet lifecycle failure provenance: the service-entry adapter

2026-09-21. Frame: `SPEC.md`, "Safe Fleet lifecycle failure provenance", and
`RESIDUAL-DISPOSITION.md`. Implementation: `src/codex_harness/adapters/service_entry.py`, reusing
the rotating journal of `src/codex_harness/adapters/background_service.py`.

This is operational hardening of one measured gap. It is **not** completed distribution absorption
(that assessment stays deferred in `RESIDUAL-DISPOSITION.md`), and it is **not** a fix or an
explanation of the old Fleet exit 1, whose cause remains unknown.

## The gap

`launch-fleet.ps1` sends the CLI's stdout and stderr to `Out-Null`, and the entry keeps only the
two allow-listed `zeus.fleet.runner` transition messages. An exit 1 therefore arrives with no
exception type, no place in the package, no cause chain and no way to tell one run from the next.
The adapter records those bounded facts in the process itself, before the streams are discarded.

## What it does

```
python -m codex_harness.adapters.service_entry --journal PATH -- CLI_ARGS
```

The arguments after `--` are passed to the existing `codex_harness.cli.main` unchanged, through a
scoped `sys.argv` replacement that is restored however the call ends; `argv[0]` is the fixed string
`zeus`. The CLI runs in this same process, so its own stdout and stderr go exactly where the
launcher already sends them. The adapter itself prints nothing (the single exception is a fixed
usage line on stderr when its own arguments are malformed, which echoes nothing back).

Ownership is unchanged: `background_service.ProcessTree` remains the sole process owner, and this
adapter starts, retries, releases, kills, budgets and configures nothing.

### Exit status

| answer | meaning                                                                         |
|--------|---------------------------------------------------------------------------------|
| child  | the CLI's own `SystemExit` code, preserved exactly, including `0` and `None`     |
| 1      | an uncaught exception, or an exit whose code is not an integer value             |
| 125    | the diagnostics failed; before the start entry, the CLI was never invoked at all |
| 130    | `KeyboardInterrupt`                                                              |

125 takes precedence over the CLI's own number: a run that could not be described durably is never
reported as a success, and never as a plain failure code either. This differs deliberately from
`background_service`, where 124 (unproven tree) outranks everything, because that module owns a
process tree and this one owns nothing.

### The journal

A rotating JSONL file: the owner's own primitive (1 MiB, two backups, `logging` not allowed to
swallow a lost line) under a separate logger name `zeus.service_entry` and a separate typed
allowlist, so the owner's `zeus.background_service` journal keeps its handler, its fields and its
file unchanged. Three entries per run, appended: `start` (before the CLI is called), `finish` (the
outcome of the call), `exit` (the status this process returns). Every entry carries the run's
generated `run_id`, so sequential runs in one file stay separable.

Fields are allowlisted by name *and* shape; anything else a caller passes is dropped, never
sanitized into the file:

- `run_id`, `reason` (closed vocabulary: `ok`, `cli_exit`, `cli_exit_unknown`,
  `uncaught_exception`, `interrupted`, `diagnostics_failed`), `exit_code`, `final_exit_code`;
- `exception`: the name of a **built-in** exception type, or the fixed `unknown`. A class defined
  anywhere else - including one merely *named* `ValueError` - is `unknown`;
- `frames`: at most the eight deepest frames that belong to this installed `codex_harness`
  package, each a package-relative module path (`codex_harness/cli.py`) and an integer line.
  Frames outside the package are omitted, not shortened;
- `cause` (`none`/`present`), `causes` (at most four links, each `kind` `cause`/`context` with its
  own type and frames), `cause_truncated`, `cause_cycle`. `__suppress_context__` is respected and a
  cycle ends the walk instead of being followed.

Never written, anywhere: an exception message or `repr`, its arguments, any local, `argv`, the
environment, a source line, an absolute path, a raw traceback, or any of the CLI's output.

## Owner activation (not performed here)

The worker did not edit any launcher, restart any service, deploy or merge; the adapter is inert
until an owner launcher calls it. `launch-fleet.ps1` lives at
`D:\workspaces\zeus\artifacts\fleet-001\launch-fleet.ps1`, outside this repository, and was not
read or modified from here - diff it before and after the one-line change below.

1. Pause and idle first, per `docs/zeus/operations/fleet-001/RUNBOOK.md`: `fleet pause`, wait for
   every lane `active_job` to be null, then stop the scheduled task `ZeusFleet-run`.
2. In the launcher, change only the CLI invocation. The existing line has the shape

   ```powershell
   & $Python -m zeus fleet run @FleetArgs | Out-Null
   ```

   and becomes

   ```powershell
   & $Python -m codex_harness.adapters.service_entry `
       --journal "D:\workspaces\zeus\artifacts\fleet-001\service-lifecycle.jsonl" `
       -- fleet run @FleetArgs | Out-Null
   ```

   Everything else stays: the same interpreter, working directory, hidden window, in-memory DPAPI
   token in the child environment, the existing `zeus.fleet.runner` logging configuration and the
   launcher's own bounded event lines. `$LASTEXITCODE` still carries the CLI's own code, with the
   125 case above added. The journal path must be on a writable local path the service account
   owns, and one path belongs to one service instance: concurrent owners of a Fleet instance remain
   prohibited by the existing process ownership, not by this file.
3. Restart the task, confirm one run, then read the journal: a healthy start produces `start`,
   and each finished CLI run adds `finish` and `exit`.
4. Keep the launcher diff and its hash in the deployment evidence, as the existing logging
   configuration change did.

### Rollback

Restore the previous invocation line (`& $Python -m zeus fleet run @FleetArgs | Out-Null`) and
restart the task while idle. Nothing else has to be undone: no state, schema, configuration,
service or budget is created by the adapter, and the journal file is an ordinary rotating log that
can be left in place or deleted. A stale journal from a previous activation is never read back by
anything - it is operator evidence only.

## Limits

- It proves **where** an exception left this package, not the root cause. Frames and types are not
  a diagnosis, and the old Fleet exit 1 is not explained by this change.
- It says nothing about processes the CLI itself started, and it does not observe their cleanup.
- It cannot exist for a `SIGKILL`, a power loss, or any failure before the interpreter starts; a
  missing `exit` entry is not evidence about the tree.
- A non-built-in exception type is `unknown` by design: the operator gets a place, not a name.
- The journal is bounded evidence for an operator, not an event stream, not a metric and not an
  input to any automatic decision.

## Checks run for this change (Linux worker, this checkout)

```
python -m pytest tests/test_service_entry.py tests/test_background_service.py -q -p no:cacheprovider
python -m ruff check . --no-cache
```

76 passed, 1 skipped; the skip is the pre-existing Windows-only owner test
(`job-object kill-on-close is a Windows fact`). The full suite and the Windows/cross-platform run
were not executed here and remain owner/CI work. The subprocess tests execute the real module
against the real `codex_harness.cli` with `--help` and an unknown option; no model, PostgreSQL,
Redis or service was involved, and no scheduled task or launcher was touched.
