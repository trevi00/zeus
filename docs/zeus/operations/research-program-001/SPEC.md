# Research program001 — finite discovery-to-improvement operation

Owner Codex,2026-09-18. Base29f95b955cf0f4a015133ba61c0d1d6b61cc4016. One bounded delivery.

## Outcome, authority, completion

User wants current local/sterk residuals AND GitHub Trending/GeekNews to feed ongoing improvement,
not another isolated profile patch. Connect existing collectors, durable store and real council/DGE
through a reusable finite program. Operator authorizes goal/topic/write scopes and budgets once;
the program discovers, deduplicates, selects and runs within that authority, without human relay.
Claude implements; Codex owns this design, independent review, final release and issue closure.
No automatic merge/deploy, host/global edits, provider retries, budget grants or arbitrary new goals.

Batch authority: machine167 ->176 maximum: implementation+independent review2, then one real
autonomous:2 council cycle at most7. No extra calls on failure. Implementation USD12 declared,
1800seconds; canary worker USD4 declared,1200seconds; provider estimates are not billing guarantees.
Canary: two real collection ticks, max1 selected improvement, second tick must observe previous
candidate/result and avoid repeat or exceed cap. This is two collection cycles, NOT two completed
model improvements. Show local + both live sources and actual scoped research/report improvement.
External candidate may remain a lead or be deferred; no mandatory adoption of today's headlines.
Do not claim readiness until candidate code is independently accepted, focused Windows/PG tests,
CI and the two-tick actual run pass. Failure ends with evidence and the same frame revised.

## Facts, source-backed decisions and limits

Inspected current source2026-09-18:
- adapters/research.ResearchSources collects GitHub Trending and GeekNews Atom/RSS (15entries,
  2MB/30s bound); github_detail fixes commit and README evidence. Not full repository analysis.
- application/scheduling schedules6h research and separate audit work. Workflow discovers topics
  but intentionally defers source audit. Never mark those audits approved or bypass require_dispatch.
- autonomous_cli.run + CouncilRun already perform researcher, DBA, research lead, improvement lead,
  conductor, Claude implementation and independent review, with evidence-bound PG promotion.
- Fleet accepts operation manifests only; do not weaken it or duplicate its dispatcher.
- DGE verifies source citations against regular Git blobs at base, so mutable fetched text cannot
  be claimed as a verified Git source. Need a capture commit, not self-reported external citation.
- Existing FileArtifacts, Store transactions, CallBudget, no_console_kwargs/run_process and
  monitoring.collect are the reused ownership/logging surfaces.

Primary external surfaces checked2026-09-18: https://github.com/trending rendered by web reader;
https://news.hada.io/rss/news failed in that reader. Neither establishes local collector success;
owner live run must record actual fetch success/failure. No remote content is executable authority.
Local source is read only; no upstream hooks/install/tests. No popularity-as-quality claim.

## Complete path and interfaces

Add `zeus research-program register --file CONFIG`, `run ID --ticks N`, `status ID`, `pause ID`,
`resume ID`. Finite synchronous runner can be invoked by an existing hidden scheduled launcher;
no service installation by worker. `run --ticks` obeys BOTH requested cap and immutable program
max_cycles and interval; status is read only. Register never runs models. Pause blocks new ticks,
active council finishes; no takeover or retry of uncertain active work.

Use versioned strict JSON config (urn:zeus:research-program:1), unknown/missing fields refused:
id, base_revision, deadline(aware ISO), interval_seconds(positive), max_cycles(1..100),
max_adoptions(0..max_cycles), budget{per_host,total}, topics, local_candidates, template.
topics: nonempty list of {id, keywords(nonempty lowercased strings)} defining owner-authorized
relevance. local_candidates: bounded list(max100) of {id, topic, path, sha256, rationale}; path is
regular tracked source at base and hash verified. These may reference existing local-analysis or
sterk evidence; no inference that all source analysis/adoption is complete. template is a valid
autonomous:2 manifest with operator goal/plan/research/current_state and SAME base/budget. Program
never broadens its allowed_paths, criteria or goal. Validate all with existing domain validators.
One local candidate per source identity; URL normalized(no fragment) for external dedup. Same URL
updated content remains the same candidate in this program: explicit conservative policy, revised
version requires a newly authorized program. Source content digests are separately preserved.

Persistent buckets `research_programs`, `research_program_candidates`, `research_program_cycles`.
Register immutable config digest incl resolved repository identity; repeated identical registration
is cached; changed config/id/repository refused. No count reset on restart. State active/paused/
completed/blocked; initially paused. Each tick reserves the next cycle number/owner in one PG
transaction before fetching; a concurrent run refuses busy. Crash leaves owned/busy, never assumed
empty. DB failure means no fetch/model start. No transaction stays open across I/O/provider calls.
Persist cycle state before council start; candidate claim and max_adoptions reservation in same
transaction. Count any dispatched attempt (not just accepted); failure/unknown blocks program and
does not unclaim candidate. Same id/terminal replay does not call providers. No blind auto repair.

Each tick: enforce pause/deadline/max_cycles; collect BOTH live feeds via ResearchSources plus
verified local rows; record source ok/unavailable independently(type/code only, no exception text).
One unavailable feed need not suppress verified local work but must show degraded, never 'empty'.
Discovery itself is read-only and uses no model calls. Dedup across ticks in PG. Map relevance by
topic keyword match in bounded title/summary; record deterministic reason, never call this semantic
quality evaluation. Stable order: authorized local first, then topic/id/url lexical. Nonmatches
remain ignored with reason; matching candidates are eligible leads only. No new topic invention.
Select at most1 eligible unclaimed candidate if adoption cap and remaining machine headroom>=7;
otherwise record no-selection reason. Cap exhaustion still permits remaining collection ticks.
If due time not reached return not_due without increment or sleep; host scheduler calls later.

## Evidence capture and council reuse

For a selected candidate create canonical bounded snapshot JSON with source URL/ref/fetched_at,
candidate identity/reason and source-status map; read local bytes at config.base (never live dirty
files). For selected GitHub candidate optionally reuse github_detail once; absence/failure recorded
as unknown, not successful review. GeekNews feed description is discovery only, never primary-source
verification; missing primary proof must be reported/deferred by the council, not fabricated.

Pin snapshot at `docs/zeus/research-captures/<program>/<cycle>.json` in a NEW detached capture commit
based on immutable config.base in the SAME object database; never commit/reset checkout working
tree or current branch. Recommended temporary Git index + read-tree/hash-object/update-index/
write-tree/commit-tree with explicit synthetic commit author; fixed argv/no shell, run_process
timeouts, cleanup only owned index. Ref under refs/zeus/research/<program>/<cycle> retains commit.
Reject existing target path/ref conflicts; avoid symlink/path injection; never follow source data
as commands. Writes only snapshot blob and this ref; do not stage user files or move user HEAD.
Capture records are unverified source data, not approved knowledge. Keep large raw feed bodies in
FileArtifacts runtime directory and their SHA refs; small bounded snapshot in Git. State failure
after commit records recovery reference; don't delete evidence or silently redo active cycle.

Derive council manifest only: new deterministic run id, base=capture commit, deadline=min(program
deadline,template.deadline), original goal/plan/budget unchanged, add snapshot path to research
search_scope and a bounded discovery question naming it as untrusted lead and reminding primary
evidence requirements. Goal file hash remains valid at capture commit; no generated role answers.
Call existing autonomous_cli.run(service,args) using persisted manifest path and existing configured
repository/runtime/Redis/DB. One existing CouncilRun owns actual calls, cancellation, output and
promotion. Read authoritative autonomous_runs row and require matching manifest/run status; never
accept stdout/model 'success' as authority. Return accepted/rejected/failed/unknown exactly, record
candidate + cycle result references. No fake/provider substitute in owner live acceptance.

## Logs and reports

PG cycle receipt: counts discovered/new/duplicate/ignored/selected, source statuses, selection reason,
budget snapshot, capture revision, council id/status, timestamps, remaining cycles/adoptions and
stop reason. Progress persists through failure; unknown distinct from0/missing. General (tick),
development (selection/evidence/check), operations (failure/budget/blocked) categories in explicit
local safe JSONL event log if existing observer cannot represent these without schema changes;
no raw exception, source body, credentials or DSNs in logs. Do not change observation schema here.
Reuse monitoring envelope: additive `research_programs` read-only bounded projection(max20,
truncated explicit) in monitoring.collect, exposing program/cycle counts/outcomes/stop reasons;
no frontend redesign. `status` emits same safe facts with schema/version. Write bounded report.md
under runtime/research-program/<id>/ with real counts and a simple source→selection→DGE→result
diagram; clearly distinguish configured stages from observed successes. No model-generated facts.

## Implementation boundary / checks

