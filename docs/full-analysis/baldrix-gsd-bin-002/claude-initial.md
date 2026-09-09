All 8 primaries read in full. Here is my independent static review.

## Reads performed (pinned `cbb5c3e6…`, `.runtime/absorption/sources/baldrix/pinned`)

**Primary — full bodies, fresh:**

| # | File | Lines read |
|---|---|---|
| 1 | `get-shit-done/bin/lib/init.cjs` | 1–1523 (full) |
| 2 | `get-shit-done/bin/lib/intel.cjs` | 1–661 (full) |
| 3 | `get-shit-done/bin/lib/learnings.cjs` | 1–379 (full) |
| 4 | `get-shit-done/bin/lib/merge-back.cjs` | 1–268 (full) |
| 5 | `get-shit-done/bin/lib/milestone.cjs` | 1–283 (full) |
| 6 | `get-shit-done/bin/lib/model-profiles.cjs` | 1–71 (full) |
| 7 | `get-shit-done/bin/lib/phase.cjs` | 1–932 (full) |
| 8 | `get-shit-done/bin/lib/profile-output.cjs` | 1–1049 (full) |

**Supporting intervals (bounded):** `bin/gsd-tools.cjs` 455–494, 970–1049 + dispatch grep (lines 450–1043); `lib/core.cjs` 170–215, 355–404, 525–594, 1230–1254, 1253–1362; `lib/config.cjs` 400–454; `lib/verify.cjs` 625–644; `lib/__tests__/merge-back.test.cjs` 1–130, 140–199, 355–445 + test-title grep.

No execution, no imports, no test runs, no writes, no network. Grep/Glob only for tracing.

---

## Findings

### 1. `--expected-base` is accepted, threaded, and never read — no ownership check exists
`gsd-tools.cjs:475-478` parses `--expected-base` and passes `expectedBase` into `cmdQuickMergeBack`. `merge-back.cjs:212-218` destructures only `quickId` and `quickDir`; `expectedBase` appears nowhere else in the file (full body read). The merge therefore proceeds against whatever `main` HEAD is (`merge-back.cjs:99`), with no verification that main is the base the worktree branched from.

This is aggravated by the test suite: all 12 non-trivial scenarios pass `--expected-base` (`merge-back.test.cjs:146`, and lines 192, 227, 250, 274, 290, 307, 330, 347, 370, 393, 410, 427, 437), and `makeBase` computes it at line 123 — but no scenario constructs a divergent base, and no assertion references it. The parameter reads as covered while being inert. This is a threaded-but-unenforced contract, not a source defense.

### 2. merge-back: partial success across multiple worktrees, with no rollback
`merge-back.cjs:248-258`: worktrees are merged in a loop; `merged` is `entries.every(e => e.merged)`. If worktree A merges cleanly and B conflicts, A's merge is already committed to main (`:107`), A's reconcile commit may already exist (`:172`), and A's worktree and branch are already destroyed (`:183-187`) — before B is attempted. The reported `merged:false` is a *summary*, not a rollback. Test 7 (`:360-379`) covers conflict in the single-worktree case only; test 8 (`:381-400`) covers two clean worktrees. The mixed cell is untested.

Also `entry.merged = true` (`:189`) is set unconditionally after cleanup, so a failed `worktree remove` or `branch -D` (`:184`, `:186`) still reports `merged:true` with `removed:false` — the receipt fields are honest, but the top-level boolean is not gated on them.

The empty case is correctly handled (`:240-244` returns `merged:false, reason:'no_worktrees'` before `every()` could vacuously return true) — no empty-denominator bug here.

### 3. Three-way divergence in `model_profile` authority
Same config key, three disagreeing authorities:

- `model-profiles.cjs:28` — `VALID_PROFILES = Object.keys(MODEL_PROFILES['kha-planner'])` = `quality, balanced, budget, adaptive`. This gates the setter at `config.cjs:407,411-412`.
- `core.cjs:1321-1325` — `resolveModelInternal` special-cases `profile === 'inherit'` and returns `'inherit'`.
- `verify.cjs:633-635` — `validProfiles = ['quality','balanced','budget','inherit']`, warning `W004` otherwise.

Net: `adaptive` is settable via `config-set-model-profile` but is flagged invalid by the health check; `inherit` is honored at resolution time and accepted by the health check but rejected by the setter. Note the setter's valid list is derived structurally from one agent's key set, so adding a profile column to `kha-planner` silently changes CLI validation without touching `verify.cjs`.

