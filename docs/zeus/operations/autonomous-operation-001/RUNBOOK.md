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

## Known boundaries handed to the owner

- The one-shot `zeus fleet backlog tick` command records the durable status and the
  `zeus.fleet.backlog` log line, but builds no observer: the structured events above are emitted by
  the configured continuous runner, which owns a durable process observer.
- `Portfolio.bind` is called by a tick; `Portfolio.accept` is not. A recorded binding says which
  criterion the work was admitted under, never that the criterion is met.
- Runtime activation on the current Windows host, the real PG check and the whole-loop acceptance
  in `SPEC.md` remain owner work.
