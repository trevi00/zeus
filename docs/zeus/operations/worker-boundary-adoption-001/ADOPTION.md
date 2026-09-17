# Boundary guidance adoption record (worker-boundary-adoption-001)

2026-09-17. Per SPEC.md and source.json, selected producer-consumer contract principles from
baldrix `skills/_common/qa-boundary.md` (cbb5c3e6) were rewritten into the packaged worker-v1
document. No new profile, loader, hook, permission, limit, runtime or test change. Rollback: revert
the three files together.

## Files changed

- `src/codex_harness/resources/worker-profile-v1.md`: new `## Assigned integrations` section with
  the four SPEC requirements (paired producer/consumer/contract read naming files and interfaces;
  applicable-only comparison of envelopes, fields/types, missing vs null, status transitions,
  acknowledgement vs final result; fix the violating side within allowed paths, contract changes go
  to the lead with compatibility/migration, never weaken validation or bend expectations to the
  bug; verify the real producer-consumer path, mocks/static reads do not replace required
  integration or user acceptance, missing real verification is a gap). Existing prose compressed.
  Metadata command: 5998 characters before, 5998 after; digest
  `ba0269ddf428f9f5faba870debc812fb709e88af5b6d182cc4239b5c1bb85bc1`.
- `src/codex_harness/resources/worker-profile-v1.json`: `document_sha256` updated; source.json
  appended verbatim as the eighth `sources` entry. id, version, hook and hook digest,
  character_limit, hooks, permissions, note and the seven earlier sources are unchanged.
- This file.

## Condensation map (every enumerated safeguard kept)

- Role/authority and "nothing you write grants approval or completion": opening paragraph. The bug
  section's "profile and hook receipts are guidance, not proof of adherence, acceptance or
  promotion; review authority unchanged" moved into the opening and now applies to every task.
- Objective-first reading: "Order of work" is one paragraph instead of three numbered steps; read
  objective/criteria/paths/code/tests first, smallest coherent change, reuse, verify, report.
- SSOT/disposition/compatibility/rollback/retirement: "Existing authority" bullets kept; heading
  shortened; "one or two relevant siblings" became "a sibling or two"; "approval loop per edit"
  became "per-edit approval".
- Review batches and evidence-based disagreement: first and last bullets merged; "review batch"
  became "batch"; "patch loops" became "loops".
- Allowed paths, untrusted evidence, no publication/host/home changes, no outside reads: Boundaries
  kept; the two "Do not" bullets merged into one; "handed to you" dropped.
- Verified interpreter, exact metadata command, Bash policy: Environment unchanged in meaning.
- Focused/full verification ownership, honest failure/skip/unknown reporting: Verification bullets
  kept; intro shortened to "A claim is not its evidence:"; "Report failures as failures ... skips as
  skips" became "Report failures with their output and skips with the reason"; "say what was not
  verified and why" became "say what and why". Test-pinned heading and phrases unchanged.
- Bounded investigations and controls, isolated old-behavior check, no retry-until-green, one
  consolidated report: bullets kept; the "Only for an assigned investigation..." intro line became
  the heading "Assigned bug investigations only"; "not historical observations" dropped after
  "label ... as such"; "attempted count with its denominator" became "attempts with denominator".
- Exact legacy/project-evidence answer semantics: Reporting kept verbatim except "In the
  structured answer" prefix and "those belong in" -> "those go in"; "not unrelated parts of the
  repository" dropped, "Bind the report to this change" kept.
- Continuation lines of list items are no longer indented (valid lazy continuation); saves the cap.

## Adapted and rejected

Adapted: paired reads of both sides plus contract, shape/state/optional-value mapping limited to
what applies, fixing the violating side, real-path verification with explicit gaps. Rejected:
global six-pattern gate, mandatory code generation, automatic loops, upstream incident/origin
claims, any upstream text, examples or executables. License chain unverified; prose rewritten.

## Limits and known gap

- This invocation ran under the old packaged profile; no adherence or effectiveness claim.
- `tests/test_worker_profile.py:238` asserts `len(manifest["sources"]) == 7`. The SPEC-required
  append makes eight, so that one test fails until the owner changes the constant. The test file is
  outside the allowed paths and was not edited. Full suite, image rebuild and canary belong to
  Codex/CI.

## Source-count correction (resolved; history preserved)

- Historical failure, kept as recorded above: the implementation batch ran
  `python -m pytest tests/test_worker_profile.py -q -p no:cacheprovider` and observed 19 passed,
  1 failed. The single failure was `test_the_metadata_command_is_one_exact_allow_and_every_earlier_grant_is_preserved`
  at the `len(manifest["sources"]) == 7` expectation; the evidence gate stopped there (SPEC,
  "Existing source-count assertion: owner scope correction"). The owner classified it as a
  specification omission: the test predates the eighth source and the SPEC required the append.
- Corrective batch, authorized by that SPEC section, changed only the expectation `7` to `8` in
  `tests/test_worker_profile.py`. Every other assertion in that test and file is unchanged,
  including the manifest key order, exact allow list, hook list, character limit, denies delivered
  unchanged and the single exact metadata grant. Profile document, manifest and hook were not
  touched; digest `ba0269ddf428f9f5faba870debc812fb709e88af5b6d182cc4239b5c1bb85bc1` and the
  eight sources are as recorded above.
- Verification for the corrective batch: `python -m pytest tests/test_worker_profile.py
  tests/test_worker_profile_metadata.py -q -p no:cacheprovider` and `python -m ruff check .`.
  Observed results are in the corrective batch's report, not restated here as expectations.
- Still not claimed: the corrective batch also ran under the previously packaged profile. No run
  under the new document digest has been observed in this delivery; that remains the rebuilt-image
  canary task and CI, per the SPEC acceptance matrix.
