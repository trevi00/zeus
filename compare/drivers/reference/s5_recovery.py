"""Reference driver: `coordination.execution_recovery` (M7 ExecutionRecovery over M7's Workflow and FileArtifacts)."""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s5_recovery  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import execution_time, workflow  # noqa: E402,F401
from codex_harness.application.execution_recovery import ExecutionRecovery  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import envelope  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000e5e5"}})
ORG = organization()
API = SimpleNamespace(
    MemoryStore=MemoryStore, workflow=lambda store: workflow.Workflow(store, ORG),
    recovery=lambda store, root: ExecutionRecovery(store, ORG, FileArtifacts(Path(root))),
    artifact_root=lambda: tempfile.mkdtemp(prefix="zeus-s5-recovery-"), envelope=envelope, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "coordination.execution_recovery", s5_recovery.run(API))
