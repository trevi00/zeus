"""Target driver: `coordination.continuation_binding` on the target tree (`ContinuationBindings(store).binding`; case f is `RunTask._continuation` with no port)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s10_continuation_binding  # noqa: E402
from codex_harness.coordination.application.continuation.bindings import (  # noqa: E402
    ContinuationBindings,
)
from codex_harness.execution.application.run_task import RunTask  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402


def binding(store, details):
    return ContinuationBindings(store).binding(details)


def legacy(store, details):
    return RunTask._continuation(SimpleNamespace(continuations=None), details)


if __name__ == "__main__":
    driver.finish("target", "coordination.continuation_binding", s10_continuation_binding.run(binding, MemoryStore, legacy))
