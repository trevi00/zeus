# autonomous run, council mode (`urn:zeus:autonomous:2`)

`zeus autonomous run --file MANIFEST` with schema `urn:zeus:autonomous:2` runs the topic-bound two-lead
council (INV-COUNCIL-001): SSOT research, one read-only database snapshot, a DBA report, the research
lead's proposal, the improvement lead's constructive alternative, the conductor's arbitration, then the
existing Operation v2 implementation/review and one same-transaction promotion. `zeus autonomous status
ID` reads the store only. `urn:zeus:autonomous:1` is unchanged (see `../autonomous-dge-001/RUNBOOK.md`):
same validator, roles and six-start cap, with additive receipt metadata; neither mode is a fallback for the other.

Framework construction only. Actual Zeus Claude implementation and Codex review calls built/reviewed
this candidate; their outcomes are in RESULT.md. Council orchestration unit tests use labelled
executor, budget, snapshot, clock and role-output fixtures. `test_council_postgres.py` separately uses
real isolated PostgreSQL. These prove the exercised contracts, not debate quality. The subsequent
live seven-call council is measured separately in LIVE-001.md; construction fixtures do not establish it.

## Manifest

The v1 fields (`id`, `base_revision`, `goal`, `plan`, `budget`, `claude`, `deadline`, `research`) plus:

```json
"schema": "urn:zeus:autonomous:2",
"current_state": {"records": [{"bucket": "tasks", "id": "0b7c..."}, {"bucket": "operations", "id": "op-001"}],
                  "max_age_seconds": 600}
```

- `records`: 1..20 unique explicit keys; buckets `tasks`, `operations`, `autonomous_runs`, `promotions`
  only; ids are safe tokens. No wildcard, scan or SQL.
- `max_age_seconds`: integer 60..3600 (a boolean is refused).
- Anything else (unknown schema, extra key, oversize, duplicate, unsafe id) is refused before Git,
  PostgreSQL or a provider is touched.

## Topology (receipt field `topology`)

| Role | Real agent | Internal DGE slot | Responsibility |
|---|---|---|---|
| `researcher` | `lead:researcher` | - | SSOT research at base; frozen packet |
| `dba` | `lead:dba` | - | interpret the snapshot; report names `snapshot_digest`, claim ids, unknowns |
| `research_lead` | `lead:research` | proposer | proposal from packet and frozen DBA report |
| `improvement_lead` | `lead:improvement` | attacker | alternative (reuse/improve/migrate/new, transition) plus findings |
| `conductor` | `conductor` | arbiter | arbitration by the existing verdict and disposition rules |

The slots exist only inside the reused DGE session state machine. Task rows, role bindings, event
bindings, the receipt and the promoted design node carry the real agents. Every role is a `dge_role`
task through the six-W outbox, the bus and `Executor.execute_one` at stage `dge:<role>`, bound to its
task row, execution artifact, settled reservation, base revision and exact input digest exactly as in v1.

Hierarchy: the conductor assigns each lead directly. The single exception to "assignment follows a
reporting edge" is the conductor's own arbitration task: sender and recipient `conductor`, action
`dge_role`, `details.role == "conductor"`, and that task's `task.result`. Any other self-addressed
message, a lead assigning or reporting to another lead, and a worker approving stay refused. The DBA
reports to the conductor; the run hands the report to the leads only after that `task.result` went
through the conductor's workflow (`report_not_relayed` otherwise). Both leads receive the same report,
`snapshot_digest` and `report_digest`.

## Flow, limits and stop codes

1. Claim `autonomous_runs/<id>` as in v1 (`configuration_mismatch`, `running_residue`, `residue`,
   `deadline_expired`; a terminal run replays cached with no call and no new snapshot). `max_starts` is 7:
   research, DBA, two leads, conductor, implement, review. One round, one absolute deadline, no retry,
   no takeover, no topology change for a claimed id.
2. Research and packet freeze: unchanged v1 path.
3. Snapshot (stage `snapshot`): one `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` transaction on a
   separate connection (connect timeout 5 s, `statement_timeout` 5000 ms), one statement over the selected
   `documents` keys, always rolled back. The envelope `urn:zeus:db-snapshot:1` is stored content-addressed
   in the executor artifact store; the run row keeps `ref`, `sha256`, `observed_at`, `expires_at`,
   `database_identity` (digest of database, schema and server version; never the DSN) and `coverage`.
   `snapshot_unavailable` (connect or read failure), `snapshot_corrupt` (malformed port output) or
   `snapshot_mismatch` stop the run with no further model start.
