"""The collector, web and desk wiring of `zeus-monitor`: the journal, the collect loop, the desk service, the listener refusal and the production `CollectorPorts`.

Layer: composition
Owns: Journal, source_states, run_collector, desk_service, viewer_port, listener_refusal, collector_ports, serve_web, serve_desk
Does not own: the argument shape and the mode dispatch (entry.processes.monitor), the desk routes (entry.http.desk), the viewer listener (observation.adapters.viewer_http), the collection itself (observation.adapters.collectors)
Entry points: run_collector, serve_web, serve_desk, listener_refusal, collector_ports
Contracts: INV-MONITOR-VIEWER-001, local-operations-desk-001

Moved from M7 `monitor.py` (SOURCE e38aa722) by named rule R-e2 (S10 unit E2a): `Journal` (:33-50), `source_states` (:53), `run_collector` (:56-114), `desk_service` (:116-131), `viewer_port` (:134-139) and
`listener_refusal` (:142-158) are M7's statements except the import homes (`settings`/`runtime_dir` are `composition.configuration`, `FileArtifacts` is `storage.adapters.file_artifacts`, the collector
functions are `observation.adapters.collectors`, `build`/`redis_url` are `composition`, `VIEWER_PORT` is `observation.adapters.viewer_http`) and the target seams: `collect(..., ports=collector_ports())` and
the desk's `FrontDesk` built by `composition.cli_desk.front_desk` (the outbox port, R-f1). `serve_web` and `serve_desk` are the two `serve(...)` calls of M7 `main` (:174-179); `desk_http` is a parameter because composition
may not import `entry.http.desk` (the entry passes the module itself).

`collector_ports()` mirrors `tests/ported/m7_observation._Monitoring.collect` and the S9 target driver `s9_collectors_sources.bind`; each home was found by grep:

| field | wiring | home |
|---|---|---|
| run_process | the process-group runner | `host_os.adapters.process_groups.run_process` |
| bus_factory | `RedisBus` (M7 `RedisBus(url)`; the target takes the namespace from `HARNESS_REDIS_NAMESPACE` as `composition.cli_bus.bus` does) | `storage.adapters.redis_bus.RedisBus` |
| fleet | `FleetRegistry(store).status()` (the shim routes `status` to the registry) | `coordination.application.fleet.registry` |
| research_program | `ResearchProgram(store).monitor()` | `research.application.research_program` |
| portfolio | `portfolio(store).status()` | `intake.adapters.portfolio` |
| fleet_backlog | `FleetBacklog(store).status()` | `coordination.application.fleet_backlog` |
| host_delivery | `host_delivery_owners(store, None).registry.status()` (C8b-4; the shim routes `status` to `registry`) | `composition.cli_host_delivery` |
| worker_session | `WorkerSessions(store, None).status()` | `execution.application.worker_sessions` |
| continuation | `continuation_owners(store).frames.status()` (C8b-1; the shim routes `status` to `frames`) | `composition.continuation` |
| discovery_pressure | the module's `status` | `research.application.discovery_pressure` |
| registered | `FleetRegistry(store).registered()` | `coordination.application.fleet.registry` |

`lane_resolver` is called with `dsn_for=lane_dsn` (`coordination.adapters.fleet_runtime`). Imports sit inside the functions, so importing this module stays light.
"""
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from filelock import FileLock, Timeout

from codex_harness.composition.configuration import settings

LOG_BYTES, LOG_BACKUPS = 1024 * 1024, 2
# Sanitized operational log: event/type names and small integers only; never DSNs, env values,
# payloads or raw exception text.
LOG_FIELDS = frozenset({'mode', 'once', 'scope', 'containers', 'source', 'status', 'error', 'reason'})
LOG_VALUE = re.compile(r'[A-Za-z0-9_.:-]{1,64}')


class Journal:
    def __init__(self, path):
        self.logger = logging.getLogger('zeus.monitor.collector')
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        for old in list(self.logger.handlers):
            self.logger.removeHandler(old)
            old.close()
        self.logger.addHandler(handler)

    def write(self, event, **fields):
        safe = {key: value for key, value in fields.items() if key in LOG_FIELDS and (
            value is None or isinstance(value, bool) or type(value) is int
            or (isinstance(value, str) and LOG_VALUE.fullmatch(value)))}
        self.logger.info(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'event': event, **safe},
                                    sort_keys=True))


def source_states(result):
    return {name: (envelope.get('status'), envelope.get('error')) for name, envelope in result['sources'].items()}



