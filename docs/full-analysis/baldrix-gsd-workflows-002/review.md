# Pinned workflow contracts: bounded static review

All nine primary bodies were freshly read in full at Baldrix revision `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`. This is a review of orchestration prose and bounded implementation, not execution of its instructions. Primary status remains `body_reviewed_call_test_trace_pending`. Prior ledger rows were unreviewed; earlier partial supporting reads are not reused. Exact bytes, Git blobs, SHA-256 values and read ranges are in files.json and supporting.json.

The material does not implement the user's eight-stage SDD merely by naming discussion, planning, execution and verification. Zeus needs the human-defined eight stages as versioned Git definitions, with PG holding runtime attempts, decisions, ownership, evidence and transition receipts. The proposals below describe adaptations to evaluate, not current Zeus equivalence or approval to absorb this source.

## f01

`get-shit-done/workflows/discuss-phase.md`, full lines 1-1201.

Purpose and outputs: turn the user's phase vision into CONTEXT decisions, canonical references and a question trail; optionally consult an advisor and chain planning. It keeps implementation outside discussion and presents scoped choices, with an empty-answer retry and fallback (118 onward). These are useful conversation safeguards. The roadmap scope is called fixed near 50, but automatically matching todos can be folded in at 351-358. The helper's matching score is a heuristic, not user authorization to expand scope.

Entry and authority: `--power` branches at 160-163 before the ordinary existing-context and blocking checks. Auto initialization says to skip existing context near 166, while the later existing-context branch chooses update near 211. Semantic self-answers to blockers are not proof that a filesystem, account or runtime blocker has been removed. Auto decisions at 713 onward are model-selected defaults; the later locked decision IDs and question trail must not turn these into historical human choices. The requested single pass and the separately loaded default maximum of three discussion passes also need one explicit control contract.

Provenance and recovery: the checkpoint stores questions and answers but lacks a bound actor, automatic/manual selection origin, source revision, input digest, attempt owner or lease. The advisory output may have missing cells filled and rationales rewritten around 576-582, so generated additions need their own provenance. Previously locked context can include prior automatic choices. Reading a canonical reference or merely confirming its existence near 786 are different levels of evidence. Directory creation near 868 does not visibly rebind an initially null phase_dir before its later use. Deleting the checkpoint before the commit at 1061-1073 creates a recovery gap when the commit helper returns false. An unconditional committed message is not a checked receipt.

Supporting: phase initialization returns nullable paths and discovers existing artifacts (s05); config getter returns raw configured values and errors for absent fields (s07); todo matching uses lexical scores and a short body slice (s10); the direct skill caller is s11. Model resolution (s22) chooses aliases or overrides, with no observed capability certification. The project-wide auto-chain flag is not a session-owned authorization token. A downstream PHASE COMPLETE string cannot supply missing acceptance evidence.

Zeus adaptation: preserve explicit questions and canonical decision references, but store auto recommendations separately from signed human decisions. Bind resumable checkpoints and context proposals to PG attempt IDs and immutable source hashes. Promote only approved definitions into Git. Unknown: all advisor/runtime paths, interruption recovery, model qualification and real human acceptance remain unexecuted.

## f02

`get-shit-done/workflows/do.md`, full lines 1-104.

This is a natural-language router, not substantive implementation. Its first-match route table covers project setup, bugs, research, discussion, planning, execution, reviews, status, todos, tests, shipping and small tasks. Overlapping requests such as a research request about a bug depend on ordering; the ambiguity prompt around 59 is a useful defense. Showing a selected route is not necessarily the explicit confirmation promised by the purpose/caller. The final dispatch spelling `/gsd-*` near 87 differs from the `kha` route names in the table.

The planning prerequisite excludes a few commands but may be broader than the actual preconditions of independent research or debugging. Calling state load and suppressing stderr is not itself a branch on state existence. The actual state loader returns existence booleans and can return empty state after read failure (s21). Original request text and extracted phase values are forwarded to downstream parsers, whose authority and argument handling are not closed by this router.

Supporting caller s12 promises routing confirmation and uses this workflow; no fresh downstream body reuse is claimed. Zeus should emit a typed route proposal with an explicit target, validated arguments and retained original intent. Dispatch success and task completion must be separate receipts. Route ambiguity tests, command availability, downstream safety and real interaction are pending; no routing command ran.

