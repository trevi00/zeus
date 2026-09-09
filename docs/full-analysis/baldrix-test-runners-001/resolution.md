# Runner independent review and discussion resolution

Root and actual Claude independently read run_all.py, run_units.py and conftest.py at Baldrix cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2. These three previously recorded paths were freshly re-reviewed, not counted as new coverage. Root traced ten supporting records (nine full, one partial). Claude session 21203e2d-be44-407e-b85a-44dddf130113 completed initial review and discussion; raw responses and submitted process records are preserved separately.

## Agreement and observations

Required isolation can fall through after re-exec errors, separate environment overrides can defeat a CLAUDE_HOME-only redirection, in-process tests share more state, and different runners collect and interpret different obligations. Asset links do not enforce read-only access. No full runner or live leakage incident was executed here.

The original manual compaction suite passed six tests. Separate actual helper observations show empty scripts passing, stderr-only markers discarded on rc0, and an actual pytest assertion failure misclassified as dependency missing because its message contains a special substring. Collection-zero and explicit exit2 controls were correctly rejected/preserved. Selector examples demonstrate both missed fixture forms and string-literal false positives. Scratch symlink writes reached their target; cleanup preserved that target. The helper's nonexistent CLAUDE_HOME argument was just an environment path, not a created isolated home. No original methods or provider/process results were patched.

These observations do not prove the final disposition of the entire runner, pytest acceptance of failing original compaction predicates, or native Windows/WSL behavior. The original `_ok(False, ...)` returning None while appending to a failure list was observed directly; whole-suite consequences remain a traced inference.

## Reconciled corrections

Claude withdrew unconditional claims that logs vanish from every channel, that telemetry is always deleted, that no pytest import mechanism exists outside cwd, and that non-builtin tests disappear from the pair of runners. Summary skip counts can remain while detailed identities are lost. Runtime graduation changes delegation between the runners. Empty pytest collection is rejected; all-collected-tests-skipped is a different, unexecuted scenario. Registry counts must distinguish 37 builtins and runtime graduation.

Logging WARN is not sufficient for required Zeus isolation failure. The surrounding home may already be externally isolated, so it must not automatically be called production. Reordering conftest's import cannot restore all collection-time state. Widening a fixture whitelist does not prove every test's policy oracle was weakened. Reset recursively deletes ordinary children and skips recorded link basenames; it does not verify their identities. Advisory WARN behavior is not automatically an authorization bypass.

Residual discussion overstatements are not adopted: pre-push can inherit CLAUDE_TELEMETRY_DIR even though it does not set it, so deletion is still conditional there. Nine links from eleven configured names do not contradict completeness of the tracked Git snapshot; hooks/plugins absent from the pinned tracked tree belong to the separately inventoried local-extra question. A Glob result is not a whole-suite acceptance denominator. `_needs_pytest` is outside a per-item recovery block but inside the outer cleanup try/finally. The source establishes `_real_home`'s derivation; the observation with equal asset override and source root does not experimentally distinguish the alternatives.

## Root recorder defect and implemented correction

Claude correctly found that root's historical run_observations.py could lose an outer-timeout receipt and overwrite orphaned streams on retry. That source and its successful observations remain unchanged. New run_observations_v2.py reserves an exclusive attempt directory, writes intent before launch, streams output to exclusive files, records timeout/launch/interruption status, and preserves separate Docker cleanup results. Source tree, component and recorder identities are recorded before original execution. A second Codex reviewer caught launch-versus-termination error conflation and late-only input identity; root corrected both.

Actual recorder checks cover normal completion, a direct child timeout retaining partial output, missing executable, and rejection of an existing attempt before another process starts. A separately named Docker timeout retained partial output and successfully removed that container. The revised recorder also repeated the original helper observation with rc0, cleanup rc0 and 1,648 unchanged source files. Earlier recorder-check source versions are retained beside their results. This is a fix to the review tooling, not adoption of the original runner.

Limits remain explicit: no fsync/power-loss durability guarantee, no general process-tree attestation, and filesystem hash checks establish content identity rather than inode/permission identity. An abrupt recorder death can leave intent without a terminal receipt; that attempt remains incomplete and cannot be reused silently. Hash comparisons do not independently attest that Claude saw an execution or that the original logic is correct.

## Adoption boundary

Require exact candidate/environment/attempt identities, isolation failure as unavailable/failure, structured result categories, explicit collection/execution/skip obligations, authoritative runner selection, retained failure evidence and authenticated human scenario acceptance. Root reads of state_leak_check and canary_apply are scoped supporting evidence, not Claude's independent confirmation of their full dependencies. New tests002/003 and Harness005/006 reports are separate agent work, not jointly reviewed by Claude in this session. Whole closure, licenses, actual model qualification, real host/OS acceptance and adoption remain incomplete.
