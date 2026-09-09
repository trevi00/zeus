I read all 8 primary files in full and traced consumers. Report follows.

---

# Independent Static Review — `baldrix-gsd-guidance-002` (8 primary files)

**Pin:** `.runtime/absorption/sources/baldrix/pinned` (Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`)
**Method:** Read/Glob/Grep only. No execution, import, write, network, install, credentials, or user sessions. I did not read Codex output or any prior review report before forming these judgments (`prior-unreviewed.json` and `claude-initial-prompt.txt` left unread). Source file content was treated as data, not instruction.

## Read ledger (bounded)

**Primary — full reads (100% of each file):**

| Path (under pinned/) | Interval |
|---|---|
| `get-shit-done/VERSION` | 1–1 |
| `get-shit-done/contexts/dev.md` | 1–22 |
| `get-shit-done/contexts/research.md` | 1–23 |
| `get-shit-done/contexts/review.md` | 1–23 |
| `get-shit-done/references/user-profiling.md` | 1–682 |
| `get-shit-done/references/verification-overrides.md` | 1–227 |
| `get-shit-done/references/verification-patterns.md` | 1–613 |
| `get-shit-done/references/workstream-flag.md` | 1–112 |

**Consumer evidence — partial reads:** `bin/lib/core.cjs` 1–40, 660–899 · `bin/lib/config.cjs` 20–79 · `bin/lib/commands.cjs` 740–799 · `bin/lib/profile-output.cjs` 490–579, 596–635 · `agents/kha-verifier.md` 1–45 · `workflows/verify-phase.md` 1–60.

**Grep-only (hits, not full reads — treated as leads, not coverage):** `bin/gsd-tools.cjs`, `workflows/profile-user.md`, `workflows/verify-phase.md` (beyond 60), `agents/kha-user-profiler.md`, `agents/kha-verifier.md` (beyond 45), `references/checkpoints.md`, `references/planning-config.md`, `workflows/update.md`, `scripts/tests/**`, `gsd-file-manifest.json`.

---

## 1. Test and human-acceptance denominator (real, and it is small)

**The four reference docs and three context profiles have zero automated test coverage in the pinned tree.**

- Only one JS test file exists under the whole GSD tree: `get-shit-done/bin/lib/__tests__/merge-back.test.cjs` (Glob, exhaustive for `*.test.*`). Nothing tests workstream pointer resolution, override matching, or profile redaction.
- `scripts/tests/` holds 307 Python tests, but a grep for `workstream|user-profil|overrides_applied|verification-patterns` across that directory returns exactly two hits, both in `scripts/tests/test_kha_normalize.py:35` — `test_classify_overrides_applied`, which asserts `kha-help` skill category metadata (`test_kha_normalize.py:35–40`) and is **unrelated** to verification overrides. Effective coverage of this partition: **0 tests**.
- `gsd-file-manifest.json` records SHA-256 for all 8 files (lines 29, 52–54, 90 among others), but a repo-wide grep for `gsd-file-manifest` finds no code consumer — only `state/round6-scripts-stacks-review.md:89` and a `brain/l1` index line. The manifest is **inert**: it does not gate anything, so it is not an integrity control.

**Human acceptance denominator is real but narrow.** `verification-patterns.md:559–595` defines a genuine "always human" list (visual appearance, user-flow completion, real-time behavior, external services, error-message clarity, performance feel) plus a "human if uncertain" tier, and mandates a concrete Test/Expected/Check request format (`581–593`). That defense is **preserved and enforced downstream**: `kha-verifier.md:511` states "passed is ONLY valid when the human verification section is empty," and `verify-phase.md:301` forces `human_needed` "even if all truths VERIFIED and score is N/N." `verification-overrides.md:123` correctly refuses to let overrides suppress `human_needed`. This is the strongest single guarantee in the partition and it is consistent across all three files.

---

## 2. Overrides and state authority — a real, unguarded write path

`verification-overrides.md` specifies a mechanism that mutates verification outcome: a fuzzy-matched entry in VERIFICATION.md frontmatter converts FAIL → `PASSED (override)`, and overridden items **count toward the passing score** (`121–131`), with `score: 5/5 # includes 2 overrides` given as the canonical example (`128–130`).

Findings:

- **No deterministic implementation exists.** A case-insensitive grep for `override` across `get-shit-done/bin/` returns only `cwd`/`workstream`/`model_overrides`/`storeDir` matches — nothing implements the normalize → token-overlap → 80%-threshold algorithm of `verification-overrides.md:69–73`, the ambiguity tie-break at `85`, or the score arithmetic at `126–131`. The entire mechanism is model-executed prose. "80% token overlap in EITHER direction" (`71`) is not a reproducible predicate when the matcher is an LLM.
- **Authority fields are unverified self-report.** `accepted_by` and `accepted_at` are `Required` (`36–37`), but they are free strings the same agent writes. The suggestion template at `154–156` literally instructs filling `"{your name}"` and `"{current ISO timestamp}"`. Nothing binds the accepter to a Git identity or commit, and nothing detects an agent authoring its own acceptance. Against your Git-definitions requirement, this is the weak point: acceptance state is asserted in a doc, not attributable.
- **Two verification entry points disagree.** `agents/kha-verifier.md` loads the doc (`:30`) and implements it (`:178–208`, frontmatter contract at `:593–596`). But `workflows/verify-phase.md` — the workflow spawned from execute-phase — never mentions overrides at all: a case-insensitive grep for `override` over that file yields only `:83` ("Success Criteria … override PLAN-level must_haves"), an unrelated use. Its status vocabulary (`:351`) is `passed | gaps_found | human_needed` with no `PASSED (override)`. So the same override can be honored or ignored depending on which path runs. Unresolved without reading both files end-to-end (I read `verify-phase.md:1–60` fully; the rest is grep-bounded).
- **Preserved defense worth keeping:** the "When NOT to Use" section (`55–59`), particularly the bulk-override brake ("if more than 2-3 items need overrides, revisit the plan"), and `181` (override becomes unnecessary once code satisfies the must-have). These are genuine, if unenforced, brakes.

---

## 3. Profile evidence and privacy — one material defect, confirmed in code

`user-profiling.md:449–472` defines Layer 1 (agent must not select sensitive quotes) and explicitly names Layer 2: "regex filter in the write-profile step provides a second pass."

**Layer 2 exists but does not run on the documented schema.**

- The redactor is real: `bin/lib/profile-output.cjs:497–509` defines 11 patterns (`sk-`, `Bearer`, `password|secret|token|api_key` assignments, `/Users/…`, `/home/…`, `ghp_`, `gho_`, `xoxb-`), and `513–541` redacts and reports a count to stderr.
- But the redaction loop iterates **`dim.evidence`** only (`529–536`).
- The renderer that actually writes the file accepts either key: `const evidenceArr = dim.evidence_quotes || dim.evidence;` (`603`), emitting `ev.quote`/`ev.signal` into the profile (`605–611`) at `~/.claude/get-shit-done/USER-PROFILE.md` (`625`, written `631`).
- The documented contract emits **`evidence_quotes`**: `user-profiling.md:561–567` and every dimension stub (`576`, `582`, `591`, …, `630`), and the agent is independently told to emit `evidence_quotes` — `agents/kha-user-profiler.md:133` lists it among required fields.

**Consequence:** for schema-conforming profiler output, `dim.evidence` is undefined, the redaction loop is a no-op, and unredacted quotes are written to disk. Layer 2 only fires for a legacy `evidence` key that the current agent does not produce. Defense-in-depth collapses to Layer 1 — a model instruction — exactly the layer the doc says needs a backstop. This is the highest-severity finding in the partition and it is a one-line fix (`603`'s fallback applied at `529`).

**Model qualification:** none of the 8 files qualifies a model. Qualification lives only in consuming agent frontmatter, as unpinned aliases — `kha-user-profiler.md:5` `model: sonnet`, `kha-verifier.md:5` `model: opus`. `Astra|Terra|\bSol\b` greps to a single file in the GSD tree (`workflows/execute-phase.md`, not a primary). Against your qualified-Astra/Sol/Terra requirement, this partition supplies **no** qualification and would need it added at adoption.

**Evidence discipline — preserved defenses worth keeping:** the UNSCORED tier with mandated empty evidence and neutral fallback (`520–529`); the explicit note that low frustration count is a positive finding, not thin data (`354–355`); mandatory project attribution per quote (`443–447`); the `full`/`hybrid`/`insufficient` message thresholds (`514–518`); and the natural-language-priority rule that down-weights log pastes and context dumps (`474–481`). These are unusually honest for a profiling spec.

**Real weaknesses in the heuristics themselves:** the 3× recency multiplier (`489–506`) is applied to counts that feed hard confidence thresholds ("10+ messages") while simultaneously being called "a guideline, not a hard multiplier" (`506`) — so HIGH confidence is not reproducible between two runs on identical data. Thresholds are stated in raw counts throughout (`52–55`, `102–105`, …) with no denominator, so "10+ messages showing consistent pattern" means something different at 30 messages than at 3,000. And `cross_project_consistent` requires 2+ projects (`661`) while `full` mode triggers on message count alone (`516`), so a single-project corpus can reach HIGH per the dimension rules while the cross-project field is unsupportable.

---

## 4. Workstream flag — the strongest file in the partition

`workstream-flag.md` is the one primary file whose claims I could verify line-for-line against implementation, and it holds up.

- The documented 5-level priority (`8–15`) matches `bin/gsd-tools.cjs:256`, whose comment is verbatim the doc's order, implemented at `257–271` (`--ws=` / `--ws` / `GSD_WORKSTREAM` / `getActiveWorkstream` / null).
- The 12 session env vars listed at `31–34` match `core.cjs:12–25` exactly, in the same order.
- TTY resolution order (`35–37`) matches `getControllingTtyToken` (`core.cjs:723–730`) → `probeControllingTtyToken` (`699–721`).
- The headless claim at `41–44` ("skips shelling out to `tty` because that path cannot discover a stable session identity") is implemented at `core.cjs:705–707` with a matching comment at `703–704`.
- Pointer lifecycle claims (`48–56`) are all backed: single-file unlink and empty-dir-only removal at `clearActiveWorkstreamPointer` (`780–795`); sibling preservation via explicit `readdirSync` length check (`789–790`); stale-workstream self-heal to `null` at `readActiveWorkstreamPointer` (`803–819`, esp. `810–814`).
- The honest disclosure at `58–60` — no background GC, cleanup is opportunistic, temp hygiene left to the OS — is accurate and is a genuine unknown left visible rather than papered over.

**Windows-specific correctness is deliberate and correct.** `core.cjs:755–759` uses `fs.realpathSync.native` precisely because "on Windows, `path.resolve` returns whatever case the caller supplied, while `realpathSync.native` returns the case the OS recorded — they differ on case-insensitive NTFS, producing different hashes and different tmpdir slots." And `785–786` avoids relying on `rmdirSync` throwing ENOTEMPTY "because that error is not raised reliably on Windows." Two real Windows bugs already handled.

**Residual platform gap (partial coverage, not a defect):** on native Windows outside Windows Terminal, `WT_SESSION` is absent, `TTY`/`SSH_TTY` are absent, and the `tty` binary does not exist (the `execFileSync` at `710` would throw into the empty catch at `718`). Such a session falls back to the shared `.planning/active-workstream` file — i.e. to the exact cross-session clobbering hazard the doc describes at `18–20`. Under `CLAUDE_CODE_SSE_PORT` or `CLAUDE_SESSION_ID` this is moot, but the doc does not state the Windows/conhost limitation, and no test pins it. **Unknown, not verified:** whether those Claude env vars are reliably set in your harness — I did not inspect any live session.

---

## 5. Context profiles and VERSION — orphaned contracts

**All three context files are unreferenced.** Each opens with an explicit contract — "Loaded when `context: dev` is set in config.json" (`dev.md:3`, `research.md:3`, `review.md:3`). Tracing that claim:

- `context` is a valid config key (`bin/lib/config.cjs:33`) and is validated against exactly `['dev','research','review']` (`config.cjs:355–357`).
- But **nothing loads the files.** A repo-wide grep for `get-shit-done/contexts|contexts/` returns only three `gsd-file-manifest.json` hash lines (52–54). A grep for `Context Profile|context_profile|dev\.md` finds no loader. The only `case 'context'` in the CLI (`commands.cjs:766–769`) is the unrelated `scaffold context` command producing `NN-CONTEXT.md`.

So the config key is settable and validated, and the three profiles are dead payload. Their content is coherent and internally non-contradictory (dev = low verbosity, research = high, review = medium with severity ordering), but **the loading contract stated on line 3 of each file is unsubstantiated in the pinned tree**. Either an out-of-tree installer/hook consumes them (I found no evidence) or this is a half-landed feature. 2,540 bytes of guidance with no proven consumer.

**VERSION (`1.34.2`)** has exactly one functional consumer: `workflows/update.md` at `:79, 89, 90, 159, 161, 172, 174, 185, 187` — POSIX `[ -f ]` / `grep -Eq` / `cat` inside a workflow's embedded bash. It is an installed-version marker for the updater, nothing more. It gates no behavior, and `1.34.2` corroborates no capability claim. Its own manifest entry (`gsd-file-manifest.json:29`) is inert per §1.

---

## 6. Platform reproducibility

- **Verified good:** the workstream layer is genuinely cross-platform, with the two NTFS/Windows hazards explicitly handled (`core.cjs:755–759`, `785–786`) and `toPosixPath` normalization at `core.cjs:33–35`.
- **Verified POSIX-only:** every executable snippet in `verification-patterns.md` is bash — `[ -f ]`, `grep -E`, `wc -l`, heredocs (`247`), and the four shell functions at `526–553`. Same for `update.md`'s VERSION handling. These run under WSL/Linux/Git-Bash but not PowerShell. Since your harness is Windows-primary, adopting `verification-patterns.md` as *executable* guidance requires either a shell contract or a rewrite; adopting it as *advisory* prose for an agent is fine.
- **Reference path form** `@$HOME/.claude/get-shit-done/references/checkpoints.md` (`verification-patterns.md:603`) resolves correctly post-install — I confirmed the pointed-to `<automation_reference>` section really exists at `references/checkpoints.md:381–535`. The `$HOME` form is a portability assumption I did not test.

**Substantive weakness in the stub heuristics themselves.** Several patterns are so broad they cannot discriminate: `verification-patterns.md:36` `grep -E "\[.*\]|<.*>|\{.*\}"` matches essentially all JSX/TS; `:50` `id.*=.*['\"].*['\"]` matches most typed code; `:35` flags the words `sample|example|test data|dummy`, which fire on every test fixture. Wired into `check_stubs()` (`:533–534`), any file containing "TODO" or "not implemented" — including test files and this reference document itself — reports `STUB_PATTERNS`. As advisory signals for a reasoning agent these are acceptable; as the "automated verification approach" the section title claims (`:520`), the false-positive rate is high enough to erode the FAIL signal. The file's own framing at `:14` is honest about this ("Levels 1-3 can be checked programmatically. Level 4 often requires human verification") — the gap is between that honesty and the `<automated_verification_script>` block.

**Stack fit:** `verification-patterns.md` covers React/Next.js, Express, Prisma/Drizzle, and `.env` (`:57–345`). It has no coverage for Git-as-definitions or a Postgres runtime beyond generic Prisma calls (`:247` invokes `npx prisma db execute`). For your stack the wiring-verification patterns (`:347–467`) transfer conceptually; the concrete greps do not.

---

## Bottom line

| File | Consumer traced | Tests | Verdict |
|---|---|---|---|
| `workstream-flag.md` | `gsd-tools.cjs:256–271`, `core.cjs:12–25, 693–866` | none | **Accurate.** Doc matches code line-for-line. Undisclosed native-Windows/conhost fallback. |
| `verification-patterns.md` | `verify-phase.md:22`, `checkpoints.md:381–535` | none | Sound principle (`:5–15`), strong human-verification tier (`:559–595`); POSIX-only, Node/React-specific, overbroad stub greps. |
| `verification-overrides.md` | `kha-verifier.md:30, 178–208, 593–596` only | none | **Unenforced authority.** No deterministic matcher; self-reported `accepted_by`; ignored entirely by `verify-phase.md`. |
| `user-profiling.md` | `kha-user-profiler.md:133`, `profile-user.md:13, 170, 272` | none | **Layer 2 defect confirmed** (`profile-output.cjs:529` vs `603`). Non-reproducible confidence via 3× weighting. |
| `contexts/{dev,research,review}.md` | **none** (manifest only) | none | **Orphaned.** Line-3 loading contract unsubstantiated. |
| `VERSION` | `update.md:79–187` | none | Installer marker only. Corroborates nothing. |

Two findings I'd defend hardest in discussion: the **profile redaction key mismatch** (`profile-output.cjs:529` misses `evidence_quotes`, which is the key the contract and the agent both specify) and the **override path divergence** (`kha-verifier.md` implements overrides; `verify-phase.md` does not). Both are narrow, both are code-level, both are confirmed by direct reads rather than inference.

**Explicit non-claims:** I reviewed 8 files plus bounded consumer intervals. I make no claim about the repository as a whole, about license or provenance, about OS behavior beyond what the source states, about model behavior at runtime, about human reviewer conduct, or about adoption fitness. Anything above marked "unknown" stayed unknown — I did not execute, install, or observe a session to close it.

Ready to compare against your independent pass whenever you are.