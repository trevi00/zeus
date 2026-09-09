# Harness contract tests 005: independent static review

The 15 primary files, 196,677 bytes, were read in full from revision a3f8b3be9a0a389329de6e16a6c7db81782041a3. The initial Zeus HEAD was 2458b8fd73616d4cd28d5e7a2f9a0457c72b9fc4. Exact scope, prior path-ledger rows, raw Git blob identity, bytes, SHA256 and read ranges are in the JSON companions. All prior primary rows were unreviewed. All primary and supporting reads here were fresh; earlier partial supporting appearances are not claimed as new prior primary coverage or semantic reuse. Source execution/import/probe/network/install and live/credential access were zero. The tests contain executable experiments; reading them is not executing them. No historical denied gatewriter probe was retried or replaced.

## f01

tests/contract/test_role_supervisor_contract.py, 1-649. Six main test functions cover supervisor state, process restart, cap controls, idle-window characterization, source token/AST checks and six frozen mutations. Temporary queues and a stub process marker distinguish spawn attempt from request creation; a fabricated guardian token supplies only fixture eligibility. Watermark deletion deliberately restarts queue indexing. Cap-1 versus cap and armed versus unarmed cases are useful paired controls. The idle-request no-spawn expectation is explicitly historical characterization, not a desired permanent invariant. Its source-position assertions cover one function, not every dispatch path. Mutation compilation exceptions count as detection, so those cases do not prove behavioral sensitivity. Five-second marker polling and immediate negative checks do not establish all timing or OS behavior.

s01 validates object watermarks, rejects negatives, limits in-flight requests, keeps opaque queue data out of inline briefs, and advances a durable watermark after append. It nevertheless labels a host watermark as spawned. s02's selected legacy spawn path consumes after Popen; the separate arm path is outside this file's cap fixture. In s02 an unbound run returns _try_arm before the legacy request reader; the whole _try_arm transition was not read here. s03 counts only l2-spawn keys and treats any PASS in a spawn segment as fruit, not final acceptance. Atomic single-file writes do not establish a transaction across request, result, watermark and process lifetime.

Zeus: preserve paired cap controls and explicit opaque-input handling, but place lease/fencing, process-start receipts and consumed/rejected/completed states in PG. Git stores definitions. Role names, fake tokens and a stub argv are not model qualification, actual Claude work, or human SDD acceptance. Full dispatch closure remains pending.

## f02

tests/contract/test_run_marker_halt_contract.py, 1-250. The test creates continue state, calls _mark_halt for cap/safe mode, observes history growth, and retains a continue control. AST checks search required halt reason calls and ensure transient active-session/lease branches do not call the helper. The count of unmarked returns uses proximity within six lines with a ceiling of nine; it is a heuristic, not path-sensitive control-flow coverage. The watchdog predicate is copied into the test and explicitly may drift; the real watchdog was not read or executed here. The historical 48-minute stoppage and 11 ticks are source-reported observations, not this review's measurements.

s02 writes a bounded marker history even if contract diagnostics object; _mark_halt swallows OSError, intentionally separate from human notifications. Safe mode, precheck, daily cap, circuit and token refusal call it in the read ranges. Repeated helper calls do not establish two real scheduler ticks. Missing/corrupt marker data collapses to an empty marker; the test's short history cannot exercise saturation of the ring.

Zeus: record explicit intentional hold reasons with monotonic attempt identity, and independently verify the actual watchdog consumer. Operational halt is separate from SDD completion. PG needs authoritative refusal receipts even if a convenience marker write fails; notification delivery and all return paths remain pending.

## f03

tests/contract/test_sandbox_runner_env_contract.py, 1-254. Synthetic trees would run a Korean/YAML child, raw cp949 bytes, a failing child and an empty suite set. Removing inherited PYTHONIOENCODING prevents one masking effect. The negative encoding control can emit SKIP-AXIS on a compatible environment; that is an unverified axis, not platform success. Parent replacement decoding is partly checked as a source string, and a zero return code from raw-byte output cannot itself prove all output survived. Signature/glob checks do not validate every discovered suite. _body splits on triple quotes and remains representation-sensitive.

