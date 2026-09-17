# Ordinary dot-path support: accepted implementation and actual execution

2026-09-18 KST. Refs #132. Runtime/test source `e8b5c9795a58b87893c71fff41e70190c8fbe353`.
Codex selected the contract and acceptance matrix; Claude implemented through Zeus;
independent Codex accepted. Final CI and merge status are recorded on the PR.

## Delivered and verified

One shared path helper now accepts ordinary dot-prefixed project names, including
.github/workflows, .gitignore and nested hidden goal/source/scope paths. It continues
to reject traversal, roots/drives/UNC/backslashes, ADS/control/whitespace, wrong types
and .git at any depth in any letter case. Dot-prefixed trailing-period aliases are
refused; the optional dot counts toward255 characters and total cap1024 is unchanged.
Previously accepted non-hidden grammar remains unchanged, including its trailing-dot
allowance; existing isolation checks remain stricter there. No global grants, provider
profile, authentication or staging/import/ownership implementation was changed.

| Acceptance | Evidence |
|---|---|
| Linux isolated focused suite |255 passed,1 existing integration skip; lint passed; inspection2/2 checked |
| Windows owner focused suite |255 passed,1 existing integration skip; lint passed |
| Baseline countercheck |Only operation.py reverted:11 newly allowed cases fail,13 metadata refusal controls pass; restored module24/24 pass |
| Shared paths |Operation manifest/goal, plan, DGE sources and autonomous scope exercised in focused regressions |
| Filesystem seam |Real temporary Git staging/import test with hidden files; labelled fixture, no provider |
| Actual container canary |.github/GOAL.md bound; Claude directly changed .github/verified.md and .gitignore; three fixed tests and isolated replay passed; independent lead accepted |
| Owner acceptance |Exact candidate Git bytes and two-file diff confirmed; NO owner copy workaround |

The actual canary candidate is `30b4d50883b64b59ce5f2aa2711e9df97162ba2f` from `dd47eaaf1cf030cd6d1cc4610e7ada7c17661a45`.
Its operation is `dotpaths-132-canary2`, task `0c38aa3d-55b3-555d-984e-daedc3820b34`,
decision `832e2187-3b04-4374-aaed-18b970aaf407`. Implementation operation is
`dotpaths-132-implementation`, task `6d3180c7-a411-5dd6-9b08-ee7006344887`,
decision `e73a42aa-5a53-48b0-9cef-a0ed1325ccd1`. Execution and inspection identities are
bound in EVIDENCE.json and owner-acceptance.json.

Built image `sha256:2da7ea98796963a802a40594e6e78eddc182727196522642d02f6018d9764e4d` (`zeus-worker:dotpaths-001`) from the tested source.
Future isolated operations select this image and the merged host runtime. Existing
profile bytes remain unchanged; both accepted runs recorded its digest and live hooks.
Implementation collected111 observations; canary
collected41; sink failures/corrupt/refused zero.
The initial refused canary collected22 observations with no sink failure.
All11 recorded worker/verifier containers
were removed. Each launcher reports zero exact-token hits among scanned files <=64 MiB;
that is a bounded scan, not a universal secret-leak guarantee.

## Failures preserved and limits

Claude's first staging regression incorrectly expected adapter rejection of ..x; the
manifest is intentionally stricter and its rejection comes first. A later assertion
misread stripped git-status output. Corrected checks and diagnostic runs are described
in IMPLEMENTATION.md; final successful claims were independently replayed. No additional
implementation dispatch was needed. Owner's newly created Windows venv passed lint but its
interpreter was then blocked by app control before pytest. Existing interpreter plus
explicit accepted-source PYTHONPATH passed; OS policy was not changed. JUnit and launcher
facts are preserved. No operation failure or unknown was rewritten as success.

First canary directly edited the two dot paths and passed both target checks, but its
unchanged KEEP.md was CRLF in host replay. The owner had omitted a checkout-byte rule.
The gate refused before lead; its failed receipt remains in c. One corrected baseline
adds only .gitattributes '* text eol=lf'; tests/goal/task and expected bytes are unchanged.
The fresh c2 pair passed without relaxing assertions or changing runtime/global Git.
Same-frame rework explicitly extended the ceiling by one consumed worker call.

Ledger118->123: five settled calls (three Claude, two Codex), no automatic retries.
The canary is an owner-authored synthetic filesystem task using real models,
not GitHub publishing, Code Tutor product acceptance or continuous unattended scheduling.
Manifest grammar is not symlink/hardlink containment; existing isolation owns those checks.
Rollback requires no data migration but restores rejection of new dot-path manifests.
No additional path grammar, permission expansion or unrelated environment investigation.

Raw evidence: D:/workspaces/zeus/artifacts/p132. Large files remain on D; EVIDENCE.json
pins selected receipts, logs, baseline JUnit, owner checks and model execution artifacts.
