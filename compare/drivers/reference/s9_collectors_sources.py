"""Reference driver: `observation.collectors_sources` (M7 `adapters/monitoring.py` U7: the source collectors).

The doubles sit where M7's names are: `monitoring.run_process`, `monitoring.RedisBus`, `monitoring.Fleet` and the lazily imported `ResearchProgram`, `portfolio`, `FleetBacklog`,
`HostDelivery`, `WorkerSessions`, `Continuation`, `discovery_pressure.status` and `fleet_runtime.lane_dsn` (the B3 pattern), restored after each use. No clock or id source is
installed: the `datetime.now` values are proven in bounds and normalized by the shared steps."""

import contextlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_collectors_sources  # noqa: E402

import codex_harness.adapters.fleet_runtime as fleet_runtime  # noqa: E402
import codex_harness.adapters.monitoring as module  # noqa: E402
import codex_harness.adapters.portfolio as portfolio_module  # noqa: E402
import codex_harness.application.continuation as continuation_module  # noqa: E402
import codex_harness.application.discovery_pressure as discovery_module  # noqa: E402
import codex_harness.application.fleet_backlog as backlog_module  # noqa: E402
import codex_harness.application.host_delivery as delivery_module  # noqa: E402
import codex_harness.application.research_program as program_module  # noqa: E402
import codex_harness.application.worker_sessions as sessions_module  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.domain.fleet import FleetRefused  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

NAMES = ("docker_stats", "docker_facts", "redis_facts", "fleet_facts", "research_program_facts", "portfolio_facts", "fleet_backlog_facts", "host_delivery_facts",
         "worker_session_facts", "continuation_facts", "discovery_pressure_facts", "lane_resolver", "lane_session_facts", "collect")


@contextlib.contextmanager
def bind(doubles):
    patches = [(module, "run_process", doubles.run_process), (module, "RedisBus", doubles.RedisBus), (module, "Fleet", doubles.Fleet),
               (program_module, "ResearchProgram", doubles.ResearchProgram), (portfolio_module, "portfolio", doubles.portfolio),
               (backlog_module, "FleetBacklog", doubles.FleetBacklog), (delivery_module, "HostDelivery", doubles.HostDelivery),
               (sessions_module, "WorkerSessions", doubles.WorkerSessions), (continuation_module, "Continuation", doubles.Continuation),
               (discovery_module, "status", doubles.discovery_status), (fleet_runtime, "lane_dsn", doubles.lane_dsn)]
    saved = [(owner, name, getattr(owner, name)) for owner, name, _ in patches]
    for owner, name, value in patches:
        setattr(owner, name, value)
    try:
        yield SimpleNamespace(**{name: getattr(module, name) for name in NAMES})
    finally:
        for owner, name, value in saved:
            setattr(owner, name, value)


API = SimpleNamespace(module=module, MemoryStore=MemoryStore, FleetRefused=FleetRefused, ContractError=ContractError, bind=bind)

if __name__ == "__main__":
    driver.finish("reference", "observation.collectors_sources", s9_collectors_sources.run(API))
