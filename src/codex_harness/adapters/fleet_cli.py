"""Fleet CLI wiring: backlog uses existing admission; explicit owner recovery commands
retain their existing evidence, pause and authorization gates. No new executor or authority.
Contracts: INV-FLEET-001 and INV-FLEET-BACKLOG-001.
"""
from __future__ import annotations

import signal
from pathlib import Path

from codex_harness.adapters.operation_cli import GitSource, bind_goal, read_manifest, refusal
from codex_harness.adapters.providers import packaged_policy
from codex_harness.application.fleet import BUCKET_JOBS, Fleet, FleetRunner
from codex_harness.domain.fleet import FleetRefused, lane_of, validate_config
from codex_harness.domain.fleet_recovery import (
    validate_recovery_evidence,
    validate_relocation_request,
)
from codex_harness.domain.operation import validate_manifest
from codex_harness.domain.usage_policy import MODES

__all__ = ["add_parser", "execute", "refusal"]


def add_parser(commands) -> None:
    fleet = commands.add_parser("fleet", help="Bounded multi-lane admission of operation manifests; no conductor")
    sub = fleet.add_subparsers(dest="fleet_command", required=True)
    register = sub.add_parser("register", help="Register the one host fleet configuration (urn:zeus:fleet:1)")
    register.add_argument("--file", type=Path, required=True)
    enqueue = sub.add_parser("enqueue", help="Queue one validated operation manifest on a lane")
    enqueue.add_argument("--lane", required=True)
    enqueue.add_argument("--file", type=Path, required=True, help="Operation manifest JSON")
    enqueue.add_argument("--after", action="append", default=[], help="Job id that must be accepted first; repeatable")
    run = sub.add_parser("run", help="Admit and dispatch queued jobs up to max_parallel")
    run.add_argument("--once", action="store_true", help="Drain runnable work, then exit")
    sub.add_parser("pause", help="Stop new admissions; running work finishes")
    sub.add_parser("resume", help="Allow new admissions again")
    grant = sub.add_parser("authorize-budget", help="Operator grant of higher effective ceilings; idle fleet only")
    grant.add_argument("--per-host", type=int, required=True, dest="per_host")
    grant.add_argument("--total", type=int, required=True)
    grant.add_argument("--expected-total", type=int, required=True, dest="expected_total",
                       help="The current effective total; refused when it no longer matches")
    grant.add_argument("--mode", choices=list(MODES), default=None,
                       help="Accounting mode for new work: finite (numbers are ceilings) or subscription "
                            "(every call recorded, numbers retained as migration metadata); omitted keeps the current mode")
    delivery = sub.add_parser("record-delivery", help="Record the owner's merge/deploy evidence for an "
                              "accepted job (urn:zeus:owner-delivery:1); trusted owner CLI only")
    delivery.add_argument("--job", required=True, help="Existing accepted fleet job id")
    delivery.add_argument("--file", type=Path, required=True, help="Owner delivery document JSON")
    reconcile = sub.add_parser("reconcile-interrupted", help="Settle one interrupted job from proven-dead "
                               "evidence (urn:zeus:fleet-recovery-evidence:1); paused fleet, owner CLI only")
    reconcile.add_argument("--file", type=Path, required=True, help="Owner recovery evidence document JSON")
    reconcile.add_argument("--docker", default="docker", help="Docker client used to inspect the named container")
    relocate = sub.add_parser("relocate", help="Move lane repository/runtime paths to verified copies "
                              "(urn:zeus:fleet-relocation:1); paused, idle fleet, owner CLI only")
    relocate.add_argument("--file", type=Path, required=True, help="Owner relocation request document JSON")
    relocate.add_argument("--journal", type=Path, required=True,
                          help="Service lifecycle journal of the Fleet CLI; the runner must be stopped in it")
    relocate.add_argument("--docker", default="docker", help="Docker client used to inspect retained lane runs")
    sub.add_parser("status", help="Read the fleet projection; store read only")
    backlog = sub.add_parser("backlog", help="Approved Git-pinned backlog: register, tick, status")
    backlog_sub = backlog.add_subparsers(dest="backlog_command", required=True)
    backlog_register = backlog_sub.add_parser("register", help="Register one owner-approved plan read at a commit")
    backlog_register.add_argument("--lane", required=True, help="Lane whose repository holds the plan")
    backlog_register.add_argument("--revision", required=True, help="40-hex commit the plan is read at")
    backlog_register.add_argument("--path", required=True, help="Repository-relative plan path")
    backlog_tick = backlog_sub.add_parser("tick", help="Select and admit at most one eligible successor")
    backlog_tick.add_argument("--plan", required=True, help="Registered plan id")
    backlog_status = backlog_sub.add_parser("status", help="Read the backlog projection; store read only")
    backlog_status.add_argument("--plan", default=None, help="One plan id; omitted reads every registered plan")


