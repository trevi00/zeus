# research-program-001 — runbook

`zeus research-program` connects the existing collectors (`ResearchSources`: GitHub Trending and
GeekNews), owner-authorized local candidates, the durable store and the real `urn:zeus:autonomous:2`
council into one finite, bounded program (INV-RESEARCH-PROGRAM-001). Nothing here merges, deploys,
retries, grants budget or invents goals. Live results are only what the owner run records.

## Commands

```
zeus research-program register --file CONFIG.json   # validate, bind goal + local rows at base, store; no models
zeus research-program resume ID                     # paused -> active (initial state is paused)
zeus research-program run ID --ticks N              # up to N ticks, never beyond max_cycles/interval/deadline
zeus research-program status ID                     # store read only, urn:zeus:research-program-status:1
zeus research-program pause ID                      # block new ticks; an owned cycle finishes
```

`run` must be invoked from the repository the program was registered in: another clone or root is
refused with `repository_mismatch` before any reservation, fetch, capture or model call. A failure
between the capture commit and the council start (stages `capture_record`, `manifest_derive`,
`manifest_artifact`, `manifest_file`, `council_start`) blocks the program with `<stage>:<code>`
and keeps the capture ref; a receipt with `failure.recorded: false` means the store could not
record it and the cycle is still owned (`busy`), to be inspected, never retried blindly.
`run` stops early after a `not_due`, `busy`, `paused`, completed or blocked tick and after any
failed/unknown council. Exit 0 means every tick was recorded without failure/unknown; exit 1 means a
refusal or a blocking outcome (the receipt names it). Refusals print `reason_code` and `error_type`
only.

## Config (`example.json`)

- `base_revision`, `budget` and the template's must be identical; the template is a complete,
  valid `urn:zeus:autonomous:2` manifest (goal bytes verified at base on register).
- `topics[].keywords`: lowercase; relevance is a literal keyword match in bounded title/summary.
- `local_candidates[]`: regular tracked file at base with its exact sha256 (verified on register
  and again every tick). One candidate per path.
- `max_adoptions <= max_cycles`; `interval_seconds` gates ticks (`not_due` costs nothing).
- `example.json` is a shape example: replace the all-zero local sha256 with the real digest at
  base (register refuses `local_source_digest_mismatch` otherwise), set the goal digest/paths of the
  chosen goal document and use `claude` controls the packaged provider policy accepts.
- Re-registering the identical file is cached; any change (or another repository) is refused.
  A revised program needs a new id.

## What one tick does

`reserve (PG) → local verify + both feeds (read-only) → dedup/relevance/claim (PG) →` if selected:
`snapshot → detached capture commit + ref refs/zeus/research/<id>/<cycle> → derived manifest persisted →
council start recorded (PG) → zeus autonomous run (existing CouncilRun) → autonomous_runs row read →
result recorded (PG)`. Then `runtime/research-program/<id>/report.md` and `events.jsonl` are
written. The checkout, index, HEAD and branches are never touched; the capture is reachable only
through the ref and the recorded revision.

## Outcomes

| Result | Meaning | Program |
|---|---|---|
| `accepted` | run row accepted (existing promotion recorded) | continues |
| `rejected` | run row rejected (review/design rejected) | continues; stays rejected |
| `failed` | run row failed/exhausted/expired/needs_*, or refusal before any row | blocked |
| `unknown` | row missing/mismatched/still running after the council returned | blocked |

Blocked and completed programs cannot be resumed; the claim on the candidate is kept as evidence.
Investigate with `status`, the cycle's `council.run_id` via `zeus autonomous status RUN_ID`, the
capture ref and the event log; then authorize a new program if warranted.

## Owner live canary (not executed by the worker)

1. `HARNESS_INTEGRATION=1 python -m pytest tests/test_research_program.py -q -p no:cacheprovider`
   on the PostgreSQL host (the concurrent-claim test runs only there).
2. Register `example.json` adapted to the real base/goal/local rows; `resume`; run
   `run ID --ticks 1` twice (second after the interval, or set a short interval). Record the source
   statuses from `status` verbatim (ok/unavailable per feed), the selection reason, the capture
   revision, the council run id and the result from `zeus autonomous status`.
3. Expected shape: tick 1 selects at most one candidate (local first); tick 2 shows duplicates,
   `adoption_cap_reached` or a second selection only if the cap allows; never more than one
   dispatch per tick; a rejected council remains rejected.
4. Windows focused run plus CI on both platforms are the owner's separate checks.
