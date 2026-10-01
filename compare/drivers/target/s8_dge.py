"""Target driver: `research.dge` on the target tree (S8 pilot 65: `research.application.dge`).

The API mirrors the reference driver's names over the target homes: the use case from `research.application.dge`
(`DgeRefused` is the S5 move-ahead in `research.domain.dge`, re-exported there) and the validators and vocabulary from
`research.domain.dge`. The scenario reads the kernel's default clock where M7 read `utcnow`; the harness's scripted
clock reaches it through the kernel `Clock` port: the driver sets `kernel.ids.SYSTEM_CLOCK`, the one default `utcnow`
reads (the target's standard library is never patched)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_dge  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.research.application import dge as application  # noqa: E402
from codex_harness.research.domain import dge as domain  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

API = SimpleNamespace(
    MemoryStore=MemoryStore, DebateSessions=application.DebateSessions, DgeRefused=application.DgeRefused,
    design_gate=application.design_gate, _by_status=application._by_status, SESSIONS=application.SESSIONS,
    EVENTS=application.EVENTS, STATUS_SCHEMA=application.STATUS_SCHEMA, ContractError=ContractError,
    EventError=domain.EventError, PacketError=domain.PacketError, packet_digest=domain.packet_digest,
    event_digest=domain.event_digest, source_binding=domain.source_binding, validate_event=domain.validate_event,
    validate_packet=domain.validate_packet, ORIGIN=domain.ORIGIN, PHASE_ROLE=domain.PHASE_ROLE, TERMINAL=domain.TERMINAL,
    TRUST=domain.TRUST)

if __name__ == "__main__":
    driver.finish("target", "research.dge", s8_dge.run(API))
