# SSOT-first worker guidance adoption

2026-09-17. One bounded delivery under the user's continuing authorization. Codex owns source
analysis, design and acceptance; actual Zeus Claude implements; independent Codex reviews.

## Outcome and scope

Carry the user's SSOT-first reuse/improvement/migration rule from autonomous research into the
existing Claude worker profile. Adopt selected sibling-discovery principles from the pinned
Baldrix code-quality guide, rewritten for Zeus. Do not create a parallel profile, loader or gate.
Success is an accepted profile/manifest update, existing profile checks, actual autonomous
research/debate/implementation/review/provenance cycle and Windows/Linux/integration CI.
This is delivery compatibility, not proof that guidance improves model behavior.

## Evidence and decision

Owner read the full 6854-byte pinned `skills/_common/code-quality.md`; identity is source.json.
Its original manifest inventory and snapshot hash match. The guide says to inspect existing
sibling implementations before designing another instance and avoid a separate duplicate lane.
Its private incident figures, mandatory numeric refactoring thresholds, blanket interface/DTO
rules, automatic skill gates and historical performance are not adopted or verified. No upstream
code runs, dependencies or text are copied; principles are rewritten. Upstream license and private
incident links were not verified, so no source distribution/license claim is made.

Existing SSOT: resources/worker-profile-v1.md and .json -> adapters/worker_profile.load_profile
(LF-normalized UTF-8 digest, <=6000 characters, refused on mismatch) -> adapters/claude_cli.py
runtime.worker_profile selection -> --append-system-prompt / per-run hooks -> recorded delivery.
tests/test_worker_profile.py covers loading, tamper refusal, hook subprocess and transport fixtures.
Autonomous SSOT fields already exist in domain/autonomous.py; this task extends guidance only.
Baseline document is 4989 characters. Existing generic reuse sentence is insufficient to express
the user's definition/caller/evidence and migration disposition requirements. This is a scope gap,
not evidence of a production failure. source.json describes the narrow owner-selected adaptation;
it does not change the full-analysis coverage ledger or claim complete source absorption.

## One implementation batch

Allowed worker files only:
- src/codex_harness/resources/worker-profile-v1.md
- src/codex_harness/resources/worker-profile-v1.json
- docs/zeus/operations/worker-ssot-adoption-001/ADOPTION.md

Add one concise English section, about 750-950 characters, keeping the whole document <=6000.
Preserve existing investigation, verification, command reporting and permission rules.
The section must convey:
1. Before new functionality, find the authoritative definition, its callers, tests/evidence and
   one or two relevant siblings within the assigned scope. Search absence is unknown, not proof
   that no implementation exists; record searched scope and remaining uncertainty.
2. State reuse, improve, migrate or justified new implementation. Existing mechanisms should be
   improved/migrated rather than given a competing source of truth. Do not copy a known defect
   merely to conform. Record material incompatibility and the smallest coherent alternative.
3. Improvement/migration identifies compatibility, rollback and retirement of the old authority.
   Routine authorized choices proceed; consequential product/authority choices or scope expansion
   go to the lead as one evidence-backed question, not a new approval loop for every edit.
4. Stop when the fixed criteria pass; unrelated/minor opportunities are follow-up notes.

Update document_sha256 using the existing normalization. Append exactly the source.json entry
to sources. Keep all previous sources, id/version, hook bytes/digest, permissions and limit.
ADOPTION.md in Korean states adapted/rejected principles, SSOT paths and limits. This implementation
call starts with the old profile, so it cannot prove the new guidance was used. Future selection
loads the new profile after merge; no additional behavioral canary is required for this prose change.

## Fixed acceptance matrix

| Path | Evidence / condition |
|---|---|
| Normal | Section has the four requirements; only three allowed worker files change |
| Identity/size/error | Existing loader accepts exact digest and <=6000; existing tamper/size refusals pass |
| Delivery | Existing hook subprocess/transport tests pass; fixtures are not real model compliance |
| Unknown/authority | Unknown search result stays unknown; product/authority choices go to lead, no self-approval |
| Migration | Compatibility, rollback, retirement named as implementation planning requirements |
| Timeout/restart/concurrency | Runtime unchanged; reuse accepted autonomous bounds, no new retry or writer |
| Platforms | Existing targeted checks plus final Windows/Linux/integration CI; no host setting changes |
| Cleanup | Raw evidence on D, existing dirty analyses preserved; no upstream install/process |

Worker runs `python -m pytest tests/test_worker_profile.py -q` and `python -m ruff check .`.
No new mirrored tests; no full suite by worker. Owner/CI owns final checks. Exact commands in tests,
outcomes/skips in summary. Independent review checks the same matrix, critical evidence-backed
blockers only. Scope expansion requires reframing this document, not recursive minor review.

## Execution and completion

Use shipped `autonomous run`, immutable goal/base/packet, four actual Codex design sessions,
Claude worker and independent Codex reviewer. Six starts maximum; machine ledger 52 -> ceiling58,
Claude declared USD2 / timeout600s; absolute run deadline60min. No automatic retry or budget reset.
No automatic merge, deployment or ticket closure. Owner merges after acceptance and CI; #13 stays
open unless its broader criteria independently close. Record source, candidate, calls, logs,
promotion scope and failures in RESULT. The current whole-task agreement remains authoritative.
