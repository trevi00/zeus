"""Reference driver: `research.reverse_source` (M7 `adapters/reverse_source.py: `observe_source``).

The API holds the plain M7 module; `observe(path, process)` is the M7 seam: the module's `run_process` name replaced by the scenario's LABELLED
fake for the call (what M7's `monkeypatch.setattr('codex_harness.adapters.reverse_source.run_process', run)` does).

The clock and ids are not used (no result holds a time or an id)."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_hostos_adapters as common  # noqa: E402

from codex_harness.adapters import reverse_source as module  # noqa: E402


def observe(path, process):
    saved = module.run_process
    module.run_process = process
    try:
        return module.observe_source(path)
    finally:
        module.run_process = saved


API = SimpleNamespace(observe=observe)

if __name__ == "__main__":
    driver.finish("reference", "research.reverse_source", common.reverse_source(API))
