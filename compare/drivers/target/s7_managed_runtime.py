"""Target driver: `delivery.managed_runtime` on the target tree (S7 pilot 43).

The API holds the moved `delivery.adapters.managed_runtime` names with the V6 injections closed over composition's
wiring (`s7_managed_composition`): the managed classes are thin wired subclasses, `entry`, `launch`, `run_fixture` and
`host_ports` are composition's, `Fleet` composes the S5 target objects. `PACKAGE_DIR` is the TARGET package directory
(the trusted launcher runs the target's shim -> entry -> launch); `SOURCE_PACKAGE` is still the SOURCE archive (the
fixture source repository copies it, so the sealed runtimes are identical inputs on both sides). `sync_clock` and
`reset_ids` are the reference driver's: the fake clock on the real wall time and the id source of the stage names."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s7_managed_composition  # noqa: E402
import s7_managed_runtime  # noqa: E402
from codex_harness.context.adapters import worker_profile  # noqa: E402
from codex_harness.delivery.adapters import host_delivery  # noqa: E402


IDS = s7_managed_runtime.SpreadIds()


def Materializer(target, **kwargs):
    return s7_managed_composition.Materializer(target, new_hex=lambda: IDS.uuid4().hex, **kwargs)


def sync_clock():
    """No-op: the target driver installs no determinism; its clock is the real wall time."""


API = SimpleNamespace(
    **{**s7_managed_composition.names(), "Materializer": Materializer},
    effective_profile_digest=lambda: host_delivery.effective_profile_digest(worker_profile),
    SOURCE_PACKAGE=Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "src" / "codex_harness",
    sync_clock=sync_clock, reset_ids=IDS.reset)

if __name__ == "__main__":
    driver.finish("target", "delivery.managed_runtime", s7_managed_runtime.run(API))