def run_collector(args, root, runtime, snapshot):
    from codex_harness.composition import build, redis_url
    from codex_harness.coordination.adapters.fleet_runtime import lane_dsn
    from codex_harness.observation.adapters.collectors import (
        collect,
        container_scope,
        lane_artifact_resolver,
        lane_resolver,
        read_only,
    )
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    journal = Journal(runtime / 'monitor-collector.log')
    config = settings()
    try:
        containers = container_scope(config.get('ZEUS_MONITOR_CONTAINERS'))
    except ValueError as exc:
        journal.write('startup_refused', reason='config_invalid', error=type(exc).__name__)
        raise
    scope = config.get('ZEUS_MONITOR_SCOPE')
    os.chdir(root)
    try:
        with FileLock(str(runtime / 'monitor-collector.lock'), timeout=0):
            service, artifacts = read_only(build(), FileArtifacts(str(runtime / 'artifacts')))
            # Registered lanes are read through their own schemas (read-only, cached per lane).
            lanes = lane_resolver(config.get('HARNESS_DATABASE_URL'), dsn_for=lane_dsn)
            # S2a: each lane's registered artifact root, read-only and never created.
            lane_artifacts = lane_artifact_resolver()
            url = redis_url()
            ports = collector_ports()
            journal.write('startup', mode='collect', once=bool(args.once),
                          scope='named' if containers is not None else 'compose',
                          containers=len(containers) if containers is not None else None)
            previous = {}
            while True:
                result = collect(service, artifacts, str(root), url, containers, scope, runtime=runtime, lanes=lanes,
                                 lane_artifacts=lane_artifacts, ports=ports)
                for name, state in source_states(result).items():
                    if previous.get(name) != state:
                        journal.write('source_state', source=name, status=state[0], error=state[1])
                previous = source_states(result)
                try:
                    temp = snapshot.with_suffix('.tmp')
                    temp.write_text(json.dumps(result, ensure_ascii=False), 'utf-8')
                    os.replace(temp, snapshot)
                except OSError as exc:
                    journal.write('snapshot_write_failed', error=type(exc).__name__)
                    raise
                if args.once:
                    journal.write('shutdown', reason='once')
                    return
                time.sleep(5)
    except Timeout:
        journal.write('startup_refused', reason='collector_lock_busy')
        return
    except KeyboardInterrupt:
        journal.write('shutdown', reason='interrupt')
        return
    except Exception as exc:
        journal.write('shutdown', reason='failure', error=type(exc).__name__)
        raise



def desk_service():
    """The opt-in local front door (local-operations-desk-001), or None.

    The web process serves the desk only when the owner configured ZEUS_DESK_REVISION as a full
    40-hex Git revision; that configured revision is the base every request is captured at. An
    unset value keeps the web process exactly read-only, and a malformed one refuses to start
    rather than serving a half-enabled desk. No store connection is opened here: an unreachable
    PostgreSQL is answered per request, never with a local fallback.
    """
    configured = settings().get('ZEUS_DESK_REVISION')
    if not configured:
        return None
    from codex_harness.composition import build
    from codex_harness.composition.cli_desk import front_desk

    return front_desk(build(), configured)


def viewer_port(environ=None) -> int:
    """The viewer listener's port: the aibox unit's ZEUS_AIBOX_WEB_PORT when set, else 8787."""
    from codex_harness.observation.adapters.viewer_http import VIEWER_PORT

    value = str((os.environ if environ is None else environ).get('ZEUS_AIBOX_WEB_PORT') or '')
    return int(value) if value.isdigit() else VIEWER_PORT


def listener_refusal(mode, port, desk_revision, viewer=None):
    """INV-MONITOR-VIEWER-001 (D6), checked before any listener binds: the viewer web service refuses to
    start while ZEUS_DESK_REVISION is set, and the local-operator desk runs only as its own mode on an
    explicit port that is neither 8787 nor the configured viewer port. Returns the refusal text, or None."""
    from codex_harness.observation.adapters.viewer_http import VIEWER_PORT

    viewer = viewer_port() if viewer is None else viewer
    if mode == 'web' and desk_revision:
        return ('monitor web refuses to start with ZEUS_DESK_REVISION set: the viewer listener never serves the '
                'desk; run the separately bound local-operator mode (monitor desk --port <other>) instead')
    if mode == 'desk':
        if not desk_revision:
            return 'monitor desk needs ZEUS_DESK_REVISION'
        if port is None or port in (VIEWER_PORT, viewer):
            return 'monitor desk needs its own --port, never the viewer port ' + str(viewer)
    return None



def collector_ports():
    """The production `observation.ports.CollectorPorts` (the table in the module docstring)."""
    from codex_harness.composition.cli_host_delivery import host_delivery_owners
    from codex_harness.composition.continuation import continuation_owners
    from codex_harness.coordination.application.fleet.registry import FleetRegistry
    from codex_harness.coordination.application.fleet_backlog import FleetBacklog
    from codex_harness.execution.application.worker_sessions import WorkerSessions
    from codex_harness.host_os.adapters.process_groups import run_process
    from codex_harness.intake.adapters.portfolio import portfolio
    from codex_harness.observation.ports import CollectorPorts
    from codex_harness.research.application import discovery_pressure
    from codex_harness.research.application.research_program import ResearchProgram
    from codex_harness.storage.adapters.redis_bus import RedisBus

    def bus_factory(url):
        return RedisBus(url, settings().get('HARNESS_REDIS_NAMESPACE', 'codex-harness'))

    return CollectorPorts(
        run_process=run_process, bus_factory=bus_factory,
        fleet=lambda store: FleetRegistry(store).status(),
        research_program=lambda store: ResearchProgram(store).monitor(),
        portfolio=lambda store: portfolio(store).status(),
        fleet_backlog=lambda store: FleetBacklog(store).status(),
        host_delivery=lambda store: host_delivery_owners(store, None).registry.status(),
        worker_session=lambda store: WorkerSessions(store, None).status(),
        continuation=lambda store: continuation_owners(store).frames.status(),
        discovery_pressure=discovery_pressure.status,
        registered=lambda store: FleetRegistry(store).registered())


def serve_web(snapshot, port):
    """M7 `main`'s web branch: the viewer listener, read-only, no desk, whatever the environment says."""
    from codex_harness.observation.adapters.viewer_http import VIEWER_PORT, serve
    serve(snapshot, VIEWER_PORT if port is None else port)


def serve_desk(snapshot, port, *, desk_http):
    """M7 `main`'s desk branch; `desk_http` is the `observation.ports.DeskHttp` module the entry passes."""
    from codex_harness.observation.adapters.viewer_http import serve
    serve(snapshot, port, desk=desk_service(), viewer_port=viewer_port(), desk_http=desk_http)
