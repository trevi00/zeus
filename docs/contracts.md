# Contracts — authoritative definitions

| ID | Contract |
|---|---|
| INV-MESSAGE-001 | All messages are six-W JSON. IDs cannot identify two payloads. DB commit precedes ACK; delivery is at-least-once. Reports match durable completed executions. |
| INV-RECURRENCE-001 | Two independent occurrences with the same confirmed cause/scope require a hook. Redelivery is not recurrence. Active-hook recurrence requires a version update while preserving the previous verified version. |
| INV-CONTEXT-001 | Required role, goal, acceptance, policy and provenance are never silently truncated. UTF-8 bytes are a conservative composition budget, distinct from measured tokens. External evidence is bounded data. |
| INV-ARTIFACT-001 | Artifact queries address one exact SHA-256 reference under one explicit store root, validate the retained bytes, and emit a deterministic JSON projection whose complete successful stdout is within the requested character limit. JSON pointers follow RFC 6901; paging and search expose explicit continuation cursors. The limit bounds reader output, not arbitrary tool or provider usage. |
| INV-RELEASE-001 | Exact commit/tree and incumbent policy bind lead review, conductor review, incumbent tests and actual CLI canaries. Failed checks cannot promote. Changed commits require new approvals. |
| INV-MODEL-001 | Unqualified tasks run on Astra. Difficulty, model answers and narrow transfer pilots cannot authorize Sol/Terra production routing; versioned task qualification and enforced transfer gates are required. |
| INV-SESSION-001 | Current context at 70% requests safe-point handoff. Checkpoint generation and execution lease fence stale writers. Busy agents do not hibernate; identity survives replacement. |
| INV-GRAPH-001 | Git owns definitions; PostgreSQL owns runtime facts. Graph/vectors are versioned derived views. Unchanged symbols retain IDs; stale evidence cannot enter commit-bound review. |
| INV-RECOVERY-001 | An external host controller restores the previous deployment without Codex. Images are pinned; rollback withdraws that release's hook. Destructive schema downgrade is outside this contract. |
| INV-RESOURCE-001 | Runtime limits have one definition in domain/policy.py. Collection retains pending messages, referenced artifacts and transitive evidence; only aged unreferenced artifacts are removed. A referenced artifact that is missing is reported as lost evidence with a durable event, and a corrupted one aborts collection before any deletion; neither is folded into a healthy result. Hash-linked journals fail closed on any break, and an appended well-formed record never softens that verdict. |

Comments cite invariant IDs and explain non-obvious local reasons, without duplicating policy definitions.
Organization SSOT: `src/codex_harness/resources/organization.json`.
Wire schema SSOT: `src/codex_harness/resources/message.schema.json`.
Runtime policy SSOT: `src/codex_harness/domain/policy.py`.
The trusted local-process identity boundary is documented in status.md; validation is not authentication.

## Research enforcement stage

| ID | Contract |
|---|---|
| INV-RESEARCH-001 | Discovery and historical inventory never imply semantic review. Versioned imports preserve original reference records. Source verification reconciles every raw Git path and object against the pinned commit/tree, not just a manifest hash. Assets outside Git (uncommitted notes, caches, private sessions, nested repositories) are a separate observed-asset ledger per audit: they never enter the tracked denominator, but whole-analysis completeness and adoption proposals share one denominator — every observed asset dispositioned and no open partition questions — a disposition never regresses to pending, and observed records are part of the approval binding. |
| INV-RESEARCH-002 | Partition scope is immutable. Checkpoints require an authorized assigned task, current lease and task/partition generations; evidence history and continuation outbox writes commit atomically. Remaining work reconciles with recorded evidence. |
| INV-RESEARCH-003 | Model-authored receipt IDs are not runner evidence. Missing execution, binary inspection or unresolved subsystem work cannot establish completion. Record tests not run with reasons and follow-up. |
| INV-RESEARCH-004 | Both discovery feeds and legacy approvals lack adoption authority. Positive eligibility requires complete coverage and ordered independent reviews bound to source/evidence/proposal, deployed revision/policy and graph. Revalidate approval and immutable bytes before execution. Reviews are sequenced per binding and actor; a rejection after approval revokes it and the latest review is the verdict, so an earlier acceptance never outranks a later rejection, and redelivery of an already recorded review is idempotent (original sequence kept), so re-approval requires a new review bound to a new inspection receipt. Verified release activation enables dispatch; rollback pauses it without deleting evidence. |

Audit wire schema: `src/codex_harness/resources/research.schema.json`.
Dormant seed definitions: `src/codex_harness/resources/research-backlog.json`.
Remaining integration work is explicit in `docs/research-standard.md`; these invariant definitions
must not be read as evidence that pending execution or rollout integrations exist.

## Bounded conductor measurements

