"""Reference driver: `review.release_suite` (M7 `adapters/release_suite.py`).

The API holds the plain M7 module. Its `run_logged_process` (imported from M7 `adapters.commands`) is replaced on the module by the scenario's labelled
`FakeRunner`; `ProcessCancelled` is M7's own class, so the fake raises the class the module catches. The clock and ids are not used (the module draws
neither); no real child runs."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_release_suite as common  # noqa: E402

from codex_harness.adapters import commands  # noqa: E402
from codex_harness.adapters import release_suite as module  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402


def make_suite(artifacts, fence, runner, batch_nodes=None):
    module.run_logged_process = runner
    return module.ReleaseSuite(artifacts, fence) if batch_nodes is None else module.ReleaseSuite(artifacts, fence, batch_nodes)


CONSTANTS = ("BATCH_NODES", "LOG_HEAD_BYTES", "LOG_TAIL_BYTES", "EVENTS_TAIL_BYTES", "NODE_FIELD_CHARS", "PLUGIN_MODULE", "REPORT_ENV", "SELECT_ENV",
             "LAST_TEST_NOTE")
API = SimpleNamespace(make_suite=make_suite, bounded_log=module.bounded_log, read_events=module.read_events,
                      ProcessCancelled=commands.ProcessCancelled, ContractError=ContractError, PLUGIN_SOURCE=module.PLUGIN_SOURCE,
                      constants={name: getattr(module, name) for name in CONSTANTS})

if __name__ == "__main__":
    driver.finish("reference", "review.release_suite", common.release_suite(API))
