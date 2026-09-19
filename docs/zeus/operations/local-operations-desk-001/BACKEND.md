# Backend B — what is implemented and what stays unknown

Base 35749fd; completion of the preserved draft 39c69cd, to be reviewed whole against e67842a.

## Path
Browser POST -> `adapters/frontdesk_http` gates -> `FrontDesk` (one PG transaction persists the user
turn AND the six-W outbox assignment) -> `zeus desk run` claims one turn as `dispatching` -> scoped
flush -> `lead:frontdesk` -> `Workflow.handle` -> guarded `Executor.execute_one` -> read-only
`execute_frontdesk` at the request base, one handoff -> flush -> durable terminal turn.

## Completion batch
1. Monitoring evidence. `execute_frontdesk` defaults its snapshot to `monitoring_evidence()`: the
owner runtime `monitoring.json`, sanitized to capture time, age and `current`/`stale` freshness,
per-source status/error type, fleet registration/pause/accounting mode and lane-job counters, and
pending termination/alert counters kept apart from the historical sample. No path, goal text,
ceiling number, credential or raw log leaves it. Missing, oversized, unreadable, malformed or
undated captures are explicit `unknown`; the read never raises and never fails a turn.
Contradictory or invalid explicit accounting modes are `unknown`, never silently finite.
2. Per-turn accounting receipt (`desk_receipts`), written after the call and before the terminal
status, recording ONLY the slots that call created, their settlement, the bound task and whether the
result publication completed; earlier turns' slots cannot contaminate a later outcome. Restart
finalizes a `dispatching` turn only with a bound succeeded task, a receipt proving settlement and
publication for THAT task, and a complete scoped flush now; anything else is `needs_reconciliation`
with no provider call. A crash between settlement and receipt stays unknown. The ledger is only read.
3. Loop and cleanup. Observations are collected after recovery and every turn (counts, or the
failure's exception type). The summary keeps the newest 50 turns plus counts and reports omissions.
A dispatch exception ends the turn as `needs_reconciliation` when storage works; a failed terminal
write leaves the turn `dispatching` for the next startup and stops the process without retry. The
desk observer and host lock are released even when the wiring fails.

## Not proven here
No provider ran in these tests; injected executors, buses and collectors are labelled injected. Real
browser -> Redis -> PG -> Codex -> response, refresh persistence, full CI and the owner delivery
record of actual #157 facts remain owner work. Verified here: `python -m pytest tests/test_frontdesk.py
tests/test_frontdesk_http.py tests/test_fleet_delivery.py` and `python -m ruff check .`; not the suite.
