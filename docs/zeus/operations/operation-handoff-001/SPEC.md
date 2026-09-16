# Cycle handoff for the next operating session

2026-09-16. User asked to continue operation. Codex analyzes/designs/accepts; Claude implements through Zeus. One Claude call (USD3 option, 900s) and one Codex review (300s), then stop. Preserve 17 existing machine slots; cumulative cap 19. LocalCycle limit 2. No retries, deployment or unattended budget extension. Provider USD option is not a billing guarantee.

## Source and decision

Codex read local baldrix skills/_common/handoff-clear-trigger.md in full and reused docs/full-analysis/baldrix-common/additional-notes.json. Exact source is pinned in source.json. Adapt task/revision/evidence identity and bounded continuation; reject mandatory /clear, arbitrary iteration quality thresholds, mutable HANDOFF as authority, zero recovery cost claims, hardcoded host paths and self-authorizing fallback tasks. Upstream incidents are not newly executed evidence.

Current path: CLI parser/cycle_command to LocalCycle to PG local_cycles/tasks/decisions_pending. Redis/executor/observer are only needed by step. Existing status shows the cycle but operators must manually locate its result evidence. Add a read-only projection, no new store/prompt/daemon. It works without executor, bus, or provider configuration.

## Implementation

Allowed files ONLY: src/codex_harness/application/local_cycle.py; src/codex_harness/cli.py; tests/test_cycle_handoff.py; docs/contracts.md (add INV-CYCLE-HANDOFF-001); docs/zeus/operations/operation-handoff-001/OPERATIONS.md.

Add LocalCycle.handoff(cycle_id) and `zeus cycle handoff <cycle_id>`. CLI explicitly handles handoff before step without building executor/observer/Redis. Unknown cycle uses existing ContractError. Store errors propagate, never return an empty success.

Read cycle and optionally last_execution target in one store transaction. Never put/update/delete rows, publish/ack, open artifacts, probe providers, reset budget or execute work. Return JSON-ready fields:
- schema: urn:zeus:cycle-handoff:1
- authority: observation_only
- automatic_resume: false
- cycle: whitelist id, correlation_id, status, max_executions, executions, in_flight, stopped_reason, last_execution, created_at, updated_at. Do not mutate stored data.
- remaining_executions: max(0, max_executions - executions); informational headroom only.
- target_record: observation of the CURRENT row addressed by last_execution, NOT proof of historical execution. Include availability: none when no last execution; unsupported_kind for kind other than task/decision; missing when row absent; correlation_mismatch when target message correlation differs; found only when it matches. Non-found outputs have only availability/kind/id (null when absent), no target data.
- Found target_record includes kind/id/status, attempt/generation/phase when present, and selected result metadata ONLY: candidate base/revision/tree/diff_hash (string fields only), execution_ref (string or null), evidence_inspection verdict (string or null), accepted (boolean for decision result, else null). Missing optional metadata stays null/empty. Do not include task input, prompt, summary, stdout, raw error, messages, settings, absolute candidate path. References are recorded data, not integrity-checked artifacts or deployment approval.

Handle absent/non-dict result/candidate/last_execution defensively, not with catch-all. Valid stored policy determines counts. No recovery heuristics or generated next-step commands. OPERATIONS.md explains stdout usage, current record versus historical execution, unknown/mismatch, and explicit operator action before continuing. Portable Windows/Linux behavior, no upstream module execution or code copying.

## Fixed acceptance matrix

1. Initial active cycle: no target, full remaining count, automatic_resume=false.
2. Completed worker/accepted review: same-correlation metadata only, exact revision/ref, boolean acceptance, remaining=0. Arbitrary secret canary/input/summary fields never emitted.
3. stopped/budget-exhausted/in-flight: states/counts retained, no execution/repair. Overrun display clamps to zero.
4. Missing/foreign/unsupported target, empty/malformed optional result: explicit unknown; no foreign data or invented success.
5. Unknown cycle/store failure: fail explicitly. Reads leave tables unchanged. Fresh object yields same view when rows unchanged. Changed target is its current row, not historical truth.
6. CLI test makes executor/Redis/observer builders fail if touched; handoff still works. Existing start/status/step outputs unchanged.

Meaningful MemoryStore/CLI tests cover these boundaries; fixtures are not actual provider evidence. Claude runs focused commands only (full suite explicitly owned by Codex):
- python -m pytest tests/test_cycle_handoff.py tests/test_local_cycle.py tests/test_cycle_remaining.py -q
- python -m ruff check .

Codex owns independent full PG/Redis suite, final CI and a read-only handoff measurement on actual completed operation PG rows, with no extra model call. Final tests array has exact commands only, results in summary. Actual Codex reviewer evaluates the fixed matrix. Real cycle must reach 2/2 awaiting_operator without input supplementation, then stop. A failed single call/review remains recorded and ends the batch without retry.

## Review finding and consolidated correction specification (not implemented)

Candidate bdd0d1b was rejected by the actual reviewer. Root independently reproduced this synthetic error through the ordinary application path: a failed task's error becomes `failed:<raw error>` in LocalCycle._candidate/_stop, and handoff copies it in cycle.stopped_reason. The original frame contradicted itself by requiring stored reason preservation and no raw errors. The raw stored record and existing status command remain unchanged; the new projection needs its own safe representation.

For the next authorized implementation batch only: project stopped_reason as a recognized reason code, never its arbitrary detail suffix; include a SHA-256 digest of the complete stored reason separately when present so the operator can correlate it without printing it. Unknown/non-string reasons must be explicitly unknown, not rendered. Whitelist fields inside last_execution/in_flight as well, excluding error or arbitrary nested data. Keep ids/agent/kind/status/timestamps/claimed/result_id as applicable. Preserve raw PG records and all existing status/step behavior. Add a regression that creates a failed task with a synthetic marker, calls ordinary step then handoff, and checks marker absence plus safe code/digest and unchanged stored reason. Include a control where a normal reason remains meaningful. This is one output-projection boundary, not a redesign of execution recovery.

The reviewer also noted synthetic list-valued kind raises TypeError, but no normal writer producing that shape was established. It is a nonblocking defensive hardening note; handle it in the same local helper if that helper is edited, without expanding scope or creating another blocker.

Current batch made exactly two provider calls, reached 19/19, retained accepted=false, and used the existing cycle gate to stop at budget_exhausted without invoking a provider. No repair/review retry is authorized within this completed batch. The corrected specification is reviewable here; it is not a claim that the defect is fixed.
