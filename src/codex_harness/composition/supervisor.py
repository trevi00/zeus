"""The `zeus-supervisor` process: docker-host supervision, wake-on-message and release recovery without an LLM (S10 unit E3, R-e3).

Layer: composition
Owns: TARGETS, tick, deploy_queued, maintain_views, refresh_embeddings, run, and the process-lifetime thread and timer globals
Does not own: the argument shape (entry.processes.supervisor), the executor, observer and bus builders (composition.operation, composition.observation, composition.cli_bus)
Entry points: run, tick
Contracts: INV-OBSERVATION-001, INV-GRAPH-001

Moved from M7 `supervisor.py` (SOURCE e38aa722) by rule R-e3: the bodies are M7's verbatim except that each name comes from its target home
(`RedisBus(redis_url())` is `composition.cli_bus.bus()`, which adds the namespace M7's bus read itself (R-c8); `service.flush_outbox(bus, audit=)`
is `composition.cli_bus.flusher(service).flush(bus, audit=)`; `ReleaseRunner(...)` is `composition.cli_executor.release_runner`, whose `fence`
M7 passed to the constructor is set on the runner (the runner reads `self.fence` at call time); `ReleaseQueue(store)`, `Workflow(store, org)`,
`ArtifactMaintenance(...)` are the `composition.cli` and `composition.cli_executor` builders; `DockerSourceRunner` gets the V18 ports
(`ChokepointProcesses`, `process_groups.run_process`, `classify_isolated_run`) as `composition.operation` wires its sibling `AuditRunner`; the
`schedule_research` ports (`Outbox`, `Releases.reconcile_audits`) are wired as `composition.operation.Executor` wires them). `run` is M7 `main()`
after `parse_args()`. The `graph_index` reads and writes are `knowledge.application.graph_index.GraphIndexState`. The `health` writes are `observation.application.health.HealthRecords.record` (the bucket's owner, as `composition.cli_bus.flusher` binds it).
The observer: `build_observer` returns the `CatalogCheckingObserver` wrapper; M7's `observer.store = service.store` assigned on the wrapper would
leave the wrapped `Observer.store` None (alerts would not persist), so the assignment reaches the wrapped observer.

Target methods every call here relies on (verified by grep at the unit's base): `RedisBus.stream/compact` and `.client` (storage/adapters/redis_bus.py:129,
210,106); `PostgresKnowledge.embed_missing/index_python/project_runtime` (knowledge/adapters/postgres_knowledge.py:200,129,156); `GitWorkspace._git`
(host_os/adapters/git_workspace.py:101); `ReleaseRunner.monitor/run` (delivery/adapters/deployment.py:700,292); `ReleaseQueue.claim/heartbeat/finish`
(review/application/release_queue.py:78,141,173); `DockerSourceRunner.run_one` (research/adapters/source_execution.py:184);
`ArtifactMaintenance.collect` (storage/adapters/maintenance.py:36); `VerificationServices.collect_stale` (host_os/adapters/verification.py:664);
`CatalogCheckingObserver.emit/audit_system/store` (observation/application/catalog_observer.py:43, `__getattr__`); `OutboxFlusher.flush`
(coordination/application/outbox_relay.py:428).
"""
import json
import sys
import threading
import time
from datetime import datetime, timezone

from filelock import FileLock, Timeout

from codex_harness.composition import build, cli, cli_bus, cli_executor
from codex_harness.composition.configuration import (
    compose_environment,
    repository_root,
    runtime_dir,
    select_repository,
)
from codex_harness.composition.observation import build_observer
from codex_harness.composition.operation import build_executor
from codex_harness.host_os.adapters.process_groups import run_process
from codex_harness.host_os.adapters.verification import VerificationServices
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.policy import POLICY
from codex_harness.knowledge.adapters.embeddings import LocalEmbeddings
from codex_harness.knowledge.application.graph_index import GraphIndexState
from codex_harness.observation.application.health import HealthRecords
from codex_harness.research.application.scheduling import schedule_research

TARGETS = {"conductor": "conductor", "lead:research": "research-lead",
           "lead:improvement": "improvement-lead", "worker:implementation": "implementation-worker",
           "worker:github": "github-worker", "worker:geeknews": "geeknews-worker"}
release_thread = None
source_thread = None
maintenance_thread = None
last_maintenance = 0
last_collection = 0