s04 retains NOUSERSITE and DONTWRITEBYTECODE while adding the user-site directory to inherited PYTHONPATH. This is not a hermetic environment or a dependency lock. run_suites judges only process returncode: an rc=0 child with zero assertions, declared skip, or printed FAIL can be accepted here although s20/s21 classify those differently. The synthetic successful child has no assertion prefix, exposing this deliberate mismatch in test scope. A nonempty only filter selecting no existing suite returns []; the empty-only set is rejected. Timeout exception handling and promotion callers were not fully traced.

Zeus: bind tests and dependencies to the candidate revision, preserve child/parent encoding separation, and use structured execution receipts with collected/asserted/skipped denominators before SDD verification or self-improvement promotion. Real Windows/Linux/WSL and complete sandbox promotion closure remain pending.

## f04

tests/contract/test_self_qualification_contract.py, 1-151. A self-authored high-severity proposal with nonempty evidence text is ranked above 6.0, then expected not to get auto under current rules. Enabling the disabled autonomy rule must make the loader raise an approved-related error; the unchanged disabled rule remains loadable. The final source-token guardian_home assertion and verify(x,None)=False do not authenticate a person. These are authorization fixtures, not actual approval.

s07 rank multiplies configured source weight by severity and accepts nonempty evidence text; s30 makes high research score 6.0. s05 validates enabled auto rules require approved=True, rejects approve=True combined with that match, and verifies both autonomous stamp and HMAC proof in the read match path. s06 signs candidate ID alone, not candidate content/revision/expiry, and allows GUARDIAN_HOME injection. No key was opened by this review. s09 retains an obsolete comment claiming a design revision is the only remaining blocker, while s05 now independently rejects self-qualification; the enabled=false configuration remains consistent with the safer implementation.

Zeus: preserve external approval authority but bind approvals to exact proposed change, scope and expiry in PG. A high score, evidence string, actor label or candidate-only proof must not replace human SDD acceptance or model qualification. Actual guardian issuance and authority boundary closure remain pending.

## f05

tests/contract/test_session_handoff_contract.py, 1-205. Synthetic ledger/cycle tails, missing/corrupt rows, one failed pending-request reader and empty-open-items fixtures check bounded output and explicit limitations. Heading normalization detects some presentation overlap with re_anchor, not semantic nonduplication or a proof that a new module is justified. Source substring ordering is not actual spawn execution. Corrupt JSON-line survival is narrower than arbitrary malformed record types. The test explicitly says previous reasoning is not transferred.

s10 reads the whole ledger before taking a bounded tail, drops malformed lines, and combines missing/empty/unreadable ledger into one message. _cycles suppresses read errors. _open_items catches some errors silently; its sandbox.pending hasattr fallback can return zero, whereas s04 exposes list_pending. The test forces only the role-reader failure and therefore does not establish its blanket no-silence claim. s11 composes goal/completion/approval sections; s02 appends handoff after re_anchor and continues spawning on composition failure.

Zeus: restore immutable references, pending obligations and uncertainty from PG after compaction; do not claim to restore unrecorded human judgment. SDD stage progress and actual experience evidence need durable provenance, not just headings or tails. Complete pending-item APIs, corruption handling, token-cost bounds and real resumed-session behavior remain pending.

## f06

tests/contract/test_skill_contract.py, 1-174. A valid synthetic SkillFile is contrasted with missing/extra keys, bad names/kinds/IDs/domains/stacks/triggers, boolean priorities, small bodies, broken frontmatter and duplicate IDs/triggers. Empty corpus is not ok; no-frontmatter paths are separately listed and removed from the examined denominator. Router vocabulary scraping is tested both for drift and unreadability. The real audit requires at least 30 examined files; that is a collapse floor, not an immutable whole-corpus denominator, nor proof all eighteen rules received independent mutants.

s12 enforces the recorded file and corpus checks and scrapes a literal marker mapping with a regex; supported source refactoring can still break this mirror. s13 resolves a configured skill root and reads all markdown, but can fall back to home/skills; relative_to(home) assumes the root is inside the supplied home. The contract catalog and actual router body were not read in this partition. This review does not adopt all skills or certify their technical guidance.

