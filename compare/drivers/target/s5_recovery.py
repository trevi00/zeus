"""Target driver: `coordination.execution_recovery` on the target tree (the recovery remainder; composed by
s5_coordination_composition: the MessageHandler-backed workflow, the target FileArtifacts, intake's ticket binding
injected; no audit binding or threshold-review rows - the golden's decision case refuses before either)."""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s5_recovery  # noqa: E402
from codex_harness.coordination.application import execution_recovery  # noqa: E402
from codex_harness.intake.application import tickets  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402


def recovery(store, root):
    return execution_recovery.ExecutionRecovery(store, composition.ORG, FileArtifacts(str(root), clock=composition.PORT),
                             ticket_binding=tickets.ticket_binding, clock=composition.PORT, ids=composition.IDPORT)


API = composition.api(recovery=recovery, artifact_root=lambda: tempfile.mkdtemp(prefix="zeus-s5-recovery-"))

if __name__ == "__main__":
    driver.finish("target", "coordination.execution_recovery", s5_recovery.run(API))
