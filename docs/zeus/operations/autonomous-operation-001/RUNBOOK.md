# Approved backlog admission runbook (batch 1)

Scope: `SPEC.md` batch 1 only - a durable owner-approved backlog feeding the EXISTING Fleet
admission. This closes manual enqueue and manual next-selection for work that is already specified.
It is **not** self-direction, not release readiness and not host activation. Contract:
`docs/contracts.md` INV-FLEET-BACKLOG-001.

## What this batch does and does not do

| Does | Does not |
|---|---|
| Reads an owner-approved plan from Git at an explicit commit | Write, generate or edit a plan |
| Selects one eligible dependency-satisfied item per tick | Invent successors, retries or merges |
| Writes a durable intent, then calls the unchanged `Fleet.enqueue` | Add a second executor, scheduler or launcher |
| Reports accepted / failed / unknown / pending / unlinked distinctly | Treat `accepted` as merged, released or deployed |
| Validates the item's project and criterion against the portfolio | Write a portfolio acceptance or criterion verdict |
| Records the job's goal binding through the owner's `Portfolio.bind` | Rewrite a binding that already names another criterion |

`accepted` in every projection here means **one accepted lane operation**. Merge, release, canary
and the actual running worker identity are batch 3 and remain owner evidence.

## Plan document

`urn:zeus:fleet-backlog:1`, committed in the lane repository:

```json
{
  "schema": "urn:zeus:fleet-backlog:1",
  "plan_id": "plan-1",
  "repository": "<64-hex identity of the lane repository>",
  "enabled": true,
  "items": [
    {"id": "one", "project_id": "research-improvement", "criterion_id": "verified-loop",
     "lane": "a", "manifest_path": "docs/zeus/manifests/one.json",
     "manifest_revision": "<40-hex>", "manifest_sha256": "<64-hex of the manifest bytes>",
     "priority": 10, "dependencies": []}
  ]
}
```

- `repository` is `digest(normalized resolved lane repository path)`; every item's lane must resolve
  to it, so a foreign repository is refused rather than admitted.
- `project_id`/`criterion_id` must exist in the packaged portfolio definitions.
- `manifest_sha256` is the digest of the committed manifest **file bytes**, not of the canonical
  manifest object.
- Lower `priority` is selected first; ties break on the item id.

## Commands

```
zeus fleet backlog register --lane a --revision <40-hex> --path docs/zeus/backlog.json
zeus fleet backlog tick --plan plan-1
zeus fleet backlog status [--plan plan-1]
```

`register` is idempotent for the identical plan at the identical pin. A later registration may add
items and flip `enabled`; it may not move or remove an item that already has a durable intent, and
a refused registration writes nothing. The frozen scope of a selected item is its lane and manifest
pin (`item_pin_changed`) plus its project, criterion and dependency ids (`item_scope_changed`) -
open intents and already accepted jobs alike.

`tick` admits at most one item. Exit 0 for `selected`, `enqueued`, `backlog_exhausted`, `blocked`,
`plan_paused` and `fleet_paused`; exit 1 for `plan_unregistered`, `unavailable`, `refused` and
`conflict`.

## Continuous operation (opt-in, default off)

The runtime default is unchanged. To let the already running dispatcher continue successors without
a chat or an operator invoking `tick`, set the host setting before `zeus fleet run`:

```
ZEUS_FLEET_BACKLOG_PLAN=plan-1
```

`fleet_cli.run` then wires `FleetRunner(..., backlog=backlog_ticker(...))` together with the durable
process observer. The tick runs once per runner cycle, before admission, in its own transactions. A
graceful stop skips it, so a stopping runner admits no new work.

A tick that RETURNS a failure is reported as a failure, not as `ok`:

| Returned outcome | Runner `state` |
|---|---|
| `enqueued`, `selected`, `backlog_exhausted`, `blocked`, `plan_paused`, `fleet_paused` | `ok` |
| `unavailable` (or a raised exception) | `unavailable` |
| `refused`, `conflict`, `plan_unregistered` | `refused` |

The summary carries `{"state", "outcome", "reason_code", "error_type"}`; only a state transition is
logged (one line, never raw exception text), and unrelated admission and finalization keep running.

