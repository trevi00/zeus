"""Target driver: `coordination.execution_time` on the target tree (execution_time, execution_rejections).

The wall clock and the monotonic clock are injected (the scripted harness clock through the kernel Clock port);
the process clock-domain identity is set to the same value the reference driver sets.
"""

import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import functools  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_time  # noqa: E402
from codex_harness.coordination.application import execution_rejections, execution_time  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock()
PORT = PortClock(CLOCK)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000e4e4"  # this process's clock-domain identity
TIME = SimpleNamespace(
    DOMAIN=execution_time.DOMAIN, ExecutionTimeError=execution_time.ExecutionTimeError,
    deadline=execution_time.deadline, check_clock=execution_time.check_clock,
    observe_domain=execution_time.observe_domain, contain_with_notice=execution_time.contain_with_notice,
    active=functools.partial(execution_time.active, monotonic=CLOCK.monotonic),
    pin_clock=functools.partial(execution_time.pin_clock, clock=PORT, monotonic=CLOCK.monotonic),
    running=functools.partial(execution_time.running, clock=PORT, monotonic=CLOCK.monotonic))
API = SimpleNamespace(MemoryStore=MemoryStore, dt=datetime, advance=CLOCK.advance, time=TIME,
                      reconcile=functools.partial(execution_rejections.reconcile, clock=PORT,
                                                  monotonic=CLOCK.monotonic),
                      org=packaged_organization())

if __name__ == "__main__":
    driver.finish("target", "coordination.execution_time", s4_time.run(API))
