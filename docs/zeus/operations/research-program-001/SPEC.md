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