## f03

`get-shit-done/workflows/docs-update.md`, full lines 1-1153.

Purpose: discover documentation, resolve preservation/update/supplement modes, dispatch document writers, verify claims, repair bounded failures, inspect secrets and commit results. Preservation by default when a question tool is unavailable, surgical fixes and a repair cap are valuable defenses. The advertised six plus three canonical documents do not cover the additional custom gap and per-package queues, so nine is not a stable total-work denominator.

Discovery and queue integrity: the implementation scans root Markdown and a bounded documentation tree, catches read errors, and recognizes the generated marker only in the first 500 bytes (s03). This is not a complete project document census. Existing noncanonical docs are queued before custom canonical path resolution; an overlapping file can have conflicting roles. Queue confirmation at 183 precedes mode resolution even though 285 requires that mode table before confirmation. Directory creation at 249/263 and manifest writing at 291 precede the verify-only branch at 338. Therefore verify-only is not read-only even though the skill caller requires it (s14). Preservation can remove queue entries without a clearly specified manifest update. The fixed manifest temporary path also lacks per-run ownership.

Dispatch closure: the referenced detect_runtime_capabilities step has no defined body in this primary. Wave prompts do not consistently pass the resolved output path; default path references remain even after custom path resolution. The writer contract exposes output_path for custom documents (s02). Custom gap items and per-package work are not consistently represented in the same manifest or verification denominator. Parallel collection explicitly routes to per-package work or commit around 702, and the per-package step routes to commit around 752; the sequential path routes to verification around 805. These named transitions can omit verification, repair and secrets steps despite the caller's stronger before-commit requirement. This is a static control-flow mismatch, not a reproduced bypass.

Evidence quality: verification sets a manifest status to verified at 835/845 before inspecting all claim results. The verifier (s01) checks file existence, text patterns and structural claims; it explicitly does not run the documented commands. VERIFY markers, unsupported source claims, examples and versions can be skipped, and output lacks an explicit skipped denominator. The writer can convert an unprovable claim to a VERIFY marker (s02), after which a later zero-failure result can exclude that claim. Two repair iterations and stopping on regression are useful but do not fix denominator drift. Basename-based verification filenames can collide across directories/packages. Results lack a document digest and attempt identity.

Commit and cleanup: verify-only removes matching verification JSON files near 993, which discards evidence and can affect concurrent work. The grep secrets check suppresses errors and can conflate a grep failure with no matches; printing raw matches can expose the very content being inspected. Paths also need typed argument handling. The default commit file list near 1056 does not cover all dynamically resolved paths. The helper can skip or fail a commit (s10), yet the final summary may say committed based only on config. No command, scan or commit was executed in this review.

Zeus adaptation: one PG manifest with immutable item IDs, resolved path, input digest, output digest, claim denominator and distinct passed/failed/skipped/unknown states. Every route must join the same validation barrier before publication. A generated explanation cannot validate itself. Git stores the approved documentation proposal; PG stores attempts and receipts. Public-content review, actual secret scanner behavior, parallel execution, tests and adoption remain pending.

## f04

`get-shit-done/workflows/execute-phase.md`, full lines 1-1260.

Purpose: load a phase, filter plans, schedule waves, run executors, merge worktrees, handle checkpoints, perform regression/schema/phase verification and advance state. Useful defenses include forcing sequential execution without worktrees, detecting declared overlapping files, incomplete-wave controls, explicit architectural/human-action stops and retaining a human-UAT artifact. Declared file lists are not observed mutation sets, and platform-specific path normalization and ownership still matter.

State and scheduling: configuration is read before the step that says to clear auto-chain state before any config reads. begin-phase can write state before filtering discovers no eligible work. The plan index (s06) infers completion from SUMMARY filenames and does not return the gap_closure property used by filtering prose. Summary presence does not prove verification, and filtering only gap plans can exclude prerequisites from an incomplete-wave check. A pause that proceeds without response is not human authorization. The direct skill caller (s13) promises locking/checkpoint protections that are not established merely by this workflow body.

