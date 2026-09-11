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
segment only when it is fully acknowledged and no longer being written, so a spool that is
consumed never saturates and an active segment is never truncated. Correlation, causation and
evidence identifiers are opaque handles and are refused, never rewritten, when they are not;
operator labels follow the same rule and operator free text is redacted and bounded before it is
stored or returned. Once the provider is entered, every failure up to the durable checkpoint
(transport, progress, cleanup, settlement, breaker report, result persistence, checkpoint) leaves
redacted termination evidence naming its boundary, records the failure, blocks the task and
notifies the lead through the existing execution notice; a refusal proven to precede entry stays
an ordinary retry, and a runner-observed output failure whose evidence is already persisted is an
observed outcome. Reconciliation commits the operator's decision and audit to the sink before the
local blocking record is finalized, is idempotent for the same decision and refuses a different
one; re-queuing goes through execution recovery, which refuses while any termination record is
pending. Pending alerts are persisted locally, cleared only after the transaction that carried
them committed, and inherited by the next process run. The invocation ledger closes an orphaned
reservation as unsettled_unknown. Health, status, orphan and alert reports are informational
only. Unit fault injection and MemoryStore exercise these boundaries; they are not operational
evidence.

# SDD preparation contracts

- INV-SDD-001: Missing specs, unknown fields, uncovered requirements and reused retired scenario IDs fail validation. Git definitions produce immutable runtime snapshots bound to the current local ticket revision. Superseded iterations cannot append observations or request transitions. Given/When/Then are lists of statements, never one-line strings to be parsed; generated replay drafts embed the spec hash and attribute every assertion at runtime to its scenario, oracle index and requirement IDs, carry spec text only as Python literals without truncation, contain no placeholder or expected-failure skeletons, and are never written over a different existing draft.
- INV-ORACLE-001: Imported observations and structural coverage cannot populate approved expected outcomes, certify real-device execution, authenticate human QA, or authorize a release. Gaps remain visible. Eight-stage reports are preparation only until actual providers are implemented.
- INV-SDD-002: SDD journals retain ordered, hash-linked events; duplicate imports/proposals are idempotent and transitions use compare-and-swap. Notifications are local records, not external messages. Model transfer candidates never change routing authority.
- INV-GATE-001: Every gate verdict names one fixed statement, its stage, run, cycle and the definition hash it judged, with the runner receipt and process exit status or the reviewer's actor and authority level; a non-zero exit is never PASS and an unauthenticated reviewer claim never settles a statement. A runner receipt counts only when the receipt document itself names the same run, cycle, statement, definition, artifact, environment and exit status; human statements (`human_*`) accept reviewer decisions only; `authenticated_provider` authority is granted only by the configured provider's own verification of that exact statement and actor, and an unverified claim is kept as a pending unauthenticated claim. A retraction binds to the run, cycle, stage and definition of the verdict it names; one issued for another run or cycle is foreign and never removes a verdict here. All consumers use one fold: the planned statements are the denominator (`not_run` is a state, never an omission), verdicts for another run, cycle or definition are foreign, the latest live verdict wins, ERROR withdraws validity rather than leaving an earlier PASS, PARTIAL stays pending, and a retraction removes exactly one named verdict so that the fold of a compacted view equals the fold of the full view.
