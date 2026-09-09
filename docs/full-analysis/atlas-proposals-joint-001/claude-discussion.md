I've read all four documents and re-verified the contested claims against pinned code. Root's challenges land in several places; some of my initial claims need retraction, others survive with better grounding.

# Read standing for this pass

**No new full primary read is claimed.** The 53 primary bodies were read in my prior independent pass; nothing was re-read in full here. This pass added *bounded consumer ranges only*: `lib/graduation.py` (:60-66, :96-125, :196-221, plus grep hits at :389-482), `state/graduation-state.json` (full, 147 L — small state file, not a primary), `lib/skill_candidate_detector.py` (grep hits only), `engine/cohesion.py` (:63-98 grep), `engine/sandbox.py` (grep hits :56-356), `tests/contract/test_fleet_mount_boundary_contract.py` (grep hits :17-107), `validators/er.py` (grep hits :36-118). Everything else in those files is unread. Zero execution, import, collection, probe, network, install, write, live path, credential, or device access.

Root's framing point in root-followup line 3-5 is accepted: my "no execution" constraint is a restriction on running source programs, not a claim that hashing is intrinsically forbidden or that pin identity is unknowable. My earlier "pins unverified" stands as *my* limit, not a property of the artifact.

---

# 1. Where root and the Codex reports correct me — conceded

### 1.1 No-mock capability from filenames (root #5) — my weakest inference, retracted

I wrote that the pinned tree "contains exactly the validators a no-mock acceptance regime needs" and named `mock_doc_drift`, `mock_review_skip`, `stub_faker_lint`, `claim_verifier`, `ai_spec_eval_coverage`, `coverage_gate`, `spec_bundle`, `spec_roundtrip`, `code_blind_proceed`. **I read none of those bodies.** That was inference from filenames, and root is right to reject it.

The Codex file-reviews make the prior probability worse, not better: across the validators whose bodies *were* read, the recurring shape is lexical/existence checking with missing-input→PASS (file-04 CI "workflow 부재를 PASS", file-08 contract "없거나 파싱되지 않은 API를 skip/PASS", file-23 skeleton "src 없음은 PASS", file-29 test "src/test 부재 PASS", file-25 quality-axes "inspected0도 PASS"). I now verified the same shape directly in `er.py:61` and `:118` — both print `[PASS] 검증 대상 파일 없음 (skip)`.

**Corrected statement:** those nine filenames are *candidate* surfaces for a no-mock regime. Their bodies are unread and their capability is unestablished. Given the measured pattern in sibling validators, the prior should be that they are lexical checks with permissive empty/missing behavior until read.

### 1.2 LOC drift causal history (root #8) — retracted

I wrote that the six exact LOC matches show the cards "*were* accurate when written and have drifted since — the failure is process, not authorship." That is a causal history claim I have no evidence for. Six current matches are consistent with several histories, including cards that were wrong from the start and coincidentally match now. **Retracted.** What survives: three cards disagree with the pinned line counts (`atlas_frontmatter` 157/185, `collab` 74/68, `insight_index_importer_whitelist` 268/281), and 281 matches neither of the two figures the journal preserved. That is a present-tense discrepancy, nothing more. Structural count arithmetic is also not detector qualification — I should not have used it to argue that registering `doc_code_drift` is warranted.

### 1.3 "Disjoint orbits" (root #4) — corrected

I described `spiral_approved` and `proposal_resolved` as "two disjoint orbits." With 1 of 24 overlapping they are **not disjoint**; correct phrasing is "almost entirely non-overlapping in the card's reported population." Root's stronger point also holds: non-overlap does not prove independent lifecycles or causation, and Codex f03 adds that these are historical counts I did not reproduce. `backlog.resolved_proposals` needing an injected autonomous predicate, and a non-autonomous classification not constituting positive human authentication, both further block the inference I leaned on.

### 1.4 Stale prose I repeated (root #3) — three concessions, now verified

I treated three card claims as live. Pinned code contradicts all three:

