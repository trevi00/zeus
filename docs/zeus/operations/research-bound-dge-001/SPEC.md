# Research-bound DGE: fixed delivery frame

Owner: Codex (research/design/acceptance); implementation: Zeus Claude worker.
Base: cc0c4057ad362149cfe472d42b908a2da0a003a5. Date: 2026-09-16.

## Outcome and boundary

Research BEFORE debate. A bounded, durable design-control path must refuse debate without
an immutable meeting packet and refuse implementation without an accepted design bound to
that packet and the exact implementation plan. Research -> proposal -> critique -> arbitration
-> approved design -> existing operate G/E. Agreement is NOT verified knowledge.

This delivery implements the operator-controlled control plane and its operate gate. It does
not claim autonomous researcher/debate session dispatch, authenticated role identities, real
independent three-model debate, semantic truth of citations, or formal ontology promotion.
Those remain explicit residuals in the SAME overall DGE goal. Existing operation v1 remains
compatible and ungated; the new v2 path requires this gate. Do not claim universal enforcement.
No new models are called by the DGE commands themselves, no retry/merge/deploy/graph writer.

## Primary source and design decisions

Baldrix reference commit cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2:
commands/harness-debate.md (protocol, four-generation cap, CLI convergence, provenance caveat),
agents/harness-critic.md (design-vs-implementation distinction and three critique axes),
scripts/lib/debate_convergence.py (canonical snapshot comparison and conflicting verdict refusal).
Original bytes are in the owner's .runtime/absorption/sources/baldrix/pinned. Existing file
reviews: docs/full-analysis/baldrix-agents-001/file-reviews.md; harness-pipeline-contracts/review.md.
Original source execution: NOT RUN. Scope is selected control concepts, not full adoption.
No source code/text copying: independent implementation of user requirements; upstream license
and whole-repository adoption are not established by this scoped design.

Facts: the original command researches during the planner turn; its own text says model-authored
verdicts are not a provenance trust boundary. Its critic distinguishes design from committed code.
Zeus operate already binds a Git goal/plan, uses PG transactions/outbox, real worker, evidence
inspection and review, with knowledge=False. PG store serializes transactions. Original
convergence/snapshot repetition does not prove research adequacy or implementation correctness.

Decision: immutable research packet first; exact role order and bounded rounds; explicit
operator-submitted records labelled as such. Design approval authorizes only the bound plan.
Unknowns blocking a decision stop debate for research; other unknowns stay visible but do not
force recursion. New evidence requires a NEW packet/session id, explicit supersedes linkage,
and a reason identifying the blocking question. No auto continuation or budget reset.

## Contracts (INV-DGE-001)

Implement standard-library domain validation, application state machine, thin CLI adapter.
Reuse safe ids/paths, canonical digest, GitSource, MemoryStore/PostgresStore, transaction semantics.
Do not implement a second provider runner. No credentials or unrestricted source fetching.

Meeting packet JSON, schema urn:zeus:research-packet:1:
- id (safe token), base_revision (40 hex), topic, objective, exclusions (text list).
- plan: EXACT existing operation.plan shape; nonempty acceptance_criteria and allowed_paths.
- questions: nonempty list of unique {id, question, blocking: bool, status: answered|unknown,
  claim_ids: [ids]}. Blocking unknown prevents registration for debate.
- sources: nonempty unique {id, path, sha256, locator, revision, read_scope}.
  path is safe regular tracked file in the packet's base_revision, sha256 exact Git bytes.
  locator/revision/read_scope identify provenance; external research must first be captured
  as a tracked, bounded research note. Hash verification proves bytes, NOT truth/fetch execution.
- claims: unique {id, kind: fact|inference|unknown, text, source_ids:[ids]}.
  fact/inference require existing source ids; unknown may have none. Answered questions need
  existing non-unknown claims. Every claim/source reference resolves. Empty/unknown/malformed
  schema fields, boolean-as-integer and invalid digests rejected before writes.
- limits: {max_rounds: 1..4, deadline: timezone-aware ISO8601 UTC-normalized}.
  Expiry is checked on every mutation and implementation gate, not just registration.
- supersedes: null or prior session id; research_reason: null or text. A replacement is allowed
  only for a prior needs_research session and its unresolved question, same objective/plan,
  with no auto budget extension. Preserve prior record. Avoid building an automatic scheduler.

CLI: zeus dge register --file PACKET; zeus dge submit ID --file EVENT; zeus dge status ID.
Register verifies source bytes through Git before PG registration, records packet canonical digest,
repository identity, normalized packet, version=0, round=1, state=proposal, origin=operator_submitted.
Same id+digest+repository is idempotent; conflict refuses. PG authoritative, no JSON-only status.
Status has no provider/budget/bus/knowledge side effects. Safe CLI summaries omit raw packet/body;
include digest, phase, round/limit, unresolved/deferred counts and explicit trust/remaining boundary.
Error output is fixed reason/type, no raw exception chains/source text/credentials.

