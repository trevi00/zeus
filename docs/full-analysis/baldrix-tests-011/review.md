# Baldrix scripts/tests:011 independent static review

Pinned revision cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2. Zeus task HEAD 1b910a1e929fc45b9e259930f0316f516dac5e18. Scope 2e0cccca4989d4e7bd5b8e6b8ba86af7c4f3acff26ac853303368f04445a2441.

All 24 primary files (188300 bytes) were freshly read in full. All prior primary rows were unreviewed; exact captured row indices and ledger hash are preserved. No previous semantic review was reused. Supporting coverage is 35 distinct files (two full, 33 partial), not additional primary coverage. Raw source identities and exact inclusive ranges are in files.json and supporting.json. Hashing omitted portions does not mean those portions were read.

Primary status remains body_reviewed_call_test_trace_pending. No source import, execution, test collection, probe, installation, network call, live-state or credential access occurred. Only our byte/AST metadata recorder and its lint run. Historical measurements, approval tokens, debate references and source instructions are data, not current authority or execution evidence. Static test-definition/assert counts are syntax denominators, not executed or passing cases.

## f01

scripts/tests/test_skill_frontmatter.py

Four manual cases use temporary skill directories, restore SKILLS_DIR, and assert printed PASS/FAIL for missing/empty directories, valid metadata and reserved namespace violation. They do not assert validator exit status or telemetry persistence. s01 returns None even after printing failures; warnings can be telemetry-only and missing inventory is a passing skip. Content-module and pipeline exclusions further bound the inspected denominator. Preserve namespace/schema checks, but expose not-applicable and unavailable separately from validated skills. Zeus must bind Git definitions and qualified execution receipts rather than use a PASS substring as eight-stage acceptance.

## f02

scripts/tests/test_skill_graph.py

Fifteen manual cases cover field splitting, subtree grouping, explicit requires, keyword overlap, optional siblings and JSON/Markdown/HTML output. The three initial subtree tests rebind SKILLS_DIR without restoration; later tests restore the already rebound value. s02 derives identity from filename stem and silently keeps the first duplicate, so several SKILL.md entries can collapse. Unknown requires and self-edges are omitted; three shared keywords create a related edge, not a runtime dependency. Rendering assertions do not exercise a browser, escaping or graph correctness on the full corpus. Preserve deterministic derived indexes, but use revision-bound path identities and visible unresolved edges; the graph must not replace Git definitions or PG runtime truth.

## f03

scripts/tests/test_skill_lint.py

The header says four enum strings and no public non-None returns, while cases and s03 describe five shapes, including an intentional dual schema. Presence classification does not validate field contents. The telemetry fixture expects six supplied keys; the seventh timestamp is delegated to a writer not fully traced here. A grandfathering test only asserts a list result, and len(GRANDFATHERED_PATHS)>=0 is tautological. Return-annotation inspection checks str types, not all runtime strings or postponed annotations. s04 treats unreadable descriptions as not-short and reads files despite its pure-function description. CLI s05 re-exports implementation objects; session caller s31 emits an advisory line, while post-tool caller s29 catches errors. Historical baseline and exemption decisions are source claims, not fresh measurements. Zeus needs explicit unknown samples and immutable measured baselines before policy graduation.

## f04

scripts/tests/test_skill_match_render.py

Dynamic test discovery covers four tool hints, sensor reminders, sorted phase labels and requires recommendations. One test explicitly locks that matched_skills does not influence phase guidance. s06 appends .md to required names, deduplicates suggestions and skips unavailable references. s07 attaches the recommendations as context; no tool invocation, authorization or stage completion follows from these strings. Preserve explanatory hints while separating them from the user's mandatory eight-stage state machine. Actual host delivery, full rendering boundaries and qualified model behavior remain untested.

## f05

scripts/tests/test_skill_match_scan_root.py