Allowed: new domain/research_program.py, application/research_program.py,
adapters/research_program.py, adapters/research_program_cli.py; cli.py minimal wiring;
adapters/monitoring.py additive source only; tests/test_research_program*.py plus directly affected
monitor/CLI tests; docs/contracts.md new INV-RESEARCH-PROGRAM-001;
docs/zeus/operations/research-program-001/{IMPLEMENTATION.md,RUNBOOK.md,example.json}.
Do not modify fleet, autonomous/council engine, provider policy, loader/profile or permissions.
No global process, env, credential or source-ledger writes. No new dependencies. Code functions
live in reusable package, not an untracked one-off automation. Outer domain/application remain
stdlib + ports; adapters own filesystem/network/process operations.

Acceptance matrix:
| Boundary | Required evidence |
| Normal | Two ticks: same candidate dedup; local + both external inputs; <=1dispatch/tick |
| Relevance/authority | unrelated ignored, deterministic rationale; template scope/goal/budget immutable |
| Missing/error | source unavailable distinct from empty; evidence/DB/capture/council failure persisted |
| Budgets/time | headroom7 preflight + existing reservations; absolute deadline; caps persist; no retry |
| Restart/concurrency | identical replay no duplicate; separate-process/concurrent PG claim exactly1; active unknown blocks |
| Git/cleanup | native temp Git dirty checkout unchanged; only snapshot/ref; bounded owned temp cleanup |
| Truth | rejected remains rejected; mocked unit outcomes labeled; actual canary no mocks; no audit promotion bypass |
| Platforms | focused Windows plus CI Linux/Windows; fake clock/faults in tests labeled |
| Reporting | counts from PG, source errors visible, pause/status read without models; three categories |

Worker runs `python -m pytest tests/test_research_program.py tests/test_research_program_cli.py -q
-p no:cacheprovider` (create these two test files; helpers may be test_research_program*.py),
`python -m ruff check .`. Tests use real temporary Git; PG integration gated consistently with
repo existing convention. Stub council/network only for deterministic failures, labeled; real
owner canary is required separately. No full suite by worker; owner/CI owns full/platform checks.
One consolidated review across this matrix, critical reachable defects only. Minor optional
refactoring is follow-up, not a new blocker. Reframe here if an assumption fails.

## Consolidated review001 and bounded correction (2026-09-19)

Candidate75bc8bb2 was rejected by actual independent Codex. Owner native Windows + isolated PG
checks49passed and lint passed, but the three whole-path boundaries below remain unaccepted.
This WIP is integrated only onto the task branch for correction; main/deployed code is unchanged.
Raw evidence D:/workspaces/zeus/artifacts/research-program-001/{review.json,owner-check.json,
owner-boundaries.log,capture-check.json,test_owner_boundaries.py,capture-check.py}.

R1 repository authority: register in A, run same id in real Git cloneB using same store/base.
Owner reproduction with labelled synthetic feeds/budget/council reached council and created the
capture ref in B. Expected: repository_identity(current root) must equal registered identity
before cycle reservation or any fetch, log/filesystem capture or model effects. Enforce in the
actual production runner, not just register; test wrong-root refusal with0newcycles,0fetches,
0capture/ref and0council calls; matching root continues normally. Update fake tests to name real
identities where necessary, do not weaken the production check to accept fixtures.

R2 pre-dispatch ownership: after successful capture, injected PermissionError writing manifest
artifact escaped, leaving state active/captured and indefinite busy with no failure reason. Owner
reproduced on actual temporary Git with a specifically injected artifact failure; models were
stand-ins. Wrap the whole known pre-provider preparation phase (derive, artifact write, manifest
directory/write and start record) under explicit stage tracking. If state store remains available,
fail_cycle must record blocked/count/claim and retained capture reference; zero council calls.
Include failed on-disk manifest writes, not only an artifact mock. If recording itself is uncertain
retain ownership and report inability; never claim a durable failure receipt that was not committed.
Do not turn post-provider unknown outcomes into known failures or clear ownership to retry.

R3 exact bytes: native Windows Git capture of UTF8 body18bytes yielded19byte Git blob (LF→CRLF),
while receipt SHA named original18bytes. Existing text-mode test reads normalized away the defect.
Capture must write exact UTF8 bytes (e.g. owned temp binary file + git hash-object -w -- path) and
verify binary blob bytes/hash before publishing ref/claiming evidence. Do not globally modify
commands.run_process semantics. Tests read raw git bytes/GitSource.blob, with LF and Korean text;
owner repeats on Windows. Existing dirty checkout/index/HEAD and cleanup guarantees stay fixed.

These share an end-to-end binding requirement: authorized repository -> exact evidence bytes ->
durable pre-dispatch state. Fix all three as one batch, preserve already accepted functionality.
No fourth speculative review round; expand only on changed boundaries or concrete failed checks.
Worker targeted tests and lint unchanged; include regression tests in existing two test modules.
Write CORRECTION.md with each finding, actual checks, labelled injections and unrun Windows/PG work.
Allowed files remain the original boundary plus this CORRECTION.md; do not edit owner frame.

Budget reallocation inside unchanged176 ceiling: after build/review169, use2 of remaining7 for
explicit corrective implementation/review (not a provider retry), stopping at171. No grant or
additional model calls are automatic. Real council headroom7 then exceeds remaining5; its live
acceptance stays pending a separately explicit grant. Do not call this unattended-ready meanwhile.

## Owner disposition after review002 (2026-09-19)

Candidate b047dc87205c99fd6e7e0593b1946df4069e527c corrects repository binding,
manifest preparation containment and exact Git bytes. Native Windows/isolated PostgreSQL
focused checks: 54 passed; lint passed. Binary capture: original18bytes == Git18bytes,
SHA256 8301c655af3516611f45755f017b4c045044ca1ef38f9214d734a3da305ababf.

Independent review002 remains REJECTED: council_started diagnostic append can raise after
the council-start record and before dispatch. Owner reproduced with real temporary Git,
injected OSError, and explicitly synthetic feeds/store/budget/council. No council call occurs;
ownership remains active and the next tick is busy. This proves containment in that injected
case, not correct failure reporting or recovery. No machine verdict was changed.

Owner scope decision under the user's critical-only policy: this diagnostic failure is a
recorded limitation for a finite healthy-log canary, not permission to declare general
unattended readiness. The prior full failure-reporting condition remains unmet. Keep issue152
open, keep deployment unchanged, and prepare a draft PR. Do not retry or clear such ownership
automatically. If observed in the canary, stop and record external owner evidence. A coherent
diagnostic-failure/recovery design is required before general unattended acceptance; do not
patch each emit call in successive reviews.

Remaining acceptance: CI, then two real collection ticks with at most one seven-role council
and a reviewed recommendation artifact (not runtime release). Current calls171/ceiling176
leave5, below required7 headroom. No partial council or automatic budget increase. A concrete
additional2-call grant would set ceiling178 and reserve exactly7 remaining calls, then stop.

Evidence manifest and limitations: OWNER-REVIEW.md. No additional exploratory review pass.

## Authorized live attempt and stop (2026-09-19)

User explicitly granted ceiling176 ->178 for this two-tick/one-council verification, then stop;
no automatic merge/deploy. Grant00000005 applied while fleet paused. CI35363033521 completed
successfully on954399c (Windows/Linux3.12/3.14, integration, gate; docs job intentionally skipped).

One actual attempt ran against real PG/Redis with both live feeds. Cycle1 collected31 candidates,
selected the pinned local notes, and captured commit c63c303f3d3069f882325851dc9a5c15f946b0a8.
The actual researcher succeeded as an execution but its packet was rejected: answered questionq3
cites claimc11 of kindunknown. Pure validator replay against the unchanged execution artifact
reproduces PacketError. No fabricated role output, output editing or extra model call was used.

Observed outcome: programblocked, autonomous runfailed, reasonpacket_invalid:PacketError;
calls171 ->172/178; no DBA/debate/Claude/reviewer call; tick2 not executed. Fleet remains paused,
active lanes0; no worker container remains. The requested stop is honored. This is an unsuccessful
live acceptance attempt, not completion of two ticks or general unattended readiness.

Reframe for a later bounded batch (not executed/authorized by this stop-only verification):
observation -> researcher JSON passed execution schema but failed the packet's relational rule;
affected assumption -> successful structured role output is not necessarily a valid council packet;
discriminating check -> replay of unchanged real artifact confirms q3/c11 relationship failure;
design boundary -> align producer guidance/schema examples with existing semantic packet rules,
including answered-with-unknown and nonblocking unknown questions. Preserve validator rejection,
original evidence and no silent repair. Acceptance must include valid/invalid relationship controls
and a fresh complete live path. Diagnose prompt/schema ownership before a consolidated Claude
handoff; do not turn this into successive per-answer patches or another automatic call grant.

RESULT.md records actual stages, evidence and the separate pre-existing diagnostic-log residual.

## Packet producer alignment batch (2026-09-19, continuation authorized)

Outcome: align researcher handoff with the existing question/claim contract without rewriting
answers, relaxing evidence rules, adding provider retries or claiming guaranteed valid generation.
Scope: adapters/autonomous_roles.py, focused role contract tests, contracts documentation and
PACKET-ALIGNMENT.md. Existing program state, budget, source audit, diagnostic-log residual and
deployment are excluded. Codex designs/reviews; Claude implements. Same issue152 and PR153.

