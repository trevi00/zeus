"""Target driver: `coordination.owner_actions_canary` on the target tree: the S6 moved owner-action families
(`s6_owner_actions_composition.OwnerActions`, whose `CanaryFamily` owns `_canary_binding`, `_advance_canary`,
`_canary_still_bound` and `recover_canary`) over the S7 V8 delivery split (`s7_delivery_composition.HostDelivery`). Harness
composition only: pilot 29's composition (`s7_owner_actions_delivery`), the delivery owner-command names of
`delivery.owner_commands`, and the three accessors of the reference API at their split homes."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s6_owner_actions_composition  # noqa: E402
import s7_delivery_composition  # noqa: E402
import s7_owner_actions_canary  # noqa: E402
from codex_harness.delivery.domain import host_delivery as domain  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402

# The names the s7 delivery API does not carry (the reference API's `NAMES`, less what the composition supplies): their
# target homes. A name in both APIs must be the same object.
EXTRA_NAMES = ("UNCHANGED", "WITHDRAWN", "migration_lineage_digest", "migration_request_id", "new_intent",
               "WITHDRAW_REASONS", "RECOVERY_VERIFICATION_MISSING", "RECOVERY_FIRST_ACTIVATION",
               "RECOVERY_CONSUMPTION_REARM", "RECOVERY_GENERATION_RESTART", "FIRST_ACTIVATION_SCHEMA",
               "CONSUMPTION_RETRY_SCHEMA", "CONSUMPTION_REARM_SCHEMA", "GENERATION_RESTART_SCHEMA",
               "CONSUMPTION_RETRY_RESTART_FIELD", "CONSUMPTION_REARM_MAX_SECONDS", "GENERATION_RESTART_REASONS",
               "RESTART_REQUESTED", "RESTART_LAUNCHED", "RESTART_STARTED", "validate_first_activation",
               "validate_consumption_retry", "validate_consumption_rearm", "validate_generation_restart", "resumable",
               "first_activation_resumable", "first_activation_unbound", "consumption_retryable",
               "consumption_retry_exhausted", "consumption_rearmable", "consumption_rearm_exhausted",
               "generation_restartable", "resolve_descriptor")
EXTRA = {"digest": digest, **{name: getattr(domain, name) for name in EXTRA_NAMES}}
# The M7 private methods, at their split homes on the target's CanaryFamily (`owner.objects["canary"]`).
ACCESSORS = {
    "advance_canary": lambda owner, policy_row, continuation, action: owner.objects["canary"].advance(
        policy_row, continuation, action),
    "canary_binding_of": lambda owner, plan_action: owner.objects["canary"].canary_binding(plan_action),
    "canary_still_bound": lambda owner, plan_action, action: owner.objects["canary"].still_bound(plan_action, action)}


def api() -> SimpleNamespace:
    owner = s6_owner_actions_composition.api()
    delivery = vars(s7_delivery_composition.api(**EXTRA))
    for name in owner.keys() & delivery.keys():
        assert owner[name] is delivery[name], name
    merged = {**owner, **delivery, **ACCESSORS}
    merged["dc"] = merged.pop("domain")
    return SimpleNamespace(**merged)


if __name__ == "__main__":
    driver.finish("target", "coordination.owner_actions_canary", s7_owner_actions_canary.run(api()))
