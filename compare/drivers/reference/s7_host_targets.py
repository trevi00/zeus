"""Reference driver: `delivery.host_targets` (M7 `ProcessHostTarget`, its service child, `GitHubDelivery`).

The API holds plain M7 objects from `adapters.host_delivery`:
- `ProcessHostTarget`, `HostTargetBase`, `GitHubDelivery`;
- `serve`, `main` and `startup_receipt` (the launched service's entry points);
- `reaped` and `alive` (the module's `_reaped` and `_alive`, the pid reaping and liveness checks);
- the file names `DESCRIPTOR_FILE`, `RECEIPT_FILE`, `STATE_FILE`, `WORK_FILE`, `STOP_FILE`, `PAUSE_FILE`,
  `LOCK_DIR`.

It also holds these M7 domain and adapter names the cases use:
- `validate_descriptor`, `descriptor_digest`, `consumption_verdict`, `DeliveryRefused` and `LifecycleInterrupted`
  (`domain.host_delivery`);
- `DESCRIPTOR_SCHEMA`, `RECEIPT_SCHEMA` (`domain.host_delivery`);
- `ContractError` (`domain.model`) and `MergeRefused` (`adapters.git`).

`PACKAGE_DIR` is the directory of the imported `codex_harness` package: the launched child's runtime root links to
it, so the child runs this side's OWN `service`. `advance(seconds)` moves the driver's fake clock, because
`determinism.install` freezes `time.monotonic` and M7's bounded lock wait reads it. The module reads no other
clock and no id source."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_host_targets  # noqa: E402

import codex_harness  # noqa: E402
from codex_harness.adapters import host_delivery  # noqa: E402
from codex_harness.adapters.git import MergeRefused  # noqa: E402
from codex_harness.domain import host_delivery as domain  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
API = SimpleNamespace(
    ProcessHostTarget=host_delivery.ProcessHostTarget, HostTargetBase=host_delivery.HostTargetBase,
    GitHubDelivery=host_delivery.GitHubDelivery, serve=host_delivery.serve, main=host_delivery.main,
    startup_receipt=host_delivery.startup_receipt, reaped=host_delivery._reaped, alive=host_delivery._alive,
    DESCRIPTOR_FILE=host_delivery.DESCRIPTOR_FILE, RECEIPT_FILE=host_delivery.RECEIPT_FILE,
    STATE_FILE=host_delivery.STATE_FILE, WORK_FILE=host_delivery.WORK_FILE, STOP_FILE=host_delivery.STOP_FILE,
    PAUSE_FILE=host_delivery.PAUSE_FILE, LOCK_DIR=host_delivery.LOCK_DIR,
    validate_descriptor=domain.validate_descriptor, descriptor_digest=domain.descriptor_digest,
    consumption_verdict=domain.consumption_verdict, DeliveryRefused=domain.DeliveryRefused,
    LifecycleInterrupted=domain.LifecycleInterrupted, DESCRIPTOR_SCHEMA=domain.DESCRIPTOR_SCHEMA,
    RECEIPT_SCHEMA=domain.RECEIPT_SCHEMA, ContractError=ContractError, MergeRefused=MergeRefused,
    PACKAGE_DIR=Path(codex_harness.__file__).resolve().parent, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "delivery.host_targets", s7_host_targets.run(API))
