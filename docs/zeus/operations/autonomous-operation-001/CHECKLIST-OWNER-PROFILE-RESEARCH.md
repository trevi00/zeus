# Checklist owner-profile research result

Program `checklist-owner-profile-research-001`, cycle 1, implementation slot `.c001.impl`.
Base revision `6acb38e28a7d2bcfd1022e7e6ca564d64580270c`; goal `SPEC.md` sha256
`203d243ff5a478893bcf4541917d88a4b854afc63508b637f8a2b6c93615ce8c` (re-hashed by this task).
Scope: ONLY `cont-fe15931105e915769378e016` and `cont-6adfa87f8938c830ab60ac35`. Other jobs that
share reason `evidence_gate_refused` are neither diagnosed nor resolved here. This is a report, not
a repair verdict, an acceptance, a receipt or a hold release. No runtime file was edited.

## Council fields

- Question: are the two held attempts the same cause, and what existing-owner path repairs them?
- Answer: no shared cause. `cont-fe15` was an independent code rejection; `cont-6adfa` failed
  evidence inspection because of an owner test-profile error. The repair for `cont-6adfa` is
  evidence repair of the retained candidate under a corrected owner profile, with gates unchanged.
- Open policy gate: the receipt and hold coverage for `cont-fe15` (see Unknowns U1, U2).

## Facts (source: pinned SPEC and capture, read by this task)

F1. `cont-fe15931105e915769378e016` is the first correction of `autonomous-operation-001-release-checklist`:
    candidate `92da6a74`, task `93bb51d9`, review ref `71f5467e`. Independent review rejected it with
    two remaining findings (P1 unredacted parameter IDs in `release_suite.py` progress/reconciliation;
    P2 unbounded `process.wait()` after a tree-kill failure in `commands.py`). The earlier collection
    interruption fix was accepted. This is a **code rejection** (SPEC 13:20 UTC section).
F2. `cont-6adfa87f8938c830ab60ac35` produced candidate `adeab8c79b5c6b34832d88eac43607d70307ddef`.
    Evidence inspection
    `inspector6b2bfd54ff8aa9cc83ec1a51c1e6121bde01759794ae1851b08afd67f089cf70` refused it because
    the OWNER profile named `tests/test_commands.py`, `tests/test_check_results.py` and
    `tests/test_deployment.py`, none of which exist at that candidate. The worker reported exit 4 /
    no tests collected and lint exit 0. This is an **owner test-profile failure**, NOT an assertion
    failure and NOT an independent code rejection (SPEC 16:08 UTC section).
F3. The SPEC records that the owner later ran the candidate at 16:12 UTC on Windows with isolated
    PostgreSQL: 68 passing tests across the existing release_suite, release_runner, release_recovery,
    release_health, check_binding and runner_categories suites, plus Ruff, under a new versioned owner
    profile `release-checklist-evidence-profile-v2.json`. **Historical owner-recorded evidence**; not
    executed by this task, and it does not replace authoritative inspection or independent review.
F4. No independent review of `adeab8c7` exists yet (SPEC 16:16 UTC section).
F5. Hold `ed1af38692cd7198847816719bd556de1cd954b1d6c89112c42b9768c3aaf491` covers both jobs. The
    SPEC states the same continuation family does not establish a shared cause.
F6. The earlier scoped receipt `3f9db6c8bf6a253ef398a58092b9301fa83f2588e569d3f263cd99b2c2ed4cfa`
    covered intent `f3342d71…` and ONLY the original release-checklist job plus `cont-fe15`.
F7. The capture `docs/zeus/research-captures/checklist-owner-profile-research-001/001.json`
    (investigation `aab8c6d6…`, observed 2026-09-24T18:48:48Z, 9 job IDs, job_ids_sha256
    `93090f14…`) lists `cont-6adfa87f8938c830ab60ac35` but does NOT list `cont-fe15931105e915769378e016`.
    The SPEC 16:16 section recorded 19 jobs for the same investigation at an earlier point.
    The capture marks itself as an unverified symptom, not a cause.
