# Baldrix test assets: bounded independent static review

Pinned revision: cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2. Partition: baldrix:scripts/tests:008. Scope: a91f30a4c9492e6111bd7d29e2757415afa0ff5fdb050098c28674a0d7800292. Task-start Zeus HEAD: 18c91d6aaebf0ee2105daa822b1027cb73dcab44.

All 26 primary bodies (194042 bytes) were freshly read. The captured prior ledger marks all 26 unreviewed; no prior semantic review substitutes for this read. Supporting evidence is 35 distinct files: two complete bodies and 33 partial bodies. Exact original paths, inclusive line ranges, raw SHA-256, Git blob identity, byte counts and prior ledger bindings are in files.json, supporting.json and prior-ledger.json. Supporting files are not additional primary coverage.

This is body review with direct trace ranges; primary status remains body_reviewed_call_test_trace_pending. No source was imported or executed. No pytest collection, manual main, hook, mutation, network request or probe ran. Static AST counts in files.json count syntax, not evaluated assertions, parametrized cases, passing tests or successful host operations. Historical success comments and self-authored approval fixtures are source claims only.

## f01

scripts/tests/test_mock_doc_drift.py: five manual TESTS exercise a temporary Git document commit, unchanged documents, an uncommitted edit, missing attestation, missing SHA and warning-only main behavior. Git-unavailable branches return early and can subsequently be labelled OK by the manual runner. The comment about a bad or non-ancestor SHA is not a corresponding executed fixture assertion; the missing-SHA case does not establish that boundary.

Direct validator s01 compares the attested SHA with HEAD and working/staged document changes. It does not prove the attested commit is an ancestor in the reviewed range. Any qualifying document change can clear drift without proving feedback was understood or applied. Some command errors yield undetermined or are ignored; undetermined is reported as a nonblocking result. Preserve advisory drift detection, but require revision-bound human feedback and acceptance receipts for Zeus's review stage. Git availability, malformed history and actual runner interpretation remain unexecuted.

## f02

scripts/tests/test_mock_review_skip.py: five manual cases distinguish document-plus-code progression without attestation, matching-root attestation, document-only changes, no Git and warning-only behavior. Git-dependent early returns can be counted as OK. Temporary module log-path rebinding is not fully restored by the test itself.

Validator s02 accepts a historical matching Git-root stage attestation in the inspected range; actor identity, current revision, expiry and feedback closure are not established. Malformed lines are ignored. This is a reminder against skipping review, not evidence that an authorized person reviewed the current mock. Zeus needs authenticated, revision-bound acceptance and an explicit policy for missing evidence. No interactive review or Git scenario was executed here.

## f03

scripts/tests/test_mock_review_stage.py: eight manual entries check stage parsing, a nonempty id, optional=true, no output, designer ownership, incomplete status and ordering before generation. One entry loops over three stack overlays. The pytest autouse fixture pins real skills assets; the manual main does not invoke pytest fixtures. Import-order flake comments remain historical.

Picker s03 treats an existing output or nonempty source directory as completion evidence for applicable stages, while optional-stage traversal and next-index selection are separate heuristics. Configuration s35 declares mock review optional and carries prose about interaction, incorporated feedback and named stakeholder approval. That prose does not become an enforced human-acceptance receipt. The user's required eight-stage SDD must not inherit optional mock review or file-existence completion as approval. Other overlays and the complete transition engine remain outside these support ranges.

## f04

scripts/tests/test_model_router.py: 18 manual entries test empty/trivial requests, implementation, architecture/security keywords, length scores, Korean text, model-id mapping, unknown ids, tuples and frozen results. A generic exception is accepted for attempted mutation, rather than requiring a precise exception type.

Router s04 is a lexical score and tier mapping; additive de-escalators can offset stronger indicators. External-jury caller s33 resolves an architect prompt in auto mode and falls back on unknown/failure paths. The fixed model strings and tier labels do not establish current vendor availability, model qualification or successful execution. Preserve immutable reasons and routing provenance, but bind Zeus selection to a qualified model registry and actual run receipts. No current vendor fact or model behavior was verified.

## f05

scripts/tests/test_mutation.py: 11 manual entries use temporary Git repositories and weak/strong calculator tests to distinguish surviving mutants, killed mutants and red baselines. Other cases cover lexical exclusions, deterministic caps, dirty fixtures, time budgets, missing commands/targets and cleanup. Commands use the interpreter basename, so execution still depends on PATH. No mutation ran in this review.

