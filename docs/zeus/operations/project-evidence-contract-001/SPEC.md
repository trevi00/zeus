# Project evidence contract 001

## Outcome, scope, authority, finish

Codex designs/accepts; Claude implements through Zeus. User authorized continuation of
Code Tutor's measured residual: project execution/evidence binding. Deliver one backwards-
compatible host-authored project verification contract, structured worker observations,
and exact debate criterion schema binding. Reuse existing inspection/operation machinery;
no second runner, no automatic dependency installation, no weakening gates, no rewriting
old failed records. Code Tutor product candidate d975d55 remains accepted for its narrow
local lane; do not change product behavior or rerun full product browser acceptance here.

Finish: focused real subprocess and seam regressions, full Zeus lint/tests, clean independent
review and one bounded actual Claude->replay->Codex operation with a project subdirectory
context. Create reviewable PR with evidence; merge if all required checks pass. Human/device,
public deployment, arbitrary JS runtime provisioning and general dependency attestation are
out of scope. One coherent review batch; only material demonstrated residuals block.

## Evidence, existing path, decisions

Base 18f09815f128245664d99522d66e58b894fe5c9a. Codetutor runs 001/002/003 are preserved
at D:/workspaces/code-tutor-zeus/artifacts. Run003 inspection
f896187a9c9000a0cf073c4c0ec0e6e76cbfabf4f7873bd93c5c4e980a8a3aa2:
15 claims = 1 checked, 6 mismatch, 8 not_checked. Worker listed attempted commands;
consumer assigned every free-text command expected_exit=0, ran backend-relative paths at
repository root with Zeus Python. Worker separately disclosed failures in RUNBOOK.md.
Run002 criterion prose was refused by exact item membership. These are observed contract
mismatches, not proof the product failed. Owner later measured 62 tests + 4 browser scenarios.

SSOT: domain/evidence.py parse_claim/authorized/verdict; adapters/evidence_inspection.py
snapshot/replay_environment/inspect/_capture; application/evidence_inspection.py keys and
require_all_checked; adapters/executor.py IMPLEMENTATION/implement/_inspect_evidence/
review_context; bootstrap build_executor; operation_cli identity; autonomous_roles schemas
and execute_role -> domain/dge exact criterion validation. Reuse all these boundaries.

Flow: trusted host configuration -> executor loaded profile -> candidate workspace + model
output -> immutable snapshot -> bounded allowlisted replay -> PG inspection -> operation
review gate -> separate Codex review -> owner integration. Provider lease/budget/outbox,
checkpoint and cleanup paths remain unchanged. Profile file is operator configuration, never
read from the candidate or accepted from model output. Each operation identity includes its
profile digest so same-id cached replay cannot silently change context. Autonomous entrypoint
identity must also bind it if it composes an operation. Profile loaded once and passed into
executor; bad configured profile fails before provider entry. Legacy absence stays legacy.

Opened primary docs 2026-09-17:
- https://docs.python.org/3.12/library/subprocess.html (3.12.14): explicit argv/cwd/env and
  executable select execution context; returncode records outcome. Does not attest dependencies.
- https://docs.python.org/3.12/library/venv.html (3.12.14): virtual environments have own
  interpreter/site-packages; activation is unnecessary when invoking the absolute interpreter.
- https://docs.pytest.org/en/stable/reference/exit-codes.html: 0 pass, 2 interruption, 4 usage
  error, 5 no collected tests. A reported attempted command is not a passing test.

## Complete implementation batch

Add INV-PROJECT-EVIDENCE-001. Prefer new domain/project_evidence.py and
adapters/project_evidence.py for cohesive new contract, keep existing legacy semantics.

1. Host-only optional ZEUS_EVIDENCE_PROFILE (HARNESS alias through existing settings) names
   an absolute external JSON file. Schema urn:zeus:project-evidence:1, closed fields:
   {schema, contexts, checks}. contexts is nonempty mapping of safe short id to
   {cwd, interpreter, source_paths, dependency_files}; cwd is '.' or safe relative path,
   interpreter is trusted existing absolute host file, source_paths and dependency_files are
   safe workspace-relative paths. Every resolved directory/file must stay in candidate root,
   including symlinks. Never accept arbitrary env/secrets. checks is nonempty list of
   {id, context, argv, expected_exit}; id distinct, context exists, argv restricted by the
   SAME packaged allowlist; all named checks are required acceptance checks. No command
   mutation/format/install authorization. Host prepares dependencies, not this module.
   Host rejects missing/invalid profile instead of falling back. Store parsed immutable copy.