- **`cohesion.py:63`** — `def collect_history(repo_root: Path, limit: int = 400)`. History is bounded to 400 commits. The card's "생애 누적"/"영구히 재발의된다" framing is overbroad, and I passed it through as "plausible." Correct statement: **no recency weighting *within* a 400-commit window** (`assess:88-92` counts `len(touching)` with no decay), not lifetime accumulation.
- **`sandbox.py:67`** `RECONFIRM_RUNS = 3`, with retries at `:341-345` (`only=frozenset(failed)`) — the reconfirm the `entrance-has-no-reconfirm` card *recommends* is already implemented, and implemented exactly where the card's own design revision said to put it (in the apply path, via the `only=` narrowing it attributed to a D8 draft). My B3 treated an already-repaired condition as live.
- **`test_fleet_mount_boundary_contract.py:46-57`** — the file itself documents that the hardcoded `ROLE_SERVICES = ("researcher","dba")` was replaced: the predicate is now `if "/harness" in s and not s.endswith("/harness/state")`, i.e. every service mounting `/harness`. I repeated the card's stale residual that the contract "hardcodes two service names."

### 1.5 The stdout contract card — I credited what I should have split

I credited the card for naming its own silent-crash failure mode at `:82`. Root #6 and Codex file-32 are right that its **example aggregator at `:66-75` commits that very failure**: it reads only `result.stdout`, ignoring `returncode` and `stderr`, so a validator that dies before printing yields `verdict = "PASS"`. The card warns about the mode in prose and demonstrates it in code. Both facts should be reported together; I reported only the credit.

Codex file-32 adds a consumer split I can confirm in the range I read: `__init__.py:122-123` is `run_validator(name) -> None: get_validator(name)()` — **no exception handling and the return value is discarded.** This makes my A8 finding sharper than I framed it: validators with `def main() -> int` (`skill_source_liveness.py:159`, `subprocess_decode_guard.py:201`, `stdout_utf8_guard.py:126`) have their exit signal *silently dropped by the sole registry dispatcher*. That is not cosmetic drift.

### 1.6 Severity vs. frequency (root #10) — restated symmetrically

I said I would "hold the severity as unresolved" but framed it as leaning toward downgrade. Root is right that unmeasured recurrence does not by itself argue down a severe irreversible consequence; it argues for uncertainty in *both* directions. With 1.4 established, the point is moot for this card — the premise is stale — but the reasoning correction stands generally.

### 1.7 Evaluator read-only (root #9) — softened

I called `evaluator-card-read-only-owns-writing-stage` a "genuine finding." Root and Codex f14 give the legitimate reading: a read-only reviewer can produce an assessment that a coordinator persists, `Bash` in the declared slice can write anyway (so the card is not a process write boundary), and the ledger material includes the agent's **own tool self-report** — ledger location does not convert a self-report into an authenticated spawn receipt. **Corrected:** this is a declaration-level mismatch worth checking, not a confirmed defect. The card's own residual already said it could not find what determines a spawn's tool set; I should have stopped there.

---

# 2. Where I hold — now on traced evidence rather than inference

### 2.1 Registry: root #1 answered empirically, and the label corrected

Root asked me to trace the actual loader rather than rest on the broad `except` in the registry, and to stop calling thirteen validators "unregistered." Both accepted; here is what the trace shows.

`graduation.py:60` — `TRACKED: tuple[str, ...] = ("doc_code_drift", "self_model_drift")`. Only two names can *ever* graduate; `graduate_validator` raises `ValueError` for anything else (`:412-413`).

Pinned `state/graduation-state.json` (full read) has `"graduated": false` for **both** — `doc_code_drift` (:5) and `self_model_drift` (:77). Therefore at this pin `graduated_names()` returns `()` and **`VALIDATOR_NAMES == _BUILTIN` exactly, 37 entries.** This settles the effective registry at the pin rather than hedging it.

