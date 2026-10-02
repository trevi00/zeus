"""Reference driver: `research.threshold_reviews` (M7 `application.threshold_reviews`: `ThresholdReviews`).

The API holds plain M7 objects:
- `adapters.store`: `MemoryStore`; `bootstrap.organization` (the packaged organization); `application.workflow.Workflow`;
  `application.threshold_reviews.ThresholdReviews`; `domain.model.digest`; `domain.policy.POLICY.max_attempts`;
- `claim(store, org, artifacts, actor)`: the ORDINARY claim, M7 `Executor.decide_one` stopped at the V20 adapter boundary (the one
  LABELLED stub: `adapters.threshold_reviews.review_threshold` records the lease and raises a `BaseException`, so `decide_one`'s own
  `except Exception` never sees it). The executor's process run id is drawn where its constructor draws it, then the id counter is put
  back so the owner id is the next scripted id, as the target caller draws it;
- `records(store, org, artifacts)`: the reference of V22 R-tr3, LABELLED: M7 has no such object; `row` is what
  `application/execution_recovery.py:94` builds (`ThresholdReviews(Workflow(store, org), artifacts)._row`) and `restore` is the inline
  put of `:252`.
The clock and the id source are the harness's (`determinism.install`, with the import-time execution domain pinned); `advance` ticks the
fake clock."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_threshold_reviews  # noqa: E402

from codex_harness.adapters import threshold_reviews as adapter  # noqa: E402
from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.application.threshold_reviews import ThresholdReviews  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000a0d2"}})
ROOT = Path("/tmp/zeus-rebuild-s8-threshold-reviews")


class Boundary(BaseException):
    """Raised at the adapter boundary (the V20 `review_threshold`)."""


def claim(store, org, artifacts, actor):
    seen = {}

    def review_threshold(executor, lease, verdict):
        seen["lease"] = lease
        raise Boundary()

    position = IDS.counter
    executor = Executor(Harness(store, org), SimpleNamespace(repository=ROOT), artifacts)
    IDS.counter = position  # the constructor's process run id is the composition's, not a step of the scenario
    original, adapter.review_threshold = adapter.review_threshold, review_threshold
    try:
        executor.decide_one(actor)
    except Boundary:
        return seen["lease"]
    finally:
        adapter.review_threshold = original
    return None


class Records:
    def __init__(self, store, org, artifacts):
        self.reviews = ThresholdReviews(Workflow(store, org), artifacts)

    def row(self, tx, row_id):
        return self.reviews._row(tx, row_id)

    @staticmethod
    def restore(tx, request):
        tx.put("threshold_review_requests", request["id"], request)


API = SimpleNamespace(
    MemoryStore=MemoryStore, organization=organization, digest=digest, max_attempts=POLICY.max_attempts, claim=claim,
    reviews=lambda store, org, artifacts: ThresholdReviews(Workflow(store, org), artifacts), exhausted=ThresholdReviews.exhausted,
    records=Records, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.threshold_reviews", s8_threshold_reviews.run(API))
