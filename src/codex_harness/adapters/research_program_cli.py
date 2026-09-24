"""`zeus research-program register|run|status|pause|resume|recover`: thin wiring around the application
state machine and the adapters (INV-RESEARCH-PROGRAM-001). Register verifies the template goal and
every local candidate through git at base and never builds a provider, bus or budget. Status, pause
and resume touch the store only. Run is the finite synchronous runner an existing scheduled launcher
may call; it installs nothing."""
from __future__ import annotations

from pathlib import Path

from codex_harness.adapters.dge_cli import read_document, repository_identity, verify_sources
from codex_harness.adapters.operation_cli import GitSource, bind_goal, refusal
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.dge import DgeRefused
from codex_harness.application.research_program import ResearchProgram
from codex_harness.domain.research_investigations import REVOCATION_SCHEMA, SUCCESSOR_SCHEMA
from codex_harness.domain.research_program import ProgramRefused, validate_config

MAX_TICKS = 100


def add_parser(commands) -> None:
    program = commands.add_parser("research-program", help="Finite discovery program: local + live feeds -> dedup -> "
                                                           "<=1 council per tick; operator-authorized bounds")
    sub = program.add_subparsers(dest="research_program_command", required=True)
    register = sub.add_parser("register", help="Register one immutable program config (urn:zeus:research-program:1); no models")
    register.add_argument("--file", type=Path, required=True)
    run = sub.add_parser("run", help="Run up to N collection ticks under the program bounds")
    run.add_argument("program_id")
    run.add_argument("--ticks", type=int, required=True, help="Requested cap for this invocation; never above max_cycles")
    for name, text in (("status", "Safe read-only projection; store read only"), ("pause", "Block new ticks; an owned cycle finishes"),
                       ("resume", "Allow new ticks again (paused only)")):
        sub.add_parser(name, help=text).add_argument("program_id")
    recover = sub.add_parser("recover", help="Owner request (urn:zeus:research-dispatch-recovery:1): authorize ONE "
                                             "replacement of a proven pre-provider failed dispatch; version 2 "
                                             "(execution_revocation) revokes instead of proving; version 3 "
                                             "(settled_read_only_successor) succeeds a current failed "
                                             "read-only council once; no models")
    recover.add_argument("--file", type=Path, required=True)


def register(service, args) -> dict:
    from codex_harness.adapters.configuration import repository_root
    config = validate_config(read_document(args.file, "Research program config"), packaged_policy())
    repository = repository_root()
    source = GitSource(repository)
    bind_goal(config["template"], source)  # goal bytes at base; a mismatch refuses before any row exists
    try:
        verified = verify_sources({"base_revision": config["base_revision"], "sources": config["local_candidates"]}, source) \
            if config["local_candidates"] else []
    except DgeRefused as exc:
        raise ProgramRefused("local_" + exc.reason_code) from exc
    return {**ResearchProgram(service.store).register(config, repository_identity(repository), verified), "exit_code": 0}


def run(service, args) -> dict:
    from codex_harness.adapters import autonomous_cli
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.call_budget import CallBudget
    from codex_harness.adapters.configuration import repository_root, runtime_dir
    from codex_harness.adapters.research import ResearchSources
    from codex_harness.adapters.research_program import GitCapture, ProgramRunner

    if type(args.ticks) is not int or not 1 <= args.ticks <= MAX_TICKS:
        raise ProgramRefused("ticks_invalid")
    repository, runtime = repository_root(), runtime_dir()
    artifacts = FileArtifacts(str(runtime / "artifacts"))
    sources = ResearchSources(artifacts)
    runner = ProgramRunner(service, ResearchProgram(service.store), sources, GitSource(repository), GitCapture(repository),
                           CallBudget(), artifacts, runtime, council=autonomous_cli.run, github_detail=sources.github_detail,
                           repository=repository_identity(repository))  # R1: current root, checked before any tick effect
    result = runner.run(args.program_id, args.ticks)
    bad = any(t.get("failure") or t.get("result") in {"failed", "unknown"} for t in result["ticks"])
    return {**result, "exit_code": 1 if bad else 0}


def recover(service, args, transport=None, evidence=None) -> dict:
    """The owner's explicit recovery request. The transport proof reads the CONFIGURED bus
    (`HARNESS_REDIS_URL`, `HARNESS_REDIS_NAMESPACE`) through the same `RedisBus` the publisher uses;
    its readiness is the owner's preflight. An unreachable bus refuses with
    `recovery_transport_unavailable` instead of being assumed empty, and a bus that is not the one
    the failed attempt committed before publishing refuses with `recovery_transport_changed`.

    An explicit `urn:zeus:research-dispatch-recovery:2` `execution_revocation` request builds no bus
    and reads no transport: it revokes execution authority in the control store only."""
    document = read_document(args.file, "Research dispatch recovery request")
    schema = document.get("schema") if isinstance(document, dict) else None
    if schema == SUCCESSOR_SCHEMA:
        # The settled read-only successor reads the predecessor's execution artifacts from the executor's
        # own content store and builds no bus: it never proves or reads transport history.
        if evidence is None:
            from codex_harness.adapters.artifacts import FileArtifacts
            from codex_harness.adapters.autonomous_evidence import ExecutionEvidence
            from codex_harness.adapters.configuration import runtime_dir
            evidence = ExecutionEvidence(FileArtifacts(str(runtime_dir() / "artifacts")))
        return {**ResearchProgram(service.store).recover_dispatch(document, None, evidence), "exit_code": 0}
    if transport is None and schema != REVOCATION_SCHEMA:
        from codex_harness.adapters.bus import RedisBus
        from codex_harness.adapters.research_program import TransportProbe
        from codex_harness.bootstrap import redis_url
        failed = document.get("failed") if isinstance(document, dict) else None
        run_id = failed.get("run_id") if isinstance(failed, dict) else None
        # A run-scoped council published under its own namespace; the probe reads it when that run's
        # storage token exists (see TransportProbe._select). A malformed request refuses in the owner.
        transport = TransportProbe(RedisBus(redis_url()), scoped=RedisBus.for_run(redis_url(), run_id)
                                   if isinstance(run_id, str) and run_id else None)
    return {**ResearchProgram(service.store).recover_dispatch(document, transport), "exit_code": 0}


def execute(service, args) -> dict:
    command = args.research_program_command
    try:
        if command == "register":
            return register(service, args)
        if command == "run":
            return run(service, args)
        if command == "recover":
            return recover(service, args)
        programs = ResearchProgram(service.store)
        if command == "pause":
            return {**programs.pause(args.program_id), "exit_code": 0}
        if command == "resume":
            return {**programs.resume(args.program_id), "exit_code": 0}
        return {**programs.status(args.program_id), "exit_code": 0}
    except Exception as exc:
        return refusal(exc)


__all__ = ["add_parser", "execute", "recover", "register", "run"]
