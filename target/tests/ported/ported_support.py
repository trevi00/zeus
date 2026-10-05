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

from codex_harness.kernel.ids import digest

ATTESTED = {}

RESOURCES = Path(__file__).resolve().parents[2] / "src" / "codex_harness" / "resources"


class NativeThresholds:
    def effective_policy(self):
        text = (RESOURCES / "threshold-policy.json").read_text(encoding="utf-8")
        policy = json.loads(text)
        values = {"skill_match.FULL_BODY_MIN_SCORE": 3, **policy["overrides"]}
        return {"values": values, "definition_hash": digest(text), "definition": policy}


NATIVE_THRESHOLDS = NativeThresholds()
