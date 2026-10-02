"""Target driver: `intake.frontdesk_adapter` on the target tree (S8 pilot 90: the V17 P-b split move, the execute side in
`intake.adapters.frontdesk` and the monitoring evidence in `observation.adapters.desk_monitoring`).

The API mirrors the reference driver's names over the target homes. M7's `Harness` is the S5 composition's `Service` and the desk the moved
`FrontDesk` with coordination's `Outbox` wired (as in the `intake.frontdesk` driver); the harness's scripted clock and ids reach the kernel through the
`Clock` and id ports, exactly as there. The merged `constants` read each name from the module that now owns it. `default_path` is None: the target has no
`snapshot_path` (V17 R-m1) and refuses `snapshot=None` (R-f1), so the reference's `s6_snapshot_none` and `s7_default_path` groups are the scenario's two
declared intended differences; the driver records nothing for them. As in the reference driver `datetime` is the class the modules use (the target's
standard library is never patched)."""

import contextlib
import datetime as stdlib_datetime
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_frontdesk_adapter  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.intake.adapters import frontdesk as execute_side  # noqa: E402
from codex_harness.intake.application import frontdesk as application  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.observation.adapters import desk_monitoring as monitoring_side  # noqa: E402
from codex_harness.observation.adapters.monitoring_readiness import readiness  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
application.uuid4 = composition.IDS.uuid4   # the default owner token: the harness id source, as the reference run installed it


class FrontDesk(application.FrontDesk):
    """The moved class with its outbox port wired (a subclass: the scenario builds it from the service and revision alone)."""

    def __init__(self, service, base_revision, *args, **kwargs):
        super().__init__(service, base_revision, *args, outbox=Outbox(), **kwargs)


@contextlib.contextmanager
def max_bytes(value):
    """The M7 test's `monkeypatch.setattr(..., "MONITORING_MAX_BYTES", 10)`, over the module that now owns the constant."""
    saved = monitoring_side.MONITORING_MAX_BYTES
    monitoring_side.MONITORING_MAX_BYTES = value
    try:
        yield
    finally:
        monitoring_side.MONITORING_MAX_BYTES = saved


def constant(name):
    return getattr(monitoring_side if hasattr(monitoring_side, name) else execute_side, name)


API = SimpleNamespace(
    datetime=stdlib_datetime.datetime, MemoryStore=MemoryStore, FrontDesk=FrontDesk, message_id_of=application.message_id_of,
    Harness=lambda store, org: composition.Service(store), organization=lambda: composition.ORG,
    advance=composition.CLOCK.advance, reset=lambda: (composition.CLOCK.reset(), composition.IDS.reset()),
    execute_frontdesk=execute_side.execute_frontdesk, clean_checkout=execute_side.clean_checkout, monitoring_facts=monitoring_side.monitoring_facts,
    monitoring_evidence=monitoring_side.monitoring_evidence, readiness=readiness, max_bytes=max_bytes, default_path=None,
    constants={name: constant(name) for name in s8_frontdesk_adapter.CONSTANT_NAMES})

if __name__ == "__main__":
    driver.finish("target", "intake.frontdesk_adapter", s8_frontdesk_adapter.run(API))
