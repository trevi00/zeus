"""Reference driver: `host_os.verification_services` (M7 `adapters/verification.py`: `VerificationServices` and its attempt machinery).

The API holds the plain M7 module. The scripted `docker` is put where the module looks `run_process` up; `published_ports.choose` and the `port_diagnosis`
probes are scripted by the scenario through the module objects handed over here. The wall clock for `utcnow` is the harness's (`determinism.install`);
`time.monotonic` stays REAL, because readiness waits, reclaim windows and loopback sockets are real time, and the id source is not read by any step
(the scenario names its projects). No Docker, registry or network beyond loopback is used."""

import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_verification_services  # noqa: E402

from codex_harness.adapters import port_diagnosis, published_ports  # noqa: E402
from codex_harness.adapters import verification as module  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)
time.monotonic = determinism.ORIGINAL_MONOTONIC
for loaded in list(sys.modules.values()):
    if loaded is None or not getattr(loaded, "__name__", "").startswith("codex_harness"):
        continue
    for attr, value in list(vars(loaded).items()):
        if getattr(value, "__self__", None) is CLOCK and getattr(value, "__name__", "") == "monotonic":
            setattr(loaded, attr, determinism.ORIGINAL_MONOTONIC)

API = SimpleNamespace(VerificationServices=module.VerificationServices, module=module, port_diagnosis=port_diagnosis, published_ports=published_ports,
                      ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-verification-") as raw:
        result = s8_verification_services.run(API, Path(raw).resolve())
    driver.finish("reference", "host_os.verification_services", result)
