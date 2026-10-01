"""Reference driver: `research.capture` (M7 `GitCapture.capture`, the detached capture commit and its create-only ref).

The API holds plain M7 objects:
- `adapters.research_program`: `GitCapture`, `CaptureError`, `CAPTURE_AUTHOR`, `MAX_SNAPSHOT_BYTES` and `run_process` (the
  adapter module's own name of `adapters.commands.run_process`, for the simulated Windows pipe);
- `adapters.operation_cli.GitSource` (the read-back reader);
- `domain.research_program.CAPTURE_ROOT`; `domain.model.ContractError`;
- `patch(name, value)`: a context manager replacing one name of the `adapters.research_program` module (the labelled
  fault seam: `GitSource`, `run_process`).
Plain M7 objects or lambdas over them only. The clock and the id source are the harness's (`determinism.install`); the
fixture repositories pin their own `GIT_*` identity and dates."""

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s8_capture  # noqa: E402

from codex_harness.adapters import research_program as adapter  # noqa: E402
from codex_harness.adapters.operation_cli import GitSource  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402
from codex_harness.domain.research_program import CAPTURE_ROOT  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)


@contextmanager
def patch(name, value):
    saved = getattr(adapter, name)
    setattr(adapter, name, value)
    try:
        yield
    finally:
        setattr(adapter, name, saved)


API = SimpleNamespace(
    GitCapture=adapter.GitCapture, CaptureError=adapter.CaptureError, CAPTURE_AUTHOR=adapter.CAPTURE_AUTHOR,
    MAX_SNAPSHOT_BYTES=adapter.MAX_SNAPSHOT_BYTES, run_process=adapter.run_process, GitSource=GitSource,
    CAPTURE_ROOT=CAPTURE_ROOT, ContractError=ContractError, patch=patch)

if __name__ == "__main__":
    driver.finish("reference", "research.capture", s8_capture.run(API))