SSOT inspected at2d899bb: domain/dge.py::_questions rejects answered questions citing unknown
claims and blocking unknown questions; domain/autonomous.py::packet_from_research constructs the
packet; adapters/autonomous_roles.py::QUESTION admits both and OBJECTIVES[researcher] omits the
answered-to-nonunknown reference rule. Real failed artifact is preserved in RESULT/EVIDENCE.
This is a producer guidance/consumer relation mismatch. Schema shape success cannot establish
cross-reference semantics. No external API or provider-subset change is needed beyond nested
anyOf/enum/minItems already used by CLAIM and verified by existing output preflight tests.

Design: encode local question constraints as provider-compatible typed alternatives: answered
requires nonempty claim_ids and permits either blocking value; unknown requires blockingfalse
and permits empty or nonempty references. Keep exact field sets and shared enum constants.
Cross-array claim-kind lookup remains the existing domain validator's authority. Researcher
guidance must explicitly self-check references: answered cites only fact/inference, never unknown;
unknown evidence stays unknown, never relabelled for passage. Explain the meta-question case:
"what remains unknown" can be answered by sourced facts about documented limitations while the
underlying uncertainty remains a separate nonblocking unknown question/claim; alternatively mark
the question unknown. Examples are synthetic, not repairs to the saved model answer. Blocking
unresolved design choices must be reported honestly, not made nonblocking to bypass refusal.

Acceptance matrix for this one batch:
- normal: fact/inference answered references pass schema and unchanged packet validator;
- failure: answered+unknown still fails the domain validator; no coercion or retry;
- local schema: answered empty refs and blocking unknown refused, nonblocking unknown accepted;
- relational limits: unknown/missing claim ids and mixed known+unknown answered refs remain
  consumer-refused; explicitly distinguish schema capability from consumer proof;
- concrete recurrence: labelled fixture reproducing q3/c11 semantics rejected, paired honest
  nonblocking-unknown and sourced-limitation controls pass; original live artifact unchanged;
- provider: existing output-schema preflight accepts all roles, other role contracts unchanged;
- restart/concurrency/cleanup: no new ownership/resources; existing behavior unchanged, no new
  platform-specific primitives. Run focused role/council/autonomous tests and lint. Owner full
  suite/CI remains separate. Tests demonstrate contract behavior, not model adherence probability.

Completion: one Claude implementation and one independent review inside unchanged ceiling178
(currently172, expected174 after pair), owner checks, publish truthful result. No live council
retry in this batch: remaining4 then cannot cover7 starts, and no grant is implicit. Record this
as producer alignment only, not live path completion. Do not edit this owner frame or old receipts.

Batch outcome: actual Claude candidatefbde62db2f37ab43eacb9054a97c4a67a91652b9 was accepted by
independent Codex decision950776f2-4ae0-43a2-b276-c1ef1e9fe10b. Owner Windows + isolated PG
checks103passed, lintpassed. Calls172->174/178; fleetpaused after terminal acceptance. Only this
packet-alignment batch is accepted: the earlier diagnostic-log residual and failed live acceptance
remain unchanged. The unchanged bad relationship remains consumer-refused; model adherence to new
guidance has not been measured. A fresh seven-role run would need3 additional headroom (181 ceiling),
not implicitly granted. No merge/deploy performed.

## Second live authorization and terminal result (2026-09-19)

User explicitly granted178->181 after CI success for one fresh run, then stop. CI35372344181
passed onf1edf72, grant applied, research-live-002 registered with immutable new identity.
Owner scheduling clarification: last_tick_at is completion time, so two collection ticks require
two single-tick invocations separated by interval1second. This is finite external scheduling,
not a code change or provider retry; second invocation only after accepted first cycle.

Observed: researcher packet passed, DBA/research lead/improvement lead/conductor succeeded,
Claude succeeded and submitted candidate d491e1de50a412fc1d2da1dac55fc99ab0d97f5e. Host evidence
inspection refused both test claims with isolated_replay_unavailable:FileNotFoundError before
container creation (no prepared transition). Reviewer and tick2 did not run. Calls174->180/181,
fleetpaused, active lanes0, no worker/verifier containers; failed inspection preserved.

Affected assumption: worker execution success does not establish that the host's fresh replay
snapshot can be prepared at this runtime location. Root filesystem cause remains unknown; missing
source, destination/path handling and concurrent deletion are alternatives, not findings. Next
bounded diagnostic is snapshot-only reproduction against retained candidate with exact failure
stage/path evidence and no model call. Do not patch or retry in this stop-authorized run. Preserve
accepted packet alignment and the now-observed research/council progress; do not reopen those.
Overall acceptance and diagnostic-log residual remain incomplete. See RESULT-002/EVIDENCE-002.

## Replay preparation diagnosis (continuation, 2026-09-19)

Authorized outcome: identify the host preparation failure without model calls or rewriting the
failed inspection. Inputs are the retained candidate and two original refused lifecycle records.
Path: scan_tree(source) -> create snapshot parents -> copy regular files -> prepared -> Docker;
both original failures precede prepared, so Docker/model execution is excluded from this check.

Competing explanations: missing/changed source, destination path handling, concurrent deletion.
One discriminating batch: scan and hash retained source; reproduce the exact preparation loop
in exclusively created D scratch destinations with original snapshot-root length and a short
root; capture exact failure operation, relative path, OS error and path lengths; verify source
hashes before/after and destination bytes on successful copies. No fault injection. Do not change
Windows settings, rename original workspace or execute candidate commands. Long-path behavior is
a hypothesis until the comparison measures it. Missing sources or failed short control invalidate
that explanation and are reported, not recursively patched.

Completion: evidence-backed disposition, same-frame implementation handoff if a defect is found,
and issue/PR record. Normal/failure/platform paths are the two actual Windows copies; restart and
model behavior are irrelevant to this filesystem-only diagnostic. Cleanup only newly owned scratch
after path containment checks; preserve originals and raw diagnostic JSON. Budget stays180/181;
no worker/reviewer pair fits the remaining1 call, so no implementation call is part of this batch.

Diagnosis complete: scan5,111files succeeded; original-length snapshot root128 reproduced copyfile
FileNotFoundError at a262-character destination after2,761 verified files. The source exists and
matches its hash. Short-root50 copied/verified all5,111; source hashes unchanged; owned scratch
removed. No injection, model call, Docker execution or original evidence mutation. Microsoft
MAX_PATH documentation supports the mechanism (see SNAPSHOT-DIAGNOSIS.md).

Revised design choice: fix owner execution layout first, not runtime code. A fresh runtime root
D:/workspaces/zeus/artifacts/rp003 projects max235-character replay destinations for the current
manifest (max relative133); recheck against the next pinned revision before any future run.
Do not move active/original workspaces or change global settings. No Claude implementation call
is needed for this owner configuration choice. Do not claim container replay, independent review
or live acceptance passed: those remain pending under a separately sufficient finite budget.

## Short-root recovery verification (2026-09-19, authorized continuation)

Resolve the measured replay preparation blocker by applying fresh runtime root
D:/workspaces/zeus/artifacts/rp003. Run the retained candidate's exact two authorized test claims
through the existing DockerEvidenceInspector with its pinned image, no network/credentials and
unchanged replay policy. This is a new owner verification receipt, not mutation of the old
inspection, task, program or acceptance. No model calls, merge, deployment or automatic council
resume. Preflight current file/path bounds; verify candidate HEAD/tree/cleanliness before/after;
accept only actual successful replay, archived outputs and confirmed owned-container cleanup.
On failure preserve evidence and stop. Existing short-copy diagnostic remains accepted.

Recovery verification complete: same candidate d491e1de50a412fc1d2da1dac55fc99ab0d97f5e, pinned
image, production DockerEvidenceInspector and unchanged policy; pytest twice21passed/1skipped,
lint twicepassed; all four exits0, cleanupremovedtrue, no unresolved runs. Candidate hash/HEAD
and clean state unchanged; calls180before/after. Short runtime root applied for this verification
and prescribed in RUNBOOK for future owner launchers; production code and global settings unchanged.
Original failed DB inspection remains intact. This resolves the measured snapshot/replay blocker,
not the missing independent model review, full new live cycle or separate diagnostic-log residual.

## Consolidated remaining acceptance (2026-09-19)

Owner Codex independently reviewed retained candidate d491e1de50a412fc1d2da1dac55fc99ab0d97f5e:
diff is exactly the allowed100-line recommendation document; inspected read_document and its
target tests substantiate the scoped encoding-test proposal. Earlier short-root container replay
already checks its exact tests. The recommendation is acceptable as an owner-reviewed proposal,
not a deployed implementation. Its heading says reviewed but explicitly labels worker draft;
runtime/council facts remain externally evidenced, not established by that heading. No blocker
for the fixed recommendation criterion; no new encoding task is automatically created.