Zeus: preserve missing-versus-unparseable distinction, closed schemas and explicit skipped paths. Tie skills to Git definitions and PG delivery receipts for each SDD stage, with content provenance and measured usefulness. Routing grammar alone is neither safe execution nor model qualification.

## f07

tests/contract/test_skill_corpus_smoke.py, 1-80. Synthetic trees test oversize, under-limit, absent cap, cap>=budget and missing skills directory, then assert the real corpus has no violations. Missing skills is intentionally accepted here; this must not be reported as complete corpus validation. Boundaries are compared through formatted block size rather than raw body alone.

s14 reads s29 budget/cap, skips missing frontmatter and YAML parsing failures, and computes an approximate router block. Malformed YAML yielding a nonmapping can still reach .get. cap/budget use isinstance(int), accepting booleans and not requiring positive values. The claim that a top-ranked block always fits depends on actual router formatting/selection and a matching runtime budget, outside the read ranges. The 8,000/6,000 character values are policy seeds, not token or model-context guarantees.

Zeus: preserve bounded delivery and separate corpus membership from size validation. Pin the actual assembler and budget to the SDD invocation receipt; empty/invalid corpus and real model tokenization remain unverified.

## f08

tests/contract/test_skill_eval.py, 1-260. Pure fixtures exercise None denominators, PRF micro/macro distinctions, declaration instance counts, stale/orphan pending lists, self-matching, slice targeting, monolith candidates, mixed-stack masking, axis delivery and recent/unattributed no-hit windows. Real evaluation floors are loose and explicitly permit substantial corpus loss. The telemetry before/after check enters real_state and only counts lines, so this test must not be executed under the current no-live-access assignment. Equal line counts do not prove no content rewrite.

s15 preserves None for unmeasured values and independently reports misses/unattributed cases. Its no_hit uses truthiness and recent=0/negative selects all rows while retaining the requested window label. s16 enumerates pipelines but converts loader SystemExit into a build-fail placeholder stage with no skills; a visible placeholder is preferable to disappearance but does not certify that pipeline. Only selected evaluator setup/result ranges were read; actual router invocation, full threshold catalog and telemetry isolation closure remain pending.

Zeus: separate routing self-match from actual skill usefulness, capability qualification and human experience. Preserve raw denominator and window lineage in PG; Git owns declared skill/stage sets. Regression fixtures support SDD verification but do not replace external or user acceptance evaluation.

## f09

tests/contract/test_source_note_contract.py, 1-214. Loaded source/youtube pipelines are compared for two stages, machine modes, common marker requirements, differing outputs/feed paths and artifact enums. Equal counts plus a few common substrings are not full contract equivalence. Archive prefixes are searched across all pipeline expectations rather than bound to each corresponding gate. Pure source_queue fixtures check already-queued and known/missing verdict eligibility; they do not execute queue append, cap enforcement or malicious-title omission, despite the broader heading. Path existence under the routing check does not build every pipeline.

s19 uses fixed paths and self-assigned source IDs with only marker/source/canary/linkage substring gates. s31 can check must-not rules when configured; the source comment that file_content cannot prove absence is broader than the implementation, although these particular gates use presence only. s17 permits missing/unreadable reachability cache, truncates eligible[:limit] and appends without within-batch dedup. s18 requires a first-line marker while gates search anywhere. safe_name folds and appends eight hex hash characters, which reduces collisions but cannot make collisions impossible as its comment claims; a long folded ID can exceed the subsequent 64-character _ID bound. One a/b versus a-b test is not injectivity proof. Same ID archives overwrite previous content atomically rather than retain versions.

Zeus: preserve external text as data and source-specific identity, but bind source/uptake artifacts and archive receipts to each request and content digest. These two stages are research/connection candidates within the user's eight-stage SDD, not the entire process. Full loader, youtube comparison, schema and archive index closure remain pending here.

## f10

tests/contract/test_spiral_candidate_cut_contract.py, 1-136. Synthetic ranking tests approved-below-cut visibility, unapproved exclusion, above-cut dedup, order and both cut boundaries. A fabricated proof string is only an event fixture. It deliberately tests the pure selector rather than CLI.

