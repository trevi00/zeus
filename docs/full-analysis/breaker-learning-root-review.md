# Root checkpoint: breakers, learning and integration tests

Base Zeus revision: `2fd81d0a7bc7b6e26a0e1e8470a497ad9984b2ff`.
The four bounded folders contain 62 primary records: breakers001 3, lib002 23,
lib004 19 and harness-integration-tests002 17. Supporting records total 85, comprising
82 support rows and three explicit same-byte prior full-body references. Sixteen of
integration002's support rows reuse exact earlier ranges. Support is not new primary
coverage. Repeated primary paths must be deduplicated by the global ledger.

Root read the lib002 review/notes/per-file discussion, lib004 review and integration002
review, and checked their stated scope, evidence limits and unresolved work. Root independently
reviewed breakers001, compared actual Claude initial/discussion responses, and resolved the
differences in that folder. Claude's breaker discussion is not independent Claude coverage
for the three other folders; those areas retain that pending requirement.

## Findings that change the adaptation work

The breaker observation makes state ownership and persistence an implementation requirement:
admission cannot succeed without a durable owner, and stale results cannot change a replacement
owner's reservation. Explicit write/emit failures and unknown/corrupt states must survive the
transition into Zeus. Original unit tests passing does not close these gaps.

Lib002 exposes a related distinction between a claimed action and its receipt. Canary rollback
ignores a false return while reporting reversion; exceptions in the regression callback can
escape its rollback path. A dirty-path set comparison misses edits to already-dirty paths.
Budget emission can claim emission after delivery failure and counts characters rather than
actual model usage. Debate convergence and wrapper replay require exact current evidence;
presence, counters, historical convergence or skipped fixtures cannot establish acceptance.
The bounded notes retain the narrower branches where source guards already exist.

Lib004 extends this to self-improvement qualification. Graduation state can retain readiness,
watermark and drift after epoch restoration; direct promotion relies on readiness and a
literal token without proving a fresh scan. Repeated evidence can promote L2 facts, and edge
counts can inflate cascade strength. Pollution tuning records configuration that detection
does not necessarily consume. Missing module-level event-store append and swallowed probe
failures weaken the recorded basis for learning. These are static findings, not measured
production faults, and all source execution in lib002/lib004 remains zero.

Integration002 distinguishes actual product evidence from fixture intent. A synthetic operator
approval or a caller-supplied executed flag does not prove a person accepted a real scenario.
Same-evidence merging can confirm a note; wrapper environment redirection has uncovered paths
to real HOME or external service state if those tests were executed without further isolation.
Lowercase skip messages are not the runner's SKIP-AXIS receipt. Statement deletion comparison
does not establish full semantic ratcheting, and one-statement fixtures do not establish
independent acceptance of multiple statements. Existing pin protection, valid SKIP handling,
zero-discovery guards and current Zeus deferrals are retained rather than reported as absent.
No integration002 source script, import, probe, model, service call or installation was run.

## Verification scope and remaining work

`verify-breaker-learning-checkpoint.py` validates exact partition membership, source raw Git
blobs/bytes/SHA-256, declared ranges, complete primary body ranges, prior-ledger/review references,
current artifact hashes and five captured process receipts. It does not establish semantic
correctness, transitive closure, license approval or actual product/model/human acceptance.
The first verifier run failed on a prior Zeus support row using `sha256` instead of
`pinned_sha256` (KeyError). The verifier now accepts either recorded schema and still requires
equality with the actual bytes; no evidence record or failure output was rewritten to pass it.
Terminal tool result `2960d7` records that initial metadata failure; `a06715` records the first
successful identity check. Later checks add partition and checkpoint-artifact verification.

Original breaker executions are two unit wrappers (34 tests) plus real isolated file/permission
observations. Clock/config/emitter fixtures and sequential seeded-state limitations remain
explicit. No actual model invocation, OS process race, device test or human acceptance occurred.
FA-020 carries the breaker requirements; learning/canary/convergence findings also remain in
their per-file review/remaining records for full-area closure and later issue decomposition.
This checkpoint changes review evidence and tooling; it does not deploy or activate Zeus.
