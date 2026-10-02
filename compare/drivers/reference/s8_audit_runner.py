"""Reference driver: `research.audit_runner` (M7 `adapters.audit_runner`: `AuditRunner`).

The API holds plain M7 objects: `adapters.audit_runner.AuditRunner`; `adapters.artifacts.FileArtifacts` (over a run-scoped directory);
`domain.research`: `SourceIdentity`, `InventoryEntry`, `ExecutionReceipt`; `domain.model`: `canonical`, `digest`. The three spawns of `acquire`
and the verifier's Git calls are M7's `subprocess.run` calls: the driver puts the scenario's LABELLED scripted `git` where the adapter's and the
verifier's `subprocess` names are (a shim with `run`, `PIPE`, `TimeoutExpired`, `CalledProcessError` and `CompletedProcess`), and the LABELLED
bubblewrap double where `run_process` is (the seam M7's own tests patch). M7's own `classify_isolated_run` is the classifier. No clone, network
or bwrap ever runs. The clock and the id source are the harness's (`determinism.install`); `advance` ticks the fake clock."""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_audit_runner  # noqa: E402

from codex_harness.adapters import audit_runner as module  # noqa: E402
from codex_harness.adapters import source_verification  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.domain.model import canonical, digest  # noqa: E402
from codex_harness.domain.research import (  # noqa: E402
    ExecutionReceipt,
    InventoryEntry,
    SourceIdentity,
)

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
determinism.install(CLOCK, determinism.FakeIds())

FAKES = SimpleNamespace(git=s8_audit_runner.Git(), bwrap=s8_audit_runner.Bwrap())
SPAWN = SimpleNamespace(run=FAKES.git.run, PIPE=subprocess.PIPE, DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired,
                        CalledProcessError=subprocess.CalledProcessError, CompletedProcess=subprocess.CompletedProcess)
module.subprocess = SPAWN                      # M7: `subprocess.run(['git', ...], check=True, capture_output=True, **no_console_kwargs())`
source_verification.subprocess = SPAWN         # M7: `GitSourceVerifier.git`
module.run_process = lambda argv, timeout: FAKES.bwrap(argv, timeout)   # M7: `run_process(argv, timeout=120)`


def make_runner(root, artifacts, host_execution=False):
    return module.AuditRunner(root, artifacts, host_execution)


API = SimpleNamespace(
    fakes=FAKES, make_runner=make_runner, FileArtifacts=FileArtifacts, SourceIdentity=SourceIdentity, InventoryEntry=InventoryEntry,
    ExecutionReceipt=ExecutionReceipt, canonical=canonical, digest=digest, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "research.audit_runner", s8_audit_runner.run(API))
