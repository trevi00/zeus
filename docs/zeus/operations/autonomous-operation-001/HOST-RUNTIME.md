# Managed host runtime: immutable runtime consumption (opt-in)

Contract for the `Operating-host composition: immutable runtime consumption` batch of
[SPEC.md](SPEC.md). This is a reviewed, testable composition primitive. It does not cut over the
live Fleet, it does not change the current production launcher (`fleet-owner.pyw`, `fleet-entry.py`,
`launch-fleet.ps1`), and it grants no approval. The actual cutover, the live rollback and the
two-item qualification are still owner gates.

## What changes, and what does not

| Area | Behaviour |
|---|---|
| Registry `urn:zeus:host-delivery-targets:1` | New target kind `managed_fleet`. Only this kind accepts the extra owner fields `source`, `python` and `environment_lock`. The `process` and `windows_scheduled_task` kinds keep exactly their five fields and their meaning. |
| Plan `urn:zeus:host-delivery:1` | Unchanged. A plan names a target id, a reviewed revision, an image and a profile. It cannot carry a root, a source, an interpreter, a command or an argv (`plan_fields`). |
| Descriptor `urn:zeus:host-descriptor:1` | Unchanged schema. For a managed target, `root` is `<managed root>/runtimes/<revision>`. It is derived from the registry and the reviewed revision in `resolve_descriptor` and never taken from a plan. |
| Releases, ReleaseQueue, fence, instance authority | Unchanged. Materialization, drain, switch, start and rollback run under the same fence, the same target guard and the same `instance_authority`/`replaces` rules as PR182. |
| `zeus fleet run` | Unchanged. `FleetRunner` and `fleet_cli.run` gain an optional `control`. With `None`, the default, the loop and the summary are exactly as before. |
| Host opt-in | Unchanged. `ZEUS_HOST_DELIVERY_ENABLED` must be set, and a managed target must be registered by the owner. Without both, nothing new runs. |

## Owner registry entry (`managed_fleet`)

| Field | Meaning |
|---|---|
| `root` | The managed root. Sealed runtimes live under `root/runtimes/<revision>`. |
| `state_dir` | Descriptor, receipt, heartbeat, pause and stop files, launch record, launcher journal. |
| `source` | The owner's source repository. Revisions are resolved here with Git. It is also the host configuration root (`.env`) that the child reads, exactly as the unmanaged Fleet reads it today. |
| `python` | The fixed interpreter used for both the trusted launcher and the child. |
| `environment_lock` | sha256 of the `uv.lock` bytes that this interpreter's environment was built and qualified for. |
| `service` | Identity token, as for the other kinds. |

All paths must be absolute. `root`, `state_dir` and `source` must not contain one another
(`target_overlap`). A sealed runtime can therefore never be written into the live checkout, and a
state file can never land inside a sealed runtime.

## Sealed runtime (`urn:zeus:managed-runtime:1`)

`adapters.managed_runtime.Materializer`, called by `HostDelivery` at the `merged` stage before any
drain:

1. Resolves the revision in `source` with `git rev-parse --verify <rev>^{commit}`, and the result
   must equal the revision exactly. Git handles a linked worktree's `commondir` itself, so no
   revision claim is copied without a check.
2. Lists `src`, `pyproject.toml` and `uv.lock` at that revision with `git ls-tree -r`.
   Submodules and symlinks are refused (`runtime_submodule_unsupported`,
   `runtime_entry_unsupported`).
3. Reads every blob with `git cat-file --batch` and checks each against its own Git blob id.
4. Checks `sha256(uv.lock)` against `environment_lock`. This check runs before anything is
   written. A mismatch raises `EnvironmentUnqualified`, and the tick reports the named outage
   `unavailable / environment_unqualified`. Nothing is installed or downloaded.
5. Writes a stage `runtimes/.stage-<revision>-<id>`, makes its files read-only, writes
   `runtime-files.json` (every `[path, blob]`) and `runtime.json` (revision, tree, file count,
   content digest, lock digest), and verifies the stage against them.
6. Seals the stage with a single atomic `os.rename` to `runtimes/<revision>`.

Immutability rules:

- Candidate code is never imported during preparation.
- The source checkout is only read, and its HEAD and status are unchanged.
- An existing directory is revalidated and is never replaced: the same content gives
  `recovered: true`, anything else is refused (`runtime_content_mismatch`, `manifest_schema`).
- A stage that did not seal stays under its name as recovery evidence.
- Nothing is ever deleted, so the predecessor of every switch stays on disk.
- `runtime.json` is the same attestation that the incumbent `runtime_revision` already reads.

Before every launch, and again inside the trusted launcher, the target re-verifies the runtime:

- the descriptor's `root` is exactly the sealed directory of its own revision under this managed
  root (`runtime_path_foreign`);