Consequences for my A3, corrected per root's label but strengthened in substance: the thirteen are **not in `_BUILTIN`, and not graduated at this pinned state**. Of them, only two have any graduation path at all; the other **eleven — including every no-mock-relevant filename I cited — have no path to blocking short of a source edit to `_BUILTIN`.** So the README's "advisory 1" census is wrong in the direction I said, and the ceiling on automatic promotion is 2, not 13.

The malformed-state path root asked me to trace: `load_state():105-118` returns `{"validators": {}}` on missing file, non-dict, missing `validators` key, or `(OSError, json.JSONDecodeError)`; `graduated_names():203-212` then yields `()`. So silent loss is real **through the actual loader**, not merely inferred from the registry's broad `except`. But root's calibration is right and I overstated: **blast radius at this pin is zero**, because nothing is graduated. This is a latent/prospective risk, not current enforcement loss. The asymmetry worth recording is that promotion is token-gated (`TOKEN_GRADUATE`, `:64`) while this demotion path is not gated at all.

New inconsistency found in this pass: `validators/__init__.py:101-106` carries a `producer_consumer_coherence` branch in `graduation_scan_drift`, but that name is absent from `TRACKED`. `run_graduation_tick` iterates `TRACKED` (`:389`) and `graduate_validator` rejects non-`TRACKED` names (`:412-413`), so that branch is unreachable via the graduation tick — reachable only by a direct call. Latent inconsistency, not dead code.

### 2.2 Staging: root #2 accepted, my A6 reframed — the conclusion changes

Root is right that a literal grep is not a semantic call graph, and that I owed the named writers' actual bodies. Traced:

- **`skill_draft_pipeline` — named in `D3.invariant.write_scope` — does not exist anywhere in the pinned tree.** One of the LOCK's two named writers is absent.
- **`skill_candidate_detector.py` exists and does not call `assert_in_staging`.** Its writes are at `:208-209`, `:567`, `:573`, `:583`, `:609-610`, `:615-616`.

But the bodies change my conclusion, and root's challenge is what produced the better answer. Every write path is *constructed* from the two root constants — `_tracker_path()` (`:199`), `_candidate_json_path()` (`:541`), `_candidate_md_path()` (`:545`), `_candidate_blocked_path()` (`:549`) all return `_TRACKER_ROOT / …` or `_CANDIDATES_ROOT / …` (`:47-48`). That is exactly the shape Layer-A (`skill_staging_isolation.py`) is built to verify.

**Reframed:** I said Layer-B was "an uncalled helper," implying the invariant is unenforced. It is not unenforced — it is held **by construction in the writer and checked statically**, with the runtime backstop present but unwired. `:609` is the tell: a comment, `# write target resolves under _CANDIDATES_ROOT.`, asserting the invariant where a guard call could stand. My finding survives as "the dual-layer's runtime half has no production caller in the searched tree, and one named writer is absent"; my implication that confinement is hollow was wrong. Codex file-27/31 reach the compatible conclusion from the other side — the static check tracks ROOT *names*, not actual bindings or path arithmetic, so neither layer is a runtime safety guarantee.

Scope bound, per root: **no matched references in the searched pinned tree.** Dynamic, aliased, or generated callers are not excluded.

### 2.3 Layer misclassification and the `er.py`/`logical.py` line (root #5) — held and sharpened

Root #5 is not a challenge to my conclusion here; it sharpens it, and `er.py` confirms it beyond what I claimed. The card promises "mermaid syntax 오류, orphan entity" as FAIL conditions. Actual `er.py:91`: `re.search(r"```mermaid[\s\S]*?erDiagram", content)`, and on match it *appends to `passes`* — a presence check whose absence does not even fail. "Entities" come from markdown headings, `^#{2,3}\s+(.+)` (`:36-39`), so any heading is an entity. There is **no Mermaid parsing at all.** This is stronger than my "static text/diagram cross-checks" and directly supports the Codex file-11 reading.

