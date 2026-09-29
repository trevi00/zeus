"""Reference driver: `containers.staging` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S3, R-C first).

M7 `adapters.isolated_worker` staging (path rules, bounds, pinned export, standalone Git, output scan,
import plan/apply) and `adapters.role_containers` evidence hand-off (retain, refs, materialize) over
M7 `adapters.artifacts.FileArtifacts` in the scenario's own temporary directory. Host git reads a
fixture repository; no provider or container is used.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s3_staging  # noqa: E402

from codex_harness.adapters import isolated_worker as iw  # noqa: E402
from codex_harness.adapters import role_containers as rc  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

API = SimpleNamespace(
    check_relative_path=iw.check_relative_path, check_bounds=iw.check_bounds, list_revision=iw.list_revision,
    stage_source=iw.stage_source, init_standalone_git=iw.init_standalone_git, scan_tree=iw.scan_tree,
    plan_import=iw.plan_import, apply_import=iw.apply_import, retain_evidence_handoff=rc.retain_evidence_handoff,
    handoff_refs=rc.handoff_refs, materialize_handoff=rc.materialize_handoff, Artifacts=FileArtifacts,
    MAX_FILES=iw.MAX_FILES, MAX_FILE_BYTES=iw.MAX_FILE_BYTES, IsolationError=iw.IsolationError,
    ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("reference", "containers.staging", s3_staging.run(API))