- the directory is sealed (`runtime_unsealed`);
- the manifest and listing are valid, and every file on disk matches them
  (`runtime_content_mismatch`);
- the manifest revision matches (`runtime_revision_mismatch`) and the lock matches
  (`environment_unqualified`);
- the interpreter exists (`runtime_interpreter_unavailable`);
- the child's effective worker image equals the descriptor's (`runtime_image_mismatch`).

All of this happens before anything on the target is stopped. The profile digest is checked after
launch, from the child's own receipt, by the incumbent `consumption_verdict`.

## Launch chain and loaded identity

1. **Controller.** `ManagedFleetTarget._launch` runs under the target guard. It writes
   `managed-target.json` (the owner registry entry only), starts one trusted launcher hidden and in
   its own group (`no_console_kwargs(process_group=True)`), and records the launch
   (`pid`, `started_at`, `descriptor_sha256`, `manifest_sha256`).
2. **Trusted launcher.** `python -m codex_harness.adapters.managed_runtime launch` runs the
   controller's own code (`PYTHONPATH` = the controller's package root, `cwd` = `state_dir`). It
   revalidates the target entry, the descriptor digest it was launched for, and the sealed runtime.
   It then owns the child through the incumbent `background_service.run_owned` (a job object on
   Windows, a process group on POSIX, and a journal in `launcher-journal.jsonl`). If verification
   fails, it exits `2` and starts nothing.
3. **Child.** `python -m codex_harness.adapters.managed_runtime entry` runs in `cwd` = the sealed
   root, with `PYTHONPATH` = only the sealed `src`, `PYTHONDONTWRITEBYTECODE=1`,
   `PYTHONNOUSERSITE=1` and `ZEUS_REPOSITORY` = `source`. It writes the incumbent startup receipt:
   the module root and runtime root it actually imported, the revision from `runtime.json`, the
   effective image and profile, the instance and the start time. It then runs the workload:
   - `fleet`, the production default: the real existing `fleet_cli.run` with `bootstrap.build()`
     and the managed control;
   - `fixture`: the labelled controlled workload used by the tests.

   The controller chooses the workload. It is never a plan field.

Writing a descriptor is never called consumption. Activation still requires the child's own
receipt to match every bound field, followed by the canary, followed by the `Releases`
compare-and-swap.

## Pause, drain, heartbeat and stop

`FleetRunner(control=...)` works as follows:

- `control.stop_requested()` triggers the existing graceful `stop()`.
- `control.admission_open() == False` skips the backlog tick and new admissions. Owned children are
  still waited for and finalized.
- If the control cannot be read, admission is closed.
- After every pass, the runner reports its heartbeat.

The heartbeat (`urn:zeus:managed-heartbeat:1`, `heartbeat.json`) contains: `instance_id`,
`descriptor_sha256` and `pid` (the same values as the receipt), `at`, `admission`
(`open` / `paused` / `stopping`), `active` (children this runner launched and has not finalized),
and `unresolved` (dispatching or unknown jobs this runner does not own).

`domain.managed_runtime.work_verdict` is the only reader:

| Heartbeat condition | Verdict |
|---|---|
| Missing | `unknown`, `heartbeat_missing` |
| Unreadable or malformed | `unknown`, `heartbeat_unreadable` |
| Not bound to the valid receipt (instance, descriptor, pid) | `unknown`, `heartbeat_mismatched` / `heartbeat_receipt_*` |
| Older than 30 s | `unknown`, `heartbeat_stale` |
| From the future | `unknown`, `heartbeat_future` |
| Owned children | `busy`, `work_active` |
| Unresolved reservations | `busy`, `work_unresolved` |
| Pause not yet acknowledged | `busy`, `pause_unacknowledged` |
| None of the above | `idle` |

Unknown is never idle.

Drain and stop:

- **Drain** writes `pause.json` under the guard and returns
  `drained = (verdict == idle with admission paused)`. An unknown verdict is `unconfirmed`, so the
  coordinator waits and then blocks with `drain_unconfirmed_effects`. The verdict is recorded on
  the intent (`work`) and projected.
- **Stop** pauses, waits within a bound for a paused idle verdict, writes `stop.json`, and waits
  for both the launcher and the child to exit.
  - Active or unknown work refuses the stop (`instance_work_busy` / `instance_work_unknown`), and
    `start` surfaces that code instead of `previous_instance_unconfirmed`.
  - No signal is ever sent, so no owned child is killed.
  - A refused stop leaves admission paused until the delivery proceeds or the owner removes
    `pause.json`.
- **Liveness** of a managed target is the launcher OR the child from the receipt. A child that
  outlives its killed launcher (the documented POSIX limit of `run_owned`) is still running and
  never counts as an absence.

## Rollback

The forward descriptor names the candidate's sealed directory, and its `predecessor` is the digest
of the old descriptor. The old directory is never removed.

