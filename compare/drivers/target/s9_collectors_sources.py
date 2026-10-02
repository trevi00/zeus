"""Target driver: `observation.collectors_sources` on the target tree (`observation.adapters.collectors`, the moved U7 source collectors with the D1.1 seams).

The same scripted doubles the reference driver puts where M7's names are are INJECTED here: `run_process=`, `bus_factory=`, `project=` (the owner's `X(store).method()` call
of M7, built from the double class), `dsn_for=`, `registered=` and `ports=` (`observation.ports.CollectorPorts`, as S10 composes it). No clock or id source is installed: the
`datetime.now` values are proven in bounds and normalized by the shared steps."""

import contextlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_collectors_sources  # noqa: E402
from codex_harness.coordination.domain.fleet import FleetRefused  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.observation.adapters import collectors as module  # noqa: E402
from codex_harness.observation.ports import CollectorPorts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402


@contextlib.contextmanager
def bind(d):
    projections = {"fleet": lambda store: d.Fleet(store).status(), "research_program": lambda store: d.ResearchProgram(store).monitor(),
                   "portfolio": lambda store: d.portfolio(store).status(), "fleet_backlog": lambda store: d.FleetBacklog(store).status(),
                   "host_delivery": lambda store: d.HostDelivery(store).status(), "worker_session": lambda store: d.WorkerSessions(store, None).status(),
                   "continuation": lambda store: d.Continuation(store).status(), "discovery_pressure": d.discovery_status}
    registered = lambda store: d.Fleet(store).registered()  # noqa: E731
    ports = CollectorPorts(run_process=d.run_process, bus_factory=d.RedisBus, registered=registered, **projections)

    def facts(name):
        function = getattr(module, name)
        return lambda store: function(store, project=projections[name.removesuffix("_facts")])

    yield SimpleNamespace(
        docker_stats=lambda names: module.docker_stats(names, run_process=d.run_process),
        docker_facts=lambda repository, containers=None: module.docker_facts(repository, containers, run_process=d.run_process),
        redis_facts=lambda url, agents: module.redis_facts(url, agents, bus_factory=d.RedisBus),
        fleet_facts=facts("fleet_facts"), research_program_facts=facts("research_program_facts"), portfolio_facts=facts("portfolio_facts"),
        fleet_backlog_facts=facts("fleet_backlog_facts"), host_delivery_facts=facts("host_delivery_facts"), worker_session_facts=facts("worker_session_facts"),
        continuation_facts=facts("continuation_facts"), discovery_pressure_facts=facts("discovery_pressure_facts"),
        lane_resolver=lambda host_dsn, store_factory=None: module.lane_resolver(host_dsn, store_factory, dsn_for=d.lane_dsn),
        lane_session_facts=lambda store, resolve, artifacts=None, now=None: module.lane_session_facts(store, resolve, artifacts, now, registered=registered),
        collect=lambda *args, **kwargs: module.collect(*args, ports=ports, **kwargs))


API = SimpleNamespace(module=module, MemoryStore=MemoryStore, FleetRefused=FleetRefused, ContractError=ContractError, bind=bind)

if __name__ == "__main__":
    driver.finish("target", "observation.collectors_sources", s9_collectors_sources.run(API))