def _research_schedule(service):
    """`schedule_research(service)` with the ports `composition.operation.Executor` wires for its own `Releases` and `Outbox`."""
    from codex_harness.coordination.application.events import EventJournal
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.intake.application import tickets
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.research.application.hook_rollback import HookRollback
    from codex_harness.review.application.releases import Releases
    releases = Releases(service.store, service.org, ticket_binding=tickets.ticket_binding,
                        ticket_superseded=tickets.TicketSuperseded, events=EventJournal(), hooks=HookRollback(),
                        clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
    return schedule_research(service, outbox=Outbox(), reconcile_audits=releases.reconcile_audits)


def refresh_embeddings(service, executor, runtime):
    """Optional network/model work has a separate lifetime from task dispatch."""
    status = {"id": "embeddings", "at": utcnow()}
    try:
        executor.knowledge.embed_missing(LocalEmbeddings(str(runtime / "models")), limit=200)
        status["status"] = "healthy"
    except Exception as exc:
        status.update(status="failed", error_type=type(exc).__name__)
    with service.store.transaction() as tx:
        HealthRecords().record(tx, "embeddings", status)


def maintain_views(service, executor, bus, root, runtime):
    """INV-GRAPH-001: derived-data failures cannot stop the authoritative work queue."""
    global last_collection

    def graph():
        revision = executor.git._git("rev-parse", "HEAD")
        with service.store.transaction() as tx:
            indexed = GraphIndexState().indexed(tx)
        if not indexed or indexed["revision"] != revision:
            index = executor.knowledge.index_python(str(root))
            with service.store.transaction() as tx:
                GraphIndexState().record(tx, revision, index)
        executor.knowledge.project_runtime(service.store, service.org)

    def collect():
        global last_collection
        if time.monotonic() - last_collection >= 86400:
            result = cli_executor.artifact_maintenance(service, executor.artifacts).collect(apply=True)
            last_collection = time.monotonic()
            return result
        return {"status": "not_due"}

    jobs = [("stream-maintenance", lambda: sum(
        bus.compact(agent, POLICY.stream_retention_entries) for agent in TARGETS)),
        ("graph-index", graph), ("artifact-maintenance", collect),
        ("verification-cleanup", lambda: VerificationServices.collect_stale(runtime / "verification", executor.artifacts))]
    for name, action in jobs:
        try:
            result = action()
            status = {"status": "healthy", "result": result}
        except Exception as exc:
            status = {"status": "failed", "error_type": type(exc).__name__}
        with service.store.transaction() as tx:
            HealthRecords().record(tx, name, {"id": name, "at": utcnow(), **status})
    refresh_embeddings(service, executor, runtime)


def deploy_queued(service, executor):
    queue = cli.release_queue(service)
    claim = queue.claim()
    if not claim:
        return
    runner = cli_executor.release_runner(service, executor)
    runner.fence = lambda: queue.heartbeat(claim)
    try:
        result = runner.run(claim["id"])
    except ContractError as exc:
        result = {"status": "blocked", "reason": str(exc)}
    except Exception as exc:
        result = {"status": "retry", "reason": str(exc)}
    try:
        queue.finish(claim, result)
    except ContractError:
        result = {"status": "stale", "reason": "release controller ownership changed"}
    print(json.dumps({"release": claim["id"], "result": result}), flush=True)


def tick(research=False, releases=False, observer=None):
    global release_thread, source_thread, maintenance_thread, last_maintenance
    root, runtime = repository_root(), runtime_dir()
    compose_env = compose_environment()
    status = run_process(["docker", "compose", "ps", "--all", "--format", "json"],
                         cwd=str(root), timeout=20, env=compose_env)
    if status.returncode:
        raise RuntimeError(status.stderr)
    rows = [json.loads(line) for line in status.stdout.splitlines() if line.startswith("{")]
    services = {row["Service"]: row for row in rows}
    if any(services.get(name, {}).get("State") != "running" for name in ("postgres", "redis")):
        ready = run_process(["docker", "compose", "up", "-d", "--wait", "postgres", "redis"],
                            cwd=str(root), timeout=90, env=compose_env)
        if ready.returncode:
            raise RuntimeError(ready.stderr)
    service = build()
    # INV-OBSERVATION-001: supervisor decisions are operations-log system events (no task).
    observer = observer or build_observer(service.store, "supervisor")
    # The wrapper delegates reads; the store belongs on the wrapped observer (module docstring).
    sink = getattr(observer, "_observer", observer)
    if sink.store is None:
        sink.store = service.store
    bus = cli_bus.bus()
    if research:
        _research_schedule(service)
    cli_bus.flusher(service).flush(bus, audit=observer.audit_system)
    now = datetime.now(timezone.utc)
    with service.store.transaction() as tx:
        tasks = tx.scan("tasks") + tx.scan("decisions_pending")
        active = tx.get("deployment", "active")
        image = tx.get("images", active["release_id"]) if active else None
    desired = image["image"] if image else "zeus:bootstrap"
    if source_thread is None or not source_thread.is_alive():
        from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
        from codex_harness.research.adapters.source_execution import DockerSourceRunner
        from codex_harness.review.domain.check_results import classify_isolated_run
        from codex_harness.storage.adapters.file_artifacts import FileArtifacts
        runner = DockerSourceRunner(runtime / 'source-executions',
                                    FileArtifacts(runtime / 'artifacts'), processes=ChokepointProcesses(),
                                    run_process=run_process, classify=classify_isolated_run)
        source_thread = threading.Thread(target=runner.run_one,
            args=(cli.workflow(service),), daemon=True)
        source_thread.start()
    if time.monotonic() - last_maintenance >= 60:
        executor = build_executor(service)
        health = cli_executor.release_runner(service, executor).monitor()
        if health["status"] == "rolled_back":
            with service.store.transaction() as tx:
                image = tx.get("images", health["active"]["release_id"])
                desired = image["image"]
        with service.store.transaction() as tx:
            HealthRecords().record(tx, "latest", {"id": "latest", "at": utcnow(), **health})
        last_maintenance = time.monotonic()
        if maintenance_thread is None or not maintenance_thread.is_alive():
            maintenance_thread = threading.Thread(target=maintain_views,
                args=(service, executor, bus, root, runtime), daemon=True)
            maintenance_thread.start()
    backlog_total = 0
    for agent, name in TARGETS.items():
        agent_tasks = [row for row in tasks if row.get("agent", row.get("actor")) == agent]
        busy = any(row["status"] == "running" and datetime.fromisoformat(row["lease_until"]) > now
                   for row in agent_tasks)
        ready = any(row["status"] in {"queued", "pending", "retry"}
                    or (row["status"] == "running" and datetime.fromisoformat(row["lease_until"]) <= now)
                    for row in agent_tasks)
        key = bus.stream(agent)
        groups = bus.client.xinfo_groups(key) if bus.client.exists(key) else []
        backlog = (sum(g.get("pending", 0) + (g.get("lag") or 0) for g in groups)
                   if groups else bus.client.xlen(key))
        backlog_total += int(backlog)
        row = services.get(name, {})
        running = row.get("State") == "running"
        replace = running and row.get("Image") != desired and not busy
        observer.emit("operations.backlog_observed", "observed", severity="debug",
                      attributes={"agent": agent, "stream_backlog": int(backlog), "durable_ready": bool(ready),
                                  "busy": bool(busy), "running": bool(running)})
        if (not running and (backlog or ready)) or replace:
            if replace:
                observer.emit("operations.worker_replace_requested", "started",
                              attributes={"agent": agent, "service": name, "image_from": row.get("Image"),
                                          "image_to": desired})
            else:
                observer.emit("operations.worker_wake_requested", "started",
                              attributes={"agent": agent, "service": name, "image": desired,
                                          "stream_backlog": int(backlog), "durable_ready": bool(ready)})
            result = run_process(["docker", "compose", "--profile", "agents", "--profile", "workers",
                                  "up", "-d", "--no-build", name], cwd=str(root), timeout=60,
                                 env={**compose_env, "HARNESS_AGENT_IMAGE": desired, "ZEUS_AGENT_IMAGE": desired})
            if result.returncode:
                raise RuntimeError(result.stderr)
            print(json.dumps({"woken": agent, "queued": backlog, "durable_tasks": ready,
                              "image": desired}), flush=True)
            if replace:
                break
    observer.emit("operations.supervisor_tick", "observed", severity="debug",
                  attributes={"services_running": sum(1 for row in services.values() if row.get("State") == "running"),
                              "backlog_total": backlog_total, "desired_image": desired})
    if releases and (release_thread is None or not release_thread.is_alive()):
        release_thread = threading.Thread(target=deploy_queued, args=(service, build_executor(service)), daemon=True)
        release_thread.start()


def run(args):
    if args.repository:
        select_repository(args.repository)
    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    observer = None
    try:
        with FileLock(str(runtime / "supervisor.lock"), timeout=0):
            while True:
                failed = False
                try:
                    if observer is None:
                        observer = build_observer(None, "supervisor")
                        observer.emit("general.process_started", "started",
                                      attributes={"agent": None, "autonomous": True, "platform": sys.platform,
                                                  "python": sys.version.split()[0], "mode": "supervisor"})
                    tick(args.research, args.releases, observer)
                except Exception as exc:
                    failed = True
                    if observer is not None:
                        observer.emit("operations.supervisor_error", "failed", severity="error",
                                      reason_code=type(exc).__name__, attributes={"error_type": type(exc).__name__})
                    print(json.dumps({"supervisor_error": str(exc), "at": utcnow()}), flush=True)
                if args.once:
                    if release_thread:
                        release_thread.join()
                    if source_thread:
                        source_thread.join()
                    if failed:
                        raise SystemExit(1)
                    break
                time.sleep(5)
    except Timeout:
        print(json.dumps({"status": "supervisor_already_running"}), flush=True)