This session's owner review is NOT the missing automated review_lead execution. Do not insert a
synthetic decision into PG or reopen the terminal failed program. Full-path acceptance still needs
one new program: two scheduled collection ticks, at most one seven-role council with real independent
review, fixed goal and120-line recommendation limit, then stop. Use fresh short runtime rp004 and
check projected snapshot paths before any provider start. Preserve existing role/byte/PG evidence;
do not add another exploratory review. Diagnostic-log recovery remains the documented nonblocking
limitation for this finite healthy-log canary, not silently considered fixed.

Current180/181 permits1 call;7 starts require ceiling187 (additional6), not yet granted. Prepare
the exact config and CI gate before requesting that explicit grant. No merge/deploy or unbounded
retry. If granted and CI passes, one attempt only; failure stops. Completion requires real accepted
run plus second collection with0extra model starts and max_cycles termination. A manual review or
standalone collection must not be substituted for that whole-path result.


## Approved ceiling187 and third live attempt (2026-09-19)

User explicitly granted187 (+6 from181), one fresh attempt after CI, at most2collections/1council,
stop on success or failure, no merge/deploy. Pinned CI35379964168 on1a0e9bf passed before the grant.
The prepared short-root runtime rp004 was used; no production code or global settings changed.

Actual run003 used180->185/187. Collection and four roles succeeded; conductor crossed its local
execution deadline, task became blocked/reconciliation_required and council failed/role_blocked.
Worker, independent reviewer and tick2 were not started. Fleet paused, active lanes0, no leftover
worker/verifier containers. Exact-token scan0, unreadable0. The2unused slots remain unused.

Acceptance matrix disposition: collection/research/DBA/leads observed; conductor timeout safely
stopped this program; complete council/replay/reviewer/tick2 not exercised in this attempt. Prior
short-root replay remains accepted separately. No current concurrency/restart/platform expansion
was needed for this single authorized Windows-host run. General log-failure recovery remains open.

Reframe only the unmet conductor completion boundary: observed deadline expiration -> previous
assumption that the existing role allocation suffices for this payload did not hold in this run.
Input/output burden versus variable provider latency remain competing explanations. Any future
batch first inspects retained input/execution timing, then defines one role-specific bounded design;
no claim that larger limits alone fix it. Current authorized batch is finished, stopped as promised.
No retry, reconciliation, budget extension, implementation, merge or deployment follows implicitly.
See RESULT-003.md and EVIDENCE-003.md. Full-path acceptance remains incomplete.


## Conductor delivery batch (2026-09-19, user continuation)

Outcome: remove observed delivery friction before another live attempt. Keep the original fixed
program acceptance. User said proceed after run003 stopped; this batch uses at most the remaining
2 starts under187 for one Claude implementation and one independent Codex review, then pauses.
No new7-stage run, budget increase, repair/reconciliation, merge or deployment is included.

Facts: run003 conductor task details are32119 UTF8 bytes. compile_context has22000 bytes usable
(28000 minus6000 reserve); its estimated_tokens field is a byte estimate, not model tokens.
The stored conductor context has4097 estimated bytes, zero inline evidence and the whole task
listed omitted:budget. It retains a hash-bound reader handle. Actual event history records reading
an artifact index and20516 input tokens in the last retained usage event; no completed verdict.
The local policy is300 seconds. Both app-server READ_ONLY_INSTRUCTIONS and isolated_review_context
incorrectly frame this pre-implementation dge_role as candidate review; the latter asserts worker
and verifier ran when they have not. These delivery facts are demonstrated, not a proven sole
cause of the timeout. Details size without prior_outputs and ssot is17819 bytes. Removing ssot
from inline delivery must retain an exact pointer; it is not wholly duplicate or dispensable.

Sources: local executor._run, autonomous_roles.execute_role, application/council.py, domain/model.py
compile_context, app_server.py and isolated_worker.py at ee3c378. Official App Server documentation
https://developers.openai.com/ko-KR/docs/app-server opened2026-09-19: turn/completed carries terminal
status. It neither specifies Zeus's300s deadline nor establishes why this call exceeded it.
Raw measured facts: D:/workspaces/zeus/artifacts/research-program-001/conductor-delivery/diagnosis.json.

Complete affected path: immutable role details -> executor raw artifact/binding -> stage-aware
context delivery -> existing context compiler -> App Server read-only assignment -> unchanged
schema/consumer/digest checks -> role result or existing blocked termination. Original raw details,
packet/report/snapshot digests, stage binding and DB task are authoritative. Delivery projection is
only a view and must not be persisted as an alternative authoritative packet or mutate source.

One implementation batch owned by Claude:
1. For trusted action dge_role, construct truthful pre-implementation read-only context. Never
assert a worker, verifier, candidate diff or execution evidence exists without that input. Keep
no host candidate-code execution, no checkout writes and independent role boundaries. Replace
App Server's unconditional candidate-review wording with phase-neutral read-only instructions;
actual post-implementation review_context remains specific and unchanged.
2. For council debate roles (research_lead, improvement_lead, conductor), deliver a deterministic
lossless projection inline as required context: role/run/base/round, complete packet, packet digest,
DBA report, snapshot/report digests, relay, exact acceptance criteria/blocker rule, and available
research/improvement proposals once. Keep ssot and prior_outputs accessible by exact RFC6901
pointers on the original hash-bound artifact; state explicitly these are not inline and provide
precise reading instructions. No LLM summary, text truncation, dropped findings or rewritten IDs.
Do not change task details at creation or downstream binding/validation. Avoid duplicating the full
raw task as optional inline evidence when this projection is supplied. Original raw artifact remains.
3. Required projection overflow must fail BEFORE provider entry under existing compiler rules,
with no model call and no silently omitted semantic content. No larger global context/time budget.
Give conductor concise phase-specific guidance to decide from the supplied verified meeting inputs,
account for all findings, keep unknowns, and avoid redoing prior research absent a material gap.
4. Regression tests cover actual compiler/executor delivery, not just helper dict shapes; a synthetic
size-matched conductor case must retain all required fields inline <=22000 bytes while preserving
exact original artifact and pointer access. Label synthetic/injected tests. Include large critical
finding, Unicode, alias/source immutability, missing role data refusal, required-overflow before
provider, and a real candidate-review control retaining its isolation instructions. Keep snapshot
freshness, unknown verdicts, strict consumers, retries and timeouts unchanged.

Acceptance matrix: normal three debate inputs and original pointer lookup; failure/missing input
refused before provider; oversized mandatory content refused before provider; timeout/unknown keeps
existing fail-closed path; concurrency/restart unchanged immutable task/binding ownership; Windows
and POSIX use existing argv-list reader paths (no shell interpolation); cleanup read-only workspaces
remain untouched. No live timing improvement claim follows from fixtures. Existing tests plus focused
new tests, ruff, owner acceptance and CI decide code acceptance, separately from future live completion.

Completion: one reviewed candidate or concrete failed result preserved, <=2starts, paused. No
recursive new scope. Snapshot age600s is an independent existing guard; do not weaken or refresh it
as part of this delivery fix. The old blocked task remains pending reconciliation.


### Delivery batch review and revised denominator (2026-09-19)

Actual Claude candidate643bf6a and independent Codex decisionc75cd1a0 both completed, consuming
185->187/187; decision rejected. Owner92 focused tests and lint passed, original candidate clean.
Do not integrate candidate: retained actual conductor details through candidate Executor._run with
injected store/Git/no-model runtime produce23377 required bytes against22000. Two prior lead inputs
fit. Independent review found the measured-size fixture insufficient; owner verified actual refusal.

Observation -> assumption:17819-byte projection alone fit, but complete required context did not.
Discriminating check now fixed: whole serialized prompt, representative isolation/reader/path metadata,
at least17819-byte projection plus exact retained-input owner replay. Reduce duplicated advisory
instructions and non-authoritative repeated isolation metadata; preserve all meeting content, source
handles, reader argv rules and existing guards. No wider context/deadline allowance or semantic trim.
Existing matrix remains; this revises its measurement denominator rather than adding a new scope.

One remaining correction, not multiple new tickets. Current batch stops paused at187/187. A further
Claude+Codex pair needs explicit+2 authorization; no fresh live council is included. See
CONDUCTOR-REVIEW-001.md for one consolidated handoff and hashes. Runtime candidate not integrated.


### Authorized correction189 outcome and delivery-shape revision (2026-09-19)

User approved189 (+2) for one Claude correction and one independent Codex review, then stop.
Grant applied; candidate f571809 submitted on741fd68. Required evidence gate found1test mismatch
and stopped before review; no gate bypass or extra correction. Calls188/189, paused, active lanes0.
Owner actual preserved conductor input now fits21917/22000bytes in the labelled no-model replay,
but representative complete-prompt regression fails (short-root Windows94passed/1failed, lintpassed).
No source integrated. See CONDUCTOR-CORRECTION-189.md including first owner path-limit diagnostic.

