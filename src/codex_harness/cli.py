from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.bus import RedisBus
from codex_harness.adapters.canary import executable_canary
from codex_harness.adapters.codex import CodexRuntime
from codex_harness.adapters.commands import run_process
from codex_harness.adapters.contracts import validate_message
from codex_harness.adapters.knowledge import PostgresKnowledge
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import (
    build,
    build_executor,
    build_observer,
    database_url,
    organization,
    redis_url,
)
from codex_harness.domain.model import (
    ContextItem,
    ContractError,
    compile_context,
    digest,
    envelope,
    require,
    utcnow,
)
from codex_harness.domain.policy import POLICY


def emit(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)


def demo(service, scope: str) -> dict:
    """Scripted bootstrap lifecycle using real persistence, not autonomous agent review."""
    correlation = "bootstrap-" + str(uuid4())
    records = []
    for _ in range(2):
        message = envelope("incident.report", "worker:implementation", "lead:improvement",
                           "record_incident", {"occurrence_id": str(uuid4()),
                           "root_cause": "powershell-codex-ps1-policy", "scope": scope,
                           "evidence_refs": ["fixture:windows-codex-ps1-policy"]}, correlation)
        records.append(service.record_incident(validate_message(message)))
    hook_id = records[-1]["hook_id"]
    existing = service.get_hook(hook_id)
    if existing["status"] == "active":
        return {"mode": "scripted-bootstrap", "already_active": hook_id, "incidents": records}
    spec = {"kind": "executable_alias", "platform": "windows", "match": "codex.ps1",
            "replacement": "codex.cmd"}
    revision = "spec-sha256:" + digest(spec)
    service.propose(hook_id, "worker:implementation", spec, revision)
    canary = executable_canary(spec)
    for actor in ("lead:improvement", "conductor"):
        service.review(hook_id, actor, revision, digest(spec), True,
                       "fixture:scripted-review-not-llm")
    service.record_canary(hook_id, revision, digest(spec), canary["checks"])
    if all(canary["checks"].values()):
        service.activate(hook_id)
    checkpoint = service.checkpoint("worker:implementation", _generation(service, "worker:implementation"),
                                    {"next_action": "apply active hooks before the next command",
                                     "source_revision": revision, "graph_snapshot": "bootstrap-fixture",
                                     "hook_id": hook_id})
    return {"mode": "scripted-bootstrap; no autonomous PR review or deployment",
            "incidents": records, "hook": service.get_hook(hook_id), "canary": canary,
            "prepared_command": service.prepare_command(["codex.ps1", "--version"], "windows"),
            "checkpoint": checkpoint}


def _generation(service, agent: str) -> int:
    with service.store.transaction() as tx:
        return (tx.get("sessions", agent) or {"generation": 0})["generation"]


def serve(service, agent: str, once: bool, execute: bool = False, observer=None) -> None:
    service.org.actor(agent)
    bus = RedisBus(redis_url())
    consumer = f"{agent}:{uuid4()}"
    last_activity = time.monotonic()
    workflow = Workflow(service.store, service.org)
    # INV-OBSERVATION-001: one process run, one spool; message receipt, ledger acceptance and the
    # transport acknowledgement are three separate general-log facts, none of them a task result.
    observer = observer or build_observer(service.store, "cli.serve", agent)
    executor = build_executor(service, observer=observer) if execute else None
    prefer_decisions = True
    observer.emit("general.process_started", "started",
                  attributes={"agent": agent, "autonomous": execute, "platform": sys.platform,
                              "python": sys.version.split()[0], "mode": "serve"})
    emit({"status": "listening", "agent_id": agent, "autonomous": execute,
          "process_run_id": observer.process_run_id})
    while True:
        row = bus.receive(agent, consumer)
        if row:
            entry_id, fields = row
            message = None
            try:
                message = bus.decode(fields)
                observer.emit("general.message_received", "observed", correlation_id=message["correlation_id"],
                              causation_id=message["message_id"],
                              attributes={"stream_entry_id": entry_id, "message_id": message["message_id"],
                                          "message_type": message["type"], "sender": message["who"]["sender"],
                                          "recipient": message["who"]["recipient"]})
                require(message["who"]["recipient"] == agent, "Message routed to wrong agent")
                service.org.authorize(message)
                if message["type"] == "incident.report":
                    result = service.record_incident(message)
                else:
                    result = workflow.handle(message)
                observer.emit("general.message_accepted", "succeeded", correlation_id=message["correlation_id"],
                              causation_id=message["message_id"],
                              attributes={"message_id": message["message_id"], "message_type": message["type"],
                                          "result_kind": type(result).__name__})
                service.flush_outbox(bus, audit=observer.audit_system)
                bus.ack(agent, entry_id)
                observer.emit("general.message_acknowledged", "observed", correlation_id=message["correlation_id"],
                              causation_id=message["message_id"],
                              attributes={"stream_entry_id": entry_id, "message_id": message["message_id"]})
                emit({"message_id": message["message_id"], "result": result})
                last_activity = time.monotonic()
            except (ContractError, json.JSONDecodeError, KeyError) as exc:
                bus.dead_letter(agent, entry_id, fields, str(exc))
                observer.emit("general.message_rejected", "blocked", severity="warning",
                              correlation_id=message.get("correlation_id") if isinstance(message, dict) else None,
                              reason_code=type(exc).__name__,
                              attributes={"stream_entry_id": entry_id, "error_type": type(exc).__name__,
                                          "dead_letter": True})
                emit({"rejected": entry_id, "reason": str(exc)})
        if executor:
            # Give both durable queues turns, even under a continuous task backlog.
            first, second = ((executor.decide_one, executor.execute_one) if prefer_decisions
                             else (executor.execute_one, executor.decide_one))
            result = first(agent) or second(agent)
            prefer_decisions = not prefer_decisions
            if result:
                emit({"execution": result})
                service.flush_outbox(bus, audit=observer.audit_system)
                last_activity = time.monotonic()
        if once:
            break
        if time.monotonic() - last_activity >= POLICY.idle_seconds:
            observer.emit("general.process_idle_exit", "observed",
                          attributes={"agent": agent, "idle_seconds": POLICY.idle_seconds})
            observer.close()
            emit({"status": "idle_exit", "agent": agent, "at": utcnow()})
            return
    observer.close()


