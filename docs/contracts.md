# Contracts — authoritative definitions

| ID | Contract |
|---|---|
| INV-MESSAGE-001 | All messages are six-W JSON. IDs cannot identify two payloads. DB commit precedes ACK; delivery is at-least-once. Reports match durable completed executions. |
| INV-RECURRENCE-001 | Two independent occurrences with the same confirmed cause/scope require a hook. Redelivery is not recurrence. Active-hook recurrence requires a version update while preserving the previous verified version. |
| INV-CONTEXT-001 | Required role, goal, acceptance, policy and provenance are never silently truncated. UTF-8 bytes are a conservative composition budget, distinct from measured tokens. External evidence is bounded data. |
| INV-ARTIFACT-001 | Artifact queries address one exact SHA-256 reference under one explicit store root, validate the retained bytes, and emit a deterministic JSON projection whose complete successful stdout is within the requested character limit. JSON pointers follow RFC 6901; paging and search expose explicit continuation cursors. The limit bounds reader output, not arbitrary tool or provider usage. |
| INV-RELEASE-001 | Exact commit/tree and incumbent policy bind lead review, conductor review, incumbent tests and actual CLI canaries. Failed checks cannot promote. Changed commits require new approvals. A captured candidate also names its canonical target repository — the normalized GitHub repository (`github:owner/repo`, whatever spelling configured it) or, without a remote, this exact local repository's Git common directory re-read from Git on every check (a clone or copy is another target) — and the hash of the exact base→revision patch beside the preimage base and postimage tree; the runner re-derives the patch and the merge/publish path re-checks the target, so a drifted patch or a reconfigured repository can never consume a review granted for another. Candidates recorded before this binding carry no target and merge as an explicit `legacy_unverified` exception, never as a verified target. |
| INV-MODEL-001 | Unqualified tasks run on Astra. Difficulty, model answers and narrow transfer pilots cannot authorize Sol/Terra production routing; versioned task qualification and enforced transfer gates are required. |
| INV-SESSION-001 | Current context at 70% requests safe-point handoff. Checkpoint generation and execution lease fence stale writers. Busy agents do not hibernate; identity survives replacement. |
| INV-GRAPH-001 | Git owns definitions; PostgreSQL owns runtime facts. Graph/vectors are versioned derived views. Unchanged symbols retain IDs; stale evidence cannot enter commit-bound review. |
| INV-RECOVERY-001 | An external host controller restores the previous deployment without Codex. Images are pinned; rollback withdraws that release's hook. Destructive schema downgrade is outside this contract. |
| INV-RESOURCE-001 | Runtime limits have one definition in domain/policy.py. Collection retains pending messages, referenced artifacts and transitive evidence; only aged unreferenced artifacts are removed. A referenced artifact that is missing is reported as lost evidence with a durable event, and a corrupted one aborts collection before any deletion; neither is folded into a healthy result. Hash-linked journals fail closed on any break, and an appended well-formed record never softens that verdict. |

Comments cite invariant IDs and explain non-obvious local reasons, without duplicating policy definitions.
Organization SSOT: `src/codex_harness/resources/organization.json`.
Wire schema SSOT: `src/codex_harness/resources/message.schema.json`.
Runtime policy SSOT: `src/codex_harness/domain/policy.py`.
Guidance-document conventions (layers, one owner per rule, actual delivery): `docs/context/README.md`.
The trusted local-process identity boundary is documented in status.md; validation is not authentication.

## Research enforcement stage

| ID | Contract |
|---|---|
| INV-RESEARCH-001 | Discovery and historical inventory never imply semantic review. Versioned imports preserve original reference records. Source verification reconciles every raw Git path and object against the pinned commit/tree, not just a manifest hash. Assets outside Git (uncommitted notes, caches, private sessions, nested repositories) are a separate observed-asset ledger per audit: they never enter the tracked denominator, but whole-analysis completeness and adoption proposals share one denominator — every observed asset dispositioned and no open partition questions — a disposition never regresses to pending, and observed records are part of the approval binding. |
| INV-RESEARCH-002 | Partition scope is immutable. Checkpoints require an authorized assigned task, current lease and task/partition generations; evidence history and continuation outbox writes commit atomically. Remaining work reconciles with recorded evidence. Assigned partition output binds one result to each assigned identity: `paths` and `subsystems` are closed objects keyed by exactly the assigned path/subsystem identities, each key required once and carrying either `null` (not analyzed; the identity stays in remaining work) or one record body without its `path`/`name` field, which the boundary injects from the trusted key. A missing, foreign or inner identity, an array of rows, a malformed body or an unknown key is refused before the domain decode and before the checkpoint, never deduplicated, merged or normalized; an empty assignment is `{}`. An unscoped `partition_schema()` keeps the generic array shape for inspection only. The checkpoint's own duplicate-coverage and scope guards stay authoritative. A draft this boundary refuses is RETAINED WORK, not a stopped execution. The trusted stored partition is validated before any generated content is decoded; an execution failure is not always a raised exception, so a RETURNED `inspection_blocked` result from either the planning or the semantic turn is classified as a stopped execution BEFORE that decode, with a fixed error that never quotes, logs or projects the returned reason, and blocked wins even when the same result also carries otherwise valid content (a refused planning turn runs no inspection command and no semantic turn). A candidate draft can pass type validation and still fail relationship and evidence-claim validation, so the recoverable rejection is the whole CANDIDATE-CLAIM boundary, told from execution integrity by TYPE and OWNER and never by the wording of a message. Two owners raise it. First, the pure decode of paths, subsystems, cursor and open questions into the proposed checkpoint — which touches no store, lease, runner, artifact or provider — where any `ContractError` is a content refusal. Second, `ResearchAudits.checkpoint`, which raises the typed `AuditDraftRejected` (a `ContractError` subtype, so every existing caller and message is unchanged) for the claims the draft itself makes: duplicate or cross-partition records; links or subsystem trace paths that are not inventory identities; an unsupported submodule or binary classification; a receipt claim that is missing, foreign to this audit or task, of another generation, blocked or unsuccessful; a test command with no matching successful execution; and its own remaining-work reconciliation. Every path reference — assigned keys, `PathDisposition.links` and `SubsystemAnalysis.paths` — is the exact inventory Base64 identity; a display name is narrative only, a claim is never silently encoded, decoded, normalized or deduplicated to fit, and this validation stays authoritative whatever the model instructions say. A model-named artifact reference is a candidate claim ONLY when it is absent (`FileNotFoundError`) AND is not one of this audit's authoritative anchors — the verified `source.manifest_ref`, the verified inventory `artifact_ref`s, the evidence its partitions and checkpoints already retain, and the stored runner `output_ref`s — all read from trusted records; a missing anchored body, any modified body, invalid or missing metadata, a permission error and every other IO failure stay execution failures. Ownership, lease, assignment and current generation and the immutable trusted scope are validated BEFORE any relationship classification. The checkpoint transaction stays all-or-nothing: a rejection raised after staged writes leaves that transaction first, so no coverage, history, checkpoint, partition, outbox or knowledge row of a refused batch is ever committed, and `AuditExecution` catches ONLY `AuditDraftRejected`, outside that transaction, before inspecting the executor-owned output. The refusal becomes one explicit versioned `analysis_rejected` result binding task id, task generation and attempt, audit, partition and partition generation, the executor-owned `execution_ref` and a fixed reason code with the refusal's type and the digest of its message. No raw exception, model or source text enters that result. A rejection checkpoints nothing, advances no generation, drops no scope, writes no evidence or knowledge and is never a successful review; the refused content stays in its existing immutable artifact and its identity stays in remaining work until an explicit reviewed decision. Absent, unreadable or modified rejection evidence, a stale or corrupt assignment, and every provider, runner, lease, store, commit, receipt, ownership or continuation-authorization failure remain execution failures and are never converted into an outcome — including an ordinary `ContractError` carrying exactly the same text as a candidate refusal. Valid content still uses the unchanged checkpoint and carries an `analysis_checkpointed` marker with the same binding and the persisted checkpoint untouched: a checkpoint is partial progress, never semantic acceptance, and a result carrying neither marker is unclassified and is never newly inferred to be either. |
| INV-RESEARCH-003 | Model-authored receipt IDs are not runner evidence. Missing execution, binary inspection or unresolved subsystem work cannot establish completion. Record tests not run with reasons and follow-up. One named domain vocabulary (`PATH_DISPOSITIONS`: unreviewed, semantic, generated, duplicate, binary, unavailable) governs path dispositions: the packaged schema, the generated provider output schema and its definition nested in partition output declare exactly those values, so a partially read path is `unreviewed` with its explanation and remaining work (or an omitted identity) and earns no coverage. Any other value, including `partial`, is refused by both boundaries and never normalized to a reviewed disposition. |
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
Each observed selection records score and, from the sealed context packet rather than the
selection manifest, the tier that actually entered the final context (a skill the budget
dropped is `omitted`, never `full`) with the hash of the admitted body; the record names its
evidence stage (context compiled, before provider submission), which is not model reach.
Audits report raw match, rank-first and body-arrival counts as separate targets; no blended
precision/recall is derived across different decisions, and model behavior is declared
unmeasured by telemetry.
Leased writes require current task ownership in the same transaction. A task excludes
its own observation from historical assessment. Advisory text and its full skill body
are included or omitted atomically; assessment provenance binds session recovery.
## INV-EXPERIENCE-001

Imported upstream experience (lesson) records are claims, not evidence. Each claim binds the
source name, upstream path, exact bytes and rule version; the original `occurrences`, `trust`,
`lifecycle` and `evidence` fields are preserved verbatim under `upstream` and never copied into
Zeus incident, hook, review or release state. Independent occurrences are recomputed only from
evidence tokens that identify one incident each; cumulative counters (`ledger:PASS xN`) and
note locations (`repair-notes:*`) count zero, so a record without identities stays
`upstream_occurrences_unverified`. Re-import of identical bytes changes nothing; different
bytes of the same path are separate versions. The acquisition basis (observed bytes, pinned
commit) is separate from the content claim: the same bytes seen on another basis add an
acquisition to the existing claim, never a version or an occurrence. Claims live in their own bucket and do not
participate in INV-RECURRENCE-001 counting.

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
Observations of one ticket read back in the order they were recorded, by a sequence assigned
in the ledger transaction; the wall clock never decides that order, so two observations made
within one clock tick cannot swap.

## INV-VERIFICATION-001

Release pytest receives only disposable service endpoints, with inherited Zeus/Harness aliases
removed. PostgreSQL and Redis use a unique Compose project, localhost-only random ports and
dedicated storage, without production mounts. Teardown runs on success and failure; stale
cleanup requires matching generated definitions. A service is ready only when its published
loopback port accepts a connection from the harness process, checked with a bounded wait after
the container healthchecks and recorded as ready_after_seconds; a stack that never becomes
connectable fails entry and is cleaned up. This isolates service state, not arbitrary
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

## INV-IDEMPOTENCY-001

Same-key deduplication reads and writes inside one store transaction, serialized by the
control-plane advisory lock (PostgreSQL) or the store lock (memory); no check-then-append
across transactions. Receipts are keyed by durable identity (message, request, failure or
recovery digest) and a redelivery returns the recorded result or is rejected when its content
differs. External side effects follow one of two shapes: intent committed before the call and
a receipt committed after it, where an intent without a receipt is pending and never treated
as done (outbox attempts); or reconciliation from the external system's own state (GitHub PR by
head revision, merge uncertainty as `blocked_remote`, image by digest). A lost acknowledgement
therefore repeats or blocks explicitly; it never silently completes or duplicates.

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

Execution progress records are written only under the current lease and carry the task
generation and attempt, a per-record sequence, a unique event identity, and the event's
own occurrence time separately from the collection time (absent occurrence time stays
null); a stale generation cannot write progress, and a malformed runtime event is retained
as evidence and counted instead of being dropped or allowed to overwrite the last
well-formed state.

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

One execution's time limit is a ceiling built from the shortest applicable source, never a grant:
the single policy default for the role (`domain/policy.py`, a worker task or a decision), the
remaining time of the execution's own durable deadline, and any explicit provider control the host
configuration declares. Changing a default changes what is allowed at most; it never extends a
recorded deadline, a lease, a heartbeat interval, a command-evidence replay window or a retry, and
it never re-dates a manifest that was already queued.

This contract assumes usable UTC across restarts. OS clock-step, suspend/VM-resume
and multi-host time behavior are unmeasured operating conditions, not certified by
pure clock-input tests or modified stored observations. Their absence must remain
explicit in acceptance evidence. This does not authorize changing the user's host
clock or claim trusted elapsed-time continuity across offline clock changes.

## INV-THRESHOLD-APPROVAL-001

Calibration evaluates unique executions: a corpus is deduplicated by observation identity (or
exact content when unidentified) before any metric runs, and every proposal carries its
denominator (collected, unique, duplicates, unidentified, unscored, invalid) and evaluation
scope (source, policy revision, time range). A candidate value that would admit no entry in
the trailing or held-out window is rejected by the gate as `empty_admission`, whatever the
pinned precision returns for an empty admission. An approval exists only for a request both
independent assessments accepted, and it binds the exact threshold name, current value,
proposed value, policy revision, evaluation evidence reference, corpus hash, registry hash,
reviewers, issuing actor, target environment and expiry; the same binding is one approval.
Certifying an application is a conditional transition consumed exactly once: the applied Git
policy must move only that name, from exactly the approved current value to exactly the
approved proposed value (same type), on top of exactly the assessed previous revision, to a
different revision, in the approved environment, before expiry. Every refusal is recorded as
its own event and consumes nothing; a consumed or revoked approval certifies nothing further;
issued, consumed, revoked, expired, missing and corrupt are distinct states. The approval
never writes the active definition and never authorizes routing, graduation or deployment.

## INV-INVOCATION-001

A model invocation is a typed request against a declared transport support matrix: unknown
options and options the transport does not support are refused before execution with their
names, never silently dropped, and invalid types or values (empty model, non-finite or
non-positive timeout, empty schema) are refused the same way. A probe proves an executable and
at most a version; it never proves model readiness or qualification, and registry lookup is not
availability. Before the call, the attempt reserves one invocation in the transaction that
re-proves current ownership; an attempt holds at most one open reservation, open reservations
are the concurrency budget, and a reservation that never settles is closed as
`unsettled_unknown` with unknown usage when the next attempt reserves or the transport raises.
The result is classified from what was observed — accepted, empty answer, invalid output,
tool-only, interrupted, inspection-blocked, provider failure — so a clean exit with no answer is
never acceptance. Usage names its source event and basis; absent usage is unknown, never zero,
and unknown usage is excluded from measured sums. The requested model and the model the
transport reported are separate fields; an unreported model stays unknown. The raw event stream
is hashed (surrogates preserved) and kept with the execution evidence.

## INV-BREAKER-001

Provider admission is a committed, generation-fenced state transition in the control-plane
store, never a boolean from a file. A breaker is keyed by typed lowercase provider and scope
tokens hashed together (aliases and path-like parts are refused, not folded). Admission
returns a token naming the generation, policy revision, task, attempt and time it was granted
under, and only a committed transaction can return one: a store that cannot write admits
nothing. An open breaker refuses until its cooldown elapses; half-open holds exactly one probe
reservation bound to its holder with a TTL, an expired reservation is reclaimed under a new
generation, and a result reported against any other generation is recorded as stale and
changes nothing, so an old holder never closes or opens the slot a new holder owns. Unknown
results (interrupted, cancelled, unproven) release the slot without a verdict; only provider
failures and transport deaths count as failures, and malformed output is not a provider
failure. Failure history folds over unique events ordered by time inside the window, so
duplicates and input order cannot change the count. Policy is validated on read and on write
(integer-not-bool counts, finite positive durations, threshold within retained history, probe
TTL within the window, Git or explicit unversioned revision) and a written policy is applied
only when it reads back equal. Missing, corrupt and unreadable state are distinct from a new
breaker and none of them is quietly closed; corruption records a notice and requires repair. A
closed breaker admits calls and authorizes nothing else: not acceptance, graduation or deployment.

## INV-SEAM-001

A seam contract observation is typed: a qualified identity (stack, package, name — the same
short name in another package is another contract, never dropped), a kind, members with name,
type, tag and byte span into the exact blob, a fidelity claim, a denominator (symbols found,
unresolved) and a source identity (path, blob hash, revision, parser). HIGH fidelity cannot
coexist with unresolved members; an extractor that could not read, decode, parse, or does not
support a stack returns an UNKNOWN observation with a named state, never a regex HIGH. Spans
are computed on the original bytes with no comment stripping or renumbering. Discovery sorts
before it caps and counts what it omitted; discovery and parse denominators are separate. A
transform is a closed schema (unknown options are refused, never ignored) whose effective
mapping is computed over the whole input set including passthrough values; any collision or
empty target is NEEDS_TRANSFORM, and a declared non-identity that changes nothing is reported
as effectively identity rather than trusted as a mapping. Comparison is directional under a
versioned policy that names the compared keys; fidelity below HIGH is BLOCKED; agreement on
names, types and tags is textual and is not compiler, serialization or product compatibility.
A comparison is advisory; only a reviewer, under a Git policy revision and with a reason, makes
a DRIFT blocking-eligible. An imported ledger keeps every prior valid record, reports each
corrupt line, and a partial audit never presents itself as complete or current.

## INV-CHECK-001

A release check is evidence about one candidate only when its receipt binds the tree it ran
against: the workspace path, the candidate revision the runner expected, the HEAD Git actually
reported there and whether the tree was clean, plus the environment keys and the argv. A check
whose workspace HEAD is not the candidate or whose tree is dirty is `revision_mismatch` and does
not run; a workspace whose revision cannot be observed is `observation_error`, never a verdict.
A test run passes only by its parsed denominator — executed tests greater than zero and no
failures or errors — so an exit status of zero with everything skipped, deselected or no
tests collected is `empty_check`, unparseable output is `unstructured_output`, and a summary
that reports failures outranks a zero exit. When the verification runner cannot establish its
isolated services the run stops before any test check with an observation-error receipt and
the release stays reviewed; nothing downstream is a pass. Zeus installs no Git hooks; native
Codex hooks are verified per candidate manifest and discovered through the transport, and no
installation success, file presence or string marker is a check result.

## INV-RUNNER-001

An isolated source run is named by where the attempt ended and what it produced, never by an
exit status alone. Materialization or runner start failures are `isolation_unavailable` with
the failing stage and error; they are never substituted by a run in the host environment. A
runner client that outlives its deadline is `client_timeout` and the uniquely named container
is removed regardless. In-container deadline exits (124, 137) are `timeout`; the runner's own
exits (125-127) are `runner_error`, not the command's verdict. An executed command passes only
with exit 0 and observable stdout: exit 0 with no output, or with diagnostics only on stderr,
is not a pass; a pytest command passes only by its parsed denominator (INV-CHECK-001), and an
assertion message is never read as a missing dependency. Every receipt carries the command,
the runner mode, output digests, the category and, when dispatched from the queue, the
request, owner, task and generation it ran for.

## INV-SNAPSHOT-001

A confirmed snapshot is verified against a closed manifest that names every required file, its
kind, its schema version, its required fields and its references. Every line of every required
file is checked: a line that is not an object, lacks a required field, carries another schema
version, contains a non-finite number or cannot be parsed is corrupt and counted, never dropped.
A missing file, an unreadable file, a corrupt file and a legitimately empty file are four
distinct states, and "0 records" is reported with the state that produced it. A torn trailing
line is tolerated only in live mode as a line that is not yet part of the confirmed set; in
confirmed mode it is corruption. A reference to an id that no required file declares dangles and
invalidates the snapshot. The verdict carries the whole denominator (files required, present,
valid, empty, missing, unreadable, corrupt; lines total, corrupt; records valid; torn tails;
dangling references; extra files). An import archives the exact bytes, binds the source, tool
and environment revisions and the manifest hash, records valid and invalid snapshots alike, and
lets only a valid snapshot be consumed; an invalid one never touches runtime state. A change
names the checks it obliges through an explicit path policy; a change that obliges no check is
stated as such and is never a passed check, and an unmapped change is named, never silently
unchecked. Zeus's own CI runs every job on every push and pull request without path filters;
commits marked to skip CI carry no check result at all and must not be read as green.

## INV-MIGRATION-001

The database migration tool is pinned: `zeus-sql-migrator@1` with the filename contract
`V?<n>(.<n>|_<n>)*(__<description>)?.sql`. A version is normalized to its integer components
(`V01`, `V1`, `001` and `V1.0` are the same version; `V1_2` and `V1.2` are the same version;
`V08` is eight, never an octal error) and compared component-wise, never by its first number
or lexically. A `.sql` file whose name does not match the contract is refused by name; it is
never skipped, and a run that saw one never succeeds. Files with other extensions are listed
as ignored, not treated as migrations.

Every configured location is identified by module, vendor and path and classified as found,
empty, missing or unreadable with the exact error; a location the discovery did not observe
is unknown. Missing, unreadable and unknown are never empty; a required scope in any of these
states refuses, and an optional one is stated as not applicable. The vendor list of one
module never overwrites another's. Filename parity across the vendors of a module, the SQL
content of the target vendor (empty, oversized and undecodable files are named), the applied
history and the live schema are four separate results; a single vendor makes parity not
applicable, not ok, and an unobserved required vendor makes it unknown. Apply is allowed only
when every result is ok or not applicable; unknown is never approval.

An applied version is immutable: the checksum recorded at apply time must equal the file's
checksum, an applied version without a file cannot be verified, and a new version lower than
an applied one is out of order. "Use MAX+1" is guidance, not a guarantee: apply re-reads the
history under the control-plane advisory lock, refuses if any result changed, executes pending
versions in normalized order and records version, checksum, name, tool and actor in the same
transaction, so two concurrent appliers record each version exactly once. A statement that
fails leaves no history row and no partial schema change of that version.

A precheck or apply is evidence only as a receipt that binds the operation, the exact argv,
the parsed config digest, the root, the source revision, the environment label, the exact
stdout and stderr bytes and the exit code; a refused run (exit 1) and an errored run (exit 2)
are recorded as such and never as success. Only a precheck whose recorded tool equals the
pinned tool, that completed with exit 0 and allowed apply, and that is bound to the same
revision and environment can approve an apply. None of this is deployment approval: the real
Windows/Linux/WSL install, upgrade, interrupted-recovery and data-preservation runs, the money
scenarios and the human acceptance they require are not performed by this contract, and no
document count, quality score or gate table substitutes for them.

## INV-EVIDENCE-001

A worker's evidence claim is typed (a file with optional content hash and line range, or a
command with its expected exit status); free text is at most a command claim of expected exit
zero. Inspection yields exactly one of checked, not_checked, missing, unknown, error,
replay_failed, flake_pattern or verified_mismatch, always with a cause; there is no CLEAN, a
directory or an unrelated file is not evidence, a permission or stat error is unknown, and an
inspection whose claims were not all checked is incomplete. File checks and command replays
share one explicit context: the workspace the claims came from, the candidate source revision,
the policy hash and a minimal recorded environment; nothing is ever resolved against the
inspector's own cwd. A model-written command is never authority: only an argv prefix listed in
the Git-defined evidence policy is replayed, in a bounded child (finite positive per-command
deadline within an aggregate budget, claim count and output byte caps, process-tree
termination recorded), and identical replays that disagree are a flake pattern. Raw stdout and
stderr bytes are archived byte-for-byte with their hashes; a decoding problem is a recorded
property of the output, never a replacement. Inspections are ledger rows bound to task,
generation, attempt, owner and revision; a recording failure is a notice, never a success; and
a checked inspection is deterministic evidence, never historical truth, semantic review, human
acceptance, SDD acceptance or model qualification.

A Python replay runs the trusted host interpreter, the verified absolute `sys.executable` of the
harness, never the first token the model wrote: authorization is decided on the original claim
argv, and only an authorized `python -m ...` claim has its first token replaced; every other
authorized command runs exactly as claimed, no policy prefix is widened, and a claim naming an
absolute or other interpreter stays unauthorized. The finding keeps the original argv, the
effective argv, whether they are identical and the reason they differ. A missing or unverifiable
interpreter is a refusal before any child starts. The snapshot is taken per workspace and binds
the interpreter, the normalized cwd, a PYTHONPATH that is the candidate's `src` only when it
exists (the parent's PYTHONPATH and the harness's own secrets are never inherited) and the digest
of the environment values; the replay runs under exactly that snapshot whatever the parent
environment has become since, and the ledger key includes it, so a changed cwd, value or
interpreter is a new inspection and an older row is neither reused nor overwritten. A worker's
`tests` answer holds only commands that were executed, one per string; results, skips and unrun
work are stated in `summary`, and past claims are parsed as written, never leniently reinterpreted.

The execution lease covers the replays, not only the provider call. A heartbeat taken when the
provider returns says nothing about the minutes an inspection then spends in child processes, so
the owner's check travels with that work: the caller passes one per-call progress/cancellation
callback into the inspection, it is invoked before and after every command and between the bounded
polls of every wait, and it is never module state, a shared callback or a detached renewal thread.
It re-reads ownership and the remaining deadline through the existing workflow and renews at the
existing cadence and lease duration; nothing here makes a lease longer. A refusal - lost or
superseded ownership, an exceeded deadline, or a failure of the callback itself - starts no further
replay, reclaims the owned process tree (and, in the isolated backend, stops and confirms the exact
container) through the existing cleanup, and leaves no ledger row: a stale owner publishes neither a
verdict nor a success, and its refusal keeps its own type for the caller's containment path. A
caller that supplies no callback, and an inspector that declares none, keep their previous behaviour
exactly, and the callback takes no part in the inspection identity or its digests.

That check covers every production inspector route - the host inspector, the isolated container
backend and the host project-profile inspector - and its cadence throttles only the intermediate
polls of one wait: at every boundary (inspection start and end, each command start and end) the
ownership and deadline read is taken fresh, so a verdict read seconds earlier never authorizes one
more child or one more publication. Renewal keeps its own longer cadence. The ledger is fenced by
the same owner inside its own transactions: the caller's guard runs in the transaction that reads a
cached inspection and in the transaction that looks up and writes the row, opening none of its own,
so a cache hit is no more exempt than a new publication. A guard refusal is the caller's ownership
failure, raised unchanged with no row written and no inspection-recording-failure notice, because
the ledger did not fail; the production executor always supplies one, while a caller that supplies
none keeps its previous contract and transaction count. Injected ownership loss in tests is contract
evidence, never evidence of a recovered live operation.

