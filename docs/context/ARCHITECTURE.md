# Architecture — feature and ownership map (rebuild)

**Purpose.** One navigation map from each capability to its code, ports, contracts and tests, for the
whole-architecture rebuild (`REBUILD-DESIGN-v2`, SOURCE = M7 `e38aa722`). **Owner:** the rebuild
implementation owner, through ordinary slice review. **When to read:** before moving or adding code
in the target tree `target/`, or when tracing where a capability lives today.

**Reference-only.** Per [DELIVERY.md](DELIVERY.md) this document is never delivered to a provider,
starts no loader and grants no authority. `docs/contracts.md` stays the invariant registry,
`src/codex_harness/domain/policy.py` the runtime-limit owner, and DELIVERY.md's ownership table stays
as written until the corresponding implementation is promoted (S11).

**Not a status table.** Status lives only in `coverage/ledger-coverage.json` (`unmapped`, `designed`,
`implemented`, `verified`, `retired-with-authority`), generated from the pinned ledger. File counts and
line diffs are never parity evidence. Parity evidence is the differential harness in `compare/`.

## Symbol labels

Every symbol cell carries one label, checked by `target/tests/test_architecture_doc.py`:

- **CURRENT** — the reference (SOURCE M7) symbol at the worktree root. It must resolve in `src/`.
- **PROPOSED** — the planned target symbol. It must *not* resolve in `target/src` yet: once a slice
  implements it, the slice relabels it TARGET in the same change.
- **TARGET** — an implemented target symbol. It must resolve in `target/src`. S0 has none.

Symbols are `module` or `module:Qualname`; tests are `path::function` or `path`. No line numbers.

## Contexts

| Context | Owns (single writer) | Does not own |
|---|---|---|
| kernel | ids, canonical JSON/digest, `ContractError`, clock/id-source ports, six-W message value types, `RuntimePolicy` | any bucket, any IO |
| storage | PostgreSQL/Redis/artifact access, retention, message/observation JSON-Schema adapters, the per-bucket writer registry check | the meaning of record bodies |
| host_os | process groups/trees, Windows Job objects, background services, scratch, port diagnosis, Git workspaces | which process runs; release policy |
| routing | organization graph and `authorize`, provider/model selection, role-to-container profile mapping | invocation, credentials |
| context | delivered-context composition (L1-L4), budgets, omission reports, context receipts, the retained `ContextPacket` schema | persisted operational state; knowledge storage |
| knowledge | graph/vectors, seams, experience claims, promotion, snapshots, profile data policy | what a run receives |
| intake | desk sessions, tickets, backlog plans and bindings, goals, portfolio | admission/capacity |
| coordination | leases, generations, attempts, inbox/outbox, operations, local cycles, Fleet, continuation, owner actions, breaker, execution time/budgets | provider invocation, deployment stages |
| execution | one invocation: provider transport, role-container lifetime, invocation ledger, worker sessions | credential bytes, leases, verdicts |
| credentials | Codex credential store custody, write-back validation, quarantine, scrubbing sets | containers, processes |
| evidence | claims, inspections, replay, check results, gate verdicts, completion ledger, reviewer hand-off | who may promote |
| review | lead/conductor decisions, release candidates, canary, release queue lease, SDD | deployment stages |
| research | programs, audits, thresholds, decision feedback, autonomous cycle, council, DGE, incidents-to-hooks | provider execution, deployment |
| delivery | HostDelivery plans/stages/leases, host migration, managed runtime, release materialization, restore | Fleet admission |
| observation | observation events/spool, monitoring projection, readiness, viewer, metrics | any control action; desk mutations |
| composition | one object graph per process kind; typed `HostSettings` read once | business rules |
| entry | argv/HTTP/container parsing; one composition call plus one use case | business rules |

Dependency direction: the executable form is the one allowed-edge table of design §3.6, implemented in
`target/tests/import_rules.py` with positive and negative fixtures under
`target/tests/fixtures/import_rules/`. `D(X)` is X's direct row of the §2.4 DAG. The target exception
list is empty; the reference is not checked because it never changes.

## Capabilities

