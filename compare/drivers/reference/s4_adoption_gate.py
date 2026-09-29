"""Reference driver: `research.adoption_gate` (M7 audit_gate binding/require_adoption/inspect_approval)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s4_adoption_gate  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.audit_gate import (  # noqa: E402
    binding,
    inspect_approval,
    require_adoption,
)
from codex_harness.domain.model import digest  # noqa: E402

API = SimpleNamespace(MemoryStore=MemoryStore, digest=digest, binding=binding, require_adoption=require_adoption,
                      inspect_approval=inspect_approval)

if __name__ == "__main__":
    driver.finish("reference", "research.adoption_gate", s4_adoption_gate.run(API))
