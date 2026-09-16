# autonomous run / status

`zeus autonomous run --file MANIFEST` takes one pinned goal through SSOT research, an immutable packet,
proposer -> attacker -> arbiter as independent executor tasks, the existing Operation v2
implementation/review and one same-transaction promotion (INV-AUTONOMOUS-001). `zeus autonomous
status ID` reads the store only. Framework construction only: no model was called by the worker that
built it, and fixtures in `tests/test_autonomous.py` are labelled fault injection, not the canary.

## Manifest (`urn:zeus:autonomous:1`)

The operation manifest fields (`id`, `base_revision`, `goal`, `plan`, `budget`, `claude`) plus:

```json
"deadline": "2026-09-30T00:00:00+00:00",
"research": {"topic": "runbook note", "questions": ["where is the runbook?"], "search_scope": ["docs"]}
```

The operator supplies goal, criteria and allowed paths only. Role answers, packets and debate events
are produced by the role executions; `dge submit` refuses an autonomous-owned session (`session_owned`).

## Flow and fixed limits

1. Claim `autonomous_runs/<id>` (same terminal request replays; changed config `configuration_mismatch`;
   in-flight owner `running_residue`; preexisting session or operation `residue`; passed deadline
   `deadline_expired`). Every later write records the expected prior stage (`run_state_changed`).
2. Researcher, proposer, attacker, arbiter: conductor -> `lead:<role>` `task.assign` with action
   `dge_role` through the outbox, bus delivery to that lead, claimed by `Executor.execute_one` under
   the machine `CallBudget`, executed read-only in a clean detached checkout at base with one provider
   entry (no handoff retry). The answer is bound to the persisted task row (agent, correlation,
   action, role, base, execution_ref, generation, attempt) or the run stops (`role_task_*`).
3. The researcher output becomes the packet through the existing validator plus Git source
   verification; `needs_user` stops as `needs_user`. One round only: `revise` ends `exhausted`.
4. Critical attacker findings need trigger, impact and mitigation; otherwise refused. Minor findings
   never block. Arbiter dispositions follow the existing DGE rules.
5. Approved design launches `Operation.run` with the `.impl` v2 manifest (start cap six in total).
6. Promotion re-reads the accepted operation, the succeeded worker task, the accepted `review_lead`
   decision for the same candidate revision, the all_checked inspection row and the owned session
   inside the transaction that writes `verified:<run>` nodes/edges and the `promotions` receipt.
   Identical retry is idempotent; a different graph is `promotion_conflict`.

Legacy `operate` v1/v2 stays manual maintenance; it is never a fallback for an autonomous failure.

## Invocation

```powershell
uv run zeus --repository C:\Users\rudtn\zeus autonomous run --file D:\workspaces\zeus\artifacts\autonomous-dge-001\MANIFEST.json
uv run zeus --repository C:\Users\rudtn\zeus autonomous status <id>
```

Exit 0 only for accepted (or cached accepted). Refusals print `status`, `reason_code`, `error_type`.

## Limitations for the owner canary

- Not run by the worker: real Claude/Codex executions, Redis, PostgreSQL (`tests/test_dge_postgres.py`
  style checks for `PostgresGraph`), CI on both platforms, the six-start canary.
- Role provider routing uses the packaged default (Codex, app_server); the `dge_role` action has no
  Claude assignment rule. Role `invocations` are counted from `invocation_reservations` per task.
- Provenance proves which execution produced the bytes, not that citations are true.
