# Calibration joint review resolution

Source: Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, six primary bodies,
43,851 bytes, scope `6e068fc63c99a989ac5c2f321cc0f61777e09a62ae16eb994a7d04aa6d37309c`.
Root stored its independent initial review before reading Claude's response. Actual Claude
session `7c17de7b-6b89-40a7-8b0c-9fcb0f11dacd` completed independent review and discussion.
Raw initial/discussion responses, prompts and process receipts remain unchanged.

## Agreed findings

The effective-policy boundary is broken in the reviewed source. Numeric proposals start at
the registry default rather than the effective override. The original-method observation
generated suggested 4 from current 3, applied 999 with that same-name ready flag, then generated
another current-3/suggested-4 proposal. A malformed flag permitted 1000; an empty flag permitted
NaN, which the effective policy reader returned as NaN. Flag existence does not bind the value,
corpus, reviewer, revision or freshness. Plain YAML write, subsequent best-effort flag removal
and swallowed history errors are not one transaction. A literal token is a direction label,
not human authentication. No live unauthorized policy change is established by these tests.

Metric success is also separate from user success. The precision function returns 1 when no
match is eligible, and the generic gate accepted 3→999 on a synthetic corpus with no matches
at 999. The single-step proposer did not propose 999 in that observation. The metric uses
score distribution rather than actual relevance or human acceptance. A partly unsized event
returned guard 1; unknown body size and actual production overflow were not measured. Current
skill_match selects on base scores while telemetry records boosted scores and only top five
matches. Replay therefore lacks the same selection inputs and full candidate denominator.

The proposer uses holdout delta to choose among accepted candidates. That holdout participates
in selection; a positive sampled delta does not prove stationarity, generalization or usefulness.
Both split-size checks, replay-exception rejection and nonfinite metric rejection are real
guards worth preserving. The registry's runtime ValueError check survives Python -O, and
membership plus apply-time locked-name checks are useful. Four unwired registry entries are
explicitly inert; do not characterize their mere existence as active tuning.

Outcome denominators need separate unknown states. Ten synthetic success-false/empty-mode
records produced sample 10, success 0, failure 0 and success_rate 1. Repeating a failure mode
three times counted three for one failed record. A non-object JSON array raised AttributeError;
the historical output key says scalar_record_exception, corrected in observations.md. The
success_rate property is a misleading public value; no use in R1–R4 was observed. Failure-rate
dilution does affect proposal rules. R2's early continue can suppress R4's fabrication note.
One sampled hook or audit producer does not establish complete event provenance or frequency.

Breaker calibration reports imported defaults and classifies frequent failures without actual
false-positive labels. A seeded 100%-failing window suggested raising 3→4. Corrupt breaker JSON
became zero-history CLOSED statistics rather than None. The default retained window of ten
cannot satisfy BR3's default required twenty; caller overrides or arbitrary input change that
reachability. Normal close resets trip count; zero does not prove current state or no history.

## Corrections and precise limits

Claude withdrew an old top-body budget-bypass claim after reading the actual implementation.
Root freshly read all skill_token_budget.py: apply_token_budget calls fit_top_skill. Old comments
in that module and skill_match still describe previous behavior. The usual current budget path
must not be reported as the historical bypass. Selection inputs, per-body cap, partial telemetry
and truncation-model differences remain separate fidelity concerns, not measured incident rates.

Claude corrected its primary line counts, unused module/constant claim (qualified() consumes
both), BR4 arithmetic (with cap 3600 a decrease requires base>1800, not >900), unconditional
dead-branch language, stationarity claim and global label/caller assertions. Extra Claude-only
caller observations, including CLI dry-run wording and telemetry rotation, retain that reader's
scope; they are not fresh root full-body coverage. Root support is exactly six records: four
full bodies and two partial files with declared ranges.

Two discussion recommendations require further qualification. The docstring's never-sees-heldout
claim is not restored by calling gate results indirect: selection consumes holdout statistics.
Also, consuming a flag before a file write plus rollback does not by itself prove exactly-once
external effects. Zeus requires fenced transactional state and recoverable application receipts,
with external effect identity where applicable. Failed/unknown application must remain explicit.

Claude read the captured streams/receipts and root observations, but explicitly did not read
the component/runner program bodies. Root reviewed and authored those programs and verifies
their hashes. This evidence is not an independently certified execution backend or adoption gate.

## Execution and adaptation boundary

The original test_threshold_tuning wrapper passed 16 tests. It invokes real library methods
and temporary files, with mocked registry/path objects and synthetic telemetry. A separate
original-method program used real isolated files and synthetic events without method/clock/
provider patches. Both receipts show return code zero, immutable Docker image, network none,
read-only source/root, uid 65534 and resource limits. All 1,648 source files stayed byte-identical.
There was no original provider/model call, actual human approval, real incident distribution,
native Windows/WSL acceptance or concurrent-process experiment.

FA-021 records the adaptation topic: effective Git policy identity; PG-bound event denominators;
actual consumer-equivalent replay; human-relevant outcomes; separate final evaluation; exact
value/corpus/reviewer/revision approvals; atomic consumption and application recovery. Link it
with FA-020 breaker ownership, FA-019 actual invocation and FA-018 completion authority.
Preserve proposal/approval separation and existing guards while replacing misleading receipt
and metric contracts. Full caller/config/test closure, licensing, OS/process/model qualification,
human acceptance and pilot readiness remain incomplete. No source or live harness was modified.
