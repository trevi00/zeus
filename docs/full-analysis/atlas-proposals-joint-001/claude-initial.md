I read all 53 primary bodies in full before judging, then traced bounded consumers in the pinned trees. Findings below.

# Read ledger (honest completeness)

**Primary — 53/53 read in full, no truncation.**
- 38 Atlas docs (`baldrix/pinned/atlas/validators/…`): 1 README, 28 artifact cards, 5 concepts, 2 decisions, 2 journals. All are 54–96 lines; each was read whole.
- 15 Harness cards (`harness/pinned/brain/proposed/backlog-*.json`), `chapter-count-off-by-one` → `feed-lang-window-have-no-consumer`. These are small JSON objects with multi-KB embedded strings; each file object was read whole in one call.

**Scope identity.** `scope.json` lists exactly 38 baldrix + 15 harness = 53, and every path resolved in the pinned trees. I matched by **path only**. I did **not** verify `pinned_sha256`/`git_blob` — that needs hashing, which is execution. The claim "pinned == revision `cbb5c3e…`/`a3f8b3b…`" is therefore **unverified data**, not something I confirmed.

**Corroboration reads (secondary, partial — enumerated deliberately):** `validators/__init__.py` (full, 124 L); `lib/insight_index.py` L88–142 only; `lib/l2_facts.py` L150–184 only; `lib/staging_guard.py` **grep only, never read in full**; line-counts and greps across `scripts/validators/`. Everything else in the pinned trees is unread.

**Not read, per instruction:** no Codex/agent reports, no `files.json`, no prior reviewer output. I read `claude-initial-prompt.txt` and treated it, along with all counts/PASS/approvals in the sources, as data.

**No fixed database key literals appear anywhere in the 53 files.** Nothing required redaction. `private-content-leak.md:21` names the *category* (private API key) without a value.

---

# A. Atlas validators — documentation vs. actual pinned code

The single most important result: **the pinned implementation is available, and the Atlas cards are materially stale against it.**

### A1. The registry concept card is wrong on structure, count, and its own invariant

`concepts/validator-registry-alphabetic-ordering…md:28-62` publishes `VALIDATOR_NAMES` as a static 27-entry alphabetical tuple. Actual `scripts/validators/__init__.py`:

- **L33–71: `_BUILTIN` has 37 entries, not 27.** Ten registered validators are undocumented by any of the 38 cards: `code_blind_proceed`, `context_coupling`, `exit_contract_coverage`, `falsy_zero`, `subprocess_decode_guard`, `skill_structure_depth`, `spec_bundle`, `spec_roundtrip`, `test_depth`, `threshold_registry_locked`.
- **L84: `VALIDATOR_NAMES = _BUILTIN + _graduated()` — no longer a static tuple.** A third enforcement tier ("graduated": advisory→blocking flip, token-gated via `cli/graduate_validator.py`, per L26–32) exists in code and appears in **none** of the 38 cards, including the tier concept card that claims exactly two tiers.
- **The card's own audit query fails on the real tuple.** `…:83-84` asserts `VALIDATOR_NAMES == tuple(sorted(VALIDATOR_NAMES))`. Actual ordering violates it at least twice: `context_coupling` sits at L44 *after* `ddl` (should precede `contract`), and `subprocess_decode_guard` sits at L61 between `skill_frontmatter` and `skill_quality_axes`. The card says at L87 that self-check is "의도적 manual review 영역" — the manual review did not hold. This is a concrete, checkable defect.

### A2. `_graduated()` is a silent enforcement-downgrade path

`__init__.py:74-81` catches bare `Exception` and returns `()`. A malformed `graduation-state.json` therefore **silently drops every graduated (blocking) validator from the registry** with no `[FAIL]`, no warning, no log. The docstring frames this as protecting registry import; the cost is that enforcement loss is indistinguishable from "nothing graduated yet." No Atlas card mentions this failure mode. Useful defense: assert `len(VALIDATOR_NAMES) >= len(_BUILTIN) + expected_graduated`, or make `_graduated()` emit a `[WARN]` on the exception path rather than returning empty mutely.

### A3. The advisory-tier count is off by 12