def observe_command(service, args):
    from codex_harness.adapters.observation_spool import SpoolDirectory
    from codex_harness.application.observations import status_report
    from codex_harness.bootstrap import build_collector, observation_root
    if args.observe_command == "collect":
        observer = build_observer(service.store, "cli.observe")
        result = build_collector(service.store, observer).collect()
        observer.close()
        emit(result)
    elif args.observe_command == "status":
        emit(status_report(service.store, SpoolDirectory(observation_root())))
    else:
        observer = build_observer(service.store, "cli.observe", "operator")
        emit(observer.resolve_termination(args.record_id, resolution=args.resolution, operator=args.operator,
                                          reason=args.reason))
        observer.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zeus", description="Zeus: evidence, independent review, and recoverable operations")
    p.add_argument("--repository", type=Path, help="Harness checkout (independent of current directory)")
    from importlib.metadata import version
    p.add_argument("--version", action="version", version="Zeus " + version("zeus-harness"))
    commands = p.add_subparsers(dest="command", required=True)
    from codex_harness.adapters.sdd_cli import add_parser
    add_parser(commands)
    commands.add_parser("paths", help="Resolved local paths and persistent namespace; no service access")
    commands.add_parser("setup", help="Create local configuration without overwriting credentials")
    commands.add_parser("init-db")
    recovery = commands.add_parser('execution-recovery', help='Explicit trusted local operator recovery; no human attestation')
    actions = recovery.add_subparsers(dest='recovery_action', required=True)
    prepare = actions.add_parser('prepare')
    prepare.add_argument('task_id')
    prepare.add_argument('--bucket', choices=['tasks', 'decisions_pending'], default='tasks')
    prepare.add_argument('--operation', choices=['migrate', 'resume', 'repair'], required=True)
    prepare.add_argument('--max-attempts', type=int, required=True, help='Total ceiling including attempts already spent')
    prepare.add_argument('--deadline', help='Future aware ISO timestamp; existing deadline cannot be removed')
    prepare.add_argument('--reason', required=True)
    prepare.add_argument('--operator', required=True, help='Audit label, not authenticated identity')
    prepare.add_argument('--evidence', action='append', required=True, help='Existing sha256 artifact reference')
    prepare.add_argument('--output', type=Path, required=True)
    apply = actions.add_parser('apply')
    apply.add_argument('--packet', type=Path, required=True)
    seed = commands.add_parser("seed-research-backlog")
    seed.add_argument("--artifacts", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--offline", action="store_true", help="Check installation without a database")
    commands.add_parser("status")
    for name in ("release-abandon", "release-retry"):
        release = commands.add_parser(name)
        release.add_argument("release_id")
        release.add_argument("--reason", required=True)
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--apply", action="store_true")
    commands.add_parser("organization")
    v = commands.add_parser("validate")
    v.add_argument("file")
    d = commands.add_parser("demo")
    d.add_argument("--scope", default="bootstrap/windows/codex")
    i = commands.add_parser("incident")
    i.add_argument("file")
    commands.add_parser("flush")
    send = commands.add_parser("send")
    send.add_argument("file")
    run = commands.add_parser("run-command")
    run.add_argument("--timeout", type=int, default=120)
    run.add_argument("argv", nargs=argparse.REMAINDER)
    s = commands.add_parser("serve")
    s.add_argument("--agent", required=True)
    s.add_argument("--once", action="store_true")
    s.add_argument("--execute", action="store_true")
    research = commands.add_parser("research")
    research.add_argument("source", choices=["github", "geeknews"])
    improve = commands.add_parser("improve")
    improve.add_argument("objective")
    improve.add_argument("--acceptance", action="append", required=True)
    improve.add_argument("--importance", choices=["simple", "important"])
    execute = commands.add_parser("execute-one")
    execute.add_argument("--agent", required=True)
    cancel = commands.add_parser("cancel")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", required=True)
    rebase = commands.add_parser("rebase")
    rebase.add_argument("task_id")
    rebase.add_argument("--onto", default="HEAD")
    artifact = commands.add_parser("artifact")
    artifact.add_argument("reference")
    artifact.add_argument("--start", type=int, default=0)
    artifact.add_argument("--length", type=int, default=8000)
    artifact.add_argument("--search")
    index = commands.add_parser("index")
    index.add_argument("root", nargs="?", default=".")
    q = commands.add_parser("query")
    q.add_argument("text")
    q.add_argument("--semantic", action="store_true")
    embedding = commands.add_parser("embed")
    embedding.add_argument("--limit", type=int, default=200)
    commands.add_parser("project-graph")
    rlm = commands.add_parser("rlm")
    rlm.add_argument("reference")
    rlm.add_argument("question")
    rlm.add_argument("--max-calls", type=int, default=8)
    context = commands.add_parser("context")
    context.add_argument("query")
    context.add_argument("--agent", default="worker:implementation")
    context.add_argument("--budget", type=int, default=12000)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("bucket", choices=["incidents", "hooks", "sessions", "events", "deliveries", "outbox",
                                           "outbox_quarantine", "outbox_delivery", "outbox_attempts",
                                           "execution_failures", "execution_recoveries", "execution_notices", "execution_notice_errors",
                                           "execution_rejections",
                                           "execution_time_events",
                                           "invocation_reservations",
                                           "observations", "observation_audit", "observation_quarantine",
                                           "observation_alerts", "observation_collections", "observation_terminations",
                                           "tasks", "decisions_pending", "releases", "deployment", "release_queue",
                                           "audit_service"])
    observe = commands.add_parser("observe", help="Observation logs: collect the spool, report status, reconcile")
    observe_commands = observe.add_subparsers(dest="observe_command", required=True)
    observe_commands.add_parser("collect", help="Move durable spool records into PostgreSQL and acknowledge them")
    observe_commands.add_parser("status", help="Counts, process health, pending terminations, orphans; read-only")
    reconcile = observe_commands.add_parser("reconcile", help="Operator decision for a pending termination record")
    reconcile.add_argument("record_id")
    reconcile.add_argument("--resolution", choices=["rerun", "discard"], required=True)
    reconcile.add_argument("--operator", required=True, help="Audit label, not authenticated identity")
    reconcile.add_argument("--reason", required=True)
    rollback = commands.add_parser("rollback-hook")
    rollback.add_argument("hook_id")
    rollback.add_argument("--reason", required=True)
    canary = commands.add_parser("canary")
    canary.add_argument("--live", action="store_true", help="Execute a real Codex file task (uses account quota)")
    cycle = commands.add_parser("cycle", help="Bounded persistent execution loop over one correlation; no conductor")
    cycle_commands = cycle.add_subparsers(dest="cycle_command", required=True)
    for name in ("start", "status", "handoff", "step"):
        sub = cycle_commands.add_parser(name)
        sub.add_argument("cycle_id")
        if name == "start":
            sub.add_argument("--correlation", required=True)
            sub.add_argument("--max-executions", type=int, required=True,
                             help="Executor starts allowed through this cycle; not a billing count")
    operate = commands.add_parser("operate", help="One bounded operation: worker, evidence gate, lead review; no conductor")
    operate_commands = operate.add_subparsers(dest="operate_command", required=True)
    operate_run = operate_commands.add_parser("run", help="Claim the manifest id and run it to a terminal receipt")
    operate_run.add_argument("--file", type=Path, required=True, help="Operation manifest JSON (urn:zeus:operation:1)")
    operate_status = operate_commands.add_parser("status", help="Read the saved receipt; store read only")
    operate_status.add_argument("operation_id")
    from codex_harness.adapters.audit_service import add_parser as add_audit_service_parser
    add_audit_service_parser(commands)
    from codex_harness.adapters.audit_repair_cli import add_parser as add_audit_repair_parser
    add_audit_repair_parser(commands)
    from codex_harness.adapters.dge_cli import add_parser as add_dge_parser
    add_dge_parser(commands)
    from codex_harness.adapters.fleet_cli import add_parser as add_fleet_parser
    add_fleet_parser(commands)
    from codex_harness.adapters.host_delivery import add_parser as add_host_delivery_parser
    add_host_delivery_parser(commands)
    from codex_harness.adapters.worker_sessions import add_parser as add_worker_session_parser
    add_worker_session_parser(commands)
    from codex_harness.adapters.continuation_cli import add_parser as add_continuation_parser
    add_continuation_parser(commands)
    from codex_harness.adapters.frontdesk_cli import add_parser as add_desk_parser
    add_desk_parser(commands)
    from codex_harness.adapters.autonomous_cli import add_parser as add_autonomous_parser
    from codex_harness.adapters.decision_feedback_cli import (
        add_parser as add_decision_feedback_parser,
    )
    from codex_harness.adapters.research_program_cli import (
        add_parser as add_research_program_parser,
    )
    add_autonomous_parser(commands)
    add_research_program_parser(commands)
    add_decision_feedback_parser(commands)
    ticket = commands.add_parser("ticket", help="Versioned review topics and explicit GitHub issue sync")
    ticket_commands = ticket.add_subparsers(dest="ticket_command", required=True)
    ticket_commands.add_parser("list")
    create = ticket_commands.add_parser("create")
    create.add_argument("--file", type=Path, required=True)
    create.add_argument("--author", default="operator")
    for name in ("show", "export", "update", "review", "dispatch", "sync", "pull", "evidence", "prepare-close", "close", "reopen", "review-close"):
        sub = ticket_commands.add_parser(name)
        sub.add_argument("ticket_id")
        if name == "show":
            sub.add_argument("--revision", type=int)
        if name in {"update", "review", "dispatch"}:
            sub.add_argument("--revision", type=int, required=True)
        if name == "dispatch":
            sub.add_argument("--goal-manifest", type=Path, help="Goal manifest JSON; requires --criterion")
            sub.add_argument("--criterion", help="Criterion id in the goal manifest; requires --goal-manifest")
        if name == "update":
            sub.add_argument("--file", type=Path, required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--author", default="operator")
        if name == "review":
            sub.add_argument("--reviewer", required=True)
            sub.add_argument("--provider", required=True)
            sub.add_argument("--verdict", choices=["support", "changes_requested", "question"], required=True)
            sub.add_argument("--summary", required=True)
            sub.add_argument("--evidence", action="append", required=True)
        if name in {"sync", "pull"}:
            sub.add_argument("--repo", required=True, help="GitHub owner/repository")
        if name == "sync":
            sub.add_argument("--preview", action="store_true", help="Print projection; no network or state changes")
            sub.add_argument("--reconcile-observation", help="Explicitly replace the observed title/body with the local projection")
            sub.add_argument("--revision", type=int, help="Required current revision when reconciling")
        if name in {"evidence", "prepare-close"}:
            sub.add_argument("--file", type=Path, required=True)
        if name == "prepare-close":
            sub.add_argument("--output", type=Path, required=True, help="New canonical packet file for external signing")
        if name == "close":
            sub.add_argument("--packet", type=Path, required=True)
            sub.add_argument("--signature", action="append", required=True, help="PRINCIPAL=SIGNATURE_FILE; repeat per signer")
        if name == "review-close":
            sub.add_argument("--packet", type=Path, required=True)
            sub.add_argument("--output", type=Path, required=True, help="Read-only HTML review; never grants approval")
        if name == "reopen":
            sub.add_argument("--revision", type=int, required=True)
            sub.add_argument("--sequence", type=int, required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--expected-state", choices=["closed", "open", "dispatched"], default="closed",
                             help="Use open/dispatched explicitly to reconcile a new external close")
    goal = commands.add_parser("goal", help="Goal manifest progress: read-only report and same-definition compare")
    goal_commands = goal.add_subparsers(dest="goal_command", required=True)
    report = goal_commands.add_parser("report", help="Observe criterion closure state; no completion authority")
    report.add_argument("manifest", type=Path)
    compare = goal_commands.add_parser("compare", help="Gained/regressed criteria between two reports of one definition")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    return p


def _json_file(path):
    try:
        require(path.stat().st_size <= 1024 * 1024, "Goal file exceeds budget")
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError("Goal file unavailable") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("Goal file is not valid JSON") from exc


def goal_command(service, args):
    # INV-GOAL-PROGRESS-001: store read only; no executor, observer, bus or provider is built.
    from codex_harness.application.goal_progress import GoalProgress, compare_reports
    if args.goal_command == "report":
        emit(GoalProgress(service.store).report(_json_file(args.manifest)))
    else:
        emit(compare_reports(_json_file(args.before), _json_file(args.after)))


def ticket_command(service, args):
    from codex_harness.application.tickets import Tickets, render_ticket
    tickets = Tickets(service.store, service.org)
    command = args.ticket_command
    if command == "list":
        emit(tickets.list())
    elif command == "create":
        emit(tickets.create(json.loads(args.file.read_text("utf-8")), args.author))
    elif command == "update":
        emit(tickets.update(args.ticket_id, args.revision, json.loads(args.file.read_text("utf-8")),
                            args.reason, args.author))
    elif command == "review":
        emit(tickets.review(args.ticket_id, args.revision, args.reviewer, args.provider,
                            args.verdict, args.summary, args.evidence))
    elif command == "show":
        emit(tickets.get(args.ticket_id, args.revision))
    elif command == "export" or (command == "sync" and args.preview):
        print(render_ticket(tickets.get(args.ticket_id)), end="")
    elif command == "dispatch":
        manifest = _json_file(args.goal_manifest) if args.goal_manifest is not None else None
        executor = build_executor(service)
        emit(tickets.dispatch(args.ticket_id, args.revision, executor.git._git("rev-parse", "HEAD"),
                              goal_manifest=manifest, criterion_id=args.criterion))
    elif command in {"evidence", "prepare-close", "close", "reopen", "review-close"}:
        from codex_harness.adapters.ticket_cli import execute
        emit(execute(tickets, args))
    else:
        from codex_harness.adapters.github_tickets import GitHubTickets
        from codex_harness.adapters.ticket_cli import build_lifecycle
        lifecycle = build_lifecycle(tickets)
        github = GitHubTickets(tickets, lifecycle.artifacts, lifecycle)
        if command == "sync":
            emit(github.sync(args.ticket_id, args.repo,
                            reconcile_observation=args.reconcile_observation, expected_revision=args.revision))
        else:
            emit(github.pull(args.ticket_id, args.repo))


def cycle_command(service, args):
    from codex_harness.application.local_cycle import LocalCycle
    if args.cycle_command == "start":
        emit(LocalCycle(service).start(args.cycle_id, args.correlation, args.max_executions))
    elif args.cycle_command == "status":
        row = LocalCycle(service).status(args.cycle_id)
        # Presentation only: derived here, never written back to the stored cycle row.
        emit({**row, "remaining_executions": max(0, row["max_executions"] - row["executions"])})
    elif args.cycle_command == "handoff":
        # INV-CYCLE-HANDOFF-001: store read only; no executor, observer, bus or provider is built.
        emit(LocalCycle(service).handoff(args.cycle_id))
    else:
        observer = build_observer(service.store, "cli.cycle")
        executor = build_executor(service, observer=observer)
        cycle = LocalCycle(service, executor, RedisBus(redis_url()), Workflow(service.store, service.org),
                           observer=observer)
        try:
            emit(cycle.step(args.cycle_id))
        finally:
            observer.close()


def operate_command(service, args):
    """INV-OPERATION-001: exit 0 only for an accepted (or cached accepted) receipt; failures print a
    code and a type, never DSNs, raw exceptions, prompts, plans or environment values."""
    from codex_harness.adapters import operation_cli
    try:
        receipt = (operation_cli.run(service, args) if args.operate_command == "run"
                   else operation_cli.status(service, args))
    except Exception as exc:
        emit(operation_cli.refusal(exc))
        raise SystemExit(1) from exc
    emit(receipt)
    if args.operate_command == "run" and receipt.get("exit_code", 1) != 0:
        raise SystemExit(1)


def dge_command(service, args):
    """INV-DGE-001: exit 0 only for a recorded, replayed or read result; refusals print a code and a
    type, never packet text, payloads, DSNs or raw exceptions."""
    from codex_harness.adapters import dge_cli
    result = dge_cli.execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def fleet_command(service, args):
    """INV-FLEET-001: exit 0 only for a completed command; refusals print a code and a type, never
    manifests, paths, schemas, DSNs, raw exceptions or process output."""
    from codex_harness.adapters import fleet_cli
    try:
        result = fleet_cli.execute(service, args)
    except Exception as exc:
        emit(fleet_cli.refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def host_delivery_command(service, args):
    """INV-HOST-DELIVERY-001: exit 0 only for a completed command; refusals print a code and a type,
    never a plan, a descriptor, a host path, a service name, a PR body, a DSN or a raw exception."""
    from codex_harness.adapters import host_delivery
    try:
        result = host_delivery.execute(service, args)
    except Exception as exc:
        emit(host_delivery.refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def worker_session_command(service, args):
    """INV-WORKER-SESSION-001: read-only status and explicit close; refusals print a code and a
    type, never transcript bytes, archive paths, DSNs or raw exceptions."""
    from codex_harness.adapters import worker_sessions
    try:
        result = worker_sessions.execute(service, args)
    except Exception as exc:
        emit(worker_sessions.refusal(exc))
        raise SystemExit(1) from exc
    emit(result)


def continuation_command(service, args):
    """INV-CONTINUATION-001: exit 0 only for a completed command; refusals print a code, the named
    next owner and a type, never a manifest, a path, a DSN or a raw exception."""
    from codex_harness.adapters import continuation_cli
    try:
        result = continuation_cli.execute(service, args)
    except Exception as exc:
        emit(continuation_cli.refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def desk_command(service, args):
    """local-operations-desk-001: exit 0 only for a completed command; refusals print a code and a
    type, never conversation text, paths, DSNs, raw exceptions or provider output."""
    from codex_harness.adapters import frontdesk_cli
    try:
        result = frontdesk_cli.execute(service, args)
    except Exception as exc:
        emit(frontdesk_cli.desk_refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def autonomous_command(service, args):
    """INV-AUTONOMOUS-001: exit 0 only for an accepted (or cached accepted) receipt; refusals print a
    code and a type, never manifests, packets, payloads, DSNs or raw exceptions."""
    from codex_harness.adapters import autonomous_cli
    result = autonomous_cli.execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def audit_service_command(service, args):
    """INV-AUDIT-SERVICE-001: exit 0 only for a completed command; refusals print a code and a type,
    never prompts, source text, partition scope, credentials, DSNs or raw exceptions."""
    from codex_harness.adapters import audit_service
    try:
        result = audit_service.execute(service, args)
    except Exception as exc:
        emit(audit_service.refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def audit_repair_command(service, args):
    """INV-AUDIT-REPAIR-001: exit 0 only for a completed owner command; refusals print a code and a
    type, never a model draft, a validator message, source text or a raw exception."""
    from codex_harness.adapters import audit_repair_cli
    try:
        result = audit_repair_cli.execute(service, args)
    except Exception as exc:
        emit(audit_repair_cli.refusal(exc))
        raise SystemExit(1) from exc
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def decision_feedback_command(service, args):
    """INV-DECISION-FEEDBACK-001: exit 0 only for a recorded or read result; refusals print a code and
    a type, never registry content, row bodies, payloads, DSNs or raw exceptions."""
    from codex_harness.adapters import decision_feedback_cli
    result = decision_feedback_cli.execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def research_program_command(service, args):
    """INV-RESEARCH-PROGRAM-001: exit 0 only for a recorded, replayed or read result; refusals print a
    code and a type, never configs, feed bodies, DSNs or raw exceptions."""
    from codex_harness.adapters import research_program_cli
    result = research_program_cli.execute(service, args)
    emit(result)
    if result.get("exit_code", 1) != 0:
        raise SystemExit(1)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    if args.repository:
        from codex_harness.adapters.configuration import select_repository
        select_repository(args.repository)
    try:
        if args.command == "sdd":
            from codex_harness.adapters.sdd_cli import execute
            emit(execute(args))
            return
        if args.command == "paths":
            from codex_harness.adapters.configuration import repository_root, runtime_dir, settings
            config = settings()
            emit({"repository": str(repository_root()), "runtime": str(runtime_dir()),
                  "compose_project": config.get("COMPOSE_PROJECT_NAME", "codex-harness"),
                  "redis_namespace": config.get("HARNESS_REDIS_NAMESPACE", "codex-harness")})
            return
        if args.command == "setup":
            from codex_harness.adapters.configuration import initialize, runtime_dir
            result = initialize()
            runtime_dir().mkdir(parents=True, exist_ok=True)
            emit(result)
            return
        if args.command == "doctor" and args.offline:
            import shutil

            from codex_harness.adapters.codex import resolve_codex
            from codex_harness.adapters.configuration import (
                codex_auth,
                repository_root,
                runtime_dir,
            )
            checks = {name: shutil.which(name) is not None for name in ("git", "uv", "docker")}
            checks.update(codex=resolve_codex() is not None, codex_auth=codex_auth().is_file(),
                          compose=(repository_root() / "compose.yaml").is_file())
            emit({"checks": checks, "repository": str(repository_root()),
                  "runtime": str(runtime_dir()), "services_checked": False})
            if not all(checks.values()):
                raise SystemExit(1)
            return
        if args.command == "organization":
            emit({"agents": [asdict(a) for a in organization().agents.values()]})
            return
        if args.command == "validate":
            message = validate_message(json.loads(Path(args.file).read_text(encoding="utf-8")))
            organization().authorize(message)
            emit({"valid": True, "message_id": message["message_id"]})
            return
        if args.command == "canary":
            runtime = CodexRuntime()
            result = runtime.probe()
            if args.live:
                import tempfile

                with tempfile.TemporaryDirectory(prefix="harness-canary-") as directory:
                    fixture = Path(directory) / "input.txt"
                    fixture.write_text("HARNESS_CANARY_42", encoding="utf-8")
                    schema = {"type": "object", "additionalProperties": False,
                              "properties": {"value": {"type": "string"}}, "required": ["value"]}
                    run = runtime.run("Read input.txt, write its exact contents to output.txt. "
                                      "Return the exact input in the value field. Use no network.",
                                      directory, schema)
                    output = Path(directory) / "output.txt"
                    result["live_passed"] = (run["answer"]["value"] == "HARNESS_CANARY_42"
                                             and output.exists()
                                             and output.read_text(encoding="utf-8").strip() == "HARNESS_CANARY_42")
                    result["event_count"] = len(run["events"])
            emit(result)
            if not result["passed"] or result.get("live_passed") is False:
                raise SystemExit(1)
            return
        if args.command == "goal" and args.goal_command == "compare":
            goal_command(None, args)
            return
        service = build()
        if args.command == "goal":
            goal_command(service, args)
        elif args.command == "init-db":
            receipt = service.store.migrate()
            emit({"migrated": True, "applied": receipt["applied"], "already_applied": receipt["already_applied"], "tool": receipt["tool"]})
        elif args.command == 'execution-recovery':
            from codex_harness.adapters.artifacts import FileArtifacts
            from codex_harness.adapters.configuration import runtime_dir
            from codex_harness.application.execution_recovery import ExecutionRecovery
            from codex_harness.domain.model import canonical
            recovery = ExecutionRecovery(service.store, service.org, FileArtifacts(runtime_dir() / 'artifacts'))
            if args.recovery_action == 'prepare':
                packet = recovery.prepare(args.bucket, args.task_id, operation=args.operation,
                    max_attempts=args.max_attempts, deadline=args.deadline, reason=args.reason,
                    evidence_refs=args.evidence, operator=args.operator)
                try:
                    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
                        stream.write(canonical(packet))
                except OSError as exc:
                    raise ContractError('Cannot create new recovery packet file') from exc
                emit({'packet': str(args.output), 'authority': packet['authority'], 'applied': False})
            else:
                from codex_harness.adapters.sdd import parse_json
                try:
                    require(args.packet.stat().st_size <= 1024 * 1024, 'Recovery packet exceeds budget')
                    packet = parse_json(args.packet.read_text(encoding='utf-8'))
                except OSError as exc:
                    raise ContractError('Recovery packet file unavailable') from exc
                emit(recovery.apply(packet))
        elif args.command == "release-abandon":
            from codex_harness.adapters.configuration import codex_auth
            from codex_harness.adapters.deployment import ReleaseRunner
            executor = build_executor(service)
            emit(ReleaseRunner(service, executor.git, executor.artifacts, str(codex_auth()))
                 .abandon(args.release_id, args.reason))
        elif args.command == "release-retry":
            from codex_harness.application.release_queue import ReleaseQueue
            emit(ReleaseQueue(service.store).retry(args.release_id, args.reason))
        elif args.command == "seed-research-backlog":
            from codex_harness.adapters.artifacts import FileArtifacts
            from codex_harness.application.research import ResearchAudits

            audits = ResearchAudits(service.store, None, FileArtifacts(args.artifacts),
                                    Workflow(service.store, service.org))
            records = audits.seed_backlog()
            emit([{k: r[k] for k in ("id", "repository", "priority", "status", "activation",
                                     "reviewed_paths")} for r in records])
        elif args.command == "doctor":
            with service.store.transaction() as tx:
                hooks = tx.scan("hooks")
            emit({"postgres": True, "redis": RedisBus(redis_url()).client.ping(),
                  "organization_valid": True, "hooks": len(hooks),
                  "active_hooks": sum(h["status"] == "active" for h in hooks)})
        elif args.command == "status":
            with service.store.transaction() as tx:
                tasks = tx.scan("tasks")
                decisions = tx.scan("decisions_pending")
                terminal = [task for task in tasks if task["status"] in {"succeeded", "failed", "expired"}]
                emit({"policy": POLICY.snapshot(), "tasks": {state: sum(t["status"] == state for t in tasks)
                      for state in sorted({t["status"] for t in tasks})},
                      "observed_task_success_rate": sum(t["status"] == "succeeded" for t in terminal) / len(terminal) if terminal else None,
                      "sample_size": len(terminal), "active_deployment": tx.get("deployment", "active"),
                      "health": tx.get("health", "latest"),
                      "blocked_decisions": [{"id": d["id"], "actor": d["actor"], "result": d.get("result")}
                                            for d in decisions if d["status"] in {"failed", "blocked"}],
                      "pending_hooks": [{"id": h["id"], "status": h["status"]} for h in tx.scan("hooks") if h["status"] != "active"]})
        elif args.command == "cleanup":
            from codex_harness.adapters.maintenance import ArtifactMaintenance

            executor = build_executor(service)
            emit(ArtifactMaintenance(service.store, executor.artifacts).collect(apply=args.apply))
        elif args.command == "ticket":
            ticket_command(service, args)
        elif args.command == "cycle":
            cycle_command(service, args)
        elif args.command == "operate":
            operate_command(service, args)
        elif args.command == "dge":
            dge_command(service, args)
        elif args.command == "autonomous":
            autonomous_command(service, args)
        elif args.command == "fleet":
            fleet_command(service, args)
        elif args.command == "host-delivery":
            host_delivery_command(service, args)
        elif args.command == "worker-session":
            worker_session_command(service, args)
        elif args.command == "continuation":
            continuation_command(service, args)
        elif args.command == "desk":
            desk_command(service, args)
        elif args.command == "audit-service":
            audit_service_command(service, args)
        elif args.command == "audit-repair":
            audit_repair_command(service, args)
        elif args.command == "research-program":
            research_program_command(service, args)
        elif args.command == "decision-feedback":
            decision_feedback_command(service, args)
        elif args.command == "observe":
            observe_command(service, args)
        elif args.command == "demo":
            emit(demo(service, args.scope))
        elif args.command == "incident":
            emit(service.record_incident(validate_message(json.loads(Path(args.file).read_text(encoding="utf-8")))))
        elif args.command == "flush":
            observer = build_observer(service.store, "cli.flush")
            emit(service.flush_outbox(RedisBus(redis_url()), audit=observer.audit_system))
            observer.close()
        elif args.command == "send":
            message = validate_message(json.loads(Path(args.file).read_text(encoding="utf-8")))
            service.org.authorize(message)
            emit({"stream_id": RedisBus(redis_url()).publish(message)})
        elif args.command == "run-command":
            argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
            require(bool(argv), "Command argv required after --")
            command = service.prepare_command(argv, "windows" if os.name == "nt" else "linux")
            result = run_process(command, timeout=args.timeout)
            emit({"argv": command, "exit_code": result.returncode, "stdout": result.stdout,
                  "stderr": result.stderr})
            if result.returncode:
                raise SystemExit(result.returncode)
        elif args.command == "serve":
            serve(service, args.agent, args.once, args.execute)
        elif args.command == "research":
            executor = build_executor(service)
            message = envelope("task.assign", "lead:research", "worker:" + args.source, "research",
                               {"source": args.source}, "research:" + str(uuid4()))
            message["where"]["revision"] = executor.git._git("rev-parse", "HEAD")
            emit({"message": message, "stream_id": RedisBus(redis_url()).publish(message)})
        elif args.command == "improve":
            executor = build_executor(service)
            details = {"objective": args.objective, "acceptance_criteria": args.acceptance}
            if args.importance is not None:
                details["importance"] = args.importance
            message = envelope("task.assign", "conductor", "lead:improvement", "plan", details,
                               "improvement:" + str(uuid4()))
            message["where"]["revision"] = executor.git._git("rev-parse", "HEAD")
            message["how"]["acceptance_criteria"] = args.acceptance
            emit({"message_id": message["message_id"], "correlation_id": message["correlation_id"],
                  "stream_id": RedisBus(redis_url()).publish(message)})
        elif args.command == "execute-one":
            observer = build_observer(service.store, "cli.execute-one", args.agent)
            executor = build_executor(service, observer=observer)
            emit(executor.execute_one(args.agent) or executor.decide_one(args.agent) or {"status": "idle"})
            service.flush_outbox(RedisBus(redis_url()), audit=observer.audit_system)
            observer.close()
        elif args.command == "cancel":
            Workflow(service.store, service.org).cancel(args.task_id, "conductor", args.reason)
            emit({"cancelled": args.task_id})
        elif args.command == "rebase":
            executor = build_executor(service)
            revision = executor.git._git("rev-parse", "--verify", args.onto + "^{commit}")
            emit(executor.workflow.request_rebase(args.task_id, revision))
            service.flush_outbox(RedisBus(redis_url()))
        elif args.command == "artifact":
            artifacts = build_executor(service).artifacts
            emit(artifacts.search(args.reference, args.search) if args.search
                 else artifacts.read(args.reference, args.start, args.length))
        elif args.command == "index":
            emit(PostgresKnowledge(database_url()).index_python(args.root))
        elif args.command == "query":
            knowledge = PostgresKnowledge(database_url())
            if args.semantic:
                from codex_harness.adapters.embeddings import LocalEmbeddings

                emit(knowledge.hybrid_query(args.text, LocalEmbeddings(".runtime/models")))
            else:
                emit(knowledge.query(args.text))
        elif args.command == "embed":
            from codex_harness.adapters.embeddings import LocalEmbeddings

            emit(PostgresKnowledge(database_url()).embed_missing(LocalEmbeddings(".runtime/models"), args.limit))
        elif args.command == "project-graph":
            emit(PostgresKnowledge(database_url()).project_runtime(service.store, service.org))
        elif args.command == "rlm":
            from functools import partial
            from types import SimpleNamespace

            from codex_harness.adapters.app_server import AppServer
            from codex_harness.adapters.hooks import NativeHooks
            from codex_harness.application.rlm import RecursiveContext
            from codex_harness.domain.model_routing import select_model

            executor = build_executor(service)
            with AppServer(hooks=NativeHooks(service, executor.git, executor.artifacts).configuration()) as runtime:
                selected = SimpleNamespace(run=partial(runtime.run, model=select_model('design').requested_model))
                rlm = RecursiveContext(executor.artifacts, selected, str(executor.git.repository),
                                       max_calls=args.max_calls)
                emit(rlm.analyze(args.reference, args.question))
        elif args.command == "context":
            actor = service.org.actor(args.agent)
            hits = PostgresKnowledge(database_url()).query(args.query)
            items = [ContextItem(h["id"], h["body"], h["source_ref"], h["revision"]) for h in hits]
            snapshot = digest(sorted({h["properties"].get("snapshot", h["revision"]) for h in hits}))
            packet = compile_context(actor.id, "query:" + args.query, snapshot,
                                     {"role": actor.role, "objective": args.query,
                                      "acceptance_criteria": ["Return grounded evidence"],
                                      "policy": "bootstrap-v1"}, items, args.budget, 2000)
            emit(asdict(packet))
        elif args.command == "inspect":
            with service.store.transaction() as tx:
                emit(tx.scan(args.bucket))
        elif args.command == "rollback-hook":
            service.rollback(args.hook_id, args.reason)
            emit({"rolled_back": args.hook_id})
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
