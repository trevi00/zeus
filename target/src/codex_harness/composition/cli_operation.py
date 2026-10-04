"""The `zeus operate` and `zeus autonomous` composition: the policy, identity and session owner of an operation, and the builders of its adapters.

Layer: composition
Owns: packaged_policy, execution_policy, identity, session_owner, operation, run_bus, call_budget, execution_evidence, read_only_snapshot, autonomous_run, council_run
Does not own: the argument shape and the command bodies (entry.cli.operate, entry.cli.autonomous), the helpers shared by the roots (entry.cli.operation) and the use cases (coordination.application)
Entry points: packaged_policy, execution_policy, identity, session_owner, operation, run_bus, call_budget, execution_evidence, read_only_snapshot, autonomous_run, council_run
Contracts: INV-OPERATION-001, INV-AUTONOMOUS-001, INV-COUNCIL-001, INV-PROJECT-EVIDENCE-001, INV-ISOLATED-WORKER-001, INV-CONTINUATION-001, INV-WORKER-SESSION-001

Moved from M7 `adapters/operation_cli.py` (SOURCE e38aa722) by named rule R-c24 (S10 unit C6a): `execution_policy` (:81-89), `identity` (:92-111) and `session_owner` (:114-128) are M7's bodies
with the target homes (`routing.adapters.provider_policy`, `routing.domain.providers`, `coordination.domain.operation`, `intake.domain.operation_manifest`, `kernel`, `composition.cli_sessions`); they sit here because
they need adapters an entry module may not import. The other functions build what M7 constructed inline in `operation_cli.run` and `autonomous_cli.run`: `operation` is `Operation(service, ...)` as
`tests/ported/m7_research.Operation` wires it (the S5 class takes the store, the organization, the outbox flusher, the incident use case, the design gate and the evidence records), `run_bus` is
`RedisBus.for_run(redis_url(), manifest["id"])` (the target bus takes its namespace from the setting M7's read itself), `call_budget` is `CallBudget()`, `execution_evidence` is `ExecutionEvidence(executor.artifacts)`,
`read_only_snapshot` is `ReadOnlySnapshot(database_url())` and `autonomous_run` / `council_run` are `AutonomousRun` / `CouncilRun` with the ports of `tests/ported/m7_research` (sessions factory, evidence records,
knowledge promotion and the operation factory). `packaged_policy` re-exports the routing adapter for the entry modules. Imports sit inside the functions, so importing this module stays light.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


def packaged_policy():
    """The packaged provider policy (an entry module may not import the routing adapter)."""
    from codex_harness.routing.adapters import provider_policy
    return provider_policy.packaged_policy()


def execution_policy(manifest: dict, host_settings: dict):
    """The packaged policy with the fixed worker profile and restricted surface, enabled for this
    operation's controls; executable, credentials and endpoints stay host settings."""
    from codex_harness.coordination.domain.operation import RESTRICTED, WORKER_PROFILE
    from codex_harness.intake.domain.operation_manifest import provider_settings
    from codex_harness.routing.adapters.provider_policy import ExecutionPolicy
    from codex_harness.routing.domain.providers import parse_configuration
    policy = packaged_policy()
    claude = policy.provider("claude")
    runtime = {**claude.runtime, "worker_profile": WORKER_PROFILE, "restricted": RESTRICTED}
    policy = replace(policy, providers={**policy.providers, "claude": replace(claude, runtime=runtime)})
    merged = {**host_settings, **provider_settings(manifest)}
    return ExecutionPolicy(policy, parse_configuration(policy, merged))


def identity(manifest: dict, repository, policy, host_settings: dict, runtime,
             evidence_profile: dict | None = None, isolation: dict | None = None) -> dict:
    """Effective repository, resolved runtime directory, packaged policy, provider policy/config and
    endpoint digests; a same-id run under any other of these is refused before any call. With a host
    project evidence profile its digest is bound too (INV-PROJECT-EVIDENCE-001), so a same-id replay
    cannot change its verification context; without one the identity keeps its exact old shape.
    A host-selected isolation (INV-ISOLATED-WORKER-001) binds its mode, image and limits the same way."""
    from codex_harness.coordination.application.operation import identity_digest
    from codex_harness.coordination.domain.operation import RESTRICTED, WORKER_PROFILE
    from codex_harness.kernel.ids import digest
    from codex_harness.kernel.policy import POLICY
    summary = policy.summary()
    profiled = {} if evidence_profile is None else {"evidence_profile": evidence_profile["profile_digest"]}
    if isolation is not None:
        profiled["isolation"] = {"mode": isolation["mode"], "image": isolation["image"],
                                 "limits": isolation["limits"], "digest": isolation["digest"]}
    return {**profiled, "repository": digest(str(Path(repository).resolve())),
            "runtime": digest(str(Path(runtime).resolve())),
            "runtime_policy": digest(POLICY.snapshot()),
            "provider": {"policy_digest": summary["policy_digest"], "config_digest": summary["config_digest"],
                         "worker_profile": WORKER_PROFILE, "restricted": RESTRICTED},
            "endpoints": identity_digest({"database": host_settings.get("HARNESS_DATABASE_URL", ""),
                                          "redis": host_settings.get("HARNESS_REDIS_URL", ""),
                                          "namespace": host_settings.get("HARNESS_REDIS_NAMESPACE", "")})}


