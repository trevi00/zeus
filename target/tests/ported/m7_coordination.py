"""M7 `Fleet`, `FleetRunner` and `Workflow` surface over the S5 target, for the ported M7 coordination suites.

Layer: harness (never shipped). A TEST shim: it lets M7 `tests/test_fleet.py` and `tests/test_workflow.py` run, with
their assertions unchanged, against the objects DESIGN-s5 §F/§M built from them. The wiring mirrors
`compare/drivers/target/s5_fleet_composition.py` (Fleet) and `s5_coordination_composition.py` (Workflow); ids and
clocks are NOT scripted here: as in M7 the real clock and uuid4 are used (kernel `utcnow`, SYSTEM_CLOCK/SYSTEM_IDS).

Named adaptations (each is a construction/import adaptation, never a behaviour change):
- `Fleet(store, clock=utcnow, token=lambda: uuid4().hex)` is a facade over `FleetRegistry`, `AdmissionControl`,
  `FleetPause` and `FleetRecovery`. It routes each M7 method to its owning object with the golden composition's
  route table and to nothing else (an unrouted name raises AttributeError, never a fallback). It exposes `.store`
  (so `.store.data` reads as in M7) and the four owners as `.registry`, `.admission`, `.pause_control`,
  `.recovery_control`. Its `pause` and `resume` routes are the `FleetPause` methods of the same names.
- `FleetRunner(fleet, launcher, sleep=time.sleep, interval=5.0, **ports)` builds the target
  `fleet.runner.FleetRunner(fleet.registry, fleet.admission, fleet.pause_control, launcher, ...)`: M7's runner held
  one `Fleet`, the target's holds the three objects it drives.
- `LaunchRefused` is re-exported from `coordination.domain.fleet` (M7 `application.fleet.LaunchRefused`).
- `Workflow(store, organization)` is a facade over the target S4 `Workflow` built with intake's
  `tickets.ticket_binding`/`TicketSuperseded`, research's `require_adoption`, `operation_finalization.park` as the
  terminal park and the system clock/ids. `handle`, `cancel`, `request_rebase` and `context` route to the S5
  `MessageHandler` over it (M7 had them on `Workflow`); everything else routes to the S4 Workflow.
- `organization()` is `routing.adapters.organization_source.packaged_organization` (M7 `bootstrap.organization`) and
  `packaged_policy` is `routing.adapters.provider_policy.packaged_policy` (M7 `adapters.providers.packaged_policy`).
"""

from __future__ import annotations

import time
from uuid import uuid4

from codex_harness.coordination.application import operation_finalization
from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.pause import FleetPause
from codex_harness.coordination.application.fleet.recovery import FleetRecovery
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.fleet.runner import FleetRunner as _FleetRunner
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.coordination.application.workflow import Workflow as _Workflow
from codex_harness.coordination.domain.fleet import LaunchRefused
from codex_harness.intake.application import tickets
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, utcnow
from codex_harness.research.application.audit_gate import require_adoption
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.routing.adapters.provider_policy import packaged_policy

__all__ = ["Fleet", "FleetRunner", "LaunchRefused", "Workflow", "organization", "packaged_policy"]

ROUTES = {
    "registry": ("register", "registered", "enqueue", "record_delivery", "delivery", "reconciliation_required",
                 "status"),
    "admission": ("admit_one", "reserve_unit", "settle_unit", "units", "held_units", "finalize"),
    "pause": ("pause", "resume", "activation_gate", "release_activation_hold", "authorize_budget", "budget_grants"),
    "recovery": ("reconcile_interrupted", "recovery", "relocate", "migrate_host", "relocations"),
}
OWNER = {method: owner for owner, methods in ROUTES.items() for method in methods}


class Fleet:
    def __init__(self, store, clock=utcnow, token=lambda: uuid4().hex):
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


def FleetRunner(fleet, launcher, sleep=time.sleep, interval=5.0, **ports):  # noqa: N802 - the M7 constructor name
    return _FleetRunner(fleet.registry, fleet.admission, fleet.pause_control, launcher, sleep=sleep,
                        interval=interval, **ports)


class Workflow:
    """Task ownership from the S4 Workflow, messages from the MessageHandler over it."""

    MESSAGE_METHODS = ("handle", "cancel", "request_rebase", "context")

    def __init__(self, store, organization):
        self.workflow = _Workflow(store, organization, ticket_binding=tickets.ticket_binding,
                                  TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption,
                                  park_terminal=operation_finalization.park, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
        self.messages = MessageHandler(self.workflow)

    def __getattr__(self, name):
        return getattr(self.messages if name in self.MESSAGE_METHODS else self.workflow, name)


def organization():
    return packaged_organization()
