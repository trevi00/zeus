"""Target driver: `research.source_verification` on the target tree (S8 pilot 91: `research.adapters.source_verification`, V18 R-sv2: host_os's
`ChildProcesses` is an injected keyword-only port `processes`).

`verifier(repository, artifacts, run)` injects a LABELLED `ChildProcesses` double whose `run` calls the scenario's fake `subprocess.run` with the
no-console keywords the reference's patched `no_console_kwargs` returns (what `ChokepointProcesses.run` does with the real ones); nothing in the
standard library is patched."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_hostos_adapters as common  # noqa: E402
from codex_harness.kernel.ids import canonical  # noqa: E402
from codex_harness.research.adapters import source_verification as module  # noqa: E402
from codex_harness.research.domain.research import InventoryEntry, SourceIdentity  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402


class Processes:
    """LABELLED double of `host_os.ports.ChildProcesses`: `run` applies the (fake) no-console keywords itself, as the chokepoint implementation does."""

    def __init__(self, run):
        self.fake = run

    def run(self, argv, *, process_group=False, **kwargs):
        return self.fake(argv, **kwargs, **common.CONSOLE_MARK)


def verifier(repository, artifacts, run):
    return module.GitSourceVerifier(repository, artifacts, processes=Processes(run))


API = SimpleNamespace(verifier=verifier, FileArtifacts=FileArtifacts, SourceIdentity=SourceIdentity, InventoryEntry=InventoryEntry, canonical=canonical)

if __name__ == "__main__":
    driver.finish("target", "research.source_verification", common.source_verification(API))