Implementation s05 adds a worktree under a .git-based path, executes a baseline before mutants and retains a no-verdict result for a bad baseline. Preserve that defense against metric inversion. Static concerns: a .git file in linked worktrees may not support the assumed directory layout; joining an unchecked target path deserves containment validation; worktree creation occurs before the cleanup try/finally; removal return codes are not checked. Nonzero mutant commands do not by themselves distinguish a killed behavior from infrastructure failure. These are bounded source inferences, not reproduced defects or adopted fixes.

## f06

scripts/tests/test_mutation_runner.py: five test functions use an _ok accumulator checked by manual main. Under direct pytest invocation, failed _ok conditions need not fail the test function. Deterministic AST operators, compilation, weak/strong suites and restored bytes/backup absence are checked; a compile loop could be vacuous if the generated set were empty. Fixtures disable survivor rechecks and leave temporary directories behind.

Runner s06 mutates a target in place, restores decoded text, and classifies timeout return code 124 as killed. Restoration swallows an OS error before later backup cleanup, creating a recovery concern. The red-baseline response uses a different score key from the successful response; unstable mutants alter the denominator. Preserve baseline-first/no-verdict behavior, but Zeus needs an isolated workspace, durable recovery and explicit timeout/infra outcomes before promoting mutation scores. Default rechecks and actual filesystem recovery remain unexecuted.

## f07

scripts/tests/test_mutation_safety.py: dynamic test discovery injects tmp_path for fixture-taking cases. Lexical examples cover recursive removal, single-file removal, nearby safety text, exclusions, SQL drops, force-with-lease, Docker and file scanning. The destructive command strings are test data. No such command was executed.

Validator s07 returns no findings on read errors and emits at most one finding per line. Nearby approval/dev/anti-pattern vocabulary can suppress a match within a broad radius. This is neither authenticated permission nor comprehensive enforcement; Windows destructive cmdlets and actual shell interpretation are not established by these fixtures. Preserve advisory scanning and safe-command distinctions, but bind Zeus mutation authorization to an actor, exact target and approved operation, with unknown read failures visible.

## f08

scripts/tests/test_narration.py: eight functions use soft _ok checks, fixture graph construction and a fake AskResponse. They inspect rendered repositories/seams/values, unresolved references, reference filtering, pipe parsing and a generated answer containing expected text. No actual LLM request occurs in the mocked path.

Narration s08 grounds by reference membership. A valid reference does not prove that accompanying natural-language claims follow from the referenced fact. The fixture checks dropped unknown references, not adversarial false statements attached to valid references. Preserve explicit citations, but Zeus experience ingestion needs claim-to-evidence validation and provenance before learning promotion. Complete graph extraction, live model grounding and pytest failure propagation are unverified.

## f09

scripts/tests/test_no_degradation_gate.py: five manual cases construct a Probe, supply a secret_scan_clean flag, test absent/dirty candidates and a property that raises. An unused malformed candidate object is not an exercised case. A constructed probe's passed property is not a receipt that a command ran.

Gate s09 coerces values with bool; probe s10 reports success from its constructed state. The fixtures bypass the actual probe builder. Truthy non-boolean values therefore deserve stricter boundary validation. The file title does not establish a quantitative, workload-matched degradation threshold. Zeus should require genuine qualified executions, immutable baselines and explicit evidence types before promoting a learned change. This review did not execute the probe or retry any historically denied operation.

## f10

scripts/tests/test_nodejs_scaffolder.py: six soft-check functions inspect package dependencies/scripts, strict configuration, feature-step generation, pending steps, world-function shape, framework selection and emitted file names. Unknown stacks fall back to the JVM selection in the tested contract.

Scaffolder s11 produces package/configuration artifacts. No npm install, Node process, Cucumber run or first failing test is observed here. Preserve deterministic path and generation contracts, but do not turn emitted files into a runnable-stack or RED-stage receipt. Unknown-stack fallback and generated user-data escaping require further validation before Zeus qualifies the stack. Direct pytest can also miss accumulated _ok failures.

## f11

scripts/tests/test_on_notification_smoke.py: one manual subprocess case would invoke the notification hook with a test payload and assert exit code zero plus absence of ImportError/Traceback. The fixture does not explicitly disable inherited notification configuration, so a configured environment could dispatch. This review did not execute it.

Full hook s12 loads enabled channels and triggers, dispatches and records telemetry. A test notification may be filtered or allowed; unsuccessful delivery can still end with exit code zero. Thus the smoke oracle measures process survival, not message delivery, privacy boundary or exactly-once receipt. Zeus needs isolated fake transports for tests and durable delivery outcomes. Actual host registration/settings and transport behavior remain unverified.

