"""Reference driver: `review.release_verifier` (M7 `adapters/release_verifier.py`: `ReleaseVerifier`, `CancellationBoundary`, `bounded_fence`, `HostFacts`).

The API holds the plain M7 objects. The one scripted `docker` answers where M7 resolves its process runner: `isolated_worker.run_process` (what `_docker` of every
`OwnedContainer` call and of the verifier's listings reads) and `verification.run_process` (the compose verbs of `VerificationServices`). `commands._announce` is the
spawn notification a recorded child arrives through. The wall clock for `utcnow` is the harness's (`determinism.install`); `time.monotonic` stays REAL (fence waits are
real, shortened). No Docker, registry or network is used."""

import inspect
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
import s8_release_verifier  # noqa: E402

from codex_harness.adapters import commands, deployment, verification  # noqa: E402
from codex_harness.adapters import isolated_worker as iw  # noqa: E402
from codex_harness.adapters import release_verifier as module  # noqa: E402
from codex_harness.application.tickets import TicketSuperseded  # noqa: E402
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


def install_runner(fake):
    iw.run_process = fake
    verification.run_process = fake


API = SimpleNamespace(
    module=module, ReleaseVerifier=module.ReleaseVerifier, CancellationBoundary=module.CancellationBoundary, bounded_fence=module.bounded_fence,
    EvaluationCancelled=module.EvaluationCancelled, FenceLost=module.FenceLost, FenceUnobservable=module.FenceUnobservable, HostFacts=module.HostFacts,
    observe_spawns=commands.observe_spawns, announce=commands._announce, install_runner=install_runner, signature=inspect.signature,
    attempt_resources=deployment.attempt_resources, ATTEMPT_ID=deployment.ATTEMPT_ID, RETRY_OBSERVATION=deployment.RETRY_OBSERVATION,
    new_owned=lambda docker, run_id, role: iw.OwnedContainer({"limits": iw.LIMITS, "image": None}, docker, run_id, role),
    ContractError=ContractError, TicketSuperseded=TicketSuperseded)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-release-verifier-") as raw:
        result = s8_release_verifier.run(API, Path(raw).resolve())
    driver.finish("reference", "review.release_verifier", result)
