I read all 86 primary bodies in full. Report follows.

## Scope actually read

**All 86/86 primary bodies read in full**, from the pinned trees, no partial reads, no truncation:

- **69/69** baldrix SKILLs — `.runtime/absorption/sources/baldrix/pinned/skills/<name>/SKILL.md`, whole file each (longest: `kha-reapply-local-patches` 320 L, `kha-ai-integration-phase` 148 L, `kha-workstream-manager` 116 L).
- **17/17** harness cards — `.runtime/absorption/sources/harness/pinned/brain/proposed/*.json`, whole file each.

Bounded secondary reads (verification only, 3 targeted greps, no full-body judgment drawn from them): `pinned/scripts/lib/debate_rules.py` (lines 11–338 matched), `pinned/config/policy/write-boundary.json` (grade entries). Confirmed `pinned/scripts/lib/debate_rules.py` exists via Glob.

Not read, as instructed: any Codex/agent report, `files.json`, or other reviewers' output. Read/Glob/Grep only; nothing executed, imported, installed, or written.

---

## A. Baldrix — `mutates: no` declared while the body specifies writes

The single largest defect class. **10 of the 17 `mutates: no` skills declare `Write` and name durable file artifacts.**

| Path | Declares | Body specifies |
|---|---|---|
| `skills/kha-audit-milestone/SKILL.md:13` | `mutates: no` + Write | `.planning/v*-MILESTONE-AUDIT.md` |
| `skills/kha-forensics/SKILL.md:12` | `mutates: no` + Write | forensics report **+ STATE.md** |
| `skills/kha-map-codebase/SKILL.md:13` | `mutates: no` + Write | 7 docs **+ commit** |
| `skills/kha-milestone-summary/SKILL.md:13` | `mutates: no` + Write | report + commit + STATE.md |
| `skills/kha-scan-codebase/SKILL.md:14` | `mutates: no` + Write | `.planning/codebase/` docs |
| `skills/kha-session-report/SKILL.md:10` | `mutates: no` + Write | `.planning/reports/SESSION_REPORT.md` |
| `skills/kha-review-code/SKILL.md:13` | `mutates: no` + Write | `{NN}-REVIEW.md` |
| `skills/kha-review-plan-peer/SKILL.md:12` | `mutates: no` + Write | `{NN}-REVIEWS.md` |
| `skills/kha-review-ui/SKILL.md:14` | `mutates: no` + Write | `{NN}-UI-REVIEW.md` |
| `skills/kha-verify-uat/SKILL.md:14` | `mutates: no` + Write/Edit | `{NN}-UAT.md` |

**Exceptions (correctly clean, 7):** `kha-audit-uat-backlog`, `kha-help`, `kha-join-discord`, `kha-list-workspaces`, `kha-phase-assumptions`, `kha-project-stats`, `kha-status` — all `mutates: no` with no `Write` in `allowed-tools`. `kha-audit-uat-backlog` is the notable positive case: a genuinely read-only audit whose Output explicitly says "read-only backlog gap report."

This is a **declaration, not an enforcement**: `mutates` is frontmatter metadata; the write capability is granted by `allowed-tools: Write`. Anything that filters on `mutates: no` for dry-run or CI safety gets a wrong answer for these 10.

**Worst internal case — `kha-forensics/SKILL.md`.** Four statements in one file that cannot all hold: frontmatter `mutates: no` (L12); objective "Forensic report saved to `.planning/forensics/`" (L19); success_criteria "report **written** to `.planning/forensics/report-{timestamp}.md`" (L47); critical_rules "Only write the forensic report **and update STATE.md session tracking**" (L53) — versus Output "**optional** persisted … **only when the user asks** to save" (L62) and Gate summary "**no STATE mutation** in audit mode" (L72). The mandatory-write and the optional-write readings are both present, and STATE.md is both required and forbidden.

---

## B. Baldrix — flags used by the body but absent from `argument-hint`

Where the safety story depends on a flag the invocation contract never advertises:

- `skills/kha-remediate-audit-findings/SKILL.md` — `argument-hint` (L4) lists `[--dry-run]`; the body requires **`--apply`** (L48) and **`--apply --confirm`** (L57) for any mutation. Neither token is in the hint. Additionally the objective calls `--source <audit>` "**which audit to run**" (L26) while Step 1 states "This skill does **NOT** itself run an audit" (L40) — the flag's documented semantics are negated 14 lines later.
- `skills/kha-remove-phase/SKILL.md` — `argument-hint: "<phase-number>"` (L4); Stability section adds `--dry-run` (default) and `--apply` (L39–41) for a **destructive renumber**.
- `skills/kha-complete-milestone/SKILL.md` — `argument-hint: "<version>"` (L4); Stability adds `--dry-run` default / `--apply` required (L142–144) for delete+tag+commit.
- `skills/kha-triage-backlog/SKILL.md` — no `argument-hint` at all; body adds `--dry-run`/`--apply` (L69–71) gating directory **deletion**.
- `skills/kha-submit-pr/SKILL.md` — `argument-hint` is phase/milestone only (L4); `--dry-run`/`--apply` gate `gh pr create` (L36–39).
- `skills/kha-reapply-local-patches/SKILL.md` — no `argument-hint`, no `allowed-tools`; body adds `--dry-run`/`--apply` (L304–306).
- `skills/kha-scan-codebase/SKILL.md` — no `argument-hint`; objective documents `--focus` (L18).

**Exceptions:** `kha-execute-phase` (L46–58) and `kha-sync-docs` (L21–45) do this correctly and explicitly — both carry a "Flag handling rule" stating a flag is active *only* when its literal token appears in `$ARGUMENTS`, and both list every flag in `argument-hint`. These two are the model the others depart from.

---

## C. Baldrix — undeclared / non-existent tools

- `skills/kha-remediate-audit-findings/SKILL.md:12` and `skills/kha-scan-codebase/SKILL.md:10` declare **`Agent`**. Every other agent-spawning skill in the corpus declares `Task` (`kha-debug`, `kha-research-phase`, `kha-plan-phase`, `kha-map-codebase`, `kha-audit-milestone`, …). `kha-scan-codebase` says it "spawns one mapper agent" (L20) with no `Task` declared.
- `skills/kha-reapply-local-patches/SKILL.md` — **no `allowed-tools` block at all**, while `mutates: yes` and the body performs shell detection, three-way merges, and writes merged results over live installed files (L220). `kha-join-discord` also lacks `allowed-tools`, but that one is a static text emission and is harmless.
- `skills/kha-capture-backlog/SKILL.md` and `skills/kha-context-thread/SKILL.md` declare `Write` but not `Edit`, while the bodies require in-place modification — "Add to ROADMAP.md under a `## Backlog` section" (capture-backlog L39) and "Update the thread's status to `IN PROGRESS`" (context-thread L57). With `Write` only, these are whole-file rewrites of ROADMAP.md.

---

## D. Baldrix — cross-file contract mismatches

These are the ones that will actually break at runtime, since one skill consumes another's artifact.

1. **`kha-submit-pr` preflight cannot be satisfied by `kha-review-code`.** `kha-submit-pr/SKILL.md:33` requires `.planning/<phase>/REVIEW.md` **ending with `verdict: pass`**. But `kha-review-code/SKILL.md:29` writes `{padded_phase}-REVIEW.md` (different filename, phase-directory path), and its status vocabulary is severity counts; `kha-remediate-code-review/SKILL.md:51` reads that same file's status as `clean`/`skipped`. No producer in the 69 emits `verdict: pass`.

2. **`kha-remediate-audit-findings` has no producer for its default source.** It reads `.planning/<phase>/AUDIT.md` (L40) and defaults to `--source audit-uat` (L26). But `kha-audit-uat-backlog` is read-only and persists **nothing** (its Output is an inline report). `kha-audit-milestone` writes `.planning/v*-MILESTONE-AUDIT.md`; `kha-audit-planning-health` writes `.planning/audit/health-<ts>.md`. No skill in the corpus writes `.planning/<phase>/AUDIT.md`.

3. **Router `mutates` is inconsistent across three equivalent skills.** `kha-advance` (`mutates: yes`, SlashCommand) and `kha-dispatch` (`mutates: yes`) both declare mutation because they invoke a downstream mutating command; `kha-status/SKILL.md:11` declares `mutates: no` while holding `SlashCommand` and routing to `routed_execute_phase` / `routed_complete_milestone` (L33). Same behavior, opposite label.

4. **`kha-intel-index` names two different artifact sets for one operation.** The spawn prompt at L146 instructs the agent to write `stack.json, api-map.json, dependency-graph.json, file-roles.json, arch-decisions.json`; the Output block at L186 says the refresh produces `files.json, apis.json, deps.json, stack.json` plus an `arch.md` slot. Only `stack.json` is common to both lists. The file also asserts a "machine-readable `.json`" boundary (L201) that its own `arch.md` entry violates.