| Capability | Label | Domain / use case | Port | Adapter / entry | Contracts | Tests |
|---|---|---|---|---|---|---|
| intake_backlog | CURRENT | `codex_harness.application.fleet_backlog:FleetBacklog`, `codex_harness.application.frontdesk:FrontDesk` | `codex_harness.ports` | `codex_harness.adapters.frontdesk_http`, `codex_harness.adapters.fleet_cli` | INV-FLEET-BACKLOG-001, INV-TICKET-001 | `tests/test_fleet_backlog.py`, `tests/test_frontdesk.py`, `tests/test_tickets.py` |
| intake_backlog | PROPOSED | `codex_harness.intake.application.backlog:BacklogAdmission` | `codex_harness.intake.ports:FleetQueue` | `codex_harness.entry.http.desk` | INV-FLEET-BACKLOG-001, INV-TICKET-001 | pending (S8) |
| role_provider_routing | CURRENT | `codex_harness.domain.providers:ProviderPolicy`, `codex_harness.adapters.role_containers:select_profile` | `codex_harness.ports` | `codex_harness.adapters.providers` | INV-MODEL-001, INV-NATIVE-REPLAY-001 | `tests/test_model_routing.py`, `tests/test_role_containers.py` |
| role_provider_routing | PROPOSED | `codex_harness.routing.domain.profiles:select_profile` | `codex_harness.routing.adapters.provider_policy` | `codex_harness.composition.settings` | INV-MODEL-001, INV-NATIVE-REPLAY-001 | pending (S2) |
| bounded_context_knowledge | CURRENT | `codex_harness.domain.model:ContextPacket`, `codex_harness.adapters.worker_profile:load_profile` | `codex_harness.ports` | `codex_harness.adapters.knowledge:PostgresKnowledge` | INV-CONTEXT-001, INV-WORKER-PROFILE-001, INV-GRAPH-001 | `tests/test_worker_profile.py`, `compare/goldens/reference/effects.context_packet.json` |
| bounded_context_knowledge | PROPOSED | `codex_harness.context.application.compose:ContextComposer`, `codex_harness.context.domain.packet:ContextPacket` | `codex_harness.context.ports:ProfileSource` | `codex_harness.knowledge.adapters.postgres_knowledge` | INV-CONTEXT-001, INV-WORKER-PROFILE-001, INV-GRAPH-001 | pending (S2) |
| execution_container_credentials | CURRENT | `codex_harness.adapters.executor:Executor`, `codex_harness.adapters.role_containers:CodexCredentialBroker` | `codex_harness.ports` | `codex_harness.adapters.role_containers:IsolatedCodexRuntime`, `codex_harness.adapters.isolated_worker_entry` | INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-INVOCATION-001 | `tests/test_role_containers.py`, `tests/test_executor.py` |
| execution_container_credentials | PROPOSED | `codex_harness.execution.application.run_task:RunTask`, `codex_harness.credentials.adapters.codex_custody:CodexCredentialCustody` | `codex_harness.execution.ports:ProviderRuntime` | `codex_harness.execution.adapters.containers.launcher:RoleContainerLauncher` | INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-INVOCATION-001 | pending (S3/S4) |
| research_self_improvement | CURRENT | `codex_harness.application.research_program:ResearchProgram`, `codex_harness.application.service:Harness` | `codex_harness.ports` | `codex_harness.adapters.research_program_cli` | INV-RESEARCH-PROGRAM-001, INV-RECURRENCE-001 | `tests/test_research_program.py` |
| research_self_improvement | PROPOSED | `codex_harness.research.application.hooks:HookLifecycle` | `codex_harness.research.ports:SourceFetch` | `codex_harness.research.adapters.sources:ResearchSources` | INV-RESEARCH-PROGRAM-001, INV-RECURRENCE-001 | pending (S8) |
| independent_review_promotion | CURRENT | `codex_harness.application.releases:Releases`, `codex_harness.application.release_queue:ReleaseQueue` | `codex_harness.ports` | `codex_harness.adapters.executor:Executor` | INV-RELEASE-001, INV-SESSION-001 | `tests/test_decision_atomicity.py::test_decision_effects_require_current_lease_and_atomic_completion`, `compare/goldens/reference/effects.decision_unit.json` |
| independent_review_promotion | PROPOSED | `codex_harness.review.application.decisions:ReviewDecisions`, `codex_harness.review.application.release_queue:ReleaseQueue` | `codex_harness.review.ports:CandidateVerifier` | `codex_harness.review.adapters.release_verifier` | INV-RELEASE-001, INV-SESSION-001 | pending (S4/S8) |
| storage_artifacts | CURRENT | `codex_harness.adapters.store:PostgresStore`, `codex_harness.adapters.store:MemoryStore` | `codex_harness.ports` | `codex_harness.adapters.bus:RedisBus`, `codex_harness.adapters.artifacts:FileArtifacts` | INV-ARTIFACT-001, INV-MIGRATION-001 | `tests/test_bus.py` |
| storage_artifacts | PROPOSED | `codex_harness.storage.application.artifact_query` | `codex_harness.storage.ports:Store` | `codex_harness.storage.adapters.postgres_store:PostgresStore` | INV-ARTIFACT-001, INV-MIGRATION-001 | pending (S1) |
| deployment_recovery | CURRENT | `codex_harness.application.host_delivery:HostDelivery`, `codex_harness.application.host_migration` | `codex_harness.ports` | `codex_harness.adapters.host_delivery`, `codex_harness.adapters.managed_runtime` | INV-HOST-DELIVERY-001, INV-RECOVERY-001 | `tests/test_host_delivery.py` |
| deployment_recovery | PROPOSED | `codex_harness.delivery.application.host_delivery.controller:DeliveryController` | `codex_harness.delivery.ports:HostTarget` | `codex_harness.delivery.adapters.systemd_target` | INV-HOST-DELIVERY-001, INV-RECOVERY-001 | pending (S7) |
| monitoring_operator_security | CURRENT | `codex_harness.adapters.monitoring:ReadOnlyStore` | `codex_harness.ports` | `codex_harness.adapters.monitoring_web:handler`, `codex_harness.monitor` | INV-MONITOR-VIEWER-001, INV-OBSERVATION-001 | `tests/test_monitoring.py` |
| monitoring_operator_security | PROPOSED | `codex_harness.observation.application.monitoring:SnapshotProjection` | `codex_harness.observation.ports:PostgresFacts` | `codex_harness.observation.adapters.viewer_http:ViewerHandler` | INV-MONITOR-VIEWER-001, INV-OBSERVATION-001 | pending (S9) |
| cli_composition | CURRENT | `codex_harness.application.workflow:Workflow`, `codex_harness.application.operation:Operation`, `codex_harness.application.fleet:Fleet` | `codex_harness.ports` | `codex_harness.cli`, `codex_harness.bootstrap`, `codex_harness.supervisor` | INV-MESSAGE-001, INV-OPERATION-001, INV-FLEET-001 | `tests/test_workflow.py`, `tests/test_operation.py`, `tests/test_fleet.py`, `compare/goldens/reference/cli.parser.json` |
| cli_composition | PROPOSED | `codex_harness.coordination.application.workflow.messages:MessageHandler` | `codex_harness.coordination.ports:TaskRunner` | `codex_harness.entry.cli`, `codex_harness.composition.fleet` | INV-MESSAGE-001, INV-OPERATION-001, INV-FLEET-001 | pending (S5/S10) |

