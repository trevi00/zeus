"""Reference driver: `coordination.breaker` (M7 Breaker admit/report/inspect/update_policy and result mapping)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_breaker  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.breaker import (  # noqa: E402
    DEFAULT_POLICY,
    Breaker,
    breaker_key,
    result_of,
    result_of_exception,
)
from codex_harness.domain.model import ContractError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)


def reset():
    CLOCK.reset()
    IDS.reset()


API = SimpleNamespace(
    MemoryStore=MemoryStore, ContractError=ContractError, DEFAULT_POLICY=DEFAULT_POLICY, breaker_key=breaker_key,
    result_of=result_of, result_of_exception=result_of_exception, reset=reset,
    breaker=lambda store, policy=None: Breaker(store, policy) if policy is not None else Breaker(store))

if __name__ == "__main__":
    driver.finish("reference", "coordination.breaker", s4_breaker.run(API))
