# Decision feedback and recurring-work candidates

2026-09-21. Frame: `SPEC.md`, "Decision feedback and recurring-work candidates: first runnable
delivery". Canonical judgment rules: `docs/context/AUTHORING.md`, *Repeated work becomes reusable
capability* and *Conductor decision improvement*. Contract: `docs/contracts.md`,
INV-DECISION-FEEDBACK-001. Implementation: `src/codex_harness/domain/decision_feedback.py`,
`src/codex_harness/application/decision_feedback.py`,
`src/codex_harness/adapters/decision_feedback.py` and
`src/codex_harness/adapters/decision_feedback_cli.py`.

**Purpose.** Show existing conductor decisions beside the actual outcomes of the runs that carried
them, and name repeated procedures — successes included — as *unverified* improvement candidates.
**Owner.** Implementation Claude; independent acceptance Codex; the operating collection and any
scheduling decision stay with the repository owner.
**When to read.** Before running `zeus decision-feedback`, before writing a registry entry, and
before citing a candidate as evidence of anything.

This is one operating read/collect/report cycle. It is **not** an evaluator, **not** a policy
activation, **not** a skill or script, and **not** a claim that judgments already improve
themselves. Nothing here calls a model or a network, and no candidate it writes carries authority.

## What it reads, and what it refuses

An observation is admitted only when one execution identity binds across four rows that other owners
already wrote **and** the stored bytes behind that identity are that execution's own answer:

| row | what must hold |
|---|---|
| `autonomous_runs` | the run names its session, carries the packet digest and the council topology |
| `dge_sessions` | `executor_bound`, owned by that run, same packet digest |
| `dge_events` | the conductor's arbitration slot of that session, with a task id and `execution_ref` |
| `tasks` | a succeeded `conductor` execution whose result repeats that reference, generation and attempt |
| the execution artifact | read through the existing execution-evidence port at `execution_ref` and checked by the existing `execution_evidence` rule against the authoritative `invocation_reservations` row: this task's exact answer, hashing to the binding's `output_sha256`, produced by the settled `accepted` reservation of this task, generation, attempt and conductor stage at the session's base revision |

A matching `execution_ref` **string** in the run, event and task rows is therefore never evidence
credit by itself: a reference whose artifact is absent, whose bytes no longer hash to it, or that
belongs to another execution is refused like any other unproven identity.

Any gap is one fixed reason code and **no** evidence credit: `run_identity_unknown`,
`foreign_repository`, `source_kind_unknown`, `decision_session_unproven`, `work_contract_unknown`,
`decision_event_unproven`, `decision_execution_unproven`, `decision_artifact_missing`,
`decision_artifact_corrupt`, `decision_artifact_invalid`, `decision_artifact_unproven`. `collect`
refuses outright (`evidence_port_unavailable`) when no artifact port is wired at all. Absent
historical fields stay unknown; none
is defaulted or repaired. Only identities, digests and closed vocabularies (outcome state, arbiter
verdict, disposition count) are stored — never rationale, scenario, packet, payload or answer text.

Outcome states are `pending`, `accepted`, `rejected`, `failed`, `cancelled`, `unknown`, always beside
the exact source status, reason code and provenance. A terminal `accepted` is operation acceptance
only. Decision quality is reported `unknown` in this delivery, because downstream success or failure
alone never establishes it.

## The trusted registry

The registry decides which observations are comparable, so it is owner-authored and Git-pinned:

```json
{
  "schema": "urn:zeus:procedure-registry:1",
  "version": 1,
  "entries": [
    {
      "id": "runbook-note",
      "source_kind": "council",
      "repository": "<the identity `zeus operate` records for this checkout>",
      "allowed_paths": ["docs/zeus/operations/example-001/RUNBOOK.md"],
      "acceptance_criteria_sha256": "<sha256 of the canonical JSON of the exact criteria list>",
      "remediation": "existing_owner_review"
    }
  ]
}
```

`acceptance_criteria_sha256` is `sha256` of `json.dumps(criteria, sort_keys=True, ensure_ascii=False,
separators=(",", ":"))` for the acceptance-criteria list **in the plan's own order**
(`domain.decision_feedback.criteria_digest`); a reordered or edited list is another contract.
`remediation` is `skill`, `script` or `existing_owner_review` and records what the owner would
consider, not a decision. Matching compares exactly four values — source kind, repository identity,
the complete allowed-path set and that digest. There is no title, substring, family, regular
expression, model-selected cause or executed rule, and an empty or ambiguous match is `unknown`.

