"""Reference driver: `coordination.decision_claims` (M7 Executor.decide_one's claim, stopped at the provider)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s4_claims  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import (  # noqa: E402,F401
    execution_recovery,
    execution_time,
    workflow,
)
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import envelope  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000e6e6"}})
ORG = organization()
ROOT = Path("/tmp/zeus-rebuild-s4-claims")


class Boundary(BaseException):
    """Raised at the provider boundary: decide_one's own `except Exception` never sees it."""


def fresh():
    CLOCK.reset()
    IDS.reset()
    return MemoryStore()


def claim(store, agent, expected=None):
    seen = {}

    def run(agent_, key, *args, **kwargs):
        seen["lease"] = kwargs["lease"]
        raise Boundary()

    IDS.reset()  # the owner id is the first id drawn by this claim, as on the target
    executor = Executor(Harness(store, ORG), SimpleNamespace(repository=ROOT), FileArtifacts(str(ROOT / "artifacts")))
    executor._run = run
    try:
        executor.decide_one(agent, expected)
    except Boundary:
        return {k: v for k, v in seen["lease"].items() if k != "_bucket"}
    return None


API = SimpleNamespace(fresh=fresh, claim=claim, envelope=envelope, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "coordination.decision_claims", s4_claims.run(API))