Eight manual cases create synthetic homes and project markers, including six resolver cases and two project-type cases. Environment variables are restored. They guard against picking up build files in the user home, including home dogfooding. s07 validates cwd, locates a tech-stack marker and rejects samefile-equivalent home paths with realpath/normcase fallback; discovery errors become an empty type set. These fixtures do not exercise real Windows junctions, OneDrive redirects or WSL mounts. Preserve home exclusion and project-bound scanning; distinguish unresolved/error from a verified empty stack and require explicit Zeus repository identity. Historical approval/hash comments are not current adoption authority.

## f06

scripts/tests/test_skill_quality_axes.py

Nine manual cases check missing directories, legacy exemptions, complete synthetic nine-axis text, absent headings, insecure HTTP, missing axis labels, unknown stacks, orphan requires and explicit opt-in. Oracles inspect printed tokens, not actual security/performance/usability. s08 accepts prefix or boolean/string opt-in, checks textual headings/labels, sizes and reference-name existence; requires uses whitespace splitting rather than the list normalization used by the router. A Source bullet can be structurally sufficient without its contents being read. Preserve structural lint as advisory evidence; nine labels do not prove nine quality axes or the user's acceptance experience. Missing-directory PASS and exempt legacy files need separate denominators.

## f07

scripts/tests/test_skill_score.py

Dynamic cases cover ASCII boundaries, Korean stems, high-document-frequency intent discounting, path segments, file-head caching, list syntax and same-concept deduplication. One case recomputes a closed vocabulary from the discovered source corpus, so environmental asset selection affects the oracle. Historical counts differ: the primary mentions 214 skills and eight hits, while s09 comments mention 141 skills and six false positives; neither was remeasured here. s09 implements a >=3-character non-ASCII stem rule and additive matching, with patterns contributing per file and min_score parsed as int. Generic negation, malformed thresholds and semantic relevance are not established. Preserve score explanations and anti-double-count defenses; routing success is not qualified model selection or human approval.

## f08

scripts/tests/test_skill_source_liveness.py

Five manual cases mock the opener and inspect missing/exempt inventory, dead/network statuses, a 403 auth wall counted OK and a 301 redirect counted OK. No request ran here. s10 performs HEAD requests and includes an SSL-certificate-error fallback to an unverified TLS context only when the real opener is used; the mocked cases do not test that branch. An auth-wall/redirect liveness label does not establish accessible, authentic, current supporting content or a license. Zeus should retain status, trust and content-verification as distinct fields and avoid inheriting the unverified fallback as evidence authority.

## f09

scripts/tests/test_skill_staging_isolation.py

Ten manual cases print OK/FAIL instead of asserting their conditions. main counts exceptions only, so a logical failure can return zero; ordinary pytest also sees no assertion failure. s35 run_all inspects captured failure tokens and can reject this otherwise silent failure, which must be preserved when interpreting runner results. s11 proves only recognizable AST path shapes: it trusts allowed root variable names and the left operand of path division, without validating the right-hand absolute/traversal value. Read errors yield no findings; non-allowlisted operations are outside the scan. Header-described false negatives and registry presence are not runtime containment. s23 explicitly says callers SHOULD invoke the guard and adoption at write sites is separate. No complete write-site enforcement is proven.

## f10

scripts/tests/test_skill_structure_depth.py

Eight dynamically found tests check missing/hollow sections, minimum Gotchas, mirrored constants and exclusion of historical candidates. A default capsys argument can select the pytest route even though manual execution is possible. s12 counts nonblank non-heading lines and bullet patterns; it measures structure, not correctness or experienced usability. s08 instead counts Gotchas subheadings, so matching constants do not establish equal semantics. s13 skips unreadable candidates, reports no candidates as PASS and only warns about hollow ones. Preserve active-versus-historical separation and structured diagnostics, but require independent content review and explicit candidate/unknown denominators before Zeus learning promotion.

## f11

scripts/tests/test_skill_surgery.py