Repeated local wording cuts are not the next design. One council-specific reader descriptor should
carry original ref + argv prefix once; the existing exact pointer arrays already supply operations.
Remove derivable duplicate file path/generic recipes only for this delivery path; preserve cursor,
output bounds, safe argv, full raw accessibility and other consumers' readers unchanged. This is a
proposed next correction, not an implemented guarantee. Complete prompt remains the denominator;
keep all meeting content and guards. Existing matrix and accepted results stand. No new live run,
reconciliation, merge, deployment or provider call follows automatically from the unused slot.


### Final slot189: timeout and measured whole-layout revision (2026-09-19)

User requested resolving remainder; one Claude call consumed188->189.900s provider timeout
produced no terminal answer/candidate. Three dirty files retained with hashes/patch, no source
integration. Root owner review:16delivery tests passed/1failed, lintpassed. No automatic retry.

Owner plan was too narrow: representative projection18813bytes is larger than the measured
17819minimum. The specified two reader cuts cannot satisfy that complete test. Before another
implementation, an offline WHOLE advisory-layout projection on the same failing fixture measured
22473->21690bytes, unchanged22000limit, with inline meeting content and handles equal. This is
design evidence only, not an implemented fix or live success. Apply the single measured layout
across conductor objective, phase advisory metadata, reader guidance and empty optional fields;
retain materiality obligations, isolation identity and all source/critical/unknown/argv/cursor
contracts. Keep recovery and other reviewers unchanged. Same matrix/test inputs; no budget
increase or semantic compression. See CONDUCTOR-FINAL-SLOT.md and raw design-projection.json.
Current call budget exhausted189/189; paused. No further model execution is authorized here.


### Prepared whole-layout batch (authorization pending)

Outcome: satisfy the unchanged complete council-input acceptance matrix in one implementation
batch. No live council, merge, deploy, reconciliation, guard relaxation or extra automatic retry.
Current authorization exhausted at189; proposed ceiling190 is NOT granted by this document.
Codex owns this design and direct independent review; Claude implements once only if approved.

Preserved timed-out edits are staged in51de57e, not accepted runtime. Apply the measured proposal
from final-fix/design-projection.json together, instead of guessing another local wording cut:
- Conductor objective: Arbitrate the supplied proposals. Account for every finding; never defer
  a critical finding. Use the declared verdict/disposition enums and echo snapshot/report digests.
- Council preimplementation role_context retains phase and isolation(mode,digest); instruction:
  Read-only at the pinned base; no candidate, worker or verifier has run. Do not execute
  code/tests/scripts or change files. Return structured output only.
- Council delivery reading: Read not_inline from the original external_context artifact:
  reader_argv_prefix plus operation; follow artifact_reader rules.
- Omit an empty task_contract only; empty recovery sources may use {sources:{}}. Nonempty
  recovery retains its complete reader catalogue. Candidate-review and generic paths unchanged.

Complete inline meeting data, original artifact identity, pointer arrays, required digests,
critical-finding/materiality and unknown rules, safe argv, cursor and output bounds remain exact.
Advisory representation assertions may change only to equivalent invariants. Do not alter the
representative fixture input, projection>=17819 or complete-prompt<=22000. The measured proposal
was21690bytes on the labelled synthetic fixture, not a production proof or guaranteed margin.

Allowed implementation: adapters/autonomous_roles.py, adapters/executor.py, delivery regression
file and CONDUCTOR-DELIVERY.md. Check the full failing fixture first, then six focused modules:
test_council_delivery, test_autonomous_roles, test_council_roles, test_external_context,
test_app_server, test_context_recovery; ruff. Owner performs retained-input no-model replay and
required full validation/CI separately. Existing matrix remains fixed; no additional exploration.

A single remaining slot cannot complete Fleet worker+automatic reviewer. Preserve Fleet's true
terminal status; owner direct review is distinct and must not fabricate a PG review decision.
Stop after the one worker attempt and owner checks, with actual result, remaining limits and
source hashes. Failed/timeout evidence stays retained. No second provider call is authorized.


### User direction: subscription-aware autonomous operation (2026-09-19)

User authorizes resolving the remaining operation conditions without per-call permission prompts.
Usage is recorded for token efficiency; the Claude worker uses subscription OAuth. This does not
claim unlimited provider allowance or change account extra-usage settings. For the immediate
prepared implementation, move the legacy ceiling189 to190 as a compatibility control, execute one
worker, and review directly in the owner session. This supersedes the pending numeric approval
above; it is not the future operation policy. No automatic merge or deployment.

Remaining bounded delivery: (1) accept the complete-input correction; (2) replace cumulative
experiment admission with subscription-aware run policy, retaining usage ledger, time/concurrency,
no-progress/failed-attempt stops and provider-limit wait; (3) execute one real full council cycle
and report its actual result. Do not start repeated live cycles to chase success.

Local asset absorption is a PROJECT to execute under that operation, not a prerequisite that must
finish before launch. Track complete inventory, semantic-review coverage and accepted migrations
without claiming inventory equals absorption. Project observability should reuse existing Fleet
and report SSOT: goal, owner/team, phase, accepted progress, blockers, usage and evidence links.
Do not build a second project ledger or expand this correction into UI work. Establish the existing
project-view seam while the worker implements; schedule its bounded extension after launch gates.


### Subscription policy seam and launch acceptance (owner analysis, 2026-09-19)

Evidence: CallBudget.reserve fixes storage and atomically reserves lifetime-count slots; Operation
BudgetedExecutor reserves before both worker/reviewer; Fleet ProcessLauncher and research-program
headroom independently compare those totals. Thus changing only one comparison cannot migrate
admission. Existing absolute deadlines, max_starts, max_cycles/adoptions, lane ownership and
terminal unknown handling already bound work and must survive. Fleet monitor already projects
jobs/goals/dependencies from PG; it is not yet a cross-project progress page.

Primary sources opened2026-09-19: official Claude Pro/Max usage guide
https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
supports subscription allocation shared with Claude Code and waiting for reset; API credits are
a separate choice. https://code.claude.com/docs/en/headless documents structured stream events
and API retry error categories; it does NOT prove our pinned CLI supplies reliable reset times.
Local claude_cli currently classifies generic error_result; no proven durable rate-limit resume.
Do not infer API bill from reported estimated USD or infer subscription remaining from token count.

Next implementation design after input acceptance: explicit operator-selected subscription
accounting mode, preserving legacy finite mode. One shared policy contract must govern manifest
validation, ledger reservation, Fleet admission and program headroom; no huge numeric sentinel,
no reset of lifetime ledger, no silently renewed user quota. Persist mode/policy identity with
observations. Subscription mode records counts without a lifetime admission ceiling; deadline,
max_starts/cycles/adoptions, concurrency and fail-closed ownership remain enforceable. Mode change
is idle/atomic/audited; manifests must agree with the effective policy. Scope it to configured
subscription providers, with no API-key fallback or account billing-setting changes.

Acceptance: legacy policy unchanged; prior high lifetime count does not block subscription mode;
concurrent reservations still unique and recorded; unreadable/write-failed ledger refuses starts;
mode mismatch/unknown refuses; crash leaves counted reservation and ownership; elapsed deadline
and repeated failed cycle stop; provider-limit evidence leads to a visible wait/block state,
not task success or automatic replay of uncertain effects. Never invent reset_at. A confirmed
future reset may admit NEW safe work only under original deadline; unknown reset or ambiguous
execution remains blocked and reported. Real reset is not yet observed. Validate control-plane
and frontend read-only projection as a single contract, using labelled injected limit events.

Operational acceptance remains one actual complete seven-stage cycle followed by bounded stop.
Synthetic input/limit tests establish their injected paths, not actual subscription reset or
production reliability. Current unresolved log-recovery limitation remains explicitly reported;
it must not be hidden by an accepted input-size test. Project UI/asset inventory are next project
work, not new launch gates. Completion evidence must separate prepared, implemented, tested,
actually executed and independently accepted states.


### Implementation batch008: subscription accounting admission

Owner decision: add OPTIONAL budget.mode="subscription" beside existing positive per_host/total
fields. Old shape remains byte-for-byte canonical finite mode. In subscription mode the two
numbers are retained migration metadata, NOT active ceilings or provider allowance. Do not use
an enormous sentinel or clear history. Unknown modes/extra fields refuse. Centralize budget
validation/admission semantics in a small domain usage_policy module and use it from Operation,
Fleet and research program. This is explicit operator policy, not a claim to detect billing plan.
Local observed Codex auth_mode=chatgpt and no API key; isolated Claude passes only OAuth token.
No credential, provider selection, extra usage, or auth configuration change in this batch.

Required complete path:
1. Domain operation/fleet/research_program validators preserve optional subscription mode, legacy
   finite dictionaries unchanged. Autonomous/council inherited budget binding stays exact.
2. CallBudget.reserve accepts explicit mode="subscription" only when passed by BudgetedExecutor;
   still acquires machine lock, checks readable ledger, writes one slot before provider and settles.
   Record accounting mode in that slot. Lifetime counts never block that mode; other errors do.
   Keep finite behavior unchanged and reject unknown modes. Pass new kwarg ONLY for subscription
   so existing finite fake adapters remain compatible. No reservation bypass or second ledger.
