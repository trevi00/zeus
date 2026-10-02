"""Reference driver: `evidence.project_inspector` (M7 `adapters/project_evidence.py`: `load_profile`, `resolve_profile`, `execution_instructions`,
`worker_delivery`, `shell_command`, `container_binding`, `resolve_container_profile`, `container_execution_instructions`,
`container_worker_delivery`, `ProjectEvidenceInspector`).

The API holds plain M7 objects. The host route's children are real (the REAL `ProcessTree` through the module's own `_capture`); the injected capture
the scenario substitutes is `project_evidence._capture` (the name the module imported). The container profile functions need no docker: they read
the isolation selection from a configuration built with `isolated_worker.load_isolation` and a fixed driver digest."""

import contextlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_project_inspector  # noqa: E402

from codex_harness.adapters import evidence_inspection as ei  # noqa: E402
from codex_harness.adapters import isolated_worker as iw  # noqa: E402
from codex_harness.adapters import project_evidence as pe  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.evidence_inspection import BUCKET, EvidenceInspections  # noqa: E402
from codex_harness.domain.evidence import authorized, parse_policy  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402
from codex_harness.domain.project_evidence import (  # noqa: E402
    CONTAINER_INTERPRETER,
    SCHEMA,
    SCHEMA_V2,
    observed_checks,
    parse_profile,
    requires_container,
    worker_schema,
)


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
    ProjectEvidenceInspector=pe.ProjectEvidenceInspector, EvidenceInspector=ei.EvidenceInspector, FileArtifacts=FileArtifacts, MemoryStore=MemoryStore,
    EvidenceInspections=EvidenceInspections, BUCKET=BUCKET, injected_capture=injected_capture, load_profile=pe.load_profile,
    resolve_profile=pe.resolve_profile, execution_instructions=pe.execution_instructions, worker_delivery=pe.worker_delivery,
    shell_command=pe.shell_command, container_binding=pe.container_binding, resolve_container_profile=pe.resolve_container_profile,
    container_execution_instructions=pe.container_execution_instructions, container_worker_delivery=pe.container_worker_delivery,
    SETTING=pe.SETTING, MAX_PROFILE_BYTES=pe.MAX_PROFILE_BYTES, MAX_DEPENDENCY_BYTES=pe.MAX_DEPENDENCY_BYTES, UNPRINTABLE=pe.UNPRINTABLE,
    CONTAINER_NOTE=pe.CONTAINER_NOTE, CONTAINER_INTERPRETER=CONTAINER_INTERPRETER, TRUSTED_PYTHON=iw.TRUSTED_PYTHON, WORKSPACE=iw.WORKSPACE,
    MODE=iw.MODE, IMAGE=iw.IMAGE, SCHEMA=SCHEMA, SCHEMA_V2=SCHEMA_V2, parse_profile=parse_profile, parse_policy=parse_policy,
    packaged_policy=ei.packaged_policy, authorized=authorized, observed_checks=observed_checks, requires_container=requires_container,
    worker_schema=worker_schema, load_isolation=iw.load_isolation, digest=digest)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-project-") as raw:
        result = s8_project_inspector.run(API, Path(raw))
    driver.finish("reference", "evidence.project_inspector", result)
