"""The `zeus` root parser assembler (M7 cli.py).

Layer: entry
Owns: parser (the root parser: global options and the root order), main (the M7 shell and the one dispatch table of the composed roots), and the re-export of emit (entry.cli.output)
Does not own: the root parsers and bodies (the modules of this package) and the roots not yet composed (S10 units C2c-C8)
Entry points: parser, emit, main
Contracts: none

Moved from M7 cli.py:175-389 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim.
"""

import argparse
import json
import sys
from pathlib import Path

from codex_harness.entry.cli.output import emit as emit


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zeus", description="Zeus: evidence, independent review, and recoverable operations")
    p.add_argument("--repository", type=Path, help="Harness checkout (independent of current directory)")
    from importlib.metadata import version
    p.add_argument("--version", action="version", version="Zeus " + version("zeus-harness"))
    commands = p.add_subparsers(dest="command", required=True)
    from codex_harness.entry.cli import (
        artifact,
        audit_repair,
        audit_service,
        autonomous,
        canary,
        cancel,
        cleanup,
        context,
        continuation,
        cycle,
        decision_feedback,
        demo,
        desk,
        dge,
        doctor,
        embed,
        execute_one,
        execution_recovery,
        fleet,
        flush,
        goal,
        host_delivery,
        improve,
        incident,
        index,
        init_db,
        inspect,
        observe,
        operate,
        organization,
        owner_actions,
        paths,
        project_graph,
        query,
        rebase,
        release_abandon,
        release_retry,
        research,
        research_program,
        rlm,
        rollback_hook,
        run_command,
        sdd,
        seed_research_backlog,
        send,
        serve,
        setup,
        status,
        ticket,
        validate,
        worker_session,
    )
    sdd.add_parser(commands)
    paths.add_parser(commands)
    setup.add_parser(commands)
    init_db.add_parser(commands)
    execution_recovery.add_parser(commands)
    seed_research_backlog.add_parser(commands)
    doctor.add_parser(commands)
    status.add_parser(commands)
    release_abandon.add_parser(commands)
    release_retry.add_parser(commands)
    cleanup.add_parser(commands)
    organization.add_parser(commands)
    validate.add_parser(commands)
    demo.add_parser(commands)
    incident.add_parser(commands)
    flush.add_parser(commands)
    send.add_parser(commands)
    run_command.add_parser(commands)
    serve.add_parser(commands)
    research.add_parser(commands)
    improve.add_parser(commands)
    execute_one.add_parser(commands)
    cancel.add_parser(commands)
    rebase.add_parser(commands)
    artifact.add_parser(commands)
    index.add_parser(commands)
    query.add_parser(commands)
    embed.add_parser(commands)
    project_graph.add_parser(commands)
    rlm.add_parser(commands)
    context.add_parser(commands)
    inspect.add_parser(commands)
    observe.add_parser(commands)
    rollback_hook.add_parser(commands)
    canary.add_parser(commands)
    cycle.add_parser(commands)
    operate.add_parser(commands)
    audit_service.add_parser(commands)
    audit_repair.add_parser(commands)
    dge.add_parser(commands)
    fleet.add_parser(commands)
    host_delivery.add_parser(commands)
    worker_session.add_parser(commands)
    continuation.add_parser(commands)
    owner_actions.add_parser(commands)
    desk.add_parser(commands)
    autonomous.add_parser(commands)
    research_program.add_parser(commands)
    decision_feedback.add_parser(commands)
    ticket.add_parser(commands)
    goal.add_parser(commands)
    return p


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    if args.repository:
        from codex_harness.composition.configuration import select_repository
        select_repository(args.repository)
    try:
        from codex_harness.entry.cli import (
            artifact,
            audit_repair,
            canary,
            cancel,
            cleanup,
            context,
            cycle,
            decision_feedback,
            demo,
            dge,
            doctor,
            embed,
            execute_one,
            execution_recovery,
            flush,
            goal,
            improve,
            incident,
            index,
            init_db,
            inspect,
            observe,
            organization,
            paths,
            project_graph,
            query,
            rebase,
            release_abandon,
            release_retry,
            research,
            rlm,
            rollback_hook,
            run_command,
            sdd,
            seed_research_backlog,
            send,
            serve,
            setup,
            status,
            ticket,
            validate,
            worker_session,
        )
        composed = {"paths": paths.run, "setup": setup.run, "organization": organization.run,
                    "validate": validate.run, "canary": canary.run, "doctor": doctor.run,
                    "init-db": init_db.run, "status": status.run, "inspect": inspect.run, "cancel": cancel.run,
                    "release-retry": release_retry.run, "goal": goal.run,
                    "incident": incident.run, "rollback-hook": rollback_hook.run, "run-command": run_command.run,
                    "demo": demo.run, "seed-research-backlog": seed_research_backlog.run,
                    "execution-recovery": execution_recovery.run,
                    "index": index.run, "query": query.run, "embed": embed.run, "project-graph": project_graph.run,
                    "context": context.run, "flush": flush.run, "send": send.run, "observe": observe.run,
                    "ticket": ticket.run, "sdd": sdd.run,
                    "audit-repair": audit_repair.run, "worker-session": worker_session.run,
                    "dge": dge.run, "decision-feedback": decision_feedback.run,
                    "release-abandon": release_abandon.run, "cleanup": cleanup.run, "research": research.run,
                    "improve": improve.run, "execute-one": execute_one.run, "rebase": rebase.run,
                    "artifact": artifact.run, "cycle": cycle.run, "serve": serve.run, "rlm": rlm.run}
        if args.command not in composed:
            raise RuntimeError("zeus " + args.command + " is not composed in the rebuild yet (DESIGN-s10 §3)")
        composed[args.command](args)
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc
