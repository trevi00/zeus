I read root-initial.md (1–42), root-followup.md (1–91), observations.md (1–31), and the attempt's `intent.json` (1–69) and `stdout.txt` (1). Then I re-read the exact source intervals needed to test each correction. Below is additive: what root's execution establishes that I could not, then my corrections, then new findings, then unknowns.

My initial report stands unmodified as the raw record; nothing below edits it.

---

## 1. What root's observation adds (I claimed none of this)

Seven Bash calls against the unmodified `verification-patterns.md` 525–552 functions, in an immutable/offline/read-only/unprivileged container (`intent.json:2–55`, source tree hash unchanged over 1,648 files, `intent.json:61–62`), produce measured behavior I had only reasoned about — and the measured defects are **different from and more serious than** the ones I asserted:

- `check_stubs` on a no-match file exits **2** with `[: 0\n0: integer expression expected` (`stdout.txt` obs. `no_stub_matches`). The `grep -c … || echo 0` idiom at `:533` yields a two-line value on rc=1, so the `-gt` test at `:534` is malformed. That is a real bug in the emitted numeric contract, not the false-positive story I told.
- `check_substantive` on a no-pattern file prints `THIN: … (1 lines, 0\n0 matches)` **with exit 0** while emitting the same integer error to stderr (`no_substance_pattern`). Producer failure is silently dropped; the label is still authoritative-looking.
- `check_wiring` on a **comment-only** file returns `WIRED` (`comment_wiring`), and `check_substantive` on two comment lines returns `SUBSTANTIVE` (`comment_substance`). Token presence in a comment satisfies both — the exact failure mode `verification-patterns.md:5–15` ("Existence ≠ Implementation") claims to prevent.
- `check_wiring` on a missing file returns `NOT_WIRED` with exit **0** plus raw grep stderr (`missing_wiring`); `check_exists` on a missing file returns `MISSING` exit 0 (`missing_exists`). Nothing distinguishes "absent" from "present but unwired" in the exit code.

Root's framing is the correct one and I adopt it: **these are emitted labels, not a verifier PASS.** No full verifier, no source suite, no services, no database, no model judgment, no human acceptance, no Windows/WSL run occurred (`observations.md:24–29`). One measured Linux container, seven calls, three scratch fixtures and one absent path — that is the whole denominator.

---

## 2. Corrections to my initial report

**C1 — "Effective coverage of this partition: 0 tests."** Overclaim. I ran a name-targeted grep (`workstream|user-profil|overrides_applied|verification-patterns`) over `scripts/tests/` and a `*.test.*` glob. Neither is coverage analysis. Correct statement: *no test matching those names was found in those two bounded searches; repository-wide test absence is not established.* Root's phrasing at root-followup.md:86–88 is right.

**C2 — "No deterministic implementation exists" for override matching.** Overclaim from one case-insensitive grep for `override` over `bin/`. Correct: *no matcher was found in that bounded search; absence across the pinned tree is not proven.*

**C3 — manifest "inert", "does not gate anything".** Same defect. Correct: *no consumer found by a repo-wide grep for `gsd-file-manifest`; that is not proof of inertness.*

**C4 — VERSION has "exactly one functional consumer".** Withdraw "exactly one". A grep found `update.md` hits; root additionally traced `update.md:195–243` choosing local/global runtime with unknown-version branches (root-followup.md:81–84). Correct: *the consumers found are in `update.md`; the search was not exhaustive, and even there only the listed interval was traced, not the full multi-runtime detection.*

**C5 — contexts are "dead payload", "orphaned".** Overclaim. Correct: *`config.cjs:355–357` proves a validated configuration interface for `dev|research|review`; no Markdown loader was found in bounded searches, so loading is **unconfirmed**, not disproven.* Root notes one search hit a nonexistent hooks directory and one result was truncated (root-followup.md:77–79) — neither counts as coverage.

**C6 — human-verification defenses "enforced downstream", "the strongest single guarantee".** Category error on my part. `kha-verifier.md:511` and `verify-phase.md:301` are **prose instructions to a model**, not runtime gates; nothing executes them, and I ran nothing. Correct: *a well-specified prose discipline whose enforcement is unmeasured.* Same downgrade applies to `verification-overrides.md:123`.

