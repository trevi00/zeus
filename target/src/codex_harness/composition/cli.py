"""The `zeus` CLI composition: the adapters the store-free roots use (OWNER-DECISIONS-S10 #1).

Layer: composition
Owns: organization, codex_runtime, workflow, messages, release_queue (the store roots C2a builders), hook_units, incidents, sessions, execution_recovery, research_audits, executable_canary, artifacts (the hook/incident/recovery roots C2b builders), and the re-exports validate_message and resolve_codex (run_process is the module attribute codex_runtime uses)
Does not own: any root's argument shape or body (entry.cli) and the store-backed wiring of the other roots (S10 units C3-C8)
Entry points: organization, codex_runtime, validate_message, resolve_codex, run_process, workflow, messages, release_queue, hook_units, incidents, sessions, execution_recovery, research_audits, executable_canary, artifacts
Contracts: none

Replaces the M7 `bootstrap.organization`, `adapters.codex.CodexRuntime()` and `adapters.contracts.validate_message`
imports of `cli.py` (SOURCE e38aa722). M7 built `CodexRuntime()` with no runner; the target injects `run_process`.
"""

from codex_harness.execution.adapters.providers.codex_app_server import resolve_codex
from codex_harness.execution.adapters.providers.codex_exec import CodexRuntime
from codex_harness.host_os.adapters.process_groups import run_process
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.message_schema import validate_message

__all__ = ["organization", "codex_runtime", "validate_message", "resolve_codex"]


def organization():
    return packaged_organization()


def codex_runtime():
    from codex_harness.observation.domain.observation import redact_text
    return CodexRuntime(runner=run_process, redact=redact_text)  # S11 XC-1 A3: stderr tail redaction


def workflow(service):
    """The task Workflow of `service`, wired as `tests/ported/m7_coordination.Workflow.__init__` wires it (M7 `Workflow(store, org)`)."""
    from codex_harness.coordination.application import operation_finalization
    from codex_harness.coordination.application.workflow import Workflow
    from codex_harness.intake.application import tickets
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.research.application.audit_gate import require_adoption
    return Workflow(service.store, service.org, ticket_binding=tickets.ticket_binding,
                    TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption,
                    park_terminal=operation_finalization.park, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def messages(service):
    """The MessageHandler over `workflow(service)`, as `tests/ported/m7_coordination.Workflow.__init__` builds `self.messages`."""
    from codex_harness.coordination.application.messages import MessageHandler
    return MessageHandler(workflow(service))


def release_queue(service):
    """The ReleaseQueue of `service`, wired as `tests/ported/m7_delivery.ReleaseQueue` wires it (M7 `ReleaseQueue(store)`)."""
    from codex_harness.coordination.application import execution_fence
    from codex_harness.intake.application import tickets
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.review.application.release_queue import ReleaseQueue
    return ReleaseQueue(service.store, ticket_binding=tickets.ticket_binding, fences=execution_fence,
                        clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def _lifecycle(service):
    """The hook lifecycle of `service`, constructed as `tests/ported/m7_coordination.Harness.__init__` constructs `self.hooks`."""
    from codex_harness.coordination.application.events import EventJournal
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.research.application.hooks import HookLifecycle
    return HookLifecycle(service.org, outbox=Outbox(), events=EventJournal(), clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def hook_units(service):
    """The hook lifecycle calls of `service`, one store unit per call (OWNER-DECISIONS-S10 #5): `HookUnits` over the lifecycle of
    `tests/ported/m7_coordination.Harness` (the shape of `tests/ported/m7_intake._hook_unit`)."""
    from codex_harness.composition.hook_units import HookUnits
    return HookUnits(_lifecycle(service), service.store)


class Incidents:
    """`record_incident` with the unit M7's `Harness.record_incident` opened itself (`tests/ported/m7_coordination.Harness.record_incident`
    :219-225): HookUnits has no `record_incident`, so one store unit is opened per call."""

    def __init__(self, lifecycle, store):
        self.lifecycle, self.store = lifecycle, store

    def record_incident(self, message, independent_occurrence=None):
        with self.store.transaction() as tx:
            return self.lifecycle.record_incident(message, independent_occurrence=independent_occurrence, transaction=tx)


def incidents(service):
    """The incident use case of `service`: `Incidents` over the lifecycle of `tests/ported/m7_coordination.Harness`."""
    return Incidents(_lifecycle(service), service.store)


def sessions(service):
    """The session checkpoints of `service`, wired as `tests/ported/m7_intake.Harness.__init__` wires `self.sessions` (M7 `Harness.checkpoint`),
    over `workflow(service)`."""
    from codex_harness.coordination.application.sessions import SessionCheckpoints
    from codex_harness.kernel.ids import SYSTEM_IDS
    return SessionCheckpoints(service.store, service.org, workflow=workflow(service), ids=SYSTEM_IDS)


def artifacts(directory):
    """The file artifact store at `directory` (M7 `adapters.artifacts.FileArtifacts`)."""
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return FileArtifacts(directory)


def execution_recovery(service, artifacts):
    """The ExecutionRecovery of `service`, wired as `tests/ported/m7_coordination.ExecutionRecovery` wires it (M7 `ExecutionRecovery(store, org, artifacts)`)."""
    from codex_harness.coordination.application import execution_recovery as recovery
    from codex_harness.intake.application import tickets
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.research.application.audit_gate import binding as audit_binding
    return recovery.ExecutionRecovery(service.store, service.org, artifacts, ticket_binding=tickets.ticket_binding,
                                      audit_binding=audit_binding, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


def research_audits(service, artifacts):
    """The ResearchAudits of `service` with no source verifier, wired as `tests/ported/m7_research.ResearchAudits` wires it (M7
    `ResearchAudits(store, None, artifacts, Workflow(store, org))`): the decision validation is the audit-bound recovery of `m7_research._recovery`."""
    from codex_harness.coordination.application import execution_recovery as recovery
    from codex_harness.coordination.application.decisions import PendingDecisions
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
    from codex_harness.research.application import audit_gate
    from codex_harness.research.application.research import ResearchAudits
    validation = recovery.ExecutionRecovery(service.store, service.org, artifacts, audit_binding=audit_gate.binding,
                                            clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
    return ResearchAudits(service.store, None, artifacts, workflow(service), decision_validation=validation,
                          outbox=Outbox(), pending_decisions=PendingDecisions())


def executable_canary(spec):
    """The bootstrap command-hook canary of `spec`, wired as `compare/drivers/target/s8_canary.py` wires it: research's `hook_apply` and the Codex
    probe, bound here. The runtime is built inside the probe, so a missing Codex executable is the canary's own `unavailable` probe (M7 built
    `CodexRuntime()` inside `executable_canary`'s `try`)."""
    from codex_harness.research.domain.recurrence import hook_apply
    from codex_harness.review.adapters.canary import executable_canary as canary
    return canary(spec, hook_apply=hook_apply, probe=lambda: codex_runtime().probe())
