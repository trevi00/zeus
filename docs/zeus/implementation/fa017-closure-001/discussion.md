# Joint findings and root decisions

Actual read-only Claude sessions and raw receipts are retained beside this file.
Root implements; neither reviewer observation is human acceptance.

- Root reproduced the failure-receipt early-return omission in memory and real
  PostgreSQL. Claude's initial statement that every failure path was fenced was
  incorrect; its discussion explicitly acknowledges and corrects this. The agreed
  strict guard retains the original request digest and cleared-owner semantics.
- Claude found unguarded creation-time ordering and missing status. Root reproduced
  the former as a whole-claim `KeyError`, then added per-row containment and notice
  reasons. Scheduling now compares parsed aware UTC values, then task id.
- A queued/retry row with missing, naive or malformed `created_at` is blocked with
  `InvalidExecutionOrder`. No migration invents its time from cwd, heartbeat, id or
  current time. Operators must investigate retained data before repair. `submit`
  already writes creation times in the inspected baseline; we found no evidence
  of a formerly supported producer that intentionally omitted this field. Invalid
  status is contained with `InvalidExecutionState`. Terminal history is not sorted
  or rewritten. Notices grant no business authority.
- Root agrees to native shared/nested path and tied-time tests as executor fencing
  evidence. The project/retrospective extension fields are explicit fixtures; this
  does not claim production retrospective ingestion or authenticated tenants.
- The new normative time contract makes observed-discontinuity containment and UTC
  restart assumptions explicit. OS clock-step, suspend/VM-resume and cross-host
  behavior remain unmeasured conditions. No host clock is changed. This bounded
  criterion assessment must be visible to the final human reviewer, not hidden
  behind CI success.
- Claude corrected its initially invented Samsung-device prerequisite, its claim
  that the archived evidence necessarily spans days, and its reading of AC7.
  Evidence ages must be calculated. Samsung work is outside this ticket. Exit 0
  and model review are not human acceptance.
- The implementation review requested actual actor-shaped decision fixtures and
  decision-state poison coverage; root accepts. An altered owner on a terminal
  retry row is rejected by the ordinary ownership/status path, not the new receipt
  guard; tests will distinguish the messages. The pre-recovery receipt rejection
  already exists in `test_execution_recovery.py::test_recovery_preserves_history_fences_replay_and_does_not_spend_attempt`
  for memory and PG and is included in the consolidated target. Add a literal
  historical request digest to make backward compatibility explicit.

No new issue is created. Closure evidence remains a draft until exact-revision
regression, criterion observations and configured external human approval exist.

## Final evidence audit

All five CI jobs and exact-revision local/WSL regressions passed. Eight bound
observations were imported without authority. Claude's evidence review correctly
noticed that the first six target-time observations also cited later full/CI
measurements. Root retained the original target observation time and removed the
later data from those six documents, then re-imported corrected canonical bytes.
The earlier files remain under `superseded-acceptance-timestamps/`; they are not
the current preparation input. Environment and criterion 7 use the last CI job
completion time, which is after the other measured runs.

Local Windows counts and CI counts are now explicitly labelled. Windows native
receipts resolve below `native-processes/`; WSL native receipts resolve below
`wsl/native-processes/`. Both sets are repository evidence files with verified raw
hashes; Claude's initial assertion that WSL receipts were only ephemeral was wrong.
No tests are re-stamped as fresh, and no human approval is inferred.
