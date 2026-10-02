"""Reference driver: `review.sdd` (M7 `application/sdd.py`: `SDD`).

The API holds the plain M7 module. Its `ticket_binding` is the real M7 `application.tickets` function the module imports itself; its `utcnow` reads
the `datetime` the harness's `determinism.install` rebinds to the scripted clock, as every loaded `codex_harness` module's is. The store is the M7
`MemoryStore`. No provider, device or database is used."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_sdd  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import sdd as module  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, digest, require  # noqa: E402
from codex_harness.domain.sdd import STAGES  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
determinism.install(CLOCK, determinism.FakeIds())

API = SimpleNamespace(
    MemoryStore=MemoryStore, SDD=module.SDD, STAGES=STAGES, ContractError=ContractError, canonical=canonical, digest=digest, require=require,
    make=lambda store, artifacts, provider: module.SDD(store, artifacts, provider), advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "review.sdd", s8_sdd.run(API))