Unset (or empty) means disabled: nothing selects work by itself and no observer is built.

## Structured observations

The configured loop emits fixed transitions through the existing observation port (identifiers,
codes and counts only - no manifest, objective, goal text, path or exception message):

| Event | When |
|---|---|
| `development.backlog_item_admitted` | one item became one Fleet job (`cached`, `linked`) |
| `operations.backlog_item_refused` | a definite refusal or a conflict of one item |
| `operations.backlog_unavailable` | entering unavailability and exhausting the deferral, not every poll |
| `operations.backlog_recovered` | a previously deferred item was admitted or linked |

## Portfolio linkage of an admitted job

After the enqueue, the tick calls the owner's `Portfolio.bind` for the item's project and criterion,
outside every store transaction. `link_state` is `pending` until that binding exists.

- A pending or refused linkage is **not** a success: it never unlocks a dependent item
  (`dependency_unlinked`) and shows as `complete_binding` with a `counts.unlinked` entry.
- A binding outage leaves the linkage durably pending; a later tick completes it without admitting
  anything twice.
- A job already bound to ANOTHER criterion is `portfolio_binding_conflict` and is never rewritten.
- A binding is not an acceptance. The owner's `portfolio accept` remains the only criterion verdict.

## Outcomes and next actions

| Outcome | Meaning | Next action |
|---|---|---|
| `enqueued` | one item became one Fleet job | `tick` again / let the runner continue |
| `backlog_exhausted` | nothing eligible and nothing blocked | idle (never invented busywork) |
| `blocked` | items exist but wait on dependencies, conflicts or exhausted attempts | owner review |
| `plan_paused` | the committed plan has `enabled: false` | commit an enabled plan and re-register |
| `fleet_paused` | `zeus fleet pause` is in effect | `zeus fleet resume` |
| `unavailable` | the pinned input or the binding owner could not be read (exception type only) | fix Git/store availability; the item is deferred, not lost |
| `refused` | a definite refusal of this item, attempt counted | owner review after two attempts |
| `conflict` | the job id exists under another binding, or the job is bound to another criterion | owner review; nothing is overwritten |
| `plan_unregistered` | no plan under that id | `backlog register` |

## Operating notes

- **Never nest store transactions.** Git reads, manifest validation, goal binding and
  `Fleet.enqueue` all happen outside the selection transaction. `PostgresStore.transaction` takes
  `pg_advisory_xact_lock` per transaction; a nested call deadlocks until `lock_timeout`.
- **Response loss and restart.** The durable intent exists before the enqueue. A restart between
  intent and enqueue resumes that intent before any new item is selected; a restart between enqueue
  and acknowledgement reconciles the already created job. One item is one job, always.
- **One complete identity.** The intent records the whole `domain.fleet.binding` - lane, repository,
  manifest digest, dependencies and every bound goal field - BEFORE the enqueue, and reconciliation
  compares it against the authoritative `fleet_jobs` row (never the `Fleet` projection, which omits
  `repository`). A same-id job with any other binding is a conflict; a crash before the enqueue can
  never adopt a foreign accepted job or unlock its successors.
- **Recovery exhaustion.** Two distinct definite refusals of one item block that item and report it;
  they never retry forever and never weaken a check. Transient unavailability is not an attempt: the
  item is deferred for a bounded doubling number of ticks (1, 2, 4, 8 ...) so an independent eligible
  item keeps being admitted, its intent stays observable and recoverable after a restart, its
  dependents stay blocked, and after five consecutive outages it is blocked for owner review with the
  last reason and exception TYPE preserved.
- **Idle polls write nothing.** Repeated ticks over an exhausted or blocked plan change no row and
  move no timestamp. A deferred item's countdown is a durable transition, not an idle poll.
- **Correcting a blocked or conflicted item.** An item that already has a durable intent cannot be
  re-pinned or removed - that is what keeps a queued manifest from being edited underneath an
  admitted job. The owner's route is a NEW item id with the corrected pin, committed and
  re-registered; the blocked item and its reason stay preserved as history.

## Verification run for this batch

```
python -m pytest tests/test_fleet_backlog.py tests/test_fleet_backlog_cli.py -q -p no:cacheprovider
python -m ruff check . --no-cache
```

