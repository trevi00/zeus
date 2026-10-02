"""Target driver: `observation.frontend_checks` on the target tree (`observation.adapters.monitor_frontend_checks`, the moved U9 with the D3/D3.1 seam).

The capture the composition supplies, `functools.partial(evidence_inspection._capture, process_tree=ProcessTree)` (the host_os `ProcessTree` class itself), is INJECTED here into
`observe(capture=)` and `main(capture=)` where the reference side leaves M7's module-level default. A non-None capture of a scenario is passed through unchanged. No clock or id
source is installed: temporary paths, the interpreter path, pids and durations are normalized by the shared steps."""

import functools
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s9_frontend_checks  # noqa: E402
from codex_harness.evidence.adapters.evidence_inspection import _capture  # noqa: E402
from codex_harness.host_os.adapters.process_tree import ProcessTree  # noqa: E402
from codex_harness.observation.adapters import monitor_frontend_checks as module  # noqa: E402

REAL = functools.partial(_capture, process_tree=ProcessTree)


def observe(cwd, node=None, dependencies=None, capture=None):
    return module.observe(cwd, node=node, dependencies=dependencies, capture=REAL if capture is None else capture)


def main(argv=None):
    return module.main(argv, capture=REAL)


API = SimpleNamespace(module=module, observe=observe, main=main, real_capture=lambda: REAL)

if __name__ == "__main__":
    driver.finish("target", "observation.frontend_checks", s9_frontend_checks.run(API))
