"""Target driver: `hooks.candidate_canary` on the target tree (execution HookCandidates + HostHooks, research
hook_apply). The lifecycle, Git show, the validator, the runner, the channel environment and the interpreter are
injected as composition will (the same fakes the reference driver hands M7's NativeHooks).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s4_hooks  # noqa: E402
from codex_harness.execution.adapters.providers.native_hooks import (  # noqa: E402
    HookCandidates,
    HostHooks,
)
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.research.domain.recurrence import hook_apply  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402


def native_hooks(service, git, artifacts):
    show = lambda spec, strip=True: git._git("show", spec, strip=strip)  # noqa: E731
    host = HostHooks(service, show, artifacts, sys.executable)
    return HookCandidates(service, service.store, show, host, validate=hook_apply, runner=process_groups.run_process,
                          channel_environment=process_groups.python_channel_environment, interpreter=sys.executable)


API = SimpleNamespace(MemoryStore=MemoryStore, native_hooks=native_hooks, hook_apply=hook_apply)

if __name__ == "__main__":
    driver.finish("target", "hooks.candidate_canary", s4_hooks.run(API))
