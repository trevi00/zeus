"""Reference driver: `research.correction_feedback` (M7 `adapters/correction_feedback.py`).

The API holds the plain M7 module, which redacts with M7's own `domain.observation.redact_text`, and M7's `adapters.store.MemoryStore`.

The clock and ids are not used (the module draws neither)."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import s8_correction_feedback as common  # noqa: E402

from codex_harness.adapters import correction_feedback as module  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402

API = SimpleNamespace(deliver=module.deliver, require_context=module.require_context, MemoryStore=MemoryStore, ContractError=ContractError,
                      CorrectionFeedbackRefused=module.CorrectionFeedbackRefused, REFUSALS=module.REFUSALS, SCHEMA=module.SCHEMA,
                      RESEARCH_SCHEMA=module.RESEARCH_SCHEMA, MAX_FINDINGS_CHARS=module.MAX_FINDINGS_CHARS)

if __name__ == "__main__":
    driver.finish("reference", "research.correction_feedback", common.correction_feedback(API))
