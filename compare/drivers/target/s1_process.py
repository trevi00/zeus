"""Target driver: `host_os.process` on the target tree (process_groups, process_tree, scratch, pure
diagnostics). Children are the target interpreter running fixed one-line programs.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s1_process  # noqa: E402
from codex_harness.host_os.adapters import (  # noqa: E402
    background_service,
    port_diagnosis,
    process_groups,
    process_tree,
    published_ports,
    scratch,
    service_entry,
)
from codex_harness.kernel.errors import ContractError  # noqa: E402

API = SimpleNamespace(
    no_console_kwargs=process_groups.no_console_kwargs,
    python_channel_environment=process_groups.python_channel_environment,
    run_process=process_groups.run_process, run_logged_process=process_groups.run_logged_process,
    observe_spawns=process_groups.observe_spawns, ProcessCancelled=process_groups.ProcessCancelled,
    ProcessTree=process_tree.ProcessTree, Scratch=scratch.Scratch, publication=published_ports.publication,
    narrow=port_diagnosis.narrow, parse_service_args=service_entry._parse, exit_facts=service_entry._exit_facts,
    safe_scalar=background_service.safe_scalar, ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s1-process-") as raw:
        result = s1_process.run(API, Path(raw).resolve())
    driver.finish("target", "host_os.process", result)
