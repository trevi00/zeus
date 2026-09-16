# dge register / submit / status and operate v2

Research packet in, three operator-submitted debate events in fixed order, one approved design,
then the existing `operate run` with a v2 manifest bound to that design (INV-DGE-001). No model
is called by any `dge` command; no merge, deploy, retry, graph write or knowledge promotion.

## What is delivered and what is not

Delivered: strict packet validation, Git byte verification of pinned sources, a durable
PostgreSQL session per packet, the ordered bounded state machine proposer -> attacker -> arbiter
with rounds, deadline, idempotent replay and stale-version refusal, a read-only status, and the
claim-time gate that refuses an `urn:zeus:operation:2` manifest whose design is missing, stale,
expired, unapproved or bound to another repository, base or plan.

Not delivered, and not claimed: automatic dispatch of researcher, proposer, attacker or arbiter
model sessions; authenticated role identities; an independent three-model debate; verification
that a cited source is true or that a "resolved" disposition is correct; formal ontology or
topology promotion after acceptance. Every event is an operator attestation written by whoever
runs `dge submit`. Baldrix was a scoped concept source, not adopted or absorbed as a whole.

## Meeting packet example (`PACKET.json`)

```json
{
  "schema": "urn:zeus:research-packet:1",
  "id": "research-bound-dge-001-pilot",
  "base_revision": "2baaa4ecdf78bfe9482a540b7e3fb5c17ac732b3",
  "topic": "claim-time design gate",
  "objective": "Decide how operate v2 binds an approved design before assignment.",
  "exclusions": ["no automatic model debate", "no graph promotion"],
  "plan": {
    "objective": "Add the pilot note to the RUNBOOK; change nothing else.",
    "acceptance_criteria": ["python -m pytest tests/test_dge.py -q passes", "only the allowed path changes"],
    "allowed_paths": ["docs/zeus/operations/research-bound-dge-001/RUNBOOK.md"]
  },
  "questions": [
    {"id": "q1", "question": "Is PostgreSQL authoritative for runtime records?", "blocking": true,
     "status": "answered", "claim_ids": ["c1"]},
    {"id": "q2", "question": "How does the gate behave under lock contention?", "blocking": false,
     "status": "unknown", "claim_ids": []}
  ],
  "sources": [
    {"id": "s1", "path": "docs/contracts.md",
     "sha256": "<sha256 of the exact Git bytes of docs/contracts.md at base_revision>",
     "locator": "git:docs/contracts.md#INV-OPERATION-001", "revision": "2baaa4ecdf78bfe9482a540b7e3fb5c17ac732b3",
     "read_scope": "INV-OPERATION-001 section"}
  ],
  "claims": [
    {"id": "c1", "kind": "fact", "text": "The operation claim is one PG transaction with the outbox.", "source_ids": ["s1"]},
    {"id": "c2", "kind": "unknown", "text": "Contention behaviour is unmeasured.", "source_ids": []}
  ],
  "limits": {"max_rounds": 2, "deadline": "2026-09-30T00:00:00+00:00"},
  "supersedes": null,
  "research_reason": null
}
```

A `blocking: true` question with `status: unknown` refuses registration: research first. A
non-blocking unknown stays visible and does not force another round. External research must first
be captured as a tracked, bounded note in Git so it can be pinned as a source. Compute source
digests from Git bytes, not the working tree:

```powershell
python -c "import subprocess,hashlib;print(hashlib.sha256(subprocess.run(['git','show','2baaa4ecdf78bfe9482a540b7e3fb5c17ac732b3:docs/contracts.md'],capture_output=True).stdout).hexdigest())"
```

## Debate events (`urn:zeus:debate-event:1`)

`packet_digest` is the `packet_digest` printed by `dge register` or `dge status`.
`expected_version` is the session `version` printed by the previous command (0, 1, 2 for the
first round). Round 1 proposer:

```json
{"schema": "urn:zeus:debate-event:1", "id": "r1-proposer", "expected_version": 0,
 "packet_digest": "<digest>", "round": 1, "role": "proposer",
 "payload": {"summary": "Gate inside the claim transaction; refuse before any row.", "claim_ids": ["c1"]}}
```

Attacker (an empty `findings` list is allowed and proves nothing):

```json
{"schema": "urn:zeus:debate-event:1", "id": "r1-attacker", "expected_version": 1,
 "packet_digest": "<digest>", "round": 1, "role": "attacker",
 "payload": {"findings": [
   {"id": "f1", "criterion": "only the allowed path changes", "severity": "minor",
    "scenario": "the receipt gains a design key for v1 rows too", "claim_ids": ["c1"]}]}}
```

Arbiter (every finding exactly once; critical findings cannot be deferred; `accept` needs no
`blocking` disposition; `research_question` only with `needs_research`):

```json
{"schema": "urn:zeus:debate-event:1", "id": "r1-arbiter", "expected_version": 2,
 "packet_digest": "<digest>", "round": 1, "role": "arbiter",
 "payload": {"verdict": "accept", "rationale": "Structure and sequence hold; f1 is recorded.",
             "dispositions": [{"finding_id": "f1", "decision": "deferred", "reason": "documented in RUNBOOK"}],
             "research_question": null}}
```