Event schema urn:zeus:debate-event:1: id, expected_version (int>=0), packet_digest, round,
role proposer|attacker|arbiter, payload. All three are operator-submitted attestations, never
present them as actual model executions or independent verification. Store full event in PG
with canonical digest; exact duplicate is idempotent before stale-version check, conflict refuses.
Use one transaction for stage/event/history changes; failed/stale submissions do not partly write.
Role order strictly proposer -> attacker -> arbiter; no critic bypass.

Payloads (strict fields):
proposer: {summary, claim_ids:[nonempty valid ids]}; no plan mutation.
attacker: {findings:[{id, criterion (exact plan acceptance item), severity: critical|minor,
  scenario, claim_ids:[nonempty valid ids]}]}; empty findings is allowed, not a proof.
arbiter: {verdict: accept|revise|needs_research|reject, rationale,
  dispositions:[{finding_id, decision: resolved|deferred|blocking, reason}],
  research_question: null|text}.
Each finding must have exactly one disposition. A critical finding cannot be deferred and
accept requires no blocking findings. Minor findings may be deferred and remain recorded.
needs_research requires a concrete research_question; other verdicts require null.
accept -> design_approved (not verified); reject -> rejected; needs_research -> needs_research;
revise -> next round/proposal, unless cap reached -> exhausted. No model auto calls.
Terminal states cannot be reopened in place. Persist expired status when reporting mutation
refusal without silently refreshing deadline. Interrupted client retry uses event id/digest.
This gate verifies structure/sequence/operator decision, not truth of a 'resolved' assertion.

Operation schema urn:zeus:operation:2 = existing v1 fields plus design:
{session_id, packet_digest}. Keep v1 byte-for-byte semantics. Validate v2 strictly. Within the
SAME PG transaction that first claims operations/local_cycle/outbox, require design_approved,
same packet digest, same resolved repository identity, base_revision and exact plan. A missing,
stale, expired, mismatched or needs_research design MUST result in zero assignments/call slots.
Terminal cached operation replay keeps existing no-call behavior; do not expire past completion.
Bind design reference into assignment details and safe operation receipt, so worker and reviewer
can trace the plan authority. Gate existence is not promoted knowledge; knowledge=False remains.
Do not change legacy index/project-graph paths or add a graph-writing shortcut.

## Fixed acceptance matrix / owner verification

1. Valid pinned Git packet -> three events -> approved -> exact v2 operation claim; no formal
   graph changes. Unit fixtures are labelled; actual implementation/review use real Zeus.
2. Missing research, corrupt source, unresolved blocking question, bad schema/reference, expired
   packet, wrong repo/base/plan/digest each refuses with zero downstream provider starts.
3. Out-of-order role, omitted finding disposition, critical deferral, blocking acceptance refuse;
   minor deferral remains visible; needs_research stops and replacement keeps linkage/history.
4. Same register/event replay is idempotent; conflicting duplicate/stale expected_version rejects;
   concurrent submissions on MemoryStore and isolated PG have exactly one winner.
5. Round cap terminates without auto retry; restart from PG retains phase/limits. Deadline
   comparison uses aware UTC and never resets; a resumed mutation after expiry is refused.
6. v1 regressions pass; v2 gates actual Operation.claim, not a dead validator. No calls in status.
7. CLI uses portable argv/path handling and safe exception rendering. Unknown evidence is not
   absence/success. Source symlinks/nonregular Git objects are refused. No external fetch/provider.
8. Documentation clearly distinguishes delivered operator control plane from pending automatic
   debate sessions and formal post-E promotion. No claims of Baldrix full absorption.

Worker: meaningful focused tests + ruff; no full PG suite in the worker evidence replay.
Owner/CI: relevant real PG tests, full required checks/CI, one independent review; no exploratory
review expansion unless a changed boundary/material failure invalidates the matrix.
Add RUNBOOK with complete minimal JSON examples and fixed residuals. Keep runtime/test receipts
outside checkout. Update docs/contracts.md. No changes to dirty analysis ledgers or goal-progress.

## Overall residuals (not this implementation's completion claim)

Automated Codex research/proposer/attacker/arbiter session dispatch with authenticated execution
receipts, independent role context and actual budgets; formal verified ontology/topology promotion
with exact candidate/evidence/reviewer binding and transactional write; actual product/human
acceptance where required. This PR must not label these done or fabricate such executions.