Rollback restores that exact descriptor. The start re-verifies the predecessor's sealed content and
launches it, and the incumbent consumption and canary proof then show that the old runtime (its
root, its module root and its revision) is the one running.

If the owner has meanwhile changed `environment_lock` and the predecessor's lock no longer matches,
the restoration refuses with `environment_unqualified`. It does not run old code in an environment
nobody qualified for it.

## Observability

The existing transitions are emitted through the existing `general.delivery_stage_entered`,
`operations.delivery_*` and `development.delivery_check_observed` events. The observation schema,
the event types and their attributes are unchanged.

The read-only status projection (`zeus host-delivery status`, and the monitoring
`host_delivery_facts` source that reads the same projection) now carries two more fields per
delivery, with no paths:

- `runtime`: `revision`, `manifest_sha256`, `files`, `recovered`;
- `work`: `state`, `reason_code`, `active`, `unresolved`, `paused`.

## Acceptance evidence (fixtures labelled; run on Linux/POSIX only)

Tests are in `tests/test_managed_runtime.py` unless noted. The source is a disposable Git repository
built from this checkout's real `src/codex_harness`, with two commits: A, and B, which adds one
labelled comment line. The lockfile is a labelled fixture. GitHub is `FakeGitHub`. The Fleet
workload is the labelled `fixture`: the real `FleetRunner` and control over an in-memory Fleet,
whose jobs are real waiting processes.

| Criterion | Evidence |
|---|---|
| Actual child consumes two different sealed revisions; predecessor retained | `test_forward_activation_consumes_two_sealed_revisions_and_retains_the_predecessor` |
| Clean start, graceful stop, restart; repeated start recognizes the instance | `test_a_clean_start_a_restart_and_a_repeated_start_launch_exactly_once` |
| Bad path, unsealed, image and content/revision refusal before launch | `test_a_bad_runtime_is_refused_before_the_running_instance_is_touched`, `test_a_descriptor_may_name_only_the_sealed_directory_of_its_own_revision` |
| Interruption before seal / lost response after seal | `test_an_interrupted_seal_leaves_named_evidence_and_the_retry_seals_once`, `test_a_lost_materialize_response_is_revalidated_and_projected_without_paths` |
| Interruption around launch (lost start response, killed launcher) | `test_a_clean_start_...` (repeated start), `test_a_child_that_outlives_its_killed_launcher_is_still_running_and_stops_gracefully` |
| No double launch under two owners | `test_two_owners_starting_at_once_launch_a_single_runtime` (plus the incumbent fence tests in `tests/test_host_delivery.py`) |
| Active work prevents stop | `test_active_owned_work_prevents_the_drain_and_the_stop_until_it_finishes`; `tests/test_fleet.py::test_a_paused_runner_admits_nothing_new_while_its_owned_child_finishes` |
| Unavailable heartbeat prevents idle | `test_an_unavailable_heartbeat_prevents_idle_and_the_stop`, `test_an_absent_stale_or_foreign_heartbeat_is_unknown_and_never_idle` |
| Restored predecessor executes its old code after candidate failure | `test_a_failed_candidate_restores_the_predecessor_which_runs_its_old_code` |
| Environment gate is named and writes nothing | `test_an_unqualified_environment_is_a_named_unavailable_gate_before_any_host_change`, `test_an_unresolved_revision_or_unqualified_environment_writes_nothing` |
| Linked worktree | `test_a_linked_worktree_resolves_through_git_and_its_checkout_revision_through_commondir` |
| Legacy modes unchanged | Existing `tests/test_host_delivery.py`, `tests/test_host_delivery_cli.py`, `tests/test_fleet*.py`, `tests/test_background_*.py`; `tests/test_fleet_cli.py::test_fleet_run_without_a_control_is_unchanged` |

Platform claims:

- The process tests are skipped on Windows (`posix_only`). The Windows paths used are the
  incumbent `no_console_kwargs` and `run_owned` job object, which were not exercised by this batch.
- The `fleet` workload (`run_fleet` with `bootstrap.build()`) was not run here, because it needs
  the owner's PostgreSQL and lanes. Only its wiring (`fleet_cli.run(control=...)`) is tested, with
  doubles.

## Owner gates that remain

1. Build and qualify the fixed interpreter environment for the reviewed revision's `uv.lock`, and
   register its digest as `environment_lock`.
2. Register a `managed_fleet` target:
   - `source` = the owner checkout;
   - `root` and `state_dir` outside it;
   - `python` = the fixed interpreter.

   The first revision activated must itself contain `adapters/managed_runtime.py`, because the
   sealed child runs that entry.
3. Stop the current unmanaged Fleet through its own launcher. This batch never touches it. Then
   let the first delivery (`expected_descriptor: null`) start the managed runtime.
4. Verify the real running Fleet, useful model work, and one live rollback. Fixture results are
   not evidence of unattended operation.
