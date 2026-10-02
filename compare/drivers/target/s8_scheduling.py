"""Target driver: `research.scheduling` on the target tree (S8 pilot 102: `research.application.scheduling`, DESIGN-s8 §19 V23).

The API mirrors the reference driver's names over the target homes. The two ports of R-sc1 are what composition passes: coordination's `Outbox`
(R-sc3) and the bound `reconcile_audits` of the REAL review `Releases` (pilot 106), built as `s8_releases_audits` builds it (intake's
`ticket_binding`, the harness's clock port, coordination's `EventJournal`). The scenario reads the kernel's default clock and id source where M7
read `utcnow` and `envelope`; the harness's scripted clock and ids (the composition's) reach them through the kernel `Clock` port and
`kernel.message.SYSTEM_IDS`."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_scheduling  # noqa: E402
from codex_harness.coordination.application.events import EventJournal  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.application import audit_gate, scheduling  # noqa: E402
from codex_harness.review.application.releases import Releases  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT


def ports(store, org):
    releases = Releases(store, org, ticket_binding=tickets.ticket_binding, clock=composition.PORT, events=EventJournal())
    return {"outbox": Outbox(), "reconcile_audits": releases.reconcile_audits}


API = SimpleNamespace(
    MemoryStore=MemoryStore, organization=lambda: composition.ORG, binding=audit_gate.binding, digest=digest,
    schedule_research=scheduling.schedule_research, schedule_audits=scheduling.schedule_audits, ports=ports,
    advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.scheduling", s8_scheduling.run(API))
