# Lane A — experience-aware worker context

Operation parallel-adoption-001, Lane A only. Files changed: `src/codex_harness/resources/worker-profile-v1.md`,
`src/codex_harness/resources/worker-profile-v1.json` (digest only), this file.

## Source binding

- Experience source read in this checkout (repository revision 14956d22485c709504e575a52a65a914d81f2aa8 as
  supplied by the task envelope): `docs/full-analysis/harness-experience/README.md`, `trace.md` sections T1
  and T2, and `validation.json`. The partition pins upstream harness revision
  a3f8b3be9a0a389329de6e16a6c7db81782041a3 (93 paths + 25 observed versions). No file hash was computed here
  because the lane permits only the three named commands; the reviewer can hash the paths at that revision.
- The trace findings are source-review observations of the upstream curator and repair-tier code. They are
  NOT Zeus runtime defects, fresh executions or new incidents. Nothing from the upstream implementation,
  its lesson bodies, occurrence counts or `trust=confirmed` markers was copied or adopted as fact.
- No profile JSON `sources` entry was added: the manifest test fixes the entry count at eight and the pinned
  digest cannot be computed with the allowed commands. Provenance for this adoption is recorded here instead.

## Source-to-rule mapping

Both rules live in the profile's existing "Existing authority" heading, as one new bullet; no new heading,
skill or always-loaded file was added.

| Trace finding | Profile clause |
|---|---|
| T1: `harvest_repairs` ingests every repair heading on any project-wide PASS, increments occurrences on each re-merge, and keeps the first 12 body lines so later root corrections never propagate. | "Supplied experience counts only when bound to its source revision, content and the run or incident observed; cite it by reference, inject only task-relevant lessons. Re-reading is not recurrence, an unrelated PASS validates nothing, a corrected source supersedes its lesson" |
| T2: `family_counts` sums FAIL per stage forever, ignores PASS, retractions and pipeline/run identity, so resolved history keeps escalating as a current incident. | "resolved history does not establish a current incident; contradictory or unavailable evidence stays unknown" |

The "unavailable or contradictory stays unknown" clause also carries the spec's requirement that missing
evidence is not coverage or validation; it is the same principle the profile already applies to empty
searches and unrun commands.

## What was done to make room

The profile was at 5998 of 6000 normalized characters before this change and is at 5988 after. Existing
sentences were shortened without removing any rule; the strings asserted by `tests/test_worker_profile.py`
("Verification before completion", "`tests` holds only the exact commands you actually executed",
"No arrows, results, pass counts") are unchanged. No permission, hook, authority or scope wording was
expanded.

## What this delivery is and is not

- Source review: the T1/T2 findings were read and mapped as above. Only README, trace.md and
  validation.json were read for this lane; the other partition files (analysis.json, notes, ledger
  evidence) were not re-reviewed here.
- Guidance delivery: the packaged profile text is delivered to a worker by `--append-system-prompt` and
  verified by digest and size at load time. The focused profile and metadata tests exercise delivery,
  digest and limit against a protocol child, not against a model.
- Behavior: whether a worker following this profile actually declines to count re-reads as recurrence, or
  actually separates lifetime failures from a current incident, is UNMEASURED. No model run, canary or
  before/after cohort was executed for this lane. Efficacy is not inferred from delivery and is not a
  blocker to adopting the guidance; it is a follow-up measurement, not a claim.
- This is not mechanical enforcement, not proof of model obedience and not formal promotion of any
  upstream lesson into Zeus knowledge.

## Commands run for this lane

- `python -m codex_harness.adapters.worker_profile_metadata` before the edit (exit 0, 5998 characters),
  after each document revision (exit 1 stale digest, reported 6274, 6073, then 5988 characters), and after
  the manifest digest repair.
- `python -m pytest tests/test_worker_profile.py tests/test_worker_profile_metadata.py -q -p no:cacheprovider`
- `python -m ruff check .`

Results for the last three are recorded in the worker answer summary; the full suite, git commands, model
and service commands were not run by this lane per the task contract.