`tests/test_fleet_backlog.py` includes one real-PostgreSQL case that SKIPS unless
`HARNESS_INTEGRATION=1`; the owner runs it with an isolated PG schema, together with the existing
Fleet tests and CI. Nothing in this batch establishes release readiness, host activation or
whole-loop completion.

### Git fixture portability (Windows and Linux)

The owner's Windows gate on 2026-09-22 reported six CLI failures that were fixture defects, not
runtime defects: `Path.write_text` emitted the platform separator (28 CRLF in the manifest), the
inherited `core.autocrlf=true` normalized the committed blob back to LF (0 CRLF), and the pin hashed
from the working tree then named bytes no commit held. `load_manifest` refused correctly with
`manifest_pin_mismatch`. **The exact-byte runtime check is unchanged and must stay unchanged.**

Rules for every Git fixture in `tests/test_fleet_backlog_cli.py`:

- Build the document bytes once (`canonical`), `write_bytes` them, and pin the digest of THOSE
  bytes. Never hash a re-read working-tree file and never use `write_text` for a file that is
  committed and pinned.
- Create the disposable repository with `init_repository`, which declares `core.autocrlf=false`,
  `core.eol=lf` and `core.safecrlf=false` **repo-locally**. No test reads or writes global or
  system Git configuration.

Two regressions hold this boundary, both platform-independent:

| Test | What it proves |
|---|---|
| `...pins_the_committed_bytes_under_inherited_git_newline_normalization` | with `core.autocrlf=true` set repo-locally (the reproduced Windows default) the pin equals the blob; the old platform-text-mode write is reproduced in the same repository and is still refused with `manifest_pin_mismatch`; with `Path.write_text` patched to translate newlines, the canonical writer is unaffected |
| `...overrides_an_inherited_global_autocrlf` | a temporary `GIT_CONFIG_GLOBAL` file supplies `autocrlf=true`, and the repository's own `false` wins (SKIPS on a Git that ignores `GIT_CONFIG_GLOBAL`) |

The second regression sets `GIT_CONFIG_GLOBAL` through `monkeypatch` for that test only; it is a
simulation of an inherited value, never a change to the developer's configuration.

### Relocation fixture portability (runtime integration, 2026-09-22)

The merged runtime neighbour check reported two failures in `tests/test_fleet_relocation.py`, both
fixture defects on the same two platform rules. **No runtime rejection, recovery or cleanup policy
changed; only the fixtures did.**

| Observed failure | Cause | Correction |
|---|---|---|
| `runtime_uncovered` refused with `copy_corrupt` where `copy_manifest_incomplete` was expected | the manifest entry pins the committed `docs/GOAL.md` bytes (LF), but the fixture CLONE inherited `core.autocrlf=true` and held CRLF, so `verify_copy_manifest` re-hashed the destination and refused before coverage was counted | `repository` and `clone` declare `NORMALIZATION` (`core.autocrlf=false`, `core.eol=lf`, `core.safecrlf=false`) in each disposable repository's OWN config - `clone` passes it as `--config` so it applies to the initial checkout. Same keys and same rationale as `init_repository` in `tests/test_fleet_backlog_cli.py` |
| `..._replays_a_committed_relocation_without_observing_the_old_paths` never reached its assertion | `shutil.rmtree` on the old checkout: Git writes its loose objects read-only and Windows refuses to unlink a read-only file | `retire(path, aside)` RENAMES the test-owned checkout to a sibling below the same `tmp_path` and asserts the original path is absent. The replay assertions, the `gone` faults on `collect_relocation_proof`/`docker_state` and the journal unlink are unchanged |

A rename proves exactly what the removal was there to prove - the old path no longer answers - and
needs no write permission on the files it moves. Nothing outside the test's own `tmp_path` is
touched, and no production cleanup path is involved.

Two regressions hold this boundary, both platform-independent:

