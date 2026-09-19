# Conductor delivery batch: actual results and limits

Worker Claude, 2026-09-18, base 43ceab5bf354994d1f75059767bcdd160536c5f5. Implements only the SPEC
section "Conductor delivery batch". No provider call, live run, git CLI, runtime state change or owner
SPEC edit was made. Git was unusable in this session (dubious-ownership refusal, no approval surface),
so nothing was committed; the diff is the working tree.

## Change

- `adapters/autonomous_roles.py`: `council_delivery(role, details)` builds the required inline
  projection for research_lead, improvement_lead and conductor (role, run_id, base_revision, round,
  packet, packet_digest, dba_report, snapshot/report digests, relay, acceptance_criteria,
  blocker_rule, plus research_proposal/improvement_proposal where the task carries them) as deep
  copies of the exact task values; `ssot` and `prior_outputs` are named by RFC 6901 pointer
  (`/ssot`, `/prior_outputs`) with the exact reader argv list. A missing mandatory field is a
  `ContractError` raised in `execute_role` before `_run`. `role_context(cwd)` is the
  pre-implementation read-only context (no candidate, worker or verifier asserted). The conductor
  objective gains phase guidance (decide from inline inputs, account for all findings, keep unknowns).
- `adapters/executor.py`: `_run(..., delivery=None)`; with a delivery the raw task is not added as
  optional inline evidence (the hash-bound artifact stays in `external_context`), the projection is
  `required.council_delivery`, and `read_only` + `action == "dge_role"` sets `required.role_context`
  instead of the candidate `review_context`. Review phases are unchanged.
- `adapters/app_server.py`: `READ_ONLY_INSTRUCTIONS` is phase-neutral; all previously tested phrases
  remain. Task details, downstream binding, digests, snapshot guard, deadlines, retries and the
  compiler budget (28000/6000) are unchanged.
- `docs/contracts.md`: INV-AUTONOMOUS-001 paragraph on delivery.

## Verification actually run

`python -m pytest tests/test_council_delivery.py tests/test_autonomous_roles.py tests/test_council_roles.py
tests/test_external_context.py tests/test_app_server.py tests/test_context_recovery.py -q -p no:cacheprovider`:
92 passed. `python -m ruff check .`: one unused import in the new test found and removed; rerun
result is recorded in the worker summary. Full suite not run by the worker (owner/CI).

Synthetic, labelled fixtures in `tests/test_council_delivery.py`: three debate roles through the real
`Executor._run`/`compile_context` with a fake runtime; real `artifact_reader` subprocess pointer read of
`/ssot` from the original artifact; size-matched conductor (whole details > 22000 bytes, inline part
below it, prompt <= 22000, evidence list empty, artifact == canonical details); missing input refusal
(six fields) with a forbidden runtime; injected required overflow refused by the existing compiler
rule before the provider; deep-copy immutability; candidate-review control keeping `review_context`
and the isolated wording.

## Correction 005 (2026-09-19, base 741fd68): complete-prompt denominator

Per CONDUCTOR-REVIEW-001 the retained conductor input compiled to 23377 bytes (projection 17819) against
22000. This correction only removes repeated advisory wording and non-authoritative isolation metadata;
no inline meeting content, raw ref, pointer argv, budget, deadline, retry or snapshot guard changed:

- `role_context.isolation` is the identity reference `{mode, digest}` of the host isolation configuration
  (`isolation_reference`), not the full worker container summary; `interpreter`/`src` nulls dropped;
  instruction shortened (same phrases: no candidate commit, do not create, modify or delete).
- `council_delivery.reading` is one sentence pointing at the executor's `artifact_reader` rules; pointer
  entries drop the redundant `inline: false`; the conductor phase rule is stated once in `guidance` and
  the conductor objective only points at it.
- `task_contract` omits a field the projection already carries verbatim (`acceptance_criteria`).

Measured in `test_complete_compiled_prompt_with_representative_metadata_fits_the_budget_for_every_debate_role`
(SYNTHETIC/INJECTED: docker isolation config, deep artifact root and checkout paths, fake runtime):

| Role | Projection bytes | Complete prompt bytes | Overhead before -> after |
|---|---:|---:|---|
| research_lead | 13717 | 17589 | 4731 -> 3872 |
| improvement_lead | 14511 | 18682 | 5030 -> 4171 |
| conductor (projection >= 17819) | ~18140 | refused, `Required contract exceeds budget` | ~5400 -> ~4210 |