## f12

scripts/tests/test_onboard_stack.py: six manual cases copy core assets, create candidate Go artifacts and mutate module state paths. Candidate expectations are authored from the same fixture artifact. Promotion is blocked without a token or authored flag, then a test manually flips the flag to permit promotion; no independent oracle actually authors or runs the golden test.

Caller s13 checks token equality and structural/authored flags before sequentially copying overlay/stage assets. The inspected path does not run the requested golden pin before promotion. Copy completion and variant registration can differ when source inclusion is disabled. Preserve inert candidate defaults and structural validation, but replace self-authored flags with authenticated human decisions and qualified execution receipts. Zeus Git definitions and PG acceptance should record the exact reviewed artifact revision and partial-copy failures.

## f13

scripts/tests/test_ontology_query.py: five soft-check functions build fake Dart repository graphs, inspect shared values, drift/orphans, determinism and CLI output. The single-seam empty join is a legitimate fixture case. Only the build CLI return code is explicitly checked; later command checks can succeed on text without validating process success.

Graph builder s14 derives edges from seam scans and merges wire values. A blocked seam can contribute declarations while skipping matching/drift edges, without the inspected graph exposing a separate blocked status. Shared enum labels are not runtime compatibility or successful delivery. Keep this ontology a revision-bound derived projection, not the PG runtime authority or human acceptance record. Complete extraction and actual CLI execution remain pending.

## f14

scripts/tests/test_openapi.py: three manual cases inspect printed output for absent specifications, a minimal YAML path and a missing path. They do not assert the validator main return value.

Full validator s15 uses regular expressions, not full OpenAPI schema parsing or HTTP requests. It compares heuristic YAML/document endpoint tokens and domain counts. Failure text can coexist with a None return from main, which normally exits successfully; an output-aware runner is therefore required. Empty target sets print a passing skip message, not API validation. Preserve lightweight consistency hints, but Zeus should distinguish not-applicable, parse error, contract failure and actual service acceptance. Import-time stream reconfiguration also makes pytest environment behavior material.

## f15

scripts/tests/test_operational_metrics.py: 15 manual entries seed directories, log lines, marker booleans, team artifacts and solution Markdown, then check a five-key aggregate and targets. Some parallel records deliberately include escalation or old-file variants. These are synthetic filesystem counts.

Metrics s16 counts directories or nonblank lines without proving successful unique sessions/runs; duplicates or malformed lines can inflate some counters. Marker membership in true values also accepts equivalent Python values such as 1. Read failures become zero rather than unknown. Documentation mentions legacy team paths while the inspected implementation uses the state-team directory. Zeus should count eligible, attempted, executed and accepted events separately from immutable PG receipts, not promote artifact abundance into demonstrated capability or E2E success.

## f16

scripts/tests/test_operator_ledger.py: 24 manual entries cover path/task normalization and hashes, agent paths, header idempotence, conservative defaults, self-only evidence gaps, downstream flags, malformed events and token/reason-based overrides. CLI cases expect distinct missing/wrong/success return codes. Tokens and labels are synthetic authorization fixtures.

Ledger s17 appends without a transaction or lock, then emits the gap event; its default emitter can be a no-op. Reader behavior silently skips malformed records despite a logging comment. Case-folded task hashes can merge semantically distinct input, and hashes do not authenticate a claim. Preserve false downstream/success defaults and explicit evidence-gap classification. Zeus needs authenticated actors, revision-bound approvals, transactionally durable PG events and visible malformed-event handling. Header mtime checks do not establish complete byte integrity or concurrent behavior.

## f17

scripts/tests/test_optimize_baseline.py: four manual tests create synthetic commands, skills, MCP entries, hooks and instruction bytes; check absent baseline, a command-count delta and rendered text. They do not measure token use, monetary cost, latency or quality.

Baseline s18 stores snapshots at one state path rather than partitioning storage by the supplied home identity. Baselines from different homes can therefore mix unless a caller supplies external isolation. Write failure can return a measurement indistinguishable from a persisted snapshot; the last valid line is used rather than the greatest timestamp. Preserve explicit count deltas, but Zeus optimization receipts need source/workload identity, durable-write status and matched actual performance measurements before graduation.

## f18

scripts/tests/test_orchestrator.py: the entire 1063-line primary was read, including all appended test-list groups. It checks session creation/replay, corrupt sidecars, resume decisions, phase events, child links, research quotas/fingerprints, completion decisions, listing order and pane-event merging. Fake booleans, synthetic event shards and helper-return stubs do not establish actual child spawning, evaluator execution or OneDrive behavior. Fixed timestamps coexist with a real sleep in ordering fixtures. Some module constants remain rebound beyond test-local environment restoration; optional monkeypatch arguments affect runner selection.

