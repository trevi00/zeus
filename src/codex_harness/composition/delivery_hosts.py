"""Composition of the host adapters by target kind (M7 `adapters/host_delivery.host_ports`, DESIGN-s7 v2 amendment).

Layer: composition
Owns: `host_ports`, `process_reader`, the wiring of the process, managed, managed-systemd and systemd host targets
Does not own: the scheduled-task kind (W-B, not transcribed)
Entry points: host_ports
Contracts: INV-HOST-DELIVERY-001, INV-HOST-DELIVERY-MAINTENANCE-001
"""
from __future__ import annotations

from codex_harness.composition import configuration
from codex_harness.delivery.adapters.host_delivery import ProcessHostTarget
from codex_harness.delivery.adapters.host_migration import SystemdHostTarget
from codex_harness.delivery.adapters.managed_runtime import ManagedFleetTarget, SystemdManagedFleetTarget
from codex_harness.delivery.domain.host_delivery import (
    KIND_MANAGED,
    KIND_MANAGED_SYSTEMD,
    KIND_PROCESS,
    KIND_SYSTEMD,
)
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses, run_process


def process_reader():
    """`(pid) -> process identity`: the accepted `/proc` reader of INV-HOST-MIGRATION-001 for the managed generation observation
    (INV-HOST-DELIVERY-MAINTENANCE-001), built on first use so constructing a target reads nothing. The reader needs the host_os
    facts and chokepoint, which a delivery adapter may not import, so composition hands it in (S2R built it inside the adapter)."""
    reader = None

    def read(pid):
        nonlocal reader
        from codex_harness.delivery.adapters.host_migration_evidence import HostReader, boottime_offset_usec
        from codex_harness.host_os.adapters.host_facts import HostFacts

        if reader is None:
            reader = HostReader(facts=HostFacts(), processes=ChokepointProcesses())
        return reader.process(pid, boottime_offset_usec())

    return read


def host_ports(*, fleet=None, systemd_control=None, **kwargs) -> dict:
    """The host adapters by target kind, as the coordinator expects them.

    The managed Fleet target is only ever USED for a target the owner registered with that kind;
    `fleet` is its activation-gate authority; without one a managed start refuses rather than assuming
    that no execution debt exists. `systemd_control` is the validated launcher control directory of the systemd target
    (`systemd_control_dir`); without one a systemd start refuses by name."""
    processes = ChokepointProcesses()
    return {KIND_PROCESS: ProcessHostTarget(processes=processes, **kwargs),
            KIND_MANAGED: ManagedFleetTarget(fleet=fleet, processes=processes, configuration=configuration),
            # The same managed target, its guardian owned by the owner-fixed unit (aibox SPEC s14 G3).
            KIND_MANAGED_SYSTEMD: SystemdManagedFleetTarget(fleet=fleet, processes=processes, runner=run_process,
                                                           configuration=configuration,
                                                           process_reader=process_reader()),
            KIND_SYSTEMD: SystemdHostTarget(runner=run_process, control=systemd_control or {
                "control_dir": None, "reason_code": "control_dir_unconfigured"})}
