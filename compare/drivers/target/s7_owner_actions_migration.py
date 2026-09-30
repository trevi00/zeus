"""Target driver: `coordination.owner_actions_migration` on the target tree: the S6 moved owner-action families
(`s6_owner_actions_composition.OwnerActions`, whose `MigrationRequestFamily` owns `request_migration`, `migration` and the
migration steps, with its `delivery_plan` collaborator) over the S7 V8 delivery split (`s7_delivery_composition.HostDelivery`),
and the S6 continuation composition (`Continuation`, `Fleet`, `LaneEvidence`) for the paused source. Harness composition only:
pilot 29's composition (`s7_owner_actions_delivery`) and the two accessors of the reference API at their split homes."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s6_owner_actions_composition  # noqa: E402
import s7_delivery_composition  # noqa: E402
import s7_owner_actions_migration  # noqa: E402
from codex_harness.coordination.application.continuation import lanes  # noqa: E402
from codex_harness.delivery.domain import host_delivery as domain  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402

# The names the s7 delivery API does not carry; a name in both APIs must be the same object.
EXTRA = {"digest": digest, "UNCHANGED": domain.UNCHANGED, "WITHDRAWN": domain.WITHDRAWN,
         "migration_lineage_digest": domain.migration_lineage_digest,
         "migration_request_id": domain.migration_request_id, "new_intent": domain.new_intent}
# The M7 private helpers, at their split homes: `OwnerActions._plan_binding` is the delivery-plan family's `plan_binding`
# (the migration family's `delivery_plan` collaborator); `continuation._migrated_delivery` is in `lanes`.
ACCESSORS = {"plan_binding_of": lambda owner, policy_row, intent: owner.objects["migration"].delivery_plan.plan_binding(
    policy_row, intent), "migrated_delivery": lanes._migrated_delivery}


def api() -> SimpleNamespace:
    owner = s6_owner_actions_composition.api()
    delivery = vars(s7_delivery_composition.api(**EXTRA))
    for name in owner.keys() & delivery.keys():
        assert owner[name] is delivery[name], name
    merged = {**owner, **delivery, **ACCESSORS}
    merged["dc"] = merged.pop("domain")
    return SimpleNamespace(**merged)


if __name__ == "__main__":
    driver.finish("target", "coordination.owner_actions_migration", s7_owner_actions_migration.run(api()))
