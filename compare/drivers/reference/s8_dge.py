"""Reference driver: `research.dge` (M7 `application.dge`: `DebateSessions`, `DgeRefused`, `design_gate`, `_by_status`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `application.dge`: `DebateSessions`, `DgeRefused`, `design_gate`, `_by_status`, `SESSIONS`,
  `EVENTS`, `STATUS_SCHEMA`;
- `domain.dge` (the names `tests/test_dge.py` uses and the vocabulary `application.dge` reads): `EventError`, `PacketError`,
  `packet_digest`, `event_digest`, `source_binding`, `validate_event`, `validate_packet`, `ORIGIN`, `PHASE_ROLE`, `TERMINAL`,
  `TRUST`; `domain.model.ContractError`.
Plain M7 objects or lambdas over them only. The clock and the id source are the harness's (`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_dge  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import dge as application  # noqa: E402
from codex_harness.domain import dge as domain  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, DebateSessions=application.DebateSessions, DgeRefused=application.DgeRefused,
    design_gate=application.design_gate, _by_status=application._by_status, SESSIONS=application.SESSIONS,
    EVENTS=application.EVENTS, STATUS_SCHEMA=application.STATUS_SCHEMA, ContractError=ContractError,
    EventError=domain.EventError, PacketError=domain.PacketError, packet_digest=domain.packet_digest,
    event_digest=domain.event_digest, source_binding=domain.source_binding, validate_event=domain.validate_event,
    validate_packet=domain.validate_packet, ORIGIN=domain.ORIGIN, PHASE_ROLE=domain.PHASE_ROLE, TERMINAL=domain.TERMINAL,
    TRUST=domain.TRUST)

if __name__ == "__main__":
    driver.finish("reference", "research.dge", s8_dge.run(API))
