"""The ported suites' shared objects (S11 TISO-1; moved verbatim from `tests/ported/conftest.py`).

A uniquely named module: `from conftest import …` in a ported module resolved to the top-level `tests/conftest.py` when
pytest had already registered that one as `conftest` (e.g. `pytest tests/test_s4_transports.py` alone), so those imports
failed by collection order. `tests/ported/conftest.py` re-exports these same objects.

- `ATTESTED`: the git-attested runtime root of the ported delivery suites, built before the first ported module is
  imported.
- `NATIVE_THRESHOLDS`: stands in for research's native threshold resolution (M7
  `adapters.runtime_thresholds.effective_policy`) over the packaged definition.
"""

import json
from pathlib import Path

import codex_harness
from codex_harness.kernel.ids import digest

# Module-relative on purpose (owner, S11 int61): `tests/ported/` -> parents[2] is the distribution root in BOTH layouts,
# and child processes import this module with only `tests/ported` on sys.path, where `_layout` is not importable.
TARGET = Path(__file__).resolve().parents[2]

ATTESTED = {}

# The package under test is the codex_harness this process imported, not this checkout's `src` (cutover G2-W1 W1a): the
# incumbent suite runs against the candidate package from a second checkout. Children import this module with only
# `tests/ported` on sys.path, so the anchor here is the import system, not `_audit_root`.
PACKAGE = Path(codex_harness.__spec__.origin).resolve().parent
RESOURCES = PACKAGE / "resources"


class NativeThresholds:
    def effective_policy(self):
        text = (RESOURCES / "threshold-policy.json").read_text(encoding="utf-8")
        policy = json.loads(text)
        values = {"skill_match.FULL_BODY_MIN_SCORE": 3, **policy["overrides"]}
        return {"values": values, "definition_hash": digest(text), "definition": policy}


NATIVE_THRESHOLDS = NativeThresholds()
