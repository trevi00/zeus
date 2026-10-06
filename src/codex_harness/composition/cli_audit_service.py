"""The `zeus audit-service` composition: the revision, the runner wiring and the host-owned run (S10 unit C6b, R-c25).

Layer: composition
Owns: current_revision, build_runner, run_service
Does not own: the argument shape and the command bodies (entry.cli.audit_service), the runner and the run gate (coordination.application.audit_service) and the executor, observer and repair wiring (composition.operation, composition.observation, composition.audit_repair)
Entry points: current_revision, build_runner, run_service
Contracts: INV-AUDIT-SERVICE-001

Moved from M7 `adapters/audit_service.py` (SOURCE e38aa722) by owner rule R-c25: `current_revision` is :266-271 (configuration from `composition.configuration`, `GitWorkspace`
from `host_os.adapters.git_workspace`), `build_runner` is :863-886 and `run_service` is `run` :889-937 (the host lock, the signal handlers and the observer: `filelock` is
allowed in composition, not in entry). The bodies are M7's except the imports and `build_runner`'s collaborators: `build_executor` is `composition.operation.build_executor`,
`build_observer` and `build_collector` are `composition.observation`, `redis_url` is `composition.redis_url`, `RedisBus` is `composition.cli_bus.bus()` (which supplies
the namespace M7's bus read itself, R-c8), `Workflow(store, org)` is `composition.cli.workflow(service)`, `FileArtifacts` is `storage.adapters.file_artifacts`,
`build_repair` is `composition.audit_repair.build_repair` (C7a), `AuditProgress` is `research.application.audit_progress` with intake's `ProgressCandidates` as its `investigations` port (M7's `AuditProgress` read the candidate row itself; the target's takes the keyword-only port, as `tests/ported/m7_research.AuditProgress` wires it) and the named change V-c25: the research scheduler
`research.application.scheduling.schedule_audits` is injected here as `schedule=`.
Imports sit inside the functions, so importing this module stays light.
"""


def current_revision() -> str:
    """The revision of THIS repository checkout, read with git argv through the existing workspace."""
    from codex_harness.composition.configuration import repository_root, runtime_dir
    from codex_harness.host_os.adapters.git_workspace import GitWorkspace

    return GitWorkspace(str(repository_root()), str(runtime_dir() / "workspaces"))._git("rev-parse", "HEAD")


def build_runner(service, args, observer, gate: dict):
    """Wire the real services around an ALREADY built observer, so the caller can release it even
    when this wiring fails. The executor is the existing one, with its existing audit runner, and
    the goal-progress observer reads the same store and the same host artifact root - it starts no
    process, enters no provider and owns no scheduler of its own."""
    from codex_harness.composition import cli
    from codex_harness.composition.audit_repair import build_repair
    from codex_harness.composition.cli_bus import bus
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.composition.observation import build_collector
    from codex_harness.composition.operation import build_executor
    from codex_harness.coordination.application.audit_service import AuditServiceRunner
    from codex_harness.intake.application.progress_candidates import ProgressCandidates
    from codex_harness.research.application.audit_progress import AuditProgress
    from codex_harness.research.application.scheduling import schedule_audits
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    executor = build_executor(service, observer=observer)
    artifacts = FileArtifacts(str(runtime_dir() / "artifacts"))
    progress = AuditProgress(service.store, artifacts, investigations=ProgressCandidates())
    # The repair owner reads the same store and the same host artifact root. It admits nothing
    # unless the operator durably enabled THIS audit through `zeus audit-repair enable`.
    return AuditServiceRunner(service, args.audit_id, executor=executor, bus=bus(),
                              workflow=cli.workflow(service), observer=observer,
                              collector=build_collector(service.store, observer), progress=progress,
                              repair=build_repair(service, artifacts),
                              max_tasks=args.max_tasks, revision=gate["revision"],
                              release_id=gate["release_id"], partitions=gate["partitions"],
                              schedule=schedule_audits)


def run_service(service, args) -> dict:
    """One host owner per configured runtime. The lock and the read-only activation gate come
    first: a duplicate owner, an inactive or stale activation and a foreign revision all return
    before an observer, an executor, a transport or any provider exists."""
    import signal
    from contextlib import suppress

    from filelock import FileLock, Timeout

    from codex_harness.composition.cli_audit_service import build_runner, current_revision
    from codex_harness.composition.configuration import runtime_dir
    from codex_harness.composition.observation import build_observer
    from codex_harness.coordination.application.audit_service import ACTION, AGENT, activation

    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(runtime / "audit-service.lock"), timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return {"status": "refused", "reason_code": "audit_service_lock_busy", "exit_code": 1}
    observer = None
    installed = []  # (signal, previous handler) for each handler THIS run replaced
    try:
        gate = activation(service.store, service.org, args.audit_id, current_revision())
        observer = build_observer(service.store, "cli.audit-service", role=AGENT)
        runner = build_runner(service, args, observer, gate)
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                # Graceful stop: no new assignment is bound; existing process-tree ownership
                # handles children and nothing lost is restarted here.
                number = getattr(signal, name)
                installed.append((number, signal.signal(number, lambda *_: runner.stop())))
        summary = runner.run(once=bool(args.once))
    finally:
        # The handlers close over this run's runner: every exit, including an exception and a
        # partial installation, hands the process its previous handlers back.
        for number, previous in reversed(installed):
            with suppress(Exception):  # a restore failure never replaces the original outcome
                signal.signal(number, previous)
        if observer is not None:
            with suppress(Exception):  # a close failure never replaces the original outcome
                observer.close()
        lock.release()
    # The gate's own reads win over the runner's constructor values: the receipt reports what the
    # store actually said about the activation this run was admitted under.
    # `service_stopped` is the operator's own interrupt observed at an admission point, exactly the
    # stop a signal between two ticks already exits 0 with; it is a shutdown, not a failed run.
    return {"audit_service": ACTION, **summary, **gate,
            "exit_code": 1 if summary["stop_reason"] not in
            (None, "max_tasks_reached", "service_stopped") else 0}