4. DBA: receives packet, SSOT and the redacted envelope. `report_invalid` when the report names another
   digest, cites an unknown claim id or has the wrong shape.
5. Research lead, improvement lead, conductor. Before each one the run re-reads the SAME envelope and
   checks integrity, binding and age against the frozen `expires_at`: `snapshot_missing`,
   `snapshot_corrupt`, `snapshot_mismatch`, `snapshot_stale`. Nothing refreshes or repairs a snapshot and
   no verdict can. A lead that echoes another snapshot or report digest stops with
   `council_identity_mismatch`; a shared provider thread with `role_session_shared`; a citation of a claim
   id the packet does not hold, a critical finding without trigger, impact and mitigation, or any DGE
   refusal with `debate_refused:<code>`. The improvement lead may return no finding at all. Its complete
   alternative is in the conductor's task details (`improvement_proposal`); only the findings become the
   internal attacker event, converted once by `event_from_role`.
6. Approved design: the snapshot guard and the deadline are checked again, then the existing Operation v2
   runs unchanged.
7. Promotion: the v1 worker, reviewer, inspection and session gates are unchanged. In the same
   transaction the DBA task row and execution artifact are bound again, the report is re-derived to the
   frozen digest and the snapshot document is re-verified: `promotion_report_unproven:<code>`,
   `promotion_snapshot_unproven:<code>`. The design node and the `promotions` receipt carry the DBA
   task/execution/reservation and the snapshot and report digests. Design agreement alone promotes nothing.

## What the snapshot says and does not say

Per selected key: `found`, `missing` or `unknown`, the SHA-256 of the canonical row when a row exists,
and for `found` only these required fields, each checked against a finite vocabulary or identity syntax:

| Bucket | Fields |
|---|---|
| `tasks` | `status` (the execution statuses of `local_cycle`), `agent` (`conductor` or `lead:<name>` / `worker:<name>`; the colon is part of a normal identity) |
| `operations` | `status` (`running` or an operation terminal status), `lead_accepted` (true, false or null) |
| `autonomous_runs` | `status` (`running` or an autonomous terminal status), `stage` (a v1 or v2 stage) |
| `promotions` | `repository` (`verified:<run id>`) |

- `unknown`: a row exists but a whitelisted field is absent or outside its vocabulary (or the body is
  not an object). Every listed field must be present as a key. Null is valid only where the table
  permits it, which is `lead_accepted` alone: an explicit `lead_accepted: null` is `found`, an
  operations row without the `lead_accepted` key is `unknown`, and null in any other field is
  `unknown`. Only the digest is exported, no field. An arbitrary token-shaped string is never copied
  out, and unknown is never read as success.
- `missing`: no row for that key at that snapshot. It says nothing about other keys, other buckets or a
  later moment.
- Never exported: row bodies, free text, errors, prompts, paths, credentials, the DSN. The adapter's
  public failure keeps no exception chain, so a traceback cannot print the driver's error.

Not guaranteed: atomicity between the Git base and PostgreSQL; freshness beyond `expires_at`;
completeness of topic-relevant records outside the explicit selection; correctness of the DBA's or any
lead's prose (the report is interpretation, never a Git-supported fact).

PostgreSQL: the local server is 17.11. The owner opened the PostgreSQL 17 `transaction-iso` and
`sql-set-transaction` pages on 2026-09-17 and confirmed the semantics used here (Repeatable Read: one
snapshot for the whole transaction; READ ONLY: writes fail server-side). The SPEC's earlier PostgreSQL 18
link was a documentation reference, not a local version observation.

## Receipt metrics

`topology`, `roles` (agent, task, generation, attempt, execution_ref, output digest per role), `snapshot`
(`coverage`: selected/found/missing/unknown; age = now - `observed_at`), `report`, `starts` against
`max_starts`, `durations`, `invocations`, `reason_code`. They measure this run, not feature completeness
or the truth of model prose.

## Verification

- `python -m pytest tests/test_council.py tests/test_council_roles.py tests/test_autonomous.py tests/test_autonomous_roles.py -q`
- Real PostgreSQL lane (owner/CI, `HARNESS_INTEGRATION=1` with an isolated schema):
  `python -m pytest tests/test_council_postgres.py -q`: found/missing records, one fixed transaction
  snapshot under a concurrent writer, `ReadOnlySqlTransaction` on a write, source rows unchanged,
  selection bound, unreachable server as `snapshot_unavailable`.