**Not solved.** The conductor overhead fell by about 1200 bytes but the complete prompt with an
owner-sized projection still exceeds 22000 in this fixture, so the deciding regression FAILS for the
conductor and is left failing on purpose (fixed criterion, not bent to the result). The remaining
overhead is the generic per-execution blocks (`artifact_reader` 670, `external_context` 622,
`role_context` 670, conductor objective ~430, policy/versions/recovery/binding ~630, outer envelope) plus
the delivery wrapper (~600). Fitting 17819 + this floor needs a structural choice the lead owns: for
example a delivery-only compact `artifact_reader`, dropping `external_context.file`, or moving one
more inline field (e.g. `research_proposal`, already reachable under `/prior_outputs`) to a pointer.
None of these was made here. Owner retained-input replay has not run against this correction; no live
timing claim exists.

## Correction 006 (2026-09-19, base 9450c5e): delivery-only reader descriptor

Implements only the SPEC section "Final scoped delivery fix with remaining slot". Worker Claude, no
provider call, live run, git CLI, runtime state change or owner SPEC edit. Files touched:
`src/codex_harness/adapters/executor.py`, `tests/test_council_delivery.py`, this file.

- `artifact_reader_handle(root, ref, file=True)`: a council delivery passes `file=False`, so
  `external_context` is exactly `{ref, reader_argv_prefix}` (the path is derivable from `--root`/`--ref`).
  Recovery source handles and every non-delivery prompt keep the `file` key.
- `ARTIFACT_READER` (module constant, same content as before) is the reader block of every non-delivery
  prompt. `DELIVERY_ARTIFACT_READER` replaces it only when `delivery` is present: one argv list of
  `reader_argv_prefix` plus a `not_inline` operation, never a shell string, quote every element if a
  shell is unavoidable, continue with `--cursor` = `next_cursor`, output JSON bounded by `--limit` with
  `content`, `truncated`, `next_cursor`. No operation catalogue: the exact pointer argv arrays already live
  in `council_delivery.not_inline`.
- A delivery prompt that carries recovery sources (a retried attempt with a bound checkpoint/progress row)
  gets `ARTIFACT_READER` back, because those refs list no operation. Injected test covers it.
- Inline meeting data, refs, findings, pointers, role_context, consumers, deadlines, budgets, retries,
  snapshot guard and the overflow refusal are untouched; no fixture input or assertion was changed.

Measured with the unchanged representative fixture (SYNTHETIC/INJECTED: docker isolation reference, deep
tmp paths, fake runtime; Linux, this checkout; the conductor total comes from a scratch harness with a
loosened compiler budget whose tmp path is 18 characters shorter in two places, so the real test path is
about 36 bytes larger):

| Role | Projection bytes | Complete prompt before | Complete prompt after | Result |
|---|---:|---:|---:|---|
| research_lead | 13717 | 17589 | 17037 | passes |
| improvement_lead | 14511 | 18682 | 18130 | passes |
| conductor | 18813 | ~22944 | ~22410 | still refused, `Required contract exceeds budget` |

Per-block bytes after: `artifact_reader` 670 -> 335, `external_context` 586 -> 405 (path-dependent);
`council_delivery` 19492, `role_context` 670, `objective` 418, `policy` 181, `versions` 157,
`research_context` 174, `recovery` 117, `acceptance_criteria` 55, `project_skills` 65, `task_contract` 2.

**Not solved.** The two SPEC-named cuts save about 534 bytes; the conductor regression needs about 950 in
this environment, so `test_complete_compiled_prompt_with_representative_metadata_fits_the_budget_for_every_debate_role[conductor]`
still FAILS and is left failing on purpose (fixed criterion, not bent to the result). Note the fixture's
conductor projection is 18813 bytes, about 1000 above the owner's 17819 replay, which the SPEC records as
already fitting at 21917/22000 before this change. The remaining executor-owned delivery overhead that is
advisory or empty (`recovery.instruction` on an empty source map ~95 bytes, empty `task_contract` ~18) is
not enough to close the gap and was not cut; `acceptance_criteria` and `policy` are compiler-required.
The larger remaining blocks (`role_context.instruction` and `cwd`, the conductor objective, the delivery
`reading` sentence) live in `autonomous_roles.py`, outside this correction's allowed paths. Closing the
gap is a lead decision: shorter role/objective wording there, or a different fixture denominator.

Verification actually run (this checkout, Linux, base 9450c5e): the named focused set
`python -m pytest tests/test_council_delivery.py tests/test_autonomous_roles.py tests/test_council_roles.py
tests/test_external_context.py tests/test_app_server.py tests/test_context_recovery.py -q -p no:cacheprovider`:
95 passed, 1 failed (the conductor regression above). `python -m ruff check .`: one import-sort finding in
the new test import, fixed, rerun clean. Full suite result is in the worker summary. No owner retained-input
replay ran here; no live timing claim exists. Root Codex review is independent and has not run.

