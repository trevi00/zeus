# Joint environment and fixture review resolution

Codex read all 16 primary files / 49,545 bytes before viewing actual Claude's independent
opinion. Both then compared findings against direct source reads and the recorded isolated
observation. Initial opinions, prompts, raw outputs, process receipts and corrections remain
separate. The bounded conclusions here supersede broader wording in the initial reports.

Actual Claude session: 94684b4a-2623-469f-885f-59e56db5444a.
Initial process: exit0, 358.47084403038025 seconds, reported USD2.249078.
Discussion process: exit0, 176.12711930274963 seconds, reported USD0.8358099999999999.
Claude performed static reads only. It did not independently execute source or review the
three delegated GSD partitions in these two calls.

## Findings supported by original observation

Nine isolation scenarios and seven golden.run invocations used only scratch state/cases.
Five real child commands ran. The no-prior-value real_state branch leaves a newly assigned
override behind; valid prior-value restoration, fresh scratch creation, early bool rejection,
body exception propagation and changed-input SKIP-AXIS behavior provide controls. Equal
error values and same-size/same-mtime rewrites can appear stable, matching the helper's
explicitly limited equality contract. Stable must not be reinterpreted as available or passed.

Missing/invalid-but-parseable golden case definitions produce zero cases and no failures.
Duplicate names count twice; expected text can match stderr; invalid expect_exit is converted
only after command side effects. Expected nonzero exit remains a legitimate negative test.
The original gate and selected curator/quality consumers, read but not executed, derive
success from empty failure lists. The smoke's separate >=8 floor is a real defense with a
different trigger/consumer scope. No complete curator or promotion bypass was demonstrated.

## Agreed static boundaries and corrections

- Existing source read-only mounts and tracked directory markers are real defenses.
  Shared writable state is wider than a single role store. Deployment/mount enforcement
  was not tested by reading Compose or its string-based contract test.
- The researcher loop has seven script invocations, not six. Collector source count is
  a different denominator. Its service health probe checks only the research collector
  heartbeat, not complete health of all seven stages; other diagnostics may exist.
- pip installation failure prevents the DBA loop and exits its container. The subsequent
  loop masks iteration exit codes but preserves stdout/stderr. Neither invisibility nor
  heartbeat-only failure detection applies universally.
- DBA sync exceptions/missing ledger have explicit failure branches. Successful sync with
  zero events only warns and refreshes heartbeat. Whether zero is valid depends on the
  expected source workload; empty legitimate datasets must not be forced nonempty. Real
  PG behavior and exact source-to-projection parity remain unexecuted.
- Source PG is a disposable projection; Zeus PG owns runtime records. Destructive volume
  experiments and regeneration assumptions do not transfer. No fleet operation ran.
- 158 literal isolate() hits reported by Claude are discovery/presence only, not verified
  import order or isolation. The selected lint tests text presence. The README's dated
  76-file census is historical; its table totals72. Neither count is current acceptance.
- The flat sandbox default in tests/README is fixed in current code. Paragraph-deletion
  effects were not exercised; the whole AST and lint closure were not independently proved.
- A missing golden file differs from syntactically malformed YAML, which can raise.
  Policy-name absence and grep misses do not establish absence of every authority layer.
  No blanket machine-writability, unprotected semantic core or all-gate bypass is claimed.
- The aspirational20-50 golden count is not an agreed mandatory floor. Held-out flags,
  suppressed output details and a router-scan test are narrower than access-controlled,
  independently owned acceptance oracles. Source fixtures were not executed.
- The mount test handles strings heuristically and stringifies long-form objects. A valid
  long-form read-only mount may be rejected. Suffix exclusions alone do not establish a
  full bypass, and the test has separate role/infra checks that also matter.
- Chat seeding caps characters, not bytes, and splits frontmatter text without validating
  provenance. Current files fit; arbitrary bodies with separators need a stronger parser.
  This is not an observed malicious injection or inspection of private conversations.

The helper's equal caught exceptions are distinct from a probe swallowing its own errors;
both can remain equal but neither proves availability. The no-prior real_state branch has
the same static restoration issue on normal and exceptional exit; only the normal branch
was specifically observed. Avoid treating all exception restoration as proven correct.

Read diagnostics: an explicit UTF-8 retry fixed host cp949 receipt decoding without rerunning
source. An initial discussion-launcher generator had a Python quoting SyntaxError; no Claude
process started from that failed generator. The corrected launcher produced the one actual
discussion receipt above. Raw Read endpoints may include an extra EOF line; metadata hashes
and actual byte ranges provide the source identities.

## Disposition and remaining work

Primary16 and supporting15 have separate records. Fresh body review does not close full
call/test trace, licenses, Windows/Linux/WSL qualification, model authority/competence,
real service/DB/device/human acceptance or adoption. Original source tests, the nine golden
cases, gatewriter, curator/ledger mutation and fleet deployment were not executed. All931
pinned source files remained unchanged, the named container was cleaned up, and generic
process-tree termination remains unverified. Actual operating harnesses were unchanged.

These findings extend existing ticket topics for isolation, completion evidence, environment
binding and scenario denominators. They are advisory evidence, not implemented resolution or
permission to close an issue. Exact-revision acceptance and required human approval remain
necessary before closure.