An independent review runs in a clean checkout at the candidate commit. The transport's read-only
instructions, the repository's AGENTS.md and the executor's post-run checks say the same thing: no
file in that checkout is created, modified or deleted, tracked or untracked; test output is read
from stdout, never redirected into the checkout; the one concise review frame and verdict live in
the response and tool output that Zeus preserves in its artifact store outside the checkout; and a
dirty checkout or a moved HEAD is refused, never cleaned. The host, not the model, names the
trusted interpreter and the review checkout (with its `src` when present) in the reviewer's
context, so the tests a reviewer runs exercise the candidate under review. A model run's
permission settings are not claimed as an isolation guarantee.
## INV-SEAM-VIEW-001

A seam view is a deterministic projection of recorded observations and comparisons, never a
ledger of its own: equal inputs in any order produce byte-equal output, and the view carries a
generation receipt (generator, inputs hash, view hash). Each node states its provenance —
observed (HIGH), extracted_partial (LOW), unavailable (UNKNOWN) or declared_only (required by
policy, never compared) — and each edge keeps producer and consumer roles, direction, verdict,
fidelity on both sides, the effective transform and the comparison it came from. `live` is
reserved for an OK comparison between two HIGH observations and never means observed traffic
or acceptance; BLOCKED, unknown and declared-only seams stay visible and are never live. The
gate policy is a closed vocabulary (fail-on names must be DRIFT, NEEDS_TRANSFORM or BLOCKED; a
typo or an empty list is refused) with a non-empty set of required seams; the gate passes only
when every required seam is present and OK, fails on a listed verdict, and is otherwise
undecided — a required seam that is BLOCKED or missing never passes, and zero obligations are
not a policy. The SDD gate report keeps separate denominators for declared scenarios, imported
observations, runner-executed scenarios, verified assertions and human acceptance; imported
claims, generated skeletons and marker removal never count as executed or accepted.

## INV-SEAM-SCOPE-001

A seam check names what it can see. Every observation declares its covered check scopes (an
extractor states them; an unknown observation covers nothing), and an approved comparison
policy names the scopes the specification requires — member names, types and tags, envelope,
RPC, response types, error mapping, storage, execution, human scenario. A comparison reports,
per required scope, whether both sides covered it and the policy compared it; OK speaks only
for the checked scopes, every other required scope is unverified, and an OK with unverified
required scopes is not live and never passes a gate. Byte identity of the source blobs and
equality on the checked scopes are recorded as separate facts; neither implies the other. A
shared literal value links contracts only through its type-and-tag identity and is a
coincidence of declarations, never causal message delivery. Every observed contract appears in
the view, including those no recorded comparison names, which are marked undeclared.
## INV-PROFILE-001

A profile data flow exists only as a versioned policy that names the collected record fields
and their purpose, the read scope (kinds, record and character caps, projects), the model and
its transport, temporary and permanent retention, and the user notice. The notice may claim
only what the policy enforces: "no external transfer" requires a local transport and "raw text
is not retained" requires profile-only permanent retention; a wider notice refuses the policy
itself. The policy hash identifies the contract.

Consent binds one user to one policy hash and to projects inside the read scope; cancel and
questionnaire are preserved choices that collect nothing, a grant without projects collects
nothing, and a preference inferred later is never authorization, approval or model
qualification. Collection under any other policy version needs new consent.

Every record is minimized before it can become model input: only policy fields survive, the
content is capped, then scanned, then redacted, and the project path is replaced by a
non-reversible reference. A record carrying a private key, a credential or a token is blocked
from model input, not masked. Read failures, parse failures, out-of-scope kinds and
non-consented projects are separate named results that produce no input, and each names the
fields it could not check. The ledger keeps statuses, counts and kinds; it never keeps record
text or matched values, and an output-stage filter never stands in for this input-stage
minimization.

`evidence` and `evidence_quotes` normalize to one schema; when both are present they must
agree, and unsupported fields refuse. Every rendered field of every dimension (evidence,
summary, instruction, project, signal, metadata) is scanned or named unchecked; "none
detected" is said only about checked fields, and a profile with an unchecked field or a
finding is not renderable.

A temporary bundle belongs to its run: it is written atomically with an owner, a lease and a
digest, read only by its owner after digest verification, deleted only by its owner or by an
expired lease, and never by age or name prefix; a bundle whose process died is preserved for
its owner to resume, and a tampered bundle is preserved and not used. Every run is bound to
its source revision and environment. None of this is a user acceptance, a privacy
qualification or a deployment.

## INV-COMPLETION-001

A task row's `succeeded` status is the executor's self-report; completion authority comes
only from a completion verdict bound to that execution. Verdict records use a closed,
versioned schema: an unknown or missing schema version, an unrelated event name, a verdict
that is not one of approved/iterate/escalate, a non-finite or naive or future observed time,
a caller-supplied completeness or cross-target flag, and every unexpected key are refused as
structured errors and kept as rejection notices, never as evidence. Each verdict binds the
task, generation and attempt (checked against the PostgreSQL-owned row in the same
transaction), the spec revision, the evaluation artifact hash, a runner invocation receipt
whose target must equal the verdict's, and a named reviewer; cross-target is derived from the
receipt. The current verdict is the last recorded one for the current execution, spec and
artifact; observed time never orders verdicts and a redelivered verdict keeps its original
sequence, so an earlier approval never outranks a later rejection. Approval grants authority
only when every expected scenario passed or carries a human-approved exclusion with a revision
and reason; an empty scenario denominator is incomplete. Missing ledger, corrupt or partially
corrupt rows, an unreadable store, rejection-only and not-evaluated are distinct states and
none of them grants authority; no cold-start path waives evaluation. Dispatch does not consult
this ledger yet; consumers opt in explicitly.
## INV-OUTPUT-001

Structured output is validated against a declared, versioned subset of JSON Schema draft
2020-12: every keyword a schema uses must be in the supported subset, so a misspelled or
unsupported keyword is refused at preflight as a configuration-owner error instead of a
check that silently never runs; enum and const require an explicit type; a closed object
cannot require names it does not declare; nesting depth and encoded size are bounded; and
numeric bounds are finite. Preflight returns a receipt (schema hash, dialect, subset
version, keywords seen, checks run) and every output validation result carries a structural
block naming each check as checked, failed, unchecked or configuration_error, so "ok"
always says what was checked. Failures are owned: an agent output defect (`agent_output`)
is never the same finding as a malformed schema (`configuration`), and a valid-looking
answer under a refused schema is not accepted. Runner-observed tool use (completed command,
file-change and MCP items from the transport) is recorded beside any self-reported tool
list, with the comparison stated; a self-report never certifies the presence or absence of
tool use. Zeus keeps no lexical, filename or boilerplate grade; structural validity and
observed tool use are evidence for review, never SDD acceptance or model qualification.

## INV-OBSERVATION-001

General, development and operations logs share one versioned observation contract
(`observation.schema.json`, `urn:zeus:observation:1`) that is a different contract from the
six-W business message: an observation has no who/what/how sections, cannot be validated,
routed or handled as an assignment, and grants no workflow authority; the outbox relay
quarantines one disguised as a message. Every record names its execution (role, provider,
process run, task, bucket, generation, attempt, invocation, revision) or is a system event whose
task and session are explicit nulls, never placeholders; the schema validates the two branches
separately. `occurred_at` is the event's own time or null and `observed_at` is the collection
moment; order is (process_run_id, sequence) and causality is causation_id plus the existing task,
message and generation identities, never the wall clock. The outcome vocabulary distinguishes
started, succeeded, failed, aborted, blocked, unknown and observed; a provider exit code or a
transport acknowledgement never produces a success outcome, and a stream entry id is recorded as
a delivery fact beside the attempt, not as a task completion. Attributes are allow-listed and
typed per event type and size-bounded; prompts, environment, credentials, private keys and model
reasoning are excluded by construction and every string is redacted before any durable or public
surface (spool, sink, health record, alert, CLI); foreign error messages are recorded as their
type and digest, not their text. The same event id with the same content hash is a redelivery;
the same id with different content is isolated in quarantine with an alert and never overwrites
the first record. Mandatory transitions (invocation reserved, settled, abandoned; outbox publish,
retry, error, quarantine; reconciliation) are append-only audit rows written inside the business
transaction, so the reservation does not commit — and no provider starts — without its audit.
Diagnostic records go to a bounded per-process durable spool whose sequence number advances
only on a successful append; a full or failing spool is counted, written to the protected local
health record and alerted with rate limiting, never dropped silently, and never blocks the
execution path or bypasses reservation and lease limits. The collector consumes complete
records, quarantines corrupt lines, leaves a truncated tail unconsumed, deduplicates by id and
content hash, acknowledges an offset only after the sink transaction committed, and reclaims a
segment only when it is fully acknowledged and provably no longer writable — rotated past, closed
by its writer, or its run lock released by the operating system when the writer died; file age
alone never finishes a run, so a spool that is consumed never saturates, an active segment is
never truncated and a live but idle writer keeps its collectable path. Only the writer that
holds the run lock finishes the run: a writer object that never acquired it (a refused second
writer) writes no closed marker, a closed writer refuses further appends, and a run's lock
file is unlinked only under that lock. The retention age of a run is measured from the files
its writer wrote (segments, closed marker, health) before any liveness probe, never from the
lock or acknowledgement files, so probing cannot defer a dead run's reclamation. A writer's
registration (run lock plus active segment), its close, every liveness probe and every
deletion by the collector run under one directory lifecycle lock that no run's garbage
collection removes: the collector decides and deletes as one step, a writer registers as one
step, so a writer either registers before the decision and keeps its active file or starts
after the deletions on a valid path; a successful append never leaves a record without a
collectable path, and a busy lifecycle lock defers collection and refuses registration
explicitly instead of guessing. Pending alerts replay in
their own transaction, independent of any spool record. The check that no earlier attempt of a
task is still unconfirmed is made inside the reservation transaction; a failed read is unknown,
never permission. Correlation, causation and
evidence identifiers are opaque handles and are refused, never rewritten, when they are not;
operator labels follow the same rule and operator free text is redacted and bounded before it is
stored or returned; identifiers that match a known credential shape are refused as well. The
reservation transaction also writes a durable unconfirmed marker for the attempt, before any
provider is entered; the marker closes only in the transaction that durably accepts the outcome
(task completion, decision commit or a recorded terminal decision), in the abandonment of a
refusal proven to precede entry, or with the failure record of an observed rejection of an
already persisted answer. Any other failure while the marker is open — transport, progress,
cleanup, settlement, breaker report, result persistence, checkpoint, acceptance write, workspace
capture — records the failure, blocks the task and notifies the lead through the existing
execution notice in one transaction, and adds redacted termination evidence naming its boundary
where it can; a failing evidence file or sink does not weaken the block. Failure records built
from a foreign exception carry its type and digest, never its text. Reconciliation commits the
operator's decision and audit to the sink before the
local blocking record is finalized, is idempotent for the same decision and refuses a different
one; re-queuing goes through execution recovery, which refuses while any termination record is
pending. Pending alerts are persisted locally, cleared only after the transaction that carried
them committed, and inherited by the next process run. The invocation ledger closes an orphaned
reservation as unsettled_unknown. Health, status, orphan and alert reports are informational
only. Two failure boundaries are observable without reading a raw stream, and neither decides
anything. One evaluated output is recorded after its durable receipt exists — the receipt result
persistence returned, or the one its ExecutionFailure carries — naming the ledger's own
classification beside the structural output reason and its owner, the provider's own failure cause
and reported result subtype, which structural checks ran, and the artifact reference; the event
explains a refusal, it never re-decides it, and a refused output stays refused. The evidence
inspection records its start with the number of claims and its end with the verdict it actually
reached, including no claims, incomplete and a failed inspection, with the denominator as typed
counts and a fixed reason code; only a completed all_checked inspection is recorded as succeeded,
an unknown or failed one never is, and the verdict, the ledger row and the review gate are
unchanged by the record of them. Every code on these events is a declared value: a foreign or
future provider string is `unknown` and an absent one is `none`, so nothing is inferred from a
subtype, except that a declared terminal subtype naming its own actionable failure also names the
projected reason code, so retry-exhausted structured output is readable apart from every other
provider failure while an undeclared subtype reaches no reason of its own and a structural output
reason still wins; and a failed inspection carries its exception's type and a digest of its message — the
same rule the failure records follow — on the log and on the result it returns, never the message
itself. Prompts, answers, schema property names, commands, stdout and tool arguments are excluded
by construction here as everywhere else. Unit fault injection and MemoryStore exercise these
boundaries; they are not operational evidence.

## INV-CLAUDE-WORKER-001

Zeus runs one default provider and admits a second only where a policy in the repository permits
that exact role, action, workload and read-only shape and the host configuration enables it. The
assignment message, the task details and any model output take no part in that decision. A
configuration naming a pairing the packaged policy does not permit is refused whole rather than
narrowed, and a permitted, enabled pairing whose required controls are missing is refused rather
than handed to the default provider, because an operator reading the receipt would otherwise
believe the provider they asked for had run. A provider's model is never derived from another
provider's routing policy: it is configured explicitly, and the requested model, the model the
provider reported and an unreported model stay three separate facts. Each transport declares every
request option as supported, declared, unsupported or unconfirmed, because "the transport takes
this option" and "this harness knows the option took effect" are different claims. Supported means
the effect is checked here; declared means the option is passed and its effect belongs to the
provider; unconfirmed means a mechanism exists but no claim is made, so asking for it is refused;
unsupported is refused by name when present. Every request records which of its options had their
effect verified here and which were left to the provider, so a spend ceiling is never read back as
a spend guarantee.

