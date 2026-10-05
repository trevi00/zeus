"""Generate `coverage/ledger-coverage.json`, the one old/new coverage table (REBUILD-DESIGN-v2 §1.5).

Layer: harness (never shipped); standard library only.

    python coverage/generate.py --ledger <FLEET-REBUILD-LEDGER.json>            # write (refused over a maintained table)
    python coverage/generate.py --ledger <FLEET-REBUILD-LEDGER.json> --check    # compare the generated skeleton only

Row identities are frozen from the ledger (sha256 pinned below). The context of each module row is
the accepted design mapping (`scratch/rebuild-design/map.py`, reproduced literally in MAP, with the
two declared v2 corrections: `platform` is named `host_os`, and `adapters/contracts.py` moves to
`storage.adapters.message_schema` + `observation.adapters.observation_schema`). Target symbols are
PROPOSED: the §3.1 tree where it names one, else `codex_harness.<context>.<layer>.<module>`. S0
assigned `designed` or `unmapped` only. A slice moves exactly its own rows to `implemented` (target
code and target tests exist; `SLICE_ROWS` below, with evidence links); `verified` additionally needs
Codex's slice acceptance and is never set by this generator: since S11 `coverage/relabel.py` computes every status
(and the maintained `verification` field) from the rows, the tree and its run-evidence bundle.
Untraced rows keep their ledger trace status. Bucket rows stay candidates. Atomic-unit rows are an
explicit extension keyed by M7 symbol (`compare/goldens/reference/static.source.json`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "ledger-coverage.json"
LEDGER_SHA256 = "38a84d48e4ede80839850fa087e87d526d885fdd32aa452193cb0ad307c048ee"
STATUSES = ("unmapped", "designed", "implemented", "verified", "retired-with-authority")

MAP = {
    "kernel": "domain/model domain/policy domain/usage_policy ports __init__ adapters/__init__ "
              "application/__init__ domain/__init__ resources/__init__",
    "intake": "application/frontdesk domain/frontdesk adapters/frontdesk application/tickets "
              "application/ticket_lifecycle domain/ticket_lifecycle adapters/ticket_authority "
              "adapters/ticket_review adapters/github_tickets application/fleet_backlog domain/fleet_backlog "
              "adapters/fleet_backlog application/goal_progress application/portfolio adapters/portfolio",
    "routing": "domain/providers adapters/providers domain/model_routing adapters/native_routing_replay",
    "context": "adapters/worker_profile adapters/worker_profile_metadata resources/worker_profile_hook "
               "adapters/project_skills domain/project_skills adapters/skill_routing adapters/skill_guidance "
               "domain/skill_guidance adapters/skill_history application/skill_history domain/skill_history "
               "adapters/skill_import application/skill_import domain/skill_import adapters/skill_audit "
               "domain/skill_audit domain/skill_ranking domain/skill_admission adapters/project_detection "
               "adapters/project_pipeline domain/pipeline adapters/profile_scratch application/rlm",
    "knowledge": "adapters/knowledge adapters/embeddings adapters/seam_extraction domain/seams domain/seam_view "
                 "application/seam_ledger adapters/experience application/experience domain/experience "
                 "application/promotion application/snapshot_imports domain/snapshot_integrity "
                 "application/profile_flow domain/profile_privacy",
    "coordination": "application/workflow application/operation domain/operation application/operation_finalization "
                    "application/local_cycle application/outbox application/fleet domain/fleet adapters/fleet_runtime "
                    "application/continuation domain/continuation adapters/continuation adapters/continuation_process "
                    "application/owner_actions domain/owner_actions adapters/owner_actions application/breaker "
                    "domain/breaker application/execution_time application/execution_fence "
                    "application/execution_budget application/execution_notices application/execution_rejections "
                    "application/execution_recovery application/decision_recovery",
    "execution": "adapters/executor adapters/app_server adapters/claude_cli adapters/codex adapters/hooks "
                 "adapters/call_budget application/invocation_ledger domain/invocation domain/provider_stream "
                 "adapters/output_schema adapters/execution_output application/worker_sessions "
                 "domain/worker_sessions adapters/worker_sessions adapters/isolated_worker adapters/role_containers",
    "evidence": "domain/evidence application/evidence_inspection adapters/evidence_inspection domain/check_results "
                "domain/gate_verdicts application/completion domain/completion domain/project_evidence "
                "adapters/project_evidence adapters/isolated_evidence",
    "review": "application/releases application/release_queue adapters/release_verifier adapters/release_suite "
              "adapters/verification adapters/canary application/sdd domain/sdd adapters/sdd",
    "research": "application/research domain/research adapters/research application/research_program "
                "domain/research_program adapters/research_program domain/research_attempt_scope "
                "domain/research_investigations application/discovery_pressure domain/discovery_pressure "
                "adapters/discovery_pressure application/audit_gate application/audit_progress domain/audit_progress "
                "application/audit_repair domain/audit_repair adapters/audit_repair adapters/audit_execution "
                "adapters/audit_runner adapters/audit_service adapters/observed_assets adapters/reverse_source "
                "adapters/source_verification adapters/source_execution application/source_execution "
                "application/threshold_approvals application/threshold_proposals domain/threshold_proposals "
                "adapters/threshold_proposals application/threshold_replay domain/threshold_replay "
                "adapters/threshold_replay application/threshold_reviews adapters/threshold_reviews "
                "adapters/threshold_policy adapters/runtime_thresholds application/decision_feedback "
                "domain/decision_feedback adapters/decision_feedback adapters/correction_feedback "
                "application/scheduling application/reverse_progress application/autonomous domain/autonomous "
                "adapters/autonomous_roles adapters/autonomous_evidence application/council domain/council "
                "domain/council_input adapters/council_snapshot application/dge domain/dge application/service",
    "delivery": "application/host_delivery domain/host_delivery adapters/host_delivery application/host_migration "
                "domain/host_migration adapters/host_migration domain/host_migration_evidence "
                "adapters/host_migration_evidence adapters/deployment adapters/managed_runtime "
                "domain/managed_runtime domain/fleet_recovery adapters/fleet_recovery",
    "observation": "domain/observation application/observations adapters/observation_spool adapters/monitoring "
                   "application/monitoring adapters/monitoring_observations adapters/monitoring_readiness "
                   "adapters/monitoring_web adapters/monitor_frontend_checks domain/progress_activity "
                   "application/measurements domain/measurements",
    "storage": "adapters/store adapters/bus adapters/artifacts adapters/artifact_reader application/artifact_query "
               "adapters/maintenance adapters/migrations domain/migrations application/migration_receipts "
               "adapters/contracts",
    "host_os": "adapters/process_tree adapters/commands adapters/background_service adapters/service_entry "
               "adapters/scratch adapters/published_ports adapters/port_diagnosis adapters/git",
    "entry": "cli container_main monitor supervisor adapters/operation_cli adapters/autonomous_cli "
             "adapters/continuation_cli adapters/decision_feedback_cli adapters/dge_cli adapters/fleet_cli "
             "adapters/frontdesk_cli adapters/frontdesk_http adapters/research_program_cli adapters/sdd_cli "
             "adapters/ticket_cli adapters/audit_repair_cli adapters/isolated_worker_entry",
    "composition": "bootstrap adapters/configuration",
}
# Explicit §3.1/§3.5 target symbols (PROPOSED); every other module follows the default rule.
SYMBOLS = {
    "adapters/contracts": ["codex_harness.storage.adapters.message_schema",
                           "codex_harness.observation.adapters.observation_schema"],
    "adapters/executor": ["codex_harness.execution.application.run_task.RunTask",
                          "codex_harness.review.application.decisions.ReviewDecisions"],
    "adapters/store": ["codex_harness.storage.adapters.postgres_store",
                       "codex_harness.storage.adapters.memory_store"],
    "adapters/bus": ["codex_harness.storage.adapters.redis_bus"],
    "adapters/artifacts": ["codex_harness.storage.adapters.file_artifacts"],
    "adapters/migrations": ["codex_harness.storage.adapters.migrator"],
    "adapters/git": ["codex_harness.host_os.adapters.git_workspace"],
    "adapters/commands": ["codex_harness.host_os.adapters.process_groups",
                          "codex_harness.host_os.adapters.windows.no_console"],
    "adapters/process_tree": ["codex_harness.host_os.adapters.process_tree",
                              "codex_harness.host_os.adapters.windows.job_objects"],
    "__init__": ["codex_harness (target package root)"],
    "resources/__init__": ["codex_harness.resources (unchanged bytes)"],
    "adapters/__init__": ["codex_harness.adapters (the §3.5 entry-shim package, S10)"],
    "application/__init__": ["none: empty M7 layer marker; the target's per-context layer packages replace it "
                             "(disposition at S11 promotion)"],
    "domain/__init__": ["none: empty M7 layer marker; the target's per-context layer packages replace it "
                        "(disposition at S11 promotion)"],
    "adapters/app_server": ["codex_harness.execution.adapters.providers.codex_app_server"],
    "adapters/claude_cli": ["codex_harness.execution.adapters.providers.claude_cli"],
    "adapters/codex": ["codex_harness.execution.adapters.providers.codex_exec"],
    "adapters/hooks": ["codex_harness.execution.adapters.providers.native_hooks"],
    "adapters/role_containers": ["codex_harness.execution.adapters.containers.launcher",
                                 "codex_harness.credentials.adapters.codex_custody",
                                 "codex_harness.credentials.adapters.scrubber"],
    "adapters/isolated_worker": ["codex_harness.execution.adapters.containers.owned_container",
                                 "codex_harness.execution.adapters.containers.cleanup_ledger",
                                 "codex_harness.execution.adapters.containers.staging"],
    "adapters/monitoring": ["codex_harness.observation.adapters.collectors",
                            "codex_harness.observation.application.monitoring.SnapshotProjection"],
    "adapters/monitoring_web": ["codex_harness.observation.adapters.viewer_http.ViewerHandler"],
    "adapters/frontdesk_http": ["codex_harness.entry.http.desk"],
    "application/service": ["codex_harness.research.application.hooks.HookLifecycle",
                            "codex_harness.coordination.application.sessions",
                            "codex_harness.coordination.application.outbox"],
    "application/fleet": ["codex_harness.coordination.application.fleet.registry.FleetRegistry",
                          "codex_harness.coordination.application.fleet.admission.AdmissionControl",
                          "codex_harness.coordination.application.fleet.pause.FleetPause",
                          "codex_harness.coordination.application.fleet.recovery.FleetRecovery"],
    "application/host_delivery": ["codex_harness.delivery.application.host_delivery.controller.DeliveryController"],
    "application/continuation": ["codex_harness.coordination.application.continuation.tick.ContinuationTick"],
    "application/owner_actions": ["codex_harness.coordination.application.owner_actions.scheduler"
                                  ".OwnerActionScheduler"],
    "domain/model": ["codex_harness.kernel.ids", "codex_harness.kernel.errors", "codex_harness.kernel.message",
                     "codex_harness.routing.domain.organization",
                     "codex_harness.context.domain.packet.ContextPacket"],
    "domain/policy": ["codex_harness.kernel.policy"],
    "domain/usage_policy": ["codex_harness.kernel.usage"],
    "ports": ["codex_harness.kernel.ports", "codex_harness.storage.ports", "codex_harness.host_os.ports"],
    "bootstrap": ["codex_harness.composition"],
    "adapters/configuration": ["codex_harness.composition.settings"],
    "cli": ["codex_harness.entry.cli", "codex_harness.cli (permanent shim)"],
    "monitor": ["codex_harness.entry.processes.monitor", "codex_harness.monitor (permanent shim)"],
    "supervisor": ["codex_harness.entry.processes.supervisor", "codex_harness.supervisor (permanent shim)"],
    "container_main": ["codex_harness.entry.processes.container_main",
                       "codex_harness.container_main (permanent shim until U6b)"],
    "adapters/isolated_worker_entry": ["codex_harness.entry.processes.isolated_worker",
                                       "codex_harness.adapters.isolated_worker_entry (permanent shim)"],
    "adapters/worker_profile_metadata": ["codex_harness.context.adapters.worker_profile_metadata",
                                         "codex_harness.adapters.worker_profile_metadata (permanent shim)"],
    "resources/worker_profile_hook": ["codex_harness.resources.worker_profile_hook (packaged resource)"],
}
INTENT = {
    "adapters/app_server": "change:§4 Role authority (host App Server transport constructible only in "
                           "the dev composition)",
    "bootstrap": "change:§4 Role authority (production composition requires isolation; S10)",
    "adapters/executor": "change:§4 Documented limitations (S3b Codex native hooks inside containers)",
}
CONTRACT_OWNERS = {
    "kernel": "ENCODING-001",
    "storage": "ARTIFACT-001 MIGRATION-001 RESOURCE-001",
    "host_os": "SERVICE-DIAGNOSTICS-001",
    "routing": "MODEL-001 NATIVE-REPLAY-001",
    "context": "CONTEXT-001 PIPELINE-001 PROJECT-001 SKILL-001 SKILL-HISTORY-001 SKILL-IMPORT-001 "
               "WORKER-PROFILE-001",
    "knowledge": "EXPERIENCE-001 GRAPH-001 PROFILE-001 SEAM-001 SEAM-SCOPE-001 SEAM-VIEW-001 SNAPSHOT-001",
    "intake": "FLEET-BACKLOG-001 GOAL-PROGRESS-001 TICKET-001",
    "coordination": "BREAKER-001 CONTINUATION-001 CYCLE-HANDOFF-001 EXECUTION-IDENTITY-001 EXECUTION-TIME-001 "
                    "FLEET-001 IDEMPOTENCY-001 LOCAL-CYCLE-001 MESSAGE-001 OPERATION-001 "
                    "OPERATION-FINALIZATION-001 OWNER-ACTIONS-001 OWNER-ACTIONS-MIGRATION-001 SESSION-001",
    "execution": "CLAUDE-WORKER-001 INVOCATION-001 ISOLATED-WORKER-001 OUTPUT-001 ROLE-CONTAINER-001 "
                 "WORKER-SESSION-001",
    "credentials": "CODEX-CREDENTIAL-001",
    "evidence": "CHECK-001 COMPLETION-001 EVIDENCE-001 GATE-001 PROJECT-EVIDENCE-001",
    "review": "CHECK-002 ORACLE-001 RELEASE-001 RELEASE-ENVIRONMENT-REVERIFY-001 RELEASE-EVALUATOR-MIGRATION-001 "
              "RELEASE-FILE-CANARY-001 RELEASE-REVERIFY-001 SDD-001 SDD-002 VERIFICATION-001",
    "research": "AUDIT-PROGRESS-001 AUDIT-REPAIR-001 AUDIT-SERVICE-001 AUTONOMOUS-001 COUNCIL-001 "
                "DECISION-FEEDBACK-001 DGE-001 DISCOVERY-PRESSURE-001 RECURRENCE-001 RESEARCH-001 RESEARCH-002 "
                "RESEARCH-003 RESEARCH-004 RESEARCH-ATTEMPT-SCOPE-001 RESEARCH-PROGRAM-001 REVERSE-001 "
                "RUNNER-001 THRESHOLD-APPROVAL-001 THRESHOLD-POLICY-001 THRESHOLD-PROPOSAL-001 "
                "THRESHOLD-REVIEW-001",
    "delivery": "HOST-DELIVERY-001 HOST-DELIVERY-FIRST-ACTIVATION-001 HOST-DELIVERY-MIGRATION-001 "
                "HOST-DELIVERY-VERIFY-001 HOST-MIGRATION-001 RECOVERY-001",
    "observation": "LANE-SESSIONS-001 METRIC-001 MONITOR-VIEWER-001 OBSERVATION-001",
}
CAPABILITY_OWNERS = {
    "intake_backlog": "intake", "role_provider_routing": "routing", "bounded_context_knowledge": "context",
    "execution_container_credentials": "execution", "research_self_improvement": "research",
    "independent_review_promotion": "review", "storage_artifacts": "storage",
    "deployment_recovery": "delivery", "monitoring_operator_security": "observation",
    "cli_composition": "composition",
}
BUCKET_OWNERS = {  # §2.7: one owner for each multi-writer bucket
    "outbox": "coordination", "events": "coordination", "decisions_pending": "coordination",
    "tasks": "coordination", "local_cycles": "coordination", "continuation_intents": "coordination",
    "releases": "review", "release_queue": "review", "hooks": "research", "schedule": "research",
    "research_backlog": "research", "threshold_review_requests": "research", "images": "delivery",
    "tickets": "intake", "health": "observation",
}
FLOW_OWNERS = ["coordination", "coordination", "coordination", "delivery", "observation"]
FLOW_EVIDENCE = [["effects.decision_unit", "effects.decision_unit.pg"], [], [], [], []]
UNTRACED_SLICE = {"kernel": "S1", "storage": "S1", "host_os": "S1", "routing": "S2", "context": "S2",
                  "knowledge": "S2", "credentials": "S3", "execution": "S3/S4", "coordination": "S5/S6",
                  "delivery": "S7", "review": "S8", "research": "S8", "intake": "S8", "evidence": "S8",
                  "observation": "S9", "composition": "S10", "entry": "S10"}


# --- slice progress (§1.5): rows a slice has implemented, with their evidence --------------------
TARGET_SRC = ROOT / "target" / "src"
S1_TESTS = {
    "kernel": ["target:tests/test_s1_kernel.py", "compare:kernel.values"],
    "storage": ["target:tests/test_s1_storage_units.py", "compare:storage.memory", "compare:storage.pg",
                "compare:storage.redis"],
    "host_os": ["target:tests/test_spawn_chokepoint.py", "compare:host_os.git", "compare:host_os.process"],
}
S1_MODULE_TESTS = {  # M7 module key -> ported suites that now run against the target
    "adapters/git": ["test_git.py", "test_git_merge_cas.py", "test_git_workspace.py"],
    "adapters/commands": ["test_python_channel.py", "test_windows_launchers.py", "test_git_workspace.py"],
    "adapters/process_tree": ["test_background_service.py"],
    "adapters/background_service": ["test_background_service.py"],
    "adapters/service_entry": ["test_service_entry.py"],
    "adapters/scratch": ["test_scratch_cleanup.py"],
    "adapters/published_ports": ["test_published_ports.py", "test_published_ports_cross_host.py"],
    "adapters/port_diagnosis": ["test_port_diagnosis.py"],
    "adapters/bus": ["test_bus.py"],
    "application/artifact_query": ["test_artifact_query.py"],
    "adapters/artifact_reader": ["test_artifact_query.py"],
    "adapters/migrations": ["test_migration_precheck.py"],
    "domain/migrations": ["test_migration_precheck.py"],
    "application/migration_receipts": ["test_migration_precheck.py"],
    "adapters/artifacts": ["test_migration_precheck.py"],
    "adapters/store": ["test_migration_precheck.py"],
}
# M7 module key -> the target module files that hold its public names (S1).
S1_TARGET_FILES = {
    "domain/model": ["kernel/ids.py", "kernel/errors.py", "kernel/message.py"],
    "domain/policy": ["kernel/policy.py"], "domain/usage_policy": ["kernel/usage.py"],
    "ports": ["kernel/ports.py", "storage/ports.py", "host_os/ports.py"],
    "adapters/store": ["storage/adapters/postgres_store.py", "storage/adapters/memory_store.py"],
    "adapters/bus": ["storage/adapters/redis_bus.py"], "adapters/artifacts": ["storage/adapters/file_artifacts.py"],
    "adapters/artifact_reader": ["storage/adapters/artifact_reader.py"],
    "application/artifact_query": ["storage/application/artifact_query.py"],
    "adapters/maintenance": ["storage/adapters/maintenance.py"], "adapters/migrations": ["storage/adapters/migrator.py"],
    "domain/migrations": ["storage/domain/migrations.py"],
    "application/migration_receipts": ["storage/application/migration_receipts.py"],
    "adapters/contracts": ["storage/adapters/message_schema.py"],
    "adapters/process_tree": ["host_os/adapters/process_tree.py"],
    "adapters/commands": ["host_os/adapters/process_groups.py", "host_os/adapters/windows/no_console.py"],
    "adapters/background_service": ["host_os/adapters/background_service.py"],
    "adapters/service_entry": ["host_os/adapters/service_entry.py"], "adapters/scratch": ["host_os/adapters/scratch.py"],
    "adapters/published_ports": ["host_os/adapters/published_ports.py"],
    "adapters/port_diagnosis": ["host_os/adapters/port_diagnosis.py"], "adapters/git": ["host_os/adapters/git_workspace.py"],
}
# Whole module rows S1 implements (every target symbol of the row exists). Partial rows stay
# `designed` with `slice_progress` naming what S1 did and which slice owns the rest.
S1_MODULES = {k for k in S1_TARGET_FILES if k not in {"domain/model", "adapters/contracts"}} | {
    "__init__", "resources/__init__"}
S1_PARTIAL = {
    "domain/model": "S1 implemented kernel.ids/errors/message (canonical, digest, utcnow, ContractError, "
                    "ExecutionFailure, require, envelope); Organization/Agent -> routing (S2), ContextPacket/"
                    "ContextItem/compile_context -> context (S2), session_action -> coordination (S5), "
                    "Incident/hook_apply -> research (S8)",
    "adapters/contracts": "S1 implemented storage.adapters.message_schema:validate_message; "
                          "validate_observation -> observation.adapters.observation_schema (S9)",
}
# Public names of S1 modules that move to another context's slice (§1.2/§2.5), with their target.
MOVED_NAMES = {
    ("domain/model", "Agent"): ("routing", "codex_harness.routing.domain.organization:Agent"),
    ("domain/model", "Organization"): ("routing", "codex_harness.routing.domain.organization:Organization"),
    ("domain/model", "conductor_self_arbitration"): (
        "routing", "codex_harness.routing.domain.organization:conductor_self_arbitration"),
    ("domain/model", "ContextItem"): ("context", "codex_harness.context.domain.packet:ContextItem"),
    ("domain/model", "ContextPacket"): ("context", "codex_harness.context.domain.packet:ContextPacket"),
    ("domain/model", "compile_context"): ("context", "codex_harness.context.domain.composition:compile_context"),
    ("domain/model", "session_action"): ("coordination", "codex_harness.coordination.application.sessions:session_action"),
    ("domain/model", "Incident"): ("research", "codex_harness.research.domain.recurrence:Incident"),
    ("domain/model", "hook_apply"): ("research", "codex_harness.research.domain.recurrence:hook_apply"),
    ("ports", "SpoolFull"): ("observation", "codex_harness.observation.ports:SpoolFull"),
    ("ports", "ObservationSpool"): ("observation", "codex_harness.observation.ports:ObservationSpool"),
    ("ports", "ObservationDirectory"): (
        "observation", "codex_harness.observation.ports:SpoolReader+HealthRecords+TerminationRecords"),
    ("ports", "Runtime"): ("execution", "codex_harness.execution.ports:ProviderRuntime"),
    ("ports", "Knowledge"): ("knowledge", "codex_harness.knowledge.ports:CodeIndex+KnowledgeQuery"),
    ("ports", "SourceVerifier"): ("research", "codex_harness.research.ports:SourceVerifier"),
    ("adapters/contracts", "validate_observation"): (
        "observation", "codex_harness.observation.adapters.observation_schema:validate_observation"),
}
# Renamed/split public names inside S1 (§2.5 SourceControl split; AuditArtifacts = ArtifactStore+ArtifactReader).
S1_RENAMED = {
    ("ports", "SourceControl"): ["codex_harness.host_os.ports:Workspaces", "codex_harness.host_os.ports:CandidateInspection",
                                 "codex_harness.host_os.ports:Publication"],
    ("ports", "AuditArtifacts"): ["codex_harness.storage.ports:ArtifactStore", "codex_harness.storage.ports:ArtifactReader"],
}
S1_RESOURCES = {"001.sql", "migrations.json", "message.schema.json"}
S1_CONTRACTS = {"INV-ENCODING-001": ["target:tests/ported/test_python_channel.py", "compare:host_os.process"],
                "INV-ARTIFACT-001": ["target:tests/ported/test_artifact_query.py", "compare:storage.memory"],
                "INV-MIGRATION-001": ["target:tests/ported/test_migration_precheck.py", "compare:storage.pg"],
                "INV-RESOURCE-001": ["target:tests/test_s1_storage_units.py", "compare:storage.memory",
                                     "compare:kernel.values"],
                "INV-SERVICE-DIAGNOSTICS-001": ["target:tests/ported/test_service_entry.py",
                                                "target:tests/ported/test_port_diagnosis.py", "compare:host_os.process"]}
S1_BUCKETS = {"maintenance", "migration_runs", "knowledge_nodes", "knowledge_edges"}


def _target_names(files: list[str]) -> dict[str, str]:
    """Top-level public names defined in the given target files -> dotted module path."""
    import ast
    out = {}
    for rel in files:
        path = TARGET_SRC / "codex_harness" / rel
        if not path.is_file():
            continue
        module = "codex_harness." + rel[:-3].replace("/", ".")
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            names = []
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for name in names:
                out.setdefault(name, module)
    return out


def apply_s1(rows: list[dict]) -> None:
    """Move the S1 rows (kernel/storage/host_os) to `implemented` with evidence; nothing else."""
    for r in rows:
        kind, key = r["kind"], r["key"]
        if kind == "module":
            mkey = module_key(key[len("module:"):]) or ""
            if r["target_owner"] not in S1_TESTS:
                continue
            ported = [f"target:tests/ported/{name}" for name in S1_MODULE_TESTS.get(mkey, [])]
            if mkey in S1_MODULES:
                r["status"] = "implemented"
                r["evidence"] = S1_TESTS[r["target_owner"]] + ported + [
                    "target:tests/test_architecture.py::test_target_tree_has_no_violation_and_no_exception"]
            elif mkey in S1_PARTIAL:
                r["slice_progress"] = S1_PARTIAL[mkey]
                r["evidence"] = S1_TESTS[r["target_owner"]] + r["evidence"]
        elif kind == "public_api":
            path, _, name = key[len("api:"):].partition("::")
            mkey = module_key(path) or ""
            if (mkey, name) in MOVED_NAMES:
                owner, symbol = MOVED_NAMES[(mkey, name)]
                r["target_owner"], r["target_symbol"], r["symbol_basis"] = owner, [symbol], "design §1.2/§2.5"
                continue
            if (mkey, name) in S1_RENAMED:
                r["target_symbol"], r["symbol_basis"] = S1_RENAMED[(mkey, name)], "design §2.5"
                r["status"], r["evidence"] = "implemented", S1_TESTS[r["target_owner"]]
                continue
            if mkey not in S1_TARGET_FILES:
                continue
            found = _target_names(S1_TARGET_FILES[mkey]).get(name)
            if found is not None:
                r["target_symbol"], r["status"] = [f"{found}:{name}"], "implemented"
                r["evidence"] = S1_TESTS[r["target_owner"]] + [
                    f"target:tests/ported/{n}" for n in S1_MODULE_TESTS.get(mkey, [])]
        elif kind == "contract" and key[len("contract:"):] in S1_CONTRACTS:
            r["status"] = "implemented"
            r["evidence"] = S1_CONTRACTS[key[len("contract:"):]] + [e for e in r["evidence"]
                                                                   if not e.startswith("pending:")]
        elif kind == "resource" and key.rsplit("/", 1)[-1] in S1_RESOURCES:
            r["status"] = "implemented"
            r["evidence"] = ["target:tests/test_s1_storage_units.py::test_packaged_resources_are_the_source_bytes",
                             "compare:storage.pg" if not key.endswith("message.schema.json") else "compare:kernel.values"]
        elif kind == "bucket" and key[len("bucket:"):] in S1_BUCKETS:
            r["status"] = "implemented"
            r["evidence"] = ["codex_harness.storage.ports.OWNED_BUCKETS",
                             "target:tests/test_s1_storage_units.py::test_storage_declares_its_owned_buckets_and_not_events"]
        elif kind == "capability" and key == "capability:storage_artifacts":
            r["status"] = "implemented"
            r["evidence"] = ["docs/context/ARCHITECTURE.md#capabilities"] + S1_TESTS["storage"]
        elif kind == "atomic_unit" and key == "atomic_unit:codex_harness.adapters.maintenance:ArtifactMaintenance.collect#1":
            r["status"] = "implemented"
            r["target_symbol"] = ["codex_harness.storage.adapters.maintenance:ArtifactMaintenance.collect (one "
                                  "Store.transaction(); events through storage.ports:EventJournal.append(tx, ...))"]
            r["evidence"] = ["compare:storage.memory#maintenance",
                             "target:tests/test_s1_storage_units.py::test_a_failing_journal_rolls_the_whole_collection_back"]



# --- S2 (routing, context, knowledge) --------------------------------------------------------------
S2_TESTS = {
    "routing": ["compare:routing.matrix", "target:tests/test_s2_units.py", "target:tests/ported/test_model_routing.py"],
    "context": ["compare:context.composition", "compare:context.worker_profile_entry", "target:tests/test_s2_units.py"],
    "knowledge": ["compare:knowledge.units", "target:tests/test_s2_units.py"],
}
ARCH = "target:tests/test_architecture.py::test_target_tree_has_no_violation_and_no_exception"
# M7 module key -> (target files holding its public names, ported suites run against the target).
S2_TARGET_FILES = {
    "domain/providers": (["routing/domain/providers.py"], []),
    "adapters/providers": (["routing/adapters/provider_policy.py"], []),
    "domain/model_routing": (["routing/domain/model_selection.py"], ["test_model_routing.py"]),
    "adapters/native_routing_replay": (["context/adapters/native_routing_replay.py"], ["test_native_routing_replay.py"]),
    "adapters/worker_profile": (["context/adapters/worker_profile.py"], ["test_worker_profile.py"]),
    "adapters/worker_profile_metadata": (["context/adapters/worker_profile_metadata.py",
                                          "adapters/worker_profile_metadata.py"], ["test_worker_profile_metadata.py"]),
    "resources/worker_profile_hook": (["resources/worker_profile_hook.py"], ["test_worker_profile.py"]),
    "adapters/project_skills": (["context/adapters/project_skills.py", "context/adapters/yaml_source.py"],
                                ["test_project_skills.py"]),
    "domain/project_skills": (["context/domain/project_skills.py"], ["test_project_skills.py"]),
    "adapters/skill_routing": (["context/adapters/skill_routing.py"], ["test_skill_routing.py"]),
    "adapters/skill_guidance": (["context/adapters/skill_guidance.py"], ["test_skill_guidance.py"]),
    "domain/skill_guidance": (["context/domain/skills/guidance.py"], ["test_skill_guidance.py"]),
    "adapters/skill_history": (["context/adapters/skill_history.py"], ["test_skill_history.py"]),
    "application/skill_history": (["context/application/skill_history.py"], ["test_skill_history.py"]),
    "domain/skill_history": (["context/domain/skills/history.py"], ["test_skill_history.py"]),
    "adapters/skill_import": (["context/adapters/skill_import.py"], ["test_skill_import.py"]),
    "application/skill_import": (["context/application/skill_import.py"], ["test_skill_import.py"]),
    "domain/skill_import": (["context/domain/skills/import_.py"], ["test_skill_import.py"]),
    "adapters/skill_audit": (["context/adapters/skill_audit.py"], ["test_skill_audit.py"]),
    "domain/skill_audit": (["context/domain/skills/audit.py"], ["test_skill_audit.py"]),
    "domain/skill_ranking": (["context/domain/skills/ranking.py"], ["test_skill_routing.py"]),
    "domain/skill_admission": (["context/domain/skills/admission.py"], ["test_native_routing_replay.py"]),
    "adapters/project_detection": (["context/adapters/project_detection.py"], ["test_project_detection.py"]),
    "adapters/project_pipeline": (["context/adapters/project_pipeline.py"], ["test_pipeline.py"]),
    "domain/pipeline": (["context/domain/pipeline.py"], ["test_pipeline.py"]),
    "adapters/profile_scratch": (["context/adapters/profile_scratch.py"], ["test_profile_privacy.py"]),
    "application/rlm": (["context/application/rlm.py"], []),
    "adapters/knowledge": (["knowledge/adapters/postgres_knowledge.py"], []),
    "adapters/embeddings": (["knowledge/adapters/embeddings.py"], []),
    "adapters/seam_extraction": (["knowledge/adapters/seam_extraction.py"], ["test_seam_contracts.py"]),
    "domain/seams": (["knowledge/domain/seams.py"], ["test_seam_contracts.py", "test_seam_scope.py"]),
    "domain/seam_view": (["knowledge/domain/seam_view.py"], ["test_seam_view.py"]),
    "application/seam_ledger": (["knowledge/application/seam_ledger.py"], ["test_seam_contracts.py", "test_seam_view.py"]),
    "adapters/experience": (["knowledge/adapters/experience_import.py"], ["test_experience.py"]),
    "application/experience": (["knowledge/application/experience.py"], ["test_experience.py"]),
    "domain/experience": (["knowledge/domain/experience.py"], ["test_experience.py"]),
    "application/promotion": (["knowledge/application/promotion.py", "knowledge/domain/promotion.py"], []),
    "application/snapshot_imports": (["knowledge/application/snapshot_imports.py"], ["test_snapshot_integrity.py"]),
    "domain/snapshot_integrity": (["knowledge/domain/snapshot_integrity.py"], ["test_snapshot_integrity.py"]),
    "application/profile_flow": (["knowledge/application/profile_flow.py"], ["test_profile_privacy.py"]),
    "domain/profile_privacy": (["knowledge/domain/profile_privacy.py"], ["test_profile_privacy.py"]),
}
# Declared mapping correction (S2): the module consumes context's skill admission/ranking and skill
# frontmatter, which routing may not import (§2.4 DAG: routing -> kernel only); its contract moves with it.
S2_OWNER_CORRECTIONS = {"adapters/native_routing_replay": "context"}
S2_CONTRACT_OWNER_CORRECTIONS = {"INV-NATIVE-REPLAY-001": "context"}
# S2 rows whose remainder belongs to a later slice (the row stays `designed` with slice_progress).
S2_PARTIAL = {
    "adapters/skill_import": "S2 implemented context.adapters.skill_import:import_file (injected store/artifacts); "
                             "main() (argparse, PostgresStore(database_url()), FileArtifacts) -> entry/composition (S10)",
    "adapters/skill_audit": "S2 implemented context.adapters.skill_audit:render_text; main() -> entry/composition (S10)",
    "adapters/experience": "S2 implemented knowledge.adapters.experience_import (parse_lesson/import_lessons/"
                           "preview_lessons with the injected YAML loader); main() -> entry/composition (S10)",
}
# Public names that S2 implemented outside their M7 module's owner, with their target symbol.
S2_MOVED = {
    ("domain/model", "Agent"): ("routing", "codex_harness.routing.domain.organization:Agent"),
    ("domain/model", "Organization"): ("routing", "codex_harness.routing.domain.organization:Organization"),
    ("domain/model", "conductor_self_arbitration"): (
        "routing", "codex_harness.routing.domain.organization:conductor_self_arbitration"),
    ("domain/model", "ContextItem"): ("context", "codex_harness.context.domain.packet:ContextItem"),
    ("domain/model", "ContextPacket"): ("context", "codex_harness.context.domain.packet:ContextPacket"),
    ("domain/model", "compile_context"): ("context", "codex_harness.context.domain.packet:compile_context"),
    ("adapters/role_containers", "select_profile"): ("routing", "codex_harness.routing.domain.profiles:select_profile"),
    ("adapters/executor", "review_context"): ("context", "codex_harness.context.adapters.review_context:review_context"),
    ("adapters/executor", "artifact_reader_handle"): (
        "context", "codex_harness.context.domain.composition:artifact_reader_handle"),
    ("adapters/execution_output", "evidence_json"): ("context", "codex_harness.context.domain.composition:evidence_json"),
    ("domain/threshold_replay", "finite_number"): ("kernel", "codex_harness.kernel.numbers:finite_number"),
    ("bootstrap", "organization"): ("routing", "codex_harness.routing.adapters.organization_source:packaged_organization"),
    ("ports", "Knowledge"): ("knowledge", "codex_harness.knowledge.ports:CodeIndex+KnowledgeQuery"),
}
# Cross-slice module rows S2 touched: their remainder stays with the named owner slice.
S2_CROSS_PROGRESS = {
    "domain/model": "S2 implemented routing.domain.organization (Organization, Agent, conductor_self_arbitration) and "
                    "context.domain.packet (ContextItem, ContextPacket, compile_context); session_action -> "
                    "coordination (S5), Incident/hook_apply -> research (S8)",
    "adapters/executor": "S2 implemented the legacy (non-council) context composition of Executor._run as "
                         "context.application.compose.ContextComposer (+ context.domain.composition, "
                         "context.adapters.review_context): rendered input, retained context:<key> packet, "
                         "skill-history binding (compare:context.composition). Remaining: the execution record/"
                         "checkpoint/observation bindings of context_ref and the turn loop (S4, compare:"
                         "effects.context_packet), council delivery and correction-feedback composition (S8)",
    "adapters/role_containers": "S2 implemented routing.domain.profiles:select_profile (+IsolationError); "
                                "the rest -> execution/credentials (S3)",
    "adapters/execution_output": "S2 implemented context.domain.composition:evidence_json; the rest -> execution (S4)",
    "domain/threshold_replay": "S2 implemented kernel.numbers:finite_number (shared by context and research); "
                               "the rest -> research (S8)",
    "bootstrap": "S2 implemented routing.adapters.organization_source:packaged_organization; the composition "
                 "roots -> S10",
    "domain/autonomous": "S2 implemented knowledge.domain.promotion:PROMOTED_NAMESPACE (read by research); "
                         "the rest -> research (S8)",
    "adapters/runtime_thresholds": "context consumes it through context.ports.ThresholdPolicySource (S2); the "
                                   "implementation moves with research (S8); S2 tests use a packaged-definition stand-in",
}
S2_CONTRACTS = {
    "INV-MODEL-001": ["compare:routing.matrix", "target:tests/ported/test_model_routing.py"],
    "INV-NATIVE-REPLAY-001": ["target:tests/ported/test_native_routing_replay.py"],
    "INV-CONTEXT-001": ["compare:context.composition", "target:tests/test_s2_units.py"],
    "INV-PIPELINE-001": ["target:tests/ported/test_pipeline.py", "compare:context.composition"],
    "INV-PROJECT-001": ["target:tests/ported/test_project_skills.py", "target:tests/ported/test_project_detection.py"],
    "INV-SKILL-001": ["target:tests/ported/test_skill_routing.py", "target:tests/ported/test_skill_guidance.py",
                      "compare:context.composition"],
    "INV-SKILL-HISTORY-001": ["target:tests/ported/test_skill_history.py", "target:tests/ported/test_skill_audit.py",
                              "compare:context.composition"],
    "INV-SKILL-IMPORT-001": ["target:tests/ported/test_skill_import.py"],
    "INV-WORKER-PROFILE-001": ["compare:context.worker_profile_entry", "target:tests/ported/test_worker_profile.py",
                               "target:tests/ported/test_worker_profile_metadata.py"],
    "INV-EXPERIENCE-001": ["compare:knowledge.units", "target:tests/ported/test_experience.py"],
    "INV-GRAPH-001": ["compare:knowledge.units#code_graph"],
    "INV-PROFILE-001": ["compare:knowledge.units", "target:tests/ported/test_profile_privacy.py"],
    "INV-SEAM-001": ["compare:knowledge.units", "target:tests/ported/test_seam_contracts.py"],
    "INV-SEAM-SCOPE-001": ["target:tests/ported/test_seam_scope.py"],
    "INV-SEAM-VIEW-001": ["compare:knowledge.units", "target:tests/ported/test_seam_view.py"],
    "INV-SNAPSHOT-001": ["compare:knowledge.units", "target:tests/ported/test_snapshot_integrity.py"],
}
S2_RESOURCES = {"baldrix_pipeline/provenance.json": "compare:context.composition",
                "baldrix_pipeline/stages.core.yaml": "compare:context.composition",
                "baldrix_pipeline/stages.yaml": "target:tests/ported/test_pipeline.py",
                "organization.json": "compare:routing.matrix", "providers.json": "compare:routing.matrix",
                "worker-profile-v1.json": "compare:context.worker_profile_entry",
                "worker-profile-v1.md": "compare:context.worker_profile_entry"}
S2_OWNERS = {"routing", "context", "knowledge"}
S2_BUCKET_TEST = "target:tests/test_s2_units.py::test_context_and_knowledge_declare_their_owned_buckets"
S2_UNITS = {
    "atomic_unit:codex_harness.application.skill_history:SkillHistory.record#1": (
        "codex_harness.context.application.skill_history:SkillHistory.record (one Store.transaction(); the "
        "caller's lease guard runs inside it)",
        ["target:tests/ported/test_skill_history.py", "compare:context.composition"]),
    "atomic_unit:codex_harness.application.profile_flow:ProfileFlow.prepare_model_input#1": (
        "codex_harness.knowledge.application.profile_flow:ProfileFlow.prepare_model_input (one Store.transaction())",
        ["target:tests/ported/test_profile_privacy.py", "compare:knowledge.units"]),
}
S2_ENTRIES = {"codex_harness.adapters.worker_profile_metadata": "compare:context.worker_profile_entry",
              "codex_harness.resources.worker_profile_hook": "compare:context.worker_profile_entry#hook"}


def apply_s2(rows: list[dict]) -> None:
    """Move the S2 rows (routing/context/knowledge) to `implemented` with evidence; partial rows keep
    `designed` with `slice_progress` naming the owning slice of the remainder."""
    for r in rows:
        kind, key = r["kind"], r["key"]
        if kind == "module":
            mkey = module_key(key[len("module:"):]) or ""
            if mkey in S2_CROSS_PROGRESS:
                r["slice_progress"] = ((r["slice_progress"] + "; ") if r.get("slice_progress") else "") + \
                    S2_CROSS_PROGRESS[mkey]
            if mkey not in S2_TARGET_FILES:
                continue
            if mkey in S2_OWNER_CORRECTIONS:
                r["target_owner"] = S2_OWNER_CORRECTIONS[mkey]
                r["mapping_correction"] = "S2: routing -> context (§2.4: it consumes context skill admission)"
            files, ported = S2_TARGET_FILES[mkey]
            r["target_symbol"] = ["codex_harness." + f[:-3].replace("/", ".") for f in files]
            r["symbol_basis"] = "target (S2)"
            tests = S2_TESTS[r["target_owner"]] + [f"target:tests/ported/{n}" for n in ported] + [ARCH]
            if mkey in S2_PARTIAL:
                r["slice_progress"] = S2_PARTIAL[mkey]
                r["evidence"] = tests
            else:
                r["status"], r["evidence"] = "implemented", tests
        elif kind == "public_api":
            path, _, name = key[len("api:"):].partition("::")
            mkey = module_key(path) or ""
            if (mkey, name) in S2_MOVED:
                owner, symbol = S2_MOVED[(mkey, name)]
                r["target_owner"], r["target_symbol"], r["symbol_basis"] = owner, [symbol], "target (S2)"
                r["status"], r["evidence"] = "implemented", S2_TESTS.get(owner, S2_TESTS["context"])
                continue
            if mkey not in S2_TARGET_FILES:
                continue
            if mkey in S2_OWNER_CORRECTIONS:
                r["target_owner"] = S2_OWNER_CORRECTIONS[mkey]
            files, ported = S2_TARGET_FILES[mkey]
            found = _target_names(files).get(name)
            if found is not None:
                r["target_symbol"], r["status"], r["symbol_basis"] = [f"{found}:{name}"], "implemented", "target (S2)"
                r["evidence"] = S2_TESTS[r["target_owner"]] + [f"target:tests/ported/{n}" for n in ported]
            else:
                r["target_symbol"] = [f"codex_harness.entry.cli ({name}; S10)"]
                r["slice_progress"] = "not in the S2 target module: CLI entry work of S10"
        elif kind == "contract" and key[len("contract:"):] in S2_CONTRACTS:
            ident = key[len("contract:"):]
            if ident in S2_CONTRACT_OWNER_CORRECTIONS:
                r["target_owner"] = S2_CONTRACT_OWNER_CORRECTIONS[ident]
                r["target_symbol"] = [f"docs/contracts.md#{ident} enforced in codex_harness.{r['target_owner']}"]
                r["mapping_correction"] = "S2: owner follows the module (adapters/native_routing_replay -> context)"
            r["status"] = "implemented"
            r["evidence"] = S2_CONTRACTS[ident] + [e for e in r["evidence"] if not e.startswith("pending:")]
        elif kind == "resource" and key.split("resources/", 1)[-1] in S2_RESOURCES:
            r["status"] = "implemented"
            r["evidence"] = ["target:tests/test_s1_storage_units.py::test_packaged_resources_are_the_source_bytes",
                             S2_RESOURCES[key.split("resources/", 1)[-1]]]
        elif kind == "bucket" and r["target_owner"] in {"context", "knowledge"}:
            r["status"] = "implemented"
            r["evidence"] = [f"codex_harness.{r['target_owner']}.ports.OWNED_BUCKETS", S2_BUCKET_TEST]
        elif kind == "capability" and key in {"capability:role_provider_routing", "capability:bounded_context_knowledge"}:
            r["status"] = "implemented"
            r["evidence"] = ["docs/context/ARCHITECTURE.md#capabilities"] + S2_TESTS[r["target_owner"]]
        elif kind == "atomic_unit" and key in S2_UNITS:
            symbol, evidence = S2_UNITS[key]
            r["status"], r["target_symbol"], r["evidence"] = "implemented", [symbol], evidence
            r["trace"] = "static depth 1; unit tested by the ported suites (memory and disposable PostgreSQL)"
        elif kind == "module_entry" and key in {"module_entry:codex_harness.adapters.skill_import",
                                                 "module_entry:codex_harness.adapters.skill_audit",
                                                 "module_entry:codex_harness.adapters.experience"}:
            r["slice_progress"] = "S2 implemented the injected-store functions; the -m entry form (main) -> S10"
        elif kind == "module_entry" and key[len("module_entry:"):] in S2_ENTRIES:
            r["status"] = "implemented"
            r["evidence"] = [S2_ENTRIES[key[len("module_entry:"):]], "target:tests/test_s2_units.py"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def module_key(path: str) -> str | None:
    if path.startswith("src/codex_harness/"):
        return path[len("src/codex_harness/"):-3]
    return None


REVERSE = {k: ctx for ctx, keys in MAP.items() for k in keys.split()}


def module_context(path: str) -> str | None:
    if path.startswith("frontend/"):
        return "observation"
    if path.startswith(("scripts/aibox_data", "deploy/")):
        return "delivery"
    if path.startswith("src/zeus"):
        return "entry"
    return REVERSE.get(module_key(path) or "")


def module_symbols(path: str, ctx: str) -> tuple[list[str], str]:
    key = module_key(path)
    if key in SYMBOLS:
        return SYMBOLS[key], "design §3.1/§3.5"
    if path.startswith("frontend/"):
        return [f"frontend/{path.split('/', 1)[1]} (unchanged bytes; built assets packaged as target resources)"], \
            "design §3.1"
    if path.startswith("deploy/aibox") or path.startswith("scripts/aibox_data"):
        return [f"target/{path} (S7 delivery tooling; invocation form kept)"], "design §3.1"
    if path.startswith("src/zeus"):
        return ["target/src/zeus (compatibility entry shim)"], "design §3.5"
    layer, _, name = key.partition("/")
    if not name:
        return [f"codex_harness.{ctx}.{layer}"], "rule"
    if ctx in {"entry"}:
        return [f"codex_harness.entry.cli.{name.removesuffix('_cli')}"], "rule"
    if ctx == "kernel":
        return [f"codex_harness.kernel.{name}"], "rule"
    target_layer = {"domain": "domain", "application": "application", "adapters": "adapters",
                    "resources": "resources"}[layer]
    return [f"codex_harness.{ctx}.{target_layer}.{name}"], "rule"


def row(key, kind, owner, symbols, *, intent="preserve", evidence=(), trace="", basis="", **extra):
    out = {"key": key, "kind": kind, "target_owner": owner, "target_symbol": list(symbols),
           "symbol_basis": basis or "design", "intent": intent, "evidence": list(evidence),
           "status": "designed" if owner and symbols else "unmapped", "trace": trace,
           "untraced": "untraced" in trace}
    out.update(extra)
    return out


def contract_tests(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted((root / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for ident in set(__import__("re").findall(r"INV-[A-Z0-9-]+-\d{3}", text)):
            found.setdefault(ident, []).append(path.relative_to(root).as_posix())
    return found


def build(ledger: dict, static: dict) -> dict:
    rows = []
    owner_by_module = {}
    for m in ledger["modules"]:
        ctx = module_context(m["path"])
        symbols, basis = module_symbols(m["path"], ctx) if ctx else ([], "")
        owner_by_module[m["module"]] = ctx
        tests = [t if isinstance(t, str) else t.get("path", "") for t in m["tests"]]
        evidence = [f"reference:{t}" for t in tests[:6]] + ([f"reference:+{len(tests) - 6} more test files"]
                                                             if len(tests) > 6 else [])
        if not evidence:
            evidence = [f"pending: characterization before the {UNTRACED_SLICE.get(ctx, '?')} move (R-U)"]
        rows.append(row(f"module:{m['path']}", "module", ctx, symbols, basis=basis,
                        intent=INTENT.get(module_key(m["path"]) or "", "preserve"), evidence=evidence,
                        trace=m["status"], layer=m["layer"], slice=UNTRACED_SLICE.get(ctx)))
    contract_owner = {f"INV-{cid}": ctx for ctx, ids in CONTRACT_OWNERS.items() for cid in ids.split()}
    by_test = contract_tests(ROOT)
    for c in ledger["contracts"]:
        ctx = contract_owner.get(c["id"])
        tests = by_test.get(c["id"], [])
        evidence = [f"reference:{t}" for t in tests[:6]] + ([f"reference:+{len(tests) - 6} more"]
                                                             if len(tests) > 6 else [])
        evidence += ["pending: target characterization test named in the feature-map row (R-U)"]
        rows.append(row(f"contract:{c['id']}", "contract", ctx,
                        [f"docs/contracts.md#{c['id']} enforced in codex_harness.{ctx}"] if ctx else [],
                        basis="design §1.3", evidence=evidence, trace=c["status"]))
    for node in ledger["entrypoints"]["cli"]:
        parts = node["command"].split()[1:]
        rows.append(row(f"cli:{node['command']}", "cli_node", "entry",
                        [f"codex_harness.entry.cli.{parts[0].replace('-', '_')}"
                         + (":" + " ".join(parts[1:]) if parts[1:] else "")],
                        basis="design §3.1 entry/cli (one module per root)",
                        evidence=[f"compare:cli.parser#{node['command']}"], trace=node["status"],
                        root=len(parts) == 1, current_adapter=node.get("adapter")))
    for name, target in sorted(ledger["entrypoints"]["scripts"].items()):
        rows.append(row(f"script:{name}", "console_script", "entry",
                        [f"{target} (permanent shim -> codex_harness.entry)"], basis="design §3.5",
                        evidence=[f"compare:entries.safe_matrix#console.{name} --help"],
                        trace="listed; --help characterized in S0"))
    for e in ledger["entrypoints"]["module_entries"]:
        path = e["path"]
        ctx = module_context(path)
        rows.append(row(f"module_entry:{e['module']}", "module_entry", ctx,
                        [f"{e['module']} (entry form kept; §3.5)"], basis="design §3.5/§5.2a",
                        evidence=["compare:entries.safe_matrix", "compare:static.source#shims"],
                        trace="listed; safe form characterized in S0" if e["has_main_guard"] else "listed",
                        main_guard=e["has_main_guard"]))
    for h in ledger["entrypoints"]["http"]:
        desk = "frontdesk_http" in h["provenance"]["path"]
        rows.append(row(f"http:{h['method']} {h['route']}", "http_route", "intake" if desk else "observation",
                        ["codex_harness.entry.http.desk" if desk
                         else "codex_harness.observation.adapters.viewer_http.ViewerHandler"],
                        basis="design §1.2/§3.1",
                        evidence=["pending: S9 viewer GET/404/403/405 and desk refusal scenarios"
                                  if not desk else "pending: S8 desk Origin/Host/body-bound scenarios"],
                        trace=h["status"], boundary=h["boundary"]))
    for r in ledger["resources"]:
        loaders = [ld["provenance"]["path"] for ld in r["loaders"]]
        ctx = next((module_context(p) for p in loaders if module_context(p)), None) or "kernel"
        rows.append(row(f"resource:{r['path']}", "resource", ctx,
                        [f"target/{r['path']} (unchanged bytes)"], basis="design §3.1 resources",
                        evidence=["pending: resource byte-equality check in the owning slice"],
                        trace=r["status"], loader_basis="loader module" if loaders else "no loader listed"))
    for cap in ledger["capabilities"]:
        ctx = CAPABILITY_OWNERS[cap["name"]]
        rows.append(row(f"capability:{cap['name']}", "capability", ctx, [f"codex_harness.{ctx}"],
                        basis="design §1.2", evidence=["docs/context/ARCHITECTURE.md#capabilities"],
                        trace=cap["status"]))
    static_names = set(static["bucket_candidates"]["names"])
    for b in ledger["state"]["logical_buckets"]:
        writers = sorted({a["module"] for a in b["accesses"] if a["operation"] == "put"})
        owners = sorted({owner_by_module.get(w) for w in writers if owner_by_module.get(w)})
        ctx = BUCKET_OWNERS.get(b["name"]) or (owners[0] if len(owners) == 1 else None)
        if ctx is None and not writers:
            readers = sorted({owner_by_module.get(a["module"]) for a in b["accesses"]
                              if owner_by_module.get(a["module"])})
            ctx = readers[0] if len(readers) == 1 else None
        rows.append(row(f"bucket:{b['name']}", "bucket", ctx,
                        [f"codex_harness.{ctx}.ports.OWNED_BUCKETS"] if ctx else [],
                        basis="design §2.7" if b["name"] in BUCKET_OWNERS else "single writer context",
                        evidence=["compare:static.source#bucket_candidates"
                                  if b["name"] in static_names else "ledger only (not a tx literal access)"],
                        trace=b["status"], candidate=True, writer_contexts=owners))
    for i, f in enumerate(ledger["flows"]):
        rows.append(row(f"flow:{f['name']}", "flow", FLOW_OWNERS[i], ["REBUILD-DESIGN-v2 §1.4 target column"],
                        basis="design §1.4",
                        evidence=[f"compare:{e}" for e in FLOW_EVIDENCE[i]]
                        + ["pending: flow scenarios in the owning slices"],
                        trace="traced boundaries; untraced tail"))
    for api in ledger["public_api_interfaces"]:
        path = api["provenance"]["path"]
        ctx = module_context(path)
        symbols, basis = module_symbols(path, ctx) if ctx else ([], "")
        rows.append(row(f"api:{path}::{api['name']}", "public_api", ctx,
                        [f"{s}:{api['name']}" for s in symbols[:1]], basis=basis or "rule",
                        evidence=[f"module:{path}"], trace=api["status"]))
    unit_rows = []
    for u in static["transaction_blocks"]["units"]:
        writes = [w for w in u["literal_writes"] if w != "<dynamic>"]
        contexts = sorted({BUCKET_OWNERS.get(w) or next(
            (r["target_owner"] for r in rows if r["key"] == f"bucket:{w}"), None) or "?" for w in writes})
        module_ctx = owner_by_module.get(u["module"])
        cross = len(contexts) > 1 or (len(contexts) == 1 and contexts[0] != module_ctx) or bool(
            u["tx_passing_calls"])
        if not cross:
            continue
        confirmed = u["key"] == "codex_harness.adapters.executor:Executor._commit_decision#1"
        unit_rows.append(row(f"atomic_unit:{u['key']}", "atomic_unit", module_ctx,
                             [f"one Store.transaction() opened by the owning use case in codex_harness."
                              f"{module_ctx}; owner operations take tx (§2.9)"],
                             basis="design §2.9 rule 2",
                             evidence=(["compare:effects.decision_unit", "compare:effects.decision_unit.pg"]
                                       if confirmed else
                                       [f"static:compare/goldens/reference/static.source.json#{u['key']}",
                                        "pending: recorder confirmation in the owning slice"]),
                             trace=("recorder-confirmed on MemoryStore and on a disposable PostgreSQL "
                                    "(M7 PostgresStore)" if confirmed else "static depth 1; callee writes untraced"),
                             bucket_owners=contexts, fences=u["fence_calls"],
                             tx_passing_calls=u["tx_passing_calls"]))
    rows += unit_rows
    apply_s1(rows)
    apply_s2(rows)
    counts = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    keys = sorted(r["key"] for r in rows if r["kind"] != "atomic_unit")
    return {
        "schema": "zeus:rebuild-ledger-coverage:1",
        "ledger_sha256": LEDGER_SHA256,
        "source_commit": ledger["revision"],
        "statuses": list(STATUSES),
        "intents": ["preserve", "change:<§4 row>", "retire:<U-id>"],
        "counts": counts,
        "extra_counts": {
            "cli_roots": sum(1 for r in rows if r["kind"] == "cli_node" and r["root"]),
            "main_guards": sum(1 for r in rows if r["kind"] == "module_entry" and r["main_guard"]),
            "untraced": sum(1 for r in rows if r["untraced"]),
            "static_bucket_scan": {"names": len(static_names),
                                   "ledger_only": sorted({b["name"] for b in ledger["state"]["logical_buckets"]}
                                                         - static_names),
                                   "scan_only": sorted(static_names - {b["name"] for b in
                                                                        ledger["state"]["logical_buckets"]})},
        },
        "ledger_key_digest": hashlib.sha256("\n".join(keys).encode()).hexdigest(),
        "adapters": [],
        "adapters_note": "Temporary compatibility adapters (purpose, direction, owning slice, removal "
                         "condition). None is planned; permanent entry shims are listed in §3.5 rows.",
        "rows": rows,
    }


# Since S3 (0a8737cc, 2026-09-30) the slice integrations maintain these row fields in place, through their recorded
# edit scripts, and append `addition` rows (no SOURCE counterpart; OBSERVABILITY-COVERAGE-20261002). The generator owns
# everything else: the SOURCE-derived skeleton of row keys, kinds, layers, traces and every other field. `--check`
# therefore compares skeletons, and writing a fresh table over a maintained one is refused (it would discard every
# integration edit). SKIPPED-TEST-CLOSURE-20261004 B (`test_table_regenerates_from_the_pinned_ledger`).
# Since S11 L the statuses are `coverage/relabel.py`'s output (DESIGN-s11 §5): it also owns `verification`, the
# per-row record of the unmet conditions (or the passing items) at the evidence head of `coverage/run-evidence.json`.
MAINTAINED_FIELDS = frozenset({"evidence", "mapping_correction", "slice", "slice_progress", "status", "symbol_basis",
                               "target_owner", "target_symbol", "verification", "writer_contexts"})
ADDITION = "addition"
ADDITION_INTENT = "addition:<authority>"


def skeleton(table: dict) -> dict:
    """The generator-owned part of a coverage table: no maintained field, no addition row, count or intent."""
    top = {k: v for k, v in table.items() if k not in {"rows", "counts", "intents", "ledger_key_digest"}}
    return {**top, "counts": {k: v for k, v in table["counts"].items() if k != ADDITION},
            "intents": [i for i in table["intents"] if i != ADDITION_INTENT],
            "rows": [{k: v for k, v in r.items() if k not in MAINTAINED_FIELDS}
                     for r in table["rows"] if r["kind"] != ADDITION]}


def dump(document: dict) -> str:
    head = {k: v for k, v in document.items() if k != "rows"}
    lines = json.dumps(head, indent=1, ensure_ascii=False, sort_keys=True)[:-2]
    body = ",\n".join("  " + json.dumps(r, ensure_ascii=False, sort_keys=True) for r in document["rows"])
    return lines + ',\n "rows": [\n' + body + "\n ]\n}\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if sha256_file(args.ledger) != LEDGER_SHA256:
        print("ledger sha256 differs from the pinned ledger", file=sys.stderr)
        return 1
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    static = json.loads((ROOT / "compare/goldens/reference/static.source.json").read_text(encoding="utf-8"))
    text = dump(build(ledger, static))
    current = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    if args.check:
        same = current is not None and skeleton(current) == skeleton(json.loads(text))
        print(json.dumps({"coverage_matches_generated": same, "compared": "skeleton",
                          "maintained_fields": sorted(MAINTAINED_FIELDS),
                          "addition_rows": sum(r["kind"] == ADDITION for r in (current or {}).get("rows", []))}))
        return 0 if same else 1
    if current is not None and OUT.read_text(encoding="utf-8") != text:
        print("refused: coverage/ledger-coverage.json is integration-maintained since S3; regenerating it would discard"
              " every integration edit (use --check)", file=sys.stderr)
        return 1
    OUT.write_text(text, encoding="utf-8")
    print(json.dumps({"written": str(OUT.relative_to(ROOT)), "bytes": len(text.encode())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
