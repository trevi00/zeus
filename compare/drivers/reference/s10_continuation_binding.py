"""Reference driver: `coordination.continuation_binding` on SOURCE M7 (`Executor._continuation`, called UNBOUND with a minimal `self`)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s10_continuation_binding  # noqa: E402

from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402


def binding(store, details):
    return Executor._continuation(SimpleNamespace(service=SimpleNamespace(store=store)), details)


if __name__ == "__main__":
    driver.finish("reference", "coordination.continuation_binding",
                  s10_continuation_binding.run(binding, MemoryStore))