`README.md:77-80` states "Registered 27 / Advisory-unregistered 1 (skill-source-liveness)". The pinned tree holds **50 validator modules**; 37 registered leaves **13 unregistered**, not 1: `ai_spec_eval_coverage`, `claim_verifier`, `coverage_gate`, `design_slop_a11y`, `doc_code_drift`, `mock_doc_drift`, `mock_review_skip`, `producer_consumer_coherence`, `seam_parity_drift`, `self_model_drift`, `skill_source_liveness`, `stdout_utf8_guard`, `stub_faker_lint`. The tier concept's reasoning is sound; its census is not.

### A4. Layer taxonomy is misapplied on 2 of the 3 non-Layer-A entries

`README.md:71-75` tallies Layer-A 25 / Layer-B 2 / Layer-AB 1. Against pinned code:

- **`harness-bridge-state-block.md:24` claims Layer-B** ("runtime guard … `inspect.getmodule(sys._getframe(1)).__spec__.name`"). A repo-wide grep for `_getframe|__spec__|getmodule` returns **zero hits** in `harness_bridge_state_block.py`. It has `def main() -> None` at L265 and a stdout reconfigure at L45–48 — it is a Layer-A static validator, and it is registered and invoked as `python -m validators.harness_bridge_state_block`.
- **`skill-source-liveness.md:24` claims Layer-B.** It is actually an outbound-network checker: `urllib.request.urlopen(..., method="HEAD", timeout=…)` at L79–95. Not a runtime caller guard at all.
- **`insight-index-importer-whitelist.md:24` claims the single file is "Layer-AB — dual-layer."** It is not. The runtime half lives in `lib/insight_index.py:111-141`, called at `:302` (`append`) and `:419` (`retract`). `decisions/debate-w13-d7…md:58` repeats the error ("Layer-A + Layer-B 둘 다 **단일 산출물**") and then contradicts itself one line later at `:59`. The concept card `layer-a-ast-plus-layer-b-modulespec…md:39-41` gets it right.

So the real Layer-B count in the documented set is **1**, not 2, and the "dual" entry is split across two files.

### A5. Layer-B fail-open is real and undisclosed in the Atlas docs