**C7 — "two real Windows bugs already handled" (`core.cjs:755–759`, `785–786`).** Overclaim. Those are static branches with explanatory comments. No Windows or WSL execution occurred. Correct: *documented intent addressing plausible NTFS case-folding and `rmdirSync` behavior; unverified as fixes.*

**C8 — "runs under WSL/Linux/Git-Bash but not PowerShell."** Withdraw the positive half. I measured nothing; the one Linux measurement that exists shows these snippets failing in the ways above. Correct: *POSIX-shell-shaped, not PowerShell-compatible on their face; general Linux/WSL/Git-Bash correctness is not claimed, and the measured Linux behavior is partially defective.*

**C9 — "heredocs (`:247`)."** Wrong term. `npx prisma db execute --stdin <<< "…"` is a **here-string**, not a heredoc.

**C10 — "Wired into `check_stubs()` (`:533–534`), any file containing 'TODO'…"** Misleading juxtaposition. The broad patterns I listed (`:35`, `:36`, `:50`) live in prose sections and are **not** wired into `check_stubs`; the function contains exactly four literal alternatives — `TODO|FIXME|placeholder|not implemented` (`:533`, re-read). And I asserted a "false-positive rate high enough to erode the FAIL signal" with **no measurement**. Withdraw the rate claim; root measured none either (`observations.md:29`).

**C11 — "a single-project corpus can reach HIGH."** Wrong, withdrawn. `user-profiling.md:52` states HIGH requires "10+ messages showing consistent pattern (> 70% match), **same pattern observed across 2+ projects**" — the two-project requirement is explicit in the HIGH tier itself. The same conjunction appears at `:102`, `:152`, `:202`, `:252`, `:302`, `:352`, `:402`. My inference contradicted the rubric text.

**C12 — I praised `:354–355` (low frustration count is POSITIVE) as "unusually honest".** Correct the sign: that line is an **overreach in the source**. Low *observed* frustration cannot prove satisfaction when the corpus is sampled and truncated upstream (`profile-pipeline.cjs:122–124`, `:487`) — absence of a signal in a 150-message, 500-char-truncated sample is not absence of the trait. Root had this right at root-initial.md:31.

**C13 — "a one-line fix (`:603`'s fallback applied at `:529`)."** Withdrawn as wrong on scope. The redaction pass at `profile-output.cjs:527–537` misses `evidence_quotes` **and** every other rendered field: `summary` (`:600`), `claude_instruction` (`:599`), and the per-quote `project` label (`:608`) are all rendered outside it (`:616–620`). Upstream is worse: `profile-pipeline.cjs:146–151` and `:489–495` write `content` and `projectPath` into the sample file with **no redaction at any point**, and that file is what reaches the model. A `:529` patch would not touch either. Root's `:27–33` framing supersedes mine.

**C14 — override path divergence "confirmed by direct reads".** Overstated. I read `verify-phase.md:1–60` in full and the remainder only by grep for `override|human_needed|status:`; I read `kha-verifier.md:1–45` in full and the rest by grep. Correct: *a hypothesis supported by a partial-consumer read plus name-bounded grep, not code-level proof.* Root reached the same override content independently at `kha-verifier.md:165–219` and schema `589–607` (root-followup.md:63–65) without asserting divergence.

---

## 3. Additive agreements (verified against my own re-reads)

**Consent gate is real — preserve it.** `profile-user.md:59–121`: `--questionnaire` skips all JSONL reading (`:61`), an explicit three-way AskUserQuestion with a "Not now" exit (`:115–121`), and a separate refresh path with backup (`:98–111`). Root is right that this is a genuine defense.

**And it makes a promise the code path does not keep.** `:94` "✗ Nothing is sent to external services" and `:95` "✗ Sensitive content … automatically excluded", plus the stderr banner `profile-pipeline.cjs:399` "read-only, nothing is modified or sent anywhere". But `:160–174` spawns `kha-user-profiler` via Task with `Session data: @{temp_dir}/profile-sample.jsonl` — the sampled messages are model input. **I make no exfiltration claim**: the provider configuration was not inspected and no transfer was observed. The accurate statement is that the display asserts a blanket guarantee the inspected path does not enforce.

**Sampling arithmetic — confirmed exactly as root described.** `perProjectCap` (`:440`) is applied as `proj.sessions.slice(0, perProjectCap)` (`:450`) — it caps **sessions, not messages**, so per-project message fairness does not follow. Recency is `session.modified` mtime → `perSessionMax = isRecent ? 10 : 3` (`:458–459`), a sampling-side denominator entirely separate from the rubric's ~3× *signal* weighting (`user-profiling.md:497`). The two compound. Projects are sorted `b.lastActive - a.lastActive` (`:433`) with a global `break` at `allMessages.length >= limit` (`:448`), so older projects can be starved to zero.

