"""Target composition for the S6 owner-action families (harness only, never shipped).

`OwnerActions` composes the split objects of `coordination.application.owner_actions` (DESIGN-s6 §4) with the M7
constructor's ports and routes the M7 public surface to their owners. Research's ResearchPrograms port is the S6
moved-ahead `ProgramState` over the same control store and clock (M7 constructed `ResearchProgram(store, clock)`).
The G1 decision envelope gets the S5 scripted clock/id ports (R6), the sequence the reference patches globally.
"""

from codex_harness.coordination.application.owner_actions.actions import ActionStore
from codex_harness.coordination.application.owner_actions.canary import CanaryFamily
from codex_harness.coordination.application.owner_actions.delivery_plan import (
    DeliveryRegistrationFamily,
)
from codex_harness.coordination.application.owner_actions.migration import MigrationRequestFamily
from codex_harness.coordination.application.owner_actions.requalify import RequalifyFamily
from codex_harness.coordination.application.owner_actions.research_acceptance import (
    ResearchAcceptanceFamily,
)
from codex_harness.coordination.application.owner_actions.research_dispatch import (
    ResearchLaunchFamily,
)
from codex_harness.coordination.application.owner_actions.scheduler import OwnerActionScheduler
from codex_harness.coordination.domain import owner_actions as owner_domain
from codex_harness.kernel.ids import canonical, utcnow
from codex_harness.research.application.program_state import ProgramState
from codex_harness.routing.adapters.organization_source import packaged_organization
from s5_coordination_composition import IDPORT, PORT
from s6_continuation_composition import api as continuation_api

ROUTES = {"register": "scheduler", "status": "scheduler", "tick": "scheduler", "recover_canary": "canary",
          "request_migration": "migration", "migration": "migration"}


class OwnerActions:
    def __init__(self, store, *, continuation=None, org=None, lanes=None, deliveries=None, publisher=None,
                 assessments=None, targets=None, fleet=None, validate=None, first_activation=None, clock=utcnow,
                 withdrawals=None, mainline=None, requalify=None, artifacts=None, research=None, ledger=None):
        actions = ActionStore(store, clock=clock)
        research_acceptance = ResearchAcceptanceFamily(store, assessments=assessments, continuation=continuation,
                                                       lanes=lanes, org=org, message_clock=PORT, ids=IDPORT,
                                                       actions=actions)
        delivery_plan = DeliveryRegistrationFamily(store, deliveries=deliveries, first_activation=first_activation,
                                                   publisher=publisher, targets=targets, actions=actions)
        canary = CanaryFamily(store, clock=clock, deliveries=deliveries, fleet=fleet, lanes=lanes, org=org,
                              targets=targets, validate=validate, actions=actions)
        migration = MigrationRequestFamily(store, clock=clock, deliveries=deliveries, publisher=publisher,
                                           targets=targets, delivery_plan=delivery_plan)
        requalify_family = RequalifyFamily(store, artifacts=artifacts, clock=clock, continuation=continuation,
                                           deliveries=deliveries, mainline=mainline, requalify=requalify,
                                           withdrawals=withdrawals, actions=actions)
        research_dispatch = ResearchLaunchFamily(store, clock=clock, ledger=ledger, research=research,
                                                 programs=ProgramState(store, clock=clock), actions=actions)
        scheduler = OwnerActionScheduler(store, clock=clock, continuation=continuation, actions=actions, canary=canary,
                                         delivery_plan=delivery_plan, migration=migration,
                                         requalify_family=requalify_family, research_acceptance=research_acceptance,
                                         research_dispatch=research_dispatch)
        self.objects = {"scheduler": scheduler, "canary": canary, "migration": migration}

    def __getattr__(self, name):
        owner = ROUTES.get(name)
        if owner is None:
            raise AttributeError(name)
        return getattr(self.objects[owner], name)


def api(**extra):
    base = continuation_api(OwnerActions=lambda store, **ports: OwnerActions(store, **ports),
                            organization=packaged_organization, canonical=canonical, owner_domain=owner_domain)
    base.update(extra)
    return base
