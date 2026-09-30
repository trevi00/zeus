"""Target composition for the S6 continuation families (harness only, never shipped).

`Continuation` composes the split objects of `coordination.application.continuation` (DESIGN-s6 §3) and routes the M7
public surface to their owners, as S5's FleetFacade did. There is no facade in the product's application layer;
production composition is S10. The collaborators are the M7 constructor's: store, fleet, lanes, conductor, validate,
observer, clock, evidence. Intake's PortfolioLineage port is the S6 moved-ahead implementation. `_note` routes to
`IntentStore.note` for the unit family's stale-writer injection (M7 exposed it on the one class).
"""

from codex_harness.coordination.application.continuation.frames import PolicyFrames
from codex_harness.coordination.application.continuation.grants import CapacityGrants
from codex_harness.coordination.application.continuation.intents import IntentStore
from codex_harness.coordination.application.continuation.lanes import (
    MAX_MIGRATION_HOPS,
    LaneEvidence,
)
from codex_harness.coordination.application.continuation.ownership import OwnershipReconciliation
from codex_harness.coordination.application.continuation.requalification import Requalification
from codex_harness.coordination.application.continuation.research import ResearchAcceptance
from codex_harness.coordination.application.continuation.settlement import LaunchSettlement
from codex_harness.coordination.application.continuation.successors import Successors
from codex_harness.coordination.application.continuation.tick import ContinuationTick
from codex_harness.coordination.domain import continuation as continuation_domain
from codex_harness.coordination.domain import operation as operation_domain
from codex_harness.coordination.domain.fleet import repository_identity
from codex_harness.intake.application.portfolio_lineage import PortfolioLineage
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow
from codex_harness.routing.adapters.provider_policy import packaged_policy
from codex_harness.storage.adapters.memory_store import MemoryStore
from s5_fleet_composition import FleetFacade

ROUTES = {"register": "frames", "policy": "frames", "status": "frames", "unresolved": "frames",
          "accept_research": "research", "supplement_research_scope": "research", "research_facts": "research",
          "tick": "tick", "drain": "settlement", "reconcile_ownership": "ownership", "grant_capacity": "grants",
          "requalify_delivery": "requalification"}


class Continuation:
    def __init__(self, store, fleet=None, lanes=None, conductor=None, validate=None, observer=None, clock=utcnow,
                 evidence=None):
        self.store = store
        intents = IntentStore(store, clock=clock, observer=observer)
        successors = Successors(store, clock=clock, validate=validate, portfolio=PortfolioLineage())
        research = ResearchAcceptance(store, clock=clock, evidence=evidence, lanes=lanes)
        grants = CapacityGrants(store, clock=clock, lanes=lanes, intents=intents, research=research,
                                successors=successors)
        requalification = Requalification(store, clock=clock, lanes=lanes, validate=validate, intents=intents,
                                          research=research)
        frames = PolicyFrames(store, clock=clock, grants=grants, intents=intents, requalification=requalification)
        settlement = LaunchSettlement(store, conductor=conductor, fleet=fleet, lanes=lanes, frames=frames,
                                      intents=intents)
        tick = ContinuationTick(store, conductor=conductor, fleet=fleet, lanes=lanes, frames=frames, intents=intents,
                                research=research, settlement=settlement, successors=successors)
        self.objects = {"intents": intents, "frames": frames, "research": research, "successors": successors,
                        "grants": grants, "requalification": requalification, "settlement": settlement,
                        "tick": tick, "ownership": OwnershipReconciliation(store, successors=successors)}

    def _note(self, intent, **fields):
        return self.objects["intents"].note(intent, **fields)

    def __getattr__(self, name):
        owner = ROUTES.get(name)
        if owner is None:
            raise AttributeError(name)
        return getattr(self.objects[owner], name)


POLICY = packaged_policy()


def api(**extra):
    base = dict(MemoryStore=MemoryStore, Fleet=FleetFacade, LaneEvidence=LaneEvidence,
                Continuation=lambda store, *, fleet, lanes, conductor, validate, clock, evidence=None: Continuation(
                    store, fleet=fleet, lanes=lanes, conductor=conductor, validate=validate, clock=clock,
                    evidence=evidence),
                validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
                repository_identity=repository_identity, ContractError=ContractError, domain=continuation_domain,
                migration_source=continuation_domain.migration_source,
                migration_resume=continuation_domain.migration_resume, MAX_MIGRATION_HOPS=MAX_MIGRATION_HOPS)
    base.update(extra)
    return base
