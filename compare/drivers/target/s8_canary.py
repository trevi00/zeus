"""Target driver: `review.canary` on the target tree (S8 pilot 99: `review.adapters.canary` (V18 R-cn0/R-cn1: the hook rule and the Codex probe are
injected keyword-only)).

`run` injects research's real `hook_apply` (the reference uses M7's own) and the scenario's labelled `FakeProbe` as `probe` (the reference replaces
M7's `CodexRuntime` on the module instead). No real Codex binary runs."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_canary as common  # noqa: E402
from codex_harness.research.domain.recurrence import hook_apply  # noqa: E402
from codex_harness.review.adapters import canary as module  # noqa: E402


def run(spec, probe):
    return module.executable_canary(spec, hook_apply=hook_apply, probe=probe)


API = SimpleNamespace(run=run)

if __name__ == "__main__":
    driver.finish("target", "review.canary", common.canary(API))
