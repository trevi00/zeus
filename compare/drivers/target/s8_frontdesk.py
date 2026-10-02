"""Target driver: `intake.frontdesk` on the target tree (S8 pilot 84: the V16 split move, `FrontDesk` in intake and `DeskRunner` in
coordination).

The API mirrors the reference driver's names over the target homes. M7's `Harness` is the S5 composition's `Service` (store, organization,
the outbox flusher `DeskRunner` publishes through) and M7's `Workflow` its `WorkflowAndMessages`. `FrontDesk` is the moved class with its one
injected port (R-f1): coordination's `Outbox` (the shape of `intake.ports.OutboxAppend`); a subclass, so the scenario builds it from
`(service, revision)` as M7's tests do. `DeskRunner` is the moved class unchanged: its `desk` is the moved `FrontDesk` (the `DeskQueue` shape)
and `flush_outbox` takes the service's `.flusher` (R-d2). The harness's scripted clock reaches the kernel through the `Clock` port
(`FrontDesk`'s default `clock=utcnow`, the envelope's `created_at`) and the scripted ids through `kernel.message.SYSTEM_IDS`. M7 read the
patched stdlib for the default owner token (`uuid4`) and `datetime.now(timezone.utc)` in `_bound_execution`; the target's standard library is
never patched, so the driver substitutes those two module names with the scripted id source and clock."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_frontdesk  # noqa: E402
from codex_harness.coordination.application import desk_runner  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.intake.application import frontdesk as application  # noqa: E402
from codex_harness.intake.domain import frontdesk as domain  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.ids import canonical  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.message_schema import validate_message  # noqa: E402
from codex_harness.storage.ports import MessageDeliveryError  # noqa: E402

ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
application.uuid4 = composition.IDS.uuid4   # the default owner token: the harness id source, as the reference run installed it
desk_runner.datetime = SimpleNamespace(now=composition.CLOCK.now)   # `datetime.now(timezone.utc)` reads the scripted clock


class FrontDesk(application.FrontDesk):
    """The moved class with its outbox port wired (a subclass: the scenario builds it from the service and revision alone)."""

    def __init__(self, service, base_revision, *args, **kwargs):
        super().__init__(service, base_revision, *args, outbox=Outbox(), **kwargs)


API = SimpleNamespace(
    MemoryStore=MemoryStore, FrontDesk=FrontDesk, DeskRunner=desk_runner.DeskRunner, LEAD=domain.LEAD,
    SUMMARY_TURNS=desk_runner.SUMMARY_TURNS, correlation_of=application.correlation_of, message_id_of=application.message_id_of,
    Harness=lambda store, org: composition.Service(store), Workflow=lambda store, org: composition.WorkflowAndMessages(store),
    ClaimGuardRefused=composition.ClaimGuardRefused, organization=lambda: composition.ORG, domain=domain,
    validate_message=validate_message, canonical=canonical, MessageDeliveryError=MessageDeliveryError,
    advance=composition.CLOCK.advance, reset=lambda: (composition.CLOCK.reset(), composition.IDS.reset()))

if __name__ == "__main__":
    driver.finish("target", "intake.frontdesk", s8_frontdesk.run(API))
