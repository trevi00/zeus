"""Target driver: `research.correction_feedback` on the target tree (S8 pilot 93: `research.adapters.correction_feedback` (V18 R-cf1: `redact` is an
injected keyword-only rule)).

`deliver` injects observation's `redact_text` where the reference module imports M7's own. The store is the target `MemoryStore`; `ContractError` is
the target kernel's (the class the moved module catches)."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_correction_feedback as common  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.observation.domain.observation import redact_text  # noqa: E402
from codex_harness.research.adapters import correction_feedback as module  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402


def deliver(store, artifacts, binding):
    return module.deliver(store, artifacts, binding, redact=redact_text)


API = SimpleNamespace(deliver=deliver, require_context=module.require_context, MemoryStore=MemoryStore, ContractError=ContractError,
                      CorrectionFeedbackRefused=module.CorrectionFeedbackRefused, REFUSALS=module.REFUSALS, SCHEMA=module.SCHEMA,
                      RESEARCH_SCHEMA=module.RESEARCH_SCHEMA, MAX_FINDINGS_CHARS=module.MAX_FINDINGS_CHARS)

if __name__ == "__main__":
    driver.finish("target", "research.correction_feedback", common.correction_feedback(API))
