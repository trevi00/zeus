"""The `zeus operate` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus operate`), run (its body: M7 operate_command) and the private _run and _status (M7 operation_cli)
Does not own: dispatch (entry.cli main), the shared helpers (entry.cli.operation) and composition (composition.cli_operation, composition.operation, composition.observation)
Entry points: add_parser, run
Contracts: INV-OPERATION-001, INV-PROJECT-EVIDENCE-001, INV-ISOLATED-WORKER-001, INV-OBSERVATION-001

Moved from M7 cli.py:300-305 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `operate_command` (:471-483) and `_run` / `_status` are `adapters/operation_cli.py` `run` (:131-170) and `status` (:173-175) (R-c24, S10 unit C6a): the bodies are M7's verbatim except that the service is built first (as M7 `main()`
did), `refusal` and `bind_goal` are `entry.cli.operation`, the policy, identity and session owner are `composition.cli_operation` (they need adapters), `load_profile(host)` is `composition.operation.host_evidence_profile()` and the
adapters M7 built inline (`GitSource`, `RedisBus`, `CallBudget`, `Operation`) are builder calls.
"""

from pathlib import Path


def add_parser(commands) -> None:
    operate = commands.add_parser("operate", help="One bounded operation: worker, evidence gate, lead review; no conductor")
    operate_commands = operate.add_subparsers(dest="operate_command", required=True)
    operate_run = operate_commands.add_parser("run", help="Claim the manifest id and run it to a terminal receipt")
    operate_run.add_argument("--file", type=Path, required=True, help="Operation manifest JSON (urn:zeus:operation:1)")
    operate_status = operate_commands.add_parser("status", help="Read the saved receipt; store read only")
    operate_status.add_argument("operation_id")


def run(args) -> None:
    """INV-OPERATION-001: exit 0 only for an accepted (or cached accepted) receipt; failures print a
    code and a type, never DSNs, raw exceptions, prompts, plans or environment values."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.operation import refusal
    from codex_harness.entry.cli.output import emit
    service = build()
    try:
        receipt = _run(service, args) if args.operate_command == "run" else _status(service, args)
    except Exception as exc:
        emit(refusal(exc))
        raise SystemExit(1) from exc
    emit(receipt)
    if args.operate_command == "run" and receipt.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _run(service, args) -> dict:
    from codex_harness.composition import cli, cli_bus, cli_operation, cli_research
    from codex_harness.composition.configuration import repository_root, runtime_dir, settings
    from codex_harness.composition.observation import build_collector, build_observer
    from codex_harness.composition.operation import build_executor, host_evidence_profile, host_isolation
    from codex_harness.entry.cli.operation import bind_goal, read_manifest
    from codex_harness.intake.domain.operation_manifest import validate_manifest

    document = read_manifest(args.file)
    manifest = validate_manifest(document, cli_operation.packaged_policy())
    host = settings()
    policy = cli_operation.execution_policy(manifest, host)
    # Loaded once from host settings; an invalid configured profile refuses here, before any provider.
    profile = host_evidence_profile()
    # INV-ISOLATED-WORKER-001: the host selection (or None) is validated, with Docker, image and token,
    # before the reservation, the executor and any provider; a refusal here never runs on the host.
    isolated = host_isolation(profile)
    repository = repository_root()
    goal = bind_goal(manifest, cli_research.git_source(repository))
    bound = cli_operation.identity(manifest, repository, policy, host, runtime_dir(), profile,
                                   **({} if isolated is None else {"isolation": isolated.config}))
    observer = build_observer(service.store, "cli.operate")
    try:
        # No knowledge adapter: this entry point writes execution ledgers and provisional
        # artifacts only; formal knowledge promotion is a separate explicit contract.
        executor = build_executor(service, observer=observer, execution_policy=policy, knowledge=False,
                                  evidence_profile=profile, **({} if isolated is None else {"isolation": isolated}),
                                  **cli_operation.session_owner(service, manifest["id"], observer))
        # INV-OBSERVATION-001: the one process observer also sees the operation's message path.
        operation = cli_operation.operation(service, executor, cli_bus.bus(), cli.workflow(service),
                                            cli_operation.call_budget(), build_collector(service.store, observer),
                                            observer=observer)
        return operation.run(manifest, bound, goal)
    finally:
        observer.close()


def _status(service, args) -> dict:
    from codex_harness.composition import cli_operation
    # Store read only: no executor, observer, bus or provider is built.
    return cli_operation.operation(service).status(args.operation_id)