5. `kha-review-code/SKILL.md` spells the same flag two ways: `--files file1,file2,...` (L27) vs `--files=file1,file2,...` (L41).

---

## E. Baldrix — authoring worklog shipped inside live skill bodies

`skills/kha-workstream-manager/SKILL.md:93–116` ships **24 lines of build-process residue** inside a body the runtime injects into context: a `=== worker-4 meta/infra/docs 완료 ===` marker, Korean boundary notes about *other* skills, a "destructive 스킬 stability 규약 적용 결과" table, a **`## 협의 필요` (needs-discussion) open-defect list**, then `[end] worker-4 rc=0 2026-04-30T10:11:02+09:00` and `DONE`.

`skills/kha-run-milestone/SKILL.md:103` has the same class of leak, smaller: `=== worker-1 lifecycle/phase 본문 fill 완료 ===` as the final line of the Retry/Resume block.

The `협의 필요` list matters beyond tidiness: it is an **unrepaired known-defect register embedded in a shipped artifact**, and it is **incomplete**. It names 4 skills with `mutates` mismatch (`kha-map-codebase`, `kha-scan-codebase`, `kha-milestone-summary`, `kha-session-report`) — my independent read found **10** (§A), so the register undercounts its own class by 6. It also names the `long-running: no` mismatch for `kha-self-update` (L9, runs an npm install) and `kha-sync-docs` (L16, spawns up to 9 doc-writer subagents in waves) — both confirmed against those files. And it names the intel filename mismatch, which I confirmed independently at §D.4.

Two claims in that register I flag as **unverified**: the assertion about `bin/lib/intel.cjs`'s actual implementation, and the `adaptive` profile value in `model-profiles.md`/`settings.md` — neither file is in scope, and I did not open them. Within scope, `kha-set-model-profile/SKILL.md:4` is internally consistent (`quality|balanced|budget|inherit`).

---

## F. Harness cards — schema drift across a nominally uniform card set

Same `kind: "backlog_proposal"`, materially different shapes:

- **`residual` type collides.** Array in `acceptance-coordinate`, `agent-eval-axes`, `architecture-index`, `bash-fence-absent`, `blackbox-stage-names`, `blocker-severity`, `bus-tailer`, `case-folding`; **string** in `agentsmd-counts`, `approval-hardware`, `archive-copies`, `arming-skips-freshness`, `ask-evaporates`; **absent** in `arm-does-not-reopen`, `arming-preview-drop`, `caption-langs` (which folds residual into `evidence`), `catalog-index-pagination`.
- **`relation_to_existing` type collides**: object in `acceptance-coordinate`, `agent-eval-axes`, `case-folding`; **string** in `ask-evaporates`, `blocker-severity`, `bus-tailer`.
- **`slug` present** in 9, absent in 8 (including `acceptance-coordinate`, `agent-eval-axes`, `architecture-index`, `case-folding`, `catalog-index-pagination`).
- **Resolution recorded three incompatible ways**: object `resolved{}` (`acceptance-coordinate`, `arm-does-not-reopen`), date-suffixed booleans `measured_2026_09_04: true` / `partially_resolved_2026_09_05: true` (`ask-evaporates`, `bus-tailer`), and free-form Korean date keys `규명_2026-08-27`, `방향_b_기각_2026-08-27`, `재현_2026-08-28` (`bash-fence-absent`).
- **Korean-language JSON keys** in `agent-eval-axes` (`원천_있음`, `원천_0`, `이미_붉은_축`, `tier1_기계`) and `bash-fence-absent` (`남은_진짜`, `안_잰_것`, `대조군_6`) — un-greppable alongside the English-keyed majority.
- **`catalog-index-pagination` is the outlier**: uses `project` and `scope` instead of `target_project`, carries a machine-specific absolute path `"C:\\Users\\rudtn\\nfx-kr"` (L4), and is the only card whose subject is a different repository entirely.

This is **corroborated from inside the corpus, with a larger denominator than my sample**: `bus-tailer` residual ⑦ measures `brain/proposed` at 128 cards — residual as list 39, string 58, absent 31 — and states plainly that only that one card was normalized and **"나머지 57건은 안 건드렸다."** It also correctly notes the drift is *currently harmless* because the sole consumer, `validators/harness_lint._residual_notes`, slurps raw file text rather than parsing the field. So: a **known, deliberately-deferred latent defect**, not an active one — but it becomes live the moment a structured consumer appears.

