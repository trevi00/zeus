"""Target driver: `evidence.inspector` on the target tree (S8 batch B5a: `evidence.adapters.evidence_inspection`).

The API mirrors the reference driver's names over the target homes. The injected port (DESIGN-s8 V26 E-4c) is the REAL `ProcessTree` class of
`host_os.adapters.process_tree`, passed as keyword-only `process_tree`; a scenario step that replaces `spawn` injects a small class whose `spawn`
does instead, so the adapter's `process_tree.spawn` is what the step controls. `TreeOwnershipError` comes from `host_os.ports`, where it moved."""

import contextlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_evidence_inspector  # noqa: E402
from codex_harness.evidence.adapters import evidence_inspection as ei  # noqa: E402
from codex_harness.evidence.domain import evidence as domain  # noqa: E402
from codex_harness.host_os.adapters.process_tree import ProcessTree, TreeOwnershipLeak  # noqa: E402
from codex_harness.host_os.ports import TreeOwnershipError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402


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


def port(spawn):
    """The process-tree port: the real class, or a stand-in whose `spawn` is the step's function."""
    if spawn is None:
        return ProcessTree
    return type("SpawnPort", (), {"spawn": staticmethod(spawn)})


class Inspector(ei.EvidenceInspector):
    """The moved inspector with the real `ProcessTree` injected; a `spawn` replaces the port's `spawn` for every replay."""

    def __init__(self, artifacts, policy=None, interpreter=None, spawn=None):
        super().__init__(artifacts, policy, interpreter, process_tree=port(spawn))


def make(artifacts, policy, interpreter, spawn=None):
    return Inspector(artifacts, policy, interpreter, spawn)


def capture(argv, cwd, timeout, max_bytes, env, progress=None, spawn=None):
    return ei._capture(argv, cwd, timeout, max_bytes, env, progress=progress, process_tree=port(spawn))


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
    driver.finish("target", "evidence.inspector", result)
