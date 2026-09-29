"""Reference driver: `knowledge.units` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S2, R-C first).

M7 `domain.{seams,seam_view,experience,snapshot_integrity,profile_privacy}`, `application.{seam_ledger,
experience,snapshot_imports,profile_flow,promotion}`, `adapters.{seam_extraction,experience,knowledge,
embeddings,profile_scratch}` with MemoryStore/FileArtifacts; the bounded YAML loader is M7's
`adapters.project_skills.load_yaml` (the one `adapters.experience.parse_lesson` uses internally, so the
`load_yaml` keyword the scenario passes is ignored here). Clock and ids are the scripted fakes.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s2_knowledge  # noqa: E402

from codex_harness.adapters import experience as experience_adapter  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.embeddings import LocalEmbeddings  # noqa: E402
from codex_harness.adapters.knowledge import extract_python  # noqa: E402
from codex_harness.adapters.profile_scratch import ProfileScratch  # noqa: E402
from codex_harness.adapters.project_skills import load_yaml  # noqa: E402
from codex_harness.adapters.seam_extraction import discover, extract  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.experience import ExperienceClaims  # noqa: E402
from codex_harness.application.profile_flow import ProfileFlow  # noqa: E402
from codex_harness.application.promotion import promote  # noqa: E402
from codex_harness.application.seam_ledger import SeamLedger  # noqa: E402
from codex_harness.application.snapshot_imports import SnapshotImports  # noqa: E402
from codex_harness.domain import (  # noqa: E402
    experience,
    profile_privacy,
    seam_view,
    seams,
    snapshot_integrity,
)

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)


def parse_lesson(source, path, data, basis, *, load_yaml):
    return experience_adapter.parse_lesson(source, path, data, basis)


def import_lessons(paths, source, basis, store, artifacts, path_prefix="", *, load_yaml):
    return experience_adapter.import_lessons(paths, source, basis, store, artifacts, path_prefix)


API = SimpleNamespace(
    seams=seams, seam_view=seam_view, SeamLedger=SeamLedger, extract=extract, discover=discover,
    experience=experience, ExperienceClaims=ExperienceClaims, parse_lesson=parse_lesson,
    import_lessons=import_lessons, snapshot=snapshot_integrity, SnapshotImports=SnapshotImports,
    privacy=profile_privacy, ProfileFlow=ProfileFlow, ProfileScratch=ProfileScratch, promote=promote,
    extract_python=extract_python, LocalEmbeddings=LocalEmbeddings, MemoryStore=MemoryStore,
    FileArtifacts=FileArtifacts, load_yaml=load_yaml)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s2-knowledge-") as raw:
        result = s2_knowledge.run(API, Path(raw).resolve())
    driver.finish("reference", "knowledge.units", result)