---

## G. Harness cards — resolution state vs. machine keys

Three cards carry a `resolved`-shaped key while their own prose says the fix is partial. A consumer filtering on the key gets the wrong answer; a human reading the prose gets the right one.

- **`backlog-arm-does-not-reopen-cycle.json`** — `resolved{}` block at L10–16 with verification. But the evidence says explicitly **"처분 2026-09-01 — 절반 닫힘"** and "② 소각 조건은 **못 고쳤다**" (L8), and the card's own `proposed_fix` (cycle-scoping the idempotency key, L9) is *not* what was done. There is no `partial` marker on the key.
- **`backlog-acceptance-coordinate-not-unique-on-retry.json`** — genuinely resolved (L23–29, mutation 3/3 bidirectional, 156 suites / 4,469 assertions / red 0), and it contains an exemplary self-retraction: `correction` (L22) demolishes its own first diagnosis on two counts. But it retains `"severity": "high"` (L4) with no closed-status field, so a severity filter still surfaces it. The one thing genuinely still open — the commit-trap mechanism — is correctly delegated to `backlog-entrance-has-no-reconfirm.json`.
- **`backlog-bus-tailer-discards-unflushed.json`** — title itself says "미전송 잔량 절반은 `0f1d7f9` 로 닫힘," and the card warns "이 카드는 첫 판 그대로 착지시키면 안 된다." Half-closed, `severity: high` retained. Honest in prose; opaque to a machine.

**Recurring documented pattern — premature closure.** Two cards exist *solely because* a prior proposal was marked resolved too early and the append-only ledger (INV-S) forbids retraction: `backlog-arm-does-not-reopen-cycle` ("그 발의는 … 해소 표시됐는데 **성급했다** — 확인한 것은 derive_state 의 리더뿐이고 배정 경로의 라이터는 안 봤다", L8) and `backlog-arming-preview-drop-opaque` ("**성급했다** — 해소 근거로 적힌 '발의 35건 중 근거 부재 2건' 은 kind 필터를 잘못 건 측정이고 실제는 14건", L8). With §G's three partial-marked-resolved cards, that is five instances of the same failure mode in a 17-card sample.

---

## H. Harness — a claim I verified against pinned source

`backlog-blocker-severity-key-unvalidated.json` is the strongest card in the set, and its line references hold **exactly** at the pinned revision:

- `scripts/lib/debate_rules.py:97` — `canonical_severity(b.get("severity") if isinstance(b, dict) else None) == "HIGH"` ✓ single-key lookup, no alias folding.
- `:129` — `invalidated = declared == "approved" and gen in _critic_high_gens(records)` ✓
- `:268–269` — `canonical_severity` docstring "미상은 UNSPEC (무표지≠사소 — LOW 로 …)" ✓, i.e. the docstring declares unlabeled ≠ trivial while `UNSPEC` ranks **below** `LOW` at `SEVERITY_SCALE` and is the one value that cannot trigger the downgrade.
- The card's own canary condition "안 먹었으면: `:97` 그대로" is **confirmed unfixed** at this revision.

**The grade contradiction is real and verified.** `debate_rules.py:18` declares `등급: 불가침 심장(판정기)` in its own docstring; `config/policy/write-boundary.json:147–148` classifies `scripts/lib/` as **`verifiable`**, while `:35–36` gives `scripts/engine/` `inviolable`. Since `sandbox.classify` reads the policy, the effective grade is `verifiable` — the judge that gates approval downgrades is self-labeled untouchable but is in fact reachable by the automated sandbox+bake path, and the file that *should* be hardened (`engine/debate.py`, where `record_verdict` fail-closes `actor` and `verdict` but lets `blockers` through unvalidated) is the one that is inviolable. The card states this inversion; I confirm both halves independently.

---

## I. Smaller per-file notes