| ID | Contract |
|---|---|
| INV-METRIC-001 | Git versions metric populations and formulas; PostgreSQL retains observations bound to immutable inputs and repository revision. Retries retain failed attempt outcomes. Missing, invalid, stale, future or insufficient evidence is unknown. Undefined targets remain observational. Measurements never authorize promotion or replace independent reviews and actual CLI canaries. |

## Reverse workflow progress

| ID | Contract |
|---|---|
| INV-REVERSE-001 | Reverse-stage records bind source repository, commit, tree and retained artifacts. Unknown or dirty source cannot authorize continuation. Requests are idempotent and generation-fenced; complete predecessors are required; explicit rebaseline preserves prior history. Component integrity is not source-adoption, semantic-quality or deployment approval. See baldrix-reverse-progress.md for remaining integration scope. |

## Project context routing

| ID | Contract |
|---|---|
| INV-PROJECT-001 | Git-pinned project YAML controls eligible skill paths. Missing configuration permits common skills only; invalid profiles fail explicitly. Routing values are parsed YAML scalars validated as path segments, so inline comments never become path text and a scalar containing spaces or `#` is rejected rather than routed; `18` and `3.2` both add their major line (`18.x`, `3.x`), and packaged `SKILL.md` files are collected at any depth below an eligible prefix except under underscore-prefixed directories. Selected regular Git files receive immutable content references and pass through the bounded context compiler. Initialization never overwrites an existing project definition. See baldrix-project-routing.md for scope and outstanding full-migration work. |


## INV-PIPELINE-001

Pipeline output presence is a recommendation signal, not a workflow completion or
approval. Definitions and observed project paths are bound to Git revisions; bundled
upstream assets retain hashes and source provenance. Dirty/untracked outputs cannot
advance recommendations. Pipeline priority cannot include a stack-ineligible skill.
Full recommendation evidence lives in the project-skill manifest, whose digest also
invalidates recovery after definition/output changes. Gate commands are inert data.


## INV-SKILL-001

Prompt relevance and pipeline boosts are recorded separately. A pipeline-only match
cannot satisfy the full-body score threshold. Annotated skill content uses bounded
full-body/pointer tiers; complete bytes remain in immutable artifacts. Pattern evidence
comes only from regular files at the captured Git revision, never host paths or dirty
files. Prompt identity is part of the skill manifest and session recovery binding.

Cross-skill references are advisory one-hop links within the eligible inventory; they
cannot activate an excluded stack. Ambiguous/unavailable names remain explicit. Full
reference evidence survives advisory truncation via immutable handles, and non-skill
guidance never inflates selected/included/omitted skill counters.

Skill metadata is parsed by the bounded string-only YAML loader: inline comments never
enter matcher values, inline lists become string lists, and nested, tagged, duplicated (also after key
normalization) or non-mapping metadata fails explicitly rather than being routed. Routing summaries state
how many skills were inspected next to matched/full/pointer/legacy counts together with the
policy, objective and admission-model identity, so zero matches are never read as
"checked and clean" when nothing was inspected.

## INV-SKILL-HISTORY-001

Skill-history observations are project/content-bound compiled selections, never success
attestations. Retry delivery cannot add samples, including after hot-window eviction.
Leased writes require current task ownership in the same transaction. A task excludes
its own observation from historical assessment. Advisory text and its full skill body
are included or omitted atomically; assessment provenance binds session recovery.
# INV-SKILL-IMPORT-001

Legacy skill telemetry imports bind exact raw bytes to a project/source segment and
advance only a validated append-only prefix. Replays do not add observations; changed
committed prefixes fail. Historical timestamps and unknown content versions are not
replaced with import time or current skill identity. Imported archives do not mutate
live history or become authority to activate skills, hooks, thresholds or releases.

## INV-THRESHOLD-PROPOSAL-001

Numeric proposals use a closed registry disjoint from locked source invariants.
They bind supplied effective current values, Git policy revision, corpus and registry
digests, and temporal holdout evidence. A single allowed step must improve training
beyond hysteresis and pass independent reference replay. Reference acceptance alone
never grants native activation authority. Staging and apply must verify the supplied
basis against authoritative Git and runtime state before changing policy.

## INV-THRESHOLD-REVIEW-001

Threshold assessments require a live execution lease, immutable calculated evidence,
current Git-bound policy and separate lead then conductor execution. Receipt identity
must match the actor, decision, input and revision. Review completion and downstream
review queueing are atomic. An assessment never authorizes implementation, source
adoption, policy activation or deployment; existing approval gates remain required.

## INV-THRESHOLD-POLICY-001

Native routing and proposal collection resolve the same packaged Git threshold
definition. Only implemented, unlocked registry consumers accept finite numeric
overrides. Invalid definitions fail explicitly. Resolved values and definition
identity accompany routing evidence; a calculated or assessed proposal cannot write
the active definition. Candidate promotion and rollback retain release authority.
## INV-NATIVE-REPLAY-001

