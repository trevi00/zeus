"""Observation builders: the process Observer and the Collector over the projecting store (INV-OBSERVATION-001).

Layer: composition
Owns: observation_root, build_observer, build_collector, PROVIDERS
Does not own: the Observer, the Collector and the catalog check (observation), the stream identities (execution)
Entry points: observation_root, build_observer, build_collector
Contracts: INV-OBSERVATION-001, OWNER-DECISIONS-S10 #18(a)

Moved from M7 `bootstrap.py:31-55` (SOURCE e38aa722). The bodies are M7's apart from the imports and two changes:
`build_observer` returns the Observer wrapped in `CatalogCheckingObserver` (#18(a)), and the Collector's store is a
`ProjectingStore` over the real store (DESIGN-s9-X §2.2).
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


def build_collector(store, observer=None):
    from codex_harness.observation.adapters.observation_schema import validate_observation
    from codex_harness.observation.adapters.observation_spool import SpoolDirectory
    from codex_harness.observation.application.metrics_projector import MetricsProjector, ProjectingStore
    from codex_harness.observation.application.observations import Collector

    projecting = ProjectingStore(store, MetricsProjector(providers=PROVIDERS))
    return Collector(projecting, SpoolDirectory(observation_root()), validate=validate_observation,
                     observer=observer)
