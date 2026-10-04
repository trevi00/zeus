"""The `zeus fleet` composition: the runner, the configuration check and the three owner recovery commands.

Layer: composition
Owns: run_fleet (M7 `fleet_cli.run`), reconcile_interrupted, migrate_host, relocate and the private _resolved
Does not own: the argument shape, the owner documents' read and the other command bodies (entry.cli.fleet), the backlog and continuation tickers (composition.fleet_backlog, composition.continuation), the lane launcher (composition.fleet) and the recovery collectors (composition.fleet_recovery)
Entry points: run_fleet, reconcile_interrupted, migrate_host, relocate
Contracts: INV-FLEET-001, INV-FLEET-BACKLOG-001, INV-CONTINUATION-001, INV-HOST-MIGRATION-001

Moved from M7 `adapters/fleet_cli.py` (SOURCE e38aa722) by named rule R-c28 (S10 unit C8b-2): `run` (:135-188) is `run_fleet`, `_resolved` (:80-105), `reconcile_interrupted` (:198-240), `migrate_host` (:243-273) and
`relocate` (:276-315) keep their bodies, because they need the lane launcher, the tickers and the fleet recovery adapters with the Docker and journal observations. The statements are M7's verbatim except the construction seams:
`settings()` is `composition.configuration.settings`, `LaneLauncher(config, host)` is `composition.fleet.lane_launcher(config, host)`, `build_observer` is `composition.observation`, the tickers are `composition.fleet_backlog` and
`composition.continuation`, `portfolio_reconciler` is `intake.adapters.portfolio`, `lane_dsn` is `coordination.adapters.fleet_runtime` and the recovery collectors are the target homes wired by `composition.fleet_recovery.collectors`
(`state` is `docker_state` over the Docker call; `budget` is `CallBudget()`, which M7's `collect_recovery_proof` built itself for `budget=None`, constructed inside the observation as M7 did).

M7's one `Fleet(store)` is the S5 split. Each method this module and `entry.cli.fleet` call is routed to the owner that `tests/ported/m7_coordination.Fleet` (its `ROUTES`) names:

    M7 Fleet method (call site)                                     split owner                                  class (coordination.application.fleet)
    register, enqueue, record_delivery (entry.cli.fleet)            registry                                     registry.FleetRegistry
    registered (run_fleet, enqueue, the recovery commands)          registry                                     registry.FleetRegistry
    status, reconciliation_required (entry.cli.fleet)               registry                                     registry.FleetRegistry
    pause, resume, authorize_budget (entry.cli.fleet)               pause                                        pause.FleetPause
    reconcile_interrupted, relocate, migrate_host                   recovery                                     recovery.FleetRecovery
    FleetRunner(fleet, ...) (run_fleet)                             registry, admission, pause (three objects)   runner.FleetRunner(registry, admission, pause, ...)

The three owner commands take the owner's document as a third argument: M7 read it with `read_manifest(args.file)` as their first statement, and `read_manifest` is `entry.cli.operation`'s, which composition may not
import, so `entry.cli.fleet` reads it first and hands it over (the same order: the read and the validation precede every other effect). `check_resolved` (:108-118) stays in `entry.cli.fleet`: it needs the domain and the
filesystem only. `admission` (`admit_one`, `reserve_unit`, `settle_unit`, `units`, `held_units`, `finalize`) is used by the runner only. Imports sit inside the functions, so importing this module stays light.
"""
from __future__ import annotations

import signal
from contextlib import suppress


def run_fleet(service, args, *, control=None) -> dict:
    """`zeus fleet run`. `control` is the optional descriptor-bound pause, stop and heartbeat of a
    managed host runtime (`composition.managed_runtime`); the CLI itself never passes one, so
    `zeus fleet run` keeps its exact previous behaviour."""
    from codex_harness.composition import continuation, fleet, fleet_backlog
    from codex_harness.composition.configuration import settings
    from codex_harness.composition.observation import build_observer
    from codex_harness.coordination.application.fleet.admission import AdmissionControl
    from codex_harness.coordination.application.fleet.pause import FleetPause
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.application.fleet.runner import FleetRunner
    from codex_harness.intake.adapters.portfolio import portfolio_reconciler

    registry = FleetRegistry(service.store)
    config = registry.registered()["config"]
    host = settings()
    # Opt-in only (INV-FLEET-BACKLOG-001): without the host plan setting the runner keeps its exact
    # previous behaviour, never selects work of its own and builds no observer.
    plan_id = fleet_backlog.configured_plan(host)
    backlog_tick = None
    if plan_id is not None:
        # The durable process observer of the configured continuous loop: the backlog's fixed
        # admission, refusal, conflict, unavailability and recovery transitions are collected as
        # structured observations, not only as log lines.
        backlog_tick = fleet_backlog.backlog_ticker(service.store, config, plan_id,
                                                    observer=build_observer(service.store, "fleet-backlog"))
    # Opt-in only (INV-CONTINUATION-001): without the host policy setting no continuation pass,
    # lane connection, conductor process or observer is built, and the runner is unchanged.
    # A comma-separated setting names several disjoint policies; the ONE runner ticks them in turn.
    policy_ids = continuation.configured_policies(host)
    continuation_tick = None
    if policy_ids is not None:
        continuation_tick = continuation.continuation_ticker(
            service.store, config, host, policy_ids, observer=build_observer(service.store, "fleet-continuation"))
    # The bounded portfolio pass is wired here, in the adapter: the runner keeps no portfolio
    # dependency and a reconciliation outage never blocks admission (operating-portfolio-001).
    runner = FleetRunner(registry, AdmissionControl(service.store), FleetPause(service.store),
                         fleet.lane_launcher(config, host), reconcile=portfolio_reconciler(service.store),
                         backlog=backlog_tick, control=control, continuation=continuation_tick)
    installed = []  # (signal, previous handler) for each handler THIS run replaced
    try:
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                # Graceful stop: admission closes, owned children are drained, nothing is killed.
                number = getattr(signal, name)
                installed.append((number, signal.signal(number, lambda *_: runner.stop())))
        summary = runner.run(once=bool(args.once))
    finally:
        # The handlers close over this run's runner: every exit, including an exception and a
        # partial installation, hands the process its previous handlers back.
        for number, previous in reversed(installed):
            with suppress(Exception):  # a restore failure never replaces the original outcome
                signal.signal(number, previous)
    return {**summary, "exit_code": 0}


def _resolved(read):
    """One store input, read on the FIRST observation and reused on the re-read.

    Both owner commands hand `FleetRecovery` an observation callback that it calls a second time from
    INSIDE its committing transaction. `PostgresStore.transaction` opens its own connection and takes
    advisory lock 734219 for every transaction, so a callback that reads the primary store there
    waits for a lock the same call already holds and fails with `LockNotAvailable` when
    `lock_timeout` expires; `MemoryStore`'s reentrant lock hid that boundary, and the first real
    owner recovery rolled back on it. The immutable registry, lane and job rows an observation needs
    are therefore resolved once, while `FleetRecovery` is still outside its transaction, and reused on the
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


def _collectors():
    """The wired recovery collaborators: `state` over the Docker call, `run_records`, `git_source` and the machine call budget
    M7's `collect_recovery_proof` built for `budget=None`."""
    from codex_harness.composition import fleet_recovery
    from codex_harness.execution.adapters.call_budget import CallBudget

    return fleet_recovery.collectors(budget=CallBudget())


def reconcile_interrupted(service, args, document) -> dict:
    """Owner recovery of ONE interrupted job. The evidence document says what the owner proved; the
    adapter observes the lane store, Docker and the machine ledger itself and re-reads that
    observation inside the committing transaction. No model is called and no work is resumed.

    The observation is a callback, not a value: `FleetRecovery.reconcile_interrupted` answers an identical
    replay from the committed receipt, and this command then reads no lane schema, no Docker daemon
    and no call ledger at all, so a settled recovery survives the removal of what it settled.

    The lane the observation reads is resolved once, outside the application's transaction (see
    `_resolved`); the lane store, Docker and the call ledger are read again on the re-read."""
    from codex_harness.coordination.application.fleet.recovery import FleetRecovery
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.domain.fleet import FleetRefused, lane_of
    from codex_harness.coordination.domain.fleet_recovery import validate_recovery_evidence

    evidence = validate_recovery_evidence(document)
    registry = FleetRegistry(service.store)

    def pinned_lane() -> dict:
        """The lane this evidence names, taken from the registry the evidence expects.

        Pinning the digest here binds the observed lane to the exact configuration
        `FleetRecovery.reconcile_interrupted` compares against under its own transaction: the schema and
        runtime that were read cannot belong to some other configuration that the commit's
        `config_expected_mismatch` check would then accept as the expected one."""
        registered = registry.registered()
        if registered["config_sha256"] != evidence["expected"]["config_sha256"]:
            raise FleetRefused("config_expected_mismatch", "expected.config_sha256")
        return lane_of(registered["config"], evidence["expected"]["lane"])

    lane = _resolved(pinned_lane)

    def observe() -> dict:
        from codex_harness.composition.configuration import settings
        from codex_harness.coordination.adapters.fleet_recovery import LaneReader, collect_recovery_proof
        from codex_harness.coordination.adapters.fleet_runtime import lane_dsn

        target = lane()
        reader = LaneReader(lane_dsn(settings().get("HARNESS_DATABASE_URL"), target["schema"]), target["schema"])
        wired = _collectors()
        return collect_recovery_proof(evidence, target, reader=reader, budget=wired.budget,
                                      state=lambda container: wired.state(container, args.docker),
                                      run_records=wired.run_records)

    return {**FleetRecovery(service.store).reconcile_interrupted(evidence, observe=observe, reread=observe),
            "exit_code": 0}


def migrate_host(service, args, document) -> dict:
    """Owner host migration of the registry bindings (INV-HOST-MIGRATION-001) on the target host.

    The observation is a callback so an identical replay is answered from the receipt without
    reading the journal, checkouts, Docker or the database. The target schemas are checked under
    the lane search-path rule against this host's configured database.

    The job rows the observation needs are resolved once, outside the application's transaction
    (see `_resolved`); the journal, the checkouts, Docker and the target schemas are read again on
    the re-read, and `FleetRecovery.migrate_host` still judges the proof against the queued set its own
    commit reads."""
    from codex_harness.composition.configuration import settings
    from codex_harness.coordination.application.fleet.recovery import FleetRecovery
    from codex_harness.coordination.application.fleet.state import BUCKET_JOBS
    from codex_harness.coordination.domain.fleet_recovery import validate_host_migration_request

    request = validate_host_migration_request(document)

    def pinned_jobs() -> list:
        with service.store.transaction() as tx:
            return tx.scan(BUCKET_JOBS)

    jobs = _resolved(pinned_jobs)

    def observe() -> dict:
        from codex_harness.coordination.adapters.fleet_recovery import collect_host_migration_proof

        wired = _collectors()
        return collect_host_migration_proof(request, jobs(), journal=args.journal,
                                            host_dsn=settings().get("HARNESS_DATABASE_URL") or "",
                                            state=lambda container: wired.state(container, args.docker),
                                            run_records=wired.run_records, git_source=wired.git_source)

    return {**FleetRecovery(service.store).migrate_host(request, observe=observe, reread=observe), "exit_code": 0}


def relocate(service, args, document) -> dict:
    """Owner relocation of lane repository/runtime paths to already-copied, verified targets. The
    copy itself is the owner's preparation step: nothing here moves, deletes or rewrites files,
    history, manifests or goal identities.

    The observation is a callback, not a value: `FleetRecovery.relocate` answers an identical replay from
    the committed receipt, and this command then reads no journal, no checkout, no Docker daemon
    and no copied file, so a completed cutover replays even once the old paths are gone.

    The configuration and job rows the observation needs are resolved once, outside the application's
    transaction (see `_resolved`); the journal, the checkouts, Docker and the copied files are read
    again on the re-read, and the queued denominator the proof is judged against is the one the
    commit reads for itself."""
    from codex_harness.coordination.application.fleet.recovery import FleetRecovery
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.application.fleet.state import BUCKET_JOBS
    from codex_harness.coordination.domain.fleet import FleetRefused
    from codex_harness.coordination.domain.fleet_recovery import validate_relocation_request

    request = validate_relocation_request(document)
    registry = FleetRegistry(service.store)

    def pinned_inputs() -> tuple[dict, list]:
        """The expected configuration and the job rows, read before the application's commit.

        The digest is pinned for the same reason as in the recovery command; the job rows are only
        the queued bindings this observation must look for, and `FleetRecovery.relocate` still recomputes
        the queued denominator inside its transaction and refuses a proof that does not cover
        exactly that set, so rows that changed in between cannot commit."""
        registered = registry.registered()
        if registered["config_sha256"] != request["expected_config_sha256"]:
            raise FleetRefused("config_expected_mismatch", "expected_config_sha256")
        with service.store.transaction() as tx:
            jobs = tx.scan(BUCKET_JOBS)
        return registered["config"], jobs

    inputs = _resolved(pinned_inputs)

    def observe() -> dict:
        from codex_harness.coordination.adapters.fleet_recovery import collect_relocation_proof

        config, jobs = inputs()
        wired = _collectors()
        return collect_relocation_proof(request, config, jobs, journal=args.journal,
                                        state=lambda container: wired.state(container, args.docker),
                                        run_records=wired.run_records, git_source=wired.git_source)

    return {**FleetRecovery(service.store).relocate(request, observe=observe, reread=observe), "exit_code": 0}
