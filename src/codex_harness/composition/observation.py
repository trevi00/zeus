"""Observation builders: the process Observer and the Collector over the projecting store (INV-OBSERVATION-001).

Layer: composition
Owns: observation_root, build_observer, build_collector, PROVIDERS, the `operations.collector_started` emit
Does not own: the Observer, the Collector and the catalog check (observation), the stream identities (execution)
Entry points: observation_root, build_observer, build_collector
Contracts: INV-OBSERVATION-001, OWNER-DECISIONS-S10 #18(a)

Moved from M7 `bootstrap.py:31-55` (SOURCE e38aa722). The bodies are M7's apart from the imports and two changes:
`build_observer` returns the Observer wrapped in `CatalogCheckingObserver` (#18(a)), and the Collector's store is a
`ProjectingStore` over the real store (DESIGN-s9-X §2.2).

S10 unit A5-3 (DESIGN-s10 §17b): `build_collector` emits `operations.collector_started {collector, previous_exit}` once per
observer process run (`observations.py` is byte-pinned, so the emit lives here). `previous_exit` is derived from the spool
health records that already exist: the latest other run of the same component is `clean` when its spool was closed, `unknown`
while its writer is alive, otherwise `crashed`, which means it ended without closing its spool (a kill is not distinguishable).
`announce=False` (owner, int42, DESIGN-s10 §17e) is for the one-shot `observe collect` reporter only: it would otherwise
collect, and report as M7's counts, the lifecycle event it just emitted about itself (the `entry.cli_bus.pgredis` SOURCE golden).
"""

from __future__ import annotations

from codex_harness.composition.configuration import runtime_dir
from codex_harness.execution.domain.provider_stream import ClaudeStream, CodexStream

# The closed provider roster the metrics projection labels by; read from the stream classes, never copied.
PROVIDERS = (ClaudeStream.identity, CodexStream.identity)


def observation_root():
    return runtime_dir() / "observations"


def build_observer(store, component: str, role: str | None = None, root=None):
    """One durable observer per process: spool, health and termination records under the runtime dir.

    `root` is the spool directory of an explicitly selected Fleet lane (its own runtime's
    `observations`); None keeps this process's runtime dir, exactly as every caller had it."""
    from codex_harness.kernel.policy import POLICY
    from codex_harness.observation.adapters.observation_spool import FileSpool, SpoolDirectory
    from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
    from codex_harness.observation.application.observations import Observer
    from codex_harness.observation.domain.observation import new_process_run_id

    root = observation_root() if root is None else root
    spool = FileSpool(root, new_process_run_id(), max_bytes=POLICY.observation_spool_bytes)
    return CatalogCheckingObserver(
        Observer(store, spool, component=component, directory=SpoolDirectory(root), role=role))


_STARTED: set = set()  # process_run_ids whose collector_started was already emitted; a process may build its Collector twice


def _previous_exit(directory, component, process_run_id):
    """The `previous_exit` enum value for `component`'s Collector start, from the existing spool health records.

    The latest (by `updated_at`) readable record of the same component other than this run decides: none is
    `first_start`, a closed spool is `clean`, a live writer is `unknown` (a concurrent instance, not an exit),
    otherwise `crashed`: it ended without closing its spool; a kill is not distinguishable. An unreadable record
    has no component or time, so it cannot be ordered: when it is the only candidate evidence the answer is `unknown`."""
    try:
        records = directory.read_health()
    except Exception:  # noqa: BLE001 - derived field: an unreadable health directory is not a first start
        return "unknown"
    same, unreadable = [], False
    for record in records:
        run = record.get("process_run_id") if isinstance(record, dict) else None
        if run == process_run_id:
            continue
        if (not isinstance(record, dict) or record.get("unreadable") or type(run) is not str
                or type(record.get("updated_at")) is not str):
            unreadable = True
        elif record.get("component") == component:
            same.append(record)
    if not same:
        return "unknown" if unreadable else "first_start"
    latest = max(same, key=lambda record: record["updated_at"])["process_run_id"]
    if directory.closed(latest):
        return "clean"
    if directory.writer_alive(latest):
        return "unknown"
    return "crashed"


def _emit_collector_started(observer):
    run = getattr(observer, "process_run_id", None)
    if run in _STARTED:
        return
    _STARTED.add(run)
    try:
        from codex_harness.observation.adapters.observation_spool import SpoolDirectory
        directory = getattr(observer, "directory", None) or SpoolDirectory(observation_root())
        observer.emit("operations.collector_started", "observed",
                      attributes={"collector": observer.component,
                                  "previous_exit": _previous_exit(directory, observer.component, run)})
    except Exception:  # noqa: BLE001 - the diagnostic path never stops a process from starting its Collector
        pass


def build_collector(store, observer=None, *, announce=True):
    from codex_harness.observation.adapters.observation_schema import validate_observation
    from codex_harness.observation.adapters.observation_spool import SpoolDirectory
    from codex_harness.observation.application.metrics_projector import MetricsProjector, ProjectingStore
    from codex_harness.observation.application.observations import Collector

    if observer is not None and announce:
        _emit_collector_started(observer)
    projecting = ProjectingStore(store, MetricsProjector(providers=PROVIDERS))
    return Collector(projecting, SpoolDirectory(observation_root()), validate=validate_observation,
                     observer=observer)
