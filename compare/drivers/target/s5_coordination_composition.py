"""Target composition for the S5 coordination-core families (DESIGN-s5 §M, §O, §L), the way S10 will build it.

Layer: harness (never shipped)

One scripted clock and id source per driver process (FakeClock/FakeIds through the target ports), shared by every
object composed here, as the reference's patched module globals are shared. `WorkflowAndMessages` is the golden's one
M7 `Workflow` (S4 task ownership + the S5 MessageHandler with the real terminal-operation park). `Service` stands for
what M7's `Harness` gave LocalCycle/Operation: the store and organization, the outbox flusher (with observation's
health owner operation) and the incident use case (a unit around research's HookLifecycle owner operation).
"""

import functools
from types import SimpleNamespace

import determinism
from codex_harness.coordination.application import execution_time, operation_finalization
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.local_cycle import LocalCycle
from codex_harness.coordination.application.messages import MessageHandler
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.coordination.application.outbox_relay import OutboxFlusher
from codex_harness.coordination.application.workflow import ClaimGuardRefused, Workflow
from codex_harness.intake.application import tickets
from codex_harness.kernel.message import envelope
from codex_harness.observation.application.health import HealthRecords
from codex_harness.research.application.audit_gate import require_adoption
from codex_harness.research.application.hooks import HookLifecycle
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore
from codex_harness.storage.adapters.message_schema import validate_message
from codex_harness.storage.ports import MessageDeliveryError
from s1_target import PortClock, PortIds

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, IDPORT = PortClock(CLOCK), PortIds(IDS)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000e5e5"  # this process's clock-domain identity
ORG = packaged_organization()


class WorkflowAndMessages:
    """Task ownership from the S4 Workflow, messages from the MessageHandler over it."""

    MESSAGE_METHODS = ("handle", "cancel", "request_rebase", "context")

    def __init__(self, store):
        self.workflow = Workflow(store, ORG, ticket_binding=tickets.ticket_binding,
                                 TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption,
                                 park_terminal=functools.partial(operation_finalization.park, clock=PORT),
                                 clock=PORT, ids=IDPORT, monotonic=CLOCK.monotonic)
        self.messages = MessageHandler(self.workflow)

    def __getattr__(self, name):
        return getattr(self.messages if name in self.MESSAGE_METHODS else self.workflow, name)


class Service:
    def __init__(self, store):
        self.store, self.org = store, ORG
        self.flusher = OutboxFlusher(store, ORG, health=HealthRecords().record, clock=PORT, ids=IDPORT)
        self.hooks = HookLifecycle(ORG, outbox=Outbox(), events=EventJournal(), clock=PORT, ids=IDPORT)

    def flush_outbox(self, bus, limit=100, audit=None, correlation_id=None):
        return self.flusher.flush(bus, limit, audit, correlation_id)

    def record_incident(self, message):
        with self.store.transaction() as tx:  # M7 Harness.record_incident opened this unit itself
            return self.hooks.record_incident(message, transaction=tx)


def local_cycle(service, executor=None, bus=None, workflow=None, observer=None):
    return LocalCycle(service.store, service.org, flusher=service.flusher, incidents=service.record_incident,
                      executor=executor, bus=bus, workflow=workflow, observer=observer, clock=PORT)


def api(**extra):
    base = SimpleNamespace(MemoryStore=MemoryStore, service=Service, workflow=WorkflowAndMessages,
                           LocalCycle=local_cycle, ClaimGuardRefused=ClaimGuardRefused,
                           validate_message=validate_message, MessageDeliveryError=MessageDeliveryError,
                           envelope=functools.partial(envelope, clock=PORT, ids=IDPORT), advance=CLOCK.advance,
                           org=ORG)
    for key, value in extra.items():
        setattr(base, key, value)
    return base