3. Fleet LaneLauncher exhaustion and research headroom use same mode semantics. Subscription
   headroom.remaining=null, ok=true only when observed counts are valid/readable; required=7
   remains shape information, not free provider quota. Add accounting_mode for truthful reports.
4. Existing idle atomic authorize-budget CLI gains optional --mode subscription. Keep numeric
   fields for migration compatibility. Immutable grant records include mode; preserve pause and
   refuse queued/active/unknown jobs. A mode change with unchanged numbers is valid; ordinary
   finite same/decrease rules stay. Runtime admissions never grant/change mode themselves.
5. Fleet status/sanitized_config retain mode. Do not remove per-run max_starts/deadlines, program
   caps, ownership, evidence, reconciliation or failure stops. This stage has explicit STOP on
   provider error; automatic reset/resume is deferred until structured provider evidence exists.
   It is finite unattended execution, not a promise of uninterrupted service across provider limits.

Tests: old finite cutoff; subscription reservation above historical ceiling preserves all slots;
unknown mode and unreadable ledger fail before provider; concurrent subscription reservations;
operation wrapper actually passes mode; Fleet idle grant/admission and mismatch; program headroom
and manifest/template round trip; fixed deadlines/caps remain. Injected failures labelled. Do not
call providers in tests. Focused command: python -m pytest tests/test_call_budget.py tests/test_fleet.py
tests/test_fleet_runtime.py tests/test_operation.py tests/test_research_program.py tests/test_research_program_cli.py
tests/test_subscription_accounting.py -q -p no:cacheprovider . Then python -m ruff check .
Owner full suite/CI separate. Write actual report SUBSCRIPTION-ACCOUNTING.md; no full live cycle here.
No frontend redesign now: status API reports mode; the existing UI mode label will be verified with
project-view work, and must not be described as an already migrated dashboard. No automatic merge.


### Operational projects after launch: owner routing

User asks to run complete local-experience absorption AS unattended work and see active projects.
Existing SSOT inspected: docs/full-analysis/path-ledger.json, coverage.json, local-assets-status.json;
coverage says tracked_paths2736 and whole_analysis_complete=false, not_approved_not_incorporated.
This is a recorded inventory snapshot, not a new full local scan or current semantic coverage claim.
Reuse these pinned sources and operation goal bindings; no new competing asset/progress ledger.

First project local-harness-absorption: inventory every authorized source, trace semantics/callers,
compare incumbent Zeus contracts, assign adopt/migrate/already-covered/defer-with-reason disposition,
Claude implements selected bounded changes and Codex reviews evidence. Private auth/session material
is not publishable implementation. Keep local evidence on D; Git stores small specifications/hashes.
Denominators stay separate: inventoried, semantically reviewed, dispositioned, implemented, verified.
Second project project-observability: extend existing Fleet read-only snapshot and monitor route with
stable project identity/goal, jobs grouped by binding, phase/owner, last evidence timestamp, blockers,
remaining acceptance conditions and observed usage. Missing/stale/truncated data is unknown, never
zero or done. Accepted review is not deployment. Existing shadcn/Lucide/tokens/components reused.
No extra launch gate: these projects begin after the bounded real-cycle acceptance, not before it.


### Batch008 observed obstacle and complete provider-control correction

Actual worker008 stopped with result_subtype=error_max_budget_usd at the legacy5USD CLI estimate
cap. This is NOT observed subscription exhaustion or an API bill. Dirty implementation preserved
in14fa934, owner83tests passed/2skipped and lint passed; no terminal model answer/candidate existed.
Owner also named a nonexistent test_call_budget.py; correct focused ledger file is
 test_claude_review_boundaries.py. Do not repeat the nonexistent command.

Revised SAME design: accounting mode must reach provider command AND invocation receipt, not just
admission. Implement this complete narrow path on top of preserved008 code:
- domain.operation.provider_settings explicitly sets ZEUS_CLAUDE_ACCOUNTING_MODE to finite or
  subscription from manifest budget. Keep manifest positive numeric max_budget_usd for compatibility;
  in subscription it is retained metadata, not forwarded as an active dollar ceiling.
- domain.providers validates that explicit setting (unknown refuses); binds subscription into the
  selected Claude runtime accounting_mode/config digest. Finite/default canonical configuration
  remains unchanged. Subscription selection omits max_budget_usd from assignment.controls.
- Executor builds invocation options WITHOUT max_budget_usd when absent; assignment/receipt must
  identify accounting_mode and must not claim delivery of a dollar cap. No change to timeout,
  schema, model, permissions, worktree/isolation, provider auth or actual usage recording.
- ClaudeRuntime requires a positive spend ceiling on finite/default exactly as before. Explicit
  runtime.accounting_mode=subscription omits --max-budget-usd, records null dollar cap and named
  accounting mode; unknown mode refuses before spawning. Capability preflight may still require
  supported CLI features, but must not claim an unused option was passed. No enormous dollar cap.
- isolated runtime serializes runtime dict already; verify the mode crosses request/entry and
  isolated command generation. Owner must rebuild/pin worker image from accepted source before
  live use: old immutable image contains old ClaudeRuntime. Do not falsely claim host-only code
  changes update the image. Worker does not build images or call providers.

Tests cover finite unchanged, subscription command flag absent/receipt truthful, unknown rejected,
provider_settings -> policy select -> executor invocation, and isolated request transport. Add in
 test_subscription_accounting.py; preserve old tests. Focused verification: python -m pytest
 tests/test_subscription_accounting.py tests/test_fleet.py tests/test_fleet_runtime.py
 tests/test_operation.py tests/test_research_program.py tests/test_research_program_cli.py
 tests/test_claude_review_boundaries.py tests/test_claude_cli_process.py tests/test_claude_assignment.py
 tests/test_invocation_ledger.py -q -p no:cacheprovider. Check file existence before commands; report any
 name mismatch and substitute actual file, do not invent success. Then python -m ruff check .
Update SUBSCRIPTION-ACCOUNTING.md and docs/contracts.md. No schema weakening or automatic retry.
One Claude completion attempt, owner direct review; legacy ceiling192 holds the remaining slot.
Bootstrap call alone uses10USD estimate cap to finish this migration, not new billing authorization;
900s execution bound stays. Future subscription mode forwards no dollar cap. No live retry now.


### Live004 reframe: variable meeting input exceeds the complete envelope

Actual evidence: RESULT-004.md / EVIDENCE-004.json. Four roles succeeded; conductor preflight refused.
Old retained-input proof remains accepted. New exact-input no-model replay is23055/22000 complete bytes;
projection alone20751. No timeout, quota exhaustion or stale snapshot is implicated by this failure.
Subscription operation010 was actually accepted and final runtime CI passed. No numeric grant loop.

Invalid assumption: fixed advisory compaction alone bounds variable upstream packet/proposal contents.
Do not respond with another arbitrary short sentence, raised context ceiling, or silent semantic truncation.
Next bounded design decision: compare existing hash-bound paged reader delivery against an explicit
producer/consumer byte-envelope contract. A valid solution must preserve every claim, proposal, finding,
unknown, citation and digest, or refuse the plan before spending its downstream role calls. Inspect actual
reader execution/receipt coverage before relying on model self-report that all pages were read.
Acceptance matrix: old/new exact raw inputs; non-ASCII size; empty/maximum admitted arrays; missing,
corrupt or changed pages; all findings accounted; cancellation/deadline; finite total read/output bounds.
Concurrency/restart use existing immutable artifact identity and attempt binding; no new mutable store.
A successful small fixture alone cannot close this issue. No implementation selected or claimed yet.

Next implementation remains Claude's responsibility under one consolidated owner specification; Codex
reviews the complete delivery path. No new live retry in004. Completion criteria remain accepted full
cycle plus tick2/stop; absorption and project page are queued operational projects, not launch blockers.


### Delivery research and owner recommendation (2026-09-19; research only)

Outcome: choose a coherent JSON delivery architecture after live004. No runtime edits, model calls,
resumption, merge or deployment in this research batch. Preserve prior accepted results and raw evidence.
Questions that change the decision: is22000 a provider limit; what existing reader can be reused; does
paging actually reduce total context; what delivery evidence can the host verify? Research stops here:
these decisions are supported; exact new capacity and receipt integration need implementation evidence.

#### Sources opened, supported claims and limits

