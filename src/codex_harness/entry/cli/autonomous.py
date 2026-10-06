"""The `zeus autonomous` argument parser (M7 adapters/autonomous_cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus autonomous`), run (its body: M7 autonomous_command) and the private _run, _status and _execute (M7 autonomous_cli)
Does not own: dispatch (entry.cli main), the shared helpers (entry.cli.operation, the repository identity and source verification of entry.cli.dge) and composition (composition.cli_operation, composition.operation, composition.observation)
Entry points: add_parser, run
Contracts: INV-AUTONOMOUS-001, INV-COUNCIL-001, INV-PROJECT-EVIDENCE-001, INV-ISOLATED-WORKER-001

Moved from M7 adapters/autonomous_cli.py:82-89 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `autonomous_command` (:578-585) and `_run`, `_status` and `_execute` are `adapters/autonomous_cli.py` `run` (:25-75), `status` (:78-79) and `execute` (:92-96) (R-c24, S10 unit C6a): the bodies are M7's
verbatim except that the service is built first (as M7 `main()` did), `read_document` and `refusal` are `entry.cli.operation`, `repository_identity` is the private `_repository_identity` of
`entry.cli.dge`, `verify_sources` is `composition.cli_research.verify_sources` (S11 XC-9 DUP-1), the policy, identity, bus, budget, evidence, snapshot and the two use cases are builders of `composition.cli_operation` (they need adapters), `load_profile(host)` is
`composition.operation.host_evidence_profile()` and `GitSource` is `composition.cli_research.git_source`.
"""

from pathlib import Path


def add_parser(commands) -> None:
    auto = commands.add_parser("autonomous", help="Research, immutable packet, independent debate, Operation v2, atomic promotion")
    sub = auto.add_subparsers(dest="autonomous_command", required=True)
    run_parser = sub.add_parser("run", help="Claim the manifest id and run the full cycle to a terminal receipt "
                                            "(urn:zeus:autonomous:1, or urn:zeus:autonomous:2 for the DBA/two-lead council)")
    run_parser.add_argument("--file", type=Path, required=True)
    show = sub.add_parser("status", help="Safe read-only receipt; store read only")
    show.add_argument("run_id")


def run(args) -> None:
    """INV-AUTONOMOUS-001: exit 0 only for an accepted (or cached accepted) receipt; refusals print a
    code and a type, never manifests, packets, payloads, DSNs or raw exceptions."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    result = _execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _run(service, args) -> dict:
    from codex_harness.composition import cli, cli_operation, cli_research
    from codex_harness.composition.configuration import repository_root, runtime_dir, settings
    from codex_harness.composition.observation import build_collector, build_observer
    from codex_harness.composition.operation import build_executor, host_evidence_profile, host_isolation
    from codex_harness.entry.cli.dge import _repository_identity
    from codex_harness.entry.cli.operation import bind_goal, read_document
    from codex_harness.research.domain.council import profile, validate_any_manifest

    # v1 and v2 each keep their own validator; an unsupported schema is refused before any provider or DB access.
    manifest = validate_any_manifest(read_document(args.file, "Autonomous manifest"), cli_operation.packaged_policy())
    host = settings()
    policy = cli_operation.execution_policy(manifest, host)
    repository = repository_root()
    source = cli_research.git_source(repository)
    goal = bind_goal(manifest, source)
    # INV-PROJECT-EVIDENCE-001 / INV-ISOLATED-WORKER-001: this entry point composes an operation, so it
    # loads the profile and the isolation selection in the same order, and binds both into the identity.
    evidence_profile = host_evidence_profile()
    isolated = host_isolation(evidence_profile)
    bound = cli_operation.identity(manifest, repository, policy, host, runtime_dir(), evidence_profile,
                                   **({} if isolated is None else {"isolation": isolated.config}))
    observer = build_observer(service.store, "cli.autonomous")
    try:
        executor = build_executor(service, observer=observer, execution_policy=policy, knowledge=False,
                                  evidence_profile=evidence_profile,
                                  **({} if isolated is None else {"isolation": isolated}))
        # The evidence port reads the very artifact store the executor persists execution results to.
        wiring = dict(verify_sources=lambda packet: cli_research.verify_sources(packet, source), repository=_repository_identity(repository),
                      observer=observer, evidence=cli_operation.execution_evidence(executor.artifacts))
        # SPEC "Real council progress: isolated delivery": ONE run-scoped bus for every publisher and
        # consumer of this run (outbox relay, role drains, the Operation), derived from the manifest id,
        # so concurrent runs never compete for a role queue and a restart derives the same streams.
        common = (service, executor, cli_operation.run_bus(manifest["id"]), cli.workflow(service), cli_operation.call_budget(),
                  build_collector(service.store, observer))
        if profile(manifest)["version"] == 2:
            # INV-COUNCIL-001: the snapshot port is a separate read-only connection to the same database
            # (never Store.transaction); the envelope is persisted through the executor's artifact store.
            cycle = cli_operation.council_run(*common, **wiring, snapshot=cli_operation.read_only_snapshot(),
                                              artifacts=executor.artifacts)
        else:
            cycle = cli_operation.autonomous_run(*common, **wiring)
        return cycle.run(manifest, bound, goal)
    finally:
        observer.close()


def _status(service, args) -> dict:
    from codex_harness.composition import cli_operation
    return {**cli_operation.autonomous_run(service).status(args.run_id), "exit_code": 0}


def _execute(service, args) -> dict:
    from codex_harness.entry.cli.operation import refusal
    try:
        return _run(service, args) if args.autonomous_command == "run" else _status(service, args)
    except Exception as exc:
        return refusal(exc)
