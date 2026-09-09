# GSD guidance, implementation and execution workflow checkpoint

Starting root revision: 31d5091407566d4988980485246ed031784203b2. The delegated work began
while the preceding checkpoint was being published; each report preserves its own start.
New primary records: 33 files / 653,057 bytes. Supporting records: 56, excluded from the
primary denominator. The verifier checked raw blobs, lengths, hashes, ranges and 177 review
references. These checks establish record identity, not semantic correctness by themselves.

| Scope | Primary | Bytes | Supporting records | Evidence |
|---|---:|---:|---:|---|
| GSD guidance, contexts and VERSION | 8 | 70,224 | 10 | [Joint resolution](baldrix-gsd-guidance-002/resolution.md) |
| GSD bin 001 | 7 | 198,986 | 6 | [Independent review](baldrix-gsd-bin-001/review.md) |
| GSD bin 003 | 9 | 183,887 | 16 | [Independent review](baldrix-gsd-bin-003/review.md) |
| GSD workflows 002 | 9 | 199,960 | 24 | [Independent review](baldrix-gsd-workflows-002/review.md) |

Workflow support has 24 records for 23 paths; these are not 24 additional full source files.
Support overlaps across reviewers also do not add primary coverage. Root read the delegated
reports, including bin 001's per-file review, without claiming a second fresh full reading
of every delegated source. Actual Claude independently reviewed and discussed the root's
eight-file scope; those two calls do not provide Claude coverage for the other 25 files.

The original reference's four Bash functions were invoked seven times in an offline,
read-only, immutable Linux container. Comment-only fixtures produced WIRED/SUBSTANTIVE;
missing files produced labels with exit zero; no grep matches produced malformed numeric
input, with different return codes across functions. The actual TODO control was retained.
This demonstrates limits of the reference snippets, not a complete verifier PASS or real
frontend/database/payment acceptance. All 1,648 pinned source bytes remained unchanged and
the named container was cleaned up. Generic process-tree termination remains unverified.

The root/Claude joint review confirmed the profile evidence_quotes/evidence redaction
mismatch and widened its scope to other output fields, upstream model input, sampling,
consent wording and temporary data ownership. No actual user sessions or credentials were
read, no profile was collected, and no provider transmission or leak was observed. The
new FA-032 draft addresses this distinct data-flow topic. A single field rename would not
establish end-to-end protection or honest consent. It is not an implementation approval.

Delegated static findings add concrete implementation and consumer paths:

- Large JSON output can reap unrelated gsd-* temporary directories by age. Lock timeout
  and non-EEXIST error paths can proceed without ownership; callback errors and async work
  require careful lifetime handling. Existing exclusive creation is a useful partial defense.
- Workstream migration rollback errors may be ignored before destination cleanup. Merge-back
  ignores expected-base and can clean up after reconcile failure. Workflow code enumerates
  all noncurrent worktrees and can mistake newly added planning files for resurrected files.
  No destructive workflow, Git merge or race experiment was executed in these partitions.
- Frontmatter extraction reads the last block while writing replaces the first. Required-key
  validation is not semantic schema validation. Some artifact/link parsers skip all input
  and return a zero-denominator success; UAT's partial inventory is rendered as All Clear.
- SUMMARY counts, status strings, copied requirement IDs and automatic human approval can
  precede actual verification. Parent UAT/debug gaps are marked resolved before regression
  and without a finding-to-fix mapping. These findings do not resolve any current Zeus issue.
- Schema drift detection consumes declared file text and recent commit/summary command text,
  not successful execution against the intended DB. Shared/scoped configuration reads differ.
- Documentation workflows have queue/manifest/path and sequential/parallel validation
  differences; verify-only can write and remove evidence. Preserve defaults that avoid
  overwrites, bounded repair and explicit unknowns, but bind publication to actual evidence.

The primary merge-back test file contains 13 node:test cases with real Git-oriented oracles;
it was read, not run. Delegated original executions are zero. Static Windows branches and
model aliases do not establish OS qualification or Astra/Sol/Terra competence. Root/Claude
corrections explicitly withdraw search-based absence claims, runtime-enforcement claims
from prose, one-line privacy closure and unmeasured false-positive rates.

Coverage now has 1,778 paths with records and 958 unreviewed out of 2,736 tracked paths.
Recorded dispositions include body-only/static review with call/test trace pending. Extra
local assets retain a separate denominator. Full analysis, transitive/license closure,
joint review of remaining scopes, Windows/Linux/WSL qualification, actual human E2E,
qualified model transfer and adoption remain incomplete. Samsung device work stays deferred.

The starting root revision's CI run 34348586337 completed all five jobs successfully; its
raw response is saved separately. That verifies incumbent CI only. Local checks for this
checkpoint have separate receipts. Issue closure still requires implemented correction,
exact-revision acceptance evidence and required human approval. Operating harnesses and
deployment were not replaced.
