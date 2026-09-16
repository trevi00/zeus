# operate run / operate status

One fixed manifest in, one worker implementation, one bound evidence gate, one lead review, one
terminal receipt out (INV-OPERATION-001). No conductor, merge, deploy, retry or new work.

## Manifest example (`OPERATION.json`)

```json
{
  "schema": "urn:zeus:operation:1",
  "id": "operation-entrypoint-001-pilot",
  "base_revision": "228b7f3529d14388cfb6a2bbf828893b04dddebd",
  "goal": {
    "path": "docs/zeus/operations/GOAL.md",
    "sha256": "<sha256 of the exact Git bytes of GOAL.md at base_revision>",
    "criterion": "one-start operating entry point",
    "rationale": "one small RUNBOOK task exercises the entry point end to end"
  },
  "plan": {
    "objective": "Add the pilot receipt note to the RUNBOOK; change nothing else.",
    "acceptance_criteria": ["python -m pytest tests/test_operation.py -q passes", "only the allowed path changes"],
    "allowed_paths": ["docs/zeus/operations/operation-entrypoint-001/RUNBOOK.md"]
  },
  "budget": {"per_host": 30, "total": 30},
  "claude": {"model": "claude-fable-5-1", "timeout_seconds": 300, "max_budget_usd": 2}
}
```

`budget` are the machine ledger ceilings that authorize this operation; they never reset earlier
slots. `claude.max_budget_usd` is a declared CLI control, not measured spending. Credentials,
the Claude executable and PostgreSQL/Redis endpoints stay in `.env`/environment. Compute the goal
digest from Git bytes, not from the working tree:

```powershell
git show 228b7f3529d14388cfb6a2bbf828893b04dddebd:docs/zeus/operations/GOAL.md | Out-Null
python -c "import subprocess,hashlib;print(hashlib.sha256(subprocess.run(['git','show','228b7f3529d14388cfb6a2bbf828893b04dddebd:docs/zeus/operations/GOAL.md'],capture_output=True).stdout).hexdigest())"
```

## Invocation

PowerShell:

```powershell
uv run zeus --repository C:\Users\rudtn\zeus operate run --file D:\workspaces\zeus\artifacts\operation-entrypoint-001\OPERATION.json
uv run zeus --repository C:\Users\rudtn\zeus operate status operation-entrypoint-001-pilot
```

Bash / WSL:

```bash
uv run zeus --repository /mnt/c/Users/rudtn/zeus operate run --file /mnt/d/workspaces/zeus/artifacts/operation-entrypoint-001/OPERATION.json
uv run zeus --repository /mnt/c/Users/rudtn/zeus operate status operation-entrypoint-001-pilot
```

Exit 0 only when the receipt is `accepted` (a repeated run of a completed id prints the saved
receipt with zero calls). Everything else exits 1 and prints `status`, `reason_code`,
`error_type` or the receipt; DSNs, raw exceptions, prompts and plan text are never printed.

## Terminal statuses and reason codes

| status | reason_code | meaning |
|---|---|---|
| accepted | lead_accepted | succeeded accepted review_lead decision for the worker's candidate, slots settled, collection clean |
| rejected | lead_rejected | the lead rejected; no rework, diagnosis or retry |
| failed | execution_retry / execution_failed / exception:* | worker did not succeed; reviewer calls stay zero |
| failed | evidence_gate_refused | no bound all_checked `evidence_inspections` row for the task; reviewer calls stay zero |
| failed | settlement_failed | a slot could not be settled; the run stops there (after the worker slot the reviewer is never reserved or called), the slot stays counted |
| failed | collection_failed | the lead accepted but observation collection reported sink failures; not a success |
| failed | idle | nothing to execute after finite message-only turns |
| exhausted | budget_exhausted | machine ledger or cycle limit refused a start |
| unknown | review_verdict_unknown / acceptance_unproven / other | no provable outcome |

Refusals before any call: `configuration_mismatch` (same id with a different manifest,
repository, resolved runtime directory `HARNESS_RUNTIME_DIR`, packaged policy, provider
policy/controls or endpoint digest), `running_residue`, `cycle_residue`,
`base_revision_missing`, `goal_missing_at_base`, manifest errors. An interrupted run stays
`running` and is refused on restart with no new calls; an operator inspects it with
`operate status` and `cycle handoff`, never by automatic takeover.

## Evidence

The receipt holds the manifest digest, identity digests, slot ids, the cycle handoff projection,
task/decision ids, execution and inspection references and collection counts. Observation logs go
through the existing Observer spool and Collector; artifacts stay under the runtime directory.

## Ledgers, provisional artifacts and formal knowledge

Three kinds of records leave this entry point and none of them is validated knowledge:

- Execution ledgers: the PG `operations`, `local_cycles`, `tasks`, `decisions_pending`,
  `evidence_inspections` rows, machine call slots and observation records. They exist for
  recovery, audit and the receipt; they carry no semantic acceptance.
- Provisional artifacts: worker/reviewer outputs, candidate revisions and execution refs under
  the runtime `artifacts` directory. Staging evidence for a human-owned PR, never an ontology.
- Formal knowledge: not written here. `operate run` builds its executor with
  `build_executor(knowledge=False)`, so no `index_python`/`project_runtime` graph write, hybrid
  query, projection or promotion happens from the worker, the reviewer, a failure or a
  checkpoint. An accepted review boolean does not promote anything; promotion is a separate,
  explicit contract. Other commands keep the default writable adapter and are not claimed fixed.

## Pilot record

Not run by the implementation worker. Owner records the real pilot receipt hashes here after
the independent review.
