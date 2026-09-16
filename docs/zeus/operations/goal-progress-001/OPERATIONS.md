# goal-progress-001 operations note

Goal manifests fix the denominator; the local ticket closure chain is the only source of
completion (INV-GOAL-PROGRESS-001). Every command here prints one JSON document to stdout and
grants nothing.

```
zeus goal report <manifest.json>                    > before.json
zeus ticket dispatch <ticket_id> --revision <n> --goal-manifest <manifest.json> --criterion <id>
zeus goal report <manifest.json>                    > after.json
zeus goal compare before.json after.json
```

## Manifest

Tracked JSON in Git, no ledger row or migration:

```json
{"version": 1, "id": "goal-progress-001", "objective": "…", "non_goals": ["…"],
 "criteria": [{"id": "c1", "acceptance": "…", "ticket_id": "ZEUS-…", "revision": 1,
               "content_hash": "<64 lowercase hex>"}]}
```

- Exactly these fields; 1 to 50 criteria; criterion ids and ticket ids are unique.
- `revision` and `content_hash` pin the ticket revision that the criterion means. Take them from
  `zeus ticket show <id>`. If the ticket is revised, the manifest must be revised too; that is a
  new definition with a new `definition_hash`, and old reports are not comparable to it.

## `zeus goal report`

- Needs only the PostgreSQL store. No executor, observer, Redis bus or provider is built; nothing
  is written. Running it twice on an unchanged ledger yields the identical document.
- `authority` is always `observation_only`. Criterion statuses: `pending`, `reopened`, `resolved`,
  `missing`, `stale`, `unverified`. A resolved criterion carries `closure` with the event id,
  packet ref and proof ref of the existing close decision.
- `resolved` requires the real `zeus ticket close` path: verified chain, current closed event at
  the pinned revision, and a matching `ticket_closures` receipt. A GitHub issue marked CLOSED, a
  supporting review, a succeeded task, a merged PR or a green test run never moves a criterion.
- `metrics.completion_ratio` is `resolved / total` over the fixed denominator; `remaining` is
  `total - resolved`. An open ticket means zero completion for its criterion.
- Corrupted or fabricated closure records show as `unverified`; the report does not print the
  records or the reason. Store failures propagate as errors, never as an empty report.

## `zeus goal compare`

- Pure file comparison, no database. Both reports must have the same `goal_id`,
  `definition_hash` and criterion bindings; otherwise the command refuses.
- Output lists `gained` and `regressed` criterion ids and `net_resolved`, derived from the
  criterion statuses in the files, not from their `metrics` blocks. A reopen after a close appears
  as a regression. The comparison is `observation_only` and is not a budget, promotion or merge
  authority.

## Goal-bound dispatch

- `--goal-manifest` and `--criterion` are opt-in and required together. Without them, dispatch
  behaves exactly as before and is not claimed to enforce goal discipline.
- The selected criterion must name the exact ticket id, revision and content hash being dispatched
  and must be `pending` or `reopened`. Anything else (unknown criterion, other ticket, stale
  revision, closed ticket, unverifiable history) refuses inside the dispatch transaction before
  any outbox, task or dispatch write.
- The plan message and the returned dispatch carry `goal_binding` (goal id, definition hash,
  criterion id). Its dispatch id differs from an unbound or other-goal dispatch of the same
  ticket, so an earlier unbound dispatch cannot suppress the binding. Repeating the same
  goal-bound dispatch returns the stored record.
- Only plan dispatch is bound. Autonomous selection, merge, deploy and provider budgets are
  unchanged and out of scope.

## Verification scope

Worker verification for this operation is `python -m pytest tests/test_goal_progress.py
tests/test_tickets.py -q` and `python -m ruff check .`. The lifecycle fixture signs with a
test-only key; its closures demonstrate record shape, not human or product acceptance. The full
PostgreSQL/Redis suite and CI belong to the owner.
