"""Target driver: `knowledge.units` on the target tree (codex_harness.knowledge, context YAML loader).

The clock is injected through the kernel port into every record-writing object; the lesson YAML
loader is passed explicitly (context.adapters.yaml_source.load_yaml), as composition will.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s2_knowledge  # noqa: E402
from codex_harness.context.adapters.profile_scratch import ProfileScratch  # noqa: E402
from codex_harness.context.adapters.yaml_source import load_yaml  # noqa: E402
from codex_harness.knowledge.adapters.embeddings import LocalEmbeddings  # noqa: E402
from codex_harness.knowledge.adapters.experience_import import (  # noqa: E402
    import_lessons,
    parse_lesson,
)
from codex_harness.knowledge.adapters.postgres_knowledge import extract_python  # noqa: E402
from codex_harness.knowledge.adapters.seam_extraction import discover, extract  # noqa: E402
from codex_harness.knowledge.application.experience import ExperienceClaims  # noqa: E402
from codex_harness.knowledge.application.profile_flow import ProfileFlow  # noqa: E402
from codex_harness.knowledge.application.promotion import promote  # noqa: E402
from codex_harness.knowledge.application.seam_ledger import SeamLedger  # noqa: E402
from codex_harness.knowledge.application.snapshot_imports import SnapshotImports  # noqa: E402
from codex_harness.knowledge.domain import (  # noqa: E402
    experience,
    profile_privacy,
    seam_view,
    seams,
    snapshot_integrity,
)
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock()
PORT = PortClock(CLOCK)

API = SimpleNamespace(
    seams=seams, seam_view=seam_view, SeamLedger=lambda store: SeamLedger(store, clock=PORT), extract=extract,
    discover=discover, experience=experience, ExperienceClaims=lambda store: ExperienceClaims(store, clock=PORT),
    parse_lesson=parse_lesson,
    import_lessons=lambda *a, **k: import_lessons(*a, **k, clock=PORT),
    snapshot=snapshot_integrity,
    SnapshotImports=lambda store, artifacts: SnapshotImports(store, artifacts, clock=PORT),
    privacy=profile_privacy, ProfileFlow=lambda store, scratch: ProfileFlow(store, scratch, clock=PORT),
    ProfileScratch=lambda root: ProfileScratch(root, clock=PORT),
    promote=lambda tx, run_id, graph, evidence: promote(tx, run_id, graph, evidence, clock=PORT),
    extract_python=extract_python, LocalEmbeddings=LocalEmbeddings, MemoryStore=MemoryStore,
    FileArtifacts=lambda root: FileArtifacts(root, clock=PORT), load_yaml=load_yaml)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s2-knowledge-") as raw:
        result = s2_knowledge.run(API, Path(raw).resolve())
    driver.finish("target", "knowledge.units", result)
