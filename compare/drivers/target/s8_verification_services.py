"""Target driver: `host_os.verification_services` on the target tree (S8 batch B7a: `host_os.adapters.verification`).

The API mirrors the reference driver's names over the target homes. The scripted `docker` is put where the moved module looks `run_process` up (the module's own
`run_process` name, imported from `host_os.adapters.process_groups`); `published_ports` and `port_diagnosis` are the host_os adapters. The scenario reads the
kernel's default clock where M7 read `utcnow`; the harness's scripted clock reaches it through the kernel `Clock` port (the driver sets `kernel.ids.SYSTEM_CLOCK`;
the target's standard library is never patched, and `time.monotonic` is real on both sides)."""

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_verification_services  # noqa: E402
from codex_harness.host_os.adapters import port_diagnosis, published_ports  # noqa: E402
from codex_harness.host_os.adapters import verification as module  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)

API = SimpleNamespace(VerificationServices=module.VerificationServices, module=module, port_diagnosis=port_diagnosis, published_ports=published_ports,
                      ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-verification-") as raw:
        result = s8_verification_services.run(API, Path(raw).resolve())
    driver.finish("target", "host_os.verification_services", result)