def _resolved(read):
    """One store input, read on the FIRST observation and reused on the re-read.

    Both owner commands hand `Fleet` an observation callback that `Fleet` calls a second time from
    INSIDE its committing transaction. `PostgresStore.transaction` opens its own connection and takes
    advisory lock 734219 for every transaction, so a callback that reads the primary store there
    waits for a lock the same call already holds and fails with `LockNotAvailable` when
    `lock_timeout` expires; `MemoryStore`'s reentrant lock hid that boundary, and the first real
    owner recovery rolled back on it. The immutable registry, lane and job rows an observation needs
    are therefore resolved once, while `Fleet` is still outside its transaction, and reused on the
    re-read - nothing about the store is read from inside the commit, and no lock, timeout or
    compare-and-swap is relaxed to allow it.

    Every EXTERNAL fact stays freshly observed on both reads: the lane schema, the Docker daemon, the
    service journal and the copied files are read again, so state that changed between the two
    observations still refuses before the commit. The callback itself is lazy, so a request the
    committed receipt already answers reads nothing at all.
    """
    cache = []

    def resolved():
        if not cache:
            cache.append(read())
        return cache[0]

    return resolved


def check_resolved(config: dict) -> dict:
    """Adapter-side filesystem facts the grammar cannot know: each path is its own resolution and
    every repository is an existing directory. Runtime roots may not exist yet."""
    for index, lane in enumerate(config["lanes"]):
        for key in ("repository", "runtime"):
            path = Path(lane[key])
            if path.resolve() != path:
                raise FleetRefused("path_unresolved", "lanes[" + str(index) + "]." + key)
        if not Path(lane["repository"]).is_dir():
            raise FleetRefused("repository_missing", "lanes[" + str(index) + "].repository")
    return config


def register(service, args) -> dict:
    config = check_resolved(validate_config(read_manifest(args.file)))
    return {**Fleet(service.store).register(config), "exit_code": 0}


def enqueue(service, args) -> dict:
    fleet = Fleet(service.store)
    lane = lane_of(fleet.registered()["config"], args.lane)
    manifest = validate_manifest(read_manifest(args.file), packaged_policy())
    # The goal is bound at the configured lane repository, never at the current directory.
    goal = bind_goal(manifest, GitSource(lane["repository"]))
    return {**fleet.enqueue(args.lane, manifest, goal, args.after), "exit_code": 0}


def run(service, args) -> dict:
    from codex_harness.adapters.configuration import settings
    from codex_harness.adapters.fleet_backlog import backlog_ticker, configured_plan
    from codex_harness.adapters.fleet_runtime import LaneLauncher
    from codex_harness.adapters.portfolio import portfolio_reconciler

    fleet = Fleet(service.store)
    config = fleet.registered()["config"]
    host = settings()
    # Opt-in only (INV-FLEET-BACKLOG-001): without the host plan setting the runner keeps its exact
    # previous behaviour, never selects work of its own and builds no observer.
    plan_id = configured_plan(host)
    backlog_tick = None
    if plan_id is not None:
        from codex_harness.bootstrap import build_observer

        # The durable process observer of the configured continuous loop: the backlog's fixed
        # admission, refusal, conflict, unavailability and recovery transitions are collected as
        # structured observations, not only as log lines.
        backlog_tick = backlog_ticker(service.store, config, plan_id,
                                      observer=build_observer(service.store, "fleet-backlog"))
    # The bounded portfolio pass is wired here, in the adapter: the runner keeps no portfolio
    # dependency and a reconciliation outage never blocks admission (operating-portfolio-001).
    runner = FleetRunner(fleet, LaneLauncher(config, host), reconcile=portfolio_reconciler(service.store),
                         backlog=backlog_tick)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            # Graceful stop: admission closes, owned children are drained, nothing is killed.
            signal.signal(getattr(signal, name), lambda *_: runner.stop())
    return {**runner.run(once=bool(args.once)), "exit_code": 0}


def record_delivery(service, args) -> dict:
    """The owner states what they verified from a preserved receipt. This CLI is the only writer:
    no web request and no model run records a delivery, and recording one changes no job status."""
    document = read_manifest(args.file)
    return {**Fleet(service.store).record_delivery(args.job, document), "exit_code": 0}


def reconcile_interrupted(service, args) -> dict:
    """Owner recovery of ONE interrupted job. The evidence document says what the owner proved; the
    adapter observes the lane store, Docker and the machine ledger itself and re-reads that
    observation inside the committing transaction. No model is called and no work is resumed.

    The observation is a callback, not a value: `Fleet.reconcile_interrupted` answers an identical
    replay from the committed receipt, and this command then reads no lane schema, no Docker daemon
    and no call ledger at all, so a settled recovery survives the removal of what it settled.

    The lane the observation reads is resolved once, outside the application's transaction (see
    `_resolved`); the lane store, Docker and the call ledger are read again on the re-read."""
    evidence = validate_recovery_evidence(read_manifest(args.file))
    fleet = Fleet(service.store)

    def pinned_lane() -> dict:
        """The lane this evidence names, taken from the registry the evidence expects.

        Pinning the digest here binds the observed lane to the exact configuration
        `Fleet.reconcile_interrupted` compares against under its own transaction: the schema and
        runtime that were read cannot belong to some other configuration that the commit's
        `config_expected_mismatch` check would then accept as the expected one."""
        registry = fleet.registered()
        if registry["config_sha256"] != evidence["expected"]["config_sha256"]:
            raise FleetRefused("config_expected_mismatch", "expected.config_sha256")
        return lane_of(registry["config"], evidence["expected"]["lane"])

    lane = _resolved(pinned_lane)

    def observe() -> dict:
        from codex_harness.adapters.configuration import settings
        from codex_harness.adapters.fleet_recovery import (
            LaneReader,
            collect_recovery_proof,
            docker_state,
        )
        from codex_harness.adapters.fleet_runtime import lane_dsn

        target = lane()
        reader = LaneReader(lane_dsn(settings().get("HARNESS_DATABASE_URL"), target["schema"]), target["schema"])
        return collect_recovery_proof(evidence, target, reader=reader,
                                      state=lambda container: docker_state(container, args.docker))

    return {**fleet.reconcile_interrupted(evidence, observe=observe, reread=observe), "exit_code": 0}