**Zero-message edge confirmed.** `output_file: outputPath` is returned (`:523`) while the append loop `:518–520` never executes on an empty `allMessages`, so the path names a file that does not exist.

**Workstream local defenses are correct and narrower than the doc implies — preserve them.** When a session key exists, a missing or stale session pointer resolves to `null` and does **not** fall through to the shared file (`core.cjs:831–838`); the legacy pointer is read only in the no-session-key case. Root's `:49–50` is right and this is worth keeping.

**Workstream limitations confirmed.** Tokens are sanitized-and-truncated to 160 chars (`core.cjs:693–697`), not hashed — distinct raw identifiers can collide onto one pointer file. Writes are a bare `fs.writeFileSync` (`:865`) with no atomic rename or lease. Reads have unlink side effects (`:807`, `:812`). Inherited `GSD_WORKSTREAM` beats a newly set session pointer (`gsd-tools.cjs:268–271`). **No race was executed**; these are static.

---

## 4. New, additive (not in either prior report)

**The `GSD_PROJECT` mismatch has a destructive read path.** `readActiveWorkstreamPointer` validates existence against `path.join(planningRoot(cwd), 'workstreams', name)` (`core.cjs:810`), and `planningRoot` (`:668–670`) deliberately ignores the project dimension. But `planningDir` routes to `.planning/{project}/workstreams/{ws}` when `GSD_PROJECT` is set (`:649`, `:662–663`, documented `:641–642`). So under `GSD_PROJECT`, a **valid** pointer fails the existence check and is treated as stale — `clearActiveWorkstreamPointer` **unlinks it** (`:811–813`) and may remove the tmp directory. Root identified the reconciliation gap (root-followup.md:56–57); the additive point is that the consequence is silent deletion of live routing state on a read, not merely a resolution mismatch. Static only — not reproduced.

**Redaction pattern list is wrong-platform for this harness.** `profile-output.cjs:504–505` covers `/Users/…` and `/home/…` only. `profile-pipeline.cjs:148` sets `projectPath: record.cwd` and `:492` writes it through — on Windows that is `C:\Users\<name>\…`, which no pattern matches, and which is precisely the category `user-profiling.md:459` instructs the agent to exclude. Root noted the missing Windows username paths (root-followup.md:31); the additive detail is the concrete producing field and that it sits upstream of the redactor entirely.

**Sample caps are applied before the quality filters, with no backfill.** `remaining = Math.min(perSessionMax, limit - allMessages.length)` is passed as `maxMessages` into extraction (`:461–464`), and only afterward are context dumps (`:471–474`) and log pastes (`:476–485`) discarded. A session whose first 10 genuine messages are dumps contributes zero and is not topped up. This mechanically contradicts `user-profiling.md:474–481` ("Deprioritize them when selecting evidence") — deprioritization requires a pool the sampler never builds.

---

## 5. Unknowns I am not closing

Model provider and actual transmission; Layer-1 agent compliance and whether any real leak occurred; the existence of a context-Markdown loader anywhere outside my bounded searches; whether any override matcher exists outside `bin/`; repository-wide test coverage; whether `verify-phase.md` in full contradicts my divergence hypothesis; concurrency/race behavior; Windows, WSL, or Git-Bash execution of any snippet; general false-positive rates; license, provenance, external claims, adoption fitness, and any human or model acceptance. Nothing here qualifies Astra/Sol/Terra on real scenarios, and no eight-stage SDD or no-mock acceptance was demonstrated by this partition.

Line totals in my initial report derive from Read output and may run one high against root's source metadata; where they differ, root's metadata governs (root's excerpt range 525–552 matches the function block I re-read).

**Net:** on substance we converge. My distinctive contributions that survive are the `evidence_quotes`/`evidence` redaction bypass (`profile-output.cjs:527–537` vs `:603`, agent contract `kha-user-profiler.md:133`) — which root independently reached and correctly widened — and the `GSD_PROJECT` unlink path above. Fourteen of my initial formulations needed correction, most of them the same error repeated: treating a bounded negative search as proof of absence, and treating prose as enforcement.