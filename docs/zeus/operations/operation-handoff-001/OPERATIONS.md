# operation-handoff-001 operations note

`zeus cycle handoff <cycle_id>` prints one JSON document to stdout (INV-CYCLE-HANDOFF-001). It is
the read-only view an operator takes into the next session; it changes nothing and starts nothing.

```
zeus cycle handoff <cycle_id>
zeus cycle handoff <cycle_id> > handoff.json
```

- Needs only the PostgreSQL store from the existing settings. No executor, observer, Redis bus or
  provider is built; it works where `zeus cycle step` would not.
- `authority` is always `observation_only` and `automatic_resume` is always `false`. The document
  never approves, completes, resumes or deploys anything.
- `cycle` is the stored policy row unchanged. `remaining_executions` is display headroom,
  `max(0, max_executions - executions)`; an over-budget residue shows `0` and is not repaired.
- `target_record` is the CURRENT row addressed by `cycle.last_execution`, not a record of what that
  execution did. If the row moved on (rework, supersession, a later attempt), the view shows the
  row as it is now. Historical truth stays in the ledgers and artifacts, not here.
- `availability` values: `none` (no last execution; an `in_flight` marker alone is not one),
  `unsupported_kind` (kind other than task/decision), `missing` (row absent), `correlation_mismatch`
  (row belongs to another correlation; no data shown), `found` (row matches). Non-found records
  carry only availability, kind and id.
- A found record carries status, attempt, generation, phase and selected result metadata:
  candidate base/revision/tree/diff_hash, execution_ref, evidence verdict, and a boolean `accepted`
  for a decision. Absent or malformed metadata is `null`. Task input, prompts, summaries, output,
  raw errors, messages, settings and candidate paths are never emitted. References are recorded
  data, not verified artifacts.
- An unknown cycle fails with `Unknown cycle`; a store failure fails with its own error. There is
  no empty success.

Before continuing a cycle the operator decides explicitly, from the ledgers and the recorded
evidence, whether to run `zeus cycle step`, leave the cycle stopped, or start a new cycle. The
handoff document suggests no next step and does not clear `in_flight`, a stopped reason or a
budget. Unit tests use MemoryStore fixtures; the PostgreSQL measurement on real rows is owned by
the independent reviewer.
