"""Target driver: `research.hook_lifecycle` on the target tree (S8 pilot 82: research HookLifecycle's transaction-required methods).

The facade below is what the S10 composition does (as the S5 `Service.record_incident` already does): one store unit per call, `activate`
inside a given transaction when the scenario passes one. Clocks and ids are the scripted ones; events go through coordination's EventJournal.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s8_hook_lifecycle  # noqa: E402
from codex_harness.coordination.application.events import EventJournal  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.research.application.hooks import HookLifecycle  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT = PortClock(CLOCK)
ORG = packaged_organization()


def reset():
    CLOCK.reset()
    IDS.reset()


class Facade:
    """The M7 self-transacting shapes over `HookLifecycle`: the composition opens the unit and calls the transaction-required method."""

    def __init__(self, store):
        self.store = store
        self.lifecycle = HookLifecycle(ORG, outbox=Outbox(), events=EventJournal(), clock=PORT, ids=PortIds(IDS))

    def _unit(self, method, *args):
        with self.store.transaction() as tx:
            return getattr(self.lifecycle, method)(*args, transaction=tx)

    def get_hook(self, hook_id):
        return self._unit("get_hook", hook_id)

    def propose(self, hook_id, actor, spec, revision):
        return self._unit("propose", hook_id, actor, spec, revision)

    def review(self, hook_id, actor, revision, spec_hash, passed, evidence_ref):
        return self._unit("review", hook_id, actor, revision, spec_hash, passed, evidence_ref)

    def record_canary(self, hook_id, revision, spec_hash, checks):
        return self._unit("record_canary", hook_id, revision, spec_hash, checks)

    def activate(self, hook_id, *, transaction=None):
        if transaction is not None:
            return self.lifecycle.activate(hook_id, transaction=transaction)
        return self._unit("activate", hook_id)

    def rollback(self, hook_id, reason):
        return self._unit("rollback", hook_id, reason)

    def prepare_command(self, argv, platform):
        return self._unit("prepare_command", argv, platform)

    def active_hooks(self):
        return self._unit("active_hooks")


API = SimpleNamespace(MemoryStore=MemoryStore, digest=digest, reset=reset, advance=CLOCK.advance, hooks=Facade)

if __name__ == "__main__":
    driver.finish("target", "research.hook_lifecycle", s8_hook_lifecycle.run(API))
