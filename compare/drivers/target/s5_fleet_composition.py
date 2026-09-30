"""Target composition for the S5 Fleet families (DESIGN-s5 §F), the way S10 composition will build it.

Layer: harness (never shipped)

The goldens call one M7-shaped `Fleet`; the target has four objects (FleetRegistry, AdmissionControl, FleetPause,
FleetRecovery) over the same store, clock and owner-token source. `FleetFacade` routes each golden call to its owner
and to nothing else, so a call reaching the wrong object fails loudly instead of being answered by a fallback.
"""

from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.pause import FleetPause
from codex_harness.coordination.application.fleet.recovery import FleetRecovery
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.fleet.runner import FleetRunner
from codex_harness.coordination.domain import fleet as fleet_domain
from codex_harness.coordination.domain import operation as operation_domain
from codex_harness.routing.adapters.provider_policy import packaged_policy
from codex_harness.storage.adapters.memory_store import MemoryStore

ROUTES = {
    "registry": ("register", "registered", "enqueue", "record_delivery", "delivery", "reconciliation_required",
                 "status"),
    "admission": ("admit_one", "reserve_unit", "settle_unit", "units", "held_units", "finalize"),
    "pause": ("pause", "resume", "activation_gate", "release_activation_hold", "authorize_budget", "budget_grants"),
    "recovery": ("reconcile_interrupted", "recovery", "relocate", "migrate_host", "relocations"),
}
OWNER = {method: owner for owner, methods in ROUTES.items() for method in methods}


class FleetFacade:
    def __init__(self, store, clock, token):
        self.store = store
        self.registry = FleetRegistry(store, clock=clock, token=token)
        self.admission = AdmissionControl(store, clock=clock, token=token)
        self.pause_control = FleetPause(store, clock=clock, token=token)
        self.recovery_control = FleetRecovery(store, clock=clock, token=token)

    def __getattr__(self, name):
        owner = OWNER.get(name)
        if owner is None:
            raise AttributeError(name)
        return getattr({"registry": self.registry, "admission": self.admission, "pause": self.pause_control,
                        "recovery": self.recovery_control}[owner], name)


POLICY = packaged_policy()


def api(**extra):
    base = dict(MemoryStore=MemoryStore, Fleet=FleetFacade,
                FleetRunner=lambda fleet, launcher, sleep, interval, **ports: FleetRunner(
                    fleet.registry, fleet.admission, fleet.pause_control, launcher, sleep=sleep, interval=interval,
                    **ports),
                LaunchRefused=fleet_domain.LaunchRefused, validate_config=fleet_domain.validate_config,
                validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY))
    base.update(extra)
    return base