The file is read with `GitSource` at the 40-hex commit named on the command line, never from the
working tree: editing the checked-out file changes nothing until it is committed and the new commit
is passed.

## Procedure

```
zeus decision-feedback collect --registry docs/zeus/procedures.json --revision $(git rev-parse HEAD) [--limit 100] [--after RUN_ID]
zeus decision-feedback status  [--limit 100]
zeus decision-feedback report  [--limit 100] [--after CANDIDATE_ID] [--collection COLLECTION_ID]
```

`collect` scans a bounded ascending page of run ids and reports `scanned`, `eligible`, the unknown
reasons, `conflicts`, `truncated` and `next_cursor`; pass that cursor back as `--after` to continue.
The repository identity comes from the trusted CLI settings, the same digest `zeus operate` records.
Two distinct executed run identities in one contract group create exactly one candidate per
repository, procedure and registry revision; it says `needs_analysis`. Retries, replayed events,
copied receipts, repeated collection and imported experience are not additional occurrences. A group
keeps its distinct run identities durably, and the candidate's occurrence references are a bounded
*window* derived from that membership, never a list that accumulates: collecting a group that is
already larger than the reported window again adds no occurrence, no unrecorded remainder and no
candidate.

A run's decision facts are immutable: a changed decision, or a changed history after a terminal
outcome, becomes a conflict for owner inspection and the recorded observation is left exactly as it
was. Because the page is read in one transaction and recorded in the next, a differing outcome is
first revalidated against the authoritative run row inside the recording transaction. A page that
simply went stale — the run reached its terminal state and another collector recorded it first — is
counted as `observations_stale` and changes nothing; a row that cannot be re-read stays unknown.
Only a history that really changed is a conflict.

A candidate is the *start* of the existing promotion path — candidate → specified → implemented →
independently verified → activated → measured (`AUTHORING.md`). It authorizes none of those steps.

## Prerequisites

The control-plane store (PostgreSQL in operation, `MemoryStore` in tests), a Git checkout that
contains the pinned registry commit, read-only access to the runtime artifact root those runs wrote
their execution artifacts to, and at least one council (autonomous v2) run whose rows are present. A
run whose artifacts are no longer in that root is reported `decision_artifact_missing`, not observed.
No Redis, provider credential, network access or running service is used or required.

## Evidence and verification

```
python -m pytest tests/test_decision_feedback.py tests/test_decision_feedback_cli.py -q -p no:cacheprovider
python -m ruff check . --no-cache
```

The application tests run the **real** `CouncilRun` state machine with the labelled fixtures of
`tests/test_council.py`, so the rows under test are the actual stored shapes; the registry documents,
the injected divergent run histories and the broken stores are labelled fixtures. The PostgreSQL test
is skipped unless `HARNESS_INTEGRATION=1`. Before any scheduling decision the owner still runs a real
read-only historical collection in a separately named candidate namespace, plus integration and CI.

## Limits

- Replay, held-out evaluation and policy activation are not implemented; nothing is dispatched.
- Decision quality stays `unknown` until an independently reviewed diagnosis is linked.
- Execution identity is verified against the stored run, session, event and task rows **and** against
  the content-addressed execution artifact those rows reference; a matching reference string alone is
  not credit. Artifact integrity is the store's; what the bytes must prove is the existing
  `execution_evidence` rule's.
- Counts describe the scanned page; a truncated scan says so and carries its cursor.
- Candidate evidence reports at most 50 occurrence references per contract group; the distinct-run
  count stays exact and the unreferenced remainder is named, never silently counted.
- Distinct-run membership itself is exact up to 1000 runs per contract group; beyond that the group
  reports `membership_capped` and counts no further run.
- Successful repetition is grouped here and never enters incident recurrence (INV-RECURRENCE-001).
- Skill or script extraction, promotion and knowledge verification stay with their existing owners.
- Version 1 reads council runs only; v1 autonomous runs are `source_kind_unknown` by design.

## Related links

`docs/contracts.md` (INV-DECISION-FEEDBACK-001, INV-AUTONOMOUS-001, INV-COUNCIL-001, INV-DGE-001,
INV-RECURRENCE-001), `docs/context/AUTHORING.md`, `SPEC.md` in this folder. Pointers, not authority.