Ownership and mutation: Task instructions request background work, but the shown call near 333 lacks an explicit background argument. The branch realignment near 359 suppresses rebase errors and proceeds to soft reset, potentially conflicting with the executor's refusal of a dirty worktree (s23). Workers skip hooks; the main hook runs before merging their changes. The comment about unstaged changes accompanies an index check and automatic stash, without a shown restore. Most seriously, line 481 enumerates all noncurrent worktrees instead of run-owned workers. Space splitting, detached-head omission and force cleanup lack a reliable ownership boundary. The deletion test at 519-524 identifies added planning files absent from the premerge tree; this includes genuinely new files, not only resurrected files. Fresh summaries can satisfy that condition. The backup only binds committed HEAD state, not all concurrent/uncommitted work. No destructive action was tried here; this is a direct static finding.

Completion evidence: a missing Task response or selected runtime error string can fall back to a small sample of summary-created files plus a recent matching commit across refs. Those checks do not bind a worker attempt or its actual verification. Progress helpers ignore a per-plan completed assertion and count file names (s20/s21). At 636 the auto path manufactures `approved` for a human-verification checkpoint; the executor repeats that policy (s23). A generated approval is not a person's experienced acceptance. Security and code-review findings can be advisory or continued past. A wave-only run correctly avoids phase completion, but still relies on summary-derived completion.

Before final verification, lines 798-818 resolve all failed parent gap artifacts and move debug records, without a finding-to-fix mapping. This reverses the required evidence order. Regression discovery is bounded, runner selection may permit an empty Jest suite or fallback after a failed runner, and user continuation can leave failures unresolved. Source assertions about passed regression tests therefore are not an executed denominator in this review.

Schema and UAT: s04/s09 show schema checking from declared files, summaries and recent Git message text, not a database operation receipt. A missing phase can yield no drift, inline quoted filenames can miss finite ORM patterns, and text mentioning a push does not prove successful application to the intended database. A skip is explicit but must remain a skip. The generated human-UAT result uses bracketed pending near 1025, while s19 parses an unbracketed word and phase completion checks literal result: pending (s06). Its human verification parser accepts ordinary numbered/bullet/table lines, not arbitrary heading prose. More fundamentally phase complete explicitly returns nonblocking warnings for human work and gaps while updating roadmap/requirements based on files and text (s06). This can describe completion without accepted experience even if formatting is corrected.

Zeus adaptation: PG run-owned worktree leases, exact branch/commit and mutation receipts, expected-base checks, per-attempt verification results, explicit skipped/unknown obligations and human identity on acceptance. Git definitions determine all eight stages; no generated summary, warning-only gate or approval string may substitute for a stage's evidence. Preserve declared-overlap checks as an early warning, not exclusive ownership proof. Full merge safety, real hooks, schema execution, all tests, OS behavior, qualified model delegation and adoption remain pending.

## f05

`get-shit-done/workflows/execute-plan.md`, full lines 1-514.

Purpose: execute plan tasks using inline or delegated patterns, enforce read-first and acceptance criteria, handle deviations/checkpoints, commit per task and update summary/state. The dirty-worktree preflight in the executor (s23), explicit architectural escalation, failing RED before GREEN, per-task criteria and individual file staging are useful safeguards. They are instructions and unexecuted test expectations here, not current operational evidence.

Resume and input contracts: initialization depends on a phase value supplied by context; the workflow later selects the first plan without a summary. Agent tracking removes current-agent-id near 89 before checking whether it exists near 90, making the shown interrupted-agent branch unreachable in that sequence. Global tracking paths have no per-attempt ownership. Pre-extracted interfaces at 128 say not to reread source while read_first at 145 demands fresh reads; a digest-bound source snapshot would resolve the conflict. Segmented agents' no-commit/no-summary instruction and the executor role's normal state-update duties need explicit mode enforcement.

Failure and budgets: broad 401/403 classification as an auth interaction can obscure a policy denial. Deviation rules distinguish local fixes from architectural change, but automatic schema column changes versus schema architecture need an explicit boundary. Node repair (s24) allows PRUNE to skip a task and continue; DECOMPOSE creates per-subtask budgets and in-memory changes without updating the plan definition. Thus a nominal per-task budget is not a demonstrated global bound, and a skipped task is not a passed original obligation. The claimed checkpoint percentages are illustrative prose, not measurements.

