"""Target driver: `research.source_execution_adapter` on the target tree (S8 pilot 96: `research.adapters.source_execution`, V18 R-se1/R-se2: host_os's
`ChildProcesses` is the keyword-only port `processes`, `ProcessRunner` is `run_process` and `classify_isolated_run` is `classify`).

The scenario's LABELLED fakes are the ones the reference patches onto M7's module: the module-level `bounded_command`, `SourceExecutions` and `time`
are replaced the same way; `run_process` is injected, `classify` is the real `review.domain.check_results.classify_isolated_run` (injected), and the
`processes` port is a LABELLED `ChildProcesses` double whose `popen` calls the scenario's fake `Popen` with the no-console keywords the reference's
patched `no_console_kwargs` returns (what `ChokepointProcesses.popen` does with the real ones). The module's `DRIVER_HASH`, `platform` and `uuid4` are
pinned (normalization rule 1 of the common module). Nothing in the standard library is patched."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_source_execution_adapter as common  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.research.adapters import source_execution as module  # noqa: E402
from codex_harness.research.domain.research import ExecutionReceipt, SourceIdentity  # noqa: E402
from codex_harness.review.domain.check_results import classify_isolated_run  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402

REAL_DRIVER_HASH = module.DRIVER_HASH


class Processes:
    """LABELLED double of `host_os.ports.ChildProcesses`: `popen` applies the (fake) no-console keywords itself, as the chokepoint implementation does."""

    def __init__(self, popen):
        self.fake = popen

    def popen(self, argv, *, process_group=False, **kwargs):
        return self.fake(argv, **kwargs, **common.CONSOLE_MARK)


def runner(root, artifacts, bounded, run_process, docker):
    """The runner with the scenario's `bounded_command` double on the module (as the reference does) and the three ports injected; the double
    checks it is handed the runner's own `processes`."""
    processes = Processes(None)

    def wired(argv, timeout, processes=None):
        assert processes is made.processes, "bounded_command was not handed the runner's processes"
        return bounded(argv, timeout, processes)

    module.bounded_command = wired
    module.DRIVER_HASH, module.platform, module.uuid4 = common.DRIVER_HASH, SimpleNamespace(platform=lambda: common.PLATFORM), common.Ids()
    ports = dict(processes=processes, run_process=run_process, classify=classify_isolated_run)
    made = module.DockerSourceRunner(root, artifacts, **ports) if docker is None else module.DockerSourceRunner(root, artifacts, docker, **ports)
    return made


def run_one(runner_, workflow, queue):
    module.SourceExecutions = queue
    return runner_.run_one(workflow)


def client_execute(workflow, task, source, command, timeout, queue, clock):
    module.SourceExecutions, module.time = queue, clock
    client = module.SourceExecutionClient()
    return client.execute(workflow, task, source, command) if timeout is None else client.execute(workflow, task, source, command, timeout)


def bounded(argv, timeout, popen):
    return module.bounded_command(argv, timeout, processes=Processes(popen))


API = SimpleNamespace(runner=runner, run_one=run_one, client_execute=client_execute, bounded=bounded, real_driver_hash=REAL_DRIVER_HASH,
                      FileArtifacts=FileArtifacts, SourceIdentity=SourceIdentity, ExecutionReceipt=ExecutionReceipt, ContractError=ContractError,
                      canonical=canonical, POLICY=POLICY)

if __name__ == "__main__":
    driver.finish("target", "research.source_execution_adapter", common.source_execution_adapter(API))
