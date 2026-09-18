# Research program owner review — 2026-09-19

Status: draft implementation; limited live acceptance pending. Not unattended-ready.
Issue: #152. Deployed main is unchanged.

| Boundary | Evidence | Disposition |
|---|---|---|
| Authorized repository before effects | correction tests, actual temporary clone | accepted |
| Manifest preparation failure | injected artifact error and real filesystem conflict tests | accepted for exercised paths |
| Exact captured bytes on Windows | binary Git readback, Korean text and LF, 18/18 bytes | accepted |
| Related Windows + isolated PG checks | 54 passed, lint passed | passed |
| Diagnostic append before council | owner fault injection, zero council calls, next tick busy | reporting/recovery incomplete; limited-canary exception only |
| Actual two-tick autonomous council | not run; 7 calls needed, 5 available | pending |

The independent second review rejected the diagnostic failure path. Its verdict is preserved;
the owner has not relabelled it accepted. This failure safely retains ownership in the measured
case but lacks the expected blocked receipt. The owner limits the next run to a healthy-log
finite canary and will stop on any failure. General unattended acceptance still requires the
diagnostic/recovery condition. See the same SPEC for the explicit scope decision.

Both actual feed collectors succeeded in the owner preflight with15 entries each. This proves
fetch/parse at that instant, not relevance, primary-source analysis, adoption or improvement.
The planned output is a reviewed recommendation document, not an automatically deployed change.

## Raw evidence

Local root: `D:/workspaces/zeus/artifacts/research-program-001/`.
`EVIDENCE.json` records file hashes. These files are local large/raw evidence, not downloadable
from Git. Initial and corrected model verdicts and injected-failure tests remain separate.
Passing `test_owner_log_failure.py` means the unresolved failure was reproduced, not repaired.

Actual worker candidates: initial75bc8bb2ac700c96f54fce66230e840285968f9a;
correction b047dc87205c99fd6e7e0593b1946df4069e527c. No model calls were used by owner fault tests.