Completion and commits: requirements-completed is copied from the plan and all listed IDs are passed for completion even when repair can prune work. The executor's own role repeats that requirement-copying behavior (s23). Summary counts drive progress (s21), and session fields can be absent so record-session returns recorded false. The subrepo helper commits independently, warns about unmatched files and reports aggregate success if any commit succeeds (s10); this is not atomic multi-repo completion. The ordinary helper can return false, and an amend must be tied to the intended commit rather than an assumed preceding metadata commit. Human checkpoints in this workflow wait for a user, which conflicts with execute-phase/executor automatic human-verify approval. External setup omissions are usefully surfaced but remain incomplete.

Zeus adaptation: retain original obligation IDs through decomposition, store each attempt and bounded budget in PG, require evidence before requirement completion, and keep PRUNE as a nonpass outcome. Use per-repository saga receipts and reconciliation rather than a single success boolean. Only approved plan revisions belong to Git. Real RED/GREEN behavior, auth handling, cancellation, subrepo recovery, qualification and human acceptance remain pending.

## f06

`get-shit-done/workflows/explore.md`, full lines 1-139.

This workflow uses one question at a time, reflective summaries, optional research and an explicit choice before creating notes, todos, seeds, requirements or phases. These are good separation points between exploration and action. A proposed 30-second research brief with three to five findings is an instruction, not an enforced timeout or verified source receipt. Selecting an artifact to save does not validate its research claims or make it an approved requirement.

Path/data contracts differ: the artifact table and later write instructions place REQUIREMENTS differently. Todo frontmatter uses title/date/priority, whereas the direct matching helper consumes created/area/files and defaults missing metadata (s10). Slug-only naming can collide, and appending a next requirement ID lacks an observed atomic allocator. The commit flag is used without a locally shown load, and the commit helper may decline. The caller (s16) usefully says to retain partial artifacts and report failures rather than pretend success.

Zeus adaptation: PG captures candidate ideas with author, source, uncertainty and selected destination; human-approved requirement definitions are committed to Git separately. Require unique IDs, canonical paths and checked write/commit receipts. Research execution, citation verification, actual user selection, concurrent ID allocation and downstream planning remain pending.

## f07

`get-shit-done/workflows/fast.md`, full lines 1-105.

This offers a constrained inline path for at most three files and an estimated minute, with no new dependencies or architectural decision. Redirecting expanded work to a fuller workflow is useful. File count and estimated duration are not a reliable risk or authorization classification; existing tests run only if considered applicable, so no fixed verification denominator is established.

The direct `git add -A` near 58 stages unrelated changes and deletions without a shown initial ownership check. This conflicts with execute-plan's individual-file staging rule and bypasses the scoped commit helper. The subsequent STATE log is written after the code commit and may append at EOF rather than into an existing table, leaving the final commit unrelated to the log claim. Shell-interpolated user task text needs safe argument handling. If a task grows after edits, redirect alone does not establish a recoverable handoff. The skill caller (s17) requires honest visible failure, but the workflow's done message still needs a checked commit receipt.

Zeus adaptation: preserve lightweight execution for an authorized bounded diff, with an explicit risk policy and meaningful checks. Record the final commit and PG task receipt together through reconciliation; never stage unrelated user work. No small-task command, test or commit was executed, and actual platform behavior and acceptance remain pending.

## f08

`get-shit-done/workflows/forensics.md`, full lines 1-265.

Purpose: diagnose interrupted or unexpected workflow behavior from bounded Git history, planning artifacts, task metadata and worktrees, then write a report and optionally draft an issue. Labeling hypotheses and redacting user paths are useful. Thirty/twenty-commit windows, three touches of a file, repeated message words and two hours of apparent inactivity are heuristics, not proof of loops, test regressions or abandonment. A worktree being extra does not prove that its owner is dead. Artifact glob shapes can miss normal numbered PLAN/SUMMARY names or archived evidence.

The workflow describes a read-only investigation except its report, but later calls state record-session near 259. That helper mutates existing session fields (s08/s21). The direct caller (s15) also contains inconsistent permissions for state/report/issue persistence. Optional issue creation still requires the user's concrete authorization; the source instructions themselves grant none. Redacting HOME does not cover all absolute paths or secrets. Truncated excerpts and bounded history require explicit denominators. Shell-built issue bodies need literal data handling and a verified destination rather than inferred permission.

