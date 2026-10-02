"""Target driver: `review.sdd` on the target tree (S8 batch B4: `review.application.sdd`).

The API mirrors the reference driver's names over the target homes: `SDD` from `review.application.sdd`, `STAGES` from `review.domain.sdd`, the
kernel's `ContractError`, `canonical`, `digest` and `require`, the storage `MemoryStore`. The ticket binding is the real intake function injected
through R-sdd1 (`intake.application.tickets.ticket_binding`); the scripted clock reaches the module through R-sdd2 (the kernel `Clock` port over the
harness clock); the target's standard library and module attributes are never patched."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_sdd  # noqa: E402
from codex_harness.intake.application.tickets import ticket_binding  # noqa: E402
from codex_harness.kernel.errors import ContractError, require  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.review.application import sdd as module  # noqa: E402
from codex_harness.review.domain.sdd import STAGES  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
PORT = PortClock(CLOCK)

API = SimpleNamespace(
    MemoryStore=MemoryStore, SDD=module.SDD, STAGES=STAGES, ContractError=ContractError, canonical=canonical, digest=digest, require=require,
    make=lambda store, artifacts, provider: module.SDD(store, artifacts, provider, ticket_binding=ticket_binding, clock=PORT),
    advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "review.sdd", s8_sdd.run(API))
