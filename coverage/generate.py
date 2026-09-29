"""Generate `coverage/ledger-coverage.json`, the one old/new coverage table (REBUILD-DESIGN-v2 §1.5).

Layer: harness (never shipped); standard library only.

    python coverage/generate.py --ledger <FLEET-REBUILD-LEDGER.json>            # write
    python coverage/generate.py --ledger <FLEET-REBUILD-LEDGER.json> --check    # compare only

Row identities are frozen from the ledger (sha256 pinned below). The context of each module row is
the accepted design mapping (`scratch/rebuild-design/map.py`, reproduced literally in MAP, with the
two declared v2 corrections: `platform` is named `host_os`, and `adapters/contracts.py` moves to
`storage.adapters.message_schema` + `observation.adapters.observation_schema`). Target symbols are
PROPOSED: the §3.1 tree where it names one, else `codex_harness.<context>.<layer>.<module>`. S0
assigns `designed` or `unmapped` only; no row is `implemented`/`verified` before its slice.
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
FLOW_EVIDENCE = [["effects.decision_unit"], [], [], [], []]
UNTRACED_SLICE = {"kernel": "S1", "storage": "S1", "host_os": "S1", "routing": "S2", "context": "S2",
                  "knowledge": "S2", "credentials": "S3", "execution": "S3/S4", "coordination": "S5/S6",
                  "delivery": "S7", "review": "S8", "research": "S8", "intake": "S8", "evidence": "S8",
                  "observation": "S9", "composition": "S10", "entry": "S10"}


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
                             evidence=(["compare:effects.decision_unit"] if confirmed else
                                       [f"static:compare/goldens/reference/static.source.json#{u['key']}",
                                        "pending: recorder confirmation in the owning slice"]),
                             trace=("recorder-confirmed on MemoryStore; disposable PostgreSQL pending"
                                    if confirmed else "static depth 1; callee writes untraced"),
                             bucket_owners=contexts, fences=u["fence_calls"],
                             tx_passing_calls=u["tx_passing_calls"]))
    rows += unit_rows
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
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print(json.dumps({"coverage_matches_generated": same}))
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(json.dumps({"written": str(OUT.relative_to(ROOT)), "bytes": len(text.encode())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