- `skills/kha-ai-integration-phase/SKILL.md` — self-consistent and unusually rigorous. Explicitly declares itself a **staged, non-active candidate** (L22–27), and its Gotchas correctly state that `ai_spec_eval_coverage` proves referential integrity only, "A 1-byte stub passes" (L145). No overclaim. One note: it is the only skill declaring an `agent:` key plus a full staging block, so any tooling that enumerates active skills by directory glob must respect the staging note, which is prose, not metadata.
- `skills/kha-audit-planning-health/SKILL.md` — the best-specified mutation gate in the corpus: explicit two-mode split, `<24h` audit-report freshness requirement, mandatory snapshot, `--confirm`, and legacy `--repair` rejected by name (L58). Correctly `mutates: yes`.
- `skills/kha-debug/SKILL.md` — clean diagnose/fix separation, but `allowed-tools` has no `Write` while the diagnose mode is defined by a `HYPOTHESIS.md` write (L28). The write is delegated to the `kha-debugger` subagent, so this is consistent-by-delegation; note that `Bash` is declared, so "NONE on user code" (L28) is a stated discipline, not an enforced one.
- `skills/kha-reapply-local-patches/SKILL.md` — the `## Retry / Resume` dry-run text says the plan shows "which will **skip**" (L305) and the checkpoint records `status: ok|conflict|skipped` (L315), directly contradicting the file's own CRITICAL INVARIANT "**Never report `Skipped — no custom content`**" (L241, L200). Separately, its snapshot path is `.planning/snapshots/reapply-<ts>/` (L310) although the skill operates on `$HOME` config directories after a GSD reinstall, where no `.planning/` need exist.
- `backlog-architecture-index-absent.json` — the card's `second_finding` criticizes HARNESS-SPEC for a hand-maintained count ("결정 29건") under INV-09, then hard-codes its own counts (58 / 50 / 49 / 108) into title and prose, which will stale identically. Its denominators also shift within the file: title and `why_it_matters` say **108 documents**, `triage_2026_08_25.still_true` measures **110** total `*.md`. Both are defensible (108 = 58 top-level + 50 decisions), but the card never says so.
- `backlog-caption-langs-promises-unreachable-text.json` — exemplary denominator discipline; repeatedly refuses to hide a sample size of 1, then 2, then corrects the *unit* of the denominator (video → first track: "0/19 시도 · 나머지 17 트랙 미시도"), and corrects a double-count (72 → 71). Its own scoreboard line — "발의 등록 이후 baseUrl 실측이 집행된 회차: **0건**" — is the card admitting its primary verification metric has never once been executed across ~14 rounds.
- `backlog-case-folding-depends-on-host-os.json` — correctly scoped as **conditional, not live**: the defect needs posix `normcase` identity **and** a case-insensitive bind mount together, and the card measures that the current containers reference `classify`/`normalize_rel`/`write_boundary` 0 times. Correctly filed as a precondition for session containerization rather than an active breach. Its refusal to propose a fix (residual ⑤: naive `.lower()` creates the mirror-image defect on native Linux) is the right call.
- `backlog-bash-fence-absent.json` — its **title claim is explicitly false at this revision**, and the card says so itself: `재현_2026-08-28` records "제목_주장: **거짓이 됐다**" because `3831fe4` added `_unattended_shell_deny`. But `"severity": "high"` (L6) and the falsified title both remain the card's top-level face. A reader or filter taking the header at face value gets a retracted diagnosis. The still-live remainder is narrower and is correctly isolated in `남은_진짜` (B-2: missing separator in `n.startswith(home)`, 38% sibling-prefix false positives).

---

## Summary judgment

The **baldrix** corpus is broadly coherent in structure — 69 files sharing a stable Output / Failure behavior / Gate summary / Retry-Resume skeleton — but its **frontmatter is metadata that no longer tracks its bodies**. The `mutates: no` class (10/17), the undeclared-flag class (7 files, incl. 4 destructive), and the wrong-tool-name class (`Agent` ×2, missing `allowed-tools` ×1) are all cases of *declaration diverging from specified execution*, and none of them is enforced by anything. The cross-file breaks in §D are the ones with concrete runtime consequence, since `kha-submit-pr` and `kha-remediate-audit-findings` each name an input file that no skill in the corpus produces. The two leaked worklogs are the clearest evidence that this divergence is known and was left in place: `kha-workstream-manager` ships its own defect register, and that register is itself short by six.

The **harness** cards are a different kind of artifact and a much higher evidentiary standard — repeated self-retraction (`acceptance-coordinate`, `blocker-severity`, `bash-fence-absent`), explicit refusal to generalize from n=1, bidirectional canaries with vacuum controls, and consistent separation of "measured" from "inferred." Their defects are not in the reasoning but in the **envelope**: schema drift across a nominally uniform set (§F), and machine-readable status keys that contradict the prose they sit next to (§G). Five instances of premature-or-overstated closure in 17 cards is the pattern most worth acting on, because the append-only ledger makes each one permanent and forces a new slug.

I did not assess whole-analysis quality, licensing, OS/device/model acceptance, or adoption approval, and I formed no judgment from any other reviewer's output.