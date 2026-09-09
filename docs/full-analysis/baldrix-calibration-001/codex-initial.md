# Codex independent calibration review

Before reading Claude's response, root read all six primary bodies (43,851 bytes) in
`baldrix:scripts/lib/calibration:001` at `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`.
Scope SHA-256 `6e068fc63c99a989ac5c2f321cc0f61777e09a62ae16eb994a7d04aa6d37309c`.
Fresh supporting full bodies: no_degradation_gate.py, threshold_policy.py and
tests/test_threshold_tuning.py. Other callers/tests were only searched and remain unread
in this checkpoint. Prior breaker review informs hypotheses but is not new support coverage.
No source execution has occurred at this checkpoint; observations below are static.

## Statistical evidence and critic proposals

The package's explicit proposal-only policy is useful; it does not automatically edit critic
or breaker policy. Its package docstring still excludes breaker calibration despite importing
that implementation. Numeric-threshold proposals do have a state-writing ready-flag side effect.

proposer.analyze_ledger counts every record in sample_size, but success=False with no failure
modes is counted neither success nor failure. success_rate returns 1-failure_rate rather than
success_count/sample_size. Unknown or unclassified outcomes therefore improve the apparent
success rate. Invalid failure_modes shapes are treated as empty; duplicate records inflate
sample size, and repeated mode strings can push a mode count above the number of failures.
No exact attempt/revision/model identity, deduplication, age window, adjudicated ground truth
or confidence interval is bound to a proposal. Rationale says recent dispatches although the
code uses cumulative readable records. The local JSONL reader accepts non-dict JSON values
and the consumer calls .get; malformed JSON is skipped, but UnicodeDecodeError is outside
the OSError catch. A missing/invalid record and genuinely no observation need separate receipts.

The DEFAULT_INVOKE exclusion protects judgment classes from automatic skip proposals, and the
minimum sample guard exists. R2's early continue can nonetheless suppress the later fabrication
warning for a non-protected invoke agent with low overall failure rate but fabrication-heavy
failures. Explicit agent_types order/duplicates are not normalized, despite the stated sorted
determinism. Resolve policy, default sets and producer truthfulness still need direct closure.

## Breaker calibration

breaker_proposer uses imported default constants, not effective per-key configured thresholds.
BR2's documented near-30% false-positive suspicion is implemented as failures >=3; even a
100% failing window can produce a recommendation to raise the threshold. No false-positive
labels or operational outcome are supplied to distinguish oversensitivity from genuine outage.
BR2 also continues before BR4, suppressing a concurrent backoff proposal. BR4 uses configured
cooldown duration rather than observed probe latency/survival. Its statistics omit project
identity and exact evidence path; all-project scans can emit indistinguishable agent/mode rows.
Filename parsing cannot invert the lossy original key mapping.

Malformed JSON defaults to an empty dict and yields zero statistics rather than None, contrary
to its docstring. History denominator includes arbitrary list entries; False/zero are failures
and every other value remains in the denominator. int(trip_count) can raise on bad/Infinite
input, and string/nonfinite timestamps are not validated before subtraction. BR3 requires twice
the default retained window; reachability under ordinary producer retention needs closure.
No actual false-positive rate, latency frequency or incident reduction is established.

## Numeric threshold measurement, staging and application

full_body_admit_precision measures score strictly above the candidate threshold among scores
at least that threshold. It measures neither relevance nor user success and returns 1 for no
eligible matches. Raising above every score can therefore look perfect while admitting nothing.
The guard re-simulates body-character pressure and rejects a wholly unsized corpus through NaN;
this is a useful defense. It silently excludes unsized entries/events from a partially sized
corpus, accepts bool body_chars as int and does not validate finite scores. It ignores header,
summary and actual injection overhead; equivalence to the live skill_match consumer is unproven.

Timestamp splitting is lexicographic string comparison, not validated normalized time; missing
timestamps join trailing. Duplicate events and timestamp ties affect the denominator and split.
The gate checks both split sizes, handles replay exceptions and rejects nonfinite metric results.
The proposer screens candidates on trailing data but chooses the best accepted candidate using
holdout improvement, so that holdout participates in selection. It is not an untouched final
evaluation set or proof that an accepted metric improvement generalizes to user outcomes.

The proposer always starts at entry.default, not the effective override. Direction checks are
also relative to default, and there are no validated value domains, finite/positive step bounds
or cross-field relationships. telemetry_root is accepted but unused in the actual read path.
Current-metric exceptions are outside its candidate catch. A dataclass and Literal annotation
do not runtime-validate the mutable registry. Runtime locked-disjoint checking raises ValueError
and survives Python -O; membership and locked apply checks are real guards worth retaining.
Four registry entries deliberately lack metric/guard wiring; this is documented inert scope.

The ready flag records name/current/suggested/delta and wall-clock text, but no corpus hash,
policy revision, attempt, holdout digest, expiry, authenticated reviewer or one-use transaction.
Writing errors are swallowed and rejection does not remove a previously written flag.
threshold_policy checks only flag existence, not its contents or binding to the requested value.
Any value can therefore pass that part of the gate with a same-name existing flag. The literal
token is a direction label, not a human identity/approval receipt. Applying plain YAML precedes
flag deletion/history; deletion and history failures are swallowed, allowing reported success
without proved anti-replay or forensics. Config reads/writes lack finite/type/version validation
and read/modify/write fencing. A no-op before token checking does not change policy and is not
by itself an authorization bypass. Source APIs do not establish that current live config changed.

## Tests and Zeus decision

test_threshold_tuning calls actual library functions and real temporary paths but patches
registry/path objects, reloads modules and uses synthetic telemetry. Its positive token test
applies exactly the suggested value; it does not test changed value, corrupt/expired/stale flag,
parallel consumers or effective-current proposal drift. It verifies an unsized corpus failure,
not partial missing-size fidelity. Historical design debate is not current execution evidence.
Original source tests have not been executed in this initial review.

Keep proposal/approval separation, explicit typed findings, min samples, held-out replay guards
and locked registry checks. Zeus needs attempt-bound deduplicated events, unknown-state coverage,
human-relevant labeled metrics, actual consumer equivalence, separate final evaluation, effective
Git policy identity and PG-fenced approval/apply/rollback receipts. Model cost optimization must
not graduate Astra to Sol or Terra from a fabricated denominator or self-fulfilling metric.
Full callers/config/tests, license, real OS/model/human acceptance and independent discussion
remain open; no adoption or pilot readiness is claimed.
