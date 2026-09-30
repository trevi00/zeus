"""Target driver: `delivery.owner_commands` on the target tree (the HostDelivery split, DESIGN-s7 V8; composed by
s7_delivery_composition)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s7_delivery_composition  # noqa: E402
import s7_owner_commands  # noqa: E402
from codex_harness.delivery.domain import host_delivery as domain  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402

# The names the owner-command cases use beyond the shared delivery API (their target homes).
EXTRA = ("WITHDRAWN", "UNCHANGED", "new_intent", "WITHDRAW_REASONS", "RECOVERY_VERIFICATION_MISSING",
         "RECOVERY_FIRST_ACTIVATION", "RECOVERY_CONSUMPTION_REARM", "RECOVERY_GENERATION_RESTART",
         "FIRST_ACTIVATION_SCHEMA", "CONSUMPTION_RETRY_SCHEMA", "CONSUMPTION_REARM_SCHEMA",
         "GENERATION_RESTART_SCHEMA", "CONSUMPTION_RETRY_RESTART_FIELD", "CONSUMPTION_REARM_MAX_SECONDS",
         "GENERATION_RESTART_REASONS", "RESTART_REQUESTED", "RESTART_LAUNCHED", "RESTART_STARTED",
         "validate_first_activation", "validate_consumption_retry", "validate_consumption_rearm",
         "validate_generation_restart", "resumable", "first_activation_resumable",
         "first_activation_unbound", "consumption_retryable", "consumption_retry_exhausted",
         "consumption_rearmable", "consumption_rearm_exhausted", "generation_restartable",
         "resolve_descriptor")

if __name__ == "__main__":
    driver.finish("target", "delivery.owner_commands", s7_owner_commands.run(s7_delivery_composition.api(
        digest=digest, **{name: getattr(domain, name) for name in EXTRA})))