s08 selects by s07 latest_verdict, which folds event order without verifying proof, actor or timestamp; the real CLI then uses that selector. The prose that a person already chose the item is stronger than this display predicate. s05/s06 perform stronger checks for arming, so display-approved and authorized-to-arm must not be merged. This does not demonstrate an arming bypass. Revocation/reproposal order, duplicate candidate IDs and full ranking/drop closure remain pending.

Zeus: keep authorized commitments visible outside ranking cuts, but label raw claimed approvals separately from verified human authority. Bind actual approval to content and stage scope in PG; display visibility is not SDD acceptance.

## f11

tests/contract/test_suite_runner_smoke.py, 1-468. The test contrasts pass/skip/vacuous/silent_fail/infra/behavior/timeout classification, synthetic subprocess fixtures, parallel/serial outcomes, schedule order, CLI exit codes, JSON purity, discovery zero, baseline weakening and repeated flaky results. Synthetic good children print an ok line without asserting a proposition: the test proves protocol classification, not truthful assertion execution. The optional SUITE_DEEP branch runs a larger corpus after removing inherited state; its default lowercase skip line is not SKIP-AXIS. Nested CLI calls have no local timeout in several places, relying on an outer runner budget. Reconfirmation keeps unreproduced failures non-green, usefully avoiding blame from one retry.

s20/s21 count stdout/stderr prefixes, treat skip as GREEN for exit purposes while preserving separate status, and discard partial output on TimeoutExpired. summarize.no_verdict excludes skip even though lib.NO_VERDICT includes it; consumers must use the full status/axis data. reconfirm counts all non-GREEN reruns as red, so later infrastructure failures can retain an initial behavior classification; basename maps can collide. s04's returncode-only sandbox runner is a separate, weaker admission surface. Baseline loading, timing cache and all CLI branches remain only partially traced.

Zeus: use structured receipts with suite path/revision, collected/asserted/skipped counts, failures and timeout output. Guard both zero discovery and assertion loss, with human-owned baseline changes. Machine-reported PASS is not actual human SDD acceptance, and historical flaky rates are not current measurements.

## f12

tests/contract/test_tick_encoding_contract.py, 1-152. A minimal em-dash child separates child printing from parent decoding. It removes inherited IOENCODING/UTF8 for that control. On a UTF-8 locale the unverified branch calls check(True) with explanatory text, producing a counted ok line rather than SKIP-AXIS. s20/s21 therefore cannot identify this missing negative-control axis structurally. The reenforce spy checks the environment and returns failure instead of running tick; it is not loop-resumption evidence. The spy portion can still inherit ambient PYTHONUTF8, and the source implementation also preserves it.

s22 sets IOENCODING but inherits the rest of os.environ, checks cwd/unattended/safe mode, and invokes tick with a 25-second timeout. Nonzero/empty output returns None; malformed JSON, timeout and decoding exceptions are not handled within the selected handle body. continue returns a Stop block directive, whereas done/halt/idle stop without blocking. Actual host hook semantics and handler-dispatch failure behavior remain unverified.

Zeus: emit a machine-readable skipped-axis receipt, configure process encoding explicitly across Windows/Linux/WSL, and separate loop stop from completion. A synthetic environment spy cannot qualify a model or prove all eight SDD stages can resume.

## f13

tests/contract/test_topic_reaper_contract.py, 1-225. Pure name/age fixtures reject unrelated topics, hold unknown timestamps and contrast both sides of a one-hour threshold. The solo fixture mocks bootstrap and verifies no deletion; it does not cover a broker. AST checks find a driver call and inventory functions anywhere in a module, not the exact operational path. Temporary inventory writes test None/positive/zero deltas; restoring HARNESS_STATE_DIR by pop loses a prior value. No source test was executed here.

s23 separates pure selection from broker I/O and waits for each delete future, preserving partial failure counts. However the name predicate uses regex.match with a dollar anchor, and newline/nonfinite timestamps are not in these fixtures. Successful dry-run returns before cap application. s02's driver calls cycle directly, while record_inventory is called from s23 main: existence of a CLI inventory caller does not establish scheduled inventory history. The driver writes a time marker even for skipped/failed result dictionaries, deferring retry until its age expires. Exact broker timestamp implementation was not read.

