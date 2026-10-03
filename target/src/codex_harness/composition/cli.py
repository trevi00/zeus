"""The `zeus` CLI composition: the adapters the store-free roots use (OWNER-DECISIONS-S10 #1).

Layer: composition
Owns: organization, codex_runtime, workflow, messages, release_queue (the store roots C2a builders), and the re-exports validate_message and resolve_codex
Does not own: any root's argument shape or body (entry.cli) and the store-backed wiring of the other roots (S10 units C2b-C8)
Entry points: organization, codex_runtime, validate_message, resolve_codex, workflow, messages, release_queue
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
    return CodexRuntime(runner=run_process)


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