| Test | What it proves |
|---|---|
| `...checkouts_hold_the_committed_goal_bytes_under_inherited_normalization` | a temporary `GIT_CONFIG_GLOBAL` supplies `autocrlf=true`/`eol=crlf`/`safecrlf=true`, the fixture's own settings win, the clone holds the committed goal bytes verbatim and `runtime_uncovered` refuses with `copy_manifest_incomplete`; the labelled control clones the same source with `normalize=False`, observes the CRLF checkout and shows the unchanged pin still refused as `copy_corrupt` (SKIPS on a Git that ignores `GIT_CONFIG_GLOBAL`) |
| `...retiring_a_checkout_does_not_depend_on_deleting_read_only_git_objects` | a real checkout's Git objects are asserted read-only; with `os.unlink` patched to the Windows rule (labelled emulation) `shutil.rmtree` raises `PermissionError` and leaves the tree part-way, on a disposable second repository, while `retire` still makes the original path absent |

Checks executed for this correction, on Linux:

```
python -m pytest tests/test_fleet_relocation.py tests/test_fleet_recovery.py tests/test_fleet_backlog.py tests/test_fleet_backlog_cli.py -q -p no:cacheprovider
python -m ruff check . --no-cache
```

140 passed, 1 skipped (`tests/test_fleet_backlog.py` real-PostgreSQL case, "Integration environment
required"); Ruff passed. `tests/test_fleet_recovery_postgres.py` imports `setup` from
`tests/test_fleet_relocation.py` and therefore inherits the corrected fixture; it needs PostgreSQL
and was NOT run here. The owner repeats the real PG and combined runs, which remain the gate.

## Observing the backlog from the monitor (2026-09-22)

`adapters/monitoring.collect` read `Fleet`, `ResearchProgram` and `Portfolio` but never the
backlog, so a healthy collector could not say why a plan was idle. `fleet_backlog_facts(store)` now
calls the SAME read-only `FleetBacklog.status()` the `zeus fleet backlog status` command uses, and
`collect` adds it as the additive `sources.fleet_backlog` envelope beside the existing ones.

- **Read-only, and it never ticks.** The collector's `ReadOnlyStore` refuses every write anyway;
  the source only scans `fleet_backlog_plans`, `fleet_backlog_intents`, `fleet_jobs` and
  `fleet_control`. Nothing is selected, read from Git, enqueued, bound or written.
- **The envelope is the existing contract.** `{'status', 'observed_at', 'data'}` on success and
  `{'status': 'unavailable', 'observed_at', 'error': '<ExceptionType>', 'data': None}` on failure,
  sampled by the same `ThreadPoolExecutor`, so one failed source never hides another. A store
  outage is `unavailable`, never an empty backlog reported as a healthy read.
- **States stay distinct.** No registered plan is `registered: false` with an empty `plans` list
  (an honest empty read, NOT `unavailable`); per plan, `blocked` (with the per-item reason,
  including `deferred_input_unavailable`), `plan_paused`, `fleet_paused`, `backlog_exhausted`
  (idle) and `conflict` items keep the meanings in the outcome table above.
- **No new route, UI or scheduler.** `monitoring_web` is unchanged: `/api/status` already serves
  the collected snapshot bytes verbatim, so the envelope reaches a reader as-is. `readiness()`
  ignores source names it does not know, so `/ready` is unaffected and still assesses only its
  required and known optional envelopes.
- **What a collected status is not.** It is a selection projection: an `enqueued` item means one
  Fleet job exists, `accepted` means an accepted lane operation, `linked` means a recorded goal
  binding. It is never evidence of active work, review, release or host activation.

Checks executed for this item, on Linux (candidate `b7f2c16aba00050104ed7fc939380b367f6c3ebf`,
preserved and NOT accepted - see the correction section below):

```
python -m pytest tests/test_monitoring.py -q -p no:cacheprovider
python -m ruff check . --no-cache
```

23 passed, no skips; Ruff passed. The new fixture registers a real fleet and two real plans over a
`MemoryStore` and runs real ticks; its loader, its loader outage and the conflicting and orphaned
intent rows are labelled fixtures, and no git, process, provider or model call is made.

Discriminating control: with the one `'fleet_backlog'` entry removed from `collect` again, the same
command reported 4 failed / 19 passed (the two new tests plus the two updated source-set
assertions), so these tests detect the previous behaviour rather than passing either way. The entry
was restored and the run repeated at 23 passed. The control ran in this checkout because the file
tools here are confined to it; it left no other change.

**That scoped run did not cover the changed interface's neighbour, and the item was refused.**
`tests/test_monitoring_observations.py::test_collect_adds_observations_only_with_runtime_and_keeps_other_sources`
asserts the exact set of collector sources and saw the additional `fleet_backlog` name, so it
failed; the file was outside that item's allowed paths. The same run also reported four command
claims beyond the two scoped commands: those whole-suite and historical-Git results are preserved
as diagnostics only and are NOT evidence that anything passed. On replay the whole suite timed out
at 300 s and the historical-Git tests (`tests/test_output_schema.py`) failed because the verifier
snapshot is not a Git repository. Whole CI remains the host owner's gate.

## Monitor evidence-gate correction (2026-09-23)

The first automatically selected job failed `evidence_gate_refused` before independent lead review.
Its candidate is preserved as history and is not accepted; the failed item and its pin stay. This
correction is a new owner-approved item, not a re-opened monitor review, and it changes NO
production code: `adapters/monitoring.py` and `adapters/monitoring_web.py` are byte-unchanged here.

The single material finding was the changed interface's neighbour assertion. `collect` gained the
`fleet_backlog` source, and `test_collect_adds_observations_only_with_runtime_and_keeps_other_sources`
asserts the EXACT source set, so it read the new name as unexpected. The expected set now carries
`fleet_backlog`; the test additionally asserts that the unregistered backlog is the honest `ok`
envelope with `registered: false`, and that `fleet_backlog` still reports `ok` in the same
collection where the `observations` source is injected to fail - one failed source hides no
neighbour.

Checks executed for this correction, on Linux, in this checkout:

```
python -m pytest tests/test_monitoring.py tests/test_monitoring_observations.py -q -p no:cacheprovider
python -m ruff check . --no-cache
```

Before the test change the same pytest command reported 1 failed / 29 passed, the failure being
exactly the source-set assertion above. After it: 30 passed, no skips. Ruff passed.

Discriminating control: with the one `'fleet_backlog'` entry deleted from `collect`, the corrected
neighbour test failed again (the expected name now missing from the collected set), so the updated
assertion detects the absence rather than passing either way. The collector line was restored
verbatim and the scoped run repeated at 30 passed. The control ran in this checkout because the
file tools here are confined to it; it left no other change.

Not run here, by this operation's explicit scope: the whole suite, the historical-Git tests, the
real-PostgreSQL cases and CI. They are the host owner's gate, and nothing above claims them.

## Known boundaries handed to the owner

- The one-shot `zeus fleet backlog tick` command records the durable status and the
  `zeus.fleet.backlog` log line, but builds no observer: the structured events above are emitted by
  the configured continuous runner, which owns a durable process observer.
- `Portfolio.bind` is called by a tick; `Portfolio.accept` is not. A recorded binding says which
  criterion the work was admitted under, never that the criterion is met.
- Runtime activation on the current Windows host, the real PG check and the whole-loop acceptance
  in `SPEC.md` remain owner work.
# Claude worker model selection, 2026-09-23

New operation manifests MUST explicitly set claude.model to claude-opus-5-5, retaining subscription
accounting. Existing admitted manifests are immutable and keep their recorded model. Do not copy
claude-opus-5 from earlier manifests when authoring a successor. Model selection is bound by the
operation manifest, not inherited from the user's ~/.claude/settings.json.

Required CLI minimum is 2.1.280 (official model-config documentation, read 2026-09-23).
CLI-only successor image: sha256:ae070306fb25ccc37d41a73cd0ab0a2b5fdafcfff3914161518918c1932b79c6.
It derives from the accepted df85b10 image, not from the unaccepted host-delivery implementation.
The owner launcher now references this image for its NEXT start. Existing running service/worker
was not interrupted. Before admitting the first Opus 5.5 job, drain current work and restart the
Fleet owner through the existing owned-service procedure; verify its consumed image receipt.
First real run must verify requested/reported model agreement. Offline --version is not that proof.
Build logs, launcher backup and migration receipt: artifacts/autonomous-operation-001/opus55/.
