"""The `zeus research-program` root: the argument parser and the command bodies (M7 adapters/research_program_cli.py, cli.py research_program_command).

Layer: entry
Owns: add_parser (the argument shape of `zeus research-program`), run (its body: M7 research_program_command), the private _register, _run, _recover and _execute (M7 research_program_cli) and MAX_TICKS and CYCLE_OWNER
Does not own: dispatch (entry.cli main), the shared helpers (entry.cli.operation, the repository identity and source verification of entry.cli.dge) and the builders of the adapters (composition.cli_research_program, composition.cli_research)
Entry points: add_parser, run
Contracts: INV-RESEARCH-PROGRAM-001, INV-DISCOVERY-PRESSURE-001

Moved from M7 adapters/research_program_cli.py:29-55 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
`run` is M7 `cli.py` `research_program_command` (:626-633) and `_register`, `_run`, `_recover` and `_execute` are `adapters/research_program_cli.py` `register` (:58-69), `run` (:72-101), `recover` (:104-138) and `execute`
(:141-157), with `MAX_TICKS` and `CYCLE_OWNER` (:26-27) (R-c26, S10 unit C6c): the bodies are M7's verbatim except that the service is built first (as M7 `main()` did), `read_document`, `bind_goal` and `refusal` are
`entry.cli.operation`, `repository_identity` is the private `_repository_identity` of `entry.cli.dge`, `verify_sources` is `composition.cli_research.verify_sources` (S11 XC-9 DUP-1), `GitSource` is `composition.cli_research.git_source`, every other adapter
construction is a builder of `composition.cli_research_program`, the schemas are `research.domain.research_investigations`, `ProgramRefused` and `validate_config` are `research.domain.research_program`, `DgeRefused` is
`research.application.dge` and `build_observer` is `composition.observation`. `_run` passes `council=` the autonomous `_run` (`entry.cli.autonomous`): an ENTRY to ENTRY call, so it stays in entry (composition may not import entry).
"""

import re
from pathlib import Path

from codex_harness.research.domain.discovery_pressure import INTENTS, PROACTIVE

MAX_TICKS = 100
CYCLE_OWNER = re.compile(r"^[0-9a-f]{64}$")


def add_parser(commands) -> None:
    program = commands.add_parser("research-program", help="Finite discovery program: local + live feeds -> dedup -> "
                                                           "<=1 council per tick; operator-authorized bounds")
    sub = program.add_subparsers(dest="research_program_command", required=True)
    register = sub.add_parser("register", help="Register one immutable program config (urn:zeus:research-program:1); no models")
    register.add_argument("--file", type=Path, required=True)
    run = sub.add_parser("run", help="Run up to N collection ticks under the program bounds")
    run.add_argument("program_id")
    run.add_argument("--ticks", type=int, required=True, help="Requested cap for this invocation; never above max_cycles")
    # INV-DISCOVERY-PRESSURE-001: why this run fetches external feeds; no default and no inference.
    run.add_argument("--intent", required=True, choices=INTENTS,
                     help="proactive (pressure-gated) or an exempt reason: user_request, incident, "
                          "existing_work_result, task_required")
    run.add_argument("--cycle-owner", default=None, dest="cycle_owner",
                     help="64-hex owner token of the ONE cycle this run reserves (--ticks 1 only): the owner-actions "
                          "launch id, so its observer binds the cycle to that launch and never to a number alone")
    for name, text in (("status", "Safe read-only projection; store read only"), ("pause", "Block new ticks; an owned cycle finishes"),
                       ("resume", "Allow new ticks again (paused only)")):
        sub.add_parser(name, help=text).add_argument("program_id")
    recover = sub.add_parser("recover", help="Owner request (urn:zeus:research-dispatch-recovery:1): authorize ONE "
                                             "replacement of a proven pre-provider failed dispatch; version 2 "
                                             "(execution_revocation) revokes instead of proving; version 3 "
                                             "(settled_read_only_successor) succeeds a current failed "
                                             "read-only council once; urn:zeus:research-dispatch-followup:1 "
                                             "(accepted_evidence_followup) follows up an accepted report-only "
                                             "dispatch for new authoritative members once; no models")
    recover.add_argument("--file", type=Path, required=True)


def run(args) -> None:
    """INV-RESEARCH-PROGRAM-001: exit 0 only for a recorded, replayed or read result; refusals print a
    code and a type, never configs, feed bodies, DSNs or raw exceptions."""
    from codex_harness.composition import build
    from codex_harness.entry.cli.output import emit
    service = build()
    result = _execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def _register(service, args) -> dict:
    from codex_harness.composition import cli_research, cli_research_program
    from codex_harness.composition.configuration import repository_root
    from codex_harness.entry.cli.dge import _repository_identity
    from codex_harness.entry.cli.operation import bind_goal, read_document
    from codex_harness.research.application.dge import DgeRefused
    from codex_harness.research.domain.research_program import ProgramRefused, validate_config
    config = validate_config(read_document(args.file, "Research program config"), cli_research_program.packaged_policy())
    repository = repository_root()
    source = cli_research.git_source(repository)
    bind_goal(config["template"], source)  # goal bytes at base; a mismatch refuses before any row exists
    try:
        verified = cli_research.verify_sources({"base_revision": config["base_revision"], "sources": config["local_candidates"]}, source) \
            if config["local_candidates"] else []
    except DgeRefused as exc:
        raise ProgramRefused("local_" + exc.reason_code) from exc
    return {**cli_research_program.research_program(service.store).register(config, _repository_identity(repository), verified),
            "exit_code": 0}


