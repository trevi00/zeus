"""Reference driver: `evidence.inspector` (M7 `adapters/evidence_inspection.py`: `EvidenceInspector`, `_capture`, `packaged_policy`, `replay_environment`,
`trusted_interpreter`, `replay_argv`).

The API holds plain M7 objects: `adapters.evidence_inspection` (the inspector builds its own `adapters.process_tree.ProcessTree`; the REAL class is also
handed to the scenario to patch `spawn` the way M7's tests do), `adapters.artifacts.FileArtifacts`, and the `domain.evidence` and `domain.model` pieces
the scenario reads. Children are real."""

import contextlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_evidence_inspector  # noqa: E402

from codex_harness.adapters import evidence_inspection as ei  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.process_tree import (  # noqa: E402
    ProcessTree,
    TreeOwnershipError,
    TreeOwnershipLeak,
)
from codex_harness.domain import evidence as domain  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402


@contextlib.contextmanager
def patched(name, value):
    """Rebind one module attribute of the adapter for the duration of a step."""
    old = getattr(ei, name)
    setattr(ei, name, value)
    try:
        yield
    finally:
        setattr(ei, name, old)


def real_spawn():
    return ProcessTree.spawn


@contextlib.contextmanager
def spawning(spawn):
    """M7's tests patch the class attribute; the adapter reads `ProcessTree.spawn` at call time."""
    if spawn is None:
        yield
        return
    original = ProcessTree.__dict__["spawn"]
    ProcessTree.spawn = staticmethod(spawn)
    try:
        yield
    finally:
        ProcessTree.spawn = original


class Inspector(ei.EvidenceInspector):
    """M7's inspector; a `spawn` replaces `ProcessTree.spawn` on every replay (the class attribute, as M7's tests patch it)."""

    def __init__(self, artifacts, policy=None, interpreter=None, spawn=None):
        super().__init__(artifacts, policy, interpreter)
        self._spawn = spawn

    def _replay(self, argv, cwd, timeout, max_bytes, env, progress=None):
        with spawning(self._spawn):
            return super()._replay(argv, cwd, timeout, max_bytes, env, progress=progress)


def make(artifacts, policy, interpreter, spawn=None):
    return Inspector(artifacts, policy, interpreter, spawn)


def capture(argv, cwd, timeout, max_bytes, env, progress=None, spawn=None):
    with spawning(spawn):
        return ei._capture(argv, cwd, timeout, max_bytes, env, progress=progress)


API = SimpleNamespace(
    make=make, capture=capture, patched=patched, real_spawn=real_spawn, FileArtifacts=FileArtifacts, EvidenceInspector=Inspector,
    packaged_policy=ei.packaged_policy, replay_environment=ei.replay_environment, trusted_interpreter=ei.trusted_interpreter,
    replay_argv=ei.replay_argv, policy_file=lambda: ei.POLICY_FILE, KEEP_ENV=ei.KEEP_ENV, CLEANUP_SECONDS=ei.CLEANUP_SECONDS,
    READER_JOIN_SECONDS=ei.READER_JOIN_SECONDS, POLL_SECONDS=ei.POLL_SECONDS, TreeOwnershipError=TreeOwnershipError,
    TreeOwnershipLeak=TreeOwnershipLeak, authorized=domain.authorized, parse_claim=domain.parse_claim, classify_replays=domain.classify_replays,
    denominator=domain.denominator, verdict=domain.verdict, digest=digest)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-inspector-") as raw:
        result = s8_evidence_inspector.run(API, Path(raw))
    driver.finish("reference", "evidence.inspector", result)
