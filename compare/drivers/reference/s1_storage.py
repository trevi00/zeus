"""Reference driver: `storage.memory` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S1, R-C first).

M7 `MemoryStore`, `FileArtifacts`, the bounded reader `adapters.artifact_reader` (in-process
`main`, never `-m`), `application.artifact_query` and `ArtifactMaintenance`, plus the S0 §2.9
recorder over the M7 store. Clock and ids are the scripted fakes patched into this process only.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s1_storage  # noqa: E402

from codex_harness.adapters import artifact_reader  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.maintenance import ArtifactMaintenance  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import artifact_query  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(MemoryStore=MemoryStore, FileArtifacts=FileArtifacts, reader=artifact_reader,
                      query=artifact_query, maintenance=ArtifactMaintenance, ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s1-storage-") as raw:
        result = s1_storage.run(API, Path(raw).resolve(), CLOCK)
    driver.finish("reference", "storage.memory", result)
