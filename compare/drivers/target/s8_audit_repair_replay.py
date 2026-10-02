"""Target driver: `research.audit_repair_replay` on the target tree (S8 batch B3: `research.adapters.audit_repair`, DESIGN-s8 §28.1 R-rd1).

The API mirrors the reference driver's names over the target homes: `replay_decode` (verbatim; its lazy `AuditExecution` is the moved
`research.adapters.audit_execution` one) and the kernel's `canonical` and `digest`. The function is pure: no store, clock or id source is involved."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_audit_repair_replay  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.research.adapters.audit_repair import replay_decode  # noqa: E402

API = SimpleNamespace(replay_decode=replay_decode, canonical=canonical, digest=digest)

if __name__ == "__main__":
    driver.finish("target", "research.audit_repair_replay", s8_audit_repair_replay.run(API))
