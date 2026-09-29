"""Target driver: `storage.memory` on the target tree (storage adapters/application, kernel ports).

The clock is injected; the missing-reference events go through the EventJournal port, here the
fixture journal with the M7 write rule (coordination implements the port in S5).
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s1_storage  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.storage.adapters import artifact_reader  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.maintenance import ArtifactMaintenance  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.application import artifact_query  # noqa: E402
from s1_target import FixtureEventJournal, PortClock  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
CLOCK_PORT = PortClock(CLOCK)

API = SimpleNamespace(
    MemoryStore=MemoryStore, FileArtifacts=lambda root: FileArtifacts(root, clock=CLOCK_PORT),
    reader=artifact_reader, query=artifact_query,
    maintenance=lambda store, arts: ArtifactMaintenance(store, arts, FixtureEventJournal(), clock=CLOCK_PORT),
    ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s1-storage-") as raw:
        result = s1_storage.run(API, Path(raw).resolve(), CLOCK)
    driver.finish("target", "storage.memory", result)
