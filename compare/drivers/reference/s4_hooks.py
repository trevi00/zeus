"""Reference driver: `hooks.candidate_canary` (M7 adapters/hooks.NativeHooks.candidate/canary, domain hook_apply)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_hooks  # noqa: E402

from codex_harness.adapters.hooks import NativeHooks  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.domain.model import hook_apply  # noqa: E402

API = SimpleNamespace(MemoryStore=MemoryStore, native_hooks=NativeHooks, hook_apply=hook_apply)

if __name__ == "__main__":
    driver.finish("reference", "hooks.candidate_canary", s4_hooks.run(API))
