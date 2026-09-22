# Structured decisions inside the existing six-W protocol

## Outcome, authority and scope

2026-09-22. User confirms Jev-style enhancement of existing inter-session six-W JSON, not a new
Jev provider or weight training. No Jev/OpenRouter calls. Codex owns analysis/acceptance; Claude
implements. Preserve conductor/lead/worker roles, Redis Streams delivery and PostgreSQL runtime SSOT.
This frame owns this protocol change; storage recovery and session retirement keep their scopes.

First bounded delivery: versioned question/answer contract plus an opt-in, read-only failure-triage
path through existing six-W task assignment/result and durable evidence. Initially recommendations
only: no automatic retry, repair dispatch, permission grant, model switch, merge or deployment.
Completion requires independent review, real PG/bus round-trip and one controlled current-model
execution; schema fixtures alone do not establish active operation or improved judgment quality.

## Inspected facts, sources and limits

resources/message.schema.json is urn:codex-harness:six-w:1, schema_version 1.0. Its top level is
closed; what.details is extensible. Existing how.result_schema can carry response constraints.
domain/model.py Organization.authorize owns reporting edges and rejects worker approval. Existing
DGE questions/claims and autonomous_roles already exist; do not create a competing debate owner.
INV-MESSAGE-001 owns same-ID payload identity, PG-before-ACK and at-least-once transport.

Local thread 01a0b9e7-b4e4-7962-b6fa-0dac7f96fe9e (display title Jev model search/settings) contains
one user-pasted successful response naming typesafe/jev-1.13-20260917 for a duplicate-payment
example. D:/workspaces/jev-lab/repo/example.json declares choice, boolean-like and ordinal questions.
This is reported execution evidence, not owner-captured provider output or validated Zeus quality.
No private credentials or whole conversation transcript belongs in Git or model context.
Primary source read 2026-09-22: https://docs.typesafe.ai/concepts/system-one (unversioned).
It describes typed decisions on state, enumerated choices/scores and combining answers with code
checks. It explicitly supplies no reasoning explanation; calibration across predictions is not an
individual correctness guarantee. We adopt the interface pattern, not Jev's learned capabilities.

## Complete affected path and ownership

Git-owned task-specific decision definition -> owner-built state/evidence snapshot -> six-W
task.assign -> existing PG outbox/Redis/consumer -> existing current-model executor -> typed answer
and existing execution evidence -> deterministic binding/authority validation -> six-W task.result
and PG recorded recommendation -> existing lead/conductor disposition. Raw recommendations are not
verified knowledge: existing independent review/promotion remains the only semantic promotion path.

Keep the six-W envelope and its existing message types. Add a versioned optional
what.details.decision_request payload with its own strict schema, not arbitrary new envelope keys.
Legacy messages retain behavior. An unknown declared decision version must fail explicitly, never
silently fall through to legacy handling. Bind results to request message ID, schema/definition
digest, state/evidence snapshot digest, task generation/attempt and actual execution receipt.

Request fields: definition ID/version; bounded state with evidence refs; questions with unique IDs,
kind (choice/boolean/ordinal), question text, permitted values and explicit criteria for every
choice/score; requested evaluation only. Large immutable source material stays behind verified
content refs, not duplicated into every message. No free-form tool/action executable fields.
Results: question ID, answered/insufficient_evidence status, typed value (null if insufficient),
criterion IDs, evidence refs and concise supporting rationale. Rationales are model claims, not
hidden reasoning or independent proof. No probability/confidence fabrication; any future calibrated
metric needs its own versioned empirical evidence. Unknown is not false, score zero or rejection.

Validator enforces exact question denominator, no duplicates/extra choices, ordinal bounds,
finite values, evidence membership and accessible hash-checked bytes, request/version/execution
binding and current ownership. Valid JSON does not prove semantic correctness. Untrusted evidence
content cannot change criteria, authorize an actor or issue instructions. Preserve existing role
authorization and PG-before-ACK; no second message bus or separate runtime truth store.

Pilot family: recommend handling for an already terminal execution failure. Choices investigate,
propose_fix, eligible_for_owner_retry_review, request_user_input; insufficient evidence is separate.
The retry choice is only a review recommendation and cannot re-execute. Use observed phase, outcome,
side-effect uncertainty, settlement and existing repeat-family records; same symptom does not prove
same cause. No missing source may become a positive safety assertion. Existing lead decides action.

## Acceptance matrix and delivery batch

| Boundary | Required result |
|---|---|
| Normal | fixed questions -> typed answers -> provenance-bound stored recommendation |
| Legacy/version | old envelope behavior retained; unknown new version refused |
| Invalid/unknown | invalid values, missing answers/evidence refuse; unknown is explicit |
| Authority/injection | worker cannot approve, reference text cannot change policy or execute |
| Duplicate/concurrent/stale | idempotent same result; payload conflict/stale generation rejected |
| Timeout/cancel/restart | no recommendation credited without terminal execution; durable replay |
| Platform | Windows/Linux JSON/schema/store semantics consistent |
| Cleanup | retain source/execution evidence; no session/data deletion in this task |
| Quality/usage | separate schema validity from independent quality and measured total usage |

Before implementing, trace current validator, workflow acceptance and executor action dispatch to
select their existing extension points. One implementation batch adds the inner contracts, domain
validation and narrowly opted-in pilot path, focused tests and contract documentation. No global
message rewrite or full DGE redesign. Freeze examples/oracle before evaluation; use independent
normal, critical-failure and insufficient-evidence cases. Do not infer Sol qualification or savings
from this interface delivery; reuse the existing task-family qualification frame for later routing.

Current disposition: design established from local SSOT and primary source; implementation not yet
dispatched, no provider/model configuration or runtime routing changed. Priority storage recovery
remains blocking general Fleet admission. This frame must not be reported as deployed functionality.