def session_owner(service, operation_id: str, observer=None) -> dict:
    """INV-CONTINUATION-001 / INV-WORKER-SESSION-001: the `worker_sessions` keyword for the executor
    when, and only when, the lane store holds the opt-in controller's binding naming a task session
    for this operation. Everything else keeps the exact legacy fresh path (an empty keyword set)."""
    from codex_harness.composition import cli_sessions
    from codex_harness.coordination.domain.continuation import validate_binding

    with service.store.transaction() as tx:
        binding = tx.get("continuation_bindings", operation_id)
    if binding is None or validate_binding(binding)["session"] is None:
        return {}
    from codex_harness.execution.application.worker_sessions import WorkerSessions

    return {"worker_sessions": WorkerSessions(service.store, cli_sessions.session_archives(),
                                              evidence=cli_sessions.evidence_store(), observer=observer)}


def _service(service):
    """What the use cases read of M7's `Harness`: the store, the organization, the outbox flusher and `record_incident`."""
    from codex_harness.composition import cli_bus, cli_cycle
    return SimpleNamespace(store=service.store, org=service.org, flusher=cli_bus.flusher(service),
                           record_incident=cli_cycle.incident_recorder(service))


def operation(service, executor=None, bus=None, workflow=None, budget=None, collector=None, observer=None):
    """`Operation(service, executor, bus, workflow, budget, collector, observer=)`; with the service alone it is the store-read `status` owner."""
    from codex_harness.coordination.application.operation import Operation
    from codex_harness.evidence.application.inspections import EvidenceRecords
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.research.application import dge
    handle = _service(service)
    return Operation(handle.store, handle.org, flusher=handle.flusher, incidents=handle.record_incident,
                     executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                     observer=observer, design_gate=SimpleNamespace(check=dge.design_gate),
                     evidence_records=EvidenceRecords(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def run_bus(run_id: str):
    """The bus of ONE run: the configured namespace scoped by the run id (`RedisBus.for_run`)."""
    from codex_harness.composition import redis_url
    from codex_harness.composition.configuration import settings
    from codex_harness.storage.adapters.redis_bus import RedisBus
    return RedisBus.for_run(redis_url(), run_id, settings().get("HARNESS_REDIS_NAMESPACE", "codex-harness"))


def call_budget():
    from codex_harness.execution.adapters.call_budget import CallBudget
    return CallBudget()


def execution_evidence(artifacts):
    """The evidence port over the very artifact store the executor persists execution results to."""
    from codex_harness.research.adapters.autonomous_evidence import ExecutionEvidence
    return ExecutionEvidence(artifacts)


def read_only_snapshot():
    """INV-COUNCIL-001: a separate read-only connection to the same database (never `Store.transaction`)."""
    from codex_harness.composition import database_url
    from codex_harness.research.adapters.council_snapshot import ReadOnlySnapshot
    return ReadOnlySnapshot(database_url())


def _research_ports(service) -> dict:
    """The ports `tests/ported/m7_research.AutonomousRun` and `CouncilRun` hand the S8 use cases (R-a1, R-a3)."""
    from codex_harness.coordination.application.operation import Operation
    from codex_harness.evidence.application.inspections import EvidenceRecords
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.knowledge.application import promotion
    from codex_harness.research.application import dge

    def operation_factory(executor, bus, workflow, budget, collector, observer=None):
        return Operation(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                         executor=executor, bus=bus, workflow=workflow, budget=budget, collector=collector,
                         observer=observer, design_gate=SimpleNamespace(check=dge.design_gate),
                         evidence_records=EvidenceRecords(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
    return {"sessions_factory": dge.DebateSessions, "evidence_records": EvidenceRecords(), "promotion": promotion,
            "operation_factory": operation_factory}


def autonomous_run(service, executor=None, bus=None, workflow=None, budget=None, collector=None, **wiring):
    """`AutonomousRun(service, ...)`; with the service alone it is the store-read `status` owner."""
    from codex_harness.coordination.application.autonomous import AutonomousRun
    handle = _service(service)
    return AutonomousRun(handle, executor, bus, workflow, budget, collector, **_research_ports(handle), **wiring)


def council_run(service, executor=None, bus=None, workflow=None, budget=None, collector=None, **wiring):
    """INV-COUNCIL-001: `CouncilRun(service, ..., snapshot=, artifacts=)`."""
    from codex_harness.coordination.application.council import CouncilRun
    handle = _service(service)
    return CouncilRun(handle, executor, bus, workflow, budget, collector, **_research_ports(handle), **wiring)
