"""Target driver: `containers.staging` on the target tree (execution staging rules/adapters, hand-off).

Git is reached through the host_os `ChildProcesses` port (the chokepoint implementation), injected here
as composition will; the artifact store is the target storage `FileArtifacts`.
"""

import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s3_staging  # noqa: E402
from codex_harness.execution.adapters.containers import handoff, staging  # noqa: E402
from codex_harness.execution.domain import container_spec as spec  # noqa: E402
from codex_harness.execution.domain import staging_rules  # noqa: E402
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses  # noqa: E402
from codex_harness.kernel.errors import ContractError, IsolationError  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402

PROCESSES = ChokepointProcesses()
API = SimpleNamespace(
    check_relative_path=staging_rules.check_relative_path, check_bounds=staging_rules.check_bounds,
    list_revision=partial(staging.list_revision, processes=PROCESSES),
    stage_source=lambda repo, revision, destination, on_progress=None: staging.stage_source(
        repo, revision, destination, processes=PROCESSES, on_progress=on_progress),
    init_standalone_git=partial(staging.init_standalone_git, processes=PROCESSES), scan_tree=staging.scan_tree,
    plan_import=staging.plan_import, apply_import=staging.apply_import,
    retain_evidence_handoff=handoff.retain_evidence_handoff, handoff_refs=handoff.handoff_refs,
    materialize_handoff=handoff.materialize_handoff, Artifacts=FileArtifacts, MAX_FILES=spec.MAX_FILES,
    MAX_FILE_BYTES=spec.MAX_FILE_BYTES, IsolationError=IsolationError, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("target", "containers.staging", s3_staging.run(API))