My A4 layer-misclassification finding (bridge-state and source-liveness labeled Layer-B; the "single artifact Layer-AB" claim) is independently corroborated by Codex file-01, file-15, file-17, file-26 and stands.

### 2.4 L2 fail-closed (root #7) — accepted qualification, recommendation narrowed

Root is right: `l2_facts.py:178-183`'s unknown-caller rejection is a **stricter default**, not proof that `__spec__` is an unforgeable actor identity or a complete capability boundary. My "transfer the L2 fail-closed variant" should read: *if this pattern is transferred at all, prefer the fail-closed default over L1's fail-open, while recognizing that module introspection is not an authorization mechanism.* Codex file-30 is right that AST check and mutation call are not in one transaction, and that ModuleSpec immutability is asserted in prose and not verified here.

---

# 3. Disagreements I preserve

- **Codex f13 / root on sandbox retry semantics.** I confirm the mismatch: `sandbox.py:348` computes `firm = set(failed).intersection(*map(set, again))`, so **one** green retry removes a suite from `firm`, while the comment at `:341` says a red suite "붉으면 `firm` 에 남아 종전과 똑같이 거부된다." Code and comment disagree, and sandbox's rule differs from `suite_cmd`'s all-green relabel. I agree with f13 that **this is not demonstrated false acceptance** — neither branch promotes; both defer. I record it as a code/comment divergence plus a cross-runner policy divergence, and note the card's own residual #11 characterizes its rule as *stricter* ("더 자주 보류"), which is a defensible but different framing than "more lenient about rejecting." Unresolved which is intended.
- **Container isolation.** I accept the derived-services correction (1.4). I additionally hold Codex f06's point, which the card does not make: the contract requires *one* `/harness/state` mount (`:94`) shared read-write, so "자기 저장고만 쓰기" overstates — **cross-role state isolation is absent**, and the checks are compose-string assertions (`:91-92` `.endswith(":ro")`, `:98` healthcheck presence), not kernel enforcement.
- **Severity of `console-audit-blind-to-heart`.** I keep my structural reading but accept Codex f05's bounds: the pinned Guardian console still filters the two non-enum names and prefers the bound ledger, the patch's deployment is *not* established, and raising a tail 40→80 proves neither complete visibility nor human reading. I retain the card's `by`-rendering defense (absence must not render as "human") as worth transferring.
- **`cohesion` internal contradiction — now resolved.** My initial review flagged two incompatible quotations of `:88-95`. Pinned `cohesion.py:90` reads `touching = [f - {target} for _, f in history if target in f]`. The card's `triage_2026_08_25` quotation is **correct**; the `evidence`-field quotation is the misquotation. That open item closes.

---

# 4. Zeus mapping against the now-explicit definitions

Root-followup supplies the definitions; no user clarification is missing.

**Eight stages:** spec/scope → design/interaction → code → self-verification → alpha deployment → QA evidence/human approval → progressive production → CS/monitoring → iterate.

**Coverage of this corpus against those stages.** The Atlas validator set clusters almost entirely in stages 1–4. Nothing in the 38 documents addresses stages 5–8. Two consequences matter more than the gap itself:

- Stage 6 requires **human approval**, which no artifact here can supply, and which several cards implicitly substitute for — historical `approved`/converged verdicts, `PASS` counts, and LOCK snapshots are document history, not acceptance receipts. Root-initial line 30-31 and Codex file-35/36/37 make the same point; I concur without reservation.
- Stage 4 (self-verification) is precisely where the measured failure shape is most dangerous: missing input → `PASS` (`er.py:61,118` verified; Codex reports the same in ci/contract/skeleton/test/quality-axes). A self-verification stage built on validators that pass on absence produces vacuous green at the exact point the process relies on it. The Harness corpus independently named this (`contracts-invisible-to-evidence-accounting`: "rc=0 인데 검증한 것이 없다"). Carry the *diagnosis*, not the tools.