Verdicts: `accept` -> `design_approved` (not verified), `reject` -> `rejected`, `needs_research`
-> `needs_research` (a new packet with `supersedes` and `research_reason` that answers the exact
question may follow; the prior row stays), `revise` -> next round or `exhausted` at `max_rounds`.

## Findings across rounds

A finding is recorded once for the whole session with its id, criterion and severity. Every
finding whose last disposition is `blocking` is carried into the next round: `dge status` lists
it under `unresolved_finding_ids`, and the next arbiter must name it again even if the round's
attacker submits `"findings": []`. A round 2 attacker may not reuse a recorded id (for example to
resubmit `f1` as `minor`); that event is refused and nothing is written. Round 2 arbiter closing a
carried critical finding:

```json
{"schema": "urn:zeus:debate-event:1", "id": "r2-arbiter", "expected_version": 5,
 "packet_digest": "<digest>", "round": 2, "role": "arbiter",
 "payload": {"verdict": "accept", "rationale": "The round 2 proposal addresses f1.",
             "dispositions": [{"finding_id": "f1", "decision": "resolved", "reason": "fix described in r2-proposer"}],
             "research_question": null}}
```

`resolved` is the operator's recorded decision, not a verified fix. Critical findings can only be
`resolved` or `blocking`; minor findings may also be `deferred` and stay counted. `accept` with a
carried finding omitted or left `blocking` is refused; `revise` with it still `blocking` at
`max_rounds` ends `exhausted` with the finding recorded. Earlier decisions stay in the session row
(`findings[*].decisions` and `rounds.N.arbitration`) and are never rewritten.

## Invocation

```powershell
uv run zeus --repository C:\Users\rudtn\zeus dge register --file D:\workspaces\zeus\artifacts\research-bound-dge-001\PACKET.json
uv run zeus --repository C:\Users\rudtn\zeus dge submit research-bound-dge-001-pilot --file D:\workspaces\zeus\artifacts\research-bound-dge-001\r1-proposer.json
uv run zeus --repository C:\Users\rudtn\zeus dge status research-bound-dge-001-pilot
uv run zeus --repository C:\Users\rudtn\zeus operate run --file D:\workspaces\zeus\artifacts\research-bound-dge-001\OPERATION.json
```

Bash / WSL uses `/mnt/c/Users/rudtn/zeus` and `/mnt/d/...` paths with the same argv. Exit 0 for
a registered, replayed, recorded, duplicate or read result; refusals exit 1 and print
`status`, `reason_code` and `error_type` only. Packet text, payloads, DSNs and raw exceptions are
never printed. Keep packet, event and receipt files under `D:\workspaces\zeus\artifacts`.

## Operation v2 manifest

The v1 manifest plus one block; everything else is identical and `plan` must be byte-identical to
the packet's plan:

```json
"schema": "urn:zeus:operation:2",
"design": {"session_id": "research-bound-dge-001-pilot", "packet_digest": "<digest>"}
```

`operate run` evaluates the gate inside the same transaction that claims the operation, the local
cycle and the outbox assignment. Refusals before any row, assignment, reservation or provider
start: `design_missing`, `design_digest_mismatch`, `design_needs_research`,
`design_not_approved` (proposal, critique, arbitration, rejected, exhausted, expired),
`design_unresolved` (an approved row still carrying an unresolved finding; unreachable through
`dge submit`, checked anyway), `design_repository_mismatch`, `design_base_mismatch`,
`design_plan_mismatch`, `design_expired`.
A completed v2 operation replays its receipt without re-gating. v1 manifests stay ungated; do not
describe the gate as universal enforcement.

## Session reason codes

| command | reason_code | meaning |
|---|---|---|
| register | contract_refused (PacketError) | schema, type, reference, boolean, digest or deadline fault; blocking unknown question |
| register | base_revision_missing / source_missing_at_base / source_not_regular / source_digest_mismatch | Git verification failed; nothing registered |
| register | packet_expired / packet_conflict / source_verification_incomplete | deadline passed by the time the row would be written (clock read inside the transaction, after the lock wait); same id with another digest or repository; bindings do not cover the packet. An exact replay returns the saved row even after the deadline and authorizes nothing |
| register | supersedes_unknown / supersedes_not_needs_research / supersedes_plan_mismatch / supersedes_question_unanswered / supersedes_already_replaced | replacement linkage refused |
| submit | unknown_session / event_conflict / session_terminal / packet_expired | the last one persists state `expired` |
| submit | packet_digest_mismatch / round_mismatch / stale_version / role_out_of_order | nothing written |
| submit | contract_refused (EventError) | payload shape, criterion, claim, disposition or verdict rule; reused finding id; carried finding omitted, deferred while critical, or left blocking under `accept` |

## Owner verification

Worker evidence: `tests/test_dge.py`, `tests/test_dge_cli.py` (real temporary git), the v1
regressions and ruff. `tests/test_dge_postgres.py` needs `HARNESS_INTEGRATION=1` and an isolated
schema and is run by the owner with the full suite and CI. The pilot packet, events and receipt
hashes are recorded here by the owner after the independent review; none were run by the
implementation worker.
