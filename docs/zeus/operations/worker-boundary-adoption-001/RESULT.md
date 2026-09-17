# Accepted local guidance adoption and actual isolated execution

2026-09-18 KST. Refs #129; PR #130. Codex owns source selection, design and
acceptance; Claude implemented through Zeus. Final CI/merge status is recorded
on the PR, not inferred from this pre-merge report.

## Delivered

Selected general principles from the pinned Baldrix `qa-boundary.md` now belong
to the existing worker-v1 profile: read producer, consumer and authoritative
contract together; compare applicable envelope, type, null and state semantics;
fix the contract-violating side; verify the real affected path and state gaps.
No upstream prose or executable assets were installed. The complete old/new
guidance and ADOPTION condensation map were reviewed; prior authority, scope,
SSOT, migration, investigation, verification and reporting safeguards remain.

The profile is still 5998 characters. One source was appended (7 -> 8); existing
hook, grants, id/version and 6000 limit are unchanged. The existing provenance
count assertion was updated accordingly. No runtime or permission change.

Implementation/test head: `12c51ded635a5551d9c9ea7f745086dc8407ea87`.
New profile SHA256: `ba0269ddf428f9f5faba870debc812fb709e88af5b6d182cc4239b5c1bb85bc1`.
Built image: `sha256:ea660ebf8eb2cf064920f892acb4888366436a278497c30088cb4a05bb6dd054`
(`zeus-worker:boundary-001`), built from that head. Subsequent commits only document
assignment clarification and results. Future container operations must explicitly
select this image; existing sessions/default host execution were not switched.

## Evidence that decides acceptance

| Check | Observed result |
|---|---|
| Owner manifest/diff checks | Exact pinned source appended; other fields unchanged; scoped changes |
| Owner Windows profile + metadata tests | 49 passed, 1 skipped; ruff passed |
| Actual implementation correction | 50 profile/metadata tests passed in container; lint passed; isolated inspection 2/2 checked; independent lead accepted |
| Fixed synthetic acceptance baseline | 4 failed in credential-free, network-none container |
| New-profile actual Claude task | Read SPEC, consumer, producer and fixed tests; changed only consumer; 4 passed |
| Independent replay and review | 1/1 claim checked, no replay failures/mismatches; Codex lead accepted; read-only host review, no host candidate execution |
| Live delivery | Exact new digest; observed SessionStart=1 and PostToolUse=2 |
| Collection and cleanup | 39 observation records inserted; sink failures/corrupt/refused=0; worker and two verifier run receipts all removed |
| Credential scan | Exact token matches=0 among scanned operation files <=64 MiB; not a universal leakage proof |

Final operation `worker-boundary-129-canary-2`, worker
`0dd07c53-8b2f-5837-bcb9-d83b828fdc38`, decision
`4425b7ab-dad7-46f3-9e95-c5b32051baa9`.
Candidate `ca35ff4d5499013096a072773d563f6c4a3f5cf5`, baseline
`696063736d1e76dfd3631782196943ff9b39e233`.
Inspection `dedd597cd3e958eeacf40165330b32fe6fadd8a44d7140ea846cf2511492c6ae`.
Worker execution `sha256:b7416b224b579eceecd53d9669903025be67eb9373a926187e9adb9662e99fa9`;
lead execution `sha256:fe9a5d4ad3955346168eb63cd8289b2408f930fd16424a2f61102451c24aee45`.
The worker also listed workspace files before reading them; its only verification
command was the assigned pytest command. No claim of literal tool-level obedience
to every sentence or universal future adherence follows from this observation.

## Preserved unsuccessful attempts and bounded corrections

1. Long staging path failed before container/provider entry. The estimated longest
   path was 278 characters; the existing runtime-directory option shortened it to
   235. Windows path length is the suspected mechanism, not an authentication issue.
2. First actual adaptation passed 19 tests and failed the old source-count=7
   assertion. Owner had omitted that test from allowed paths. Worker reported it;
   gate refused before lead. A single scoped correction changed 7 -> 8 and updated
   the report. No provenance or test condition was weakened.
3. First new-profile canary passed all four functional tests/replays but additionally
   ran lint, which returned three EXE002 mount-mode warnings. Summary disclosed
   failure, but legacy test claims expected exit 0; gate refused before lead.
   Owner clarified that full/lint belong to owner and worker runs the named pytest
   check. One final task used the same baseline, image, contract and tests. No source
   modes, lint policy, functional expectations or runtime were changed to pass.

Ledger 109 -> 116: seven reserved slots, including the pre-provider staging failure;
six actual model starts (four Claude, two Codex). Reframes and explicit ceilings
are retained in SPEC. No further model calls, automatic retries or budget reset.

## Limits and residual disposition

This is one rewritten local guidance asset, not complete local harness absorption.
The canary is owner-authored synthetic workload using real modules and real models;
it establishes neither Code Tutor acceptance nor causal improvement from the new
instructions. Upstream anecdotes and license chain to referenced text remain
unverified; no copied prose/executables depend on them. Existing isolated-runtime
ownership/recovery evidence is reused because runtime is unchanged. Global hooks,
scheduler, permission expansion and ontology promotion are outside this delivery.
The synthetic mount-mode lint warning is documented, not a new operational blocker.
Final repository CI owns the full suite. Large raw evidence stays on D; EVIDENCE.json
binds individual files, receipts, execution artifacts and local checks by hash.
