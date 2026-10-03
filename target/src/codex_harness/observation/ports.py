"""Observation ports: the buckets observation owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: observation
Owns: OWNED_BUCKETS of the observation context; SpoolFull and ObservationSpool (M7 `ports.py`, moved ahead in S4
    unchanged: the append-only record store the Observer writes through); DeskHttp, the desk routes the viewer
    serves only when a desk is injected (S9 U8, OWNER-DECISIONS-S9 D2.1; S10 passes `entry.http.desk` itself);
    CollectorPorts, the seams `collectors.collect` is given (S9 U7, D1.1; S10 builds it once)
Does not own: ObservationDirectory (9 methods, above the port-size limit: S9) and the other observation Protocols
    (PostgresFacts, RedisFacts, ...: S9)
Entry points: OWNED_BUCKETS, SpoolFull, ObservationSpool, DeskHttp, CollectorPorts
Contracts: INV-OBSERVATION-001
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# `metric_observations`: S9 P0 (coordinator), declared before its one writer, M7 application/measurements.py
# (PREP-S9 §4.2 U4; no other SOURCE writer). `observation_metrics` (a different bucket): S9 X2 P0 (coordinator), the
# metrics projection's aggregates, an addition with no SOURCE counterpart, declared before its one writer
# `application.metrics_projector` (DESIGN-s9-X §2.2).
OWNED_BUCKETS = ("observation_audit", "observations", "observation_quarantine", "observation_alerts",
                 "observation_collections", "observation_terminations", "health", "metric_observations",
                 "observation_metrics")


class SpoolFull(RuntimeError):
    """The bounded observation spool cannot take another record; the caller counts and reports."""


class ObservationSpool(Protocol):
    """One process run's append-only durable record store (INV-OBSERVATION-001)."""
    process_run_id: str

    def append(self, kind: str, event: dict) -> int: ...
    def close(self) -> None: ...


class DeskHttp(Protocol):
    """The desk routes of M7 `adapters/frontdesk_http.py`, as the viewer calls them (S9 U8, OWNER-DECISIONS-S9 D2.1).

    The viewer reads it only when a desk service is injected; a module satisfies it structurally."""
    JSON: str
    READ_TIMEOUT_SECONDS: float
    ROUTES_POST: set

    def handle_get(self, desk, path: str): ...
    def check_intent(self, handler, authority: str): ...
    def read_body(self, handler): ...
    def handle_post(self, desk, path: str, document: dict): ...
    def error(self, code: str) -> bytes: ...


@dataclass(frozen=True)
class CollectorPorts:
    """What M7 `adapters/monitoring.py` imported from other contexts, injected (S9 U7, OWNER-DECISIONS-S9 D1.1).

    `run_process` runs the read-only docker commands; `bus_factory(url)` builds the Redis bus whose streams are read;
    each projection takes the read-only store and returns its owner's status; `registered(store)` is the Fleet's
    registered configuration (it raises the coordination `FleetRefused` when unregistered)."""
    run_process: Callable
    bus_factory: Callable
    fleet: Callable
    research_program: Callable
    portfolio: Callable
    fleet_backlog: Callable
    host_delivery: Callable
    worker_session: Callable
    continuation: Callable
    discovery_pressure: Callable
    registered: Callable
