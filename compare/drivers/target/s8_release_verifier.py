"""Target driver: `review.release_verifier` on the target tree (S8 batch B7b: `composition.release_verifier`).

The API mirrors the reference driver's names over the target homes. The one scripted `docker` answers where the moved module resolves its process runner: its own
`run_process` (imported from `host_os.adapters.process_groups`), which the module hands to `docker_call` for its listings and to every `OwnedContainer` it builds
(R-rv2/R-rv3), and `host_os.adapters.verification.run_process` (the compose verbs of `VerificationServices`). The scenario reads the kernel's default clock where
M7 read `utcnow`; the harness's scripted clock reaches it through the kernel `Clock` port (the driver sets `kernel.ids.SYSTEM_CLOCK`; the target's standard library
is never patched, and `time.monotonic` is real on both sides). `HostFacts` is the host_os class the module imports, never a redefinition."""

import inspect
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
import s8_release_verifier  # noqa: E402
from codex_harness.composition import release_verifier as module  # noqa: E402
from codex_harness.composition.release_verification import ExecutionContainerNaming  # noqa: E402
from codex_harness.delivery.adapters import deployment  # noqa: E402
from codex_harness.execution.adapters.containers.owned_container import OwnedContainer  # noqa: E402
from codex_harness.execution.domain.container_spec import LIMITS  # noqa: E402
from codex_harness.host_os.adapters import host_facts, process_groups, verification  # noqa: E402
from codex_harness.intake.application.tickets import TicketSuperseded  # noqa: E402
from codex_harness.kernel import ids  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
ids.SYSTEM_CLOCK = PortClock(CLOCK)


def install_runner(fake):
    module.run_process = fake
    verification.run_process = fake


API = SimpleNamespace(
    module=module, ReleaseVerifier=module.ReleaseVerifier, CancellationBoundary=module.CancellationBoundary, bounded_fence=module.bounded_fence,
    EvaluationCancelled=module.EvaluationCancelled, FenceLost=module.FenceLost, FenceUnobservable=module.FenceUnobservable, HostFacts=host_facts.HostFacts,
    observe_spawns=process_groups.observe_spawns, announce=process_groups._announce, install_runner=install_runner, signature=inspect.signature,
    attempt_resources=lambda attempt_id: deployment.attempt_resources(attempt_id, naming=ExecutionContainerNaming()), ATTEMPT_ID=deployment.ATTEMPT_ID,
    RETRY_OBSERVATION=deployment.RETRY_OBSERVATION,
    new_owned=lambda docker, run_id, role: OwnedContainer({"limits": LIMITS, "image": None}, docker, run_id, role, runner=module.run_process),
    ContractError=ContractError, TicketSuperseded=TicketSuperseded)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-release-verifier-") as raw:
        result = s8_release_verifier.run(API, Path(raw).resolve())
    driver.finish("target", "review.release_verifier", result)