`lib/insight_index.py:111-134` returns silently — **fails open** — when the frame, module, spec, or spec name is unresolvable (`eval`'d code, REPL, frozen). The pinned docstring is honest about this (L117–120), and L99–102 states plainly that dynamic-import bypass is **out of scope** and "policy is **advisory, not airtight**."

The Atlas concept card presents the opposite posture: `…modulespec-runtime-whitelist.md:23` says "둘 다 통과해야 mutation 진행," and `:41` concedes fail-open only for readers (`query()`). It never discloses that the **mutation-path guard itself** fails open, nor that the source calls the whole policy advisory. Anyone transferring this pattern on the strength of the Atlas card would over-trust it. The pinned code is the more trustworthy document here.

### A6. The strongest defect: W18 D3 "dual-layer" has **no production caller**

The decision (`debate-w18-d3…md:47-50, 61`), the journal (`2026-06-01…md:40`), and the concept (`staging-guard-blocks-non-staged-mutation.md:19-24`) all assert a live dual-layer, "둘 다 통과해야 mutation 이 production 으로 진행."

Pinned code confirms Layer-A (`skill_staging_isolation.py`, 217 L — matching the card exactly) and confirms Layer-B **exists**: `lib/staging_guard.py:51` `StagingInvariantViolation`, `:68` `assert_in_staging`, `:75` `staging_invariant_violation` telemetry. The LOCK's four `D3.layer_b.*`/`D3.telemetry.*` fields are all real.

But a complete grep of `scripts/` for `assert_in_staging|staging_guard` returns 24 hits and **not one is a production call site**: 3 docstring references in `skill_staging_isolation.py`, 3 in `test_doc_code_drift.py` fixtures, 4 in `staging_guard.py` itself, and 14 in `tests/test_staging_guard.py`. The LOCK field `D3.invariant.write_scope` names `skill_draft_pipeline` and `skill_candidate_detector` as the confined writers; **neither calls the guard.** `staging_guard.py:33` gives it away in its own words: callers "**SHOULD** call assert_in_staging(path)."

So Layer-B is a tested library function with zero wiring. The dual-layer is Layer-A plus an uncalled helper. Note the irony worth carrying forward: this is precisely the recurring diagnosis the *Harness* half of this same scope names nineteen times — "선언은 있고 소비자가 없다" — reproduced inside the Atlas validators domain and invisible to it.

Bound on this claim: pinned `scripts/` tree only. Call sites outside the pinned subset are unknown to me.

### A7. LOC fields — 6 of 9 exact, 3 drifted, and the preserved "conflict" is resolved against both sides

Counting physical lines (6/9 exact matches indicate the cards do mean total lines):

| card | card LOC | pinned | |
|---|---|---|---|
| atlas_structure | 176 | 176 | ✓ |
| contract | 244 | 244 | ✓ |
| harness_bridge_state_block | 328 | 328 | ✓ |
| skill_source_liveness | 196 | 196 | ✓ |
| skill_quality_axes | 269 | 269 | ✓ |
| skill_staging_isolation | 217 | 217 | ✓ |
| **atlas_frontmatter** | 157 | **185** | ✗ |
| **collab** | 74 | **68** | ✗ |
| **insight_index_importer_whitelist** | 268 | **281** | ✗ |

The journal at `2026-05-24…md:53` deliberately preserved a source conflict (concept/master = 321, artifact card = 268) and refused to choose. Pinned code says **281 — neither**. The journal's discipline of not fabricating a resolution was right; the honest conclusion now available is that both cited figures are stale.

### A8. `skill_source_liveness` card contradicts itself, and the signature is wrong

`skill-source-liveness.md:53` says **NOT registered** — correct, it is absent from `_BUILTIN`. But `:41-43` still publishes `run_validator('skill_source_liveness')` as a valid invocation. Per `__init__.py:110-114` that raises `KeyError`. The card advertises a call that cannot work. Separately, all cards publish `def main() -> None`; the pinned signature at `skill_source_liveness.py:159` is `def main() -> int` (as is `subprocess_decode_guard.py:201`, `stdout_utf8_guard.py:126`, and several other unregistered validators). The `-> None`/"never raises" contract is a convention the newer validators have already departed from.

### A9. Credit where earned

Three things in this corpus are genuinely well-built and should survive transfer:

- **`stdout-pass-fail-warn-contract…md`** is the strongest card in the set: explicit contract spec, an accurate quotation of `__init__.py` L14–19 (I verified it verbatim), the Windows cp949 → `UnicodeEncodeError` rationale at L53–61, and a failure-modes section that names its own silent-crash mode at L82.
- **The enforcement-tier rationale** (`validator-enforcement-tiers…md:28-29`) — keeping network-dependent, nondeterministic checks *out* of the CI hard gate — is correct engineering, and pinned `skill_source_liveness.py` honors it.
- **The gen-3 frame-globals vacuity catch** (decision `:52-54`, journal `:41`) is a real, correctly-reasoned security finding, and pinned `insight_index.py:94-97` carries the same reasoning in-code. The journal's W1-fabrication catch at `:42` (a planner inventing a writer site that did not exist) is exactly the kind of self-audit that makes a record trustworthy.

### A10. One defense the Atlas set misses entirely

`lib/l2_facts.py:162-183` implements a **second** runtime ModuleSpec whitelist (`_caller_module_name` / `_assert_writer_allowed`, D5 LOCK) that is **fail-closed** — explicitly stricter than L1, which its own docstring notes "fails open on unresolvable callers." This is the better pattern of the two, and no Atlas card documents it. If the dual-layer pattern is transferred, transfer the **L2 fail-closed** variant, not the L1 fail-open one.

---

# B. Harness proposal cards (15)

These are a different genre — self-audit cards, not reference docs — and the epistemic hygiene is markedly higher than the Atlas set. Grouped findings:

### B1. The cards that are strongest are strongest because they retract themselves

- **`completion-verdict-evaporates`** publishes a mid-card correction ("정정 … 중심 주장이 틀렸다"): the original claim "no event says a spiral finished" was false, caused by searching only the `spiral_*` prefix and missing `proposal_resolved` (13 records, writer `spiral_cmd.py:557`, reader `backlog.py:68`). It downgrades itself high→medium **and states the reason**. It then measures the negative direction and finds `spiral_approved` ∩ `proposal_resolved` = **1 of 24** — i.e. approval and resolution are two disjoint orbits, not one lifecycle. That single measurement is the most load-bearing fact in the card and it argues *against* the card's original framing. This is model behavior.
- **`confirmed-without-predicate-measurement`** is the same discipline applied reflexively: it records that the author committed three more instances of the very defect **after filing the card** (`post_filing_observation_2026_09_06`), which refutes its own recommended fix (a skill Gotcha) — "스킬 Gotchas 는 읽히는 것이지 발화하는 것이 아니다." It also declines option (c) on a stated policy ground (SC-5, no LLM in decision paths) rather than on convenience.
- **`core-gates-java-worded`** retitles itself after re-measurement ("어휘는 증상이고 병은 실행부 부재") and records that its first pass mis-defined the predicate and counted 24 instead of 28.

### B2. Two cards carry findings that are directly security-relevant

- **`container-bypasses-write-boundary` (high)** is the sharpest: `write_boundary` is a Claude Code PreToolUse hook, so **any process inside a container is outside it**. Bare Python in the container wrote to `config/policy/` and `scripts/engine/` — both graded inviolable — because a compose mount was `"../..:/harness"`. The author states plainly, "이것은 내가 같은 날 만든 구멍이다." The fix (`:ro` + narrow `state` mount) is verified **bidirectionally** (blocked paths *and* still-working paths), which is the correct acceptance shape. The residual is honest and important: the contract parses compose declarations, **not actual container behavior** — "선언과 실물 사이에 틈이 있다" — and `ROLE_SERVICES` is a hardcoded name list, so a new role service silently escapes the check.
- **`console-audit-blind-to-heart` (high)** finds an audit console structurally blind to the heart-approval channel via two compounding defects: `AUDIT_EVENTS` (`console.py:163-165`) contains 2 names absent from the closed `EVENT_TYPES` enum and **0 of the 4 real `heart_*` events**; and `_ledger_path` (`:169-185`) prefers the binding ledger while heart approvals are written to the canonical one — so during unattended cycles, the only window in which forgery is possible, the panel reads the wrong file. Simulated effect: 0 → 31 heart rows. The card's own quoted docstring is the right principle: "감시가 엉뚱한 파일을 보는 것은 감시가 없는 것보다 나쁘다."

  Two things I want to flag as *strengths* worth importing: (a) editions 4 and 7 render `by` **only when present**, on the explicit ground that absence must not render as "human" — "못 찍힌 것은 '사람이 썼다'가 아니라 '모른다'"; (b) the "하지 않는 것" section refuses to escalate this into a gate and refuses to claim subject-proof, noting 12 candidate mechanisms were measured and rejected. The card states it makes visible without preventing, and does not overclaim.

  **However:** this card's target is `guardian/console.py` — an inviolable, human-hands-only tree — and it ships an applyable patch with `git apply` commands. It says correctly that a human applies it. The `git apply --check` rc=0 result is **reported data I did not and could not verify**; I ran nothing.

### B3. `entrance-has-no-reconfirm` (critical) — the best-argued card, and the one whose severity I'd scrutinize

The asymmetry is real and well-stated: the **reversible** path (`suite_cmd`) reconfirms 3×; the **irreversible** path (`sandbox.run_suites` → ledger `rejected` append under append-only INV-S, *before* parking exists) reconfirms 0×. Notable rigor:

- It stopped citing line numbers after its first version went stale in a day, and says so.
- Its design revision **destroys its own first prescription**: a caller census found `run_suites` is also called by `mutation.py:121,139`, where adding reconfirmation would flip mutation-detection scores' sign (kills counted as survivals). It relocated the fix to `apply_via_sandbox` only, shrinking the blast radius.
- Residual #3 disqualifies its own private probe **twice over** and then states "이 카드의 어떤 주장도 그 프로브에 기대지 않는다."
- It corrects a sibling card's causal attribution (parallelism) as a repository-forbidden inference.

The honest limit, which the card itself leads with: **the failure rate is unmeasured** (1 red / 9 green, with the unattended driver uncontrolled). "critical" is therefore resting on irreversibility × unmeasured probability. I'd hold the severity as *unresolved* rather than accept it — and the card's own residual gives the grounds to do so.

### B4. The YouTube-measurement cluster shows the genre's failure mode: sample growth without disposition

`chapter-count-off-by-one` and `description-chars-counts-markup-not-content` are extraordinarily careful — every number is tagged by *who measured it* (2단 direct pull vs. 1단 self-report), samples are explicitly **not** incremented on re-observation ("재현이지 새 표본이 아니다"), and a proposed limitation is *rejected* on the ground that the number it compared against had already been retracted (`(마)` section).

Their own verdict is the finding: **"표본만 자라고 처분이 안 난다 — 10회차 이후 네 회차째 같은 진단이다."** Fourteen-plus rounds produced n=5 and zero disposition. `reachability.py:153` is unchanged throughout. Both cards independently discovered the same methodological point that generalizes well beyond them:

> The canary must measure the **code**, not the cache. `is_stale()` returns False for `reachable: True` records, so fixing the counter never changes cached values without a forced re-probe.

`description-chars…` explicitly records that it had *failed* to adopt its sibling's canary discipline and then corrects it — "이 발의는 그것을 안 받아 적고 있었다."

Also worth carrying: the 16th-round finding that `+1` is a **vocabulary collision, not a fencepost error** (the regex cannot distinguish a key name from a type name in a renderer list, 393,387 chars apart in the document) — therefore the fix is a structural predicate, not an off-by-one adjustment. And the recognition that `chapters:N` and `+description` are **not two independent sources** but the same text counted twice.

### B5. Resolved cards: two land cleanly, and one prediction was wrong in an instructive direction

- **`contracts-invisible-to-evidence-accounting`** (18 contract suites returning rc=0 with 0 counted assertions — "거짓 그린") resolved to `vacuous 0`, +501 assertions. It records that its own prediction failed: it expected fixes to turn something red; all 17 passed. "가려져 있던 것은 결함이 아니라 증거였다." It also records **disobeying** its own "don't batch 17 into one commit" advice, with the justification. And the guard it built caught **108 false positives** first, because the discriminator was narrower than the real code — "판별기가 실물보다 좁으면 축은 소음이 된다."
- **`contract-verifier-anchor-absent`** is the best-resolved card in the set: its originally prescribed axis (contract-id ↔ verifier-body anchor) was **measured and refuted** — the true verifier C1 scored 0/1 (miss) while an unrelated `README.md` matched 3/9 contracts (false positive). The landed fix instead requires `<path>::<top-level symbol>` with AST symbol-existence checking, verified by an adversarial mutation sweep (all 14 verifiers → README.md: 0 errors before, 14 after; plus non-`.py`, missing-symbol, and empty-symbol variants). Its residual is exactly right: symbol existence does **not** prove the symbol enforces the contract, and it pins that limit as an explicit complement assertion so the axis strengthening will turn it red.
- **`debate-verdict-can-lose-its-lock-target`** escalates itself from n=1 to a census: **55 of 85 verdict events (65%) across 34 sessions lack `ontology_snapshot`** — "이것은 내 실수가 아니라 구조다." Its refusal is the valuable part: do **not** relax the `CONFLICT_SENTINEL` rule, because that rule is what prevents convergence forgery. Correct ordering (harden the reader first, since "지침은 지켜지지 않을 수 있고 판정기는 지켜진다") and an honest migration warning that fail-closed will redden most of 34 historical sessions.

### B6. Weakest of the 15

- **`cohesion-churn-no-recency`** is the only card whose central measurement I can see internally contradicted: the `evidence` field quotes `touching = [f for _, f in history if target in f]` while `triage_2026_08_25.still_true` quotes `touching = [f - {target} for _, f in history if target in f]` for the same lines `:88-95`. One of the two is a misquotation of pinned code. The diagnosis (lifetime churn with no recency window ⇒ already-fixed files re-proposed forever) is plausible and its recommendation (c) is sensibly minimal, but n=1 (`CLAUDE.md` only), and residual #2 concedes no other target was checked.
- **`feed-lang-window-have-no-consumer` (low)** is correct and well-measured (writers at `research_collector.py:99,100,127`; three reader modules extract only `captured_at`/`injection_markers`/`source`/`kind`/`item_id`/`id`), and it explicitly declines to demand deletion. But it has accreted **four** uptake appendices, three of which state outright that they add nothing to the headline claim and leave the canary at 0 and 2. It correctly caught its own 1단's canary as unusable due to a name collision (`skill_eval.py:251`). The card is honest; the growth pattern is the same disposition-starvation as B4.
- **`evaluator-card-read-only-owns-writing-stage`** has a genuine finding (3 pipeline stages give `output.path` to a `risk_scope: read-only` role; `harness_lint.py:1078-1084` only checks declaration↔declaration, so it is green) but its residual concedes it **cannot find what actually determines a spawn's tool set** — declared `Bash` was absent, undeclared `WebSearch`/`WebFetch` were present. Its own residual notes the contract may *permit* the observed spawn, in which case the defect is the pipeline, not the card — and it explicitly does not resolve which. Prescribing a lint rule before that fork is decided would encode an unchosen direction.

### B7. A cross-cutting pattern these 15 establish about the harness

Ranked by how often it recurs across the set: **producers without consumers, and readers that are lenient where gates are not.** `debate-verdict…` names it exactly — "판독부는 관대하고 게이트는 안 관대하다: 읽는 쪽이 None 을 관대하게 통과시키고, 그 관대함의 대가가 다음 세대에 청구된다." The same shape appears in `feed-lang-window`, `contracts-invisible`, `completion-verdict`, `evaluator-card`, and — as shown in **A6** — in the Atlas validators domain itself. That convergence, arrived at from two unrelated corpora, is the most transferable result of this review.

---

# C. Adaptation decisions for the stated Zeus requirements

Mapping findings to what you said you require. Where I have no evidence, I say so rather than infer.

**1. Original 8-stage SDD — the Atlas pipeline set does not fit and must not be lifted wholesale.**
`README.md:37` documents **"Pipeline 0-11 validators"** — twelve stages (`prd, flow, convention, er, logical, ddl, openapi, contract, skeleton, codegen, test, ci`), and `codegen.md:21` hardcodes "파이프라인 stage 8-9 정합." Transferring these imports a 12-stage taxonomy that conflicts with an 8-stage SDD. Decision: take the *validators* individually as checks, discard the stage numbering, and re-anchor `codegen`'s stage reference. Do not treat the 0-11 sequence as the spine.

**2. Real human scenarios / no-mock acceptance — the enforcement surface exists in pinned code but is invisible in all 38 cards.**
This is the most actionable gap for your requirement. The pinned tree contains exactly the validators a no-mock acceptance regime needs, and **not one is documented by the Atlas set**: `mock_doc_drift.py`, `mock_review_skip.py`, `stub_faker_lint.py`, `claim_verifier.py`, `ai_spec_eval_coverage.py`, `coverage_gate.py`, `code_blind_proceed.py`, `spec_bundle.py`, `spec_roundtrip.py`. Decision: for the no-mock requirement, **read the pinned code directly and ignore the Atlas cards** — the cards would lead you to believe this capability does not exist. Note that several of these are in the **unregistered** 13 (`mock_doc_drift`, `mock_review_skip`, `stub_faker_lint`, `claim_verifier`, `ai_spec_eval_coverage`, `coverage_gate`), i.e. **not CI-gating today**. Whether they should graduate is a decision, and the `graduate-validator` token path in `__init__.py:26-32` is the mechanism — but see A2 before relying on it.

The harness half supplies the acceptance *discipline* to pair with this, and it is better than the Atlas half: bidirectional canaries ("한쪽만 재면 '전부 차단'도 초록이다" — `container-bypasses…`), mutation-verified assertions (`contract-verifier-anchor-absent`), vacuous-green detection (`contracts-invisible…`), and the rule that a canary must measure the artifact under repair, not a cache downstream of it (B4).

**3. Git definitions — thin, and one consumer claim is out of scope.**
`git_flow.md` is the only Git-definition validator here: branch pattern `<type>/<scope>-<short>` + Conventional Commits, 177 LOC claimed, sourced from `skills/_common/git-flow.md`. `commit_layer_adjacency.py` enforces 4-tier one-way dependency at commit level. That is the whole Git surface in these 53 files. A sibling card `backlog-gitflow-consumer-zero` (asserting zero consumers for the gitflow declaration) is referenced inside `feed-lang-window…` but is **not in this scope and I did not read it** — the "gitflow has no consumer" question is therefore **open and unreviewed** here, and it directly affects whether `git_flow` is worth transferring.

**4. PG runtime — not covered by anything in this scope.**
`ddl.md`, `logical.md`, `er.md` are static text/diagram cross-checks: `ddl.py` compares `schema/ddl/*.sql` against `.planning/` design docs; `er.py` parses mermaid syntax; `logical.py` checks normalization claims against the ERD. **None connects to a running PostgreSQL instance.** There is no runtime schema verification, no live migration check, no PG-side constraint validation anywhere in the 53 files. If PG runtime acceptance is a requirement, it is **net-new work**, not a transfer. The gap matters because `ddl.md:47` grades a missing index as `WARN` — a purely documentary judgment with no runtime evidence behind it.

**5. Qualified Astra / Sol / Terra transfer — no evidence in scope.**
None of the 53 files mentions Astra, Sol, or Terra. I have **no basis** to qualify or disqualify any transfer to them from this review. That determination requires sources outside this scope and remains entirely open.

**6. Transfer-gating rule I'd apply, given A1–A8.**
The Atlas cards are a **stale index**, not a specification. Six of nine LOC figures matched exactly, which shows they *were* accurate when written and have drifted since — the failure is process (no freshness check), not authorship. Concretely: the pinned tree contains `doc_code_drift.py` and `self_model_drift.py`, both *unregistered*, both tracked for graduation (`__init__.py:93-100`) — the repository already built the detector for exactly this class of decay and has not turned it on. Decision: **do not transfer any Atlas card as authoritative without re-deriving its claim from pinned code**, and treat registering `doc_code_drift` as a prerequisite for trusting this documentation layer at all.

---

# D. Unresolved scope — what I could not settle

1. **Pin integrity unverified.** Path identity confirmed; `pinned_sha256`/`git_blob` not checked (requires hashing). All revision claims remain data.
2. **`lib/staging_guard.py` never read in full** — grep only. My A6 conclusion (no production caller) rests on a complete grep of `scripts/`; call sites outside the pinned subset are unknown.
3. **A6 bound.** I confirmed zero production callers *in the pinned tree*. Whether `skill_draft_pipeline` exists elsewhere and calls the guard is unknown.
4. **Every execution-derived number in the harness cards is unverified reported data** — the 0→31/39 console simulation, `git apply --check rc=0`, the 3761→4317 assertion counts, the 65% verdict census, all YouTube byte counts, `harness_lint` errors=0, mutation-kill results, container write/block results. I ran nothing. Static reading cannot confirm any of them.
5. **`cohesion-churn-no-recency` internal contradiction unresolved** — two different quotations of `cohesion.py:88-95`. Requires reading that pinned file, which is in the harness tree; I did not.
6. **`entrance-has-no-reconfirm` severity unresolved** — the flake rate is unmeasured by the card's own admission; "critical" is not established.
7. **Whether the 10 undocumented registered validators and 13 unregistered ones should transfer** — I read only `__init__.py` and line counts for these, not their bodies. Their fitness is unassessed.
8. **`skill_quality_axes.md:21` cites "ISO/IEC 25010 9축"** — an external standard I did not acquire. Per your constraint, that reference is **unreviewed**; I make no claim about whether the nine listed axes correspond to any published version of that standard, or which version.
9. **The `graduate-validator` token path** (`cli/graduate_validator.py`) is referenced in `__init__.py:31` but I did not read it. Whether the advisory→blocking flip is adequately gated is unknown.
10. **Out-of-scope siblings repeatedly cited by the 15** — `prop:verdict-cache-never-reprobes`, `role-request-idle-window`, `lease-chip-intermittent-drift`, `gitflow-consumer-zero`, `note-queue-item-id-is-write-only`, `page-chars-counts-site-chrome`, `suite-parallelism-changes-verdict`, D8 patch. Several cards' dispositions depend on these. All unread.

**No closure, license, platform, model, human, or adoption approval is expressed or implied by this review.** Findings A1–A8 and B6 are defects I am asserting against pinned code; A6 is the one I would treat as blocking for any transfer that relies on the staging dual-layer. Root and delegated Codex reviews are independent of this output.