## Correction 007 (2026-09-19, base 2f86310): measured whole-layout batch

Implements only the SPEC sections "Prepared whole-layout batch" and "User direction" (the input-layout fix;
no subscription policy or UI work). Worker Claude, no provider call, live run, git CLI write, runtime state
change or owner SPEC edit. Files touched: `src/codex_harness/adapters/autonomous_roles.py`,
`src/codex_harness/adapters/executor.py`, `tests/test_council_delivery.py`, this file. The reader edits of
the timed-out attempt (`DELIVERY_ARTIFACT_READER`, `external_context` without `file`) were already present
and are unchanged. All advisory changes were applied together, as the SPEC proposal measured them:

- Conductor objective: "Arbitrate the supplied proposals. Account for every finding; never defer a critical
  finding." plus the declared verdict/disposition enum lists, the snapshot_digest/report_digest echo and the
  pointer to `council_delivery` (whose `guidance` still states the phase rule once).
- `role_context(isolation)`: `phase`, `isolation` (`{mode, digest}` identity or null) and `instruction`
  only ("Read-only at the pinned base; no candidate, worker or verifier has run. Do not execute
  code/tests/scripts or change files. Return structured output only."). The `cwd` and the null
  `candidate`/`worker`/`verifier` fields are dropped; the instruction states the same phase fact.
- `council_delivery.reading`: "Read not_inline from the original external_context artifact:
  reader_argv_prefix plus operation; follow artifact_reader rules."
- Executor, delivery prompts only: an empty `task_contract` is omitted (every contract field is inline); a
  prompt with no recovery source carries `recovery: {sources: {}}`. A nonempty recovery keeps its
  instruction and the full reader catalogue (injected retry test); the candidate-review control and every
  generic prompt keep `task_contract` and the recovery instruction exactly (control test extended).
- Unchanged: inline meeting data, raw artifact ref, pointer argv arrays, digests, critical/materiality and
  unknown rules, cursor/output bounds, consumers, deadlines, budgets (28000/6000), retries, snapshot guard,
  overflow refusal, missing-input refusal. The representative fixture input and its >=17819 projection /
  <=22000 complete-prompt assertions are untouched; advisory assertions moved to equivalent invariants.

Measured in the unchanged representative regression (SYNTHETIC/INJECTED: docker isolation reference, deep
tmp paths, fake runtime; Linux, this checkout, base 2f86310):

| Role | Projection bytes | Complete prompt before (006) | Complete prompt after | Result |
|---|---:|---:|---:|---|
| research_lead | 13717 | 17037 | 16500 | passes |
| improvement_lead | 14511 | 18130 | 17593 | passes |
| conductor | 18813 | ~22410 (refused) | 21768 | passes, 232 bytes under 22000 |

Per-block bytes after (conductor): `council_delivery` 19441, `role_context` 306 (was 670), `objective` 277
(was 418), `recovery` 14 (was 117), `task_contract` absent (was 2 plus key), `artifact_reader` 335,
`external_context` 405, `policy` 181, `research_context` 174, `versions` 157, `acceptance_criteria` 55,
`project_skills` 65. The margin is fixture-specific and path-length dependent (external_context carries the
tmp root); it is not a production guarantee and no live timing claim follows.

Verification actually run (this checkout, Linux):
1. `python -m pytest "tests/test_council_delivery.py::test_complete_compiled_prompt_with_representative_metadata_fits_the_budget_for_every_debate_role" -q -p no:cacheprovider -s`:
   before the change 1 failed (conductor, `Required contract exceeds budget; split task`), 2 passed; after
   the change 3 passed with the sizes above.
2. `python -m pytest tests/test_council_delivery.py tests/test_autonomous_roles.py tests/test_council_roles.py
   tests/test_external_context.py tests/test_app_server.py tests/test_context_recovery.py -q -p no:cacheprovider`:
   96 passed.
3. `python -m ruff check .`: all checks passed.

Not run here: the full suite and CI (owner), the owner retained-input no-model replay, any live council.
Git was unusable in this session (dubious-ownership refusal; even a read-only status with a
safe.directory override needed an approval that had no surface), so the changed-file set is the four files
named above as edited by the worker, not a git listing; nothing was committed and no automatic review was
triggered or is claimed.

## Limits

- The lease-bound `execute_role` normal path (store-owned task row, reservation, checkpoint) is not
  exercised in the unit harness; the refusal path runs through `execute_role`, the delivery path
  through the identical `_run` call without a lease.
- The isolated review control is a static source check, not a constructed config.
- No live timing result exists; nothing here shows the run003 conductor deadline is solved. Snapshot
  age, unknown verdicts, strict consumers and the 300 s policy are untouched.
