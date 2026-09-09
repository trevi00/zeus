## Read-only review

### Concrete remaining blocker: the containment path can itself throw on the input it exists to contain

`record` catches `TypeError`/`ValueError`/`AttributeError` — i.e. it expects structurally bad rows — but the very first statement of the handler is `identity = digest(source)` (`execution_notices.py:47-48`), and `digest` → `canonical` → `json.dumps(..., sort_keys=True)` raises `TypeError` on a non-serializable value or mixed-type dict keys inside `row`. For that class of bad actor/source shape the exception escapes `record` entirely. Callers do not catch it: `workflow.py:94-98` and `:102`,`:108`,`:123` only catch `ContractError`, and `block_execution` (`execution_budget.py:56-65`) catches nothing. The escape unwinds the `with store.transaction()` block, rolling back `tx.put(bucket, row['id'], blocked_row)` and every earlier queue row contained in that same pass — the exact outcome the split of `_build` from the writes is meant to guarantee against. The `except` clause's own tuple is the proof this input is considered reachable; the test at `test_execution_notices.py:62-76` only exercises JSON-clean bad values (`[]`, `'invalid-generation'`), so it passes over the gap. Fix belongs in the handler: derive the quarantine key from a defensively coerced projection (or fall back to `digest({'bucket':…, 'task_id': str(row.get('id')), 'reason_code':…})`) and never from the raw row.

Related asymmetry, same lines: notice identity is now deliberately semantic, but the quarantine identity still hashes the whole clock-bearing row. Any re-poll of a row whose `lease_until`/`attempt`/`error` moved produces a fresh `execution_notice_errors` id plus a fresh `events` row, unbounded, and root's rule forbids adding retention deletion — so this must be made semantic rather than swept later.

### Count-related existing tests that now conflate business outbox with notices

These assert on outbox cardinality with no type filter, and the branches they cover now emit `execution.notice`:

- `tests/test_workflow.py:166,170` — `assert not queued and not outbox` in the `inspection_blocked` branch, which `executor.py:563` now notifies. Direct contradiction.
- `tests/test_threshold_reviews.py:71` — `not tx.scan('outbox')` on a blocked/superseded path.
- `tests/test_usage_limit.py:105,139` — `not tx.scan('outbox')` after budget/blocked outcomes.
- `tests/test_executor_research.py:122,169,215` — same `not tx.scan('outbox')` shape.
- `tests/test_ticket_execution.py:107`, `tests/test_research_audits.py:262`.
- Positive counts: `test_core.py:167` (`== 2`), `test_decision_atomicity.py:74` (`releases == outbox == 1`), `test_tickets.py:50`, `test_integration.py:198`.

Each should filter `r['message']['type'] != 'execution.notice'` for the business assertion and, where the transition is state-changing, add an explicit notice-count assertion — otherwise a lost or duplicated notice is invisible and a spurious one reads as a business-message regression.