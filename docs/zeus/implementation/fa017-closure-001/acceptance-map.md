# FA-017 criterion-to-evidence map (human review pending)

This is a review index, not signed closure authority. Criterion numbers
below are human-readable 1..7; signed packet indices are 0..6. All seven criteria
remain exactly as captured from the PostgreSQL ticket in `ticket-scope.json`.

| Criterion | Existing implementation and measurement | Closure audit disposition |
| --- | --- | --- |
| 1: malformed/empty/missing fields preserve retry state | `acceptance/criterion-1.json`, consolidated output recovery tests | Passed explicit native fault-input tests; extension preservation is not native retrospective ingestion |
| 2: idempotent retry, budget, stale execution | `acceptance/criterion-2.json`, retry/recovery/rejection/identity suites | Receipt omission corrected; strict actor/agent/recovery checks and historical digest verified |
| 3: PG failure and commit/delivery gap | `acceptance/criterion-3.json`, consolidated PG/Redis kill and write-rejection tests | Actual rollback/restart/delivery observations passed |
| 4: shared/nested cwd, tied heartbeat, identity | `acceptance/criterion-4.json`, `native-processes/`, `wsl/native-processes/` | New native matrix passed; no authenticated multitenant claim |
| 5: finite values and clock/deadline contract | `acceptance/criterion-5.json`, normative `INV-EXECUTION-TIME-001` and consolidated clock tests | Bounded contract observations passed; actual OS clock-step/VM-resume remains explicitly unmeasured for human review |
| 6: explicit bounded recovery | `acceptance/criterion-6.json`, recovery/decision tests | Passed; operator label is not a human cryptographic signature |
| 7: Windows/Linux/WSL actual process/files/PG | `acceptance/criterion-7.json`, full/target/WSL/CI receipts | Exact solution revision passed; process tests are not model/human acceptance |

Eight canonical criterion/environment documents are imported as unverified
observations, with exact solution commit and current ticket revision/content hash.
`acceptance/imports.json` records their immutable references. A signing packet still
requires externally enrolled authority and current evidence age checks. Human
approval is absent. Historical receipts retain their original observation times;
repackaging an old run with today's timestamp is not new measurement.
