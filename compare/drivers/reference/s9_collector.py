"""Reference driver: `observation.collector` (M7 `application/observations.py`: Collector, orphan_report, status_report over the real FileSpool/SpoolDirectory).

No clock or id source is installed: the clock, the monotonic counter, the run ids, the host and the pid are injected by the shared steps."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s9_collector  # noqa: E402

from codex_harness.adapters.contracts import validate_observation  # noqa: E402
from codex_harness.adapters.observation_spool import (  # noqa: E402
    FileSpool,
    SpoolDirectory,
    encode_record,
)
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.observations import (  # noqa: E402
    Collector,
    MemoryDirectory,
    Observer,
    orphan_report,
    status_report,
)

API = SimpleNamespace(Collector=Collector, Observer=Observer, MemoryDirectory=MemoryDirectory, orphan_report=orphan_report, status_report=status_report,
                      FileSpool=FileSpool, SpoolDirectory=SpoolDirectory, encode_record=encode_record, validate=validate_observation,
                      MemoryStore=MemoryStore)

if __name__ == "__main__":
    driver.finish("reference", "observation.collector", s9_collector.run(API))
