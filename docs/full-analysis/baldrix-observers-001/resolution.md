# Evidence observer joint resolution

Root and actual Claude independently reviewed the two observer bodies at Baldrix
`cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`: 7,819 bytes, partition scope
`3febc60e9994a8aef5daa7e32cf300bcc257c9379549268479d2fd254794ccd1`.
The initial reviews remain unchanged. Claude session
`d2317a1c-e9ab-4ba1-a0b9-ed7f0b6883c9` returned successfully for independent review
and resumed discussion. Root read both responses in full. Claude additionally read
the component program and isolation runner before its discussion response. Raw provider
JSON, stderr, extracted text and process receipts are retained; their byte integrity is
checked separately from whether the reasoning is correct.

## Agreed findings and actual observations

The original unit wrapper passed 11 tests using actual original functions, temporary
files and controlled Python children with synthetic claims. The component program used
original methods without method, clock, subprocess or provider patches. Both ran in the
recorded immutable isolated Linux Docker image, with no network or host credentials,
read-only source/root, nonroot uid 65534 and bounded resources. All 1,648 source files
remained byte-identical. These are controlled component observations, not historical
user evidence or native Windows/WSL acceptance.

- A directory, empty evidence, passed-without-replay, permission-denied stat and an outer
  empty evidence array masking nested missing evidence returned CLEAN. CLEAN cannot
  establish what was checked, nor authenticate the claimed outcome.
- An existing file under entry.cwd was classified FABRICATION_CONFIRMED because stat
  resolved its relative path against the detector cwd. A missing executable received the
  same classification. Neither observation proves intentional or historical fabrication.
- The envelope-selected replay command created a scratch file and returned CLEAN.
  shell=False separates arguments but does not impose filesystem/network capabilities.
  This observation proves that scratch write only; host writes, credential access and
  network effects were not tested.
- Invalid UTF-8 child output raised UnicodeDecodeError; a NUL path raised ValueError.
  Preserve raw bytes and explicit error/unknown states instead of replacing bytes or
  catching every error as CLEAN. Replay failure must retain cause, attempts and identity.
- The detector's imported backoff remained 5.0 seconds. The unit test's later mutation
  of the constants module did not change that binding. Rebinding before first import
  could differ; no upstream change was made merely to speed up the tests.

Typed deterministic checks, explicit internal enum ordering, early success, shell=False,
default timeouts and OSError handling are useful guards. They do not provide historical
truth, a statistical flake rate, complete output/time budgets or process-tree isolation.

## Discussion corrections and bounded disagreements

Claude explicitly withdrew production-unreachability, zero incremental detection,
100-percent adversarial miss rates, universal hook termination, globally unread/forever
OPEN breakers and global absence of FLAKE consumers. Literal searches do not establish
those propositions. Runtime dictionaries can contain replay_cmd. D2 structural source
and all producers/consumers were not jointly closed by this review.

Root subsequently read agent_outcome_audit.py 329–471 and settings.json 250–279 in
addition to the earlier recorded caller ranges. The hook configuration assigns 10 seconds
to agent_outcome_audit; replay defaults allow 30 + 5 + 30 seconds per retried entry, with
no total entry budget here. Fast failure/retry can finish within 10 seconds. Actual host
kill timing, descendant cleanup and native-platform behavior remain unmeasured.

_safe_call attempts failure telemetry and then returns None. Telemetry delivery may itself
fail, and not all of main is wrapped. The sampled _resolve_failure_mode checks D2
TOOL_MISUSE before D1 FABRICATION despite the stated reverse priority. Its internal
precedence differs from the observer enum's consistent ordering. FLAKE is not failure in
this sampled resolver; other consumers remain open.

Claude's discussion says a D1 exception produces success=true. Root narrows this: it can
do so **when D2 also produces no failure and the subsequent ledger append succeeds**.
The source at 406 and 451–466 binds success to failure_mode is None, not to complete
successful inspection. A D2 failure still yields failure; the ledger may fail to persist.
No actual hook/ledger execution was performed in this checkpoint. Breaker snapshots and
before/after ledger fields exist; absence of admission blocking is not automatically a
violation of an advisory breaker contract.

For outer-empty masking, both reviewers agree on the measured result and need for one
unambiguous envelope/context contract. Claude labels it a stronger bypass surface. Root
retains that as a candidate risk, not a measured production exploitation rate or severity
without producer trust and consumer closure. The 10-second configuration mismatch and
cwd inconsistency are accepted concrete concerns, rather than unresolved disagreements
about the observed code.

## Zeus adaptation requirements

Keep missing, unknown, replay failure, flake pattern and verified mismatch separate from
semantic fabrication and human acceptance. Each finding records its checked denominator,
raw output, error cause, original/replay argv, cwd, source/environment/policy revision and
runner-owned attempt identity. Bind file checks and command replay to one explicit context.
An agent-selected command or reference path cannot issue its own execution authority.

Only an explicitly authorized, bounded, isolated runner may replay commands. Validate
finite positive deadlines, entry/output limits and the aggregate caller budget. Preserve
receipts for failed cleanup, unavailable dependencies, decoding failures and stale authority.
PG runtime transitions and notifications must distinguish missing checks from successful
execution; Git definitions retain versioned validation and approval policy. Actual human
SDD acceptance and model qualification require their own evidence and approvals.

These are requirements for root's later implementation after full analysis, not evidence
that Zeus already implements them. Remaining work includes transitive caller/config/test
closure, license/redistribution, actual hook/ledger and process-tree behavior, Windows/Linux/
WSL qualification, independent adoption review and actual product/human/model acceptance.
Samsung device work remains deferred. No harness deployment or source modification occurred.
