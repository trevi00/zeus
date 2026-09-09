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
from codex_harness.bootstrap import build, build_executor, database_url, organization, redis_url
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


def serve(service, agent: str, once: bool, execute: bool = False) -> None:
    service.org.actor(agent)
    bus = RedisBus(redis_url())
    consumer = f"{agent}:{uuid4()}"
    last_activity = time.monotonic()
    workflow = Workflow(service.store, service.org)
    executor = build_executor(service) if execute else None
    prefer_decisions = True
    emit({"status": "listening", "agent_id": agent, "autonomous": execute})
    while True:
        row = bus.receive(agent, consumer)
        if row:
            entry_id, fields = row
            try:
                message = bus.decode(fields)
                require(message["who"]["recipient"] == agent, "Message routed to wrong agent")
                service.org.authorize(message)
                if message["type"] == "incident.report":
                    result = service.record_incident(message)
                else:
                    result = workflow.handle(message)
                service.flush_outbox(bus)
                bus.ack(agent, entry_id)
                emit({"message_id": message["message_id"], "result": result})
                last_activity = time.monotonic()
            except (ContractError, json.JSONDecodeError, KeyError) as exc:
                bus.dead_letter(agent, entry_id, fields, str(exc))
                emit({"rejected": entry_id, "reason": str(exc)})
        if executor:
            # Give both durable queues turns, even under a continuous task backlog.
            first, second = ((executor.decide_one, executor.execute_one) if prefer_decisions
                             else (executor.execute_one, executor.decide_one))
            result = first(agent) or second(agent)
            prefer_decisions = not prefer_decisions
            if result:
                emit({"execution": result})
                service.flush_outbox(bus)
                last_activity = time.monotonic()
        if once:
            break
        if time.monotonic() - last_activity >= POLICY.idle_seconds:
            emit({"status": "idle_exit", "agent": agent, "at": utcnow()})
            return


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
                                           "tasks", "decisions_pending", "releases", "deployment", "release_queue"])
    rollback = commands.add_parser("rollback-hook")
    rollback.add_argument("hook_id")
    rollback.add_argument("--reason", required=True)
    canary = commands.add_parser("canary")
    canary.add_argument("--live", action="store_true", help="Execute a real Codex file task (uses account quota)")
    ticket = commands.add_parser("ticket", help="Versioned review topics and explicit GitHub issue sync")
    ticket_commands = ticket.add_subparsers(dest="ticket_command", required=True)
    ticket_commands.add_parser("list")
    create = ticket_commands.add_parser("create")
    create.add_argument("--file", type=Path, required=True)
    create.add_argument("--author", default="operator")
    for name in ("show", "export", "update", "review", "dispatch", "sync", "pull", "evidence", "prepare-close", "close", "reopen"):
        sub = ticket_commands.add_parser(name)
        sub.add_argument("ticket_id")
        if name == "show":
            sub.add_argument("--revision", type=int)
        if name in {"update", "review", "dispatch"}:
            sub.add_argument("--revision", type=int, required=True)
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
        if name == "reopen":
            sub.add_argument("--revision", type=int, required=True)
            sub.add_argument("--sequence", type=int, required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--expected-state", choices=["closed", "open", "dispatched"], default="closed",
                             help="Use open/dispatched explicitly to reconcile a new external close")
    return p


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
        executor = build_executor(service)
        emit(tickets.dispatch(args.ticket_id, args.revision, executor.git._git("rev-parse", "HEAD")))
    elif command in {"evidence", "prepare-close", "close", "reopen"}:
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
        service = build()
        if args.command == "init-db":
            service.store.migrate()
            emit({"migrated": True})
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
        elif args.command == "demo":
            emit(demo(service, args.scope))
        elif args.command == "incident":
            emit(service.record_incident(validate_message(json.loads(Path(args.file).read_text(encoding="utf-8")))))
        elif args.command == "flush":
            emit({"published": service.flush_outbox(RedisBus(redis_url()))})
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
            executor = build_executor(service)
            emit(executor.execute_one(args.agent) or executor.decide_one(args.agent) or {"status": "idle"})
            service.flush_outbox(RedisBus(redis_url()))
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
