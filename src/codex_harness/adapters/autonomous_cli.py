"""`zeus autonomous run|status`: thin wiring of the real services around AutonomousRun (INV-AUTONOMOUS-001).

Same host identity, goal binding, execution policy and `knowledge=False` executor as `operate run`;
source verification reuses the dge Git verifier. Status reads the store only.
"""
from __future__ import annotations

from pathlib import Path

from codex_harness.adapters.autonomous_evidence import ExecutionEvidence
from codex_harness.adapters.dge_cli import read_document, repository_identity, verify_sources
from codex_harness.adapters.operation_cli import (
    GitSource,
    bind_goal,
    execution_policy,
    identity,
    refusal,
)
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.autonomous import AutonomousRun
from codex_harness.application.council import CouncilRun
from codex_harness.domain.council import profile, validate_any_manifest


def run(service, args) -> dict:
    from codex_harness.adapters.bus import RedisBus
    from codex_harness.adapters.call_budget import CallBudget
    from codex_harness.adapters.configuration import repository_root, runtime_dir, settings
    from codex_harness.adapters.council_snapshot import ReadOnlySnapshot
    from codex_harness.adapters.project_evidence import load_profile
    from codex_harness.application.workflow import Workflow
    from codex_harness.bootstrap import (
        build_collector,
        build_executor,
        build_observer,
        database_url,
        host_isolation,
        redis_url,
    )

    # v1 and v2 each keep their own validator; an unsupported schema is refused before any provider or DB access.
    manifest = validate_any_manifest(read_document(args.file, "Autonomous manifest"), packaged_policy())
    host = settings()
    policy = execution_policy(manifest, host)
    repository = repository_root()
    source = GitSource(repository)
    goal = bind_goal(manifest, source)
    # INV-PROJECT-EVIDENCE-001 / INV-ISOLATED-WORKER-001: this entry point composes an operation, so it
    # loads the profile and the isolation selection in the same order, and binds both into the identity.
    evidence_profile = load_profile(host)
    isolated = host_isolation(evidence_profile)
    bound = identity(manifest, repository, policy, host, runtime_dir(), evidence_profile,
                     **({} if isolated is None else {"isolation": isolated.config}))
    observer = build_observer(service.store, "cli.autonomous")
    try:
        executor = build_executor(service, observer=observer, execution_policy=policy, knowledge=False,
                                  evidence_profile=evidence_profile,
                                  **({} if isolated is None else {"isolation": isolated}))
        # The evidence port reads the very artifact store the executor persists execution results to.
        wiring = dict(verify_sources=lambda packet: verify_sources(packet, source), repository=repository_identity(repository),
                      observer=observer, evidence=ExecutionEvidence(executor.artifacts))
        # SPEC "Real council progress: isolated delivery": ONE run-scoped bus for every publisher and
        # consumer of this run (outbox relay, role drains, the Operation), derived from the manifest id,
        # so concurrent runs never compete for a role queue and a restart derives the same streams.
        common = (service, executor, RedisBus.for_run(redis_url(), manifest["id"]), Workflow(service.store, service.org), CallBudget(),
                  build_collector(service.store, observer))
        if profile(manifest)["version"] == 2:
            # INV-COUNCIL-001: the snapshot port is a separate read-only connection to the same database
            # (never Store.transaction); the envelope is persisted through the executor's artifact store.
            cycle = CouncilRun(*common, **wiring, snapshot=ReadOnlySnapshot(database_url()), artifacts=executor.artifacts)
        else:
            cycle = AutonomousRun(*common, **wiring)
        return cycle.run(manifest, bound, goal)
    finally:
        observer.close()


def status(service, args) -> dict:
    return {**AutonomousRun(service).status(args.run_id), "exit_code": 0}


def add_parser(commands) -> None:
    auto = commands.add_parser("autonomous", help="Research, immutable packet, independent debate, Operation v2, atomic promotion")
    sub = auto.add_subparsers(dest="autonomous_command", required=True)
    run_parser = sub.add_parser("run", help="Claim the manifest id and run the full cycle to a terminal receipt "
                                            "(urn:zeus:autonomous:1, or urn:zeus:autonomous:2 for the DBA/two-lead council)")
    run_parser.add_argument("--file", type=Path, required=True)
    show = sub.add_parser("status", help="Safe read-only receipt; store read only")
    show.add_argument("run_id")


def execute(service, args) -> dict:
    try:
        return run(service, args) if args.autonomous_command == "run" else status(service, args)
    except Exception as exc:
        return refusal(exc)
