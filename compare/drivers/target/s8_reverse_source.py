"""Target driver: `research.reverse_source` on the target tree (S8 pilot 91: ``research.adapters.reverse_source` (V18 R-rs1: `run_process` is an injected keyword-only port)`).

`observe(path, process)` injects the scenario's LABELLED fake as `run_process=`, where the reference replaces the module name."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_hostos_adapters as common  # noqa: E402
from codex_harness.research.adapters import reverse_source as module  # noqa: E402


def observe(path, process):
    return module.observe_source(path, run_process=process)


API = SimpleNamespace(observe=observe)

if __name__ == "__main__":
    driver.finish("target", "research.reverse_source", common.reverse_source(API))