I make no claim about which model any alias corresponds to. `MODEL_ALIAS_MAP` (`core.cjs:1297-1301`) is a static string table; a static alias is not evidence of model qualification or availability.

### 4. `profile-output.cjs`: the redaction pass misses the field the renderer actually prefers
Redaction (`:527-537`) walks `analysis.dimensions[k].evidence` and rewrites `ev.quote`, `ev.example`, `ev.signal`. The renderer at `:603` reads `const evidenceArr = dim.evidence_quotes || dim.evidence` — preferring `evidence_quotes`, which the redaction loop never visits. An analysis JSON using `evidence_quotes` is written to `USER-PROFILE.md` (`:631`) unredacted, while `sensitive_redacted: 0` (`:639`) and the template's `{{sensitive_excluded_summary}}` (`:592-593`) both report "None detected".

Separately, `SENSITIVE_PATTERNS` includes `/\/Users\/[a-zA-Z0-9._-]+\//g` and `/\/home\/…/g` (`:504-505`), yet `analysis.projects_list` is interpolated verbatim at `:583` and `dim.summary` / `dim.claude_instruction` at `:599-600, 619` — none pass through `redactSensitive`. The redactor is a real defense, but its scope is narrower than the write surface it fronts.

### 5. `profile-output.cjs:1015-1017`: inverted `profile_status`
```
if (finalContent && finalContent.indexOf('<!-- GSD:profile-start') !== -1) { … }
else { profileStatus = 'already_present'; }
```
The `else` branch is reached precisely when the marker is **absent**. Combined with the `:1000` gate (`if (!options.auto && …)` — under `--auto` the placeholder is never appended), an `--auto` run on a file with no profile section reports `profile_status: 'already_present'` for a section that does not exist.

### 6. `milestone.cjs`: hardcoded receipt + swallowed partial archive
- `:242` `milestones_updated: true` is a literal, emitted regardless of what the write branches at `:176-195` did. Contrast `:237-239`, which are genuine `fs.existsSync` receipts of the archive targets, and `:243` `state_updated: fs.existsSync(statePath)` — an existence check, not write confirmation.
- `:211-226` the phase-archive block wraps a `renameSync` loop in `try {} catch { /* intentionally empty */ }`. A mid-loop throw leaves some phase directories moved into `${version}-phases` and the rest in place, with `phasesArchived` still `false` and no error surfaced. Partial move, no rollback, silent.
- `cmdMilestoneComplete` performs archival renames with no `--confirm`, in contrast to `cmdPhasesClear:258-262`, which does require `--confirm` before deleting phase directories. The guard is asymmetric across two destructive operations in the same file.

### 7. `phase.cjs:565-581`: renumbering rewrites text outside the current milestone
`updateRoadmapAfterPhaseRemoval` reads the whole `ROADMAP.md` (`:562`) and never narrows via `extractCurrentMilestone`, unlike `cmdPhaseAdd:329` and `cmdPhaseInsert:408`, which do scan the current milestone. It then loops `oldNum` from 99 down to `removedInt+1` applying five global regexes, including:
- `:576` `(Phase\s+)${oldStr}([:\s])` with `g` — rewrites every "Phase N" mention anywhere in the file, including shipped-milestone sections and prose.
- `:577` `${oldPad}-(\d{2})` with `g` — an unanchored two-digit pattern that matches plan IDs but equally matches any `NN-NN` substring in the document.

Order also matters: `cmdPhaseRemove:612` deletes the phase directory before `:625` touches the ROADMAP, and the on-disk renumbering at `:616-622` is wrapped in a swallowing `catch`. A throw between these steps leaves disk and ROADMAP diverged with no recovery path.

### 8. `intel.cjs:448-452`: entry-path existence check resolves against the wrong root
`intelValidate` spot-checks the first five `files.json` entry paths with bare `fs.existsSync(ep)`. `ep` is a repo-relative path, but `existsSync` resolves it against the process CWD, while `planningDir` comes from `gsd-tools.cjs:1000` as `path.join(cwd, '.planning')` where `cwd` honors `--cwd`. Invoked with `--cwd` pointing elsewhere, every entry produces a spurious `"entry path … does not exist on disk"` warning. All the sibling paths in this file are built with `intelFilePath` (`:79-81`); this one is not.