2. Profile-aware worker response schema remains {summary,tests}, but tests entries are
   {check_id,status,exit_code}, status enum executed/not_run, exit_code integer or null.
   Provide host-authored check list and resolved execution context in implement details,
   with exact interpreter/cwd/source env instructions. Worker cannot choose argv/cwd/required
   flag/interpreter. One observation per declared check: unknown/duplicate/missing ids refuse
   or produce explicit nonchecked finding. executed needs integer exit; not_run needs null.
   A required check not_run remains incomplete and is not replayed. An executed failed check
   is retained as reported failure, never coerced to expected 0; independently replay it but
   all_checked requires both observed_exit and replay exits equal host expected_exit. Expected
   nonzero negative checks are allowed only if the HOST declares them. Additional diagnostic
   attempts/unrun plans belong in summary; they are not required check claims. Legacy unprofiled
   tests strings and structured command/file claims remain compatible. No model-selected
   required/optional toggle and no empty-denominator success.

3. Profile-aware snapshot/inspection uses each named context's actual interpreter, explicit
   cwd and candidate source paths. Do not read parent PYTHONPATH or use editable install source
   as evidence. PYTHONDONTWRITEBYTECODE=1. Source path existence/containment checked before
   replay. Bind profile digest, resolved workspace/context values, dependency-file byte digests,
   interpreter file content digest and environment value digest into identity/cache. Same
   immutable snapshot values used during replay even if host environment/profile file changes.
   A selected interpreter path is not proof of installed dependency immutability: state this
   limit; new resolved lockfile/profile bytes invalidate cached inspection. Maintain aggregate
   replay time/output/claim bounds and archive raw outputs. Findings name check/context,
   original host argv/effective argv, reported exit, expected exit, observed replay exits.
   Snapshot plumbing must not silently drop contexts between application inspect and adapter.

4. Profile-aware read-only reviewer receives same project execution instructions rebound to
   its clean candidate checkout, not implementation checkout. Profile absence leaves existing
   review_context contract. Tests must not create checkout artifacts; stdout/raw artifacts go
   external as already contracted. Bind profile in operate/autonomous identity (loaded via host
   settings); old identity shape may remain exact when profile absent. No changes to evidence
   gate acceptance or ontology promotion. Worker profile instructions/AGENTS should explain
   profile vs legacy output format without stale contradictory rules; update profile digest
   fixture/manifests through existing mechanism if needed.

5. Deep-copy role output schema per execute_role and replace finding.criterion TEXT with enum
   of the pinned plan acceptance_criteria for attacker and improvement_lead. Do not normalize,
   paraphrase, coerce output or loosen domain exact membership. Keep static schema constants
   unmodified across runs. Cover schema->domain boundary; no extra debate/council call needed.

Allowed files: above/new cohesive modules, executor/bootstrap/operation_cli/autonomous_cli
or existing identity composer, application evidence_inspection, autonomous_roles, related tests,
worker-profile-v1 resources if required with digest updates, AGENTS.md, docs/contracts.md and
this task directory. Do not touch unrelated assets, runtime ledger, migrations or product repo.

## Acceptance matrix

| Boundary | Deciding check |
|---|---|
| Normal | actual Python subprocess in backend subdirectory imports candidate backend/src via host-selected interpreter; required named check replays checked; root/legacy preserved |
| Failure | executed nonzero retained, cannot pass host expected0; host expectednonzero can pass; no-tests5 is not pass0; missing/duplicate/unknown check cannot all_checked |
| Unknown | planned/not_run remains incomplete without spawn; invalid/missing profile/interpreter/source/dependency refuses before spawn, no fallback |
| Authority | model output cannot inject argv/path/env; packaged allowlist still rejects format/shell/install; traversal/absolute cwd/symlink escape refused |
| Snapshot/cache | profile, dependency bytes, interpreter bytes or effective env changes invalidate; snapshot remains used after parent env/file changes; review gets its own checkout |
| Timeout/cleanup | reuse existing bounded _capture, test timeout in context and raw-output refs, no new process-management mechanism |
| Restart/concurrency | per-run loaded profile, no global schema mutation; same operation id different profile refused; old persisted inspection/state untouched |
| Debate | enum contains exact pinned criteria; paraphrase rejected; subsequent different plan doesn't inherit old enum |
| Integration | executor profile output and inspection -> unchanged gate -> reviewer; config wiring and identity covered, fake provider seams labelled |
| Real operation | one actual Claude+Codex pair max2 starts after candidate adoption; all_checked and reviewer acceptance, no promotion/deploy claim |
| Platforms | local Windows real subprocess; Linux CI; platform-specific venv paths owner supplied, no shared Windows/WSL venv |

