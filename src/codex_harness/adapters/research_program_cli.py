"""`zeus research-program register|run|status|pause|resume`: thin wiring around the application
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


def execute(service, args) -> dict:
    command = args.research_program_command
    try:
        if command == "register":
            return register(service, args)
        if command == "run":
            return run(service, args)
        programs = ResearchProgram(service.store)
        if command == "pause":
            return {**programs.pause(args.program_id), "exit_code": 0}
        if command == "resume":
            return {**programs.resume(args.program_id), "exit_code": 0}
        return {**programs.status(args.program_id), "exit_code": 0}
    except Exception as exc:
        return refusal(exc)


__all__ = ["add_parser", "execute", "register", "run"]