Zeus: preserve fail-closed deletion eligibility and explicit ownership, add PG attempt/result receipts with source-generation and lease revalidation, and distinguish retryable failure from completed recurrence. These controls are operational safeguards; no deletion authority, actual broker success or platform validation is granted by this review.

## f14

tests/contract/test_tradeoff_lint_contract.py, 1-259. Synthetic tradeoff fences require alternatives, reasons, chosen value, registered metric and closed operator; unregistered free source_cmd/extract is rejected. Missing files/fences/catalog or axis remain non-pass. The claimed operator-value mutation test actually compares the engine set and points the reader at a missing home; it does not mutate engine operators. Catalog tests execute each registered command with threshold >=0 if run, so this suite is not a pure linter-only execution. No command was executed here.

s24 parses selected-axis fences and blocks document-owned commands but accepts float-convertible NaN/Infinity and boolean values; semantic relevance and distinctness of alternatives are not established. s28 commands collect Git output without checking the nested git returncode: failure can become a numeric zero. s31 metric threshold records command exit but compares extracted output without requiring exit==0. Therefore PASS plus got under >=0 cannot prove that a catalog command measured a meaningful repository quantity. Registry closure reduces the authority surface; it does not prove nondegenerate measurement.

Zeus: keep reviewed metric definitions in Git, use PG receipts binding command revision, actual exit, unit and collection scope, and separately review the decision's connection to user requirements. Metric registration is not a sound architecture decision or human acceptance. Full downstream monitor, command quoting/OS and catalog authority closure remain pending.

## f15

tests/contract/test_uptake_routes_contract.py, 1-285. Real route/schema text checks, synthetic missing/inviolable destinations and restored route tables test guidance consistency. The direct write-boundary comparison matches exact normalized path strings, not descendants, roots, modes or symlinks. Source word occurrence checks for schema fields/values and pipeline references do not prove runtime validator invocation or policy enforcement. The assumption that non_curator==0 proves no unauthorized writing is unsafe: created_by is metadata, and a legitimate human-authored lesson is not intrinsically a violation. digests_waiting>=1 ties success to residual data rather than an immutable contract denominator.

s25 classifies only one discovered descendant for directories; an empty directory or classification-failure string is not in CLOSED_GRADES and can appear reachable. This is patch grading, not the full runtime write decision. s27 explicitly denies direct lessons writes and allows collaboration questions, while s26 guides proposals into quarantine and acknowledges missing crystallization. Its audit permits omitted provenance fields and some list-valued metadata; a creator label is not an authenticated identity. Current ontology schema/indexer bodies and runtime write-boundary evaluator were not read here, so their equivalence is pending.

Zeus: keep proposal, validated learning and activated skill distinct, with authenticated human acceptance and evidence provenance in PG and definitions in Git. Quarantine count is not learning uptake. The user-defined eight-stage SDD governs promotion; guidance, directory existence and source labels do not grant authority or qualify models.

## supporting

supporting.json records 32 source paths, exact read ranges and hashes. Five configuration/pipeline files were read in full; 27 supporting paths are partial. None adds primary coverage. Every numbered primary section lists the direct supporting IDs relevant to that analysis in files.json. Supporting references describe only these actual ranges; source symbol searches were navigation, not additional full-body review.

No prior semantic report replaced source reading. The frozen path-ledger row and hash preserve prior primary status. Prior partial appearances of test_role_supervisor_contract.py do not reduce or inflate this task's full fresh read denominator. No original source body is reproduced in these public artifacts.

## limits

Body review is complete for this bounded partition; call/test/authorization/transition closure is not. Unread supporting regions, the actual watchdog, guardian authority, full router/config catalog, broker timestamps, schema/indexer and runtime write evaluator remain explicitly pending. No suites were collected or executed. Historical PASS/approval/incident counts are source claims only. Actual Claude joint review, license/dependency closure, model qualification, real human experience acceptance, Windows/Linux/WSL verification, whole-system completion and adoption approval are false/pending. The user's eight-stage SDD is a target contract, not equivalent to these upstream two/four-stage pipelines or their string gates. Only this folder's metadata recorder and Ruff were eligible to run.
