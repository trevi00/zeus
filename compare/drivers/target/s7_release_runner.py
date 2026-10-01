"""Target driver: `delivery.release_runner` on the target tree (S7 pilot 47; DESIGN-s7 adapters-move §13).

The API holds the moved `delivery.adapters.deployment` names with the V6 injections closed over the wiring composition
passes (`composition.release_verification.release_runner`), so the common module runs unchanged:
- `ReleaseRunner(...)` is `release_runner(...)` with `runner`, `verification_services`, `request_rebase`, `release_suite`
  and `hooks` supplied here, since their owners (S8/S10/S5) are not in the target:
  - `runner` is a holder that `install_process_double` swaps (default `process_groups.run_process`);
  - `verification_services` is a holder that `install_seam("VerificationServices")` swaps (default: a LABELLED refusal);
  - `request_rebase` is a holder that `install_seam("request_rebase")` swaps; the seam values take an unbound `self`
    first (the reference replaces `Workflow.request_rebase`), so the holder calls `value(<MessageHandler-shaped
    holder>, task_id, new_base)` (default: a LABELLED refusal);
  - `release_suite` and `hooks` are LABELLED refusals ("never reached: probe run 001", DESIGN-s7 §13).
- `install_seam("controller_code_revision")` and `install_seam("rmtree")` replace the target module attribute and
  `shutil.rmtree`, as the reference does.
- `Harness` is a holder that validates the organization and holds `.store`/`.org` (M7 `application.service.Harness`'s
  only use in this family); `organization` is `routing.adapters.organization_source.packaged_organization`.
- `attempt_resources` is the moved function with `naming` closed over `ExecutionContainerNaming()`.
- The check_results names come from `review.domain.check_results`.

The clock: ONE fake clock of the reference's shape (`determinism.FakeClock`) reaches the runner, `Releases` and
`FileArtifacts` through the injected clock port; no module clock is patched."""

import shutil
import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_release_runner  # noqa: E402
from codex_harness.composition.release_verification import (  # noqa: E402
    ExecutionContainerNaming,
    release_runner,
)
from codex_harness.delivery.adapters import deployment  # noqa: E402
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.host_os.adapters.git_workspace import GitWorkspace  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.review.domain import check_results  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT = PortClock(CLOCK)


class Holder:
    """A swappable collaborator: calls go to `value`, which `install_seam`/`install_process_double` replace."""

    def __init__(self, value):
        self.value = value

    def __call__(self, *args, **kwargs):
        return self.value(*args, **kwargs)

    def swap(self, value):
        original, self.value = self.value, value
        return lambda: setattr(self, "value", original)


def refusal(label):
    def refuse(*args, **kwargs):
        raise AssertionError("target driver: " + label)
    return refuse


RUNNER = Holder(process_groups.run_process)
SERVICES = Holder(refusal("VerificationServices reached without install_seam('VerificationServices')"))
REBASE = Holder(refusal("request_rebase reached without install_seam('request_rebase')"))
SUITE_REFUSAL = refusal("ReleaseSuite never reached: probe run 001")
HOOKS_REFUSAL = refusal("NativeHooks never reached: probe run 001")


class Harness:
    """M7 `Harness` as this family uses it: validate the organization, hold `.store` and `.org`."""

    def __init__(self, store, organization):
        organization.validate()
        self.store, self.org = store, organization


def ReleaseRunner(service, git, artifacts, auth, auto_merge=True, fence=None, verification_root=None):
    handler = SimpleNamespace(store=service.store, org=service.org)   # the MessageHandler-shaped `self` of the seam
    return release_runner(
        service, git, artifacts, auth, auto_merge, fence, verification_root, runner=RUNNER,
        release_suite=SUITE_REFUSAL, verification_services=SERVICES, hooks=HOOKS_REFUSAL,
        request_rebase=lambda task_id, new_base: REBASE.value(handler, task_id, new_base), clock=PORT, ids=PortIds(IDS))


# The unbound staticmethod the controller cases call on the class, as on the reference's `ReleaseRunner`.
ReleaseRunner._require_controller_code = deployment.ReleaseRunner._require_controller_code


def install_seam(name, value):
    if name == "VerificationServices":
        return SERVICES.swap(value)
    if name == "request_rebase":
        return REBASE.swap(value)
    owner, attribute = {"controller_code_revision": (deployment, "controller_code_revision"),
                        "rmtree": (shutil, "rmtree")}[name]
    original = getattr(owner, attribute)
    setattr(owner, attribute, value)
    return lambda: setattr(owner, attribute, original)


API = SimpleNamespace(
    ReleaseRunner=ReleaseRunner, Harness=Harness, MemoryStore=MemoryStore,
    FileArtifacts=lambda root: FileArtifacts(root, clock=PORT), GitWorkspace=GitWorkspace,
    organization=packaged_organization, ContractError=ContractError, digest=digest, canonical=canonical,
    EvaluatorPinMismatch=deployment.EvaluatorPinMismatch, EvaluatorCodeMismatch=deployment.EvaluatorCodeMismatch,
    canary_handoff_script=deployment.canary_handoff_script, canary_postcondition=deployment.canary_postcondition,
    inspect_canary_file=deployment.inspect_canary_file,
    attempt_resources=partial(deployment.attempt_resources, naming=ExecutionContainerNaming()),
    evaluator_patch_sha256=deployment.evaluator_patch_sha256, resolve_evaluator_pin=deployment.resolve_evaluator_pin,
    uv_command=deployment.uv_command, pytest_summary=check_results.pytest_summary,
    classify_test_run=check_results.classify_test_run, is_test_run=check_results.is_test_run,
    bind_revision=check_results.bind_revision, OUTCOMES=check_results.OUTCOMES,
    install_process_double=RUNNER.swap, install_seam=install_seam, reset_ids=IDS.reset)

if __name__ == "__main__":
    driver.finish("target", "delivery.release_runner", s7_release_runner.run(API))