def relocate(service, args) -> dict:
    """Owner relocation of lane repository/runtime paths to already-copied, verified targets. The
    copy itself is the owner's preparation step: nothing here moves, deletes or rewrites files,
    history, manifests or goal identities.

    The observation is a callback, not a value: `Fleet.relocate` answers an identical replay from
    the committed receipt, and this command then reads no journal, no checkout, no Docker daemon
    and no copied file, so a completed cutover replays even once the old paths are gone.

    The configuration and job rows the observation needs are resolved once, outside the application's
    transaction (see `_resolved`); the journal, the checkouts, Docker and the copied files are read
    again on the re-read, and the queued denominator the proof is judged against is the one the
    commit reads for itself."""
    request = validate_relocation_request(read_manifest(args.file))
    fleet = Fleet(service.store)

    def pinned_inputs() -> tuple[dict, list]:
        """The expected configuration and the job rows, read before the application's commit.

        The digest is pinned for the same reason as in the recovery command; the job rows are only
        the queued bindings this observation must look for, and `Fleet.relocate` still recomputes
        the queued denominator inside its transaction and refuses a proof that does not cover
        exactly that set, so rows that changed in between cannot commit."""
        registry = fleet.registered()
        if registry["config_sha256"] != request["expected_config_sha256"]:
            raise FleetRefused("config_expected_mismatch", "expected_config_sha256")
        with service.store.transaction() as tx:
            jobs = tx.scan(BUCKET_JOBS)
        return registry["config"], jobs

    inputs = _resolved(pinned_inputs)

    def observe() -> dict:
        from codex_harness.adapters.fleet_recovery import collect_relocation_proof, docker_state

        config, jobs = inputs()
        return collect_relocation_proof(request, config, jobs, journal=args.journal,
                                        state=lambda container: docker_state(container, args.docker))

    return {**fleet.relocate(request, observe=observe, reread=observe), "exit_code": 0}


def status(service, args) -> dict:
    # Store read only: no executor, observer, bus, budget or provider is built.
    fleet = Fleet(service.store)
    return {**fleet.status(), "reconciliation_required": fleet.reconciliation_required(), "exit_code": 0}


def backlog(service, args) -> dict:
    """`zeus fleet backlog register|tick|status`. Git reads and manifest validation happen in the
    adapter, outside every store transaction; admission itself is the unchanged `Fleet.enqueue`."""
    from codex_harness.adapters.fleet_backlog import register_plan, tick_plan
    from codex_harness.application.fleet_backlog import FleetBacklog
    from codex_harness.domain.fleet_backlog import FAILED_OUTCOMES

    command = args.backlog_command
    if command == "register":
        config = Fleet(service.store).registered()["config"]
        return {**register_plan(service.store, config, args.lane, args.revision, args.path), "exit_code": 0}
    if command == "tick":
        config = Fleet(service.store).registered()["config"]
        result = tick_plan(service.store, config, args.plan)
        return {**result, "exit_code": 1 if result["outcome"] in FAILED_OUTCOMES else 0}
    plan_id = getattr(args, "plan", None)
    projection = FleetBacklog(service.store).status(plan_id)
    # A named plan that is not registered is a refusal; listing every plan is a successful read
    # even when nothing is registered yet.
    return {**projection, "exit_code": 1 if plan_id is not None and not projection["registered"] else 0}


def execute(service, args) -> dict:
    command = args.fleet_command
    if command == "register":
        return register(service, args)
    if command == "enqueue":
        return enqueue(service, args)
    if command == "run":
        return run(service, args)
    if command == "pause":
        return {**Fleet(service.store).pause(), "exit_code": 0}
    if command == "resume":
        return {**Fleet(service.store).resume(), "exit_code": 0}
    if command == "record-delivery":
        return record_delivery(service, args)
    if command == "backlog":
        return backlog(service, args)
    if command == "reconcile-interrupted":
        return reconcile_interrupted(service, args)
    if command == "relocate":
        return relocate(service, args)
    if command == "authorize-budget":
        grant = Fleet(service.store).authorize_budget(args.per_host, args.total, args.expected_total,
                                                      mode=getattr(args, "mode", None))
        return {**grant, "exit_code": 0}
    return status(service, args)
