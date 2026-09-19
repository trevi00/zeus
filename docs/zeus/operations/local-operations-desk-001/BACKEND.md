# Backend B — what is implemented and what stays unknown

Base 35749fd with draft 39c69cd, plus the consolidated evidence/exit repair (git reads unavailable).

## Path
Browser POST -> `adapters/frontdesk_http` gates -> `FrontDesk` (one PG transaction persists the user
turn AND its six-W outbox assignment) -> `zeus desk run` claims one turn as `dispatching` -> scoped
flush -> `lead:frontdesk` -> `Workflow.handle` -> guarded `Executor.execute_one` -> read-only
`execute_frontdesk` at the request base, one handoff -> flush -> durable terminal turn.

## Completion batch
1. Monitoring evidence. `execute_frontdesk` defaults its snapshot to `monitoring_evidence()`: the
owner runtime `monitoring.json`, sanitized to capture time, freshness, per-source `observed_at` age,
fleet registration/pause/accounting mode and counters kept apart from the historical sample; no path,
goal text, ceiling number or raw log leaves it. Bounded read, strict parse and 20 s/future-tolerance
freshness are the accepted `monitoring_readiness` rules, so a stale capture is never `current` and is
retained only as explicit history. Schema and nested containers are checked: missing, oversized,
unreadable, malformed or undated captures are `unknown`, a malformed container is unknown rather than
zero, and the read never raises. Contradictory, invalid or explicitly null modes are `unknown`; only
a confirmed subscription gets the subscription explanation, finite says its ceiling applies, unknown claims none.
2. Per-turn accounting receipt (`desk_receipts`) is written after the call and before the terminal
status with ONLY the slots that call created, their settlement, the bound task and whether the result
was published, so an earlier turn cannot contaminate it. Restart finalizes a `dispatching` turn only
on a bound succeeded task, a receipt proving THAT task and a complete scoped flush now; anything else
is `needs_reconciliation` with no provider call. A crash before the receipt stays unknown.
3. Loop and cleanup. Observations are collected after recovery and every turn; the summary keeps the
newest 50 turns, counts and omissions. A dispatch exception is `needs_reconciliation` when storage
works; a failed terminal write leaves the turn `dispatching`, stops the process without retry, is a
durable `failure` outside that bounded list and exits `zeus desk run` nonzero, while an idle `--once`
run and a graceful interrupt stay 0. Observer and host lock are released even when wiring fails.

## Not proven here
No provider ran; injected executors, buses, collectors and storage failures are labelled injected.
Real browser -> Redis -> PG -> Codex -> response, refresh persistence, full CI and the owner delivery
record of #157 remain owner work. Verified: `python -m pytest tests/test_frontdesk.py tests/test_frontdesk_http.py tests/test_fleet_delivery.py` and `python -m ruff check .`; not the suite.
