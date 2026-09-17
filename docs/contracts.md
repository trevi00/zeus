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
only. Unit fault injection and MemoryStore exercise these boundaries; they are not operational
evidence.

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
a document over the character limit, or a rule that widens anything but Bash is refused whole and
never truncated or narrowed. The document travels as the `--append-system-prompt` value and the
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
a received execution notice, a message or queued work under another correlation, or running
residue in the ledger stops the cycle with a recorded reason. The candidate is chosen outside the
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
total) and `claude` (model, timeout_seconds, max_budget_usd); unknown fields, wrong types,
booleans as integers, nonfinite numbers, traversal, `.git` or absolute paths and empty values are
refused, and the claude controls are validated by the existing provider policy validators. The one
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
zero reviewer calls. Worker retry/failure/exception, ledger exhaustion, a lead rejection (no
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
before the verified report is handed to both leads (`report_not_relayed`). The DBA report names the
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

- INV-ISOLATED-WORKER-001: Worker isolation is a host opt-in (`ZEUS_WORKER_ISOLATION=docker` with
`ZEUS_WORKER_IMAGE=sha256:<64hex>`); absent, host execution is exactly unchanged; unknown or partial
configuration, a host project-evidence profile beside it, an unavailable daemon or image and a
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
