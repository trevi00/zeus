"""Reference driver: `research.source_verification` (M7 `adapters/source_verification.py: `GitSourceVerifier``).

The API holds the plain M7 objects: `adapters.source_verification.GitSourceVerifier`, `adapters.artifacts.FileArtifacts`, `domain.research`'s
`SourceIdentity`/`InventoryEntry`, `domain.model.canonical`. `verifier(repository, artifacts, run)` replaces the module's `no_console_kwargs` and the
stdlib `subprocess.run` with the scenario's LABELLED fakes (what M7's tests do), and binds them for every call.

The clock and ids are not used (no result holds a time or an id)."""

import contextlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_hostos_adapters as common  # noqa: E402

from codex_harness.adapters import source_verification as module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.domain.model import canonical  # noqa: E402
from codex_harness.domain.research import InventoryEntry, SourceIdentity  # noqa: E402


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
    module.no_console_kwargs = lambda: dict(common.CONSOLE_MARK)
    return Bound(module.GitSourceVerifier(repository, artifacts), run)


API = SimpleNamespace(verifier=verifier, FileArtifacts=FileArtifacts, SourceIdentity=SourceIdentity, InventoryEntry=InventoryEntry, canonical=canonical)

if __name__ == "__main__":
    driver.finish("reference", "research.source_verification", common.source_verification(API))
