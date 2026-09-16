# CI separation: verified delivery

2026-09-16. Goal: remove duplicate feature-branch validation and make operations-document edits
lightweight while preserving full code validation. Scope and acceptance remain in `SPEC.md`.

## Implementation and independent acceptance

- PR #111, candidate `7399c14480452ac54621ad4dcfb131382c08f393`. Real Zeus Claude worker completed one implementation;
  the executor independently checked all 3 evidence claims (`all_checked`). Focused scope tests:
  62 passed, 1 Windows symlink-privilege skip. Git-mode routing checks still ran on Windows;
  Linux CI exercises the real symlink and newline/tab history cases.
- Actual Codex lead review accepted this candidate. Its selected focused verification reported
  58 passed, 1 skipped and Ruff clean; this is a subset, not the entire focused suite.
- Owner full Windows PG/Redis verification: 1998 passed, 21 skipped; Ruff clean.
  The existing optional checks retain their skip conditions. No model self-report substitutes
  for this JUnit result.
- Redis assignment/result and PostgreSQL task/review records remained linked. The cycle stopped
  at 2/2 executions, `awaiting_operator`; another step returned `none`. No release was queued.
  Machine call ledger reached 26/26 without resetting prior slots. No further model calls.
- Observation collection: 67 worker + 39 reviewer records, 106 total, sink failures 0.

## Real GitHub execution

[Implementation run 35096277064](https://github.com/trevi00/zeus/actions/runs/35096277064):
`pull_request`, attempt 1, success. The branch had no duplicate push run. Full routing ran all
five existing heavy jobs (four OS/Python matrix jobs plus PG/Redis integration), with `changes`
and `CI gate` also succeeding; `docs` was skipped. Total executed jobs: 7.

Baseline PR110 at d783cf8 ran push 35093122050 and PR 35093126192: 10 heavy jobs total and
5087 summed job-seconds. This implementation PR ran 5 heavy jobs plus 2 routing/gate jobs,
2475 summed job-seconds. These are observations from different runs,
not billing measurements, causal latency estimates or a guaranteed speedup.

This RESULT-only follow-up PR exercises the actual docs route after implementation merge.
Its run ID, mode, job results and duration will be recorded in the PR body/comment after completion
without another commit/re-run solely to insert its own execution ID. Required result: changes,
docs and CI gate success, all test/integration work skipped, no duplicate branch push run.
Main push remains enabled and separate; a docs-only main push can also take the docs route.

## Limits and stopping point

Only regular Markdown strictly below `docs/zeus/operations/` is lightweight. Other Markdown,
contracts, JSON, workflows, runtime, unknown paths and uncertain comparisons remain full.
Gate failure cases and PR cancellation wiring were checked locally; a live forced-failure or
superseded-run cancellation experiment was not performed. Branch protection remains unchanged;
`CI gate` is a workflow verdict, not an administrative merge restriction.

This completes the bounded CI change after the follow-up route passes. It does not complete all
unattended-operation conditions, fix the previously recorded PROGRAMDATA replay issue, or change
runtime task policy. Broad issues #13 and #20 remain open. No further exploratory work is part
of this delivery.

## Evidence

Raw files remain at `D:\workspaces\zeus\artifacts\ci-separation-001`; only this compact summary is
tracked. Hashes identify local evidence, not claims that raw files were publicly uploaded.

| Relative raw evidence | SHA-256 |
| --- | --- |
| `worker-001/receipt.json` | `2dac55f6db27850c985c21cbc3ad0f54bbd76201027befaa5f7c3055c45d82ec` |
| `lead-review-001/receipt.json` | `f26cb1736acbc7f42e48b40f0e9e3f60cf30c3c41548ef53e9780a9a60e92bfc` |
| `acceptance.json` | `49613cfee99cdcb3c69d8a72d40b5ac8b8b77355831b247f49e400d021c5bca8` |
| `independent-checks/result.json` | `050df85e05d613666037e69c03afd0eeb70ccc167313ae0866144500d1532f6d` |
| `independent-checks/junit.xml` | `a68d03905d2e1bc15785965c6be69b7052d71b2dfcef5847c58fd4c7720c0b08` |
| `independent-checks/pytest.log` | `315646d6fef2e85c3e694f8de830036649a2b31c9da71c83356d1937e57065a5` |
| `baseline-ci.json` | `2c5fe12a27a7ebbb4fb4983fa3cad0c92090b5b3025d3f372e3d9c76b1393f91` |
| `ci-35096277064.json` | `184bad29d412aad87c78da1e4c3bcdcbeced3128e43261dce5b2107714100ee9` |
