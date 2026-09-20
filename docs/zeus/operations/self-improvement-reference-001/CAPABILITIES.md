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

## Recorded capability decisions

These decisions are bounded to the named behavior; parent families remain open. They are analysis
dispositions, not implementation or runtime acceptance. Keep this section when updating inventory.

| Behavior | Decision | Evidence | Remaining boundary |
|---|---|---|---|
| Skill source discovery | Reuse Zeus Git-revision/content-reference selection; do not port ancestor discovery into execution | SKILL-PACKAGING.md | Full installer/router/package lifecycle |
| Child environment construction | Reuse Zeus allow-list; do not replace it with inherited environment plus key stripping | Runtime comparison below | All provider launch/credential boundaries |
| Session watchdog | Retain Zeus durable deadline/clock-domain owner; do not add another timer authority | Runtime comparison below | Provider process-tree termination and cross-platform execution |

### Runtime comparison and substep review, 2026-09-20

Inspected all four `src/ouroboros/runtime` files: `__init__.py` (38 lines), `child_env.py`
(92), `controls.py` (142), `watchdog.py` (283), at the fixed SOURCES.json commit. This is complete
reading of that directory's implementation, not completed semantic review of every caller/test.

Facts:

- Child environment starts as a copy of the parent, strips configured keys and increments a depth
  field. Malformed depth falls back to 1. This is a cooperative recursion marker, not a sandbox,
  global spawn quota, or evidence that no child can recursively invoke another tool.
- Claude adapter `527–570,727–775` connects the helper to `create_subprocess_exec` and calls a
  separate termination helper after communication timeout/exception. The termination helper and
  descendants were not qualified in this slice; wrapper invocation alone does not prove cleanup.
- Runtime control loader owns a session wall-clock setting and accepts legacy knobs without
  consuming them here. Its default and disable switch are upstream policy, not Zeus requirements.
- Watchdog reads persisted cancellation before current budget settings, appends a cancel event
  before adding its in-memory fired flag, and returns a decision. Replay query followed by append
  is not itself proof of atomic concurrent deduplication. No concurrent defect is asserted without
  a reachable owning caller and reproducer.
- Auto pipeline `1490–1538` converts the decision to blocked and saves state. That is not a process
  kill acknowledgement. Invalid `created_at` returns no watchdog decision in this helper; prior
  state validation would need tracing before declaring an exploitable execution defect.
- Upstream test source `tests/unit/runtime/test_watchdog.py:144–209` uses a capturing appender and
  frozen time to check instance replay and changed budget. It was read, not executed; no actual
  database or host restart was tested by this analysis.

Zeus comparison: `application/execution_time.py:1–100` validates durable deadlines, lease state,
clock samples and process domains; renewal cannot increase same-domain deadline remaining.
`adapters/isolated_worker.py:79–110` gives Docker a configured environment allow-list and adds the
worker token only on the named token-bearing operation. No actual secret value was read.

Matrix: normal/replay and invalid clocks are covered by the existing local contract suite below;
unknown/malformed upstream state remains a source-level question; concurrent event admission,
real restart, WSL and process-tree cleanup remain unexecuted. No acceptance criterion depends on
porting those unqualified behaviors, so they do not block the bounded reuse/non-port decisions.
No new runtime limits, permissions or cancellation policies were applied.

Executed: `pytest tests/test_execution_time.py -q -p no:cacheprovider` via trusted local Python,
with ZEUS_/HARNESS_ environment removed. **21 passed, 14 skipped**, exit 0; pytest 0.43 seconds.
These are local contract checks, not a live worker or upstream runtime test.
Receipt/log/JUnit: `D:/workspaces/zeus/artifacts/self-improvement-reference-001/runtime-001.{json,log,xml}`.
Log SHA-256: `2e14cfabc299d680c329514091d1b671bb4234a95fcaf82a3095db90835c6d72`.
Substep review: source -> direct caller -> Zeus owner -> test scope -> claim check. Codex
self-crosscheck, not an additional independent reviewer. No production state changed.

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
