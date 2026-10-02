"""Reference driver: `review.canary` (M7 `adapters/canary.py`).

The API holds the plain M7 module. Its `CodexRuntime` (imported from M7 `adapters.codex`) is replaced on the module by a LABELLED stand-in whose
`probe()` is the scenario's `FakeProbe`; `hook_apply` is M7's own. No real Codex binary runs."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_canary as common  # noqa: E402

from codex_harness.adapters import canary as module  # noqa: E402


def run(spec, probe):
    class Runtime:
        def probe(self):
            return probe()

    module.CodexRuntime = Runtime
    return module.executable_canary(spec)


API = SimpleNamespace(run=run)

if __name__ == "__main__":
    driver.finish("reference", "review.canary", common.canary(API))
