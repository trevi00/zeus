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
   action, role, base, execution_ref, generation, attempt) or the run stops (`role_task_*`), and then
   to the execution artifact behind `execution_ref` read through the FileArtifacts-backed evidence
   port: the artifact's own `answer` must equal the stored output, its invocation must name a settled
   `accepted` reservation of that task/generation/attempt/stage `dge:<role>`, and its context binding
   must name the base revision and the exact input evidence digest (`evidence_missing`,
   `evidence_corrupt`, `evidence_answer_mismatch`, `evidence_reservation_unbound`,
   `evidence_reservation_unsettled`, `evidence_basis_mismatch`). Two roles sharing one provider
   thread stop the run (`role_session_shared`).
3. The researcher output becomes the packet through the existing validator plus Git source
   verification; `needs_user` stops as `needs_user`. One round only: `revise` ends `exhausted`.
4. Critical attacker findings need trigger, impact and mitigation; otherwise refused. Minor findings
   never block. Arbiter dispositions follow the existing DGE rules.
5. Approved design launches `Operation.run` with the `.impl` v2 manifest (start cap six in total). The
   run's absolute deadline travels into the child operation unchanged: it is checked before the worker
   and before the reviewer reservation (`deadline_expired`, no slot taken), after the review returns
   and again inside the promotion transaction. A late success promotes nothing (`expired`).
6. Promotion re-reads the accepted operation, the succeeded worker task, the accepted `review_lead`
   decision for the same candidate revision, the all_checked inspection row and the owned session
   inside the transaction that writes `verified:<run>` nodes/edges and the `promotions` receipt, and
   re-verifies the worker and reviewer execution artifacts the same way as the roles (the reviewer
   artifact's own `accepted` must be true; `promotion_evidence_unproven:<code>` otherwise). The
   worker artifact's context binding must name the manifest `base_revision`; the reviewer's must
   name the reviewed candidate revision, because the independent review executes in the candidate
   checkout and the executor records that binding whenever project skills are configured.
   Identical retry is idempotent; a different graph is `promotion_conflict`.
7. The receipt keeps every stage duration (roles, implementation, promotion), the actual ledger
   provider label per start (Codex for the four design leads and the reviewer, Claude for the worker)
   and reservation counts per role plus `implementation` and `review`. Ledger refusal ends `exhausted`.

Legacy `operate` v1/v2 stays manual maintenance; it is never a fallback for an autonomous failure.

## Invocation

```powershell
uv run zeus --repository C:\Users\rudtn\zeus autonomous run --file D:\workspaces\zeus\artifacts\autonomous-dge-001\MANIFEST.json
uv run zeus --repository C:\Users\rudtn\zeus autonomous status <id>
```

Exit 0 only for accepted (or cached accepted). Refusals print `status`, `reason_code`, `error_type`.

## Limitations for the owner canary

- Not run by the worker: real Claude/Codex executions, Redis, PostgreSQL (`tests/test_dge_postgres.py`
  style checks for `PostgresGraph`), CI on both platforms, the six-start canary. Separate
  `test_autonomous_cli.py`, `test_autonomous_postgres.py` and `test_promotion.py` files were not
  written; the acceptance-matrix, evidence, deadline, reporting and promotion regressions live in
  `tests/test_autonomous.py` with labelled fixtures.
- Role output contract (after canary autonomous-ssot-canary-001): the four model-facing schemas in
  `adapters/autonomous_roles.py` enumerate claim kind, question status, SSOT decision, finding
  severity, arbiter verdict and disposition decision from the domain constants the consumers check,
  so an off-contract value is refused as `schema_mismatch` (owner `agent_output`) at the provider
  boundary before any packet or event is built. The consumers are unchanged and nothing is coerced.
  `tests/test_autonomous_roles.py` holds the schema-to-consumer tests plus a compact labelled fixture
  of the live rejected kinds/status; no transcript is stored.
- Claim citations (after canary autonomous-ssot-canary-002, claim c6): the researcher claim schema is a
  nested `anyOf` of two closed object variants, fact/inference with `source_ids` `minItems: 1` and
  unknown with any list (empty stays valid, no citation is forced). A fact with `source_ids: []` is
  refused as `schema_mismatch` at the claim (`instance_path` `["claims", N]`) before the packet; the
  consumer rule in `domain/dge.py` is unchanged. The prompt tells the researcher to keep runtime,
  test-run and clean-checkout observations in `ssot.evidence`. Local preflight accepts a broader
  dialect than the provider, so provider acceptance of this shape is proven only by the next real
  role run; `if/then` and `allOf` are not used.
- Next canary: run collection as `python -P -m pytest` with only the checkout `src` on `PYTHONPATH`
  (no repository-root injection); GitHub CI runs the console entrypoint. The host's application
  control refusing `pytest.exe` (WinError 4551) is a host policy, not a code defect. The three
  `tests.test_operation` import lines stay as they are for the real canary task.
- Evidence provenance is checked against the artifact store and `invocation_reservations`; the real
  executor's artifact shape (`answer`, `invocation.reservation`, `research_binding`, `thread_id`) was
  traced in code, not exercised by a live run.
- Role provider routing uses the packaged default (Codex, app_server); the `dge_role` action has no
  Claude assignment rule. Role `invocations` are counted from `invocation_reservations` per task.
- Provenance proves which execution produced the bytes, not that citations are true.
