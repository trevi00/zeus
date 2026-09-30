"""Reference driver: `delivery.release_runner` (M7 `adapters/deployment.py`: `ReleaseRunner`, the file canary, the check
binding, the evaluator pin and controller code refusals).

The API holds plain M7 objects:
- `adapters.deployment`: `ReleaseRunner`, `EvaluatorPinMismatch`, `EvaluatorCodeMismatch`, `canary_handoff_script`,
  `canary_postcondition`, `inspect_canary_file`, `attempt_resources`, `evaluator_patch_sha256`,
  `resolve_evaluator_pin` and `uv_command`;
- `application.service.Harness`, `adapters.store.MemoryStore`, `adapters.artifacts.FileArtifacts`,
  `adapters.git.GitWorkspace`, `application.workflow.Workflow` and `bootstrap.organization` (the construction M7's
  `tests/test_release_runner.py`, `tests/test_file_canary.py` and `tests/test_check_binding.py` use);
- `domain.model`: `ContractError`, `digest` and `canonical`;
- `domain.check_results`: `pytest_summary`, `classify_test_run`, `is_test_run`, `bind_revision` and `OUTCOMES`.

The process double and the other M7 test seams are installed by replacing a module attribute for one case and
restoring it, as M7's tests do with monkeypatch:
- `install_process_double(fn)` replaces `codex_harness.adapters.deployment.run_process`;
- `install_seam(name, value)` replaces, by name, `deployment.VerificationServices`,
  `deployment.controller_code_revision`, `deployment.shutil.rmtree` (M7 patches it on the shared `shutil` module) and
  `Workflow.request_rebase`.
Both return the restore callable. `reset_ids()` restarts the fake id stream at the start of a case. The module reads
no other clock and no id source.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_release_runner  # noqa: E402

from codex_harness.adapters import deployment  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.git import GitWorkspace  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.application.workflow import Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import check_results  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, digest  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)

SEAMS = {
    "VerificationServices": (deployment, "VerificationServices"),
    "controller_code_revision": (deployment, "controller_code_revision"),
    "rmtree": (deployment.shutil, "rmtree"),
    "request_rebase": (Workflow, "request_rebase")}


def install_seam(name, value):
    owner, attribute = SEAMS[name]
    original = getattr(owner, attribute)
    setattr(owner, attribute, value)
    return lambda: setattr(owner, attribute, original)


API = SimpleNamespace(
    ReleaseRunner=deployment.ReleaseRunner, Harness=Harness, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts,
    GitWorkspace=GitWorkspace, organization=organization, ContractError=ContractError, digest=digest,
    canonical=canonical, Workflow=Workflow, EvaluatorPinMismatch=deployment.EvaluatorPinMismatch,
    EvaluatorCodeMismatch=deployment.EvaluatorCodeMismatch, canary_handoff_script=deployment.canary_handoff_script,
    canary_postcondition=deployment.canary_postcondition, inspect_canary_file=deployment.inspect_canary_file,
    attempt_resources=deployment.attempt_resources, evaluator_patch_sha256=deployment.evaluator_patch_sha256,
    resolve_evaluator_pin=deployment.resolve_evaluator_pin, uv_command=deployment.uv_command,
    pytest_summary=check_results.pytest_summary, classify_test_run=check_results.classify_test_run,
    is_test_run=check_results.is_test_run, bind_revision=check_results.bind_revision, OUTCOMES=check_results.OUTCOMES,
    install_process_double=lambda fn: install_seam_run_process(fn), install_seam=install_seam, reset_ids=IDS.reset)


def install_seam_run_process(fn):
    original = deployment.run_process
    deployment.run_process = fn
    return lambda: setattr(deployment, "run_process", original)


if __name__ == "__main__":
    driver.finish("reference", "delivery.release_runner", s7_release_runner.run(API))
