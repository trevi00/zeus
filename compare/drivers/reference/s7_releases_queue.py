"""Reference driver: `review.releases_queue` (M7 ReleaseQueue and the delivery-called Releases methods).

The API holds plain M7 objects or lambdas over them: `MemoryStore`, `queue(store)` = `ReleaseQueue(store)`,
`releases(store)` = `Releases(store, organization())`, `POLICY` (M7 `domain.policy`), `TicketSuperseded`
(`application.tickets`), the pure names `evaluator_successor_id`, `reverification_successor_id`,
`environment_successor_id`, `expected_evaluator_pin`, `EnvironmentReverificationRefused` and
`UnsupportedEvaluatorReverification` (`application.releases`), and `advance=CLOCK.advance`. The fake clock and id source
are installed before use (`determinism.install`), so M7's own `datetime.now`/`uuid4` calls are the scripted ones."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_releases_queue  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import releases  # noqa: E402
from codex_harness.application.release_queue import ReleaseQueue  # noqa: E402
from codex_harness.application.tickets import TicketSuperseded  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
API = SimpleNamespace(
    MemoryStore=MemoryStore, queue=lambda store: ReleaseQueue(store),
    releases=lambda store: releases.Releases(store, organization()), POLICY=POLICY, TicketSuperseded=TicketSuperseded,
    evaluator_successor_id=releases.evaluator_successor_id,
    reverification_successor_id=releases.reverification_successor_id,
    environment_successor_id=releases.environment_successor_id, expected_evaluator_pin=releases.expected_evaluator_pin,
    EnvironmentReverificationRefused=releases.EnvironmentReverificationRefused,
    UnsupportedEvaluatorReverification=releases.UnsupportedEvaluatorReverification, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "review.releases_queue", s7_releases_queue.run(API))