Zeus adaptation: reconstruct diagnostics from PG attempt/event receipts and immutable Git references, retain missing intervals and competing explanations, and separate a report proposal from public publication. A diagnostic finding is not a resolution, and a historical test word is not a test result. No live history, task folder, credentials or external issue was accessed; ownership, redaction completeness and real incident reproduction remain pending.

## f09

`get-shit-done/workflows/health.md`, full lines 1-181.

Purpose: inspect planning structure and optionally repair selected metadata, then recheck. The post-repair recheck and refusal to invent a missing phase are useful defenses. The validator (s04) checks Markdown/config/filesystem shape and supplies healthy/degraded/broken-like results, plus an exceptional home-directory guard. These are not runtime correctness or model qualification checks. Its pre-repair warnings are returned until a separate recheck; swallowing some read errors limits certainty.

Repair contracts: config regeneration can discard custom settings; adding validation defaults changes policy. STATE regeneration is limited to missing state in the normal flow, though the helper has backup behavior for a changed existence condition. A stale-task suggestion uses age rather than owner liveness and can suggest deleting all task children even while describing an age filter. This is neither a cross-platform lease protocol nor evidence of safe cleanup. The workflow's example error descriptions also disagree with its detailed table.

The direct skill caller (s18) defines audit, repair and confirmation modes with a recent audit snapshot, and rejects a legacy repair flag. Actual CLI dispatch (s20) only recognizes --repair for health and passes that boolean to the validator. The extended audit/confirmation contract therefore is not established by this helper. Structural consistency checks cannot validate the host's actual task ownership, pending human acceptance or evidence-bearing eight-stage transitions.

Zeus adaptation: read-only health queries over PG runtime invariants plus Git definition validity; repairs must cite a current audit snapshot and use explicit policy/ownership checks. Keep previous settings and expose all changed fields. No repair, original test or task cleanup ran. Destructive recovery, OS behavior, complete callers, human approval and adoption remain pending.

## supporting

supporting.json is the authoritative exact range and byte ledger. Every supporting range was freshly read; none counts as an additional primary body. Full supporting files are only those explicitly marked body_read_complete. Source test bodies read: zero. Bounded literal searches of pinned scripts/tests found no matches for the selected docs/health/worktree workflow terms; that does not prove the absence of differently named tests or installed integration suites.

- s01 verifier and s02 writer: static claim checking, skip semantics and writer output-mode contract. Partial s02 is not a full role review.
- s03 docs discovery: bounded scan and initialization return. Unread middle helpers are not closed.
- s04 verification: key-link text oracle, complete health function and schema-drift command ranges. Other verification entry points remain unread here.
- s05 initialization: execute-phase and phase-operation ranges, nullable paths and artifact existence flags.
- s06 phase index and selected completion ranges: summary-name completion, missing gap property and nonblocking acceptance debt. The unread middle of phase completion is not claimed reviewed.
- s07 config get/set, s08 session update, s09 schema detector and s10 commit/subrepo/todo functions: actual effects and weak textual receipts described above. Unread dependencies, locks and filesystem wrappers remain pending.
- s11-s18 direct skill callers: the invocation contracts of the eight user-facing workflows. These source skills were read as data and were not invoked or adopted.
- s19 UAT parsers: exact accepted syntax and omitted heading forms.
- s20 CLI branches: actual forwarding of commit, schema, config, health and initialization arguments; state update-progress ignores any purported plan completion argument.
- s21 state ranges: existence flags, partial advance-plan logic and filename-derived progress, not task outcome proofs.
- s22 core ranges: config defaults, partial config normalization and model alias/override lookup. Neither credentials nor runtime model capability was inspected.
- s23 executor ranges: dirty-worktree refusal, automatic human-verify approval and unconditional plan-ID-based requirement updates. The rest of the role is not counted as read here.
- s24 node repair: full prose body; retry, decomposition, pruning and escalation with per-subtask budget behavior. No repair was run.

## remaining

This checkpoint completes nine fresh primary body reads, not full transitive implementation/test closure. All original execution/import/collection/probe/network/install counts are zero. No historical or prose PASS, mocked result, approval string, summary file or empty test set is counted as current success. Actual Claude review is the parent's separate work. License, platform validation on Windows/Linux/WSL, qualified model delegation, real human experience, current Zeus equivalence and adoption approval remain false/pending. No operational state, shared coverage, source, tickets, commit or push was changed by this bounded review.
