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
| intake_backlog | PROPOSED | none further (design deviation: intake.application.backlog:BacklogAdmission superseded by codex_harness.coordination.application.fleet_backlog:FleetBacklog, DESIGN-s11 §6.2) | none further (design deviation: intake.ports:FleetQueue superseded by codex_harness.coordination.application.fleet_backlog:FleetBacklog, DESIGN-s11 §6.2) | none further (see TARGET) | INV-FLEET-BACKLOG-001, INV-TICKET-001 | none (delivered; see TARGET) |
| intake_backlog | TARGET | `codex_harness.intake.domain.backlog:select`, `codex_harness.coordination.application.fleet_backlog:FleetBacklog` |  | `codex_harness.composition.fleet_backlog:coordinator` | INV-DISCOVERY-PRESSURE-001, INV-FLEET-BACKLOG-001, INV-MONITOR-VIEWER-001, INV-TICKET-001 | `target/tests/ported/test_fleet_backlog.py`, `target/tests/ported/test_fleet_backlog_cli.py`, `target/tests/test_coordination_discovery_census_reader.py`, `target/tests/test_s10_c8b3_owner_actions.py`, `target/tests/test_s7_move_aheads.py`, `target/tests/test_s8_domain_moves_c.py`, `target/tests/test_s8_fleet_backlog_move.py`, `target/tests/test_s8_portfolio_move.py` |
| role_provider_routing | CURRENT | `codex_harness.domain.providers:ProviderPolicy`, `codex_harness.adapters.role_containers:select_profile` | `codex_harness.ports` | `codex_harness.adapters.providers` | INV-MODEL-001, INV-NATIVE-REPLAY-001 | `tests/test_model_routing.py`, `tests/test_role_containers.py` |
| role_provider_routing | TARGET | `codex_harness.routing.domain.organization:Organization`, `codex_harness.routing.domain.providers:select_execution`, `codex_harness.routing.domain.profiles:select_profile`, `codex_harness.routing.domain.model_selection:select_model` | `codex_harness.routing.adapters.provider_policy:ExecutionPolicy` | `codex_harness.routing.adapters.provider_policy:host_policy`, `codex_harness.routing.adapters.organization_source:packaged_organization` | INV-MODEL-001, INV-CLAUDE-WORKER-001, INV-ROLE-CONTAINER-001 | `compare/goldens/reference/routing.matrix.json` |
| role_provider_routing | TARGET |  |  | `codex_harness.composition.configuration:settings`, `codex_harness.execution.adapters.transports:Transports`, `codex_harness.execution.adapters.containers.launcher:IsolatedClaudeRuntime` | INV-CLAUDE-WORKER-001, INV-MODEL-001, INV-ROLE-CONTAINER-001 | `target/tests/ported/test_claude_assignment.py`, `target/tests/ported/test_configuration.py`, `target/tests/ported/test_decision_recovery.py`, `target/tests/ported/test_zeus_configuration.py`, `target/tests/test_s10_c5c1_isolation.py`, `target/tests/test_s10_c7a_operation_helpers.py`, `target/tests/test_s10_gaps_5a_6.py`, `target/tests/test_s4_run_task.py` |
| role_provider_routing | PROPOSED | none further (design deviation: routing.domain.invocation_contract superseded by codex_harness.routing.domain.providers:select_execution, DESIGN-s11 §6.2) | none further (design deviation: execution.ports:ProviderRuntime superseded by codex_harness.execution.adapters.containers.launcher:IsolatedClaudeRuntime, DESIGN-s11 §6.2) | none further (host settings are read by composition.configuration; see TARGET) | INV-MODEL-001 | none (delivered; see TARGET) |
| bounded_context_knowledge | CURRENT | `codex_harness.domain.model:ContextPacket`, `codex_harness.adapters.worker_profile:load_profile` | `codex_harness.ports` | `codex_harness.adapters.knowledge:PostgresKnowledge` | INV-CONTEXT-001, INV-WORKER-PROFILE-001, INV-GRAPH-001 | `tests/test_worker_profile.py`, `compare/goldens/reference/effects.context_packet.json` |
| bounded_context_knowledge | TARGET | `codex_harness.context.application.compose:ContextComposer`, `codex_harness.context.domain.packet:ContextPacket`, `codex_harness.context.domain.packet:compile_context` | `codex_harness.context.ports:SkillSelection`, `codex_harness.context.ports:SkillHistoryPort`, `codex_harness.context.ports:KnowledgeHits`, `codex_harness.context.ports:ThresholdPolicySource` | `codex_harness.context.adapters.worker_profile:load_profile`, `codex_harness.context.adapters.project_skills:project_context`, `codex_harness.knowledge.adapters.postgres_knowledge:PostgresKnowledge`, `codex_harness.adapters.worker_profile_metadata` | INV-CONTEXT-001, INV-WORKER-PROFILE-001, INV-SKILL-001, INV-SKILL-HISTORY-001, INV-GRAPH-001, INV-NATIVE-REPLAY-001, INV-CLAUDE-WORKER-001, INV-CONTINUATION-001, INV-EXPERIENCE-001, INV-SEAM-001 | `compare/goldens/reference/context.composition.json`, `compare/goldens/reference/effects.context_packet.json`, `target/tests/test_s4_composer_turn_loop.py`, `compare/goldens/reference/context.worker_profile_entry.json`, `compare/goldens/reference/knowledge.units.json`, `target/tests/test_s2_units.py`, `target/tests/ported/test_skill_routing.py`, `target/tests/ported/test_worker_profile_metadata.py`, `target/tests/ported/test_seam_contracts.py` |
| bounded_context_knowledge | TARGET | `codex_harness.research.adapters.council_composition:CouncilCompositionAdmission`, `codex_harness.research.adapters.correction_feedback:deliver`, `codex_harness.research.adapters.threshold_policy:current_policy` |  | `codex_harness.composition.configuration:settings`, `codex_harness.entry.cli.skill_import:main`, `codex_harness.entry.cli.skill_audit:main`, `codex_harness.entry.processes.experience:main` | INV-CLAUDE-WORKER-001, INV-CONTEXT-001, INV-CONTINUATION-001, INV-EXPERIENCE-001, INV-GRAPH-001, INV-NATIVE-REPLAY-001, INV-SEAM-001, INV-SKILL-001, INV-SKILL-HISTORY-001, INV-WORKER-PROFILE-001 | `target/tests/test_s10_c5b2_research_ports.py`, `target/tests/test_s8_council_composition.py`, `target/tests/ported/test_continuation_research.py`, `target/tests/ported/test_correction_feedback.py`, `target/tests/test_s8_correction_feedback_move.py`, `target/tests/ported/test_threshold_collection.py`, `target/tests/ported/test_claude_assignment.py`, `target/tests/ported/test_configuration.py`, `target/tests/ported/test_decision_recovery.py`, `target/tests/ported/test_zeus_configuration.py`, `target/tests/test_s10_c5c1_isolation.py`, `target/tests/test_s10_c7a_operation_helpers.py`, `target/tests/ported/test_skill_import.py`, `target/tests/ported/test_project_skills.py`, `target/tests/ported/test_skill_audit.py`, `target/tests/ported/test_experience.py` |
| bounded_context_knowledge | PROPOSED | none further (design deviation: context.domain.budget superseded by codex_harness.context.domain.packet:compile_context, DESIGN-s11 §6.2) | none further (design deviation: context.ports:ProfileSource superseded by codex_harness.context.adapters.worker_profile:load_profile, DESIGN-s11 §6.2) | none further (see TARGET) | INV-CONTEXT-001 | none (delivered; see TARGET) |
| execution_container_credentials | CURRENT | `codex_harness.adapters.executor:Executor`, `codex_harness.adapters.role_containers:CodexCredentialBroker` | `codex_harness.ports` | `codex_harness.adapters.role_containers:IsolatedCodexRuntime`, `codex_harness.adapters.isolated_worker_entry` | INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-INVOCATION-001 | `tests/test_role_containers.py`, `tests/test_executor.py` |
| execution_container_credentials | TARGET | `codex_harness.execution.domain.container_spec:container_args`, `codex_harness.execution.domain.container_spec:forbidden_controls`, `codex_harness.credentials.domain.codex_credential:credential_shape`, `codex_harness.credentials.adapters.codex_custody:CodexCredentialBroker`, `codex_harness.credentials.adapters.scrubber:CredentialScrubber` | `codex_harness.host_os.ports:ProcessRunner`, `codex_harness.host_os.ports:ChildProcesses` | `codex_harness.execution.adapters.containers.launcher:IsolatedClaudeRuntime`, `codex_harness.execution.adapters.containers.launcher:IsolatedCodexRuntime`, `codex_harness.execution.adapters.containers.owned_container:OwnedContainer`, `codex_harness.execution.adapters.containers.cleanup_ledger:hold`, `codex_harness.execution.adapters.containers.staging:stage_source`, `codex_harness.execution.adapters.containers.handoff:materialize_handoff`, `codex_harness.execution.adapters.providers.codex_app_server:AppServer`, `codex_harness.execution.adapters.providers.native_hooks:container_hooks` | INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-OUTPUT-001, INV-EVIDENCE-001, INV-INVOCATION-001, INV-ISOLATED-WORKER-001, INV-MONITOR-VIEWER-001, INV-PROJECT-EVIDENCE-001 | `compare/goldens/reference/containers.profiles.json`, `compare/goldens/reference/containers.staging.json`, `compare/goldens/reference/credentials.custody.json`, `compare/goldens/reference/credentials.scrubber.json`, `compare/goldens/reference/hooks.native_container.json`, `target/tests/ported/test_role_containers.py`, `target/tests/ported/test_isolated_worker.py`, `target/tests/ported/test_app_server.py`, `target/tests/test_s3_units.py`, `target/tests/test_s3b_native_hooks.py` |
| execution_container_credentials | TARGET | `codex_harness.execution.application.run_task:RunTask` | `codex_harness.execution.ports:TaskLedger`, `codex_harness.execution.ports:TaskLifecycle`, `codex_harness.execution.ports:InvocationAdmission`, `codex_harness.execution.ports:ExecutionRecords` | `codex_harness.composition.operation:build_executor`, `codex_harness.composition.operation:Executor`, `codex_harness.composition.evidence_gate:EvidenceGate`, `codex_harness.composition.processes:container_host`, `codex_harness.composition.isolation:isolated_worker` | INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-INVOCATION-001, INV-EVIDENCE-001, INV-ISOLATED-WORKER-001, INV-MONITOR-VIEWER-001, INV-OUTPUT-001, INV-PROJECT-EVIDENCE-001, INV-WORKER-SESSION-001 | `compare/goldens/reference/execution.run_task.json` |
| execution_container_credentials | TARGET | `codex_harness.evidence.application.evidence_inspection` |  | `codex_harness.execution.adapters.transports:Transports`, `codex_harness.entry.processes.container_main:main`, `codex_harness.entry.processes.isolated_worker:main` | INV-CODEX-CREDENTIAL-001, INV-EVIDENCE-001, INV-INVOCATION-001, INV-ISOLATED-WORKER-001, INV-MONITOR-VIEWER-001, INV-OUTPUT-001, INV-PROJECT-EVIDENCE-001, INV-ROLE-CONTAINER-001 | `target/tests/ported/test_evidence_inspection.py`, `target/tests/ported/test_evidence_lease.py`, `target/tests/ported/test_isolated_project_evidence.py`, `target/tests/ported/test_project_evidence.py`, `target/tests/test_s8_evidence_inspection_move.py`, `target/tests/test_s10_gaps_5a_6.py`, `target/tests/test_s4_run_task.py`, `target/tests/test_s10_e1_entries.py`, `target/tests/test_s10_e5a_process_entries.py` |
| execution_container_credentials | PROPOSED | none further (see TARGET) | none further (design deviation: execution.ports:ProviderRuntime superseded by codex_harness.execution.adapters.containers.launcher:IsolatedClaudeRuntime and codex_harness.execution.adapters.containers.launcher:IsolatedCodexRuntime, DESIGN-s11 §6.2) | none further (see TARGET) | INV-ROLE-CONTAINER-001, INV-CODEX-CREDENTIAL-001, INV-INVOCATION-001 | none (delivered; see TARGET) |
| research_self_improvement | CURRENT | `codex_harness.application.research_program:ResearchProgram`, `codex_harness.application.service:Harness` | `codex_harness.ports` | `codex_harness.adapters.research_program_cli` | INV-RESEARCH-PROGRAM-001, INV-RECURRENCE-001 | `tests/test_research_program.py` |
| research_self_improvement | TARGET | `codex_harness.research.application.hooks:HookLifecycle`, `codex_harness.research.domain.recurrence:Incident`, `codex_harness.research.domain.recurrence:hook_apply` | `codex_harness.research.ports:OutboxAppend`, `codex_harness.research.ports:EventAppend` | none yet (S4 moved the decision unit's research effects ahead; composition wires them, S10) | INV-RECURRENCE-001, INV-MESSAGE-001, INV-AUDIT-PROGRESS-001, INV-DISCOVERY-PRESSURE-001, INV-OBSERVATION-001, INV-RESEARCH-ATTEMPT-SCOPE-001, INV-RESEARCH-PROGRAM-001 | `compare/goldens/reference/research.hook_effects.json` |
| research_self_improvement | TARGET | `codex_harness.research.application.research_program:ResearchProgram` |  | `codex_harness.research.adapters.research:ResearchSources` | INV-AUDIT-PROGRESS-001, INV-DISCOVERY-PRESSURE-001, INV-MESSAGE-001, INV-OBSERVATION-001, INV-RECURRENCE-001, INV-RESEARCH-ATTEMPT-SCOPE-001, INV-RESEARCH-PROGRAM-001 | `target/tests/ported/test_audit_progress.py`, `target/tests/ported/test_research_attempt_scope_chain.py`, `target/tests/ported/test_research_attempt_scope_program.py`, `target/tests/ported/test_research_investigations.py`, `target/tests/ported/test_research_program.py`, `target/tests/ported/test_research_program_cli.py`, `target/tests/ported/test_research_recovery.py`, `target/tests/test_s10_r1_f2b.py`, `target/tests/test_s8_research_program_adapter_move.py`, `target/tests/test_s8_research_program_app_move.py`, `target/tests/ported/test_discovery_pressure.py`, `target/tests/ported/test_executor_research.py`, `target/tests/ported/test_external_context.py`, `target/tests/test_s8_research_sources_move.py` |
| research_self_improvement | PROPOSED | none further (ResearchProgram is TARGET under M7's module name; see TARGET) | none further (design deviation: research.ports:SourceFetch superseded by codex_harness.research.adapters.research:ResearchSources, DESIGN-s11 §6.2) | none further (ResearchSources is TARGET under M7's module name; see TARGET) | INV-RESEARCH-PROGRAM-001, INV-RECURRENCE-001 | none (delivered; see TARGET) |
| independent_review_promotion | CURRENT | `codex_harness.application.releases:Releases`, `codex_harness.application.release_queue:ReleaseQueue` | `codex_harness.ports` | `codex_harness.adapters.executor:Executor` | INV-RELEASE-001, INV-SESSION-001 | `tests/test_decision_atomicity.py::test_decision_effects_require_current_lease_and_atomic_completion`, `compare/goldens/reference/effects.decision_unit.json` |
| independent_review_promotion | TARGET | `codex_harness.review.application.decisions:ReviewDecisions`, `codex_harness.review.application.releases:Releases`, `codex_harness.review.application.release_queue:ReleaseQueue` (S7 moved ahead for delivery), `codex_harness.review.application.releases:Releases.reconcile_audits`, `codex_harness.review.application.releases:Releases.request_reverification` (S8 pilot 106) | `codex_harness.review.ports:DecisionOwnership`, `codex_harness.review.ports:DecisionFailures`, `codex_harness.review.ports:HookEffects`, `codex_harness.review.ports:VerdictInvoker`, `codex_harness.review.ports:ReviewWorkspace`, `codex_harness.review.ports:ExecutionFences`, `codex_harness.review.ports:HookRollback` | none yet (the S4 compare drivers wire it; composition, S10) | INV-RELEASE-001, INV-SESSION-001, INV-OBSERVATION-001, INV-HOST-DELIVERY-VERIFY-001, INV-RELEASE-REVERIFY-001 | `compare/goldens/reference/review.decisions.json`, `compare/goldens/reference/effects.decision_unit.json` |
| independent_review_promotion | TARGET |  |  | `codex_harness.composition.release_verifier:ReleaseVerifier`, `codex_harness.composition.release_verification:release_runner` | INV-HOST-DELIVERY-VERIFY-001, INV-OBSERVATION-001, INV-RELEASE-001, INV-SESSION-001 | `target/tests/test_s10_c8b4_host_delivery.py`, `target/tests/test_s8_batch_b7b_move.py` |
| independent_review_promotion | PROPOSED | none further (see TARGET) | none further (design deviation: review.ports:CandidateVerifier superseded by codex_harness.composition.release_verifier:ReleaseVerifier, DESIGN-s11 §6.2) | none further (candidate verification is composition.release_verifier; see TARGET) | INV-RELEASE-001, INV-SESSION-001 | none (delivered; see TARGET) |
| storage_artifacts | CURRENT | `codex_harness.adapters.store:PostgresStore`, `codex_harness.adapters.store:MemoryStore` | `codex_harness.ports` | `codex_harness.adapters.bus:RedisBus`, `codex_harness.adapters.artifacts:FileArtifacts` | INV-ARTIFACT-001, INV-MIGRATION-001 | `tests/test_bus.py` |
| storage_artifacts | TARGET | `codex_harness.storage.application.artifact_query`, `codex_harness.storage.application.migration_receipts:MigrationReceipts`, `codex_harness.storage.domain.migrations:evaluate`, `codex_harness.observation.adapters.observation_schema:validate_observation` (S9 batch L2-B1) | `codex_harness.storage.ports:Store`, `codex_harness.storage.ports:ArtifactStore`, `codex_harness.storage.ports:MessageBus`, `codex_harness.storage.ports:EventJournal` | `codex_harness.storage.adapters.postgres_store:PostgresStore`, `codex_harness.storage.adapters.memory_store:MemoryStore`, `codex_harness.storage.adapters.redis_bus:RedisBus`, `codex_harness.storage.adapters.file_artifacts:FileArtifacts`, `codex_harness.storage.adapters.maintenance:ArtifactMaintenance`, `codex_harness.storage.adapters.migrator:Migrator` | INV-ARTIFACT-001, INV-MIGRATION-001, INV-MESSAGE-001, INV-AUDIT-REPAIR-001, INV-CLAUDE-WORKER-001 | `target/tests/test_s1_storage_units.py`, `compare/goldens/reference/storage.memory.json`, `compare/goldens/reference/storage.pg.json`, `compare/goldens/reference/storage.redis.json`, `target/tests/ported/test_audit_repair.py`, `target/tests/ported/test_scoped_outbox.py` |
| storage_artifacts | TARGET | `codex_harness.coordination.application.events:EventJournal` |  | `codex_harness.composition.configuration:settings`, `codex_harness.composition.cli_bus`, `codex_harness.observation.adapters.collectors:DatabaseFacts` | INV-ARTIFACT-001, INV-AUDIT-REPAIR-001, INV-CLAUDE-WORKER-001, INV-MESSAGE-001, INV-MIGRATION-001 | `target/tests/test_s10_c5d_executor_roots.py`, `target/tests/test_s4_decision_owners.py`, `target/tests/test_s8_audit_repair_move.py`, `target/tests/test_s8_hook_lifecycle_move.py`, `target/tests/ported/test_claude_assignment.py`, `target/tests/ported/test_configuration.py`, `target/tests/ported/test_decision_recovery.py`, `target/tests/ported/test_zeus_configuration.py`, `target/tests/test_s10_c5c1_isolation.py`, `target/tests/test_s10_c7a_operation_helpers.py` |
| storage_artifacts | PROPOSED | none further (see TARGET) | none further (design deviation: observation.ports:PostgresFacts superseded by codex_harness.observation.adapters.collectors:DatabaseFacts, DESIGN-s11 §6.2) | none further (the Redis namespace is read by composition.cli_bus from the host settings; see TARGET) | INV-OBSERVATION-001 | none (delivered; see TARGET) |
| deployment_recovery | CURRENT | `codex_harness.application.host_delivery:HostDelivery`, `codex_harness.application.host_migration` | `codex_harness.ports` | `codex_harness.adapters.host_delivery`, `codex_harness.adapters.managed_runtime` | INV-HOST-DELIVERY-001, INV-RECOVERY-001 | `tests/test_host_delivery.py` |
| deployment_recovery | TARGET | `codex_harness.delivery.application.host_delivery.controller:DeliveryController`, `codex_harness.delivery.application.host_delivery.state:DeliveryState`, `codex_harness.delivery.application.host_migration:HostMigrations` | `codex_harness.delivery.ports:ReleaseAuthority`, `codex_harness.delivery.ports:ReleaseClaims`, `codex_harness.delivery.ports:ReleaseSettlement` | composition (S10) | INV-HOST-DELIVERY-001, INV-RELEASE-001, INV-HOST-DELIVERY-FIRST-ACTIVATION-001, INV-HOST-MIGRATION-001, INV-OWNER-ACTIONS-001, INV-RELEASE-ENVIRONMENT-REVERIFY-001 | `compare/scenarios/delivery.registry.json`, `compare/scenarios/delivery.stages.json`, `compare/scenarios/delivery.owner_commands.json`, `compare/scenarios/delivery.host_migrations.json` |
| deployment_recovery | TARGET |  |  | `codex_harness.delivery.adapters.host_delivery:HostTargetBase`, `codex_harness.delivery.adapters.host_delivery:ProcessHostTarget`, `codex_harness.delivery.adapters.host_migration:SystemdHostTarget`, `codex_harness.delivery.adapters.managed_runtime:SystemdManagedFleetTarget`, `codex_harness.entry.processes.delivery_service:main` | INV-HOST-DELIVERY-001, INV-HOST-DELIVERY-FIRST-ACTIVATION-001, INV-HOST-MIGRATION-001, INV-OWNER-ACTIONS-001, INV-RELEASE-001, INV-RELEASE-ENVIRONMENT-REVERIFY-001 | `target/tests/ported/test_evaluator_code_guard.py`, `target/tests/ported/test_host_delivery_cli.py`, `target/tests/ported/test_host_delivery_lane_routing.py`, `target/tests/ported/test_host_migration_evidence.py`, `target/tests/ported/test_owner_actions_canary_rearm.py`, `target/tests/ported/test_owner_actions_canary_recovery.py`, `target/tests/ported/test_owner_actions_first_activation.py`, `target/tests/ported/test_owner_canary_plan.py`, `target/tests/ported/test_owner_delivery.py`, `target/tests/test_s10_c8b4_host_delivery.py`, `target/tests/test_s10_r1_f2a.py`, `target/tests/test_s10_e5cd_entries.py`, `target/tests/test_s7_host_migration_adapter.py` |
| deployment_recovery | PROPOSED | none further (see TARGET) | none further (design deviation: delivery.ports:HostTarget superseded by codex_harness.delivery.adapters.host_delivery:HostTargetBase, DESIGN-s11 §6.2) | none further (see TARGET) | INV-HOST-DELIVERY-001, INV-RECOVERY-001 | none (delivered; see TARGET) |
| monitoring_operator_security | CURRENT | `codex_harness.adapters.monitoring:ReadOnlyStore` | `codex_harness.ports` | `codex_harness.adapters.monitoring_web:handler`, `codex_harness.monitor` | INV-MONITOR-VIEWER-001, INV-OBSERVATION-001 | `tests/test_monitoring.py` |
| monitoring_operator_security | TARGET | `codex_harness.observation.application.monitoring:Monitoring`, `codex_harness.observation.application.monitoring:initiatives` (S9 batch L2-B2; M7's own names, OWNER-DECISIONS-S9 D5 as amended) | `codex_harness.observation.ports`, `codex_harness.observation.ports:DeskHttp`, `codex_harness.observation.ports:CollectorPorts` | `codex_harness.observation.adapters.collectors:ReadOnlyStore` (S9 batch L2-B5, U6), `codex_harness.observation.adapters.viewer_http:handler`, `codex_harness.observation.adapters.viewer_http:serve` (S9 batch L2-B3; M7's own names, the desk injected through DeskHttp, OWNER-DECISIONS-S9 D2.1) | INV-MONITOR-VIEWER-001, INV-OBSERVATION-001, INV-METRIC-001 | `target/tests/test_s9_batch_l2b2_move.py`, `target/tests/test_s9_batch_l2b3_move.py` |
| monitoring_operator_security | TARGET |  |  | `codex_harness.observation.adapters.collectors`, `codex_harness.observation.adapters.collectors:DatabaseFacts`, `codex_harness.composition.monitor:collector_ports`, `codex_harness.entry.processes.monitor:main` | INV-LANE-SESSIONS-001, INV-METRIC-001, INV-MONITOR-VIEWER-001, INV-OBSERVATION-001 | `target/tests/test_s10_e2a_monitor.py`, `target/tests/test_s9_batch_l2b6_move.py` |
| monitoring_operator_security | PROPOSED | none further (see TARGET) | none further (design deviation: observation.ports:PostgresFacts superseded by codex_harness.observation.adapters.collectors:DatabaseFacts, DESIGN-s11 §6.2) | none further (see TARGET) | INV-MONITOR-VIEWER-001, INV-OBSERVATION-001 | none (delivered; see TARGET) |
| cli_composition | CURRENT | `codex_harness.application.workflow:Workflow`, `codex_harness.application.operation:Operation`, `codex_harness.application.fleet:Fleet` | `codex_harness.ports` | `codex_harness.cli`, `codex_harness.bootstrap`, `codex_harness.supervisor` | INV-MESSAGE-001, INV-OPERATION-001, INV-FLEET-001 | `tests/test_workflow.py`, `tests/test_operation.py`, `tests/test_fleet.py`, `compare/goldens/reference/cli.parser.json` |
| cli_composition | TARGET | `codex_harness.coordination.application.messages:MessageHandler`, `codex_harness.coordination.application.local_cycle:LocalCycle`, `codex_harness.coordination.application.operation:Operation`, `codex_harness.coordination.application.operation_finalization:park`, `codex_harness.coordination.application.fleet.registry:FleetRegistry`, `codex_harness.coordination.application.fleet.admission:AdmissionControl`, `codex_harness.coordination.application.fleet.pause:FleetPause`, `codex_harness.coordination.application.fleet.recovery:FleetRecovery`, `codex_harness.coordination.application.outbox_relay:OutboxFlusher` | `codex_harness.storage.ports:Store`, `codex_harness.coordination.ports:TaskRunner`, `codex_harness.coordination.ports:DesignGate`, `codex_harness.coordination.ports:EvidenceRecords` | `codex_harness.coordination.application.fleet.runner:FleetRunner`, `codex_harness.entry.cli:parser`, `codex_harness.coordination.adapters.fleet_runtime:LaneLauncher`, `codex_harness.composition.fleet` | INV-MESSAGE-001, INV-OPERATION-FINALIZATION-001, INV-FLEET-001, INV-LOCAL-CYCLE-001, INV-CYCLE-HANDOFF-001 | `compare/goldens/reference/coordination.workflow_handle.json`, `compare/goldens/reference/coordination.local_cycle.json`, `compare/goldens/reference/coordination.operation.json`, `target/tests/test_s5_boundaries.py`, `compare/goldens/reference/coordination.fleet.json`, `compare/goldens/reference/coordination.fleet_recovery.json`, `compare/goldens/reference/coordination.fleet_runner.json`, `compare/goldens/reference/coordination.fleet_relocation.json`, `compare/goldens/reference/coordination.outbox_relay.json`, `compare/goldens/reference/cli.parser.json`, `target/tests/test_s10_unit_p_parser.py`, `target/tests/ported/test_fleet_recovery.py` |
| cli_composition | PROPOSED | none further (see TARGET) | none further (design deviation: coordination.ports:LaneLauncher superseded by codex_harness.coordination.adapters.fleet_runtime:LaneLauncher, DESIGN-s11 §6.2) | none further (see TARGET) | INV-MESSAGE-001, INV-OPERATION-001, INV-FLEET-001 | none (delivered; see TARGET) |

Kernel and host_os (shared, S1; not one of the ten ledger capabilities): TARGET
`codex_harness.kernel.ids:canonical`, `codex_harness.kernel.ids:digest`, `codex_harness.kernel.errors:ContractError`,
`codex_harness.kernel.message:envelope`, `codex_harness.kernel.policy:RuntimePolicy`,
`codex_harness.kernel.usage:headroom`, `codex_harness.kernel.ports:Clock`, `codex_harness.kernel.ports:IdSource`;
`codex_harness.host_os.ports:Workspaces`, `codex_harness.host_os.ports:CandidateInspection`,
`codex_harness.host_os.ports:Publication`, `codex_harness.host_os.adapters.git_workspace:GitWorkspace`,
`codex_harness.host_os.adapters.process_groups:popen` (the one spawn chokepoint),
`codex_harness.host_os.adapters.process_tree:ProcessTree`, `codex_harness.host_os.adapters.scratch:Scratch`,
`codex_harness.host_os.adapters.background_service:run_owned`, `codex_harness.host_os.adapters.service_entry:main`,
`codex_harness.host_os.adapters.windows.job_objects` and `codex_harness.host_os.adapters.windows.no_console`
(W-B, §5.5). Contracts INV-ENCODING-001, INV-SERVICE-DIAGNOSTICS-001, INV-RELEASE-001, INV-RESOURCE-001.
Tests: `target/tests/test_s1_kernel.py`, `target/tests/test_spawn_chokepoint.py`, the ported M7 suites under
`target/tests/ported/`, and the `kernel.values`, `host_os.git` and `host_os.process` differential goldens.

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
declare `OWNED_BUCKETS` in its `ports.py`; the single-writer check is in `import_rules.py`. Declared so
far (S1): storage `maintenance`, `migration_runs`, `knowledge_nodes`, `knowledge_edges`; artifact
collection appends missing-reference `events` through `codex_harness.storage.ports:EventJournal`,
coordination's owner operation (implemented in S5).

## Atomic units (design §2.9)

`coverage/ledger-coverage.json` lists each M7 `transaction()` block that spans more than one owner
context as an `atomic_unit:` row (static depth 1). The decision/release/outbox unit
(CURRENT `codex_harness.adapters.executor:Executor._commit_decision`) is recorder-confirmed on the
reference on `MemoryStore` (`compare/goldens/reference/effects.decision_unit.json`) and on a labelled
disposable PostgreSQL through M7 `PostgresStore` (`effects.decision_unit.pg.json`), with the durable
rows read back from the database.

## Entry shims (design §3.5)

Kept unconditionally, as at most 10-line target modules delegating to `entry`:
`codex_harness.cli`, `codex_harness.monitor`, `codex_harness.supervisor`,
`codex_harness.adapters.isolated_worker_entry`, `codex_harness.adapters.worker_profile_metadata`,
`codex_harness.container_main` (until U6b), the packaged `codex_harness.resources.worker_profile_hook`,
and `src/zeus`. The conditional set follows the S0 pinned-argv scan of tracked sources
(`compare/goldens/reference/static.source.json`, `shims.conditional`): kept for `artifact_reader`
(the multi-line reader argv of M7 `executor.py:252-253`, which the target's
`context.domain.composition.artifact_reader_handle` emits too), `continuation_process`, `host_delivery`,
`host_migration`, `managed_runtime`, `migrations`, `monitor_frontend_checks`; no tracked pin found for
`experience`, `isolated_worker`, `observed_assets`, `service_entry`. Reconciliation with argv persisted in records
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

## Local trust boundary (XC-2a B5, owner 2026-10-05)

`docs/contracts.md` is a reference-fixed path in this rebuild, so the statement lives here, beside the layer map.

- The bus and the CLI trust the local OS user, exactly as the desk does (`entry/http/desk.py`): a sender, actor or
  approver named in a message or a CLI argument is an asserted string, not an authenticated identity.
- Authority for a review, report or result comes from durable rows, never from the asserted sender: a `review.result` or
  `task.result` is accepted only when a stored decision or task row binds that sender and that result
  (`MessageHandler.handle`, "Unproven decision result" / "Unproven task result"; pinned by
  `target/tests/test_s11_xc2a.py`).
- Redis must stay loopback-only and/or ACL'd. That is deployment configuration, recorded for the R/C review; the
  product does not enforce it.

## Guardrail index

`compare/run.py` (manifest check, reference environment, differential runs), `compare/baseline.json`
(SOURCE and pending DEPLOYMENT baselines), `compare/guard/` (no-real-provider layers),
`compare/harness/` (origin audit, recorder, deterministic inputs, masks), `coverage/generate.py`,
`target/tests/` (allowed-edge checker, guard and recorder controls, coverage checks).