Owner runs required uv run ruff check . and uv run pytest with runtime dependencies available
and raw evidence external. Claude runs focused regressions and lint, reports failures honestly,
leaves no commit/remote mutation and never calls models. Bootstrap operation uses OLD legacy
contract: only successful replayable commands in tests; attempted failures are explicitly in
summary, because the runtime patch is not active yet. New-contract behavior is tested directly.

Budget: starting ledger80. One implementation+review operation (2), one live external-project
canary pair (2), at most one critical corrective implementation pair (2): ceiling86 for this
bounded delivery, no blind retry. Claude max_budget_usd16, timeout900; leads300 existing limits.
Record calls actually used, not allocated budget as spend. If architecture fails, update this
same frame before any additional operation; no repeated tiny patch batches.

### Launch correction (before any model call)

Bootstrap project-evidence-001 failed ConnectionError before delivery, ledger stayed80.
The owner launcher used stale Redis port56379; current `docker port zeus-local-ops-redis`
is127.0.0.1:63589. No implementation started. Keep failed receipt and pending old namespace
unchanged, use a new operation identity and resolve/ping the exact container endpoint before
launch. This is a corrected owner launch, not a model retry or a readiness investigation.
Run002 reached Redis but refused foreign_correlation, still zero calls: shared PG outbox
included pending prior-run work even with a different Redis namespace. Revised launcher
uses a new PG schema plus new Redis namespace together, resolving endpoints before setup.
Do not drain/repair old failed operations as part of this delivery. Fresh-schema isolation
is the discriminating check; no runtime change is added for these owner setup mistakes.

## Consolidated candidate review and correction batch

Candidate784e6f9: bootstrap worker succeeded, three legacy checks all_checked; independent
Codex review rejected (artifact a9cf52257dcef36c45952a985db85c47dca4968dba684fd15ab086d05243d3c4).
Owner's actual Code Tutor project-profile replay also all_checked (two real47-test executions).
Keep these accepted paths. Three directly affected boundaries require one correction batch:

R1 selected runtime enforcement: profile accepts `uv run python -m pytest` but replay_argv
only substitutes `python -m`; uv reaches capture unchanged. The inspection records an
interpreter it did not enforce. For this Python-only first profile version, REFUSE every
profile argv form except `python -m pytest ...` and `python -m ruff check ...`, still intersect
with packaged allowlist. Legacy unprofiled forms remain untouched. Document this deliberate
version1 support boundary. Do not implement installers or new runtime adapters.

R2 aggregate deadline: independent reviewer deterministic clock/capture probe reached
all_checked at1.5s with a1s budget because every repeat gets the original remaining timeout.
Pass one absolute monotonic deadline and recompute remaining before EVERY repeat; do not
start another at/beyond deadline, late success cannot count as checked. Reuse existing
capture/cleanup; cleanup overhead is not useful execution allowance. Test partial first
success followed by budget exhaustion, remaining timeout shrinking, timely normal success.

R3 complete worker delivery: packaged worker-profile-v1.md still categorically says do not
substitute an absolute interpreter; ClaudeCodeRuntime.profile_environment still prepares
Zeus Python/root src and its Bash rules only authorize legacy python commands. The new
profile currently exists only in prompt details; its correct replay is not proof the worker
can execute the host-selected command. Fix the actual Claude transport boundary and its
instructions together. Supply per-run resolved host contexts to runtime, never derive grants
from model output, and provide safely quoted exact runnable command(s) with the named cwd,
interpreter and source environment. Add only narrowly scoped per-run permissions needed for
these host-declared checks; no blanket Bash(*)/bypassPermissions/global settings. Keep the
repository root as editing/review root; do not move Claude into backend as its workspace.
Use standard shell quoting for generated command text; model-authored commands are never
concatenated into shell. Prefer existing CLI settings/environment composition, not a new
execution runner. One or multiple contexts must match their named check. Preserve all deny
rules. Legacy profile path stays exact when project profile absent. Explicit host-profile
instructions override only the legacy interpreter/command-output instructions. Include
transport settings + instruction regression, not only fake AppServer prompt assertions.

Primary docs opened2026-09-17 https://code.claude.com/docs/en/permissions: prompt instructions
do not grant permission; per-run settings allow rules control it, with deny precedence and
compound-command checks. This supports runtime wiring, not proof our installed CLI ran it.
The final actual Claude canary decides this boundary, not a configuration-only claim.

No other source changes requested. Full service suite already running on initial candidate;
retain its result, then run relevant corrections/full required checks once on corrected head.
Use one corrective Claude+review pair ceiling84, then reserved actual Code Tutor pair ceiling86.
An unrelated issue does not extend this batch or silently weaken the completion conditions.
