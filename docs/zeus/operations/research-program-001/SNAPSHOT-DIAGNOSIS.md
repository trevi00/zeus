# Replay snapshot diagnosis — 2026-09-19

**The original-length Windows destination reproduces the copy failure; the short destination
copies and verifies all5,111 source files. No model, Docker or candidate command was run.**

| Actual check | Result |
|---|---|
| Retained candidate scan | 5,111 regular files, all readable |
| Snapshot root matching original length128 | 2,761 copies verified, then copyfile failed |
| Failing full destination | 262 characters, FileNotFoundError/errno2 |
| Same source file | exists, 243-character path, expected hash matches |
| Short snapshot root length50 | all5,111 copies hash-verified |
| Source before/after | hashes unchanged |
| Diagnostic scratch | only newly owned directory removed after containment check |
| Provider calls / original inspection mutations | 0 / 0 |

The failing relative file is
`docs/zeus/evidence/wsl-port-001/.windows-11-restart-3/artifacts/12a09e41597d256a89c92275d910ccf9ffd9880a38be41ce7826aeadbff4726b.json`.
This is a real filesystem comparison, with no injected exceptions or simulated copy results.
The original live record omitted the path; the reproduction identifies it under the same root
length and retained candidate, rather than claiming the original traceback contained it.

Microsoft documents the traditional MAX_PATH boundary and explains that lifting it requires
application and host opt-in, or appropriate extended-path APIs. This supports the mechanism;
the two local copy results establish the behavior of this machine and interpreter. We did not
inspect or change the registry or claim every Windows application has this limitation.
[Primary documentation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)
(page updated2024-07-16, consulted2026-09-19; Windows10 version1607+ opt-in described).

## Disposition: first correct the execution layout

Use a fresh short runtime root for the next authorized run, e.g.
`D:/workspaces/zeus/artifacts/rp003`, while keeping source checkout, original run records, failed
inspection and call ledger unchanged. Under the existing replay suffix structure, the longest
projected destination for all current files is235 characters (maximum relative length133).
That is a calculated layout bound, not an already completed container replay or live canary.
The source manifest and prospective paths should be checked again at the next pinned revision.

This avoids widening the task into global Windows configuration or an unmeasured long-path API
migration. A later portability improvement can add explicit path-budget refusal and stage-specific
diagnostics if needed; it is not a reason to reopen accepted research/council behavior. New longer
repository paths require a new path calculation;235 is not a guarantee for future content.

Calls remain180/181; no new execution was started. The earlier evidence gate remains incomplete
and the worker candidate remains unaccepted. A short path alone is not a substitute for the
missing independent replay/review or the second collection tick.

Raw evidence:
`D:/workspaces/zeus/artifacts/research-program-001/run002/snapshot-diagnosis.json`
and `diagnose-snapshot.py`; hashes in EVIDENCE-DIAGNOSIS.md.
