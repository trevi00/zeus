"""Reference driver: `research.source_execution_adapter` (M7 `adapters/source_execution.py`: `SourceExecutionClient`, `bounded_command`,
`DockerSourceRunner`).

The API holds the plain M7 module. As M7's tests do, the scenario's LABELLED fakes replace the module's `bounded_command`, `run_process`,
`SourceExecutions` and `time` (and, for the direct `bounded_command` cases, the stdlib `subprocess.Popen` and the module's `no_console_kwargs`). The
module's `DRIVER_HASH`, `platform` and `uuid4` are pinned (normalization rule 1 of the common module)."""

import contextlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_source_execution_adapter as common  # noqa: E402

from codex_harness.adapters import source_execution as module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.domain.model import ContractError, canonical  # noqa: E402
from codex_harness.domain.policy import POLICY  # noqa: E402
from codex_harness.domain.research import ExecutionReceipt, SourceIdentity  # noqa: E402

REAL_DRIVER_HASH = module.DRIVER_HASH


def runner(root, artifacts, bounded, run_process, docker):
    module.bounded_command, module.run_process = bounded, run_process
    module.DRIVER_HASH, module.platform, module.uuid4 = common.DRIVER_HASH, SimpleNamespace(platform=lambda: common.PLATFORM), common.Ids()
    return module.DockerSourceRunner(root, artifacts) if docker is None else module.DockerSourceRunner(root, artifacts, docker)


def run_one(runner_, workflow, queue):
    module.SourceExecutions = queue
    return runner_.run_one(workflow)


def client_execute(workflow, task, source, command, timeout, queue, clock):
    module.SourceExecutions, module.time = queue, clock
    client = module.SourceExecutionClient()
    return client.execute(workflow, task, source, command) if timeout is None else client.execute(workflow, task, source, command, timeout)


@contextlib.contextmanager
def fake_popen(popen):
    saved = subprocess.Popen
    subprocess.Popen = popen
    try:
        yield
    finally:
        subprocess.Popen = saved


def bounded(argv, timeout, popen):
    module.no_console_kwargs = lambda: dict(common.CONSOLE_MARK)
    with fake_popen(popen):
        return module.bounded_command(argv, timeout)


API = SimpleNamespace(runner=runner, run_one=run_one, client_execute=client_execute, bounded=bounded, real_driver_hash=REAL_DRIVER_HASH,
                      FileArtifacts=FileArtifacts, SourceIdentity=SourceIdentity, ExecutionReceipt=ExecutionReceipt, ContractError=ContractError,
                      canonical=canonical, POLICY=POLICY)

if __name__ == "__main__":
    driver.finish("reference", "research.source_execution_adapter", common.source_execution_adapter(API))
