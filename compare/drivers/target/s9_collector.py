"""Target driver: `observation.collector` on the target tree (`observation.application.observations` Collector, orphan_report, status_report over the moved
file spool and schema)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_collector  # noqa: E402
from codex_harness.observation.adapters.observation_schema import validate_observation  # noqa: E402
from codex_harness.observation.adapters.observation_spool import (  # noqa: E402
    FileSpool,
    SpoolDirectory,
    encode_record,
)
from codex_harness.observation.application.observations import (  # noqa: E402
    Collector,
    MemoryDirectory,
    Observer,
    orphan_report,
    status_report,
)
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

API = SimpleNamespace(Collector=Collector, Observer=Observer, MemoryDirectory=MemoryDirectory, orphan_report=orphan_report, status_report=status_report,
                      FileSpool=FileSpool, SpoolDirectory=SpoolDirectory, encode_record=encode_record, validate=validate_observation,
                      MemoryStore=MemoryStore)

if __name__ == "__main__":
    driver.finish("target", "observation.collector", s9_collector.run(API))