The usage-accounting mode of the machine ledger (`domain.usage_policy`: `finite`, the legacy
default, or explicit `subscription`) also decides whether the `claude_cli` dollar cap is forwarded
at all. It is read from one explicit host setting per transport (`ZEUS_CLAUDE_ACCOUNTING_MODE` for
`claude_cli`; `zeus operate run` always sets it from the manifest budget, so a host environment
value never decides an operation's mode); absent or `finite` yields the byte-identical legacy
configuration, digest and command; any other value refuses the configuration whole. Under
`subscription` the `max_budget_usd` control is still validated by the same rules when present but
is retained metadata: it is not required, it is absent from the assignment's `controls`, the
configuration digest differs, the selected runtime carries `accounting_mode`, the request options
omit the cap (never a null), the command passes no `--max-budget-usd` and the CLI preflight does
not require that option, and the command receipt records `max_budget_usd: null` with the named
`accounting_mode`. A runtime told `subscription` refuses a configured ceiling and an unknown mode
before any probe or process; finite still requires and passes a positive ceiling exactly as
before. None of this is a provider allowance, a billing change, a remaining-usage claim, a retry or
a change to auth, timeouts, schema, model, permissions, isolation or the isolated request protocol
(the mode travels in the `runtime` dictionary the request already serializes).

The prompt reaches a provider over its input stream, never through an argument vector or a shell
string, and the recorded command replaces every value that could carry schema, context or
configuration text with its digest. Both output streams are drained concurrently under a per-line
byte limit, a total byte limit and a bounded queue, with one monotonic deadline for the whole run
and a tick and cancel check that keep working while no output arrives and while the child ignores
its input. Entry is the moment the process starts, because initialization inside a provider can
already change the workspace: every failure after it leaves termination evidence and blocks, and
only a failure before it stays an ordinary retry. The process tree is owned from the moment it is
created rather than hunted afterwards: on Windows the process starts suspended, joins a job object
that kills its members when it closes, is verified to be a member, and only then runs, so nothing
it starts is outside the boundary; on POSIX it starts in a new session and the group id is taken at
spawn rather than read back from a process that may already be gone. Termination produces two
receipts, one for the process this harness started and one for the tree, and only both together
end a run: a parent that exited proves nothing about what it left behind, and a kill command that
reports "no such process" after the parent is gone has killed nothing. An unproven tree is an
unknown outcome that blocks rather than a failure that may be retried, and no pipe is closed while
a thread is still blocked inside it. A boundary that fails owns what it has already made: the
process exists before its membership is proven, so ending a job that never accepted it ends
nothing, and the cleanup kills through the handle this harness holds and then reads the process's
own exit status. Only that status lets the failure be called a start that left nothing behind. When
it cannot be read the refusal changes kind rather than degree: a created process that cannot be
proven gone enters the run and blocks for reconciliation, because a retry would place a second one
beside whatever the first one is. The pipes of a process that never ran are closed on that path
too.

A result is named from what was observed. A clean exit, an assistant sentence, tool activity with
no answer, an absent terminal message, two conflicting terminal messages, a truncated stream, a
refused permission and a budget stop are distinct outcomes and none of them is acceptance. What a
terminal message reports and how the process ended are two facts and the earlier one never settles
the later: a success followed by a non-zero exit, or by a stop this harness had to perform, is not
a finished run. An answer belongs to the session this attempt opened or to no attempt here, so the
identifiers the provider reports at startup and at the end are compared with the one that was
requested, and absent, disagreeing or conflicting identifiers each refuse the answer rather than
passing as a binding. The model the provider reports is compared with the model that was asked
for; an exact name that comes back different is refused, and an alias cannot be decided here and
is recorded as undecided rather than as agreement. Output
that was read but never examined is lost output whichever way it was lost, by a byte limit, by a
full queue or by a reader that died, and a run that lost output is recorded as such rather than as
a shorter record of a clean one; a startup report the provider never sent is recorded as absent
rather than as a report of nothing. The
provider's claim that it honoured the output schema is not the check: the schema is validated
locally against the same subset every transport uses. Usage is read once, from the terminal
message, so a redelivered or partial message is never counted twice; each part names what it
counts, an absent count stays unknown rather than zero, and a reported cost is recorded as the
provider's estimate, never as a billed amount. A provider's stream is execution data: six-W
messages are produced by the workflow from a verified sender and recipient, and a six-W envelope
inside a model's output is text with no authority. A session belongs to one provider, task,
attempt and workspace and is resumed across none of them; native resume is declared unsupported
and a new attempt recovers from the authoritative checkpoint through the same context compiler.
A child inherits only what it needs to start and to authenticate the way the host already does;
the harness's own database and cache credentials are withheld, the host's stored settings are
neither read into the run nor modified by it, and the effective configuration, CLI version,
executable identity, working revision and permission policy are recorded as names and digests,
never as values. Foreign diagnostic text travels outward as a digest only. Changing a task's
provider clears no block, no reservation and no attempt budget. Running a provider's CLI directly
on the host is not strong isolation, and no claim here says an effect that already happened can
be undone. Real provider calls made for acceptance experiments are limited by a ledger, not by an
argument: the ceilings come from the packaged policy, the ledger sits at one fixed place per
machine outside any checkout, the host is identified from the machine's own facts, a slot is taken
under a lock before any process can start, and a slot that was reserved and never settled stays
counted because an interrupted experiment may already have reached the provider. A run's label and
output directory are names and places, never budget authority.

## INV-WORKER-PROFILE-001

A worker profile is a packaged document, a packaged standard-library hook and a manifest that pins
both by digest and names the reviewed sources it was adapted from. It is selected only by the
configured `runtime.worker_profile`; an assignment message, task detail or model output never
chooses one, and an unconfigured run keeps every existing option, flag, settings value and
environment exactly as before. Selection is verified before any probe or process: an unknown name,
a manifest that names another profile, a document or hook whose bytes disagree with the manifest,
a document over the character limit (15000 normalized characters for the common worker document,
declared once in `adapters/worker_profile.py` and repeated only by its manifest, which must
agree), or a rule that widens anything but Bash is refused whole and never truncated or narrowed.
That ceiling bounds this one packaged document: per-run project delivery, project-skill admission
and context composition keep their own separate budgets, and it sets no model token allowance. The document travels as the `--append-system-prompt` value and the
hooks and Bash rules travel inside the per-run `--settings` value; the recorded command carries
the profile's id, version, digests, source digests and transport names, never the text. The
host's own hooks, settings files and home directory are neither read into the run nor modified,
and the profile never installs a Stop hook. The hook receives its output directory and profile
digest as fixed arguments, reads its stdin under a byte limit, records the session id, event
name, tool name and profile digest only, and writes each receipt as a new exclusively created
file under a per-session directory outside the checkout, so concurrent runs and restarts never
share or overwrite a record and no prompt, command, output or credential is ever stored. The hook
command is one string that `sh` and `cmd.exe` read the same way: every element is double-quoted,
paths travel with forward slashes, and a character either shell treats specially is refused. The
profile's environment puts the verified host interpreter's directory first on PATH and binds
PYTHONPATH to the candidate's `src` only when it exists; the parent's PYTHONPATH is never
inherited and the harness's own credentials stay withheld. After the tree is confirmed gone, the
receipts are read back and reported beside, not merged into, what was selected: a delivered
document is not a followed one, an installed hook is not an executed one, an absent receipt is
"not observed" rather than "did not happen", and no receipt approves, completes or unblocks
anything. Fixture runs record their launcher as every other transport run does, so a receipt
produced by the protocol child is never a provider measurement; the real Claude verification is
an operation canary recorded separately.

## INV-LOCAL-CYCLE-001

A local cycle binds one correlation to a durable policy row (`local_cycles`) holding the number
of executor starts it may make. Start is idempotent for the same policy and refuses a different
correlation or limit; restarts and repeated steps never reset or enlarge the count. A step reuses
the existing message path (receive, handle, outbox relay, ACK) and makes at most one executor
start, only for worker:implementation tasks or lead:improvement review_lead decisions. The slot is
taken and an in-flight marker recorded in one transaction before the executor starts; a marker
found by another step refuses execution and is never released automatically. Any outcome other
than success (retry, failed, blocked, expired, exception, no claim), a pending diagnose decision,
a received execution notice of this correlation, a message or queued work under another
correlation (except a durably proven foreign execution notice, INV-OPERATION-FINALIZATION-001,
which is informational and does not touch the cycle), or running residue in the ledger stops the
cycle with a recorded reason. The candidate is chosen outside the
claim transaction, so the step passes an optional execution guard (row id, correlation, allowed
statuses) into the existing `Workflow.claim` / `decide_one` selection; the guard is validated inside
the claim transaction before the fence, the lease and any provider entry, and a mismatch (for
example an older queued task of another correlation that arrived after the scan) refuses the claim
unclaimed and stops the cycle with `claim_guard_refused`. Callers without a guard keep the existing
selection policy unchanged. A rejected review_lead result
continues through the existing rework path; an accepted one leaves the cycle in
`awaiting_operator` before the conductor. The limit counts executor starts through this cycle,
never provider billing, and an idle turn is reported as idle, not success.

## INV-CYCLE-HANDOFF-001

`LocalCycle.handoff` and `zeus cycle handoff <cycle_id>` are a read-only projection for the next
operating session: authority `observation_only`, `automatic_resume` false, schema
`urn:zeus:cycle-handoff:1`. One store transaction reads the cycle row and, when `last_execution`
names a task or decision, the current row under that id; nothing is put, updated, deleted,
published, acknowledged, opened, probed, reset or executed, and the CLI builds no executor,
observer, bus or provider for it. The cycle view carries only the stored policy fields (id,
correlation, status, limit, count, in-flight marker, stopped reason, last execution, timestamps);
`remaining_executions` is display headroom clamped at zero and never written back. The stored
`stopped_reason` is never printed as such: the view's `cycle.stopped_reason` is null when the
stored value is absent or null, otherwise the text before the first colon when that text is one of
the finite recognized codes (the stop states, `budget_exhausted`, `foreign_correlation`,
`in_flight_residue`, `diagnose_pending`, `claim_guard_refused`, `no_execution_claimed`, the
`exception`, `foreign_queue`, `unsupported_phase` and `execution_notice` prefixes, and
`execution_<status>` only for the closed list of existing task/decision statuses), otherwise
`unknown`; any colon detail is discarded and arbitrary prefix text or a non-string value is
`unknown`. `cycle.stopped_reason_sha256` is the lowercase SHA-256 hex of the complete original
UTF-8 string when the stored reason is a string (including unrecognized ones), otherwise null; it
is correlation metadata, not a secrecy guarantee for low-entropy values. The `in_flight` and
`last_execution` views admit only the string fields agent, kind, id, status, at and result_id and
the boolean claimed; other types are null, any other key (including error) is omitted, and an
absent or non-object marker is null. The stored row, `zeus cycle status` and `zeus cycle step`
are unchanged by this projection. The target
record is an observation of the row as stored now, not proof of a historical execution: its
availability is `none` without a last execution, `unsupported_kind` for a kind other than task or
decision, `missing` when the row is absent, `correlation_mismatch` when the row's message
correlation differs from the cycle's, and `found` only when it matches; a non-found record carries
availability, kind and id alone. A found record adds status, attempt, generation and phase when
present and, from a dict result only, the candidate's base/revision/tree/diff_hash strings, the
execution_ref string, the evidence inspection verdict string and, for a decision, the boolean
acceptance; anything absent or of another type is null. Task input, prompts, summaries, output,
raw errors, messages, settings and candidate paths are never emitted. An unknown cycle is a
`ContractError` and a store failure propagates; there is no empty success, recovery heuristic or
generated next step. The references are recorded data, not integrity-checked artifacts, and the
view grants no approval, completion or deployment.

## INV-GOAL-PROGRESS-001

A goal manifest (`version` 1, `id`, `objective`, `non_goals`, 1 to 50 `criteria`) lives in Git and
pins each criterion to one ticket id, revision and content hash; duplicate criterion ids or ticket
bindings are rejected so one ticket cannot inflate the denominator. The definition hash is the
digest of the whole validated manifest; a manifest with any change is a new definition and reports
of different definitions are never compared. `GoalProgress.report` reads every needed row in one
store transaction and writes nothing. A criterion is `missing` without its ticket or revision row,
`stale` when the current ticket revision or hash differs, `pending` for a valid open or dispatched
ticket, `reopened` when that ticket's verified history contains a close, and `resolved` only when
the ticket is closed, `verify_chain` passes, the current last event is a `closed` event at the same
revision, hash and sequence with sha256 packet and proof references, and the `ticket_closures`
receipt for that packet names the current lifecycle event. Any other purported closure, corrupted
revision content or broken chain is `unverified`, never resolved. Review votes, remote issue state,
task results, commits, PRs and test counts are activity, not completion. Metrics are total,
resolved, remaining (total minus resolved), reopened, missing, stale, unverified and
completion_ratio; raw records and store errors are not emitted and store failures propagate.
`compare_reports` is pure: it validates both report shapes, requires the same goal id, definition
hash and criterion bindings, derives resolved sets from criterion statuses rather than supplied
metrics and returns gained ids, regressed ids and net_resolved, labelled `observation_only`.
Goal-bound `Tickets.dispatch` (optional `goal_manifest` with `criterion_id`, required together)
validates the manifest and the selected criterion inside the existing dispatch transaction before
any write: the dispatched ticket binding must equal the criterion binding and the criterion must be
pending or reopened; a missing, stale, unverified, resolved or unmapped selection refuses without an
outbox, task or dispatch write. The goal binding (goal id, definition hash, criterion id) is added
to the plan details and the returned dispatch, and the goal-bound dispatch id covers the ticket
binding plus the goal binding so an earlier unbound or other-goal dispatch is never replayed for
it. Unbound dispatch keeps its key and output and is not claimed to enforce goal discipline. The
chain check is not signature re-verification; the existing close path remains the only closure
authority, and no report, comparison or binding grants completion, permission, merge or deploy.

## INV-OPERATION-001

`zeus --repository ROOT operate run --file OPERATION.json` is the one bounded operating entry
point; `operate status ID` is its read-only receipt. The manifest (`urn:zeus:operation:1`) is
strict: exact fields `id`, 40-hex `base_revision`, `goal` (relative Markdown path, sha256,
criterion, rationale), `plan` (objective, acceptance_criteria, allowed_paths), `budget` (per_host,
total and an optional `mode` of `finite` or `subscription` under `domain.usage_policy`; the finite
canonical form is the unchanged legacy shape) and `claude` (model, timeout_seconds, a positive
finite max_budget_usd that under subscription is retained metadata, never an active ceiling);
unknown fields, wrong types, booleans as integers, nonfinite numbers, traversal, `.git` or absolute
paths and empty values are refused, and the claude controls are validated by the existing provider
policy validators with the budget's accounting mode bound in (INV-CLAUDE-WORKER-001). The one
path grammar (`safe_relative_path`, shared by goal.path, allowed_paths, the research packet sources
and the autonomous search scope) is forward-slash relative, at most 1024 characters, each segment
an alphanumeric start followed by ASCII letters, digits, `.`, `_` or `-` up to 255 characters, with
one optional leading dot that counts toward that 255; ordinary dot-prefixed project content such as
`.github/workflows/ci.yml`, `.gitignore` or `docs/.github/GOAL.md` is accepted, while empty
segments, `.`, `..`, repeated leading dots, `.git` in any letter case at any depth, dot-prefixed
segments ending in a period, roots, drives, UNC, backslashes, whitespace, colons (ADS), control
characters and non-string values are refused before any Git, PostgreSQL or provider access. This
grammar is manifest validation, never protection against symlinks, hard links or hostile code;
those stay with the isolated staging and import guards. Fixed by
contract: max_executions 2, worker profile `worker-v1`, `restricted` true; credentials, executable
and endpoints stay host settings. Before any call the goal must exist at base as a regular Git
blob whose bytes hash to `goal.sha256` (read with git argv); current HEAD need not equal base.
The `operations` row atomically claims the id as running with the manifest digest, the
repository, effective resolved runtime directory, packaged runtime policy and provider-policy
identity and endpoint digests (values digested, never stored), the goal binding, a
deterministic assignment message id and the durable initial `local_cycles` row; the assignment
goes to the transactional outbox in the same transaction, never to the bus first. The same id with
a different manifest or identity is `configuration_mismatch`; a completed id returns the saved
receipt with zero calls and no new assignment; a running row (concurrent or interrupted) is
`running_residue` and a preexisting cycle or task is `cycle_residue`; none of these touch the first
owner or a provider. The run reuses `LocalCycle.step` for at most two executor starts and finite
message-only turns; a wrapper reserves the machine `CallBudget` under the manifest ceilings
immediately before each underlying execute_one/decide_one, never for an idle, stopped or cached
turn, settles afterwards and keeps the slot ids in the receipt; a settlement failure keeps the
slot counted, stops before any further cycle turn, reservation or provider entry and makes the
outcome `failed:settlement_failed` (after the first slot the reviewer is never reserved or
called). The executor built for this entry point carries no knowledge adapter (explicit
`build_executor(knowledge=False)`; the default elsewhere is unchanged): no hybrid query, no graph
indexing or runtime projection from worker, reviewer, failure or checkpoint. Execution, budget
and observation ledgers and artifact files are recovery and audit evidence, never validated
knowledge; formal knowledge promotion is a separate explicit contract. Before the review reservation the
exact pending `review_lead` decision, its succeeded worker task with the same correlation and
result, the candidate revision and an actual `evidence_inspections` row bound to that task id,
generation, attempt and source revision must pass `require_all_checked`; a summary verdict string
is insufficient and a missing, foreign or incomplete row stops with `evidence_gate_refused` and
zero reviewer calls. That refusal keeps its terminal `failed` status and its cancelled pending
review exactly, and in the SAME durable finalization it records one bounded owner handoff on the
operation row (`owner_handoff`, `urn:zeus:operation-evidence-handoff:1`): reason code, operation,
correlation, task/generation/attempt, candidate fields, bounded artifact refs, the inspection's id,
bound/known flags, verdict, denominator, per-claim status counts and the inspection-bound passed and
remaining check items, owner `lead:improvement`, next action `inspect_evidence_contract`, status
`pending_owner`. It is a visible request for an owner: no raw output, cause text, command or
credential enters it, it grants no retry, acceptance, model call, merge or deployment authority, and
it schedules no follow-up - `pending_owner` is never presented as running work. Progress is reported
only for evidence bound to THIS execution: the complete current binding (task id, generation, attempt
and candidate source revision) must be known and equal to the stored one before any finding is read.
A missing id (`inspection_missing`), an unreadable row (`inspection_unknown`), an incompletely
identified current execution (`execution_binding_incomplete`) and a row bound elsewhere
(`inspection_bound_elsewhere`) are each `bound=false`, `known=false` with that reason code and the
inspection id for diagnosis; verdict, denominator, claim status counts and the passed/remaining
items are ABSENT, never a foreign checklist and never a misleading zero. The counts-only lane
projection decides credit independently of the writer: it relays `passed`/`remaining` only when the
record states both `bound` and `known` as exactly true, so a handoff retained before this rule -
contradictory flags beside populated item lists - shows null progress there too. The record is
deterministic and written once, so a repeated finalization or a lost response returns the identical
handoff through `operate status` and, for a lane job, through the safe counts-only `owner_handoff`
projection recorded by `Fleet.finalize` and shown by `fleet status`; historical receipts are never
rewritten, and a job without a handoff keeps its exact previous shape. Worker
retry/failure/exception, ledger exhaustion, a lead rejection (no
rework, diagnosis or retry), an unproven or non-boolean verdict and repeated idle turns end the
run as failed, exhausted, rejected or unknown. `accepted` requires a succeeded accepted review_lead
decision for the worker's candidate revision, all slots settled and a collection without sink
failures; `awaiting_operator` alone is insufficient. The receipt persists status, reason code,
slots, the cycle handoff projection, task/decision ids, execution/inspection references and
collection counts; the CLI exits 0 only for accepted (including cached accepted) and prints codes
and digests, never DSNs, raw exceptions, prompts, plans or environment values. Status builds no
executor, observer, bus or provider. `PROGRAMDATA`/`ProgramData` join the replay environment
allowlist; the value takes part in the snapshot digest, historical inspections stay immutable and
no other exclusion changes. No conductor, release, merge, deploy, automatic retry, new work, budget
escalation, ticket closure, cleanup or ownership takeover happens here.

## INV-DGE-001

Research before debate, approved design before implementation. `zeus dge register --file PACKET`
validates a meeting packet (`urn:zeus:research-packet:1`: safe id, 40-hex `base_revision`, topic,
objective, exclusions, the exact operation `plan` shape, nonempty unique questions with boolean
`blocking`, `answered|unknown` status and claim references, nonempty unique sources with safe
relative path and 64-hex sha256, claims of kind `fact|inference|unknown` whose fact/inference
sources exist, `limits.max_rounds` 1..4 and an aware ISO 8601 deadline normalized to UTC, and
`supersedes`/`research_reason` together or both null) before any Git, PostgreSQL or provider
access; a blocking unknown question, an integer standing in for a boolean, an unknown reference or
an invalid digest is refused. Every source must be a regular `100644` blob at `base_revision` whose
bytes hash to the pinned sha256, read with git argv; a missing path, symlink, tree, submodule or
byte mismatch refuses registration. Matching bytes prove provenance of the text, never its truth or
that any fetch ran. The `dge_sessions` row records the canonical packet digest, the resolved
repository digest, the normalized packet, `version` 0, `round` 1, state `proposal` and origin
`operator_submitted`; the same id with the same digest and repository replays the saved row
without mutation even after the deadline (a replay reauthorizes nothing), any other same-id packet
is `packet_conflict`. The registration clock is read inside the store transaction, after any wait
for the lock and immediately before the new row is written, so a deadline that passes during the
wait refuses with nothing written. A replacement (`supersedes`) is accepted only for a prior
`needs_research` session with the same objective and plan, when the new packet answers that
session's exact research question and no other replacement exists; the prior row is not modified
and the new session starts with its own declared limits, never an automatic extension.
`zeus dge submit ID --file EVENT` records one `urn:zeus:debate-event:1` (safe id, integer
`expected_version` >= 0, packet digest, round, role `proposer|attacker|arbiter`, strict payload)
in one store transaction together with the session change and history entry: an exact duplicate
event id and digest is idempotent before any version check, a same-id different-digest event is
`event_conflict`, then a terminal session, an expired deadline, a digest, round or version
mismatch and a role out of the fixed order proposer -> attacker -> arbiter refuse without writing.
The expiry refusal is the one committed write: the session becomes `expired` and the deadline is
never refreshed or compared as naive time. Proposer payloads name claims and cannot change the
plan; attacker findings name an exact plan acceptance item, a severity and claims (an empty list
is allowed and is not a proof). A finding's identity, criterion and severity are fixed for the
session in the `findings` registry of the row: a later round that reuses a recorded finding id,
whether to repeat, replace or downgrade it, is refused. Every finding whose last disposition is
`blocking` is carried unresolved into the next round even when that round's attacker omits it;
the arbiter names every open finding, carried and current, exactly once, cannot defer a critical
finding, cannot accept with a blocking disposition, gives a research question only with
`needs_research`, and moves the session to `design_approved`, `rejected`, `needs_research`, the
next round, or `exhausted` at the round cap. An explicit `resolved` disposition with a reason
closes a carried finding; every earlier decision stays in the registry and in the round record,
and the status counts `findings`, `resolved`, `deferred` and `unresolved` plus the unresolved
finding ids are derived from it. Terminal states are never reopened in place and no model is
called. All three roles are operator-submitted attestations;
the store verifies structure, sequence and the recorded decision, never model execution, citation
truth or a "resolved" assertion. `dge status ID` reads the store only and prints digests, phase,
round/limit, counts, history identities and the trust boundary, never packet or payload text;
refusals print a fixed reason code and type. `urn:zeus:operation:2` is v1 plus
`design {session_id, packet_digest}`; v1 keeps its exact semantics, canonical form and ungated
path. Inside the same transaction that first claims `operations`, `local_cycles` and the outbox,
the named session must be `design_approved` with the same packet digest, repository digest,
base revision and byte-identical plan, no unresolved finding and an unexpired deadline;
`design_missing`, `design_digest_mismatch`, `design_needs_research`, `design_not_approved`,
`design_unresolved`, `design_repository_mismatch`, `design_base_mismatch`, `design_plan_mismatch`
and `design_expired`
raise `DesignGateRefused` with zero rows, assignments, reservations or provider starts. A terminal
operation replays its saved receipt without re-gating and the gate never mutates the session. The
design reference is copied into the assignment details and the receipt so worker and reviewer can
trace the plan authority; it is not knowledge, `knowledge=False` remains and no legacy index or
project-graph path changes. Automated research/proposer/attacker/arbiter dispatch, authenticated
role identities, independent multi-model debate and formal ontology or topology promotion are not
implemented by this contract.

## INV-AUTONOMOUS-001

`zeus autonomous run --file MANIFEST` (`urn:zeus:autonomous:1`: the operation manifest plus an aware
`deadline` and a `research` brief) runs one fixed cycle: researcher, proposer, attacker and arbiter as
fresh `dge_role` tasks from the conductor to dedicated leads (`lead:researcher|proposer|attacker|arbiter`)
through the outbox, bus and the existing executor claim, lease, reservation and checkpoint paths,
read-only in a clean checkout at base with one provider entry per role; then the existing Operation v2
implementation and review; then promotion. The `autonomous_runs` row claims the id (cached terminal
replay, `configuration_mismatch`, `running_residue`, `residue`, `deadline_expired`) and every
transition records its expected prior stage. Role answers bind to the persisted succeeded task row
(agent, correlation, action, role, base revision, execution_ref, generation, attempt, output digest)
with origin `executor_bound`, and to the execution artifact behind `execution_ref` through an injected
evidence port (FileArtifacts plus `invocation_reservations`): the artifact's own answer, a settled
`accepted` reservation of that task/generation/attempt/stage, the base revision and the exact input
evidence digest; a row, flag or matching revision alone never proves an execution, and roles sharing
one provider thread are refused. The packet and events go through the existing DGE validators and an
owned session that `dge submit` cannot feed (`session_owned`). The run deadline propagates unchanged
into the child operation (checked before each provider start, after the review and inside the
promotion transaction); the worker and reviewer artifacts are re-verified in that transaction. Critical findings need trigger, impact
and mitigation; minor findings never block; one round, no rework, no retry, at most six executor
starts, deadline never reset. Only an accepted operation whose worker task, accepted `review_lead`
decision for the same candidate revision and all_checked inspection row are re-read in the same
transaction is promoted as a bounded `verified:<run>` graph (goal, research, design, candidate,
verification; derived_from/implements/verified_by) together with the `promotions` receipt through
the store transaction graph port; a rollback writes neither, an identical retry is idempotent and a
conflicting graph is refused. Promotion records verified execution/review provenance with explicit
scope, never truth of prose, merged code or product acceptance; `knowledge=False` stays for every
execution and `index_python`/`project_runtime` never touch the promoted namespace. Status reads the
store only and prints digests, codes and counts.

Packet producer alignment (`adapters/autonomous_roles.py`, research-program-001 cycle 1). The
model-facing researcher schema states the packet consumer's LOCAL rules as typed alternatives under a
nested `anyOf` with the same field sets and the same domain constants (`enum` always next to an explicit
`type`, `minItems`; never `if`/`then`/`allOf`): a claim of kind fact/inference cites at least one source
id and an unknown claim any list; an answered question cites at least one claim id with either
`blocking` value and an unknown question is `blocking` false with any list. The cross-array rule that an
answered question cites only fact/inference claims, existence and distinctness of cited ids and every
other packet check stay exactly `domain.dge` (INV-DGE-001): the schema cannot see the claims array, so an
output the schema admits is not an accepted packet, and the researcher objective carries that rule as
guidance with a self-check, the two honest forms of a "what remains unknown" question (answered from a
sourced fact about a documented limitation next to a separate nonblocking unknown, or unknown itself)
and the instruction to report a truly blocking design choice as a blocking unknown even though it is
refused. A refused output, at the schema (`schema_mismatch`, owner `agent_output`) or at the packet
(`PacketError`), is the stop of that run: nothing relabels, repairs, retries or spends another entry.
Fixture tests prove the schema and consumer behaviour on synthetic outputs, not that a live model follows
the guidance.

Conductor delivery (research-program-001 run003). A `dge_role` execution receives `role_context`
(pre-implementation, read-only at base, no candidate/worker/verifier asserted) instead of the candidate
`review_context`, and the App Server read-only instructions are phase-neutral. The council debate roles
(research_lead, improvement_lead, conductor) receive `required.council_delivery`: a deterministic
lossless deep copy of the task's packet, packet digest, DBA report, snapshot/report digests, relay,
acceptance criteria, blocker rule and available proposals, with `ssot` and `prior_outputs` reachable only
by exact RFC 6901 pointer on the unchanged hash-bound task artifact; the raw task is then not duplicated
as optional evidence. A missing mandatory input or a required block over the existing compiler budget
refuses before any provider entry; nothing is summarized, truncated, persisted as a packet or repaired.

Bounded inline council input `urn:zeus:council-input:2` (`domain/council_input.py`, research-program-001
Implementation013: shared pool with ordered future reservations; supersedes the v1 isolated section ceilings of
implementation011/012, whose historical receipts and files keep their original meaning under the name
`urn:zeus:council-input:1`). One domain module owns the policy; the unit is the UTF-8 length of the canonical
JSON of each value (escaping and multi-byte text count; local bytes, never model tokens or capacity). The four
payload components share ONE pool of 32768 bytes in the declared production order packet, dba_report,
research_proposal, improvement_proposal with default RESERVATIONS 16384/4096/4096/8192 that are held for a
component until it is produced, not ceilings: for every nonempty contiguous prefix, the actual canonical bytes of
the prefix plus the reservations of the absent later components must not exceed 32768, so the allowance of the
current component is 32768 minus the actual earlier bytes minus the later reservations. Earlier unused capacity
is available downstream; future capacity is never spent twice; a producer's allowance depends only on the exact
earlier values (re-admitted, never trusted), never on a value that does not exist yet, and a pure calculation
carries no credit between calls or runs. Holes, unknown keys, out-of-order stage arguments, a missing earlier
value (never treated as empty) and a component beyond a consumer role's prefix are distinct `ContractError`s,
never overflows. Unchanged fixed limits: `council_delivery` wrapper (serialized projection minus its present
payload components) 4096; host overhead (complete rendered ContextPacket outside the serialized delivery,
measured after recovery/skills assembly with actual ids, paths and evidence) 4096; required total 40960 =
32768 + 4096 + 4096 = council compiler window 49152 minus reserved 8192. The legacy non-council budget
(28000/6000) is unchanged and every other execution keeps it. Producers gate in `CouncilRun` against the exact
prefix committed so far: the frozen packet right after `_freeze_packet` and before the snapshot or the DBA, the
normalized report before the relay and either lead, each lead's complete derived proposal before
`sessions.submit` or the next role; the run ends `failed` with the precise
`needs_scope_split:<section>:<observed>/<allowance>` reason, original role evidence retained, no retry, summary,
drop or resize. Consumers recheck under the SAME rule with role-specific contiguous prefixes (research_lead:
packet+report with 12288 still reserved; improvement_lead adds research_proposal with 8192 reserved; conductor
the complete prefix spending the pool without per-component ceilings): `council_delivery` admits the role's
projection (role-required fields, exact prefix, no injected future component, wrapper), the executor grants the
council window only to an admitted delivery (actual read-only `dge_role`, matching debate role, stage
`dge:<role>` and real agent, and the exact deterministic projection of this task's details; a foreign, trimmed,
inflated or future-injected delivery is refused), preflights the complete required envelope (the identical
snapshot and required dict the compiler receives, rendered through `ContextPacket` before `compile_context`)
so a whole-prompt or host overflow is the typed refusal and never the generic budget error, and then admits
the final rendered prompt (evidence included) before any provider. A consumer refusal is recorded on the role
task with the typed reason: `retry` when the executor's own pre-entry gate refused (the provider never
started), `failed` when the workflow settled it as not retryable; `CouncilRun` lifts either into the run reason
only in its safe shape and never re-dispatches the role. Telemetry is additive: the execution receipt carries
`context_measurement` (policy `urn:zeus:council-input:2`, window, reserved, usable, rendered bytes; for council
prompts the named section bytes, pool spend `payload_bytes`, held `reserved_bytes`, delivery overhead, host
overhead and limit) and `estimated_tokens` keeps its old meaning; the `development.provider_started` log event
keeps its registered attributes unchanged; `policy_manifest()` names the numbers as reservations, not limits.
Producer objectives (`autonomous_roles.role_objective`) state the allowance computed by the same domain function
from the earlier payloads in the task details (the researcher's initial 16384 statically), say that the limit
covers the normalized or derived value rather than raw prose alone, and keep the rule that concision never drops
a finding or an unknown. Not guaranteed: that arbitrary research fits (the pool is a bounded supported
workload); a council delivery with recovery evidence items currently exceeds the host allowance and is refused
before the provider; the live005 sizes (11965/1677/4260 with 8192 still reserved) are covered by a synthetic
size-equivalent test only, the owner's replay of the retained raw inputs is separate.

## INV-COUNCIL-001

`urn:zeus:autonomous:2` is the opt-in topic-bound council; `urn:zeus:autonomous:1` keeps its validator,
canonical form, roles and six-start cap unchanged and an unsupported schema is refused before any
provider or database access. v2 adds `current_state` (`records`: 1..20 unique `{bucket,id}` from
`tasks|operations|autonomous_runs|promotions` with safe token ids; `max_age_seconds`: integer 60..3600,
never a bool) and runs researcher (`lead:researcher`) -> one read-only snapshot -> DBA (`lead:dba`) ->
research lead (`lead:research`) -> improvement lead (`lead:improvement`) -> conductor (`conductor`) ->
the existing Operation v2 -> promotion: at most seven executor starts, one round, one absolute deadline.
The DGE proposer/attacker/arbiter names remain INTERNAL session slots only; task rows, bindings, receipt
`topology` and the promoted design node name the real agents. The snapshot is one
`BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` transaction on a separate connection with bounded
connect and statement timeouts (never `Store.transaction`, never model-written SQL), reading exactly the
selected `documents` rows. Its envelope (`urn:zeus:db-snapshot:1`) binds topic, run, base revision,
selection, `observed_at`, `expires_at` and a digest of database, schema and server version (no DSN), and
holds per key `found|missing|unknown`, the SHA-256 of the canonical row and a whitelist of REQUIRED
fields checked against finite vocabularies or known identity syntax: task status and actor
(`conductor` or `lead|worker:<name>`, the colon is normal), operation status and `lead_accepted`
(true/false/null), run status and stage, promotion repository (`verified:<run>`). A field that is
absent, null or outside its vocabulary makes the record `unknown` with a digest and no fields; an
arbitrary token-shaped string is never copied out; producer and consumer apply the same rule. `missing`
means absent at that snapshot in the explicit selection, nothing about the rest of the database. A
connection or read failure is `snapshot_unavailable` (never an empty observation, no later model start)
and the public exception keeps no `__cause__`/`__context__`. The envelope is stored content-addressed in
the executor artifact store; the run row holds reference, digest, times, identity digest and coverage
counts only. Every council role uses the same six-W outbox -> bus -> executor path and the same
task/artifact/reservation/stage/input binding as v1, with its real agent; roles sharing a provider
thread are refused. The only hierarchy exception is the conductor's self-addressed `dge_role` task with
`details.role == "conductor"` and its `task.result`; other self-assignment, lead-to-lead assignment or
report and worker approval stay refused. The DBA `task.result` must pass the conductor's workflow
before the verified report is handed to both leads (`report_not_relayed`); a persisted
`execution.notice` of an older execution on the conductor stream is consumed as informational only
under the proof of INV-OPERATION-FINALIZATION-001 and never counts as a relayed report, while any
other foreign message still stops the run with `foreign_message`. The DBA report names the
snapshot digest and known packet claim ids and is interpretation, never a Git-supported fact. Both
leads and the conductor echo the same snapshot and report digests (`council_identity_mismatch`) and may
cite only known packet claim ids, including in the improvement alternative that never reaches the DGE
validator. The improvement lead's full alternative (decision reuse/improve/migrate/new, rationale,
transition for improve/migrate, findings) is delivered to the conductor; its findings are converted to
the internal attacker event exactly once, by `event_from_role`. Before each downstream role and before
the implementation the SAME frozen envelope is re-read and checked (`snapshot_missing`,
`snapshot_corrupt`, `snapshot_mismatch`, `snapshot_stale`); nothing refreshes or repairs it. Promotion
rechecks, in the promotion transaction and next to the unchanged worker/reviewer gates, the DBA task
binding and execution artifact, the re-derived report digest and the snapshot document
(`promotion_report_unproven:<code>`, `promotion_snapshot_unproven:<code>`) and records the DBA binding
and the snapshot/report digests in the design node and the receipt. Not guaranteed: atomicity between
Git and PostgreSQL, freshness beyond `expires_at`, completeness of topic-relevant records outside the
selection, or the semantic accuracy of any role's prose. Fixture tests prove these contracts, not
debate quality; no live seven-call council has been measured.

## INV-PROJECT-EVIDENCE-001

Optional host-authored project verification (`domain/project_evidence.py`,
`adapters/project_evidence.py`; design in `docs/zeus/operations/project-evidence-contract-001/SPEC.md`).
`ZEUS_EVIDENCE_PROFILE` (HARNESS alias) names an absolute JSON file outside the candidate, schema
`urn:zeus:project-evidence:1`, closed fields `{schema, contexts, checks}`. A context is
`{cwd, interpreter, source_paths, dependency_files}`; a check is `{id, context, argv, expected_exit}`
and every check is required. Argv is authorized by the SAME packaged evidence policy
(INV-EVIDENCE-001): a profile cannot authorize format, shell or install commands, carries no
environment or secrets, and installs nothing; the host prepares dependencies. The profile is loaded
once per run from host settings, never from the candidate or model output; a configured profile
that is missing or invalid refuses before provider entry and never falls back. Absence of the
setting leaves the legacy worker schema, inspector, review context and operation identity exactly.

With a profile the worker answer stays `{summary, tests}` but each `tests` entry is
`{check_id, status, exit_code}` (`executed` with an integer exit, `not_run` with null). The worker
cannot choose argv, cwd, interpreter or a required flag. Each declared check yields one finding:
`missing` and `not_run` are `not_checked` without any spawn; unknown, duplicate or malformed
observations are `error` findings; an executed check is replayed in its context, and is `checked`
only when the reported exit AND every replay exit equal the host's `expected_exit`. A reported
failure is retained, never coerced; an expected nonzero exit passes only when the host declared it;
pytest exit 5 is not exit 0. Zero observations is `incomplete`, never an empty-denominator success.
The evidence gate (`require_all_checked`) and ontology promotion are unchanged.

The snapshot resolves every context against the actual candidate root (containment holds through
symlinks; missing cwd, source path, dependency file or interpreter refuses before replay) and binds
the profile digest, resolved paths, dependency-file byte digests, interpreter content digest and
environment value digest into the inspection identity and cache key. Replays run under exactly the
snapshot values (context interpreter and cwd, `PYTHONPATH` from the candidate source paths only,
`PYTHONDONTWRITEBYTECODE=1`, never the parent `PYTHONPATH`), reuse the existing bounded capture,
aggregate budgets and raw-output archive, and the application refuses a project snapshot its
identity does not name. Limit: an interpreter path and byte digest do not attest the immutability
of installed dependencies. A read-only reviewer receives the same instructions rebound to its own
clean checkout under `review_context.project_evidence`. `operate` and `autonomous` identities bind
the profile digest, so a same-id run under another profile is refused. For `attacker` and
`improvement_lead`, `execute_role` deep-copies the output schema per execution and makes
`finding.criterion` the enum of the pinned plan `acceptance_criteria`; `domain.dge` exact membership
is unchanged, nothing is normalized, and the static schema constants are never mutated.

