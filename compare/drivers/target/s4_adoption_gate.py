"""Target driver: `research.adoption_gate` on the target tree (research.application.audit_gate, moved unchanged)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s4_adoption_gate  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.application.audit_gate import (  # noqa: E402
    binding,
    inspect_approval,
    require_adoption,
)
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

API = SimpleNamespace(MemoryStore=MemoryStore, digest=digest, binding=binding, require_adoption=require_adoption,
                      inspect_approval=inspect_approval)

if __name__ == "__main__":
    driver.finish("target", "research.adoption_gate", s4_adoption_gate.run(API))
