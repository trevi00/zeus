"""Target driver: `evidence.completion` on the target tree (S8 pilot 85: `evidence.application.completion`).

The API mirrors the reference driver's names over the target homes: the use case and its constants from
`evidence.application.completion`, the memory store from storage, `ContractError`/`digest` from the kernel. The scenario reads the
kernel's default clock where M7 read `utcnow` (the notices' `at`); the harness's scripted clock reaches it through the kernel `Clock`
port: the driver sets `kernel.ids.SYSTEM_CLOCK`, the one default `utcnow` reads (the target's standard library is never patched). The
artifacts store and the organization are the scenario's LABELLED fakes."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_completion  # noqa: E402
from codex_harness.evidence.application import completion as application  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

API = SimpleNamespace(
    MemoryStore=MemoryStore, CompletionAuthority=application.CompletionAuthority, BUCKET=application.BUCKET,
    REJECTIONS=application.REJECTIONS, RECORD_ONLY=application.RECORD_ONLY, STATES=application.STATES,
    EVALUATION_KIND=application.EVALUATION_KIND, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "evidence.completion", s8_completion.run(API))