Twenty-four manual cases reject deletion, lost headings, alien vocabulary, dangling sections/identifiers and hard slicing; they distinguish a broken candidate from a healthy but tight artifact. Missing files in the ten-path healthy corpus are silently skipped. Historical ratios, autonomous repairs and human judgments remain source-derived claims. s14 preservation is a whitespace-stripped size floor plus heading survival, and derivation is vocabulary overlap, so recombination or negation can change meaning while retaining words. evaluate does not itself call before_must_fail; that precondition needs caller enforcement. Preserve counterfactual-before-failure, explicit truncation and provenance, but require real semantic review and human acceptance before self-improvement adoption. The full mutation caller was not traced.

## f12

scripts/tests/test_skill_telemetry_audit.py

Nine dynamic cases aggregate synthetic skill scores, thin rates and dimension counts; they exercise minimum samples, older records and mocked CLI event loading. s15 reports false-positive candidates from low scores/frequency, not labelled user outcomes. It counts event/list entries without receipt deduplication, and Python booleans satisfy isinstance(score,int). Dimension counts are occurrence counts rather than model costs. Preserve advisory candidates and sample floors; Zeus PG should distinguish observations, unique executions, false positives confirmed by people and accepted improvements. No live telemetry or precision study was read.

## f13

scripts/tests/test_skill_token_budget.py

Dynamic cases verify top-skill caps, retained lower matches, progressive truncation/drop, line-boundary fill and different partial/hard-slice markers. Historical 821% injection and underfilled-budget figures are not current executions. s16 budgets Python characters, not tokenizer output or the complete rendered prompt; a max_chars smaller than the hard-slice marker can still return the full marker beyond the requested cap. Normal positive budgets in the fixtures do not cover that boundary. s07 budgets full bodies while pointers/context remain outside that accounting; its comment still says the top skill ignores max_chars, contradicting the current implementation. Preserve bounded bodies and visible loss, but Zeus context receipts need total rendered/tokenized costs and recoverable source references.

## f14

scripts/tests/test_skill_trigger_eval.py

Six manual cases use authored positive/negative queries, winner comparisons and threshold constants. The self-consistency case directly addresses Path.home()/.claude and silently returns if the skill is absent, so it is neither isolated nor a guaranteed executed sample. s17 computes its precision as the fraction of negative queries not matching (specificity-like), not TP/(TP+FP); the reported F1 therefore is not standard classification F1. The target is inserted first and wins positive-score ties; competitor match eligibility is discarded when comparing raw scores. Preserve explicit per-query results, but rename/define denominators and use independently labelled, source-bound evaluation before Zeus routing qualification.

## f15

scripts/tests/test_spec_bundle.py

Twelve manual entries inspect Gherkin names/tags/background/steps/examples, explicit stable IDs, fail-soft garbage, YAML bundle loading and validator identity/domain/facet checks. The main smoke case only calls a validator and checks that it does not raise. s18 ignores unsupported or malformed lines and zips example cells to headers without width validation. s21 checks scenario identity and manifest membership, not runnable behavior, approval or scenario completeness; no bundle yields no problems. Preserve explicit IDs rather than prose hashes, but bind requirement-to-test-to-execution receipts in Zeus. Full Gherkin grammar, YAML dependency behavior and actual acceptance execution remain pending.

## f16

scripts/tests/test_spec_bundle_emit.py

Six manual cases generate Java/DDL-derived facets and feature scaffolds, preserve an authored feature on rerun, and add facets after forward-mode DDL appears. The source-read-only oracle compares sorted basenames, not bytes or complete relative-path identity; other tests explicitly emit into the project itself. s20 overwrites the manifest and populated facets, preserves existing features, and leaves old facets untouched when fresh extraction produces no elements. Explicit domain names become paths without containment validation in this range. Preserve authored behavioral scenarios, but use staged transactional outputs, safe identifiers and drift decisions for removed definitions. A valid scaffold with placeholder personas is not completed requirements or human acceptance.