Native comparison uses the live admission/budget function and immutable full routing
inputs. Recorded full-body hashes, count and truncation must reproduce before any
counterfactual is reported. Missing evidence is unavailable, never success. Selection
and character pressure do not authorize activation or establish task success.

## INV-TICKET-001

The local PostgreSQL ledger is authoritative for ticket contents. Revisions retain immutable
content hashes. Advisory findings bind one revision and record claimed reviewer/provider identity;
they never impersonate authenticated model execution or authorize code adoption/deployment.
Dispatch writes one planning outbox message per revision atomically. Ticket provenance survives
planning, implementation, rejection and rebase. Stale ticket bindings cannot complete tasks,
commit reviews or promote candidates.

GitHub synchronization is explicit and outward. A preview never calls GitHub. Pending projection
hashes and uncertain creation intents survive failures. Uncertain creation without a matching
remote receipt cannot create another issue. External body changes block overwrites; comments
and remote state are collected as observations, never imported as local authority.

## INV-VERIFICATION-001

Release pytest receives only disposable service endpoints, with inherited Zeus/Harness aliases
removed. PostgreSQL and Redis use a unique Compose project, localhost-only random ports and
dedicated storage, without production mounts. Teardown runs on success and failure; stale
cleanup requires matching generated definitions. This isolates service state, not arbitrary
candidate code from the host. Actual execution and infrastructure observation errors remain distinct.

## INV-ENCODING-001

Python children that Zeus launches over its machine channel (release pytest, native hook
canaries) receive `PYTHONIOENCODING=utf-8`, so their stdin/stdout/stderr match the parent's
UTF-8 decoder in both directions. The parent decoder alone is not the contract: without the
binding a Windows child follows the console code page and either crashes on non-representable
text or returns exit 0 with corrupted bytes. The binding covers Python stdio only; it does not
set `PYTHONUTF8`, and does not change the locale of non-Python programs, user terminals or
containers. Tests keep the unbound child as a failure control. Measured through actual child
processes on the current Windows host and Linux CI; direct Windows console-host output and
in-container Python remain outside this measurement.

## INV-EXECUTION-IDENTITY-001

Task selection uses agent and explicit task identity, with UTC creation time and
task id as a deterministic tie-break. A filesystem cwd or heartbeat recency never
selects a task. Malformed scheduling metadata is contained per row. Both new
effects and failure receipt redelivery compare typed task/generation/attempt,
executor owner, agent/actor and recovery sequence. An executor owner is a fencing
token in the trusted local runtime, not an authenticated tenant principal.

Generations advance only through the durable `execution_fences` ledger, which outlives the
task, decision or release-queue row: a recreated row, a regressed generation or a corrupted
fence is blocked instead of re-armed, and a fenced task identity cannot be resubmitted from
generation 0. Every write by an existing handle re-checks the current row's generation and
owner against the fence in the same transaction, so a row restored behind the fence cannot
re-arm its old holder; rows that predate the ledger pass, a corrupted fence fails closed. Row or process existence is never execution identity, and the upstream file
lease is not ported.

## INV-EXECUTION-TIME-001

Timezone-aware UTC deadlines survive restart. Monotonic elapsed time is compared
only inside its recorded process domain and can shorten, never replenish, that
domain's remaining deadline. Foreign/legacy domains use UTC with a recorded domain
observation; they cannot establish elapsed time or detect all offline clock changes.
Observed backwards UTC or same-domain wall/monotonic divergence greater than five
seconds blocks the execution and records its observation and notice. Invalid time
values also block; deadline expiry records expiration. Resumption requires explicit
bounded recovery with cause and evidence. The five-second tolerance also bounds
the optional injected scheduling time; normal execution samples host time.

This contract assumes usable UTC across restarts. OS clock-step, suspend/VM-resume
and multi-host time behavior are unmeasured operating conditions, not certified by
pure clock-input tests or modified stored observations. Their absence must remain
explicit in acceptance evidence. This does not authorize changing the user's host
clock or claim trusted elapsed-time continuity across offline clock changes.

# SDD preparation contracts

- INV-SDD-001: Missing specs, unknown fields, uncovered requirements and reused retired scenario IDs fail validation. Git definitions produce immutable runtime snapshots bound to the current local ticket revision. Superseded iterations cannot append observations or request transitions. Given/When/Then are lists of statements, never one-line strings to be parsed; generated replay drafts embed the spec hash and attribute every assertion at runtime to its scenario, oracle index and requirement IDs, carry spec text only as Python literals without truncation, contain no placeholder or expected-failure skeletons, and are never written over a different existing draft.
- INV-ORACLE-001: Imported observations and structural coverage cannot populate approved expected outcomes, certify real-device execution, authenticate human QA, or authorize a release. Gaps remain visible. Eight-stage reports are preparation only until actual providers are implemented.
- INV-SDD-002: SDD journals retain ordered, hash-linked events; duplicate imports/proposals are idempotent and transitions use compare-and-swap. Notifications are local records, not external messages. Model transfer candidates never change routing authority.
