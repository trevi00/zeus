# Root checkpoint: calibration, workflow evidence and integration tests

Base Zeus revision: `aedc8a8bbedde73ffdc10e8f28b2097d2843b228`. Four bounded folders
contain 57 primary records: calibration001 6, lib005 13, lib006 24, integration003 14.
The earlier pipeline_stage_picker primary overlaps once, leaving 56 new tracked paths.
Supporting rows total 83 (6+14+21+42); eleven integration support rows reuse exact earlier
ranges. They do not add primary coverage. The global ledger now contains review records for
972 of 2,736 tracked paths, with 1,764 still unreviewed. Body-read records with incomplete
call/test traces remain explicitly incomplete; this is not a semantic-completion percentage.

Root independently read calibration's six bodies and exact support, authored its initial
judgment before reading actual Claude, then compared the initial/discussion responses and
recorded corrections in calibration001/resolution.md. Root also read lib005 review/notes/
supporting-notes, lib006 review and integration003 review, checking their scope and limits.
The latter three folders retain pending actual Claude whole-area review. A Claude session
for calibration is not independent review coverage for those other areas.

## Findings carried into Zeus requirements

Calibration connects policy authority with meaningful outcomes. Actual original-method file
observations show a suggested-4 flag permitting 999, a new proposal ignoring effective 999,
corrupt/empty flags permitting changes, NaN policy, zero-admission metric acceptance and unknown
outcomes inflating apparent success. Source receipt limits, direct generic gate versus proposer,
synthetic data and original-unit mocking are explicit. Current skill budget code already fits
the top body; the historical bypass comment is not a current defect. Root and Claude preserved
the correction and the remaining base-score/telemetry mismatch separately.

Lib005 broadens the evidence problem to milestone completion, review materials and mutation
testing. Content-insensitive IDs can carry old pass judgments onto changed requirements;
empty or incomplete closure data can look closed. A diff header is not proof the entire diff
body was reviewed. Narration checks reference membership rather than the truth of its sentence.
Mutation tests require exact mutation sites and restoration evidence; treating every nonzero
exit or timeout as a killed mutant does not measure assertion strength. These are bounded static
findings, not executions of the mutation tools or proof of live data loss.

Lib006 connects these findings to runtime effects: quota read/increment/replace is not atomic
reservation, and a discarded write-failure result can diverge from the returned count. Stage
selection/status use artifact existence rather than the declared gate contract. Repro probes
classify failure text and return passed=True without executing a reproduction. Their gotcha
gate consumes that value, so classification must not become a reproduction receipt in Zeus.
Paths, reflection injection and pane input results also require explicit authority and effects.
Existing path guards, typed event vocabulary and proposal/activation separation remain useful.

Integration003's default canary contract is particularly relevant to promotion: pr4 consumes
golden.gate as bool although it returns a tuple, making a returned failure tuple truthy. Its
bool-lambda fixture does not test that default contract. This is static evidence; no golden
case or promotion was executed. The same review records HUD writes after fixture env removal,
approval inferred from hook pairing, log expiry racing append, sequential idempotency versus
external action completion and partial skip reporting. It preserves current silent_fail checks,
proper SKIP-AXIS paths, service-identity checks and current role arming that old comments omit.

## Verification and remaining work

The verifier checks exact partitions, raw source Git blobs/bytes/SHA-256, declared/full-body
ranges, prior-ledger/review bindings, checkpoint artifact hashes and captured stream receipts.
It is an identity and scope check, not semantic correctness or adoption certification.
The calibration wrapper passed 16 original unit tests; the separate original-method program
used real isolated files and synthetic events. Neither is real model relevance, human approval,
native Windows/WSL acceptance, concurrent-process testing or deployed service verification.
Source execution in lib005/lib006/integration003 remains zero. The historically rejected
gatewriter probe was not retried or routed around.

FA-021 carries calibration evaluation and approval/application binding requirements. Other
new findings remain in their per-file records for full-area closure and later ticket refinement.
The terminal local regression result is recorded in calibration-workflow-local-validation.json.
No runtime implementation, workflow definition, deployment or live source harness changed in
this checkpoint. Full source analysis, independent closure, licensing, real OS/model/canary
qualification and user acceptance remain required before pilot readiness.
