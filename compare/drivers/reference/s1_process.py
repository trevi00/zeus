"""Reference driver: `host_os.process` on SOURCE M7.

M7 `adapters.commands` (run_process, run_logged_process, observe_spawns, no_console_kwargs,
python_channel_environment), `adapters.process_tree.ProcessTree`, `adapters.scratch.Scratch`,
and the pure pieces of `published_ports`, `port_diagnosis`, `service_entry` and
`background_service`. Children are the reference interpreter running fixed one-line programs.
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s1_process  # noqa: E402

from codex_harness.adapters import (  # noqa: E402
    background_service,
    commands,
    port_diagnosis,
    process_tree,
    published_ports,
    scratch,
    service_entry,
)
from codex_harness.domain.model import ContractError  # noqa: E402

API = SimpleNamespace(
    no_console_kwargs=commands.no_console_kwargs, python_channel_environment=commands.python_channel_environment,
    run_process=commands.run_process, run_logged_process=commands.run_logged_process,
    observe_spawns=commands.observe_spawns, ProcessCancelled=commands.ProcessCancelled,
    ProcessTree=process_tree.ProcessTree, Scratch=scratch.Scratch, publication=published_ports.publication,
    narrow=port_diagnosis.narrow, parse_service_args=service_entry._parse, exit_facts=service_entry._exit_facts,
    safe_scalar=background_service.safe_scalar, ContractError=ContractError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s1-process-") as raw:
        result = s1_process.run(API, Path(raw).resolve())
    driver.finish("reference", "host_os.process", result)
