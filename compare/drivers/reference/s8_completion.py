"""Reference driver: `evidence.completion` (M7 `application.completion`: `CompletionAuthority`).

The API holds plain M7 objects:
- `adapters.store.MemoryStore`; `application.completion`: `CompletionAuthority`, `BUCKET`, `REJECTIONS`, `RECORD_ONLY`, `STATES`, `EVALUATION_KIND`;
- `domain.model`: `ContractError`, `digest` (the notice id is a digest of it).
The artifacts store and the organization are the scenario's LABELLED fakes (M7's are `FileArtifacts` and `bootstrap.organization()`).
`record` reads the real clock only when no `now` is passed, through M7's patched `datetime`: the scenario never depends on it. The
clock for the notices' `at` is the harness's (`determinism.install`)."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_completion  # noqa: E402

from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import completion as application  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
IDS = determinism.FakeIds()
determinism.install(CLOCK, IDS)

API = SimpleNamespace(
    MemoryStore=MemoryStore, CompletionAuthority=application.CompletionAuthority, BUCKET=application.BUCKET,
    REJECTIONS=application.REJECTIONS, RECORD_ONLY=application.RECORD_ONLY, STATES=application.STATES,
    EVALUATION_KIND=application.EVALUATION_KIND, ContractError=ContractError, digest=digest)

if __name__ == "__main__":
    driver.finish("reference", "evidence.completion", s8_completion.run(API))
