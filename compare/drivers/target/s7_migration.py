"""Target driver: `delivery.migration` on the target tree (the HostDelivery split, DESIGN-s7 V8; composed by
s7_delivery_composition). `extra` holds the names the reference API adds beyond the shared ones, from their target homes."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s7_delivery_composition  # noqa: E402
import s7_migration  # noqa: E402
from codex_harness.delivery.domain import host_delivery as domain  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.review.domain import releases as review_releases  # noqa: E402

EXTRA = {"digest": digest, "WITHDRAWN": domain.WITHDRAWN, "migration_lineage_digest": domain.migration_lineage_digest,
         "migration_request_id": domain.migration_request_id, "new_intent": domain.new_intent,
         "evaluator_successor_id": review_releases.evaluator_successor_id,
         "environment_successor_id": review_releases.environment_successor_id,
         "expected_evaluator_pin": review_releases.expected_evaluator_pin}

if __name__ == "__main__":
    driver.finish("target", "delivery.migration", s7_migration.run(s7_delivery_composition.api(**EXTRA)))