F8. Existing owners in `src/codex_harness/domain/continuation.py`: route `evidence_repair` (owner
    `fleet`; completion = "new bound inspection and independent review of the successor"); research
    receipt schema `urn:zeus:continuation-research-receipt:1`, validated by `validate_research_receipt`
    and `check_research_receipt`, which requires the COMPLETE failed attempt set of the hold. The
    receipt is not an operation acceptance, a repair verdict or a promotion (`RECEIPT_AUTHORITY`).
    Owner entry point: `adapters/continuation.accept_research` (`zeus continuation research-accept`).

## Inference (not verified by execution)

I1. The two attempts have different causes: F1 is a defect in the candidate's code, and F2 is a defect
    in the owner's input with no code finding. The shared reason and family are a symptom (F5, F7).
I2. `cont-6adfa` needs **evidence repair**, not code correction. There is no proven code defect in
    `adeab8c7` to fix. Rerunning the correction would spend a correction attempt on an owner error.
I3. F3 is a strong discriminating signal that the candidate's declared checks pass. It is still not
    the authoritative inspection because it ran outside the bound inspector path.
I4. Whether `adeab8c7` resolves both F1 findings is decided only by independent review. This report
    makes no claim about it.

## Recommended scoped repair path (existing owners; no gate changed)

1. Keep every historical verdict: the rejection of `92da6a74`, the refusal of inspection `6b2bfd54`, the
   original evidence profile, receipt `3f9db6c8`, hold `ed1af386` and all unrelated job holds.
   Nothing is reclassified, deleted or rewritten.
2. The owner submits one scoped research receipt through `research-accept`. It names the hold's exact
   intent/policy/family, the COMPLETE attempt set {`cont-fe15…`, `cont-6adfa…`} with each attempt's
   evidence sha256 and inspection, the investigation, this program's accepted dispatch
   (run/manifest/snapshot) and immutable evidence refs. The domain validator decides; prose does not.
3. After the receipt releases the hold, route `evidence_repair` retains candidate `adeab8c7` at its
   retained workspace with the corrected v2 owner profile. Before dispatch, check every declared path
   against the pinned candidate (SPEC 16:08 UTC).
4. A new bound inspection replays the declared checks through the existing observations. Then an
   independent review of `adeab8c7` against both F1 findings. Only a pass at both gates counts.
5. If the review rejects, the normal correction route and correction budget apply. No bypass.

## Unknowns and unresolved policy gates (for the lead; not bypassed)

U1. Investigation membership. `check_research_receipt` requires the receipt's investigation to hold the
    exact attempts. The 18:48Z capture (F7) does not list `cont-fe15`. Unknown: does the
    authoritative Portfolio investigation still bind `cont-fe15`, or does another investigation? If
    neither, one receipt cannot cover the full attempt set of hold `ed1af386`. That is an owner and
    policy decision, not something this report can repair.
U2. Receipt reuse. Receipt `3f9db6c8` already covered `cont-fe15` for intent `f3342d71`. Unknown:
    whether hold `ed1af386` belongs to the same intent, and whether the validator accepts
    one attempt appearing in two receipts. Not checked by execution here.
U3. Why the membership dropped from 19 (SPEC) to 9 (capture). Not investigated: other jobs are out of scope.
U4. The inspector ID in the task is written `inspector6b2bfd54…`, and the SPEC says `inspection6b2bfd54`.
    This report assumes they are the same record. Not cross-checked against the store.

## Checks

Executed by this task: `python -m pytest tests/test_research_investigations.py -q -p no:cacheprovider`
and `python -m ruff check .` (results are in the worker summary). Not executed by this task: the owner's
68 Windows/isolated-PG tests (F3), the authoritative inspection, independent review, PostgreSQL variants,
host qualification, CI and the full suite.
