# Bounded investigation guidance absorption

2026-09-16. Codex owns analysis/design/acceptance; Claude implements one selected asset through Zeus. The user selected one Claude call plus one Codex review, then stop. Preserve the existing 15 machine slots; cumulative cap 17, no retries/reset/automatic extension. Claude budget option USD3, timeout 900s; Codex review timeout 300s. The USD option is not a billing guarantee. LocalCycle cap 2, terminal awaiting_operator, no deployment.

## Source and decision

Source identity is in source.json: local .claude skills/_common/investigation-discipline.md at 7f2d97d. Codex read the complete file and reused docs/full-analysis/baldrix-common/diagnosis-notes.json. Working bytes differ only in line endings from the pinned blob. Upstream incident anecdotes remain documentary assertions, not independently reproduced Zeus evidence.

Adapt only the investigation principles into the existing packaged worker-v1 document. Do not install upstream hooks, import its modules, copy its incident prose, add routing/daemons, change permissions, or turn investigation into a repeated mandatory gate. Existing source inventory remains untouched.

## Implementation (Claude)

Allowed files ONLY:
- src/codex_harness/resources/worker-profile-v1.md
- src/codex_harness/resources/worker-profile-v1.json
- docs/zeus/operations/asset-operation-001/ADOPTION.md

Add one concise English section for **assigned bug investigations only**, approximately 1000–1700 characters, keeping the whole document <=6000 characters. It must say:
1. Read the actual failure evidence and trace the responsible code before claiming a cause. Inspect path-owning code before declaring data absent; do not import live helpers just to ask paths.
2. Distinguish observation, hypothesis and unknown. Use one bounded reproduction and a discriminating control when feasible; injected faults and synthetic fixtures are labeled, not historical observations. State environment/revision, attempted count/denominator and the variable actually changed when reporting measurements.
3. For a defect fix, demonstrate the targeted regression detects the old behavior when practical in an isolated disposable copy. Never revert the user's tree; if this check cannot run, state the gap. Do not impose mutation testing on ordinary documentation/new-feature work.
4. Stop at the assigned scope, time/call budget and acceptance criteria. Preserve failed attempts; do not repeat until green. If the same failure invalidates the design or repair requires broader scope, report one consolidated evidence/gap handoff to the lead. Nonblocking uncertainties remain follow-up notes; no automatic scope expansion.
5. These instructions and hook receipts are guidance/observations, not proof of model adherence, acceptance or knowledge promotion. Existing review authority remains unchanged.

Recompute the manifest document_sha256 using the existing normalized UTF-8 convention. Append ONE source entry using the exact source/path/commit/blob/pinned_sha256/scope/disposition fields from source.json; preserve all previous entries and hook digest/permissions/id/version. Do not add fields that imply measured model effectiveness.

ADOPTION.md is a short Korean explanation of what was adapted/rejected and limits. Do not duplicate the whole spec/source or claim new guidance was used by this implementation call: it starts under the previous packaged profile. Future calls load the accepted document; this operation proves construction/delivery compatibility, not behavioral improvement.

## Verification and acceptance

Run exactly the relevant existing profile tests and lint:
- python -m pytest tests/test_worker_profile.py -q
- python -m ruff check .

No new mirror tests or runtime changes are needed for this instruction/manifest-only change. Codex owns independent focused verification and final Windows/Linux/integration CI. Report full suite not run by Claude. Final tests array holds executed commands only, results belong in summary.

Codex validates complete instruction semantics against the five requirements, <=6000 character limit and digest, exact source binding, unchanged hook/permissions/runtime and allowed-path diff; existing tests exercise document loading/tamper refusal/actual hook subprocess/protocol-fixture delivery. Fixtures are not actual provider behavior evidence. Then actual independent Codex reviewer consumes the unmodified worker result and replay evidence, accepts/rejects, and LocalCycle stops at 2/2. No extra model canary is authorized. Windows actual operation; Linux CI only. Failed review/call stays recorded and stops the batch without retry.

The prior actual worker/reviewer cycle and this asset are separate generations. Earlier failure states are preserved. This is one absorbed asset, not all local assets or full unattended deployment.