### 9. `intel.cjs:53-63` bypasses the project's config authority
`isIntelEnabled` reads `.planning/config.json` directly and returns `false` on any error. This is deliberate (the `intel` key is not in `loadConfig`'s whitelist — `core.cjs:332-366` returns a fixed normalized shape with no `intel`), so it is a divergence rather than a defect. Consequence worth stating: intel gating does not participate in the `~/.gsd/defaults.json` fallback chain (`core.cjs:373-394`), so intel cannot be enabled globally the way `model_profile`, `commit_docs`, etc. can. Failing closed on parse error is the safe direction.

### 10. `learnings.cjs`: strong ID defense, asymmetric destructive guard
Genuine defense: `learningsRead:141` and `learningsDelete:197` both gate on `/^[a-z0-9]+-[a-f0-9]+$/` before joining into a path, and `cmdLearningsDelete:355` repeats the check — traversal via `id` is blocked at three points.

Against that: `cmdLearningsPrune` (`:340-347`, dispatched at `gsd-tools.cjs:1035-1039`) unlinks files from the **global cross-project** store at `~/.gsd/knowledge` (`:24`) with no confirmation flag, invoked from any project's CWD. `learningsPrune` never receives `opts`, so `storeDir` is test-only override — production always hits the shared home directory. Compare `cmdPhasesClear`'s `--confirm` requirement for a project-scoped deletion.

Prune's failure direction is safe: an unparseable `record.date` yields `Invalid Date`, and `Invalid Date < cutoff` is `false`, so malformed records are kept, not deleted (`:291-297`).

### 11. `init.cjs`: silent brownfield-detection fallback
`cmdInitNewProject:313-347` — `findCodeFiles` returns `false` on any `readdirSync` failure (`:337`) and the whole block is wrapped in `catch { /* best-effort */ }` (`:347`). `hasCode` staying `false` propagates to `is_brownfield` and `needs_codebase_map` (`:383-384`). A traversal failure is reported as "greenfield" rather than "unknown" — an unsafe-direction fallback, distinct from the `hasPackageFile` path (`:349-364`), which uses direct `pathExistsInternal` checks.

`sanitizeFlags` (`:1088-1099`) is the counterexample of a correct defense in the same file: it validates every token against an allowlist, warns on stderr, and returns `''` — failing to the safe value.

### 12. `checkAgentsInstalled` is machine-global, not project-scoped
`init.cjs:37-39` injects `agents_installed` / `missing_agents` into every init payload via `core.cjs:1253-1288`, which resolves the directory from `GSD_AGENTS_DIR` or `__dirname/../../../agents` (`core.cjs:1236-1242`). The result reflects the installed toolchain, not the project at `cwd`. Also note `core.cjs:1258` applies `.replace(/^gsd-/, 'kha-')` to `MODEL_PROFILES` keys, but every key in the pinned `model-profiles.cjs:10-26` is already `kha-`-prefixed — the mapping is a no-op and its comment describes a rename that the pinned table has already absorbed. Behaviorally harmless; the comment is stale.

---

## Scope limits I am holding to

- **No whole-repo absence claims.** Where I say something "appears nowhere else," it is scoped to the file body I read in full (e.g. `expectedBase` within `merge-back.cjs:1-268`) or to the exact grep path stated. I did not enumerate the repository.
- **No platform behavior.** `merge-back.cjs:31-40, 57, 147` normalize backslashes and `merge-back.test.cjs:43-55, 419-432` reference CRLF and lock-retry, but I ran nothing; I make no Windows/Linux/WSL behavioral claim.
- **No model qualification.** `MODEL_PROFILES` and `MODEL_ALIAS_MAP` are static string tables. Nothing here establishes that Astra, Sol, Terra, or any aliased model is qualified or available.
- **No test execution, no closure, no acceptance/adoption/license claim.** `merge-back.test.cjs` is the only test file under `bin/lib/__tests__/` (Glob result above); it drives real temp git repos via subprocess rather than mocks, which I note as a *static* property of the harness — I did not run it and claim no pass/fail state.
- **User-level requirements not evidenced by this partition.** These 8 files contain no 8-stage SDD gate, no human core-scenario acceptance record, no PostgreSQL runtime, and no Git-definition surface beyond `execGit`/`spawnSync` shell-outs (`core.cjs:531-542`, `init.cjs:1288, 1307, 1410`). I am not asserting those requirements are met or unmet — only that this partition does not carry evidence either way.

**Highest-severity, in order:** #1 (inert ownership check), #2 (unrecoverable partial merge), #4 (redaction bypass with a falsely reassuring receipt), #7 (unscoped global roadmap rewrite), #6 (hardcoded receipt + silent partial archive).

Ready to discuss any of these against your independent pass.