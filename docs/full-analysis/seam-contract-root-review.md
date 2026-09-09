# Seam and contract test checkpoint — root review

This batch records 45 primary paths: seven seam bodies, four mirror extractor bodies, four worker bodies, eleven contract001 paths and nineteen contract002 paths. Supporting records total 78 (10 + 2 + 4 + 29 + 33); eleven contract002 supports explicitly reuse same-byte earlier ranges. All primary paths are newly recorded in this batch, subject to the global coverage reconciliation. Recorded bodies still have incomplete transitive trace, execution or acceptance work.

Root read both actual Claude seam responses and reconciled them with the primary/supporting source and isolated original runs. Root also read both mirror/worker review.md and file-reviews.md, and both contract review.md documents in full. Their underlying source reads belong to the delegated reviewers; root does not claim a second full original-source review of those four partitions. Actual Claude discussion and original26-unit execution apply to seams only. Other primary upstream executions in this batch are zero.

## Implications for Zeus

- Seam comparison must preserve input identity and completeness before comparing values. Transform collapse, parsed HIGH with omissions and malformed-tail disappearance were observed. Preserve explicit LOW/missing/transform-error guards while preventing advisory findings from certifying product compatibility or human acceptance. Root resolved overclaims about determinism, output confinement, current fleet facts and external CI authority.
- Mirror hashes normalize meaningful text and may lose raw bytes, paths and read failures. Worker handles omit attempt/generation and result/process-tree identity. These static findings strengthen existing source identity and runner topics; separate tests of another psmux module or sleep process are not actual model execution evidence.
- Contract001 distinguishes acceptance attachment from content/approval, stage state from completion fold, bus enqueue from delivery, and assertion counts from real scenarios. Preserve existing skip and no-data distinctions, while tracking malformed skip output, held delivery results, candidate consumption and missing evidence as explicit states. HMAC over a synthetic event is not a person approving a revision.
- Contract002 distinguishes projection heartbeat from verified projected state, source AST/Compose declarations from runtime effects, context cards from agent receipt, and fixture reenactment from actual sandbox execution. The projection zero-stage case is conditional on a return shape whose producer closure is still open. Existing environment sealing and reconfirmation defenses are present; their historical absence must not be restated as a current defect. A test's partial environment restoration is a separate issue.

The user requires eight iterative SDD stages and strict real user scenarios. Five-stage upstream self-improvement, generated docs, JSONL→PG projection, default exit0, CI green, or static approval words cannot satisfy those requirements. Definitions remain Git authoritative; runtime and issue records remain PG authoritative. FA-024 isolates extraction/transform fidelity and comparison authority; related existing runner, schema and approval topics remain open.

## Verification and boundaries

Five process receipts cover two actual Claude calls and three original-code runs: missing dependency failure, YAML-enabled26-unit pass, and a separate component observation program. Source identities, byte spans, exact captured outputs and same-byte prior references are mechanically checked. This verifies evidence integrity, not reasoning or whole-system adoption.

Exact Zeus commit `810cc3c5c3ac188b29ca884fb00b05121784df48` passed all five GitHub jobs; the raw receipt is archived under docs/zeus/ci. The user explicitly requested repository public visibility and GitHub confirmed PUBLIC; this is separate from service deployment or adoption readiness.

Full tracked/local-extra analysis, transitive closure, license and independent adoption review, agreed implementation, actual Astra/Sol/Terra qualification, Windows/Linux/WSL pilot execution and human acceptance remain unfinished. Samsung real-device work stays deferred. Original harnesses and existing operating containers were not changed.
