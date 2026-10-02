"""Target driver: `research.source_execution` on the target tree (S8 pilot 88: `research.application.source_execution`).

The API mirrors the reference driver's names over the target homes. M7's `Workflow` is the S5 composition's `WorkflowAndMessages` (the target
`Workflow` plus the MessageHandler, as `SourceExecutions` only reads `store` and `_owned` from it), over the packaged organization; `POLICY` is the
kernel's. The scenario reads the kernel's default clock and id source where M7 read `utcnow` and `envelope`; the harness's scripted clock and ids (the
composition's) reach them through the kernel `Clock` port and `kernel.message.SYSTEM_IDS`. The module's own `uuid4` (the runner's owner token) is the
harness id source and its `datetime.now(timezone.utc)` (the expiry of a running row) reads the scripted clock, as the reference run's patched
standard library did (the target's standard library is never patched). The import-time execution domain is pinned as the reference run pinned it."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s5_coordination_composition as composition  # noqa: E402
import s8_source_execution  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.research.application import source_execution as application  # noqa: E402
from codex_harness.research.domain import research as domain  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

composition.CLOCK.start = composition.CLOCK.current = datetime(2026, 9, 22, tzinfo=timezone.utc)
ids.SYSTEM_CLOCK = composition.PORT
message.SYSTEM_IDS = composition.IDPORT
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000a0d1"  # the reference run's pinned clock-domain identity
application.uuid4 = composition.IDS.uuid4   # the runner's owner token: the harness id source, as the reference run installed it
application.datetime = SimpleNamespace(now=composition.CLOCK.now, fromisoformat=datetime.fromisoformat)   # `datetime.now(timezone.utc)` reads the scripted clock

API = SimpleNamespace(
    MemoryStore=MemoryStore, Workflow=lambda store, org: composition.WorkflowAndMessages(store), organization=lambda: composition.ORG,
    SourceExecutions=application.SourceExecutions, SourceIdentity=domain.SourceIdentity, ExecutionReceipt=domain.ExecutionReceipt,
    ContractError=ContractError, digest=digest, envelope=envelope, POLICY=POLICY, now=lambda: composition.CLOCK.now(timezone.utc),
    advance=composition.CLOCK.advance)

if __name__ == "__main__":
    driver.finish("target", "research.source_execution", s8_source_execution.run(API))
