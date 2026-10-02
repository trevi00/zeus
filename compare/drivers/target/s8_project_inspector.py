"""Target driver: `evidence.project_inspector` on the target tree (S8 batch B5b: `evidence.adapters.project_evidence`).

The API mirrors the reference driver's names over the target homes. The host route's inspector is built with the REAL host_os `ProcessTree` as its
`process_tree` (DESIGN-s8 §27.2 E-4d), through a thin subclass that supplies it, so the scenario builds inspectors with M7's constructor shape; the
injected capture the scenario substitutes is `project_evidence._capture`, the module-level name M7's tests patch and E-4d keeps. The container profile
functions read their isolation selection from `owned_container.load_host_isolation` with a fixed driver digest set by the scenario."""

import contextlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_project_inspector  # noqa: E402
from codex_harness.evidence.adapters import container_contract as cc  # noqa: E402
from codex_harness.evidence.adapters import evidence_inspection as ei  # noqa: E402
from codex_harness.evidence.adapters import project_evidence as pe  # noqa: E402
from codex_harness.evidence.application.evidence_inspection import (  # noqa: E402
    BUCKET,
    EvidenceInspections,
)
from codex_harness.evidence.domain.evidence import authorized, parse_policy  # noqa: E402
from codex_harness.evidence.domain.project_evidence import (  # noqa: E402
    CONTAINER_INTERPRETER,
    SCHEMA,
    SCHEMA_V2,
    observed_checks,
    parse_profile,
    requires_container,
    worker_schema,
)
from codex_harness.execution.adapters.containers import owned_container as oc  # noqa: E402
from codex_harness.host_os.adapters.process_tree import ProcessTree  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402


class ProjectEvidenceInspector(pe.ProjectEvidenceInspector):
    def __init__(self, artifacts, profile, policy=None, interpreter=None):
        super().__init__(artifacts, profile, policy, interpreter, process_tree=ProcessTree)


class EvidenceInspector(ei.EvidenceInspector):
    def __init__(self, artifacts, policy=None, interpreter=None):
        super().__init__(artifacts, policy, interpreter, process_tree=ProcessTree)


@contextlib.contextmanager
def injected_capture(insp, capture):
    """The capture the host route uses: `project_evidence._capture`."""
    old = pe._capture
    pe._capture = capture
    try:
        yield
    finally:
        pe._capture = old


API = SimpleNamespace(
    ProjectEvidenceInspector=ProjectEvidenceInspector, EvidenceInspector=EvidenceInspector, FileArtifacts=FileArtifacts, MemoryStore=MemoryStore,
    EvidenceInspections=EvidenceInspections, BUCKET=BUCKET, injected_capture=injected_capture, load_profile=pe.load_profile,
    resolve_profile=pe.resolve_profile, execution_instructions=pe.execution_instructions, worker_delivery=pe.worker_delivery,
    shell_command=pe.shell_command, container_binding=pe.container_binding, resolve_container_profile=pe.resolve_container_profile,
    container_execution_instructions=pe.container_execution_instructions, container_worker_delivery=pe.container_worker_delivery,
    SETTING=pe.SETTING, MAX_PROFILE_BYTES=pe.MAX_PROFILE_BYTES, MAX_DEPENDENCY_BYTES=pe.MAX_DEPENDENCY_BYTES, UNPRINTABLE=pe.UNPRINTABLE,
    CONTAINER_NOTE=pe.CONTAINER_NOTE, CONTAINER_INTERPRETER=CONTAINER_INTERPRETER, TRUSTED_PYTHON=cc.TRUSTED_PYTHON, WORKSPACE=cc.WORKSPACE,
    MODE=cc.MODE, IMAGE=cc.IMAGE, SCHEMA=SCHEMA, SCHEMA_V2=SCHEMA_V2, parse_profile=parse_profile, parse_policy=parse_policy,
    packaged_policy=ei.packaged_policy, authorized=authorized, observed_checks=observed_checks, requires_container=requires_container,
    worker_schema=worker_schema, load_isolation=oc.load_host_isolation, digest=digest)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-project-") as raw:
        result = s8_project_inspector.run(API, Path(raw))
    driver.finish("target", "evidence.project_inspector", result)
