# Capability completion board

This is the continuation board for SPEC.md, not a new task frame. All 1,817 paths have
one primary analysis family. Cross-family callers must also be traced. Assignment by path
is navigation only; no family is closed merely because its files were listed or read.

| Family | Paths | Zeus comparison owner | Existing partial evidence | Decision status |
|---|---:|---|---|---|
| Requirements and product specification | 64 | ticket/plan/SDD | CONTRACT-PATH.md | open |
| Execution and coordination | 423 | workflow/Fleet/isolated worker | RECOVERY-PATH.md; LEARNING-RESUME.md | open |
| Evaluation and verification | 44 | evidence inspection/independent review | FINDINGS.md; CONTRACT-PATH.md | open |
| Evolution and recovery | 51 | portfolio/research program/Council/recovery | FINDINGS.md; STORAGE-RECOVERY.md | open |
| Persistence and event ownership | 53 | PG/outbox/Redis Streams | RECOVERY-PATH.md | open |
| Providers and process lifetime | 95 | provider adapters/isolated worker | RECOVERY-PATH.md | open |
| Skills and integration packages | 141 | project skills/worker profile/import/history | LEARNING-RESUME.md; STORAGE-RECOVERY.md | open |
| Logs, status and interfaces | 74 | observe/monitor/portfolio | FINDINGS.md | open |
| CLI, configuration and MCP | 363 | CLI/six-W/policy | open | open |
| Shared contracts and domain model | 73 | domain/versioned contracts | CONTRACT-PATH.md | open |
| Build, packaging and automation | 68 | packaging/CI/hooks | open | open |
| Documentation and examples | 168 | reference material; corroborate against code | open | open |
| Cross-cutting tests and fixtures | 158 | test evidence; fixtures are not live runs | open | open |
| Root metadata and uncategorized shared files | 42 | license/entry points/configuration | open | open |

## Closure contract

For each capability: identify contracts/configuration, implementation and actual callers;
trace input, state, ownership, outputs and failures; inspect relevant tests and label unrun
checks; map existing Zeus owner; decide reuse/enhance/new/non-adoption with evidence and
rationale. Record per-path disposition, including support docs, fixtures, license and build
assets. Important unknowns stay open. A non-adoption decision is not an implementation.

## Delivery order

1. Close shared contracts, requirements, execution, evaluation and recovery mappings as one core path.
2. Close provider/process, persistence and skill/package integration boundaries.
3. Close CLI/UI/observability plus build/docs/test assets; reconcile every inventory path.
4. Consolidate adaptation decisions into one versioned Claude handoff and acceptance matrix.

Existing source findings are preserved. No new runtime team or model dispatch is implied.
A future board revision must preserve decisions, not regenerate closed entries as open.

Raw worklist: `D:/workspaces/zeus/artifacts/self-improvement-reference-001/ouroboros-capability-worklist.json`
SHA-256: `5faa7017ecd3770313716150155eb9aeb17b8e1d1cff0b96834e5cf0f419f9ea`
Verification: 1,817 unique assigned paths, zero unassigned paths, zero semantic closures inferred.
