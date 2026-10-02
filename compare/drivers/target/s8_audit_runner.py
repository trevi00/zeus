"""Target driver: `research.audit_runner` on the target tree (S8 batch B3: `research.adapters.audit_runner`, V29 R-au0..R-au3).

The API mirrors the reference driver's names over the target homes. M7's `AuditRunner` spawns `git` through `subprocess.run`; the target takes
host_os's `ChildProcesses` as the injected `processes` port (R-au1/R-au2) and builds its verifier with it, takes `run_process` (R-au3) and
`classify` (the product's own `review.domain.check_results.classify_isolated_run`, as the composition wires it). The scenario's LABELLED
scripted `git` is the `processes` port (an object with `run`, the shape of `ChokepointProcesses.run`, whose no-console keywords are host_os's
own family) and its LABELLED bubblewrap double is `run_process`: the SAME doubles the reference driver puts where M7's `subprocess.run` and
`run_process` are, so both sides record the same calls. No clone, network or bwrap ever runs. The artifacts are the target `FileArtifacts`; the
scenario reads the kernel's default clock where M7 read `utcnow`, and the harness's scripted clock reaches it through `kernel.ids.SYSTEM_CLOCK`."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_audit_runner  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.research.adapters import audit_runner as module  # noqa: E402
from codex_harness.research.domain.research import (  # noqa: E402
    ExecutionReceipt,
    InventoryEntry,
    SourceIdentity,
)
from codex_harness.review.domain.check_results import classify_isolated_run  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT

FAKES = SimpleNamespace(git=s8_audit_runner.Git(), bwrap=s8_audit_runner.Bwrap())


def make_runner(root, artifacts, host_execution=False):
    return module.AuditRunner(root, artifacts, host_execution, processes=FAKES.git, run_process=FAKES.bwrap, classify=classify_isolated_run)


API = SimpleNamespace(
    fakes=FAKES, make_runner=make_runner, FileArtifacts=FileArtifacts, SourceIdentity=SourceIdentity, InventoryEntry=InventoryEntry,
    ExecutionReceipt=ExecutionReceipt, canonical=canonical, digest=digest, advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.audit_runner", s8_audit_runner.run(API))
