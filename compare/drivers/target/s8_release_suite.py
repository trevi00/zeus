"""Target driver: `review.release_suite` on the target tree (S8 pilot 95: `review.adapters.release_suite` (V19 R-rs0..R-rs2: the process runner
and the redaction rules are injected keyword-only)).

`make_suite` injects the scenario's labelled `FakeRunner` as `run_logged_process` (the reference patches M7's module attribute instead) and
observation's `redact_text`/`redact_value` where the reference module imports M7's own; `bounded_log` passes observation's `redact_text`.
`ProcessCancelled` is host_os's class (the one the moved module catches) and `ContractError` the target kernel's."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_release_suite as common  # noqa: E402
from codex_harness.host_os.ports import ProcessCancelled  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.observation.domain.observation import redact_text, redact_value  # noqa: E402
from codex_harness.review.adapters import release_suite as module  # noqa: E402


def make_suite(artifacts, fence, runner, batch_nodes=None):
    wired = {"run_logged_process": runner, "redact": redact_text, "redact_value": redact_value}
    return module.ReleaseSuite(artifacts, fence, **wired) if batch_nodes is None else module.ReleaseSuite(artifacts, fence, batch_nodes, **wired)


def bounded_log(path, *args):
    return module.bounded_log(path, *args, redact=redact_text)


CONSTANTS = ("BATCH_NODES", "LOG_HEAD_BYTES", "LOG_TAIL_BYTES", "EVENTS_TAIL_BYTES", "NODE_FIELD_CHARS", "PLUGIN_MODULE", "REPORT_ENV", "SELECT_ENV",
             "LAST_TEST_NOTE")
API = SimpleNamespace(make_suite=make_suite, bounded_log=bounded_log, read_events=module.read_events, ProcessCancelled=ProcessCancelled,
                      ContractError=ContractError, PLUGIN_SOURCE=module.PLUGIN_SOURCE, constants={name: getattr(module, name) for name in CONSTANTS})

if __name__ == "__main__":
    driver.finish("target", "review.release_suite", common.release_suite(API))