Continuation and owner actions (coordination, S6): CURRENT `codex_harness.application.continuation:Continuation`,
`codex_harness.application.owner_actions:OwnerActions`; PROPOSED
`codex_harness.coordination.application.continuation.tick:ContinuationTick`,
`codex_harness.coordination.application.owner_actions.scheduler:OwnerActionScheduler`; tests
`tests/test_continuation.py`, `tests/test_owner_actions.py`.

## Bucket ownership (design §2.7)

One declared writer context per bucket; a non-owner write inside an atomic unit calls the owner's
tx-taking operation with the unit's transaction. The 18 multi-writer buckets resolve to:
coordination `outbox`, `events`, `decisions_pending`, `tasks`, `local_cycles`, `continuation_intents`;
review `releases`, `release_queue`; research `hooks`, `schedule`, `research_backlog`,
`threshold_review_requests`; delivery `images`; intake `tickets`, `ticket_*`; observation `health`.
Every other bucket candidate's owner is listed per row in `coverage/ledger-coverage.json`; the 169
static buckets are candidates, not a claim that dynamic accesses cannot exist. Each context will
declare `OWNED_BUCKETS` in its `ports.py`; the single-writer check is in `import_rules.py`.

## Atomic units (design §2.9)

`coverage/ledger-coverage.json` lists each M7 `transaction()` block that spans more than one owner
context as an `atomic_unit:` row (static depth 1). The decision/release/outbox unit
(CURRENT `codex_harness.adapters.executor:Executor._commit_decision`) is recorder-confirmed on the
reference in `compare/goldens/reference/effects.decision_unit.json`; disposable-PostgreSQL
confirmation runs in the integration job of its slice.

## Entry shims (design §3.5)

Kept unconditionally, as at most 10-line target modules delegating to `entry`:
`codex_harness.cli`, `codex_harness.monitor`, `codex_harness.supervisor`,
`codex_harness.adapters.isolated_worker_entry`, `codex_harness.adapters.worker_profile_metadata`,
`codex_harness.container_main` (until U6b), the packaged `codex_harness.resources.worker_profile_hook`,
and `src/zeus`. The conditional set follows the S0 pinned-argv scan of tracked sources
(`compare/goldens/reference/static.source.json`, `shims.conditional`): kept for
`continuation_process`, `host_delivery`, `host_migration`, `managed_runtime`, `migrations`,
`monitor_frontend_checks`; no tracked pin found for `artifact_reader`, `experience`,
`isolated_worker`, `observed_assets`, `service_entry`. Reconciliation with argv persisted in records
is pending the disposable rehearsal (R2); until then no shim is dropped.

## Named changes and bugs not retained

- Body/schema changes: **none** (no bucket, field, DDL or migration before cutover acceptance).
- Intentional changes (design §4): production composition requires isolation and does not construct
  host provider transports (S10); Codex native hooks inside containers (S3b); the I2 view-gate
  successor pins the rebuilt bytes.
- Documented bugs not retained (already fixed at M7 and kept fixed): credential bytes in events and
  results (scrubber, I1 F1); a writable `/evidence` without hand-off; desk exposure through
  `ZEUS_DESK_REVISION`. D8a F1-F3 concern operator evaluators outside the product.
- Goldens under `compare/goldens/reference/` come only from reference runs; they are never rewritten
  to match new code, and masks change only through the closed list in `compare/masks.json`.

## Guardrail index

`compare/run.py` (manifest check, reference environment, differential runs), `compare/baseline.json`
(SOURCE and pending DEPLOYMENT baselines), `compare/guard/` (no-real-provider layers),
`compare/harness/` (origin audit, recorder, deterministic inputs, masks), `coverage/generate.py`,
`target/tests/` (allowed-edge checker, guard and recorder controls, coverage checks).
