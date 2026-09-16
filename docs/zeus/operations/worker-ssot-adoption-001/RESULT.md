# SSOT-first worker guidance: actual autonomous delivery

2026-09-17. Run `worker-ssot-adoption-001` accepted and promoted candidate `13408e3` from
specification base `c7fecbf`. The final PR records CI and merge disposition; this runtime receipt
does not grant merge/deploy authority or certify general model behavior.

## Result

The existing worker-v1 profile now asks the Claude worker to find the authoritative definition,
callers, tests/evidence and relevant sibling implementations before introducing functionality.
It distinguishes reuse/improve/migrate/justified-new, preserves unknown search results, avoids
duplicating authority or copying known defects, and requires compatibility/rollback/retirement
for improvement or migration. Routine authorized work proceeds; consequential choices go to the
lead as one evidence-backed question. Fixed criteria end the task; minor opportunities are notes.

Only the three assigned worker files changed. The document is 5977/6000 characters; the normalized
digest matches and the exact pinned code-quality source entry is appended. All previous guidance,
five source entries, hook bytes/digest, permissions, id/version and loader/runtime remain unchanged.
Source SHA-256 and Git blob identity were independently checked against the preserved raw bytes.
See [ADOPTION.md](ADOPTION.md) for adopted and rejected principles.

## Actual execution and checks

- Shipped autonomous entrypoint drove real SSOT research, independent proposer/attacker/arbiter,
  Claude implementation and independent Codex review. The research decision was `improve` with
  compatibility, rollback and retirement specified. Attacker findings were empty; arbiter accepted.
- Claude task `8b6a610c-0264-581a-a085-345c3e23c3ce`; independent review
  `4797bae3-41ce-4e1a-8435-adbec82a78b0` accepted. Both claimed commands were replayed: 2/2 checked,
  no missing, unknown or failed claims. No manual role answers or automatic repeats.
- Six executor starts and six actual invocation reservations (five Codex, one Claude), all settled;
  machine ledger 52 -> 58. No additional model invocation for this instruction-only change.
- Actual isolated PG contains five provenance nodes/four edges and a promotion receipt for the
  exact accepted execution/review. Runtime records and model prose are not promoted as general truth.
- Claude, independent reviewer and owner each ran the existing focused profile tests: 19 passed
  in each run, not 57 unique tests. Owner Ruff and manifest/source/size/allowed-path checks passed.
- 266 observation events and 12 audit records collected. Two collections, sink failures 0;
  quarantine/alerts 0, no pending termination, orphan reservation or live writer. The collector's
  own final 1021-byte event remains durable in its spool, not counted as already collected.

Raw evidence: D:/workspaces/zeus/artifacts/worker-ssot-adoption-001. [EVIDENCE.json](EVIDENCE.json)
binds original bytes, execution identities, review, checks and actual graph observations.

## Limits and nonblocking notes

The implementation invocation started under the previous profile. The accepted text is selected
by future runs after owner merge; this work does not demonstrate new-guidance adherence or measured
behavior improvement. Fixtures validate delivery compatibility, not model compliance. No upstream
code/automation is installed, no private incident/quality statistic is inherited, no source license
verification or full reference-analysis completion is claimed.

The new section is 988 characters, slightly above the suggested 750-950 but below the hard total
limit. Only 23 characters of headroom remain: a later guidance addition should consolidate existing
text within a separately scoped change. This does not block the current accepted document.

Some worker shell commands were policy-denied (including a Python one-liner); alternate allowed
read/hash commands completed the task. Denied commands are not execution evidence. The full suite
and Windows/Linux/integration results belong to CI, not the worker's focused report. #13 remains
open for its broader evaluation/selection/model-behavior requirements. Full source absorption and
long-term autonomous operation remain separate goals.
