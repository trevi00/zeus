"""Target-side composition for the S4 decision scenarios (`review.decisions`, `effects.decision_unit[.pg]`).

Layer: harness (never shipped). A target-driver helper: it imports the product, so it lives beside the target
drivers, not in common/ (scenario bodies never import the product).

It wires, by hand, what M7's `Executor` built and what composition will build (S10):
- coordination Workflow / DecisionOwnership / DecisionFailures / Outbox / EventJournal;
- review Releases; research HookLifecycle; the moved Observer;
- ReviewDecisions, with the fixture verdict behind the VerdictInvoker port.

`decide_one` reproduces M7's order: draw the owner id, claim in its own transaction, then decide outside it. The
ids and clocks are the scenario's scripted sources, injected. The observer's process run id is drawn where M7's
Executor constructor draws it (MemorySpool(new_process_run_id())).
"""

from __future__ import annotations

from types import SimpleNamespace

from codex_harness.coordination.application.decision_claims import claim_decision
from codex_harness.coordination.application.decision_recovery import release_review_policy
from codex_harness.coordination.application.decisions import DecisionFailures, DecisionOwnership
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.execution_recovery import ExecutionRecovery
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.intake.application import tickets
from codex_harness.kernel.ids import utcnow
from codex_harness.observation.adapters.observation_spool import MemorySpool
from codex_harness.observation.application.observations import (
    MemoryDirectory,
    Observer,
    PostExecutionRecordFailure,
    ReconciliationRequired,
)
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.research.domain.research import require_dispatch
from codex_harness.review.application.decisions import ReviewDecisions
from codex_harness.review.application.releases import Releases


def _no_adoption(tx, details):
    raise AssertionError("the decision scenarios never reach the research adoption gate")


class Composition:
    """The objects M7's Executor built for one case."""

    def __init__(self, store, org, git, *, clock, ids, monotonic):
        self.store, self.org, self.clock, self.ids, self.monotonic = store, org, clock, ids, monotonic
        self.observer = Observer(store, MemorySpool(ids.uuid4().hex), component="executor",
                                 directory=MemoryDirectory(), clock=lambda: utcnow(clock), monotonic=monotonic)
        self.workflow = Workflow(store, org, ticket_binding=tickets.ticket_binding,
                                 TicketSuperseded=tickets.TicketSuperseded, adoption=_no_adoption, clock=clock,
                                 ids=ids, monotonic=monotonic)
        self.recovery = ExecutionRecovery(store, org, None)
        self.releases = Releases(store, org, ticket_binding=tickets.ticket_binding, clock=clock)
        self.hooks = HookLifecycle(org, outbox=Outbox(), events=EventJournal(), clock=clock, ids=ids)
        self.git = git
        self.verdict = None
        self.decisions = ReviewDecisions(
            store, org, ownership=DecisionOwnership(self.workflow, self.recovery, org, clock=clock, ids=ids),
            failures=DecisionFailures(self.workflow, store, clock=clock, monotonic=monotonic),
            outbox=Outbox(), events=EventJournal(), releases=self.releases, hooks=self.hooks,
            observer=self.observer, invoker=SimpleNamespace(invoke=lambda *a, **k: self.verdict(*a, **k)), git=git,
            release_policy=release_review_policy, ticket_binding=tickets.ticket_binding,
            TicketSuperseded=tickets.TicketSuperseded, require_dispatch=require_dispatch,
            ReconciliationRequired=ReconciliationRequired, PostExecutionRecordFailure=PostExecutionRecordFailure,
            clock=clock, ids=ids)

    def decide_one(self, agent, expected=None):
        owner = str(self.ids.uuid4())
        decision = claim_decision(self.store, self.org, agent, owner, expected, recovery=self.recovery,
                                  ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                                  clock=self.clock, monotonic=self.monotonic)
        if not decision:
            return None
        return self.decisions.decide(agent, decision)