Orchestrator s19 appends pane events before unlinking their shard and ignores unlink failure; a subsequent merge can repeat events after failed cleanup or a crash. Successful full deletion is the fixture's idempotence case, not exactly-once crash recovery. Completion delegates to s31, where evaluator requirement defaults false; tests of legacy absence must not become mandatory independent evaluation. Insight emission can fail open. Preserve replay and explicit escalation states, but Zeus PG event identity, leases and transaction boundaries must own runtime state. Full engine/caller closure, real parallelism and host execution remain pending.

## f19

scripts/tests/test_ouroboros_e2e.py: two manual tests cover retained AC-tree and wonder behaviors using authored gate booleans, advisory findings, repeated fingerprints and supplied reflection text. Historical removal/approval comments describe past source decisions, not current authorization. The filename does not make these fixture tests a complete E2E run.

AC-tree s20 can approve an empty leaf set under its gate conditions and swallows emitter errors. Wonder s21 increments depth and reports exhaustion, but caller enforcement is needed to prevent continued calls beyond the cap. The fixture checks the cap event at its expected point, not arbitrary post-cap repetition. Writing provided reflection text proves neither learning nor improved outcomes. Zeus needs bounded execution, durable provenance and human acceptance before self-improvement promotion; no such acceptance was observed.

## f20

scripts/tests/test_outpos_guard.py: dynamically discovered tests invoke a hook subprocess on synthetic project/path/content payloads when run. They inspect blocking rules for writes/edits, unsafe imports/HTTP/logging/dependencies and exceptions, plus warning-only rules and aggregation. They do not perform the target writes. MultiEdit support exists in the inspected implementation but is not a corresponding primary fixture axis.

Hook s22 silently allows invalid JSON and emits block decisions with exit code zero; warnings become context rather than denial. Testing a top-level decision field is narrower than proving a host enforces the complete hook permission contract. Rules are project-specific conventions with Windows-shaped paths, not general cross-platform authorization. Preserve clear warning/deny separation, but Zeus needs an explicit policy scope and real host adapter tests. No hook was executed in this review.

## f21

scripts/tests/test_output_schema_audit.py: 12 manual cases distinguish frontmatter presence, XML declarations, missing/empty values, multi-file counts and CLI outcomes. Empty or absent directories can report all covered with zero assets.

Audit s23 tests presence via string conversion and trimming; a structured empty object can appear nonempty after conversion. It does not validate a JSON Schema or validate model output against that schema. Preserve inventory coverage as an inventory metric, including its zero denominator. Zeus must not count declaration presence or an empty set as model qualification, output conformance or completed acceptance. Actual CLI execution and downstream schema consumers remain unverified.

## f22

scripts/tests/test_parser_equivalence.py: three manual tests compare the pinned stage loader with an embedded legacy parser, inspect selected consumer value shapes and assert expected monitoring/requirements configuration. Equality to the old parser demonstrates compatibility, not semantic correctness. A gate-specific zip comparison lacks its own equal-length assertion, although another function checks length/order.

Loader s24 supports particular list and block encodings, returns an empty result on some invalid/unreadable inputs and discards unknown keys. Preserve known compatibility cases, but Zeus's eight-stage contract needs typed, versioned definitions and explicit invalid-input outcomes. Only the specified stage configuration range was separately read as supporting evidence; this is not a claim of full configuration/caller closure or enforced prose gates. No parser was imported here.

## f23

scripts/tests/test_path_delegation.py: seven manual entries check 14 delegated module accessors, regex-scan source for direct home environment access, reload state resolvers and inspect import placement/bootstrap ordering. The regex does not cover all equivalent environment access forms. An ordering condition can be vacuous when searched tokens are absent. Reloaded module constants need explicit restoration beyond restoring environment values.

Paths s25 confirms the inspected centralized home accessor, but the limited range does not establish every delegated module or the full state resolver implementation. Preserve centralized access and explicit configuration precedence; do not call this a proof of exactly one possible authority. Zeus must keep runtime location/identity explicit across Windows, Linux and WSL, with PG runtime authority independent of arbitrary home paths. All 14 transitive bodies and platform runs remain outside completed closure.

## f24

scripts/tests/test_path_denylist.py: ten manual entries cover home-derived prefixes, empty/None fail-closed behavior, a Windows-only case branch and positive/negative names. They do not exercise real symlinks, short-name aliases, traversal or a downstream filesystem write.