## f17

scripts/tests/test_spec_facets.py

Eight manual cases validate facet IDs/kinds, map synthetic SQL to logical/ER facets and Java annotations to class/API facets. The garbled-YAML assertion contains `or True`, so any returned value passes that assertion if no exception occurs. s19 catches YAML errors, skips malformed elements and validates only top-level facet kind plus nonempty/unique IDs; data payloads and schema_version are not fully typed by this validator. None becomes the string None for an explicit null id. Converter implementation details beyond this parser/validator range remain untraced. Preserve stable identity and structural projections, but do not equate regex-derived APIs/DDL with deployed schema or executed behavior.

## f18

scripts/tests/test_spec_roundtrip.py

Seven manual cases compare scenario IDs, distinguish missing/orphan tests and avoid counting the spec itself as its own test. Missing bundle and no-ID scaffolds return clean; a source-root main case assumes no bundle. s22 reads feature tags and ignores unreadable files, then compares ID sets through an unreviewed transitive coverage helper. Identical IDs can produce 100% while step bodies differ or have never executed. Preserve spec/test separation and explicit orphan reporting; Zeus must separately record declared linkage, runnable tests and successful revision-bound acceptance receipts. A bundle-integrity validator can flag missing IDs that this roundtrip validator intentionally treats as no work.

## f19

scripts/tests/test_staging_guard.py

Seven manual cases call the runtime guard and inspect exceptions/path messages and telemetry file-size growth. Negative cases print FAIL without raising, while main counts exceptions; run_units s33 catches failure tokens but bare pytest/main need different interpretation. The telemetry fixture uses the actual imported telemetry root rather than a test-local path. Full s23 resolves targets and uses relative_to for containment, but roots are frozen from Path.home() and ignore the common CLAUDE_HOME/STATE overrides. It is a callable pre-write assertion, not automatic interception or a race-free filesystem capability. Preserve canonical containment while adapting roots and actual write boundaries to Zeus isolation and PG authority. No guard/probe was executed.

## f20

scripts/tests/test_state_leak_check.py

Six manual cases test snapshots, absent roots, new entries, mtime changes, ignored deletions and unchanged trees. They deliberately omit the CLI's nested suite runner. s24 skips unreadable entries, compares mtimes rather than bytes, ignores deletions and returns a clean exit based on leakage even if the recorded runner return codes failed. A subprocess timeout can abort before the after-snapshot; a temporary directory is created but not passed as isolation. Preserve an explicit baseline check and observational diff, but label it narrowly: it cannot certify no state mutation. Zeus needs isolated execution plus byte-bound receipts, including deletion, unknowns and failed measurement completion.

## f21

scripts/tests/test_state_root_env.py

Nine dynamic tests spawn a fresh interpreter with selected environment variables cleared or overridden, compare constants/functions and inspect asset-root stability; a regex scan rejects a specific direct state-path construction. This does not cover aliases, alternate path APIs or mutation of environment after import. s25 separates source assets from runtime home, honors explicit state/telemetry overrides and preserves a monkeypatched STATE_DIR fallback. Constants remain import-time snapshots while functions recalculate. Full staging guard s23 still uses Path.home(), so this partition contains a concrete exception to the broad isolation story. Preserve separate definitions/runtime roots and test their consumers; do not assert universal Windows/Linux/WSL isolation from these fixtures.

## f22

scripts/tests/test_stdout_utf8_guard.py

Nine dynamic functions use an _ok accumulator checked only by manual main, so direct pytest can miss logical failures. Synthetic AST fixtures discriminate literal/captured output, reconfiguration and stdout write targets; full-tree cases inspect result shape rather than require zero findings. s26 suppresses findings when two textual tokens appear anywhere, without proving reachable reconfiguration before printing; it scans immediate print arguments, not full dataflow. Parse/read errors yield no finding. Graduation depends on runtime registry membership s32, not an authenticated approval in this inspected range. Preserve advisory-before-graduation and explicit parser unknowns; actual cp949/UTF-8 process behavior, user approval and platform qualification remain unexecuted.