def _run(service, args) -> dict:
    from codex_harness.composition import cli_research, cli_research_program
    from codex_harness.composition.configuration import repository_root, runtime_dir
    from codex_harness.entry.cli import autonomous
    from codex_harness.entry.cli.dge import _repository_identity
    from codex_harness.research.domain.research_program import ProgramRefused

    if type(args.ticks) is not int or not 1 <= args.ticks <= MAX_TICKS:
        raise ProgramRefused("ticks_invalid")
    owner = getattr(args, "cycle_owner", None)
    if owner is not None and not (args.ticks == 1 and CYCLE_OWNER.fullmatch(owner)):
        raise ProgramRefused("cycle_owner_invalid")
    evaluator, observer = None, None
    if args.intent == PROACTIVE:
        # Only a proactive run consults pressure, and the evaluator's transitions need the mandatory audit
        # observer; exempt runs keep their exact lightweight path (INV-DISCOVERY-PRESSURE-001).
        from codex_harness.composition.observation import build_observer
        observer = build_observer(service.store, "discovery-pressure")
    # S10 F2-B: the program reports its dispatch claims through the observer a proactive run already holds; an exempt run
    # builds none and constructs the program exactly as before.
    ports = {} if observer is None else {"observer": observer}
    programs = cli_research_program.research_program(service.store, **ports) if owner is None \
        else cli_research_program.research_program(service.store, token=lambda: owner, **ports)
    repository, runtime = repository_root(), runtime_dir()
    artifacts = cli_research_program.artifacts(runtime)
    if observer is not None:
        evaluator = cli_research_program.pressure_evaluator(service.store, observer)
    sources = cli_research_program.research_sources(artifacts, pressure=evaluator)
    runner = cli_research_program.program_runner(service, programs, sources, cli_research.git_source(repository),
                                                 cli_research_program.git_capture(repository), cli_research_program.call_budget(),
                                                 artifacts, runtime, council=autonomous._run, github_detail=sources.github_detail,
                                                 repository=_repository_identity(repository))  # R1: current root, checked before any tick effect
    result = runner.run(args.program_id, args.ticks, intent=args.intent)
    bad = any(t.get("failure") or t.get("result") in {"failed", "unknown"} for t in result["ticks"])
    return {**result, "exit_code": 1 if bad else 0}


def _recover(service, args, transport=None, evidence=None) -> dict:
    """The owner's explicit recovery request. The transport proof reads the CONFIGURED bus
    (`HARNESS_REDIS_URL`, `HARNESS_REDIS_NAMESPACE`) through the same `RedisBus` the publisher uses;
    its readiness is the owner's preflight. An unreachable bus refuses with
    `recovery_transport_unavailable` instead of being assumed empty, and a bus that is not the one
    the failed attempt committed before publishing refuses with `recovery_transport_changed`.

    An explicit `urn:zeus:research-dispatch-recovery:2` `execution_revocation` request builds no bus
    and reads no transport: it revokes execution authority in the control store only."""
    from codex_harness.composition import cli_research_program
    from codex_harness.entry.cli.operation import read_document
    from codex_harness.research.domain.research_investigations import (
        CONTRACT_SCHEMA,
        FOLLOWUP_SCHEMA,
        REVOCATION_SCHEMA,
        SUCCESSOR_SCHEMA,
    )
    document = read_document(args.file, "Research dispatch recovery request")
    schema = document.get("schema") if isinstance(document, dict) else None
    if schema in {SUCCESSOR_SCHEMA, CONTRACT_SCHEMA}:
        # The settled read-only successor (and the version-4 contract-failure successor) reads the
        # predecessor's execution artifacts from the executor's own content store and builds no bus: it
        # never proves or reads transport history.
        if evidence is None:
            evidence = cli_research_program.recovery_evidence()
        return {**cli_research_program.research_program(service.store).recover_dispatch(document, None, evidence), "exit_code": 0}
    if schema == FOLLOWUP_SCHEMA:
        # The accepted follow-up reads control-store rows only: no bus, transport or artifact port.
        return {**cli_research_program.research_program(service.store).recover_dispatch(document, None), "exit_code": 0}
    if transport is None and schema != REVOCATION_SCHEMA:
        failed = document.get("failed") if isinstance(document, dict) else None
        run_id = failed.get("run_id") if isinstance(failed, dict) else None
        # A run-scoped council published under its own namespace; the probe reads it when that run's
        # storage token exists (see TransportProbe._select). A malformed request refuses in the owner.
        transport = cli_research_program.transport_probe(run_id)
    return {**cli_research_program.research_program(service.store).recover_dispatch(document, transport), "exit_code": 0}


def _execute(service, args) -> dict:
    from codex_harness.composition import cli_research_program
    from codex_harness.entry.cli.operation import refusal
    command = args.research_program_command
    try:
        if command == "register":
            return _register(service, args)
        if command == "run":
            return _run(service, args)
        if command == "recover":
            return _recover(service, args)
        programs = cli_research_program.research_program(service.store)
        if command == "pause":
            return {**programs.pause(args.program_id), "exit_code": 0}
        if command == "resume":
            return {**programs.resume(args.program_id), "exit_code": 0}
        return {**programs.status(args.program_id), "exit_code": 0}
    except Exception as exc:
        return refusal(exc)
