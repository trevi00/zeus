"""Composition of the host adapters by target kind (M7 `adapters/host_delivery.host_ports`, DESIGN-s7 v2 amendment).

Layer: composition
Owns: `host_ports`, the wiring of the process, managed and managed-systemd host targets
Does not own: the scheduled-task kind (W-B, not transcribed) and the systemd host kind (`SystemdHostTarget`: added when
    host_migration moves)
Entry points: host_ports
Contracts: INV-HOST-DELIVERY-001
"""
from __future__ import annotations

from codex_harness.composition import configuration
from codex_harness.delivery.adapters.host_delivery import ProcessHostTarget
from codex_harness.delivery.adapters.managed_runtime import ManagedFleetTarget, SystemdManagedFleetTarget
from codex_harness.delivery.domain.host_delivery import KIND_MANAGED, KIND_MANAGED_SYSTEMD, KIND_PROCESS
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses, run_process


def host_ports(*, fleet=None, **kwargs) -> dict:
    """The host adapters by target kind, as the coordinator expects them.

    The managed Fleet target is only ever USED for a target the owner registered with that kind;
    `fleet` is its activation-gate authority; without one a managed start refuses rather than assuming
    that no execution debt exists."""
    processes = ChokepointProcesses()
    return {KIND_PROCESS: ProcessHostTarget(processes=processes, **kwargs),
            KIND_MANAGED: ManagedFleetTarget(fleet=fleet, processes=processes, configuration=configuration),
            # The same managed target, its guardian owned by the owner-fixed unit (aibox SPEC s14 G3).
            KIND_MANAGED_SYSTEMD: SystemdManagedFleetTarget(fleet=fleet, processes=processes, runner=run_process,
                                                           configuration=configuration)}