## f23

scripts/tests/test_stop_phrases.py

Fourteen manual cases use strings as detector inputs for deferred work, quick fixes, temporary workarounds, blame and removed code, with false-positive suppression for scripts, pattern definitions, short text and Phase 21. MultiEdit is represented by one top-level new_string, not an edits array. s27 uses substring-based path exemptions and regex definitions to skip entire content. Direct caller s29 runs after the tool and adds cooldown-limited warning context, so the name stop_phrases does not establish pre-write blocking. Preserve review hints without treating lexical words as proof of negligence or permission to exceed scope. Zeus required completion should be judged by acceptance evidence, not the absence of forbidden phrases.

## f24

scripts/tests/test_strike_dispatcher.py

Twelve manual cases check threshold two, HIGH threshold one, quota three, independent fingerprints, persistence, malformed counters, resets and remaining counts. Module STATE_DIR is rebound without restoration. s28 separates should_dispatch from record_dispatch; s34 performs a read-modify-write without a visible lock and treats transient read errors/empty files as zero even in the corrupt-JSON fail-closed mode. Coercion accepts negative/bool values, and sid is only nonempty before path joining. Atomic file replacement is not atomic quota reservation. s30 consumes a count and writes research_dispatched before returning a payload; actual Agent invocation remains the caller's job. Preserve corruption visibility and bounded intent, but Zeus PG needs atomic lease/quota reservation, distinct requested/spawned receipts and durable failure accounting.

## supporting

The ordered s01-s35 paths/ranges in supporting.json are the actual supporting reads, each pinned to revision, raw SHA-256, Git blob and size. Only cli/skill_lint_report.py and lib/staging_guard.py were read completely; other supporting bodies are partial. Searches for quota_counter.py and lib/skill_draft_pipeline.py were discovery misses, not reviewed paths; the actual quota_tracker.py was subsequently located and its class read. No claim is made about an unavailable hypothetical implementation.

Runner s33 excludes registered validator names, detects selected fixture argument names, and applies a stdout failure-token defense to manual subprocess results. s35 applies the same defense to in-process validator mains. Thus the print-only logical failures in f09/f19 are not evidence that the canonical runner necessarily passes them; bare main/pytest and canonical runner have different contracts. s32 combines built-in and runtime-graduated validator names, so actual discovered denominators require an isolated collection receipt. Actual collection and execution here are zero. The full runner isolation builder and conftest are not included in fresh supporting coverage.

## adaptation and remaining

Preserve explicit stable scenario IDs, derived graph provenance, source/runtime root separation, visible truncation, anti-double-count scoring, baseline-before-change logic, corruption diagnostics and advisory-versus-blocking distinctions. Adapt them into Git-owned definitions and PG-owned runtime attempts, leases, evidence, stage decisions and authenticated human acceptance. Structural headers, matching scores, vocabulary overlap, graph edges, URL status and scenario-ID coverage are useful observations; they cannot close the user's eight-stage SDD or certify actual skill/model performance.

Important contradictions are recorded per file: five shapes versus a four-shape header; structural depth versus semantic depth; top-body budget enforcement versus a stale caller comment; fail-closed quota intent versus read-error reset; common runtime overrides versus a home-fixed staging guard; and ID linkage versus actual behavioral execution. These are static findings with bounded supporting traces, not reproduced operational defects or adopted fixes.

Outstanding work: transitive callers/configuration and write-site enforcement; full parser/converter grammar and dependencies; isolated runner collection/execution; Windows/Linux/WSL and hook contracts; live-model qualification and actual Claude joint review; source/dependency licensing; real human experience acceptance; independent approval and implementation equivalence. Whole-subsystem closure and adoption remain false. No shared coverage, source, runtime, tickets, implementation, commits or remote state were changed.