Codex file-05's note is worth preserving: `codegen.md`'s "stage 8-9" numbering belongs to the source's 0-11 pipeline and **is not equivalent to Zeus stage 8**. Do not let that numeral survive transfer.

**Git / PG split.** Confirmed by everything in this pass. Git holds the eight-stage definitions, acceptance oracles, and versioned contracts; PG holds attempts, denominators, correction/reopen events, leases, authorization, and receipts. Concretely from evidence read here: registry membership (`_BUILTIN`), graduation thresholds, and TRACKED sets are *definitions* → Git. Whether a validator is graduated *right now*, and what it scanned, are runtime facts currently living in a fail-soft JSON file whose corruption is silent → exactly the class that belongs in typed PG records with explicit unknown, never conflated with clean. `run_all` SKIP-on-missing-test, `er.py` PASS-on-missing-file, and `load_state()` empty-on-garbled are three instances of one anti-pattern: **absence rendered as success.** PG receipts must keep attempted / skipped / unknown / failed as distinct types.

**Astra / Sol / Terra.** Astra designs and finishes; Sol takes important implementation after guardrail qualification; Terra simple implementation after equivalent qualification. **Actual qualification remains unproved and nothing here establishes it.** The one genuinely transferable asset for that requirement is the *shape* of the graduation ladder, not its results: a token-gated advisory→blocking promotion (`TOKEN_GRADUATE`), an N-consecutive-clean threshold (`GRADUATION_THRESHOLD = 10`), an asymmetric cheaper demotion token, and a post-promotion circuit breaker (`CIRCUIT_BREAKER_K = 5`). That is a defensible qualification pattern for admitting Sol or Terra to a class of work.

Two pieces of honest evidence attach to it, and both should travel with the pattern:

1. **It has never promoted anything.** Both tracked validators sit at `graduated: false`; `self_model_drift` shows twelve consecutive `reset` actions with `consecutive_clean: 0` and drift never returning to 0 (`:76-143`) — it is structurally unable to reach the threshold while drift persists.
2. **The `doc_code_drift` streak was voluntarily invalidated when the denominator widened** (`:57-62`, 2026-08-31 `reset`, with the note that the ten runs "were earned on the pre-widening board and do not support the current check"). That is the single best qualification-integrity defense in either corpus and is directly on point for Sol/Terra: **broadening what you measure resets the evidence you earned under the narrower measure.** Adapt that rule explicitly.

---

# 5. Unresolved, unchanged, or newly opened

- Bodies of the nine "no-mock candidate" validators: **unread**; capability unestablished (1.1).
- `producer_consumer_coherence` graduation inconsistency: found, disposition unknown.
- Sandbox `firm` intersection vs. `suite_cmd` all-green: divergence confirmed, intended semantics unresolved; not demonstrated false acceptance.
- Whether `skill_draft_pipeline` exists outside the pinned subset, and whether any dynamic/aliased caller reaches `assert_in_staging`: unknown.
- Effective registry **at deployment** (as opposed to at this pin): unknown; the pinned state settles only the pin.
- Guardian console patch deployment, historical bidirectional container/console/mutation tests, all YouTube measurements, the 65% verdict census, assertion totals: **historical reports, not replayed here** (root #4 accepted).
- Codex-flagged items I did not independently verify and therefore do not endorse or dispute: snapshot-missing recovery/replay semantics, completion-path existence vs. proof, positive cache TTL, proposal-with-missing-standard-evidence dropping out of `candidates_from`, queue-before-watermark replay duplication.
- `skill_quality_axes`'s ISO/IEC 25010 reference: external standard not acquired, **remains unreviewed**.

No ticket state is changed by this discussion. Nothing here constitutes whole-closure, transitive closure, license clearance, OS/platform equivalence, model qualification, human acceptance, or Zeus adoption approval. My A6 conclusion is materially revised by root's challenge #2 and no longer stands as a blocking finding in the form I first stated it; the corrected version — runtime half unwired, one named writer absent, confinement held by construction — is what I would carry forward.