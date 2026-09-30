"""Target driver: `coordination.owner_actions_delivery` on the target tree: the S6 moved owner-action families
(`s6_owner_actions_composition.OwnerActions`, the S6 continuation composition behind it) over the S7 V8 delivery split
(`s7_delivery_composition.HostDelivery`). Harness composition only; the reference API's names come from their target homes."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s6_owner_actions_composition  # noqa: E402
import s7_delivery_composition  # noqa: E402
import s7_owner_actions_delivery  # noqa: E402
from codex_harness.delivery.domain import host_delivery as domain  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402

# The names the s7 delivery API does not carry; a name in both APIs must be the same object.
EXTRA = {"digest": digest, "UNCHANGED": domain.UNCHANGED, "WITHDRAWN": domain.WITHDRAWN,
         "migration_lineage_digest": domain.migration_lineage_digest,
         "migration_request_id": domain.migration_request_id, "new_intent": domain.new_intent}


def api() -> SimpleNamespace:
    owner = s6_owner_actions_composition.api()
    delivery = vars(s7_delivery_composition.api(**EXTRA))
    for name in owner.keys() & delivery.keys():
        assert owner[name] is delivery[name], name
    merged = {**owner, **delivery}
    merged["dc"] = merged.pop("domain")
    return SimpleNamespace(**merged)


if __name__ == "__main__":
    driver.finish("target", "coordination.owner_actions_delivery", s7_owner_actions_delivery.run(api()))