Correction batch (R1-R3). Version 1 support boundary, deliberate: a profile check argv must be
`python -m pytest ...` or `python -m ruff check ...` AND pass the packaged allowlist. Replay
enforces the context interpreter only by replacing the first token of `python -m`, so `uv run ...`,
bare `ruff` and every other form is refused at profile load (and again before capture); the legacy
unprofiled contract keeps those forms. The aggregate replay budget is one absolute monotonic
deadline: the remaining allowance is recomputed before every repeat, no repeat starts at or beyond
it, a result observed after it is `not_checked`, and `timeouts_seconds` records what each repeat
was given. For a profiled `implement` on the `claude_cli` transport the executor resolves the host
profile against that checkout (`worker_delivery`) and hands it to `ClaudeCodeRuntime`: each check
becomes one exact POSIX `sh` command (`cd <cwd> && PYTHONPATH=<sources> PYTHONDONTWRITEBYTECODE=1
<interpreter> -m ...`, every value through `shlex.quote`, control characters refused), the per-run
`--settings` gain only exact wildcard-free `Bash(...)` allow rules for that command and its two
parts, the system prompt gains a host section that overrides only the legacy interpreter and
`tests` format instructions, and the process `PYTHONPATH` is unset. Deny rules, permission mode,
the repository-root working directory and the legacy path without a profile are unchanged; nothing
is derived from model output. Delivery is recorded as digests; whether the installed CLI honoured
the rules is decided by a real canary, not by this configuration.

Version 2 (`urn:zeus:project-evidence:2`) is the same contract declared for the pinned isolation
image: the closed fields gain `execution` (`{kind: "container", image: "sha256:<64hex>"}`) and every
context interpreter must be the trusted in-image path `/opt/zeus/bin/python`. The checks grammar,
the Python-only argv boundary, the packaged allowlist, the worker schema, the observation rules and
the classifier are shared with version 1 unchanged. A version-2 profile REQUIRES the host isolation
selection and refuses without it, under another image or with a host interpreter; a version-1 (host)
profile beside isolation stays refused; an absent profile is exactly the legacy path. All of that is
decided in `bootstrap.host_isolation` and the `Executor` constructor, before any provider entry, and
nothing falls back to the host. Contexts are verified against the real candidate tree on the host
(existence, containment through symlinks, dependency byte digests) and then mapped to `/workspace`:
the values that execute are container paths, the image interpreter and a fixed allowlisted container
environment, never a host path, host interpreter or inherited host value. Profile digest, execution
image/limits/isolation digest, relative contexts, dependency digests and the environment digest are
bound into the inspection identity and cache key. The worker delivery is the same `worker_delivery`
resolved in container terms and travels in the isolated request under its own protocol
(`zeus-isolated-worker-v1-project-evidence`), so an entry that predates delivery refuses explicitly
instead of dropping the checklist and answering as an unprofiled run; protocol and delivery must
agree in both directions. Replay is the verifier container of `DockerEvidenceInspector` - the same
function, so ownership, records, cleanup debt and refusals cannot drift - entered at the check's own
container context directory; the host lead reviews with the same check ids resolved for its own
checkout and is told explicitly that these commands do not exist on the host. Missing, duplicate,
unknown, `not_run`, unauthorized and mismatched observations stay non-passing exactly as in
version 1, and diagnostic prose confers no verification credit.

- INV-ISOLATED-WORKER-001: Worker isolation is a host opt-in (`ZEUS_WORKER_ISOLATION=docker` with
`ZEUS_WORKER_IMAGE=sha256:<64hex>`); absent, host execution is exactly unchanged; unknown or partial
configuration, a version-1 host project-evidence profile beside it (a version-2 container profile
naming this exact image is the one accepted pairing), an unavailable daemon or image and a
missing `CLAUDE_CODE_OAUTH_TOKEN` refuse before any reservation or provider, and a selected isolation
never falls back to the host. Mode, image and limits are bound into the operation identity, the
invocation request, the result and the replay cache identity; image, mounts, executable and
credential never come from model output. The pinned candidate is validated (safe relative paths,
Windows names, case collisions, no link/submodule/special entries, <=10000 files, <=256 MiB,
<=16 MiB per file) and exported into a fresh staging directory with a standalone git repository;
host git never runs there again. One uniquely named, run-labelled container (read-only root,
non-root, `--cap-drop ALL`, no-new-privileges, finite memory/CPU/pids, tmpfs home/tmp, only the
staging and evidence binds, no socket, home or port) runs the image's trusted entrypoint, which
reuses `ClaudeCodeRuntime`; the token travels by environment name, never in argv, an image, a record
or an artifact, and the container environment is never inspected or archived. States are prepared ->
created -> start_requested (external-effect boundary) -> running -> stop_confirmed -> validated ->
imported -> evidence_retained -> removed. No inner result is returned before the exact container id
is confirmed stopped; invalid, truncated or missing protocol output is never success; outputs are
fully validated before any regular addition, edit or deletion is imported, and a refused output
imports nothing and preserves its staging. An unconfirmed stop, failed import or failed removal
keeps a run record naming the exact container as the recovery reference, flows to the existing
blocked/unknown termination semantics and refuses the next run of that workspace until reconciled;
a lost create response is recovered only by exact name and label, and removal is by exact id, never
forced and never by prefix. Evidence replay keeps the inherited authorization, classification,
binding and archival and runs each authorized argv in a fresh network-none, credential-free
container of the same image over a fresh candidate copy; an unavailable container is a named replay
failure, never a host replay, and the host lead is told to review read-only without running
candidate code. Worker and verifier share one ownership rule (`hold`/`retire` over `OwnedContainer`
and the same `run.json` record): exact run, name, label and id are durable at `start_requested`
before anything starts; however the start/capture ends (return, cancel, deadline, observer failure,
interruption) the exact container gets one stop-and-confirm whose Docker calls are bounded by the
remaining cleanup window; an unconfirmed stop is `stop_unconfirmed` with its recovery reference and
is never success; bounded observations (the verifier's replay output, the worker's result plus its
whole redacted inner result file) are written outside the container before removal, and an
observation that cannot be written keeps the stopped container and its unresolved record. An
unresolved verifier record refuses the next replay and the next worker run of that workspace;
`status` and `reconcile` cover both roots. The shared bounded capture owns its client as a
`ProcessTree` and tears down in one order however the wait ends (exit, deadline, interruption, any
exception): terminate the tree, bounded reader join, close only streams whose reader finished, then
the original exception propagates carrying the cleanup record to `hold`; a stream a live reader owns
is never closed, and an unreclaimed tree or reader is a named failure (returned capture) or a
`stop_unconfirmed` record (interruption), never success. A normal return is not cleanup proof: every
capture return carries its `cleanup` record, and one join (`join_cleanup`) combines the container
stop with every supplied client/capture proof, each of which must be exactly `confirmed: true`;
absent, malformed or false is unknown and is never overwritten by another true. Anything but a full
positive join is `stop_unconfirmed` with its recovery reference, `retire` refuses it, and `reconcile`
refuses recorded client debt as `client_cleanup_unconfirmed` even when the container is absent. The image's `/opt/zeus` interpreter is a
copy, not a symlink, and the build runs the profile-selected `python -m pytest`/`ruff` under the
actual profile-derived environment and the pinned Claude version check, without a model call. This is worker/verifier isolation for trusted repositories: it does not contain the
lead, restrict worker egress or protect against a host administrator.

# SDD preparation contracts

- INV-SDD-001: Missing specs, unknown fields, uncovered requirements and reused retired scenario IDs fail validation. Git definitions produce immutable runtime snapshots bound to the current local ticket revision. Superseded iterations cannot append observations or request transitions. Given/When/Then are lists of statements, never one-line strings to be parsed; generated replay drafts embed the spec hash and attribute every assertion at runtime to its scenario, oracle index and requirement IDs, carry spec text only as Python literals without truncation, contain no placeholder or expected-failure skeletons, and are never written over a different existing draft.
- INV-ORACLE-001: Imported observations and structural coverage cannot populate approved expected outcomes, certify real-device execution, authenticate human QA, or authorize a release. Gaps remain visible. Eight-stage reports are preparation only until actual providers are implemented.
- INV-SDD-002: SDD journals retain ordered, hash-linked events; duplicate imports/proposals are idempotent and transitions use compare-and-swap. Notifications are local records, not external messages. Model transfer candidates never change routing authority.
- INV-GATE-001: Every gate verdict names one fixed statement, its stage, run, cycle and the definition hash it judged, with the runner receipt and process exit status or the reviewer's actor and authority level; a non-zero exit is never PASS and an unauthenticated reviewer claim never settles a statement. A runner receipt counts only when the receipt document itself names the same run, cycle, statement, definition, artifact, environment and exit status; human statements (`human_*`) accept reviewer decisions only; `authenticated_provider` authority is granted only by the configured provider's own verification of that exact statement and actor, and an unverified claim is kept as a pending unauthenticated claim. A retraction binds to the run, cycle, stage and definition of the verdict it names; one issued for another run or cycle is foreign and never removes a verdict here. All consumers use one fold: the planned statements are the denominator (`not_run` is a state, never an omission), verdicts for another run, cycle or definition are foreign, the latest live verdict wins, ERROR withdraws validity rather than leaving an earlier PASS, PARTIAL stays pending, and a retraction removes exactly one named verdict so that the fold of a compacted view equals the fold of the full view.

## INV-FLEET-001

`zeus fleet register|enqueue|run|pause|resume|authorize-budget|status` is the bounded multi-lane
control plane over INV-OPERATION-001. One host configuration (`urn:zeus:fleet:1`: id, `max_parallel`
1..lane count, fleet `budget`, 1..4 lanes with id, team, resolved absolute repository and runtime,
non-public safe schema, Redis namespace; no DSN or token fields; unique ids/schemas/namespaces;
runtime roots distinct, not nested and outside repositories) is registered once per control store
into `fleet_registry` with its canonical digest; the identical configuration is idempotent, any
other is `registration_conflict`; the registered row and digest are never rewritten. The effective
budget lives in `fleet_control` beside the pause flag (registration seeds it with the registered
ceilings; a row without one means the registered ceilings); pause/resume change only the flag. The
only ceiling change is the explicit operator grant `authorize-budget --per-host --total
--expected-total`, never invoked by the dispatcher or a model run: one store transaction requiring
the expected total to equal the current effective total (`budget_expected_mismatch`), valid
nondecreasing ceilings with at least one increase (`config_invalid`, `budget_decrease`,
`budget_no_increase`) and no queued/dispatching/unknown job (`fleet_not_idle`); it writes the new
effective budget without resuming and an immutable `fleet_budget_grants` record (prior and new
ceilings, expected total, registered digest, time). The same original register stays idempotent and
cannot undo a grant; historical jobs, frozen manifests and the machine ledger are unchanged.
`registered()`, `fleet status` and the monitor `budget` expose the effective ceilings. Enqueue
validates the operation manifest with the existing validator, binds the goal at the lane repository,
requires the manifest budget to equal the effective fleet budget (`budget_mismatch`) and canonical
non-glob relative paths, freezes the manifest and its digest in `fleet_jobs` under the operation id
(one job per operation; identical enqueue idempotent, changed lane/manifest/goal/dependencies
`binding_conflict`; dependencies must exist). Admission is one store transaction over the effective
configuration re-read in that transaction (the runner re-reads it before every scan): not paused,
machine ledger not at ceiling (counts only; reservation stays with the child's CallBudget use),
fewer than `max_parallel` dispatching/unknown jobs, manifest budget equal to the effective one
(`budget_stale` otherwise), lane free, no equal or directory-prefix allowed-path overlap (casefolded,
separators normalized) with a reserving job of the same repository, all dependencies `accepted`
(failed/rejected/exhausted/unknown prerequisites block only dependents). Every observed blocking
reason (`paused`, `budget_exhausted`, `budget_stale`, `capacity`, `lane_busy`, `dependency_*`,
`path_conflict`) is persisted on its queued job in that same transaction, its row and `updated_at`
changing only when the reason differs from the recorded one, and cleared on admission. The claim is
durable as `dispatching` with a fresh owner token before any process; only that owner finalizes.
The child is the existing `zeus operate run` with both `ZEUS_`/`HARNESS_` lane overrides and the
lane DSN built by psycopg.conninfo (`search_path=<schema>`, current_schema verified, never public,
never created); Docker isolation must be selected. `accepted` needs exit 0 and the exact durable lane
row (id, manifest digest, accepted); nonzero, contradictory, missing or unreadable evidence is
`failed` (definite pre-claim refusal) or `unknown`. `unknown` and `dispatching` retain lane,
capacity and path exclusion, are reported as `reconciliation_required`, are never relaunched after a
restart and are never cleared by a command here. Non-job execution units (`fleet_units`, kind
`conductor`, INV-CONTINUATION-001) share the same capacity: `reserve_unit` (same transaction and
serialization as admission; paused or `reserving jobs + held units >= max_parallel` refuses; the
same unit id replays, another binding is `unit_conflict`) holds a slot before anything is spawned,
and `admit_one` counts every held unit (`capacity`). A unit is released only by `settle_unit` on its
reservation token and an exact proof - a cleanup receipt for that unit and token confirming parent
AND tree, or the never-entered fence (`proof_invalid`, `proof_identity_mismatch`,
`proof_unconfirmed`, `owner_mismatch`); an identical replay is cached, a different proof
`settlement_conflict`. Age, a wrapper exit, a restart or a decision never release one; held units
also make the fleet not idle for `authorize-budget` and `relocate`. `activation_gate(target,
descriptor)` is the managed host activation gate (HOST-RUNTIME.md): one transaction commits the admission
pause without reading debt, and a second re-checks that exact pause and reads reserving jobs and held
units (`settled` only when both are empty). A failed pause write/commit or lost acknowledgement raises
(no pause claimed; a retry reconciles the same hold); a failed debt read keeps the committed pause and
returns `reason_code` `debt_unknown`, a pause changed in between `control_changed`, both with unknown
(null) debt and never settled. A pause it sets carries
an `activation_hold` that only `release_activation_hold` for that exact descriptor lifts, an owner
pause is never taken over, and an owner `pause`/`resume` clears the hold. No retry, merge, deploy, automatic ceiling change
or generated work. `sources.fleet` in the monitor snapshot (an additive source beside `database`,
`docker`, `redis` and `observations`; unavailable on its own when the store fails, the fixed
`registered: false` shape when no fleet is registered) and `fleet status` project
`urn:zeus:fleet-status:1` from store reads only: identities, states, safe reason codes (including
the persisted queued reasons), call counts, effective `budget`, last 100 jobs with `truncated`,
`active_job` from all reserving jobs; never manifests, paths, schemas, DSNs or raw output.

## INV-FLEET-BACKLOG-001

`zeus fleet backlog register|tick|status` admits ALREADY APPROVED work into the existing
INV-FLEET-001 admission and adds no executor, scheduler process, launcher, research model, repair,
retry, merge or deployment. An approved backlog is one owner-authored document
(`urn:zeus:fleet-backlog:1`: `plan_id`, `repository` as the 64-hex identity of the lane repository,
`enabled`, 1..64 items) read through the existing `GitSource` at an explicit 40-hex commit, never
from the working tree. Each item carries an id, an EXISTING portfolio project and criterion id, a
lane, `manifest_path` (safe relative, `.json`) + `manifest_revision` + `manifest_sha256`, a
`priority` 0..10000 and up to 8 item dependencies. Unknown or missing fields, duplicate ids, a self
dependency, a dependency on an undefined item, a cycle, a malformed pin, an unknown lane, a lane
whose repository is not the plan's repository identity (`repository_foreign`) and a project or
criterion the packaged portfolio definitions do not define (`goal_unknown`) are all refused before
anything is stored. Items are owner-approved goals, never executable commands, and no manifest
schema is duplicated: the existing operation validator and `bind_goal` decide the manifest and its
goal. Registration is idempotent for the identical plan at the identical pin; a later registration
may add items and flip `enabled`, but an item that already carries a durable intent - open or
already admitted - may not move and may not disappear (`item_removed`), and the repository identity
may not change (`repository_conflict`) - a refused registration writes nothing. The frozen scope of
a selected item is its lane and manifest pin (`item_pin_changed`) AND its project, criterion and
declared dependency item ids (`item_scope_changed`): the goal an item was selected under cannot be
swapped after the fact, for an open intent or for an accepted job.

One tick is a few short store transactions with every external read strictly between them, because
`PostgresStore.transaction` takes `pg_advisory_xact_lock` per transaction and a nested call would
block until `lock_timeout`: (1) read plan, intents, `fleet_jobs` and `fleet_control` in ONE
transaction, settle open intents against the jobs that may already exist, and write the durable
intent for the chosen item; (2) read and validate the pinned manifest, bind its goal and name the
lane repository identity OUTSIDE every transaction, then record the exact job identity on the
intent; (3) call the unchanged idempotent `Fleet.enqueue` (its own transaction) and confirm against
the durable job row; (4) call the unchanged owner `Portfolio.bind` (its own transaction) for the
item's project and criterion and record the linkage. The job id is the operation id, so a replay
after a lost response reconciles the already created job instead of creating a second one. Identity
is the COMPLETE `domain.fleet.binding` of the AUTHORITATIVE row - lane, repository, frozen manifest
digest, predeclared dependencies and every bound goal field - recorded before the enqueue and
compared field for field; the `Fleet._view` projection omits `repository` and is never compared as
if it were an identity, and an intent that carries no recorded binding reconciles nothing. An equal
job id under any other binding is `conflict` (`binding_conflict`, `job_binding_conflict`,
`intent_identity_conflict`) for the owner and never evidence that the enqueue succeeded, so a crash
between the intent and the enqueue can neither adopt a foreign accepted job nor unlock its
successors, and the already queued job is never edited.

Selection is deterministic: open durable intents first (an interrupted enqueue is completed before
new work is admitted), then admitted items whose portfolio linkage is still pending, then
dependency-satisfied pending items by `priority` then by stable id. A dependency is satisfied only
by an `accepted` AND linked Fleet job (`dependency_unlinked` otherwise), and a blocked, failed,
conflicted or unknown item blocks its own dependents only. Two distinct definite refusals of one
item block that item (`attempts_exhausted`) and hand it to the owner. A repeatedly unavailable
input or binding owner is NOT an attempt: that item is deferred for a bounded doubling number of
ticks (`deferred_*` while it waits), keeps its durable intent, stays observable and recoverable
across a restart, and lets every independent eligible item keep moving; after `MAX_DEFERRALS`
consecutive outages it is blocked for the owner with its last reason and exception TYPE preserved.
A deferred item's countdown is a durable transition, not an idle poll. `selected`, `enqueued`,
`backlog_exhausted`, `blocked`, `plan_paused`, `fleet_paused`, `unavailable` (input or binding
owner unreadable: the exception TYPE only, never an empty success), `plan_unregistered`, `refused`
and `conflict` are distinct recorded outcomes; the last four exit nonzero. An idle poll writes no
row and moves no timestamp.

The portfolio stays the authority over goals and over its own bindings: a tick calls the existing
`Portfolio.bind` for the exact project and criterion, outside every held transaction, and records
`link_state` pending / linked / conflict / blocked. An admitted job whose binding does not yet
exist is unfinished work (`complete_binding`, counted as `unlinked`): it is never reported as a
linked success and never unlocks a dependent item, a binding outage leaves it durably pending and a
later tick completes it, and a job already bound to a DIFFERENT criterion is `portfolio_binding_conflict`
and is never rewritten. A binding is not an acceptance; no criterion completion is written here.

Fleet pause, concurrency, lane and path exclusion, the machine ledger, the frozen manifest,
dispatch, finalization, the portfolio's authority over goals and bindings and the subscription
accounting are all unchanged. `FleetRunner(..., backlog=...)` is the optional per-tick connection,
disabled by default and skipped once a graceful stop begins, wired by the adapter only when the
host setting `ZEUS_FLEET_BACKLOG_PLAN` names a plan. A tick that RETURNS a failure is a failure of
that tick, exactly like one that raises: `unavailable` reads as `unavailable` and `refused`,
`conflict` and `plan_unregistered` read as `refused`, each with the tick's own fixed
`reason_code` and exception TYPE in the run summary; idle, blocked and both pauses are `ok`. Only a
state TRANSITION is logged (one line, never raw exception text or a message), and unrelated
admission and finalization keep running. The same opt-in wiring builds the durable process observer
and emits the fixed structured transitions `development.backlog_item_admitted`,
`operations.backlog_item_refused`, `operations.backlog_unavailable` and
`operations.backlog_recovered` (INV-OBSERVATION-001 allow-lists: plan, item, lane and job
identifiers, fixed codes and counts only; a run of outages emits one entry, not one per poll).
`fleet backlog status` and `sources.fleet_backlog` in the monitor snapshot project
`urn:zeus:fleet-backlog-status:1` from store reads only - plan and
item identities, the pin, item state, the authoritative Fleet `job_status`, the linkage state,
fixed reason codes, attempts, deferrals, counts and a bounded `next_action` - never manifests, objectives,
goal text, absolute paths, schemas, DSNs or raw errors. That monitor source is an additive envelope
beside `database`, `docker`, `redis`, `fleet`, `research_programs`, `portfolio` and `observations`,
collected by the same read-only collector and served unchanged by the existing `/api/status` route:
it ticks nothing, so it selects, reads no Git, enqueues, binds and writes nothing, every registered
plan's `blocked`/`plan_paused`/`fleet_paused`/`backlog_exhausted`/`conflict` outcome stays distinct,
no registered plan is the `registered: false` shape with an empty `plans` list, and a store failure
makes that one envelope `unavailable` with the exception TYPE while every other source is collected
as before. A collected status is a selection projection only: never evidence of active work,
acceptance, release or host activation. A selection receipt is never a completion,
review, release or deployment receipt: an `accepted` item means an accepted lane operation only, a
linked item means a recorded goal binding only, and missing evidence stays unknown.
Two owner-only commands exist beside `authorize-budget` for storage recovery (storage-recovery-001);
neither calls a model, retries, grants budget, resumes admission, records success or moves a file.
`fleet reconcile-interrupted --file` settles ONE interrupted job from an explicit
`urn:zeus:fleet-recovery-evidence:1` document (job, operator, expected status/owner token/lane/
registered digest, lane operation id with its `operation:<id>` correlation and task id at its
advanced generation, the owned container run id/name/id, the invocation reservation and the machine
call slot). The adapter observes that evidence itself (`urn:zeus:fleet-recovery-proof:1`): the lane
`operations` row that owns the exact correlation (the INV-OPERATION-FINALIZATION-001 ownership
rule), the task cancelled at that generation with a lease that parses and is not live, the task's
recorded `execution_progress` worktree, the ONE retained isolation run record of that worktree with
that exact container name and id, a Docker state of `exited`/`dead`/`created`, a reservation that is
`settled` or `unsettled_unknown` with no open reservation left for that task, and a `used` machine
slot. A container name with no recorded task/run binding, an ambiguous or unreadable record, an
unavailable daemon or a missing slot is a refusal, never an absence, and unknown usage stays
unknown. The slot id is never taken as its own binding: the slot must be tied to that operation by
the ledger's own `purpose` (`operation:<id>:<kind>`, written when the slot was taken) or by the lane
`operations` row's recorded `calls.slots[]`, agreeing on the provider where both exist; a purpose
naming other work is `machine_slot_foreign` and a slot with neither record is
`machine_slot_unbound`. The commit needs a paused fleet, the registered digest the evidence names,
and the job
still being that exact reservation (status in dispatching/unknown, owner token, lane, operation id);
the observation is re-read inside that transaction and its identities (everything but its clock)
must be unchanged. It writes one immutable `fleet_recovery_receipts` row and makes the job terminal
`failed` with the fixed `interrupted_unknown` reason, clearing that one reservation while manifest,
goal, dependencies, exit code, call counts and every other record stay byte-for-byte; identical
evidence replays idempotently and any other evidence for that job is `recovery_conflict`. Both
owner commands consult that committed receipt FIRST, before any lane, Docker, ledger, journal,
checkout or copied-file read: an identical replay is answered from the durable receipt and a
conflicting request for the same identity refuses there, so a settled operation survives the
removal of what it settled. This is an
owner-controlled recovery with the worker services stopped, not a distributed atomic transaction,
and the receipt says so. `fleet relocate --file --journal` moves lane repository and runtime PATHS
to already-copied targets under `urn:zeus:fleet-relocation:1` (expected registered digest, exact
`from`->`to` map, verified copy manifest, operator): only those paths may change, every stated source
must be exactly what is registered, no target may equal or contain a path this fleet already uses,
the result is re-validated by `validate_config`, and lane id, team, schema, Redis namespace,
concurrency, budget and provider authority are compared field by field. The adapter proves the
cutover state instead of trusting an idle flag: the service lifecycle journal
(INV-SERVICE-DIAGNOSTICS-001) must show the last Fleet CLI run exited (missing, unreadable or still
open is `runner_state_unknown`/`runner_not_stopped`), every retained isolation run of a moving lane
must have a container Docker proves is not running, each target must be an existing resolved
directory (no symlink or junction escape) that is an independent checkout with no borrowed objects
and the same root-commit identity as its source, each target runtime must be writable, every queued
job of that lane must have its pinned base commit and goal bytes present in the target, and the copy
manifest and every destination file must hash to what the request states. A moving lane's runs are
read from a source that was actually enumerated: a missing runtime root, a missing or unreadable
`isolated-worker/runs` root and a retained run directory without a record are
`lane_runtime_unavailable`/`lane_runs_unavailable`/`lane_runs_unreadable`, never zero active runs,
and only an initialized accessible root that genuinely holds nothing counts as zero; no missing
source is created here. Every manifest entry must be typed, carry a non-null sha256 and byte
length, name absolute resolved paths, sit below a target this request moves at the same relative
path its source sits below the stated source, appear once, and read back to exactly that digest and
length within that bounded length; a missing destination is `copy_unreadable` rather than a match
for a null digest, an entry outside the stated moves is `copy_entry_unbound`, and a moving runtime
with no entry is `copy_manifest_incomplete`, so an unrelated manifest cannot certify a cutover.
Containment is physical, not lexical: normalized absolute names do not establish where a path
leads, and `normalize_path`'s casefolded comparison form is scheduling identity, never a filesystem
rule - on a case-sensitive filesystem it reads the two distinct sibling directories `new/RT` and
`new/rt` as one. So containment is decided by concrete platform-native `Path` operations on the
components the request actually spelled: the stated components below each move root are taken with
this platform's own path rule (`relative_to`, case sensitive on POSIX and case insensitive on
Windows, nothing lowercased), a name that is not natively below the root it claims is
`copy_entry_escaped`, every move root and both ends of every entry resolve strictly, the resolved
path must sit below its own resolved root at exactly those components, and the two sides must state
the same components. Every stated component below either root is also inspected with `lstat`: a
symlink, junction or other reparse point anywhere under a move root - intermediate directory or
leaf, source side or destination side - is `copy_entry_link_refused` and is refused as a redirection
rather than resolved for ownership credit, and that holds whether or not it leads outside the root
and even when it points at a contained file, because a redirected child is not the file this request
moves wherever it points. A root that is itself such a link is `copy_entry_link_refused` too; a path
that is
missing, unreadable or looping is `copy_entry_unresolved` (a destination whose directory chain
resolves but whose file was never written keeps `copy_unreadable`). Global path canonicalization is
unchanged, so scheduling identity, the admission path exclusion and the relocation rollback
equivalence keep their existing casefolded comparison. The observation states this as
`copy_manifest.ownership: resolved_paths`, and the commit refuses a `bound` manifest observation
without it (`copy_unverified`), so a check that only compared names cannot certify a cutover. This
is what the filesystem showed when it was read; it does not exclude concurrent OS-level mutation
afterwards. The commit needs a paused
fleet with no dispatching or unknown job, compare-and-swap on the registered digest, and the same
re-read rule; it writes one immutable `fleet_relocations` receipt (prior configuration and digest,
new configuration and digest, request, observation, repository alias map) and the revised registry
row in one transaction. Job rows, manifests, goals, operation identities, provenance and artifact
references are never rewritten, so a job frozen before a move keeps its old repository identity and
admission resolves both sides through the receipts (`canonical_repositories` folds their edges into
one equivalence class per repository, answering the class's latest destination;
`resolve_repository` reads that map) to keep the path exclusion intact after repeated moves and
after a rollback, where a plain chain walk over A->B->A would answer differently from each side.
The identical request replays idempotently; another request against the same
expected digest is `relocation_conflict`. Future jobs use the new paths; no old operation is resumed.
Because both commits re-read the adapter's observation from INSIDE their own store transaction, that
observation callback never reads the primary store there: `PostgresStore.transaction` opens its own
connection and takes advisory lock 734219 per transaction, so a nested primary-store read waits on a
lock the same call holds and fails with `LockNotAvailable` at `lock_timeout` (the first real owner
recovery rolled back on exactly that; `MemoryStore`'s reentrant lock hid it). The CLI therefore
resolves its immutable store inputs once, on the first observation, while the application is still
outside its transaction - the lane of a recovery, the configuration and job rows of a relocation -
and reuses them for the re-read, refusing with `config_expected_mismatch` when the registry it reads
them from is not the digest the request expects, so the observed lanes are the configuration the
commit compares against. Every external fact is still observed twice (lane schema, Docker daemon,
service journal, checkouts, copied files) and the queued denominator is still the committing
transaction's own read of the job rows, so state that changed between the two observations refuses
before the write; no lock, timeout, compare-and-swap or replay rule is relaxed, and a request the
committed receipt already answers still reads nothing at all.

## INV-OPERATION-FINALIZATION-001

A terminal bounded operation (INV-OPERATION-001: accepted, rejected, failed, unknown, exhausted)
retires only the follow-ups it provably owns, inside the same store transaction that makes its
`operations` row terminal (`application/operation_finalization.retire`, called by
`Operation._finish`). Ownership is exact: the correlation is `operation:<id>`, the `operations` row
under that id carries that same correlation and cycle id plus an assignment message id, and the
row's agent/actor is `worker:implementation` or `lead:improvement`; free text, prefixes, absent,
malformed or active operations and conductor rows never qualify. Retirable rows are tasks
`queued`/`retry` and decisions `pending`/`retry` without a live lease: each gets an append-only
`operation_dispositions` record (stable id, prior status, generation, attempt and row hash), the row
becomes `cancelled` with separate `retirement` metadata (`reason_code: operation_terminal`) while its
message, result, error, failure, input and `attempt_outcomes` stay exactly as they were (no cancelled
attempt is invented and no prior error is replaced), advances the durable execution fence and clears
inactive lease metadata; no notice, execution, outcome, retry, diagnosis or conductor message is
produced. Running, blocked, live-leased, unparsable-lease and fence-ahead rows, and rows with an
`observation_terminations` record of any attempt in `unconfirmed` or `pending_reconciliation`
(INV-OBSERVATION-001), are untouched and listed in `finalization.unresolved` with a fixed reason
code; already terminal rows are counted only. The summary (`urn:zeus:operation-finalization:1`) is
cleanup evidence on the receipt beside the immutable outcome, never a change to it; a rolled-back
transaction leaves neither the terminal status nor a disposition. Late messages of a terminal
operation addressed to the two roles (`task.assign`, `task.result`, `review.result`,
`hook.required`, `execution.notice`) are parked by `Workflow.submit`/`handle` in the transaction
that would otherwise queue work, in one ordering: authorization, then validation of this exact
message against every older immutable binding of its id (task `input_hash`, `workflow_inbox` hash,
parked digest; a different body is refused with the existing identity error or
`ParkedMessageConflict` and nothing is written), then parking regardless of the old row's status or
inbox existence, otherwise the old result or the normal path. The idempotent
`operation_message_dispositions` record keeps the original six-W message and digest and the caller
receives a parked receipt (`parked: true`, `authority: parked_no_work`) instead of a task, decision
or inbox result; the old task or inbox row is never rewritten; conductor recipients bypass parking.
`LocalCycle._deliver` consumes a foreign message only after the workflow returned that durable
parked receipt, then ACKs and continues within the existing `MESSAGE_DRAIN` bound; any other
foreign message, including a body that conflicts with its id's binding, keeps the refusal (no ACK,
no dead letter, stop `foreign_correlation`, the refusal type in the receipt), and a replay after the
commit but before the ACK returns the identical disposition without an executor start.
Informational notices on the shared transport (research-program-001 Implementation014): the outbox
and the execution store are shared, so a persisted `execution.notice` of an older execution can
reach the stream a current run drains under another correlation. `AutonomousRun._deliver` (the
council conductor relay included) and `LocalCycle._deliver` consume a foreign `execution.notice`
only through `execution_notices.receive_foreign`: after the existing recipient check and route
authorization, the same proof as `receive` (stored `execution_notices` row whose transition digest
is the notice id and whose message equals the delivered bytes, idempotent `workflow_inbox` binding)
runs in its own transaction and commits BEFORE the ACK; the receipt is `informational_only`
(`general.message_accepted` then `general.message_acknowledged`), the message is never handed to
the current run's workflow or listed among its handled reports, the drain continues within
`MESSAGE_DRAIN`, and the current run, cycle row, tasks, decisions, reservations and promotion are
unchanged. The terminal-operation parking above is never a substitute for that proof: a foreign
notice with terminal operation metadata is refused, not parked, unless the store proves it. A
missing or tampered stored notice, a conflicting body under the same id, or an unknown notice keeps
the existing refusal (no ACK, no dead letter, no inbox row, `foreign_message` for the autonomous
run, `foreign_correlation` with the refusal type in the cycle receipt); a route or schema rejection
keeps the existing dead letter; a store failure propagates with nothing written and nothing ACKed,
so a later delivery can retry the informational persistence only. Foreign `task.assign`,
`task.result`, `review.result` and `hook.required` keep the refusal or the parking above, and a
notice of the run's own correlation keeps the existing `Workflow.handle` path.
Observation (INV-OBSERVATION-001): `Operation`, `LocalCycle` and `AutonomousRun` accept an optional
observer, wired from `operate run`, `cycle step` and the autonomous CLI; `general.message_received`
follows a validated decode, `general.message_accepted` follows durable handling,
`general.message_acknowledged` follows the returned ACK, `general.message_rejected` carries the
error type with `dead_letter` false for a foreign refusal, `operations.operation_message_parked`
and `operations.operation_finalized` carry identifiers, counts and codes only, and every affected
outbox flush audits through `observer.audit_system`; an absent observer keeps every prior caller
unchanged, and an observation failure never alters handling, the ACK or the outcome.
Correlation-scoped publication (research-program-001 Implementation015, INV-MESSAGE-001): a current
run's publication is not a side effect of the global batch. `outbox.relay`, `Harness.flush_outbox`
and the shared `local_cycle.flush_outbox` helper take an optional `correlation_id`. Default None is
the unchanged global background batch: one page from the shared `outbox_control` cursor, the cursor
advance and the `health/outbox` last-batch row; generic CLI, supervisor and background callers stay
unscoped. A non-empty correlation selects only UNSENT records of exactly that correlation, ordered
and bounded by the same limit 1..1000 (default 100), independent of the cursor and of unrelated sent
history; selection walks the outbox in ordered `entries` pages, so its read cost grows with the
table size and is not a claim of indexed scalability. The scoped batch reuses the same
prepare/publish transactions, content and identity binding, route authorization, retry, poison
quarantine and audit rows; the correlation is rechecked inside the prepare transaction and again
before the publish, so a scope changed between selection and send is counted `out_of_scope` or
superseded with the attempt evidence kept. It never advances the global cursor, never publishes,
marks sent or quarantines a foreign record, never writes the global health row, and keeps the
existing idempotent semantics for an already delivered own record. It returns `unfinished` (own
records of the batch still unsent), `remaining` (the whole unsent scoped backlog) and `complete`, so
`examined` is never read as published. Every role, operation and cycle seam publishes with the
active correlation: `AutonomousRun._role` (assignment before delivery, result and commands after the
execution) and `_deliver`, `Operation.run` before every cycle turn, and `LocalCycle._flush` and
`_deliver`. An unfinished scoped publication is a named safe refusal, never a retry and never idle
success: the role raises `publication_incomplete`, the operation ends `failed:publication_incomplete`
before any further reservation, and the cycle stops with `publication_incomplete`. In the delivery
seam that refusal happens after the workflow durably handled the report and before the ACK, so the
derived command keeps its intent and attempt evidence and the message stays pending for the existing
at-least-once redelivery; no candidate is chosen and no slot or provider entry follows. After delivery and
before `BudgetedExecutor` reserves a slot, a council role verifies the exact expected task row in the
consumer database (same id, same correlation, still queued); a missing, foreign or unadmitted row
refuses with `expected_execution_missing` / `expected_execution_foreign` /
`expected_execution_not_queued` and zero slots and provider calls. That preflight is additional: the
atomic `check_expected` / `require_expected` guard inside the claim transaction remains the race
protection, and a proven foreign notice keeps the Implementation014 handling above.

