"""Docker-host supervision, wake-on-message and release recovery without an LLM."""
import argparse
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from codex_harness.adapters.bus import RedisBus
from codex_harness.adapters.commands import run_process
from codex_harness.adapters.configuration import (
    codex_auth,
    compose_environment,
    repository_root,
    runtime_dir,
    select_repository,
)
from codex_harness.adapters.deployment import ReleaseRunner
from codex_harness.adapters.embeddings import LocalEmbeddings
from codex_harness.adapters.maintenance import ArtifactMaintenance
from codex_harness.adapters.verification import VerificationServices
from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.scheduling import schedule_research
from codex_harness.bootstrap import build, build_executor, redis_url
from codex_harness.domain.model import ContractError, utcnow
from codex_harness.domain.policy import POLICY

TARGETS = {"conductor": "conductor", "lead:research": "research-lead",
           "lead:improvement": "improvement-lead", "worker:implementation": "implementation-worker",
           "worker:github": "github-worker", "worker:geeknews": "geeknews-worker"}
release_thread = None
source_thread = None
maintenance_thread = None
last_maintenance = 0
last_collection = 0


def refresh_embeddings(service, executor, runtime):
    """Optional network/model work has a separate lifetime from task dispatch."""
    status = {"id": "embeddings", "at": utcnow()}
    try:
        executor.knowledge.embed_missing(LocalEmbeddings(str(runtime / "models")), limit=200)
        status["status"] = "healthy"
    except Exception as exc:
        status.update(status="failed", error_type=type(exc).__name__)
    with service.store.transaction() as tx:
        tx.put("health", "embeddings", status)


def maintain_views(service, executor, bus, root, runtime):
    """INV-GRAPH-001: derived-data failures cannot stop the authoritative work queue."""
    global last_collection

    def graph():
        revision = executor.git._git("rev-parse", "HEAD")
        with service.store.transaction() as tx:
            indexed = tx.get("graph_index", "main")
        if not indexed or indexed["revision"] != revision:
            index = executor.knowledge.index_python(str(root))
            with service.store.transaction() as tx:
                tx.put("graph_index", "main", {"id": "main", "revision": revision, **index})
        executor.knowledge.project_runtime(service.store, service.org)

    def collect():
        global last_collection
        if time.monotonic() - last_collection >= 86400:
            result = ArtifactMaintenance(service.store, executor.artifacts).collect(apply=True)
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
            tx.put("health", name, {"id": name, "at": utcnow(), **status})
    refresh_embeddings(service, executor, runtime)


def deploy_queued(service, executor):
    queue = ReleaseQueue(service.store)
    claim = queue.claim()
    if not claim:
        return
    runner = ReleaseRunner(service, executor.git, executor.artifacts,
                           str(codex_auth()), fence=lambda: queue.heartbeat(claim))
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


def tick(research=False, releases=False):
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
    bus = RedisBus(redis_url())
    if research:
        schedule_research(service)
    service.flush_outbox(bus)
    now = datetime.now(timezone.utc)
    with service.store.transaction() as tx:
        tasks = tx.scan("tasks") + tx.scan("decisions_pending")
        active = tx.get("deployment", "active")
        image = tx.get("images", active["release_id"]) if active else None
    desired = image["image"] if image else "zeus:bootstrap"
    if source_thread is None or not source_thread.is_alive():
        from codex_harness.adapters.artifacts import FileArtifacts
        from codex_harness.adapters.source_execution import DockerSourceRunner
        from codex_harness.application.workflow import Workflow
        runner = DockerSourceRunner(runtime / 'source-executions',
                                    FileArtifacts(runtime / 'artifacts'))
        source_thread = threading.Thread(target=runner.run_one,
            args=(Workflow(service.store, service.org),), daemon=True)
        source_thread.start()
    if time.monotonic() - last_maintenance >= 60:
        executor = build_executor(service)
        health = ReleaseRunner(service, executor.git, executor.artifacts,
                               str(codex_auth())).monitor()
        if health["status"] == "rolled_back":
            with service.store.transaction() as tx:
                image = tx.get("images", health["active"]["release_id"])
                desired = image["image"]
        with service.store.transaction() as tx:
            tx.put("health", "latest", {"id": "latest", "at": utcnow(), **health})
        last_maintenance = time.monotonic()
        if maintenance_thread is None or not maintenance_thread.is_alive():
            maintenance_thread = threading.Thread(target=maintain_views,
                args=(service, executor, bus, root, runtime), daemon=True)
            maintenance_thread.start()
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
        row = services.get(name, {})
        running = row.get("State") == "running"
        replace = running and row.get("Image") != desired and not busy
        if (not running and (backlog or ready)) or replace:
            result = run_process(["docker", "compose", "--profile", "agents", "--profile", "workers",
                                  "up", "-d", "--no-build", name], cwd=str(root), timeout=60,
                                 env={**compose_env, "HARNESS_AGENT_IMAGE": desired, "ZEUS_AGENT_IMAGE": desired})
            if result.returncode:
                raise RuntimeError(result.stderr)
            print(json.dumps({"woken": agent, "queued": backlog, "durable_tasks": ready,
                              "image": desired}), flush=True)
            if replace:
                break
    if releases and (release_thread is None or not release_thread.is_alive()):
        release_thread = threading.Thread(target=deploy_queued, args=(service, build_executor(service)), daemon=True)
        release_thread.start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--research", action="store_true")
    parser.add_argument("--releases", action="store_true")
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args()
    if args.repository:
        select_repository(args.repository)
    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(runtime / "supervisor.lock"), timeout=0):
            while True:
                failed = False
                try:
                    tick(args.research, args.releases)
                except Exception as exc:
                    failed = True
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


if __name__ == "__main__":
    main()
