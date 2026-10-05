"""The `zeus` CLI composition: the cycle and serve roots (S10 unit C5e, R-c22).

Layer: composition
Owns: local_cycle, serve_handler, incident_recorder
Does not own: any root's argument shape or body (entry.cli) and the bus, flusher and observer builders (composition.cli_bus, composition.observation)
Entry points: local_cycle, serve_handler, incident_recorder
Contracts: INV-LOCAL-CYCLE-001, INV-MESSAGE-001

Replaces `LocalCycle(service, executor, bus, workflow, observer)` and `Workflow(service.store, service.org)` of M7 `cli.py` (SOURCE
e38aa722:449-469, 83-): `local_cycle` wires the S5 `LocalCycle` as `tests/ported/m7_coordination.LocalCycle` does (the service's
store and organization, the flusher of R-c8, the incident recorder, the system clock), `serve_handler` is the `MessageHandler` M7's
`workflow.handle` became (`composition.cli.messages`) and `incident_recorder` is `service.record_incident` (`composition.cli.incidents`).
Imports sit inside the functions, so importing this module stays light.
"""


def incident_recorder(service):
    """`service.record_incident` of M7's `Harness`: one store unit per call (`composition.cli.incidents`)."""
    from codex_harness.composition import cli
    return cli.incidents(service).record_incident


def serve_handler(service, observer=None):
    """The message handler of `serve` and of the cycle step: `workflow.handle` of M7 (`composition.cli.messages`)."""
    from codex_harness.composition import cli
    return cli.messages(service, observer)


def local_cycle(service, executor=None, bus=None, workflow=None, observer=None):
    from codex_harness.composition import cli_bus
    from codex_harness.coordination.application.local_cycle import LocalCycle
    from codex_harness.kernel.ids import SYSTEM_CLOCK
    return LocalCycle(service.store, service.org, flusher=cli_bus.flusher(service), incidents=incident_recorder(service),
                      executor=executor, bus=bus, workflow=workflow, observer=observer, clock=SYSTEM_CLOCK)
