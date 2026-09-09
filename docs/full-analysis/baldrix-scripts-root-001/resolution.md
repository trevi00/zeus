# Root scripts: independent review and discussion resolution

Scope: Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, partition `baldrix:scripts:001`, five complete primary bodies / 26,711 bytes. Root read these before receiving Claude's initial response. Six supporting records contain only the fresh ranges in supporting-evidence.json. No repository-wide closure or adoption approval follows.

Actual Claude session `5bbd2db2-dff4-44fb-8c68-6c78f86d24ef` completed an independent initial review and a resumed discussion. Both raw responses, prompts, stderr and process receipts remain separate. Claude examined submitted execution records; it did not execute the upstream programs or independently calculate receipt hashes. The checkpoint verifier performs byte comparisons, not independent execution attestation.

## Agreed findings

- Installer overwrites existing pre-commit hooks. Actual installation in a disposable Git repository removed the old marker. With core.hooksPath configured it returned success while placing hooks in the unused default directory. Linked worktree installation failed because .git is a file. The generated pre-push checks the current working tree without consuming candidate push refs; this last finding is static, not an actual push observation.
- Missing JaCoCo input reports SKIP with rc0; missing counters report 0/0 as 100%. On synthetic XML, detailed and summary modes disagree, including exclusion handling. These are parser-input observations, not authenticated Gradle/JaCoCo coverage measurements or evidence that every synthetic shape occurs in real reports.
- Mermaid uses heuristics, not the official renderer/parser. No fence, an unclosed fence or an empty directory can produce a zero-check rc0 result. An empty recognized block produces ERROR and rc1 without the consumer's expected FAIL marker. Two blocks in one file contribute one final PASS. An arbitrary two-line body bypasses length-guarded checks; its PASS does not establish official syntax validity.
- FileChanged category deduplication drops additional paths in the same category, substring classification includes incidental names, and a malformed later item discards earlier notifications with rc0. Classification normalizes separators but display basename receives the original string. The Linux observation used a repeated-backslash Windows-style string; it was not native Windows verification.
- The optional old context bar, run without jq, emitted missing-command/division-by-zero stderr and partial stdout but rc0. The currently configured status line points to hud.py. No jq-enabled token/synchronization behavior or current HUD failure was demonstrated.

## Corrections retained alongside the initial reports

reviewer.py defines SCRIPTS_DIR as handlers/post_tool. Its non-project Mermaid lookup therefore misses the root-level script in this pinned layout and can return None before launching a process. Ignoring rc/stderr and interpreting only a FAIL marker is a separate conditional consumer defect when a script resolves. Neither reviewer nor the installed host hook was executed. Timeout has an explicit failure path, so 'no way to fail' is too broad.

SessionStart emits watchPaths; the FileChanged header/body mismatch alone does not prove that global watching is absent or that a live host rejects the output. Filename searches do not prove unique callers or the absence of tests. The fully read workflow declares two Ubuntu jobs and path filters; neither current upstream execution history nor all possible Windows automation was examined.

The installer test's overwrite substring does not logically prohibit adding backup/composition. Current implementation lacks preservation. Local unused variable declarations and the generated child-hook environment are different effects. Standalone Mermaid and JaCoCo can return failure on specific paths.

Root accepts Claude's narrower treatment of synthetic report validity, unexecuted jq behavior, display escape handling (not command execution), and missing numeric lower bounds as code observations rather than demonstrated production failures. Git-ref syntax and authentic JaCoCo grammar were not independently verified here; neither becomes a new closure claim. Claude's 'timeout only' phrasing applies to the read validator subprocess interpretation branch, not every path of the full handler.

## Executed scope and adaptation requirements

Original installer unit wrapper: five passing static-text tests. Separate component program: actual original Python/Bash CLIs, synthetic input files, and actual Git initialization/installation/worktree operations inside the existing immutable image, read-only source, no network or host credentials. Child failures are preserved inside the completed component observation, not counted as passing tests. Source hashes cover 1,648 unchanged pinned files. No mock providers, patched methods or fake process outcomes were used in this observation program.

Adaptation must bind gates to exact candidate revisions; preserve or compose effective hooks through Git's resolved hook location; distinguish checked/excluded/unavailable denominators; validate output with a structured status contract and process result; and preserve notification creation/delivery/acknowledgment separately. Actual Windows/Linux/WSL behavior, real renderer/build outputs and human-reviewed SDD acceptance remain required. The five original static tests and Zeus's own suite do not substitute for these.

Remaining: complete caller/host closure, real push execution, jq-enabled behavior, authenticated coverage/renderer fixtures, platform qualification, license/dependency decision, and independent adoption authority. The sibling agent's run_all/run_units review is separate evidence, not a retroactive root or Claude body read.