| Source / version | Supported fact | Does not establish |
|---|---|---|
| [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), article2025-09-29, accessed2026-09-19 | Lightweight references and just-in-time tools can complement upfront context; retrieval costs latency and compaction can lose important details | Zeus latency, completeness or receipt guarantees |
| [Microsoft Claim-Check](https://learn.microsoft.com/en-us/azure/architecture/patterns/claim-check), living architecture guidance accessed2026-09-19 | Put large payload in storage and send its retrieval reference in the message | Smaller eventual LLM context or semantic comprehension |
| [RFC6901](https://www.rfc-editor.org/rfc/rfc6901.html), April2013 | JSON Pointer identifies a value; unresolved pointers are errors | Hash integrity, authorization, pagination or delivery receipts |
| [MCP pagination](https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination),2025-06-18 | Cursor pagination applies to specified list operations | Automatic resources/read body pagination; Zeus reader is a custom contract |
| [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), living API guidance accessed2026-09-19 | Reuse stable prefixes and measure reported cached/input tokens; caching behavior depends on model and configuration | Codex CLI exposes those API controls, quota relief, or bypass of Zeus preflight |

These are design sources, not claims that Zeus uses those vendors' managed products. No new MQ,
vector database, MCP server or provider migration is required by this recommendation.

#### Current complete path and facts

Six-W message -> council task details -> content-addressed raw artifact -> council_delivery inline
projection -> Executor required envelope -> compile_context -> AppServer -> structured role result ->
existing council validators and PG runtime state. Redis transport is distinct from the model prompt.
Git owns definitions; PG owns execution state; immutable artifacts own the referenced evidence bytes.
Evidence may be persisted as unverified evidence; persistence is not approved knowledge/ontology promotion.

At source3091f1f, executor.py calls compile_context(...,28000,6000). domain/model.py compares UTF-8 byte
length against their difference22000. The field estimated_tokens contains that byte estimate, not measured
provider tokens. Provider runtime separately observes modelContextWindow/tokenUsage. Therefore the live004
failure is a local admission-policy failure, not proof of model context exhaustion or Redis size limits.
Do not silently relabel historical observations. A future version should name byte estimates and observed
tokens distinctly, retaining compatibility for old receipts.

Existing artifact_reader validates raw SHA256 and exposes index/page/pointer/search; artifact_query uses
character cursors and response-character limits. AppServer retains tool events, but inspected code does not
require complete mandatory-page coverage before accepting an answer. A file existing, a command exiting0,
or a model saying it read everything does not establish that every required result reached this attempt.
This is an identified implementation gap for the proposed reference mode, not a newly proven live defect.

Offline discriminating check used live004 exact raw SHA256 e334ba8749970226d3b4e7268d3b8aee9ff9156ed76136df374efdfecfaab4a9.
Existing pointer() reconstructed packet, DBA report and both proposals exactly in5 pages at limit8000.
Responses total21128 UTF-8 bytes versus18917 bytes for those four original serialized values. One page
contains5119 characters but5125 bytes. Thus paging works for lossless retrieval locally, but adds wrapper
bytes and does not establish context/token savings. No provider, shell-reader delivery or receipt test ran.

#### Options and recommendation

| Option | Benefit | Main limit | Owner decision |
|---|---|---|---|
| Shorter keys/new serialization or repeated wording cuts | Small local savings | Variable semantic content still has no joint bound; migration cost | Do not use as the main fix; keep JSON |
| Larger hardcoded cap alone | Would admit this sample if raised enough | No general bound/quality evidence | Do not claim structural resolution |
| Validated role-specific inline envelope | Few tool round trips; every required value explicitly delivered | Requires declared aggregate producer/output limits and measured headroom | Preferred first operational path for bounded meetings |
| Manifest plus lossless required reads | Reuses artifact SSOT; larger evidence need not travel in every MQ message | Read completeness, tool latency and cumulative context need control | Extension for larger evidence, not an automatic22KB bypass |
| Model summary as sole decision input | Potential compression | Could remove objection/unknown/qualification | Summaries are navigation aids, not replacements for mandatory evidence |

Recommended architecture: keep the six-W JSON envelope and immutable raw originals. Build a versioned,
role-specific meeting manifest naming goal/criteria, revision, attempt, complete mandatory item IDs and
hash-bound references. Deliver small mandatory material once inline; keep large source logs/history as
on-demand evidence. Hash-reference cache is not provider prompt cache and neither is verified knowledge.

For the immediate bounded council, prefer an explicit producer-to-consumer INLINE size contract over
adding a new read-receipt subsystem just to save1055 bytes. Compute the maximum admitted serialized
packet + DBA + proposals + all findings + host/recovery/schema/tool allowances across the whole path;
choose and document a role-specific capacity from that bound and pinned runtime observations. The fixed
22000 is not sacred, but replacing it needs a reasoned policy/versioned contract, not a huge sentinel.
Validate aggregate bytes at producer boundaries (Unicode/escaping included); never truncate valid output.
If a topic cannot fit, return one needs_scope_split outcome with remaining work preserved; no automatic
recursive debate/retry. Exact numerical capacities are not selected by this research and no limit changed.

For later reference delivery, mandatory reads are host-controlled/observed and bound to attempt, manifest,
artifact hash, pointer, cursor range, successful complete output and final cursor. Missing coverage blocks
approval. Receipt proves transport, not model understanding; citation/finding checks and independent review
remain. Count cumulative bytes/tokens and latency including pages; do not move data to tools to evade limits.
Repeated identical reads do not increase coverage; stale receipts cannot satisfy a new attempt. Retain
artifacts while referenced by active work/review. Additional findings and unknowns cannot vanish in summaries.

#### One future implementation batch and acceptance matrix

Codex first finalizes the numeric inline admission contract from admitted producer shapes; Claude implements
that contract, versioned measurement fields and explicit overflow outcome in existing components. Codex
reviews once across this matrix. Reference receipt mode is deferred unless the bounded inline approach
cannot satisfy an actual required use case; do not implement both paths speculatively.

| Path | Acceptance evidence required |
|---|---|
| Normal | Run003/004 exact raw inputs and maximum admitted shapes reach complete required prompt unchanged |
| Failure/unknown | Oversized/missing/malformed producer output stops before downstream provider; no silent omissions |
| Unicode | Bytes, characters and provider tokens reported separately; escaped text/long IDs included in bound |
| Timeout/cancel | Existing deadline and stop contract unchanged; incomplete role is not approved |
| Concurrency/restart | Existing attempt/revision/hash binding preserved; no receipt or output borrowing |
| Platform | Windows/Linux deterministic serialization and existing reader/path behavior retained |
| Cleanup | Evidence remains accessible through review; no new temporary store or GC policy in inline batch |
| Optional reference mode | Deferred; all mandatory page output coverage and cumulative budget must pass before enabling |

Metrics: initial prompt bytes; observed input/output/cached tokens when available; unknown explicitly when
absent; required-item coverage; duplicate material/read bytes; tool turns; stage latency; admission failures;
end-to-end accepted cycles. Provider cost estimates are not subscription invoices. Page reads are not model
comprehension metrics. Completion remains one accepted full council and second bounded tick/stop after CI;
local absorption and project monitoring are operational projects, not extra launch prerequisites.

Offline evidence: `D:\workspaces\zeus\artifacts\research-program-001\delivery-research\paging-measurement.json`; SHA256 `dcebc7a51d3abbb7e114b263e83f89d12755d829525d4ae2e8c5d4adc353196e`.


### Delivery implementation011: owner-fixed bounded inline contract

Authorization: user says proceed after research. One Claude implementation + independent review, owner
checks and CI; live canary only if accepted, at most2ticks/1council and stop at first failure. No merge/deploy.
Use existing six-W, council, raw artifact and input compiler. No paged-receipt subsystem in this batch.

Versioned contract urn:zeus:council-input:1, UTF-8 lengths of canonical JSON (including JSON escaping):
packet<=16384; normalized DBA report<=4096; complete research proposal<=4096; complete improvement
proposal INCLUDING all findings<=8192. Sum32768. Full council_delivery metadata/wrapper (serialized
projection size minus serialized present payload components) <=4096. Complete required ContextPacket
outside serialized delivery <=4096, checked after recovery/skills metadata assembly. Thus maximum
required context40960; council-debate compiler window49152, reserved8192. These are explicit local byte
policy values, NOT model tokens/capacity. Legacy non-council budget28000-6000 remains unchanged.
Current live004 payloads11871/1295/2666/3085 and required envelope23055 fit with headroom. These limits
are a bounded supported workload, not proof arbitrary research fits. Raw originals are never truncated.

One SSOT domain module owns constants, canonical-byte validation, safe typed overflow and a policy
manifest. Producers: CouncilRun validates frozen packet immediately after _freeze_packet BEFORE snapshot
or DBA; normalized DBA report before relay/next lead; complete derived lead proposal before sessions.submit
or any downstream role. Domain consumers recheck the full projection before provider, not just producer
promises. Council run ends with precise needs_scope_split reason (terminal failure is acceptable if existing
status enum retained), safe section/observed/max byte diagnostics, with original role evidence retained.
No automatic retries/summary/drop/resize. Missing mandatory fields remain errors distinct from size overflow.

Executor uses council policy only when actual action=dge_role, appropriate debate role/stage, and validated
delivery; caller cannot inject an arbitrary delivery to obtain larger budget. Measure final required prompt
including actual IDs/paths/recovery/skills, fail before provider if host allowance exceeded, and emit named
byte measurements in context artifact/receipt without changing old estimated_tokens semantics silently.
Expose context policy/version, measured required bytes and limit in an additive compatibility-safe place.
No token estimates masquerading as observed usage. Output instructions give producer limits and require
concise factual content with all findings/unknowns preserved; no schema keyword unsupported by pinned CLI.

Tests: unchanged legacy compiler and non-council executor; valid roles and caller-spoof rejection; exact cap
and cap+1 including multi-byte/escaped text; complete largest-admitted payloads+metadata+host under actual
Executor/compiler; producer overflow stops before NEXT provider/session submission (calls counted via
injected fakes and labelled); missing/unknown fields; hash/source unchanged; raw originals retained;
current recovery overflow explicitly fails safely. Existing timeout/cancel/restart/clean checkout gates stay.
Owner replays actual run003/004 raw inputs using no-model runtime and labels that limitation. Synthetic max
checks prove deterministic delivery, not semantic model quality. Then owner full suite and CI; one real run
only after pass. If a meaningful assumption breaks, return one consolidated failure; do not patch repeatedly.

Claude allowed paths: new domain/council_input.py; application/council.py; adapters/autonomous_roles.py;
adapters/executor.py; tests/test_council_input.py and directly affected council-delivery tests;
docs/contracts.md. Do not change global model.py serialization, provider limits, source/privacy gates,
auth, budgets, snapshot freshness, deadlines, consumer evidence or PR-review artifacts. No extra model calls.


### Completion012 after011 timeout: one consolidated owner review

011 ended with claude-provider-timeout, no terminal answer/candidate or automated review. Owner preserved
all seven files byte-for-byte then committed7bdbd54. Actual retained-input replay4/4 passed no-model,
including current conductor23122/40960; accepted proof only for delivery, not semantic execution.
Owner focused75passed/3errors: maximum input cases never ran because representative fixture absent.
No broad redesign or deadline increase. Complete the existing implementation in one short bounded batch:
1. Import/reuse test_council_delivery.representative properly (pytest fixture registration, no tests. imports)
   and execute the three max-input cases, not just collection. Preserve assertions; fix real failures.
2. Remove context_bytes/context_policy additions to development.provider_started attributes. Registry rejects
   both keys and Observer.emit returnsNone, losing the entire normal start event. Keep the unchanged existing
   log schema; context_measurement in execution receipt already carries additive telemetry. Test start-event
   attributes with actual check_attributes or real Observer, not a permissive fake. No observation.py edits.
3. CouncilRun._role currently unwraps only role_failed; real executor pre-entry refusals produce role_retry.
   Safely surface typed needs_scope_split for both legitimate statuses (no automatic retry), while unrelated
   failures stay unchanged. Replace/extend injected failed-only test with retry outcome and verify run code.
   Final complete-required overflow must also raise typed CouncilInputOverflow before generic compiler error:
   preflight actual required envelope through ContextPacket before compile_context; share identical snapshot
   and required dict with compiler. Keep current final rendered/host guard; no cap changes, no global compiler
   edits. Add a required-host input that exceeds whole40960 and verify named safe diagnostics/provider0.
4. Run focused tests and lint; return structured result promptly, do not perform full suite (owner/CI does).
This completes existing input gate acceptance and log compatibility; no new requirement outside touched path.


### Live005 reframe: fixed partitions waste the bounded total (no new execution)

Source RESULT-005.md/EVIDENCE-005.json. Implementation011/012 and CI pass; actual live producer correctly
refuses research proposal4260 against4096. Raw original retained. Three real roles succeeded, then stop.
Invalid owner assumption: four independent maximum allocations are a necessary way to ensure total admission.
Discriminating check: exact packet11965 + report1677 + proposal4260 + future improvement reservation8192 +
overhead reservations8192 =34286, below40960 by6674. No semantic compression is needed for this observed case.

Revised next bounded design recommendation: shared payload pool32768 plus existing two4096 overhead caps.
In declared production order, require sum(actual committed payloads through current stage) + sum(default
reservations for future payloads) <=32768. Initial reservations remain16384/4096/4096/8192. Earlier unused
capacity is available downstream; future capacity is never spent twice. Final consumer checks exact total
and all mandatory components instead of obsolete per-section maxima; preserve role/hash/source matching.
Default sizes are future reservations, not immutable section ceilings after earlier stages finish. Do not
silently keep both conflicting policies. Version the policy; old receipts retain original meanings.

Before a next implementation, one full matrix must cover every stage, exact pool/pool+1, non-ASCII,
missing/future components, current observed input, future-reservation exhaustion, whole-envelope/recovery,
restart binding, and source retention. No global budget raise, summarization, tool-context bypass or recursive
retry. Current v1 guard remains in force; this recommendation is NOT implemented and has NOT passed a live run.
No further model call in005. Acceptance stays complete real cycle plus tick2/stop; do not call early refusal
an operational success. Keep successful code/CI evidence and move only this changed policy assumption forward.

### Implementation013: shared pool with ordered future reservations (owner decision)

Outcome/authority: complete the unchanged bounded unattended acceptance; Claude implements, Codex reviews.
This replaces v1 independent payload ceilings with urn:zeus:council-input:2. No global allowance increase.
No further research needed: the exact live005 measurement above discriminates the failed design assumption.
Historical v1 receipts/files stay unchanged; new manifests/receipts truthfully name v2. Old pinned revisions
keep old behavior; do not reinterpret old evidence as v2 or build a second runtime policy unnecessarily.

Affected path: frozen packet -> snapshot/DBA -> normalized report -> research lead -> complete research
proposal -> improvement lead -> complete alternative -> conductor -> existing implementation/review/promotion.
Producer admission is a pure ordered-prefix calculation; no mutable global budget or cross-run credit.
Order is packet, dba_report, research_proposal, improvement_proposal; reservations16384/4096/4096/8192.
For any nonempty contiguous prefix, sum(canonical bytes of actual prefix) + reservations of absent future
components must be <=32768. Reject holes, unknown payload keys, and out-of-order explicit stage arguments.
Compute current-stage allowance =32768 - actual earlier bytes - reservations of later components. Typed
safe overflow names the current component and actual/available bytes. Never admit a missing earlier value
by pretending it is empty. Future values must not affect a producer's current allowance.

Consumer projections are role-specific contiguous prefixes: research_lead gets packet+report;
improvement_lead adds research_proposal; conductor adds improvement_proposal. Check role-required fields,
exact projection binding and the SAME prefix reservation rule (including future reservations for early
roles). Final complete prefix spends the pool without per-component ceilings. Wrapper<=4096 and
host<=4096, required<=40960 and compiler49152-8192 remain unchanged. No trust in producer admission alone.
Production callers must all stop using isolated per-section v1 admission. Remove/replace the old isolated
API rather than leave two contradictory policies. New manifest calls numbers reservations, not limits.

Producer instructions must not continue asserting4096 as a hard research cap. Where earlier payloads exist,
report the calculated allowance using the same domain function; researcher initial allowance16384. DBA
report normalization and derived proposals add structure, so say explicitly the limit covers the normalized
or derived value, not merely raw prose. Keep every finding/unknown; original evidence must not be rewritten.
Do not weaken compiler guard, snapshot freshness, action/role binding, acceptance schemas, ledger, auth,
isolation, source privacy or promotion. No summary, tool-context bypass, automatic retry or model call.

Acceptance matrix (one batch):
- Each of four producer prefixes: exact aggregate reservation bound passes, one byte over refuses before
  downstream submission/provider. Earlier unused bytes can be spent later; future reservations preserved.
- Actual live005 sizes11965/1677/4260 pass with future8192 reserved; later8192 remains admissible. Synthetic
  size-equivalent case is labelled as such; owner replays actual raw data separately.
- Unicode/JSON escaping counted as canonical UTF8, not characters/tokens; originals and hashes unchanged.
- Missing/holey prefix, wrong role or supplied projection, future-component injection are contract errors;
  overflow remains precise needs_scope_split and safe for existing retry/failed mapping.
- All three full executor role projections fit at their largest admitted prefix with overhead reservations;
  oversized wrapper, host/recovery and complete envelope still refuse before provider.
- Keep legacy non-council limits and source/attempt identity tests. Pure calculations introduce no new shared
  state; repeated independent calls must not borrow credit. Existing restart/freshness gates unchanged.
- Timeout/cancel/platform/cleanup architecture unchanged, use existing coverage, do not create new subsystems.

Allowed changes: domain/council_input.py, application/council.py, adapters/autonomous_roles.py,
adapters/executor.py only if required, tests/test_council_input.py, tests/test_council_delivery.py,
tests/test_council.py, tests/test_council_roles.py, docs/contracts.md. Update obsolete v1 assertions as policy
migration; preserve their safety purpose. Worker runs focused four files and ruff only; owner full suite/CI.
Return one completed candidate with exact checks and limitations. One actual new canary only after acceptance
and CI: max2 collection ticks/1 council, fail-stop, no automatic merge/deploy. Success requires full accepted
cycle plus bounded second tick/stop; local-asset absorption and project view stay operational follow-up work.