## INV-RESEARCH-PROGRAM-001

`zeus research-program register|run|status|pause|resume` is the finite discovery-to-council program
over the existing collectors, store and council. One strict config (`urn:zeus:research-program:1`:
id, base_revision, aware deadline, positive interval_seconds, max_cycles 1..100, max_adoptions
0..max_cycles, machine `budget`, 1..20 topics with lowercase keywords, at most 100 local candidates
with a regular tracked path and exact sha256 at base, and one complete `urn:zeus:autonomous:2`
template with the SAME base and budget) is validated by the existing council and operation
validators, its template goal bound at base and every local candidate verified through the dge Git
verifier before the row exists. Registration stores the canonical config with the digest of
config+resolved repository identity in `research_programs`; the identical registration is cached,
any other config, id or repository is `registration_conflict`; the row's config, digest and counters
are never rewritten by a tick and never reset. Programs start `paused`; `resume` moves paused to
`active` only (completed and blocked are refused; no repair); `pause` blocks new ticks while an owned
cycle finishes. Every tick reserves the next cycle number with a fresh owner token in ONE store
transaction before any fetch (`busy` while a cycle is owned, `paused`, `deadline_expired` and
`max_cycles_reached` completing the program, `not_due` without increment); no transaction spans a
fetch, Git command or the council. Discovery is read-only and model-free: local rows re-verified at
base, BOTH live feeds through `ResearchSources`, each source recorded ok/unavailable with an
exception type or dge code only (degraded, never empty). Candidates dedup across ticks in
`research_program_candidates` by `local:<path>` or `url:<https url without fragment>`; relevance is
a deterministic keyword match in bounded title/summary with a recorded reason, never a semantic
judgement; the stable order is local first, then topic/id/url. At most one eligible unclaimed
candidate is claimed per tick, in the same transaction that counts the adoption, only when the
adoption cap and the machine ledger headroom (>= 7 remaining on both ceilings, unreadable counts are
not free) allow; otherwise the fixed no-selection reason is recorded and collection still counts.
For a selection the bounded snapshot JSON goes to the artifact store and to a NEW detached commit on
the immutable base in the same object database (temporary index, hash-object/update-index/
write-tree/commit-tree, fixed argv, synthetic author, one new `refs/zeus/research/<program>/<cycle>`
created with an empty old value): the checkout, index, HEAD and branches are never read or moved,
an existing target path or ref is refused, and captures are unverified source data. The council
manifest is derived only: deterministic id `<program>.c<NNN>`, base = capture commit, deadline =
min(program, template), template goal/plan/budget/claude/current_state byte-identical, snapshot path
appended to the research scope with one bounded question naming the lead as untrusted; it is
persisted and its start recorded in `research_program_cycles` before `autonomous_cli.run` executes
it under the existing CouncilRun, CallBudget and promotion. The result is read from the
authoritative `autonomous_runs` row (id and manifest digest must match) and is exactly
accepted/rejected/failed/unknown; stdout, return values and exceptions are never authority; a
missing row after a refusal is `failed`. failed/unknown block the program and keep the claim;
rejected stays rejected. Capture, manifest or Git failures persist stage and code, count the cycle
and block the program. Review001 corrections: (R1) `reserve_cycle` takes the CURRENT repository
identity and raises `repository_mismatch` inside the reservation transaction when it differs from
the registered one, before any log, fetch, capture or model effect; (R2) the post-capture
pre-provider phase (`capture_record`, `manifest_derive`, `manifest_artifact`, `manifest_file`,
`council_start`) is stage-tracked, a failure records the blocked cycle with the capture reference
retained in `failure.capture` and runs no council, and if that record cannot be committed the
receipt says `recorded: false`, the cycle stays owned and nothing is cleared or retried;
(R3) the capture blob is written from exact UTF-8 bytes through an owned binary file with
`hash-object --no-filters`, its id must equal the content-addressed SHA-1 and the commit's blob
must read back byte-identical through `GitSource.blob` before the ref is created.
Investigation dispatch (research-dispatch-001). The OPTIONAL `investigation_source`
(`{"topic": "<configured topic id>", "project_ids": [...<=20], "reason_codes": [...<=50]}`, nonempty,
distinct, pattern-bound lists) lets ONE authorized program consume operating-portfolio investigations;
absent means disabled and keeps the legacy canonical config and its digest byte-identical, while
`null`, `[]`, a wildcard, an unknown topic or any other field is refused with a field name only. It
authorizes the program's unchanged template plan, nothing else, and it is evaluated on an existing
tick: no daemon, schedule, hook or second scheduler is added. Inside `record_collection`'s existing
transaction the candidates are synthesized from the authoritative `portfolio_investigations`,
`portfolio_bindings` and `fleet_jobs` reads only - an adapter that supplies an `investigation` item is
refused with `investigation_source_forbidden` - and an investigation is eligible when it is well
formed, still `research_required`, carries an authorized reason code, is unclaimed and keeps at least
two distinct referenced terminal jobs whose status and reason code equal the family's AND that are
bound to an allowed project; only those scoped job ids are used, excluded rows become bounded fixed
counts (`malformed`, `state`, `reason_code`, `insufficient_jobs`, `claimed`) and no root cause is
derived. Eligible investigations sort before local and external candidates by id, stored candidates
are revalidated against the current state, scope and claim immediately before selection (a changed
owner disposition drops the cached snapshot and can never run later), and the selected one reserves
`research_investigation_dispatches` keyed SOLELY by investigation id - one claim across all programs,
in the SAME transaction as the selection and the cycle bookkeeping, refused as
`investigation_already_claimed` and rolled back whole if a row appeared meanwhile. The claim binds
program, cycle, the immutable snapshot digest, the scoped job ids, the family status and reason code
and the timestamps; the candidate carries that `urn:zeus:research-investigation-snapshot:1` snapshot
(identities, fixed codes, at most 50 job ids with the complete count, the digest of the full scoped
set and explicit `job_ids_truncated`, observed time, explicit unverified trust) through the existing
GitCapture and `snapshot_document` into the council, and no prompt, output, exception, credential or
provider stream is copied. `record_council_start` binds the dispatch to that exact run id and manifest
digest; the result is recomputed from the authoritative `autonomous_runs` row through `council_result`
INSIDE the result transaction, so a missing, mismatched or running row stays `unknown` and the
caller's claim is kept only as the unverified `reported_result`. Capture and pre-start failures record
a failed dispatch with the fixed stage and code; failed and unknown outcomes keep the claim, nothing
is released on a timeout, retried or cleaned up, and `portfolio_investigations.state`, Fleet jobs and
owner dispositions are never written from this bridge: a dispatch outcome is not an owner disposition,
an incident resolution or a promotion. `status` gains the additive `investigations` dispatch counts,
cycle receipts gain `investigations` (bounded counts plus the claimed id, `null` when disabled), the
report names dispatch separately from acceptance and the event log gains claim, capture and outcome
identifiers with codes only.
Dispatch transport recovery (research-dispatch-recovery-001). `zeus research-program recover --file`
takes one owner request (`urn:zeus:research-dispatch-recovery:1`: `investigation`, `failed` = the exact
program, cycle, run id, manifest and snapshot digests of the claimed dispatch, `replacement` = a NEW
registered program id and its config digest; strict fields, the failed program is never its own
replacement). It qualifies ONLY a failure-family dispatch resolved `failed` with
`publication_incomplete` whose program is blocked with no owned cycle, whose cycle and
`autonomous_runs` row agree (row `failed:publication_incomplete` at stage `research`, zero reserved
or settled starts, no invocation, role or packet), with no task, invocation reservation, DGE session
or operation for that run, exactly one outbox record for its correlation - the researcher
`task.assign`, `sent` false, no delivered entry and only `retry` or pre-publish
(`superseded_before_publish`, `transport_unavailable`, `transport_changed_before_publish`) attempts -
a still `research_required` investigation, and a replacement that is paused and never ticked in the
same repository whose config equals the failed program's except id, base_revision and deadline (the
template's base and deadline included), so no source, cap, budget, goal, plan or scope widens. Any
gap refuses with a fixed `recovery_*` code and writes nothing. Three steps, none holding a
transaction across I/O: (1) the first request re-reads those records and, in the same transaction,
fences the unsent assignment through the existing outbox quarantine (`ResearchDispatchSuperseded`;
source copy retained, `sent` untouched, never reported as sent; the global and scoped relays then
return `quarantined_existing`) and records the lineage row in `research_dispatch_recoveries` (keyed
by investigation id, `fenced`); (2) `TransportProbe` reads the configured Redis recipient stream and
the dead-letter stream completely and read-only for that message id - an unreachable bus
(`recovery_transport_unavailable`) or a stream above the bound (`recovery_transport_unbounded`)
refuses and the row stays `fenced`, because a delivery error or timeout alone never proves that
nothing was delivered; (3) the records are re-read, the fence must be unchanged
(`recovery_publication_changed`) and the row becomes `authorized` (with `proof`), or `refused` with
`recovery_message_delivered` when the message is present on the bound transport.
Original transport ownership: absence counts ONLY on the transport the failed attempt used. A
binding-capable bus (`RedisBus.transport()`) yields a credential-free identity
(`urn:zeus:transport:redis-stream:1`: endpoint digest of host/port or socket path, database,
namespace, server `run_id`, and a random storage token the publisher creates once with `SET NX` at
`<namespace>:transport-incarnation`; no URL, user name or password). The outbox reads it once per
batch outside any transaction and commits it on each attempt with the intent, BEFORE the publish
call; the delivery row keeps the FIRST binding, and a later attempt elsewhere is its own record.
`publish(message, transport=binding)` rechecks endpoint, database, namespace and `run_id`, then
checks the token and XADDs in one atomic script; any mismatch raises `TransportChanged` before a
write (attempt `transport_changed_before_publish`), and an unreadable identity publishes nothing
(attempt `transport_unavailable`). A bus without `transport()` still delivers, unbound. Recovery
derives the binding from the effect-possible (`retry`) attempts and pins it in the fence: none is
`proof: no_publish_call` with no probe; an unbound one - every attempt recorded before bindings
existed, including our historical failed run - is `recovery_transport_unbound`, refused before any
fence and never backfilled from today's configuration or an owner assertion; two different bindings
are `recovery_transport_changed`. The probe reads the identity with `create=False` before and after
its stream read; both must equal the binding, otherwise `recovery_transport_changed` (another
endpoint, database, namespace, restarted server or reset/replaced storage; the row stays `fenced`).
Equality does NOT prove historical non-delivery after entry deletion, trimming or a snapshot restore
under the same process; a restart or an alias of the same server under another endpoint refuses
rather than being proven continuous. The identical request replays `cached`; any other request for the investigation is
`recovery_conflict`: one recovery per investigation, and a failed replacement is held, never retried.
Once authorized the replacement key `<investigation>.recovery-1` is the investigation's current
dispatch, even before it is claimed: only the named program sees the investigation as unclaimed, its
normal tick claims it through the same selection transaction (the dispatch carries `recovery` and
`supersedes`, the lineage becomes `claimed` with the cycle), and the failed dispatch, run, cycle,
candidate, program counters and outbox attempts remain unchanged history. The continuation owner's
`accept_research` and its consumption read the CURRENT dispatch through the lineage, so a receipt
naming the failed attempt is `research_dispatch_mismatch` and an unclaimed replacement is
`research_dispatch_unknown`. `status` gains additive `recoveries` (lineage views) and `dispatches`
rows gain `id`, `recovery`, `supersedes` and `current`; neither schedules work. No model, council or
provider runs in the recovery, and no row is deleted or rewritten as accepted.
Explicit execution revocation (SPEC "Actual legacy research recovery: execution revocation"). A
SEPARATE request version `urn:zeus:research-dispatch-recovery:2` with `mode: execution_revocation`
and `revoke` = the assignment's exact `message_id` and outbox `source_sha256` (strict fields; version
1 stays the default strict transport-proof mode with every refusal above, including
`recovery_transport_unbound`). It substitutes ONLY the transport proof: every other precondition
above still applies, the pinned message must be the one recorded (`recovery_message_changed`), and an
existing task fence for that id is foreign (`recovery_fence_exists`). In ONE store transaction, with
no transport read, bus construction, model call or network, it quarantines the unsent assignment
through the existing outbox fence, advances the existing `execution_fences` task identity fence of
that message id to generation 1 with owner `research-dispatch-recovery:<request_sha256>` while the
task is still absent, and records the lineage `authorized` with `proof: execution_revoked`,
`fence.transport` null and the immutable `revocation` evidence (fence identity, generation, owner and
time, message digest, request digest, `delivery: unknown`). `Workflow.submit` of a late identical
delivery then refuses at `require_unused` before any task, reservation or provider start; admission
that commits first makes the revocation refuse `recovery_task_exists` and write nothing. The
guarantee covers consumers of THIS authoritative store through the existing Workflow admission only;
it is not a non-delivery claim, not a cancellation of an existing task and not control of any other
database or process. A replay (`cached`), the named program's replacement selection and claim, and
the continuation owner's `accept_research` and its consumption each re-validate the EXACT retained
fence first; a missing, changed or corrupt fence, a task that appeared or a released quarantine hold
by name (`recovery_revocation_fence_missing`, `_fence_changed`, `_corrupt`, `_breached`,
`recovery_publication_changed`; continuation prefixes `research_`) and never release. Any other
request for the investigation, including a version-1 request after a revocation, is
`recovery_conflict`. Lineage views gain additive `mode` (`transport_proof` for version 1) and
`revocation`.
Settled read-only successor (SPEC "Real council progress: isolated delivery and settled-read-only
successor"). A SEPARATE request version `urn:zeus:research-dispatch-recovery:3` with `mode:
settled_read_only_successor` pins the investigation, the CURRENT head (`predecessor.lineage_version`,
`lineage_request_sha256` and its `dispatch` `<investigation>.recovery-<version>`), that failed dispatch's
program with its `config_sha256`, cycle, run, manifest and snapshot, and a NEW registered program with
the same authority. It qualifies only a head already claimed by that dispatch, resolved `failed` with
`foreign_message`, whose program is blocked, whose run row is terminal `failed:foreign_message` at a
read-only stage (research/packet/snapshot/dba) with no operation, promotion, design or `.impl`
residue, no session event, roles and slots only `researcher`/`dba` (`lead:researcher`, `lead:dba`),
every slot and every reservation settled, no termination record, and every task of the run a succeeded
read-only role bound (`role_binding` + `execution_evidence`) to its OWN settled accepted reservation and
execution artifact, read through the executor's artifact store (`recovery_evidence_missing`,
`_corrupt`, `_unavailable`, `_mismatch`). Named refusals: `recovery_successor_stale`,
`recovery_predecessor_active`, `recovery_dispatch_not_failed`, `recovery_effect_unknown`,
`recovery_not_settled_read_only`, `recovery_run_not_settled_read_only`,
`recovery_effect_outside_read_only`, `recovery_invocation_unsettled`, plus the program, cycle,
replacement and scope codes above. Artifacts are read OUTSIDE the store transaction; ONE writer
transaction then re-reads everything, requires the retained chain to hold (the original revocation
fence first), quarantines the run's unsent publications through the existing outbox fence, and appends
the immutable row `research_dispatch_successors/<investigation>:<version>` (predecessor, replacement
dispatch `<investigation>.recovery-<version>`, fence list, bound executions and the predecessor's
`calls` counted as settled - never relabelled or reused) and moves the versioned head
`research_dispatch_heads/<investigation>`. The original recovery row is never rewritten. The identical
request replays `cached` after revalidating the chain and that the head still reaches the row; any
other request for that head is `recovery_conflict`; concurrent requests serialize to one row. Claim
release, the claim itself, `accept_research` and its consumption all use the head as the current
dispatch and hold on a broken chain (`recovery_successor_corrupt`, `recovery_successor_history_changed`,
`recovery_publication_changed`, any revocation code; continuation prefixes `research_`). Another
failure is never authorized automatically. `status` gains additive `successors` and `current` (the
head), reported apart. No bus, transport read or model call.
Settled council contract failure successor (SPEC "Settled council contract failure recovery"). Council
field bounds have ONE table, `domain.council.FIELD_LIMITS` (DBA `summary` 4000, each `unknowns` item
1024; improvement lead `summary`, `rationale` and each `transition` field 4000, characters of the trimmed
value, the unchanged `_text` rule). The consumer refuses a value of the wrong type, empty or over its bound
with `CouncilFieldRefused`, whose fixed `reason_code` is `council_field_invalid:<role>.<field>:<type|empty|
too_long>` and never echoes the value; a council run stops with that exact code (the DBA keeps
`report_invalid`), nothing is truncated or retried and the role output stays as recorded. The provider-facing
schema states the same bound as a `description` annotation (not `maxLength`) and the role guidance repeats
it; text the DGE validator owns keeps its own limits. A SEPARATE request version
`urn:zeus:research-dispatch-recovery:4` with `mode: settled_contract_failure_successor` carries the version-3
fields plus `failure {role, task_id, execution_ref, check}`: `role` `improvement_lead`, `check` a field code
of that role. `predecessor.lineage_version` 0 names the INITIAL dispatch (`dispatch` = investigation id,
`lineage_request_sha256` null) and is admitted only while no recovery row and no head exist
(`recovery_successor_stale`); version >= 1 is the current head exactly as in version 3. It qualifies only a
dispatch resolved `failed` with `council_field_invalid` or legacy `debate_refused`, whose run row is terminal
`failed` at the failed role's stage with reason the typed code or the legacy `debate_refused:ContractError`,
whose roles, tasks and slots are exactly the council prefix up to the failed role (researcher, DBA,
research lead, improvement lead; never the conductor or a worker), every one succeeded, bound to its own
settled accepted reservation and artifact, with the session holding only the earlier debate events and no
decision, no operation, promotion, design or `.impl` residue and no termination. The pinned task and artifact
must be the failed role's own (`recovery_evidence_mismatch`), the earlier debate outputs must still derive,
and the failed role's bound artifact answer, replayed through `council_output` under the snapshot, report
and packet its task carried (equal to the run's frozen digests), must raise EXACTLY the pinned code: a
recorded reason, legacy or typed, is never accepted alone (`recovery_failure_not_proven`). Version 1 stays
the original recovery's replacement, so a successor of the initial dispatch is version 2
(`<investigation>.recovery-2`, head `previous.version` 0); `successor_held` admits that first row only with
proof `settled_contract_failure`. Rows, head, fences, replay, conflict, serialization, claim, current-dispatch
consumers and scoped-receipt holds are the version-3 ones; the row adds `failure` (the pinned fields plus the
answer's `output_sha256`) and views gain additive `failure` (null for version 3). The failed run, tasks,
outputs, session and dispatch are never rewritten or reused as accepted.
Run-scoped delivery. `zeus autonomous run` builds ONE `RedisBus.for_run(url, manifest id)`: the
configured `HARNESS_REDIS_NAMESPACE` stays the prefix and `:run:<first 32 hex of sha256(run id)>` is
appended, shared by the run's outbox relay, role drains and Operation, distinct across runs and equal on
restart. Exact-correlation guards and `foreign_message` are unchanged; old shared streams, groups and
pending entries are never migrated, ACKed, deleted or republished. The run row and receipt carry
additive `bus: {namespace}` (null when the bus names none). The version-1 transport probe reads the
failed run's scoped namespace only when that namespace holds its own storage token, otherwise the
configured one; the owner still compares the full committed identity. Other global consumers keep the
unscoped bus.
Authoritative publication route (SPEC "Council isolation resubmission"). `RedisBus.for_run` carries the
trusted `route {scope: run, run_id, namespace}`; the unscoped bus carries none. `AutonomousRun.claim`
refuses `route_mismatch` when that route names another run, and in the claim transaction (before any
message of the run) pins `outbox_routes/<correlation>` = `urn:zeus:outbox-route:1 {scope, run_id,
namespace, pinned_at}` for `autonomous:<id>` and `operation:<id>.impl`; the row's `bus` then gains
`scope: run`. A pin is written once: an equal route is idempotent, a different one refuses
`route_conflict` and is never replaced. Every relay, global or correlation-scoped, rechecks the pin in the
prepare AND the publish transaction: only a bus whose route equals the pin publishes; the unscoped relay
leaves the record pending (`route_held`), another run route refuses (`route_refused`), and a malformed pin
or a row with `bus.scope: run` whose pin is missing is `route_unavailable` for every relay, never a global
fallback. Held records get no intent, attempt, quarantine or sent flag; a pin changed after the intent
marks that attempt `route_changed_before_publish`. Route counters appear in relay results only when
non-zero; `route_refused`/`route_unavailable` set the global health row to `attention`. Unpinned
correlations, including historical rows with no bus or a bare namespace, keep the legacy route; nothing
already sent is moved or resent. Rollback limit: reverting the code leaves `outbox_routes` rows as inert
history, and the old global relay would again publish pending pinned records on the shared streams.
`status`, the additive read-only monitor source `research_programs`
(`urn:zeus:research-program-monitor:1`, at most 20 programs, `truncated` explicit) and the bounded
`runtime/research-program/<id>/report.md` project counts, states, codes and outcomes from the store
only; the local JSONL event log carries general/development/operations records with identifiers,
counts and codes; none of them carry configs, feed bodies, exception text, credentials or DSNs.
No retry, merge, deploy, service install, budget grant, scope change or generated goal.

## INV-AUDIT-SERVICE-001

`zeus audit-service run|status` is the one host entry point that runs ONE explicitly selected
source audit through the existing owners; it adds no second analysis engine, source reader,
scheduler, promotion authority or budget ledger, and it never activates a release, merges,
deploys, executes source code or runs an audit action other than `audit_partition`. `run` takes
the host lock (`<runtime>/audit-service.lock`, process lifetime, one owner per configured runtime)
and then the read-only gate: `research_control/activation` must be `active` and name the CURRENT
`deployment/active` release, the control and `research_control/graph` revisions must equal this
checkout's revision, the graph organization digest must equal the current organization, and the
`--audit-id` must name an imported, partitioned audit. A busy lock, an inactive, paused, legacy or
stale activation, a foreign revision or graph and an unknown or unpartitioned audit all return a
fixed reason code BEFORE an observer, an executor, a transport or any provider is built. The
existing `Releases` reconciliation stays the only activation authority; this command writes none.
That same read-only gate, plus an observed stop, is re-read at EVERY new admission and again
immediately before the executor, never trusted from startup: a release paused, rolled back or made
stale mid-run, a changed revision or graph, a gate read that fails (`activation_unavailable` -
unknown is not permission), and a stop observed while this assignment's own message was in flight
(`service_stopped`) each bind nothing, enter no executor, leave the queued assignment and its
evidence exactly where they are, and record the reason in the stop reason and the durable row. That
guard admits work; it never kills, retries or reinterprets an attempt that was already admitted.
Admission uses the existing records only: `schedule_audits(audit_id=...)` is the same scheduler
with an optional backwards-compatible filter (the narrowed pass admits that audit's partition,
proposal and adoption assignments and leaves discovery, acquisition and every other audit to the
existing global pass; generation deduplication is unchanged), the correlation-scoped outbox relay
publishes only this assignment's own records, and delivery accepts ONLY the message whose id,
correlation, recipient, action and audit match the selected assignment. A foreign stream entry a
read hands to this consumer is counted and left unacknowledged in this consumer's pending list, so
the existing consumer-group recovery returns it to its owner: never acknowledged, dead-lettered,
submitted, rewritten or published by this service, and an unsent foreign outbox record stays unsent. Exactly one task runs
at a time, claimed through `Executor.execute_one`'s expected id/correlation/status guard, so a
claim policy that would take another row refuses before the fence, the lease and any provider
entry; that refusal stops this service and changes nothing about the other row. Completion is the
existing `Workflow.complete` plus `ResearchAudits.checkpoint`: the partition record itself supplies
the generation and the remaining counts, which are scope arithmetic and never a semantic or review
credit. The narrow `audit_service` row holds only the owner, the bound task, the last result, the
completion count, the last collection health and the stop reason; the durable `schedule`, `tasks`
and `research_partitions` rows remain the authority. A restart settles a bound task only when its
stored row succeeded under the same correlation; a running, queued, retried, failed or unreadable
attempt is `reconciliation_required` and admits nothing, and a recorded predecessor that did not
succeed keeps blocking until its own row succeeds or its execution generation advances through the
existing recovery or cancellation path. Nothing here retries an attempt, rewrites a historical
failed task or restarts a lost one; the existing process-tree owner handles children on a signal.
What an execution DID and what its content was JUDGED to be are two separate facts everywhere this
service reports: the step, the summary, the durable row, the task observation and `status` carry
the task status AND the analysis outcome read from that execution's own durable result
(`analysis_checkpointed`, `analysis_rejected`, or `analysis_unclassified` for a result carrying no
marker, historical rows included; a foreign value is `unknown`, and a reference that is not an
immutable artifact handle is dropped). A rejected draft is a completed execution: it settles, lets
another partition run, and the existing same-generation schedule key holds its partition with no
automatic retry or reassignment by this service, which needs an explicit reviewed decision.
`status` counts those outcomes and lists each held current-generation partition with its task,
evidence reference and fixed reason code; it rewrites, completes or reclassifies no history.
Evidence, receipt, ownership, transport, store and checkpoint failures are unchanged: they are
execution failures, they still stop admission and they are never reported as a rejected draft.
`--max-tasks N` (1..100) is a finite acceptance mode, not a call cap: it stops after N successfully
settled executions, rejected drafts included, so a run cannot evade its own bound, and it leaves
every queued successor and its evidence untouched; `--once` does the ready
work and exits. The observations are four declared events (`operations.audit_service_started`,
`_scheduled`, `_task`, `_stopped`) carrying identifiers, fixed codes and counts only, plus the
existing collection record; prompts, cursors, source text, partition scope and credentials have no
place on them. `status` and the durable row expose the activation, the supported action, the
current task, the predecessor result, the checkpoint generation and remaining counts, the
assignment states, the collection health and the stop or block reason, and they read the store
only. Fixture executors, buses and releases in the tests are not evidence that a provider, Redis,
PostgreSQL or a host service ran.

## INV-AUDIT-PROGRESS-001

Goal-progress feedback for ONE selected source audit: the existing audit service observes its own
records and, after two comparable low-yield windows, records ONE research candidate for the existing
research program. It adds no scheduler, analysis engine, source reader, executor, promotion
authority or budget ledger; it calls no model and no provider; it starts, retries, cancels, merges,
deploys and rewrites nothing; and it never writes a `tasks`, `schedule`, `research_*` or
`fleet_jobs` row. Thresholds are the packaged `audit-progress-policy-v1.json`
(`urn:zeus:audit-progress-policy:1`: version 1, `window_executions` 1..100, `minimum_semantic_paths`
1..1000, `low_yield_windows` 2..10, an authority note): versioned Git data, strictly validated,
never model input, never defaulted when broken and never edited at runtime. It is owner policy that
is not externally validated and asserts no healthy rate for any project. ONE observation reads the
authoritative rows in a short transaction (the audit, its partitions, the coverage rows through the
EXISTING `ResearchAudits._coverage`/`_observed` authority, the terminal `tasks` rows bound to that
audit and the source-read receipts), verifies the evidence bodies through the existing artifact
store OUTSIDE any transaction, then re-reads the same rows and commits only when that binding digest
is unchanged (`state_changed` writes nothing). An unknown audit, an unpartitioned audit, a malformed
record, an unreadable store and any other failure are `degraded`: fixed reason code, nothing
written, no window, no strike, and explicitly separate from the audit execution's own success.
Durable state is `audit_progress_state` (one row per audit) and `audit_progress_windows` (one
receipt per closed window). An epoch is audit + inventory/partition scope digest + policy digest +
release + revision; a changed scope, policy, release or revision starts a NEW epoch with a new
baseline, never rewrites history and never compares across epochs. The baseline counts every
already settled execution, so historical work can never earn a strike. A settled execution is a
terminal `tasks` row (succeeded/failed/cancelled/expired/blocked/superseded) identified by
task+generation+attempt+status, so a replay, a duplicate tick or a restart counts it once; queued,
running and retrying rows are live work, never counted, never called stalled and never treated as
cancelled because another task finished. Exactly `window_executions` uncounted settled executions
close exactly ONE comparable window per reading, and that exact size is the ONLY shape that can ever
count as a strike. MORE than `window_executions` is an overflow: the whole unseen cohort is consumed
ONCE by a single `not_comparable` (`window_overflow`) receipt that reports its real execution count,
honestly larger than the configured size, every one of its identities is counted, and the next
window opens at that same complete reading. Nothing is left over, because an overflowed cohort has
no historical per-execution measurement and none may be inferred: keeping a remainder would hand old
executions a NEW opening measurement they never earned and invent a zero-gain strike out of work
that was never comparably observed. A duplicate or restarted reading after an overflow therefore
closes no window at all, and two wholly NEW low windows still trigger normally afterwards. Each
window reports LITERAL semantic paths, semantic subsystems, every other disposition counted
separately, remaining paths/subsystems, open questions, the execution count, the observed elapsed
seconds and the distinct verified source-read ranges. `semantic_paths` counts the literal `semantic`
path disposition only: `unreviewed` and `unavailable` are no coverage, and `generated`, `duplicate`
and `binary` stay entirely VALID completions for `ResearchAudits._coverage`, the remaining paths and
the completion verdict while counting as non-semantic here, so a disposition change alone is never
semantic gain. A range is (source object or inventory path, start line, start char, next line, next char)
from the reader's own verified output: DISTINCT RANGES, never unique bytes and never reviewed
coverage; two receipts of one immutable body are one range, a repeated range is no new evidence and
source-read evidence is never semantic completion. Net progress is gains minus regressions, so a
shrunken semantic set is visible and negative, and a subsystem gain never hides a semantic path
regression. Verdicts: `audit_complete` when the EXISTING audit completion contract holds (binary,
generated and unavailable dispositions stay valid); `unknown_evidence` when any evidence was
unreadable or unintelligible; `not_comparable` for an overflow cohort; `adequate_progress` when the
NET semantic PATH delta alone is at or above `minimum_semantic_paths` - subsystem progress is a
separate reported fact and is never added to that threshold; `low_semantic_yield`
when new ranges appeared without semantic gain; `no_new_evidence` when neither did. Only the last
two add a strike; every other verdict clears the streak, because a comparison that did not hold is
not evidence of low progress, and unknown evidence is never a known zero or a second strike. At
`low_yield_windows` consecutive low windows of one epoch, ONE `portfolio_investigations` row of the
explicit `audit_progress` kind is written in the owner's undecided `research_required` state with
the audit, epoch, policy digest, the fixed reason code, the window ids and their membership digests
and the bounded metrics. It carries NO job ids and no Fleet status: an empty membership is never
presented as a failed-job family, `application/portfolio.py` groups and projects failure families
exactly as before, its `investigations` queue keeps its previous shape and content, progress rows
are projected apart in the additive `progress_investigations`, and the failure-family eligibility
rule skips another kind before it is scanned, so its counts are unchanged. One candidate per epoch:
a later streak only appends a bounded observation and preserves the owner's disposition, evidence,
decision, windows and reason code. Consumption is the EXISTING research program. The optional
`audit_progress_source` (`{"topic": "<configured topic id>", "audit_ids": [...<=10 distinct
pattern-bound ids]}`) is opt-in per program; absent keeps the legacy canonical config and its digest
byte-identical, and `null`, `[]`, a wildcard, an unknown topic or any other field is refused with a
field name only. Inside `record_collection`'s existing transaction the candidates are synthesized
from the authoritative `portfolio_investigations`, `audit_progress_state` and
`audit_progress_windows` reads only - an adapter that supplies one is refused exactly as before -
and a candidate is eligible when it is well formed, its audit is authorized, it is still
`research_required`, its policy digest is the one in force, its epoch is still that audit's CURRENT
epoch, every window it names still exists in that epoch, is comparable, carries a low-yield verdict
and still matches the membership digest recorded with it, and no dispatch claim exists for it across
ALL programs; excluded rows become bounded fixed counts (`malformed`, `state`, `scope`, `epoch`,
`window`, `policy`, `claimed`). The claim is the SAME `research_investigation_dispatches` bucket
keyed solely by the candidate id (one claim across programs and kinds), committed with the selection
and the cycle bookkeeping; the dispatch row names its `kind`, its bounded `scope` (audit, epoch,
policy digest) and null job fields. The immutable `urn:zeus:audit-progress-snapshot:1` snapshot
(identities, fixed codes, both window receipts with membership digests, a bounded member sample with
explicit truncation, the bounded metrics, the observed time and the explicit unverified trust)
travels through the existing GitCapture and `snapshot_document` under the `audit_progress` key, so
no reader mistakes it for a failed-job family; no source text, path, cursor, prompt, output,
exception, credential or provider stream is copied. Capture, council start, the authoritative
`autonomous_runs` result reading, the failure/unknown blocking and the stale, cross-program and
unknown-result claim protection are unchanged, the two kinds are counted and reported apart in
`status`, the cycle receipts, the report and the event log, and selecting a topic is not evidence
that research happened: the existing council still owns research, challenge, arbitration and
independent review. The audit service wires the observer, takes the baseline BEFORE the first
admission and observes after each terminal settlement; the observation never admits, blocks,
retries or reinterprets an execution, its failure never changes a stop reason and never increments a
strike, and `status`, the durable row and the declared
`operations.audit_progress_observed` event carry allow-listed identifiers, counts and fixed codes
only, with a foreign status, verdict, identifier or count reduced to a declared code or null rather
than becoming a Zeus code. Nothing here promotes knowledge, completes an audit, decides an adoption
or resolves an incident: a recorded candidate is an unverified symptom to research, never a cause.
Fixture audits, tasks, coverage rows, councils and observers in the tests are not evidence that a
model, Redis, PostgreSQL or a host service ran.
Source preparation liveness (same batch): `isolated_worker.stage_source` takes an optional
`on_progress` callback and `IsolatedClaudeRuntime.run` passes its EXISTING `on_tick` heartbeat into
it, so the caller's own lease renewal and cancellation check run once the pinned entries are known,
at most every `PREPARATION_TICK_SECONDS` of materialization and once more before the caller may
create a container. It is the caller's callback: nothing extends a deadline, renews a lease on its
own, weakens an ownership or stale check, starts a watchdog or a thread, or changes the exported
bytes, hashes, paths, modes, refusals or cleanup - a caller that passes no callback behaves exactly
as before. A callback that refuses propagates unchanged between two files, so no further file is
written, no container is created or started, and the owned run record is retained as `refused`
with `preparation_cancelled`, which blocks no later run because no container ever existed.

## INV-AUDIT-REPAIR-001

A rejected source audit analysis may gain AT MOST ONE opted-in, evidence-bound corrective successor,
and what that successor achieved is reported truthfully. This owner adds no daemon, scheduler,
analysis engine, source reader, executor, provider, transport, promotion authority or budget ledger;
it calls no model; it never activates a release, merges, deploys, cancels, retries or reassigns; and
it never writes a `research_partitions`, `research_paths`, `research_subsystems`,
`research_checkpoints`, `audit_progress_*`, `fleet_jobs` or `portfolio_investigations` row. The
original task, its result, its rejection, its immutable artifact and its partition generation are
read only and are never rewritten. Admission is DISABLED by default: `zeus audit-repair enable
--audit-id <id> --task-id <task> --operator <label>` records one durable `audit_repair_activation`
row scoped to that audit and that rejected task (the task must exist, belong to that audit and carry
its own recorded rejection), `disable` prevents NEW admission only and leaves every recorded lineage,
its evidence and its settlement intact, and `inspect`/`status` are store (and artifact) reads that
create no task, no opt-in, no schedule key and no assignment. Automatic eligibility in THIS version
is ONLY the demonstrated missing structured test disposition: the settled task succeeded, its own
durable result carries `analysis_rejected` with `analysis_content_rejected`, the recorded
`error_type` is the pure decoder's own `ContractError`, and the recorded `error_digest` equals the
digest of a validator message this diagnosis is bound to (`Missing subsystem trace: tests`).
Classification is structured content plus the validator's identity, never model prose, an exception
substring or a subtype: `AuditDraftRejected` from `ResearchAudits.checkpoint`, every other validator
message, an unclassified or checkpointed result, a failed, cancelled, blocked, retried, queued or
running task and a foreign audit are not eligible and are reported as the fixed reason they are
(`unsupported_diagnosis`, `not_enabled`, `out_of_scope`, `unknown_task`, `unknown_partition`,
`foreign_partition`, `generation_changed`, `evidence_missing`, `evidence_unreadable`,
`evidence_mismatch`, `replay_unavailable`, `replay_mismatch`, `no_correctable_identity`,
`lineage_exists`, `family_closed`, `binding_changed`, `predecessor_unpublished`, `no_candidate`,
`research_inactive`, `unresolved_termination`, `control_unavailable`).
The rejection must still HOLD its partition at the generation it was assigned, and the predecessor's
own correlation must have no unsent outbox record. The immutable artifact is inspected and read
OUTSIDE any transaction and the pure content decode (`AuditExecution.proposed_checkpoint`, the same
half of the boundary that refused the draft) is replayed against the trusted stored partition and
the retained answer: only the refusal's TYPE and the digest of its message leave that replay, and
the admission is eligible only when the replay reproduces exactly the refusal the record claims.
Absent, modified, unreadable or mismatched evidence, an unavailable replay and a draft that now
decodes cleanly are all ineligible - unknown is never permission, and nothing is repaired, decoded,
normalized or deduplicated. The lineage identity is derived from the durable records (audit,
partition, partition generation, original task, its execution generation, the diagnosis), so a
repeated tick, a restarted service and a concurrent admission caller find the SAME
`audit_repair_corrections` row instead of creating a second call. In ONE store transaction the
admission re-reads the activation, the task, the partition, the SAME `research_control/activation`
run gate the host service reads and the `observation_terminations` markers of the execution being
corrected, refuses unless the exact binding it was diagnosed against is unchanged, refuses a paused
or unreadable control (`research_inactive`, `control_unavailable`) and an unconfirmed or
pending-reconciliation marker of that execution (`unresolved_termination`) - an unresolved marker is
the operator's alone to resolve and unknown is never permission - and writes the correction record,
the complete diagnosed target set, the ordinary `audit_partition`
assignment into the existing outbox, a `schedule` row under its own deterministic
`repair:<correction>` key carrying the same `partition_id`, and the durable `events` audit record.
The successor is an ORDINARY assignment: same action, same agent, same audit, same partition and the
SAME trusted partition generation, plus a bounded `repair` context (schema, correction id, source
task, the immutable artifact reference, the fixed diagnosis and field, the assigned identities whose
record carried no test disposition, bounded and counted, and the owner's own versioned checklist).
No draft, validator message, prompt, source text or exception text is ever copied into an
assignment, a record, a log or a status read. An executing worker allow-lists that context before it
reaches a prompt, so a foreign or malformed context is dropped and no assignment can smuggle
instructions into an analysis. `schedule_audits`, the correlation-scoped relay, the Redis delivery,
the `Workflow` claim guard, the fence, the lease, `check_expected`/`require_expected`, the claim
order, `created_at`, the audit progress observer and every existing validator are UNCHANGED: the
correction takes its turn like any other queued assignment, is never preferred, reordered or
re-prioritized, and the analysis contract gains only a fixed pre-submission checklist (a justified
`tests_not_run` entry remains an accepted incomplete result, never a fabricated pass) and no hidden
model-validation loop. Settlement is reconciled from terminal task evidence and is idempotent: a
missing or live successor stays `admitted` (`successor_not_submitted`, `successor_pending`), a
successor bound to another record is `reconciliation_required` (`successor_unbound`), a failed,
cancelled, expired, blocked or superseded successor is `reconciliation_required`
(`execution_unresolved`) and is NOT a strike, a succeeded successor whose own result is
`analysis_rejected` records `research_required` (`content_rejected_again`) ONCE and closes the
family, and a succeeded, checkpointed successor is `repaired` only when EVERY originally diagnosed
target identity carries a subsystem record persisted by THAT successor's own execution with a
justified test disposition - a corrected subset is `deferred` (`partially_corrected`) and no
corrected target at all is `deferred` (`no_corrected_subsystem`, `unclassified_result`). Settlement
counts the COMPLETE diagnosed target set retained on the lineage row, never the bounded list the
assignment carries, so a truncated recovery context can never shrink the denominator, and it counts
only identities in that set, so valid work the successor did outside it stays valid and still yields
a deferred repair; `target_subsystems`, `corrected_subsystems` and `remaining_targets` are reported
separately and a partial correction can never read as a whole repair. Those records are read from
the immutable `research_evidence_history` rows of the successor's own execution, not from
`research_subsystems`, whose latest-row-per-item semantics would let a later ordinary checkpoint
take the credit for, or erase, what the successor persisted. A checkpoint is resumed partial work,
never subsystem acceptance: a corrected record whose tests were justifiably not run leaves that
subsystem in the remaining scope. The original and the successor are the only two attempts: after
any terminal state the family is closed (`family_closed`) and there is no automatic third call, no
fabricated research completion and no claim that a recorded `research_required` means research ran -
source investigation remains the existing ResearchProgram/Codex responsibility. A lineage that
reaches `research_required` writes, in the SAME transaction as that terminal settlement, ONE
deterministic informational `execution.notice` to the executing agent's own lead over the existing
direct reporting edge, plus that notice's own outbox record, so the second strike can never be
stored without the message that reports it. The existing notice builder is extended NARROWLY for
this case alone: a `succeeded` execution is notice-eligible only when its own durable result records
`analysis_rejected` AND the authoritative repair lineage proves `research_required` for exactly that
successor, no arbitrary succeeded row becomes eligible, no row is relabelled `failed`, and the
reason `research_required` may be raised on no other status. The notice identity is the digest of
the lineage proof (correction, family, audit, partition generation, diagnosis, both tasks, both
immutable execution references, state and reason), it retains both execution references as evidence
references, and it is published by the existing correlation-scoped relay under the lineage's own
correlation even when no further worker assignment exists there. Publication is read from the
notice's own outbox record and never assumed: a failed publication keeps that record unsent and is
retried by a later tick or after a restart, a repeated settlement, a lost commit response and a
duplicate delivery all return the SAME notice through the existing proof-checked
commit-before-acknowledgement receive, and receiving it is `informational_only` - it performs no
research, queues no task or decision and authorizes no third call. The audit service asks this
owner for ONE tick under its SAME admission gate (settle, then admit at most one successor), relays
the pending lead notices of that tick through the existing scoped publication, records the bounded
facts in its `last_repair` row and summary, and reports them in the two declared observations
`operations.audit_repair_admitted` and `operations.audit_repair_settled` (identifiers, fixed codes
and counts only, both immutable artifact references as evidence references, a foreign value reduced
to a declared code or null); execution success, analysis rejection, repair settlement and notice
delivery stay four separate facts in every projection. A repair failure is `repair_unavailable` and
a failed notice publication is that attempt's recorded error type beside an unsent notice record;
both are bounded recorded facts that are never an execution outcome, a stop reason or permission to
repeat an attempt.
`zeus audit-service status` gains `repair`: the opt-in, its scope, each source task -> diagnosis ->
successor -> settlement and the SEPARATE counts (attempted, admitted, repaired, deferred,
research_required, reconciliation_required); the rejected history is preserved and a hold disappears
only because the verified lineage advanced the partition's own generation, never because a refusal
was erased. Fixture audits, tasks, artifacts, buses and executors in the tests are not evidence that
a model, Redis, PostgreSQL or a host service ran.

## INV-SERVICE-DIAGNOSTICS-001

`service_entry` (`python -m codex_harness.adapters.service_entry --journal PATH -- CLI_ARGS`) is
bounded lifecycle provenance for a service run whose stdout and stderr the launcher discards
(docs/zeus/operations/self-improvement-reference-001/SERVICE-DIAGNOSTICS.md). It passes the
arguments after `--` to the existing `codex_harness.cli.main` unchanged through a scoped `sys.argv`
replacement that is restored however the call ends, and it owns no process: `background_service`'s
`ProcessTree` remains the sole process owner, and this adapter starts, retries, releases, kills,
budgets and configures nothing. The CLI's exit status is preserved - an `int` `SystemExit` code
including `0`, a `bool` as its integer value, `None` as success - while an uncaught exception or a
non-integer exit code is
the fixed 1 whose value is never formatted, `KeyboardInterrupt` is 130, and a failure of the
diagnostics themselves is 125 and outranks the CLI's own number, so a run that could not be
described durably is never reported as success. The journal is `background_service`'s rotating
JSONL primitive reused under its own logger name and its own typed allowlist, leaving the owner's
journal, handler and fields untouched; a journal that cannot be opened or refuses the pre-start
`start` entry never invokes the CLI at all, and a post-start failure is stated in whatever entry
still reaches the file. Each run writes `start`, `finish` and `exit` carrying one generated run id, so
sequential runs in one file stay separable; one journal belongs to one service instance, and
concurrent owners stay prohibited by the existing process ownership. Facts are allowlisted by name
and by shape and anything else is dropped rather than sanitized: a reason from a closed vocabulary,
the name of a *built-in* exception type or the fixed `unknown` (a look-alike defined elsewhere is
`unknown`), at most the eight deepest frames inside the installed `codex_harness` package as a
package-relative module path plus an integer line, and a bounded four-link `__cause__`/`__context__`
walk that respects `__suppress_context__`, reports an absent cause explicitly and ends on a cycle
instead of following it. No exception message, `repr`, argument, local, `argv`, environment value,
source line, absolute path, raw traceback or CLI output is ever read into the journal or printed.
This records where an exception left the package; it is not a root cause, it observes no child
process cleanup, and it cannot exist for a `SIGKILL` or a failure before the interpreter starts.

## INV-DECISION-FEEDBACK-001

`zeus decision-feedback collect|status|report` joins conductor decisions that already exist with the
actual outcomes of the runs that carried them, and identifies repeated procedures — successes
included — as unverified improvement candidates
(docs/zeus/operations/self-improvement-reference-001/DECISION-FEEDBACK.md). It owns no decision, no
conductor and no promotion: `council.py`/`autonomous.py` remain the only writers of runs and role
executions, `dge.py` of sessions and events, `service.record_incident` of incident recurrence
(INV-RECURRENCE-001) and the existing knowledge owners of verified promotion. Nothing here calls a
model, opens a network connection, executes registry content, dispatches work or activates a policy.
An observation is admitted only when one execution identity binds across four existing rows: the
`autonomous_runs` row names the session, the `dge_sessions` row is `executor_bound` and owned by that
run with the run's packet digest, the conductor's `dge_events` row is the executor-bound arbitration
slot of that session carrying a task id and an `execution_ref`, and that `tasks` row is a succeeded
`conductor` execution whose result carries the same reference, generation and attempt, which the
run's own role binding repeats. Matching reference strings are not evidence: the artifact stored at
that `execution_ref` is read through the existing execution-evidence port and checked by the existing
`execution_evidence` rule against the authoritative `invocation_reservations` row, so credit needs
this task's own exact answer, hashing to the binding's `output_sha256`, from the settled `accepted`
reservation of this task, generation, attempt and conductor stage at the session's base revision; a
collection without an artifact port refuses (`evidence_port_unavailable`) rather than crediting rows.
Any gap is one fixed reason code — `run_identity_unknown`, `foreign_repository`, `source_kind_unknown`,
`decision_session_unproven`, `work_contract_unknown`, `decision_event_unproven`,
`decision_execution_unproven`, `decision_artifact_missing`, `decision_artifact_corrupt`,
`decision_artifact_invalid`, `decision_artifact_unproven` — with no observation, no group and no
evidence credit; absent historical fields stay unknown and are never defaulted or repaired. Version 1
reads council (autonomous v2) runs only, stores identities, digests and closed vocabularies (outcome
state, arbiter verdict, disposition count) and never copies rationale, scenario, packet, payload,
answer or credential text.
Outcome states are `pending`, `accepted`, `rejected`, `failed`, `cancelled` and `unknown`; the exact
source status, reason code and provenance are preserved beside the state, an unmapped or missing
status stays `unknown`, and a terminal `accepted` is operation acceptance only — never proof that the
decision was correct, that the change was deployed or that product acceptance passed. Decision
quality is always reported `unknown` in this delivery: downstream success or failure alone never
establishes it, and no owner-supplied label, confidence or acceptance-rate target is accepted.
Comparability is exact and owner-authored. The registry (`urn:zeus:procedure-registry:1`) is read
with `GitSource` at a 40-hex commit the caller names, never from the working tree; its bytes are
bounded, parsed as strict JSON with duplicate keys refused, and every entry pins a safe token id, the
source kind, the exact repository identity, the complete allowed-path set, the sha256 of the exact
acceptance-criteria list in the plan's own order, and a remediation kind of `skill`, `script` or
`existing_owner_review`. Matching compares those four contract values only: no title, substring,
family, regular expression, model-selected cause or executed rule exists, and an empty or ambiguous
match is `unknown` and never reaches a threshold. Runs group on exact contract equality, so different
repositories, scopes or criteria never merge.
Two distinct executed run identities in one group create exactly one advisory candidate per
repository, procedure and registry revision; it says `needs_analysis`, is explicitly unverified and
grants no publication, activation or execution authority. Attempts, retries, replayed events, copied
receipts, repeated collection and imported experiences are not additional occurrences. A group keeps
its distinct run identities durably (exactly, up to 1000 per group, beyond which it reports
`membership_capped` and counts no further run), and the candidate's at most 50 occurrence references
are a bounded window derived from that membership rather than an accumulating list, so re-collecting
a group that is already larger than the window inflates neither the distinct-run count nor the named
unreferenced remainder. Decision facts are
immutable: a changed decision digest, or a changed history after a terminal outcome, is recorded as a
conflict for owner inspection and the stored observation is left exactly as it was, while a run that
was still in flight may later join its real terminal outcome with the previous state kept in a
bounded history. Because the bounded page is read in one transaction and recorded in the next, a
differing outcome is revalidated against the authoritative run row inside the recording transaction
before any conflict: a page that went stale while another collector recorded the same terminal
outcome is counted stale and changes nothing, a row that cannot be re-read stays unknown, and only a
history that really changed is a conflict. Only `decision_observations`, `decision_feedback_groups`,
`recurring_work_candidates`, `decision_feedback_conflicts` and the collection receipt are written,
all in one transaction, so concurrent collectors and restarts converge on the same rows.
One collect scans a bounded ascending page of run ids (default 100, maximum 500) and reports scanned,
eligible, unknown by reason, conflicts, truncation and a continuation cursor; the counts describe that
page. A store or driver failure is `source_unavailable`, never an empty result, and a refused
collection writes nothing. Replay, held-out evaluation, policy activation and skill or script
extraction are out of scope here and are named as limits in every receipt and report.

## INV-HOST-DELIVERY-001

`zeus host-delivery register-targets|register|tick|run|status` carries an ALREADY reviewed release
candidate from its repository to an actual host runtime, and adds no approval, evaluator, executor,
scheduler, merge policy or deployment authority
(docs/zeus/operations/autonomous-operation-001/HOST-DELIVERY.md). `Releases` remains the only
approval and the only active-release compare-and-swap, `ReleaseQueue` the only controller fence,
`GitWorkspace` the only publisher and merger, and the registered scheduled task or owned child
process the only thing that runs. Delivery is opt-in: without `ZEUS_HOST_DELIVERY_ENABLED` a tick
registers, projects and refuses every external action, and while it is off not even a durable intent
is written. The legacy Docker `ReleaseRunner` is not enabled, driven or replaced by this component.

A delivery plan (`urn:zeus:host-delivery:1`) is owner-authored, read through the existing `GitSource`
at an explicit 40-hex commit and never from the working tree: `plan_id`, the EXISTING `release_id`,
the candidate `revision`/`tree` (the tree is the exact Git object id the candidate recorded, 40 or 64
lowercase hex, never a substituted digest), the incumbent `policy_hash`, the canonical `repository` identity,
1..16 named `required_checks`, a registered `target_id`, the `expected_descriptor` digest (or `null`
for a target's first activation), a `target_descriptor` of revision plus worker image and profile
digest (each an exact identity or the explicit word `unchanged`, which resolves against the
descriptor the target is actually running and refuses when there is none —
`unchanged_without_predecessor`), one `canary_check_id` from the incumbent fixed set, and bounded CI
and consumption timeouts. Unknown or missing fields, a malformed
identity, a duplicate or empty check list, a canary id this harness does not implement and an
out-of-range timeout are refused before anything is stored. No shell command, argv, path, host root,
service name, source text or credential is ever accepted from a plan, and nothing in one is executed.
What a target IS - its kind (`windows_scheduled_task` or `process`), its root, its state directory
and its service identity - is host configuration (`urn:zeus:host-delivery-targets:1`) registered
separately by the owner; a plan may only NAME a registered target id (`target_unregistered`), so a
candidate can never select another scheduled task, path or policy for itself. Registration is
idempotent for the identical plan at the identical pin, and a plan whose delivery has left
`registered` may not be edited at all (`delivery_in_flight`); a refused registration writes nothing.

Approval is recognized, never synthesized. `release_gate` re-derives it from the release record
itself: the candidate's revision, tree, evaluator `policy_hash` and canonical repository must be
exactly the plan's (`release_revision_mismatch`, `release_tree_mismatch`,
`release_policy_mismatch`, `release_repository_mismatch`), and the author's OWN lead plus a
conductor must both have accepted that exact revision with evidence. An incomplete review projects
`awaiting_review` and runs nothing - no queue row, no lease, no publication - and a rejected,
cancelled, rolled back or ticket-superseded record refuses. The host is touched only once the
incumbent evaluator itself recorded `verified` (`release_not_verified`), and the active release
pointer moves only through `Releases.promote` with the expected active release recorded when the
target tuple was bound, after the prescribed checks AND an actual consumption receipt.

One delivery advances at most one stage per tick under the existing `ReleaseQueue` fence:
`registered` -> `awaiting_review` -> `publishing` -> `awaiting_ci` -> `merge_intended` -> `merged` ->
`drain_intended` -> `switching` -> `awaiting_consumption` -> `active`, with `blocked`,
`rolling_back`, `rolled_back` and `failed` preserving the stage they happened at, the fixed reason
code, the error TYPE and the evidence. The durable intent names the stage BEFORE the external action
of that stage, so a lost response can only reconcile what already happened: an existing pull request
at the intended head is adopted rather than published again, an already merged one is recognized
rather than merged again, and a running instance's own receipt is recognized rather than restarted.
The controller claims only queue rows a registered plan names (so another controller's row is never
consumed or spent). Ownership is proven BEFORE every external mutation - publish, merge, drain,
switch, start, restore - and again inside that target's own lifecycle guard for the drain, the
switch and the start, so a controller whose lease expired while it waited for that guard overwrites
nothing; every durable
observation is then committed in the SAME transaction that re-checks the claim's generation, owner
and lease, and the promotion shares one transaction with its own ownership check rather than
checking and then promoting separately. A fence lost BEFORE an effect changes nothing and records
nothing; a fence lost ACROSS an effect is an explicit `conflict` carrying `ambiguous_effect`, never
a cancellation - the durable evidence is the intent that named the stage before the effect, and the
next owner reconciles the host rather than repeating the action. A tick advances at most one
delivery, so a plan it cannot act on - an incomplete review, a queue row in backoff, exhausted,
blocked, failed, cancelled or held by another controller - is skipped with its own explicit wait
reason instead of starving a qualified target; `target_busy` exclusion is unchanged, the scan is
bounded, and when nothing is actionable the first waiting plan is selected so that its own wait is
projected and nothing external happens. A long external wait never sleeps under the lease: the tick answers `pending`, returns the
lease through `ReleaseQueue.defer` (which is not a failed attempt), and the stage's own durable
deadline - not the attempt budget - ends the wait (`ci_timeout`, `rollback_unverified`). Definite
failures still go through `finish` with the queue's unchanged retry budget and backoff. No store
transaction is open across GitHub, the filesystem, a subprocess or another independently locking
transaction, and an idle poll writes no row.

CI is the provider's own answer about the exact intended head. Every required check must have
FINISHED SUCCESSFULLY: absent is `ci_check_missing`, still running is `ci_check_pending`, and
skipped, cancelled, neutral, timed out and failed are `ci_check_failed` - none of them is a pass, and
extra checks the plan does not require are ignored. A head that moved is `ci_head_changed` and goes
to requalification, never a silent rebase that inherits the old acceptance. A merge that HAPPENED is
not a qualified deployment: the merged revision is qualified against the reviewed tree by the merge
owner itself (`GitWorkspace.qualify_merged`), and the merge this controller performed and one it
only observed after a lost response take exactly the same path, so a merged tree that is not the
reviewed one is `merged_tree_mismatch` and stays blocked on every later tick.

The host boundary is descriptor-first, and ONE service is ONE lifecycle. Replacing the descriptor,
pausing, stopping the old instance, retiring its files, launching the new one and publishing the
state that identifies it all run under a single target-specific guard (`HostTargetBase.guard`),
which every controller that touches that target uses and which unrelated targets never share:
`target_lock_held` is a conflicting change on that target, waited for within its timeout and then
refused without any mutation, never broken on age - a guard that survived a crashed owner is an
actual recovery condition for the owner, not something a successor decides for itself. Inside it,
this controller's ownership is proven BEFORE the first mutation of any kind, and what is actually on
the target is reconciled before anything is touched: the descriptor must be exactly the one being
switched from (`descriptor_changed`, `descriptor_predecessor_mismatch`) or started
(`descriptor_foreign`), so a superseded controller that resumes into a target its successor has
taken over stops no service, deletes no receipt and starts no second instance. A descriptor
replacement is one atomic `os.replace`. A live instance that the incumbent `consumption_verdict`
shows is REALLY running the intended descriptor is recognized rather than killed and started again,
so a restart - forward or rollback - reconciles instead of churning the service; an instance that
merely echoes the digest from another runtime, root or revision is not recognized.

Descriptor identity and authority over a RUNNING instance are different facts, and a receipt that
does not match the descriptor being started is never by itself permission to end that instance.
Inside the guard, after the descriptor is reconciled, `instance_authority` classifies what is
actually there against the authority the coordinator passes in from its own durable intent
(`validate_replacement`: the exact descriptor digest, the instance id, and the launch record this
component wrote under that target's guard). Forward, that authority is the predecessor whose
identity was captured BEFORE the descriptor was replaced; in a rollback it is the failed CANDIDATE
this intent started, never the predecessor it is restoring, and a candidate whose startup identity
was never confirmed is reconciled by that trusted launch record rather than by a live pid. Only five
outcomes act: the `intended` live instance is recognized (no stop, no unlink, no start), the
`authorized_predecessor` and this delivery's own `owned_stopped` instance may be replaced, and a
clean target is started only on POSITIVE evidence of absence - no receipt file, no launch record and
nothing alive. Everything else refuses BEFORE the stop and before any evidence is removed: a receipt
that names another instance (`instance_not_authorized`), the named instance under another descriptor
(`instance_contradictory`), a present but missing, malformed, oversized or wrong-target receipt
(`instance_receipt_unreadable`), a live process nothing identifies (`instance_unidentified`), a
liveness that could not be read at all (`instance_liveness_unknown`) and an absence that is not
proven (`instance_absence_unknown`). The coordinator refuses earlier still when its own records and
the target disagree about who is running there (`target_instance_mismatch`), before the drain and
the switch. Both host kinds - the owned child process and the registered scheduled task - use this
one contract. Ownership is
re-checked after the bounded stop, which can outlive a lease, and a loss THERE is the ambiguous
effect it is (`service_stopped`): nothing is cleaned up or launched after it, the stopped instance's
own evidence is preserved, and the next owner reconciles the target rather than the effect being
called cancelled. New admission is paused and the drain is PROVEN before the switch: a service that
is running with no work report, or with an unconfirmed effect, blocks the switch
(`drain_unconfirmed_effects`) rather than having its active work killed. A previous instance that
cannot be proven gone is `previous_instance_unconfirmed` and no second one is started beside it. No
store transaction is open while the guard is held, it is never acquired recursively, and the
forward start and the rollback start share exactly the same protection.

The service is launched from the OWNER-REGISTERED runtime root of its target - that root as the
working directory, that root's `src` ahead of `PYTHONPATH` - and a root with no importable harness
is `runtime_root_unavailable` before a process exists. The launched process's OWN startup receipt
decides activation, and its runtime identity is OBSERVED rather than copied from the descriptor:
the package directory it actually imported, the root that package came from, the revision that root
is actually at (its own checked out `HEAD`, or the owner's `runtime.json` attestation when the root
is not a checkout) and the EFFECTIVE worker image and profile digest of that runtime, which are
configuration facts and never a model run. The root must be this target's registered root
(`receipt_runtime_root_mismatch`), the package must lie inside it (`receipt_module_root_foreign`),
and revision, image, profile and descriptor digest must be the requested ones; an old runtime handed
a new descriptor is therefore refused however alive its pid is, and a receipt that is missing,
malformed, from another target, from the previous instance or bound to any other identity never
grants activation. A switched descriptor whose receipt never arrives is not an activation either:
the consumption deadline sends it to rollback.

Observing a startup and activating it are separate durable facts: the accepted receipt is recorded
as `startup_observed` with its instance and revision BEFORE the canary runs, and `consumed` is only
the activation the canary allowed - so a canary can bind the instance and the runtime without
reading an active pointer that has deliberately not been written yet. Before every host mutation the
controller reconciles what is on the target right now: the descriptor it intended, the predecessor
it expected, or a FOREIGN state that blocks (`descriptor_foreign`, `rollback_foreign_descriptor`)
rather than being overwritten. Rollback restores the EXACT predecessor tuple and then proves it,
with that predecessor's own fresh receipt and a live process; a restoration whose durable
acknowledgement was lost is RESUMED from what the host already shows rather than attempted again,
the predecessor is started at most once per restoration, and a restoration that fails or cannot be
proven is a blocked critical alert (`rollback_failed`, `rollback_unverified`), never a `rolled_back`
claim. A target with no known-good predecessor blocks (`no_known_good_predecessor`) instead of
inventing a state to return to. Active descriptors are scoped per target, two plans on one target
serialize (`target_busy`) and unrelated targets keep moving.

The canary exercises the actual service contract, is named by an incumbent fixed id only, and is
given the OBSERVED startup it must answer about: `startup_identity` (the owned process still runs,
still names this descriptor and is still this instance), `collect_monitor_source` (a FRESH incumbent
read-only monitor projection shows this descriptor as observed-started for this target, by this
instance id and at this revision) or `fleet_worker_operation`, which is OWNER acceptance work - it
looks for the owner's own receipt for exactly this descriptor and instance and starts no model,
provider or worker itself. `canary_unavailable`, `canary_error`, `canary_source_unavailable` and
every not-passed verdict send the delivery to rollback rather than to activation.

Read-only status is projected by `host-delivery status` and by the additive `host_delivery` monitor
source, which is collected beside the existing `database`, `docker`, `redis`, `fleet`,
`research_programs`, `portfolio` and `fleet_backlog` sources and fails independently of every one of
them: plan, release, target and instance identities, the Git pin, descriptor digests, whether a
startup was observed and which instance and revision it was, the durable stage, fixed reason codes,
counts and a bounded next action. Never a descriptor body, a host root, a runtime root, a service
name, a pull request title, a check log, an exception message or a credential. Structured
transitions are `general.delivery_stage_entered`, `development.delivery_check_observed`,
`operations.delivery_switched`, `operations.delivery_rollback` and `operations.delivery_blocked`,
carrying identifiers, digests, fixed codes and counts only; a repeated idle poll re-enters no stage
and emits nothing, and a switch with `consumed: false` is never read as an activation. A collected
status is a durable-record projection: it is never evidence of a qualified live host, a passed owner
canary or a semantically accepted release.

## INV-WORKER-SESSION-001

A durable Claude task session keeps one logical worker conversation through implementation, frozen
candidate, review wait and qualified rejection correction without an idle model process
(docs/zeus/operations/autonomous-operation-001/WORKER-SESSIONS.md). It is opt-in twice: the host
constructs `Executor(worker_sessions=...)`, and a caller passes an explicit
`task_session={"task_id", "repository"}` with `max_handoffs=1`. Without both, execution is the
unchanged fresh path: `--session-id` with a new UUID per attempt, `session.resume: "unsupported"`,
the legacy isolated protocols and receipts. The packaged `providers.json` still declares Claude
`session_resume: "unsupported"` and the invocation option matrix is unchanged; native resume is this
separate, conditional path, never a capability flag.

`worker_sessions` rows (one per logical task id) hold the binding and state; the transcript bytes
live in the restricted content-addressed `SessionArchives` root (`<runtime>/worker-sessions`, never
the general artifact tree a model reads) and the row keeps only reference and hashes. The binding is
task id, repository, workspace, provider, model, runtime image, runtime, policy and config digests.
States follow one fixed matrix: `active -> checkpointed -> awaiting_review -> correction_ready ->
active`, `awaiting_review -> accepted -> archival_pending -> closed`, plus explicit
`archive_missing`, `archive_corrupt`, `incompatible` and `unresolved`; any other move is
`invalid_transition`. A foreign task/repository/workspace is refused unchanged (`session_foreign`);
a model, image, runtime, policy or config mismatch sets `incompatible` and reports that an explicit
fresh evidence handoff is required (`session_incompatible`). A turn that was never adopted reopens
fresh under a NEW session id; nothing is ever relabelled as resumed.

`begin` claims the session exclusively for one leased execution; a second owner is `session_owned`
however old the claim looks, and a claim is committed only at the row version it read, after the
archive was verified OUTSIDE the transaction. Compatibility is checked BEFORE the duplicate-owner
shortcut: the owner's own replay with a changed model, image, runtime, policy or config is
`session_incompatible` and writes nothing, so the valid owner's claim, row and archive survive; only
an exact duplicate returns the same plan. `checkpoint` puts the verified export into the archive
store (deterministic reference, read back) and THEN updates the row idempotently, so a crash between
the two replays to the same reference and a duplicate event returns the recorded checkpoint. A
resumed turn is adopted only when its transcript begins with the exact bytes of the archive it
resumed (`prefix_verified`); otherwise the session is `unresolved` (`resume_continuity_unproven`)
and only `reconcile` from retained verified bytes of this exact session continues it. A failed or
unexported turn releases the claim back to the prior resume point; an entered turn that raised is
`unresolved`. Review wait holds no owner, no reservation and no provider: `record_review` reads the
existing succeeded `review_lead`/`review_conductor` decision row for the exact frozen revision and
tree (`review_candidate_mismatch`, `review_not_succeeded`, `review_not_independent`); a rejection
makes the session `correction_ready` (eligible, never admitted: conductor continuation remains the
sole admission owner), conductor acceptance makes it `accepted`, and a rejected candidate can never
be submitted again (`candidate_rejected_immutable`).

Promotion and closure are evidence-backed. `WorkerSessions(evidence=...)` names the verified general
artifact store; without it `promote` and `close` refuse (`promotion_evidence_unconfigured`). `promote`
reads an integrity-checked receipt (`zeus.worker-session-promotion.v1`, built by
`domain.worker_sessions.promotion_receipt`) whose exact fields name this task and session id, the
accepted frozen candidate (revision, tree, base), the archive it was frozen from (reference, manifest
and transcript hashes), the accepting succeeded review (decision id, execution reference) and a
non-empty list of promoted evidence references; every listed reference and the review's execution
receipt must exist intact in the same store. A missing receipt (`promotion_receipt_missing`), any other
artifact or a changed file (`promotion_receipt_malformed`), a receipt for another session, candidate,
archive or review (`promotion_receipt_unrelated`) and missing or corrupt listed evidence
(`promotion_evidence_missing`/`_corrupt`) leave the row unchanged; a syntactically valid hash alone
is never enough. `close` re-verifies the same receipt before any cleanup, records a cleanup failure
without closing, and never deletes the archive (the default close retains it). `worker-session close`
uses `<runtime>/artifacts` as that store.

Observability: with an `observer` (the existing Observer port), every COMMITTED change of state,
owner or cleanup outcome emits one event after its transaction: `development.worker_session_transition`
or, for `archive_missing`/`archive_corrupt`/`incompatible` (outcome `blocked`), `unresolved` (outcome
`unknown`) and a failed cleanup (reason `cleanup_failed`), `operations.worker_session_blocked`. Both carry
task and session ids, state, version, the fixed `next_owner` code (`execution`, `conductor`,
`independent_review`, `evidence_promotion`, `session_owner`, `operator`, `none`) and `next_action`; a
duplicate event commits and reports nothing. The status projection (CLI and the additive monitoring
source `worker_sessions`) adds per-state counts, `blocked`, `next_owner` and reports the binding only as
`identity_sha256`; neither surface carries transcript bytes, archive paths or raw binding values, and a
store failure makes the monitoring envelope `unavailable`, never an empty list.

Transport: `ClaudeCodeRuntime(session_home=...)` alone may restore or export, and only for a
`task_session` binding; the host's own home is never read, written or resumed from, and the executor
refuses a task session without isolation. A resumed turn needs `--resume` in the installed CLI's
options, a manifest recorded for this exact workspace, and a verified restore into the empty owned
home before any process starts (each a `ClaudeUnavailable` refusal before entry); the command is
`--resume <exact id>`, never `--session-id` and never `--continue`. After the process tree is
confirmed gone, only the exact session's transcript and the regular files under that session's own
directory are exported, bounded (64 files, 64 MiB, depth 6), with dot-files, credentials, settings,
other sessions and other projects excluded by allowlist and any link or special file refused. The
isolated request names `zeus-isolated-worker-v1-task-session` (or its project-evidence twin), so an
older entry refuses it; the host stages the verified archive into THIS run's evidence mount before
the container exists (`task_session_stage_failed` otherwise), the entry accepts only the fixed
`/evidence/session-restore` and `/evidence/session-export` paths and its own `$HOME/.claude`, and the
host re-verifies every exported byte (`archive_unlisted_file`, `archive_corrupt`) before adoption.
No home and no other task's directory is ever mounted, and the export stays in the retained run
evidence until the session closes. Resumed usage is cumulative: a turn's usage is its delta against
the same session's recorded baseline and otherwise unknown; a resumed turn's cost estimate is not
attributed to it. `zeus worker-session status` is a bounded read-only projection and
`worker-session close` the explicit close; neither prints transcript bytes or paths.

Fixture tests prove the wiring against a labelled protocol child and an injected Docker fake. They do
not prove the pinned CLI's transcript layout, `--resume` behaviour under `CLAUDE_CONFIG_DIR`, or
continuity across a real container recreation; that is the owner's real two-turn probe before any
production activation.

## INV-CONTINUATION-001

The durable conductor continuation keeps one logical goal moving across FINITE operations without
editing any of them (docs/zeus/operations/autonomous-operation-001/CONTINUATION.md). It is opt-in
twice: the owner registers a Git-pinned policy (`urn:zeus:continuation-policy:1`, `zeus continuation
register --lane --revision --path`, read through `GitSource` at the commit, never the working tree),
and either the host setting `ZEUS_CONTINUATION_POLICY` names it for `zeus fleet run` or the owner runs
one `zeus continuation tick --policy`. An unregistered or disabled policy is `disabled` with zero
actions: no Git read, lane connection, process, write or model call. Every other command, the finite
Operation, LocalCycle and Fleet defaults are unchanged.

The policy binds the lanes, the repository identity, the goals (path, sha256, criterion), the
allowed paths and acceptance criteria, the session archive root digest
(`zeus continuation identity --lane`), the qualified model, image and profile, the delivery target
and `max_corrections`. A different policy under the same id is `policy_conflict`; a registered pin
whose bytes no longer resolve is `policy_unavailable`, a changed digest `policy_changed`. Membership
is immutable and applied BEFORE selection: a job whose lane, repository, goal, allowed paths or
criteria are outside the policy (`domain.continuation.check_membership`) is not this policy's work -
it is never selected, read, bound or recorded, so unrelated history never occupies a bounded pass.
For a member job, a model outside the policy, or a lane whose actual isolation image, worker profile
or archive root differs, is current eligibility: a named `refused` intent (`model_changed`,
`image_changed`, `session_archive_changed`, ...) with `next_owner: operator`; the continuation never
widens its own permission and model output never extends it.

State lives in the Fleet control store (`continuation_policies`, `continuation_intents`,
`continuation_progress`) and in each
lane store (`continuation_bindings`). The fixed routing table, over terminal Fleet jobs and their lane
evidence read outside every transaction: `failed/evidence_gate_refused` with a known handoff ->
`evidence_repair` successor (candidate preserved, fresh evidence handoff, never a resumed session);
`rejected` with a succeeded `review_lead` decision, or a conductor rejection -> `correction`
successor; the second distinct similar failure of a family -> `research` (held until the owner's
scoped research receipt for that exact intent is verified, below; replays count nothing);
`unknown`, an unknown-effect failure reason, an unconfirmed/pending termination marker or a
conductor launch that ended with its row not settled -> `recovery` for ExecutionRecovery, never a
fresh call; `accepted` ->
`conductor_review` (the existing guarded `decide_one("conductor", expected=...)` in the lane through
`zeus continuation conduct`); a conductor-accepted release -> `host_delivery` handoff to the owner's
HostDelivery plan on the policy target (`active` completes, `rolled_back`/`failed`/`blocked` holds the
family, the acceptance stays); a delivered item -> `next_item` for the approved backlog. Missing
evidence is a named refusal, never a guess; `max_corrections` successors per family, then
`correction_budget_exhausted`.

Scoped research completion (SPEC "Scoped research completion and evidence-repair delivery"): a
`research_required` intent leaves its state ONLY through an explicit owner receipt
(`urn:zeus:continuation-research-receipt:1`, `zeus continuation research-accept --file`,
`Continuation.accept_research`) stored once in the control store bucket
`continuation_research_receipts`, keyed by the intent id. The strict receipt names the exact
`intent_id`, `policy_id` and `policy_sha256`, the `family`, the COMPLETE failed attempt set
(`attempts[] {job, evidence_sha256, inspection}`: the family's distinct failure observations of that
policy since its last completed research plus the research intent's own,
`domain.continuation.research_attempts`, shown as `attempts` on the research intent in `status`), the
Portfolio `investigation` holding those jobs, the existing research dispatch binding
(`dispatch {program, run_id, manifest_sha256, snapshot_sha256}`) and 1-16 content-addressed
`evidence_refs` (`sha256:<64 hex>`). It is verified against authoritative reads
(`domain.continuation.check_research_receipt`): the registered policy row and the intent's own
policy digest; the intent route/state/family; the attempt set equal to the current one (a subset is
`research_coverage_partial`, anything else `research_attempts_changed`); each attempt's lane evidence
re-read now, its decisive digest and handoff inspection equal (`research_attempt_changed`,
`research_inspection_mismatch`, `research_attempt_unavailable`); every attempt job a member of the
failure-family investigation with its status and reason code; the dispatch keyed by that
investigation with the same binding, `resolved`, result `accepted` AND `council_result` over its
bound `autonomous_runs` row accepted (`research_unfinished`, `research_not_accepted`,
`research_dispatch_unknown`/`_mismatch`), every attempt job inside its job sample
(`research_scope_unverified`). The identical receipt replays (`cached`), another receipt for the
same intent is `research_receipt_conflict`; the receipt is never edited. Acceptance moves no intent:
a tick (any controller, after a restart) re-verifies the stored receipt, including fresh lane reads,
and completes the intent by compare-and-swap (`research_receipt_accepted`, evidence refs and
`research_receipt` digest on the intent); the job is then routed again through the unchanged table,
so an evidence-refused attempt gets exactly one `evidence_repair` successor under the existing
`max_corrections`. An unreadable lane or store, a changed attempt, a withdrawn result or a foreign
policy keeps the family held (skipped by name or `unavailable`). A later failure opens a new research
intent whose attempt set no old receipt covers. Two families under one coarse same-reason
investigation are released only by their own receipts. A Portfolio `researched`/`deferred`
disposition is evidence that the owner looked and is not read for release; no Portfolio row,
dispatch row, Fleet job or earlier intent is written. The receipt is not an operation acceptance, a
repair verdict or a promotion; nothing here mints one for a worker.

Research evidence availability (SPEC "Scoped research resubmission: actual artifact availability"):
sha256 syntax is not availability. The owner of research receipt evidence is the control host's
general artifact store `<HARNESS_RUNTIME_DIR>/artifacts` (`FileArtifacts`, where the research council
and the executor write), reached only through `adapters.continuation.ResearchEvidence` (the
`Continuation(evidence=...)` port) built by `research_evidence()` in BOTH production paths:
`accept_research` (`zeus continuation research-accept`) and `coordinator`/`tick_policy`/
`ContinuationPass` (tick and Fleet runner). No caller-supplied root, candidate path, search, network
fetch or model assertion; the root is never created on a read. Each ref's actual bytes are read with
the `FileArtifacts.text` bound (1 MiB) and their SHA-256 checked, outside any store transaction, after
`check_research_receipt` and before the receipt write, and again on every tick before the stored
receipt completes the intent; the existing intent version and attempt-set checks at commit are
unchanged. Refusals are fixed codes owned by `portfolio_research`: `research_evidence_missing`,
`_unreadable`, `_oversized`, `_corrupt` (digest mismatch), `_invalid` (not UTF-8 text); an absent
port is `research_evidence_unverified` (operator). No path, raw error or content is kept. A cached
acceptance is history, never a substitute for the consumption read; an absent file is never an
empty report. Integrity holds at the observed read time only, not as a lasting availability
guarantee: a later tick rechecks before any new hold-release effect.

Research coverage ownership (SPEC "Research coverage ownership: accepted003 receipt refusal"). Successor
ownership: a successor's Fleet admission is confirmed, its origin's `portfolio_bindings` target
inherited (`application.portfolio.inherit_binding`, `recorded_by: continuation_lineage`, with
`lineage {origin_job, intent_id}`) and the intent moved to `admitted` in ONE control-store transaction
(no nested one); the intent records `ownership {state: inherited|origin_unbound, project_id,
criterion_id}`. An unbound origin stays unbound (no project is guessed from text or names); an
existing binding of another target is `successor_binding_conflict` (owner `portfolio`), nothing is
overwritten and the intent stays `published`; an interruption after the enqueue replays the same job
id and binds once. `zeus continuation ownership-reconcile --intent` (`Continuation.reconcile_ownership`)
binds ONE already admitted successor only from the persisted exact successor intent (route
`evidence_repair`/`correction`, state `admitted|returned|completed`, successor id derived from the
intent, the lane binding's predecessor) and both Fleet rows (the successor row carries the intent's
manifest on its lane; the origin row's manifest digest is the one the intent was authorized on):
`ownership_intent_invalid`, `ownership_lineage_unproven`, `ownership_origin_unbound`,
`successor_binding_conflict`. It asserts present ownership only, never historical capture membership,
and writes no intent, Fleet, dispatch or investigation row. Scope supplement: the research dispatch
snapshot stays immutable and the default `research_scope_unverified` gate is unchanged. The ONLY way to
close a sample gap is the owner's typed, append-only supplement
(`urn:zeus:continuation-research-scope-supplement:1`, `zeus continuation research-supplement --file`,
`Continuation.supplement_research_scope`), one immutable row per research intent in
`continuation_research_supplements` (identical replay `cached`, any other `research_supplement_conflict`).
It names the receipt's intent/policy/family, the COMPLETE attempt set with evidence digests and
inspections, the investigation, the CURRENT dispatch (`dispatch {program, run_id, manifest_sha256,
snapshot_sha256, id, job_ids_sha256}`), `captured` (exactly the members inside the original sample),
`descendants[] {job, parent_job, intent_id}` (exactly the members outside it), the accepted run's
`acceptance {graph_sha256, candidate_revision, decision_id}` and two distinct content-addressed refs:
`report_ref` and `attestation_ref`. The attestation is the owner's explicit semantic judgment that the
report covers those members: not a model verdict and not an algorithmic proof. `check_scope_supplement`
runs every receipt check, then requires the current dispatch id and sample digest, each descendant an
exact persisted successor intent of a captured member or of an already proven descendant (same policy
and digest, family and lane, admitted, successor id derived from the intent, lane binding predecessor),
both jobs terminal known failures (`failed`/`rejected`) and the same Portfolio target, and the accepted
promotion evidence read mechanically from rows (run `promotion.graph_sha256` = promotion receipt,
its decision and implementation task, the task succeeded with that candidate revision, the decision
the succeeded accepting `review_lead` of it). Refusals: `research_supplement_invalid`,
`_capture_mismatch`, `_scope_mismatch`, `_lineage_broken`, `_ownership_mismatch`,
`_acceptance_unproven`, `research_dispatch_mismatch` and every receipt/evidence code; the retained
recovery fence is checked as for a receipt, and the write transaction rechecks intent version, attempt
set and the current dispatch row. A supplement releases nothing. When the sample does not cover a
receipt's members, `check_research_receipt` accepts only a stored supplement naming exactly the
receipt's binding (`research_supplement_mismatch`) that passes the full check again, at acceptance AND
at every consumption, with its report/attestation bytes read again; the receipt row stores
`coverage: original_capture|owner_supplement` and `supplement_sha256`, consumption requires the same
(`research_coverage_changed`), a stored row whose digest no longer matches is
`research_supplement_corrupt`, and `status` shows `receipt.coverage` and a separate `supplement` view.
Evidence refs alone never imply coverage; the original dispatch, snapshot, investigation and failure
verdicts are never rewritten.

An intent id is `origin job + generation/attempt + decisive evidence digest + route`; a successor id is
`cont-` plus 24 hex of it. Every external effect has a durable pre-effect state: `intended` (complete
successor manifest and binding recorded) -> `published` (lane binding written; identical replay cached,
different document `binding_conflict`, an already claimed operation `operation_already_claimed`) ->
`admitted` (the unchanged `Fleet.enqueue`, same id on replay) -> `returned` -> `completed`; for the
conductor `intended -> dispatched` BEFORE the child starts, and a dispatch whose decision row is still
`pending` with attempt 0 is provably not entered. `domain.continuation.RESUME` is the route x state
restart table: every open (route, state) has exactly one action (`publish`, `await_successor`,
`complete`, `dispatch`, `reconcile_launch`, `redispatch`, `observe_delivery`, `observe_research`,
`await_backlog`), so a crash after any commit - including `intended` and `returned` - resumes the
same intent; `returned` completes from the committed outcome it already holds (the successor status
or the conductor decision). Each move is a compare-and-swap on the intent
version (`IntentChanged` for a stale holder), so two controllers, a restart and a duplicate event
converge on one intent, one successor and one dispatch. A successor keeps the origin's goal, base,
allowed paths, acceptance criteria, budget and Claude controls byte for byte; only the id and a fixed
objective preface with identity/digest references differ, and the existing manifest validator
decides it (`successor_manifest_refused`). The rejected operation stays rejected; nothing parked is
revived. One family per tick, least recently served first, at most four per tick; a held family
(`research_required`, `recovery_required`, `paused`, `refused`) never starves another. A lane, Git or
Fleet outage skips that subject for the tick (`unavailable`, exception type only) without spending
one of the four slots; each lane's runtime identity is read once per tick, an unreadable one makes
the whole lane skip after its first visible entry, and any lane stops being read after four
`unavailable` skips, so other lanes still progress within a bounded pass. A queued job whose runtime
cannot be read is skipped visibly instead of failing the tick. A per-job read failure is not a lane
outage, so selection progress is durable: before each lane read the tick records the attempt in the
control store (`continuation_progress`, one row per policy `{policy_id, sequence, attempts{job:
sequence}}`, its own short transaction, the stored sequence + 1), and every pass - any controller,
after a restart - orders the fair pass never-attempted first, then least recently attempted
(`domain.continuation.progress_order`). With a fixed finite set of candidates each one is attempted
within ceil(n / 4) passes of its lane, and a pass still reads at most four failures per lane. The row
records a scheduling attempt only (no intent, verdict or evidence); an entry is dropped once its job
is no longer a candidate and it predates the writer's snapshot, so a concurrent controller's newer
attempt is never reset. `status` and `drain` never write it; a tick with no candidate writes nothing.

Readable correction evidence (SPEC "Readable correction evidence delivery"): the successor manifest
and the lane binding stay identity-only. For an `implement` assignment whose trusted binding
(`Executor._continuation`) has route `correction`, the executor calls
`adapters.correction_feedback.deliver` BEFORE workspace preparation, reservation or provider entry.
It requires the binding predecessor to carry exactly `job_id, task_id, candidate_revision,
decision_id, review_execution_ref, inspection_id` (as `_successor` records them), reads the lane rows
in one short read transaction and proves: the `operations` row names the task and the reviewed lead
decision; the decision is `succeeded`, a `review_lead` or `review_conductor` (the latter bound to
that lead decision) with `accepted: false`; its message names the task, its input and the task
result name the candidate (and the binding workspace head); its `execution_ref` equals the bound
ref. The artifact is read through `FileArtifacts.document` (content address re-verified over every
byte; mechanical parsing only) and its structured `answer` must equal the committed decision result.
Only `accepted`, `reason` and `risks` leave; the provider trace and every other field stay behind.
Strings pass the existing `redact_text`; at most 15000 characters are delivered and more is refused,
never truncated. The block (`urn:zeus:correction-feedback:1`: predecessor identities, `decision_id`,
`phase`, `source_ref`, `original_sha256`, `delivered_sha256`, `redaction`, `truncation`, `findings`)
is placed in the REQUIRED prompt contract, so context packing can never evict it, and the complete
required envelope is measured against the usable budget before compilation. Inline content crosses
the host/container boundary in the request itself; it contains no host path. Refusals are fixed codes
of `CorrectionFeedbackRefused` (`feedback_binding_invalid`, `_operation_mismatch`, `_decision_missing`,
`_decision_unsettled`, `_decision_not_rejection`, `_task_mismatch`, `_candidate_mismatch`,
`_ref_mismatch`, `_artifact_missing`, `_artifact_unreadable`, `_artifact_corrupt`, `_artifact_foreign`,
`_empty`, `_oversize`, `_context_insufficient`) recorded through the existing task failure path, with
no content, path or exception text. Integrity holds at the observed read, not forever; every attempt
re-reads. Legacy implementation without a binding and every other route are unchanged.

Effect ownership across policies sharing one control store: the intent id (and with it the successor
and launch ids) carries NO policy, so overlapping policies derive the same effect and can never
admit or launch it twice. A row belongs to the policy that wrote it. Another policy never replays,
advances or reports it: a job routed, or created as a successor, by another policy's effect-owning
intent is excluded before selection and projected in the tick's `owned_elsewhere {count, jobs[<=16]
{job, policy_id}}`, and a create that meets such a row (a race) is skipped as
`intent_owned_elsewhere` with no effect. The only foreign row that owns nothing is a refusal written
at creation (history `[refused]`, no successor, no launch): it never authorized an effect, so the
next slot of the same observation, `digest(["continuation_intent_slot", id, n])` for n = 1..7 and
again without the policy, is claimable, and the successor id derives from that slot. Every policy
walks the same slots, so a restart, a replay and a second controller converge on the one existing
owner and successor. Old rows are never deleted, rekeyed or edited, and no authorization is adopted
from them.

Sessions and workspaces: before admission the controller binds each queued in-policy job to its own
logical session (`task_id` = the family's root job). `Operation.claim` attaches the lane's binding to
the row identity and the assignment (`details.continuation`), refusing a binding that changed between
its reads. `Executor.execute_one` accepts it only when the identical document is the lane's own
`continuation_bindings` row for the assignment's operation; it then passes `task_session` with
`max_handoffs=1` to `_run`, freezes the adopted turn's exact candidate with `WorkerSessions.submit`,
and records a committed `review_lead` decision on the session after the commit. A correction is
`native_resume_eligible` only when `record_review` moved the family session to `correction_ready` on
that decision; otherwise it is an explicit fresh evidence handoff. `GitWorkspace.continue_workspace`
reuses only the owner-derived origin workspace under the managed root, on its own branch and pinned
base, at exactly the last candidate HEAD and clean; the executor also refuses an origin task that is
queued, retrying, running or blocked. Nothing is reset or cleaned; the frozen review checkout stays
separate. `zeus operate run` and `continuation conduct` build a `WorkerSessions` owner only for an
operation whose binding names a session.

Observability: every committed intent change emits `operations.continuation_transition` or, for
`research_required`, `recovery_required` (outcome `unknown`), `paused` and `refused`,
`operations.continuation_blocked`, with intent, family, route, state, origin/successor job, next owner
and next action only. `zeus continuation status` and the additive monitoring source `continuation`
project policies (id, enabled, digest, pin), intents (route, state, cause, next owner/action, evidence
references, predecessor/successor links, completion evidence), counts and held families; never a
manifest, objective, review text, transcript, path or credential; a store failure makes the envelope
`unavailable`. `FleetRunner(continuation=...)` runs the pass after the backlog tick and before
admission; its failure is its own `unavailable` state and never blocks admission.

Conductor launches (`adapters/continuation_process.py`, SPEC "Two-strike ownership design") are
never waited on, and three owners stay separate. (1) Capacity: ONE Fleet transaction
(`Fleet.reserve_unit`, INV-FLEET-001 `fleet_units`) reserves the launch's execution unit against
the shared `max_parallel` (reserving jobs + held units, the same serialization as `admit_one`, for
the runner, independent controllers and `zeus continuation tick` alike) AND commits the launch
identity `digest(intent, sequence)` with the unit token on the intent (`dispatched`) BEFORE anything
is spawned; a full or paused fleet refuses (`conductor_capacity`/`conductor_paused`, next owner
`fleet`) and the intent stays. No local count authorizes a start. (2) Supervision:
`ConductorProcesses.start` creates `<lane runtime>/continuation/launches/<launch>/spawn`
exclusively (one-shot; a replay, a lost response or a restart never spawns that identity again),
writes `launch.json` {launch, token}, and spawns one hidden guardian (`continuation_process.main`) in
its own POSIX session / Windows group with a breakaway request, outside every controller kill
boundary. The guardian uses NO database: it takes `lock` without waiting, skips an already `claim`ed
launch, flushes write-ahead `debt.json` (a failed write starts nothing), creates `claim=child`
exclusively, runs `zeus continuation conduct` as its own `ProcessTree`, and alone enforces the
monotonic deadline (`decision_seconds + 120`) and stop requests (`stop` file, POSIX SIGTERM, recorded
not raised) through bounded `terminate` attempts. A store that blocks or fails, a Fleet tick or a
controller exit cannot suppress them. (3) Proof and settlement: only when the parent AND the tree
are each confirmed does the guardian atomically write `cleanup.json` bound to launch and token, then
close the handle; `terminate` False/raising, a parent that exited with the tree unknown, or a proof
that cannot be persisted leave no proof, keep the debt (`debt.json: cleanup_unknown`) and record
`unresolved.json`. `observe` answers from these files alone: valid proof -> `exited`/`timeout`
with `cleanup_confirmed`; lock held -> `running` (another controller's guardian:
`conductor_owner_unknown`, only that family waits); lock free and no claim -> `claim=fenced` under
the lock -> `absent` with the fence proof (a delayed guardian executes nothing); claimed without a
proof -> `unknown`, even beside an old `exit.json`. The intent leaves `dispatched` only through
`Fleet.settle_unit`, which validates the exact proof and token and commits the unit release with the
intent move in one transaction; a failed commit keeps both and the next pass settles exactly once
from the local proof, never by a model rerun. Unknown cleanup - including a succeeded decision, a
guardian that ended without proof, and a killed guardian (never reacquired from a pid file, never
signalled) - stays `dispatched` with `hold {conductor_cleanup_unknown, execution_recovery}` and its
unit held; it neither completes nor re-dispatches, and when such debt fills every slot admission
stops. Only `absent`, or a proven-clean exit whose row is still `pending` with attempt 0, lets a NEW
launch identity start, at most `MAX_LAUNCHES` (3), then `conductor_launch_exhausted`; a proven-clean
exit with a `running`/`failed` row, or past its deadline, is `recovery_required`. A failed or lost
start response (`launch_unconfirmed`) is decided by reconciling the same identity. `ContinuationPass`
lives as long as the runner: its live guardians count as heartbeat `active`, held units and
dispatched launches it does not supervise as `unresolved`, `--once` and a graceful stop keep draining
them, `drain()` settles them while admission is closed or the pin changed/unreadable, and the run
summary lists `units_held`. `FleetRunner.stop()` forwards, before any store access and again on each
stopping pass before the drain, to `ContinuationPass.request_stop()`: a DB-free local `stop` file per
guardian this process spawned, each launch asked once. It proves no cleanup (the guardian's proof and
the Fleet settlement keep their authority) and signals no worker job; the run summary reports
`stop_request` (`requested` with the launches asked, or `failed` with each launch and error type,
the guardian deadline still bounding it). `zeus continuation tick` waits for its guardians and drains once. A
launch written before units existed has no token: it is settled without a unit. Windows job-object
and breakaway behaviour is an owner qualification gate; POSIX tests do not prove it.

Every NEW effect (lane binding, Fleet admission, conductor start, including resumed `intended`/
`published` work and a re-dispatch) passes one eligibility guard: the registered policy digest,
`check_scope` against the current runtime, and the `authorization` stored on the intent at creation
(policy/pin digest, repository, lane, goal, allowed paths, criteria, model, image/profile/archive
identity, source job manifest digest and status) must all equal the current values. Drift refuses
the effect by name (`image_changed`, `session_archive_changed`, `policy_changed`, `source_changed`,
...), records `hold {reason_code, next_owner, field}` on the intent once (an
`operations.continuation_blocked` event; the family is held; idle ticks write nothing), and keeps the
state, stored authorization and evidence unchanged; restoring the authorized binding clears it.
Reconciling an already started launch needs no guard and keeps its outcome under the original
binding; the next observation of that job under the changed binding is a named refusal.

Delivery evidence is bound: `LaneEvidence.read(job, target)` selects the ONE `host_delivery_intents`
row of the policy `delivery_target` whose `release_id` and `revision` equal the conductor's release
and the accepted task's candidate, and the `releases` record must name that candidate
(`bind_delivery`). The `delivery` intent carries `delivery_binding {target_id, release_id, revision}`
and re-validates it on every observation. Another target's plan (active or rolled back) is foreign
and neither completes nor pauses the item; a plan of this target for another revision
(`delivery_stale`), two exact plans (`delivery_ambiguous`), a release naming another candidate
(`delivery_release_candidate_mismatch`) or a changed tuple (`delivery_binding_changed`) is a named
wait with no write. Completion and pause record `delivery_plan {plan_id, plan_sha256, stage}`.

Fixture tests prove the composition with labelled worker/lead/conductor executors; the child
ownership is proven with real local sleeping children (tests/test_continuation_process.py), never a
model. They do not prove real PostgreSQL/Redis behaviour, a real two-turn model session, the managed
Fleet, native Windows execution or two useful unattended jobs; those are owner qualification gates.
