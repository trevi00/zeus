"""Target driver: `delivery.managed_systemd` on the target tree (S7 pilot 43).

The managed names are `s7_managed_composition`'s (the moved adapters wired as in `s7_managed_runtime`); the coordinator
is the S7 V8 delivery composition (`s7_delivery_composition.HostDelivery`, harness only) with its review ports and
`organization`/`releases`, and the supervise snippet's module is the target's permanent shim. The driver clock is the
delivery composition's, so the controller and the review ports share one timeline, kept on the real wall time by
`sync_clock` because the live children write real heartbeats."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s7_delivery_composition  # noqa: E402
import s7_managed_composition  # noqa: E402
import s7_managed_systemd  # noqa: E402
from codex_harness.context.adapters import worker_profile  # noqa: E402
from codex_harness.delivery.adapters import host_delivery  # noqa: E402
from codex_harness.delivery.application.host_delivery import state as delivery_state  # noqa: E402
from codex_harness.host_os.adapters.git_workspace import MergeRefused  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402


def sync_clock():
    """No-op: the target driver installs no determinism; its clock is the real wall time."""


API = SimpleNamespace(
    **s7_managed_composition.names(),
    effective_profile_digest=lambda: host_delivery.effective_profile_digest(worker_profile),
    owner_qualified_canary=host_delivery.owner_qualified_canary,
    startup_identity_canary=host_delivery.startup_identity_canary,
    HostDelivery=lambda store, org, **ports: s7_delivery_composition.HostDelivery(store, org, **ports),
    BUCKET_INTENTS=delivery_state.BUCKET_INTENTS, organization=packaged_organization,
    releases=lambda store: s7_delivery_composition.releases_for(store, packaged_organization()),
    MergeRefused=MergeRefused, ContractError=ContractError,
    SOURCE_PACKAGE=Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "src" / "codex_harness",
    sync_clock=sync_clock, reset_ids=lambda: None)

if __name__ == "__main__":
    driver.finish("target", "delivery.managed_systemd", s7_managed_systemd.run(API))