Denylist s26 normalizes and resolves paths; existing-Windows long-name handling delegates to a helper outside the read range. Prefix matching lacks a path-segment boundary and can over-deny similarly named siblings. Prefix-construction failures can omit entries. Writeback caller s34 applies the denylist before its allowed-target pattern. Preserve fail-closed empty input and deny-before-allow ordering, but Zeus requires canonical target containment and authenticated write authority. No denial bypass was attempted or validated.

## f25

scripts/tests/test_phase_detector.py: 15 manual tests cover five phase names, Korean/English keywords, multi-phase matches, negative substrings and restricted architecture/refactor terms. Immutable vocabulary membership is the oracle; it is not semantic intent qualification.

Detector s27 combines ASCII boundary rules with Korean substring matching and can return multiple phases. Prompt caller s32 gates telemetry around system-origin handling, but the system-origin classifier body was not read and is not established as authentication. Preserve these hints for routing/explanation. They must not advance the user's eight-stage SDD state, supply missing human approval or qualify a model. Real prompt delivery and complete caller policy remain pending.

## f26

scripts/tests/test_phase_events.py: the complete 27-line wrapper contains zero test_ definitions, so ordinary pytest discovery does not exercise its manual self-check. Main delegates to _self_check and interprets its result. The header's historical assertion count is not an observed current execution denominator.

Phase-events s28 includes the full self-check range: temporary home/state restoration, no-write reads, invalid inputs, round trips, ordering/limits, oversized records, malformed lines and vocabulary checks. Optional autopilot import/attribute failures can be recorded as successful skipped checks; normal output does not necessarily expose those skipped details. Writer os.write is called once without verifying the returned byte count, and fsync failure is ignored while success can still be returned. Preserve bounded records and temporary isolation, but Zeus needs durable receipt semantics and explicit skipped-case accounting. Infrastructure vocabulary agreement does not prove a completed phase transition or current autopilot integration.

## supporting

The exact 35 paths and inclusive read ranges are recorded in supporting.json and read-plan.json. IDs s01-s28 correspond to the direct implementations discussed above; s29 is scripts/tests/run_units.py, s30 is scripts/tests/conftest.py, s31 is scripts/lib/completion_gate.py, s32 is scripts/handlers/prompt/debate_trigger.py, s33 is scripts/engine/external_jury.py, s34 is scripts/lib/writeback_parser.py and s35 is skills/_pipeline/stages.yaml. Each has an independently computed raw hash and Git blob check. Full reads are only s12 and s15; all other supporting bodies are partial. No support hash is a claim of reading omitted lines.

Runner s29 selects manual main for ordinary scripts and a pytest route for detected fixture-taking tests. Conftest s30 changes the pytest environment; it does not run for manual mains. Consequently _ok accumulators checked only by main (f06/f08/f10/f13), pytest-only fixtures, import-time path constants and optional arguments can materially change the effective oracle. Ordinary printed [SKIP] messages are distinct from the runner's explicit suite-skip marker; early returning cases may be counted by a manual script as OK. The wrapper f26 has no pytest tests. Source execution and collection denominators in this review are both zero. Static syntax counts are supplied to make the unexecuted structure inspectable, not to infer passing counts.

## Zeus adaptation and unresolved closure

Git should own reviewed definitions, schema versions and approved policy artifacts. PG should own runtime attempts, leases, accepted transitions, durable evidence references and authenticated human decisions. Filesystem markers, lexical tiers, schema-presence counters, reflection text and synthetic passed flags are useful inputs or derived views; none independently establishes runtime truth, model qualification or human experience acceptance.

For the user's eight-stage SDD, attach evidence to the actual required stage and revision: requirements and mock feedback need human decisions, generation needs isolated build/test receipts, review needs independent qualified evaluation, and acceptance needs the user's real experience. Optional source stages and file-existence shortcuts cannot waive those conditions. Learning/self-improvement must retain baseline identity, unsuccessful attempts, skipped/unknown cases and authorized promotion rather than use only successful artifact counts.

Remaining: transitive call/config/test closure; isolated upstream collection/execution; Windows/Linux/WSL and host hook contracts; real model qualification and actual Claude joint review; dependency/license review; durable crash/recovery and concurrency validation; human acceptance; implementation equivalence and adoption approval. All remain false or pending. No source command, import, probe, install, network operation, live/credential access, blocked-probe retry or shared runtime/coverage/source edit occurred. This bounded checkpoint does not declare the subsystem or overall absorption complete.
