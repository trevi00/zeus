"""Target driver: `delivery.host_targets` on the target tree (S7 pilot 42a).

The API holds the moved `delivery.adapters.host_delivery` names with the V6 injections closed over composition's
wiring, exactly as composition and the launched child's entry wire them (DESIGN-s7 adapters-move §9.4):
- `ProcessHostTarget` is a thin wired subclass (`processes=ChokepointProcesses()`), so a case may subclass it;
- `GitHubDelivery` defaults its `runner` to `process_groups.run_process` unless the case supplies a labelled one;
- `serve`, `main` and `startup_receipt` pass the effective worker image (`composition.configuration.settings`) and the
  worker profile digest (`context.adapters.worker_profile`) as the entry does.

`PACKAGE_DIR` is the TARGET package directory: the launched child's runtime root links to it, so the child runs the
target's shim -> entry -> serve. `SOURCE_PACKAGE` is still the SOURCE archive (the attested fixture root).
`advance` is a no-op: this driver installs no determinism."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s7_host_targets  # noqa: E402

import codex_harness  # noqa: E402
from codex_harness.composition import configuration  # noqa: E402
from codex_harness.context.adapters import worker_profile  # noqa: E402
from codex_harness.delivery.adapters import host_delivery  # noqa: E402
from codex_harness.delivery.domain import host_delivery as domain  # noqa: E402
from codex_harness.entry.processes import delivery_service  # noqa: E402
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.host_os.adapters.git_workspace import MergeRefused  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402


class WiredProcessHostTarget(host_delivery.ProcessHostTarget):
    def __init__(self, **kwargs):
        super().__init__(processes=process_groups.ChokepointProcesses(), **kwargs)


class WiredGitHubDelivery(host_delivery.GitHubDelivery):
    def __init__(self, workspace, *, runner=process_groups.run_process, **kwargs):
        super().__init__(workspace, runner=runner, **kwargs)


def _effective():
    return (host_delivery.effective_worker_image(configuration.settings()),
            host_delivery.effective_profile_digest(worker_profile))


def serve(state_dir, max_seconds=host_delivery.SERVICE_MAX_SECONDS):
    image, digest = _effective()
    return host_delivery.serve(state_dir, max_seconds, image=image, profile_digest=digest)


def startup_receipt(descriptor):
    image, digest = _effective()
    return host_delivery.startup_receipt(descriptor, image=image, profile_digest=digest)


API = SimpleNamespace(
    ProcessHostTarget=WiredProcessHostTarget, HostTargetBase=host_delivery.HostTargetBase,
    GitHubDelivery=WiredGitHubDelivery, serve=serve, main=delivery_service.main,
    startup_receipt=startup_receipt, reaped=host_delivery._reaped, alive=host_delivery._alive,
    DESCRIPTOR_FILE=host_delivery.DESCRIPTOR_FILE, RECEIPT_FILE=host_delivery.RECEIPT_FILE,
    STATE_FILE=host_delivery.STATE_FILE, WORK_FILE=host_delivery.WORK_FILE, STOP_FILE=host_delivery.STOP_FILE,
    PAUSE_FILE=host_delivery.PAUSE_FILE, LOCK_DIR=host_delivery.LOCK_DIR,
    validate_descriptor=domain.validate_descriptor, descriptor_digest=domain.descriptor_digest,
    consumption_verdict=domain.consumption_verdict, DeliveryRefused=domain.DeliveryRefused,
    LifecycleInterrupted=domain.LifecycleInterrupted, DESCRIPTOR_SCHEMA=domain.DESCRIPTOR_SCHEMA,
    RECEIPT_SCHEMA=domain.RECEIPT_SCHEMA, ContractError=ContractError, MergeRefused=MergeRefused,
    PACKAGE_DIR=Path(codex_harness.__file__).resolve().parent, advance=lambda seconds: None,
    SOURCE_PACKAGE=Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "src" / "codex_harness",
    effective_profile_digest=lambda: host_delivery.effective_profile_digest(worker_profile))

if __name__ == "__main__":
    driver.finish("target", "delivery.host_targets", s7_host_targets.run(API))
