"""Target driver: `research.source_verification` on the target tree (S8 pilot 91: ``research.adapters.source_verification` (V18 R-sv1: `console_kwargs` is an injected keyword-only port)`).

`verifier(repository, artifacts, run)` injects the scenario's LABELLED console-kwargs fake as `console_kwargs=` and binds the same fake
`subprocess.run` the reference binds (the target's standard library is never otherwise patched)."""

import contextlib
import subprocess
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


@contextlib.contextmanager
def fake_run(run):
    """The stdlib `subprocess.run` the verifier calls, replaced by the scenario's LABELLED fake for one call."""
    saved = subprocess.run
    subprocess.run = run
    try:
        yield
    finally:
        subprocess.run = saved


class Bound:
    """The verifier under the fake `subprocess.run`: every method runs inside `fake_run`."""

    def __init__(self, verifier, run):
        self.verifier, self.run = verifier, run
        self.repository, self.artifacts = verifier.repository, verifier.artifacts

    def git(self, *args):
        with fake_run(self.run):
            return self.verifier.git(*args)

    def inventory(self, source):
        with fake_run(self.run):
            return self.verifier.inventory(source)

    def verify(self, source, entries):
        with fake_run(self.run):
            return self.verifier.verify(source, entries)


def verifier(repository, artifacts, run):
    return Bound(module.GitSourceVerifier(repository, artifacts, console_kwargs=lambda: dict(common.CONSOLE_MARK)), run)


API = SimpleNamespace(verifier=verifier, FileArtifacts=FileArtifacts, SourceIdentity=SourceIdentity, InventoryEntry=InventoryEntry, canonical=canonical)

if __name__ == "__main__":
    driver.finish("target", "research.source_verification", common.source_verification(API))
