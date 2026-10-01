"""Target driver: `research.capture` on the target tree (S8 pilot 74: `research.adapters.research_program`, V11/V13).

The API mirrors the reference driver's names over the target homes. `GitCapture` gets its two injected host_os ports (R-q2): the
composition wiring `host_os.adapters.process_groups.run_process` and `host_os.adapters.git_source.GitSource`, each reached through a
thin forwarder. The capture reads no clock and no id source (the fixture repositories pin their own `GIT_*` identity and dates), so
the driver installs none. `patch(name, value)` is the labelled fault seam: M7 replaced a module global of the adapter, and here the
forwarder reads the replacement from `PATCHED` at call time, so every labelled fault (the shifted read-back reader, the simulated
Windows pipe) still reaches the exact call site it reached in M7 and no case is weakened or skipped."""

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_capture  # noqa: E402
from codex_harness.composition import research_program_adapters  # noqa: E402
from codex_harness.host_os.adapters import git_source, process_groups  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.research.adapters import research_program as adapter  # noqa: E402
from codex_harness.research.domain.research_program import CAPTURE_ROOT  # noqa: E402

PATCHED = {}


def run_process(*args, **kwargs):
    return PATCHED.get("run_process", process_groups.run_process)(*args, **kwargs)


def GitSource(repository):  # noqa: N802 - the name the common scenario patches
    return PATCHED.get("GitSource", git_source.GitSource)(repository)


@contextmanager
def patch(name, value):
    missing = object()
    saved = PATCHED.get(name, missing)
    PATCHED[name] = value
    try:
        yield
    finally:
        if saved is missing:
            del PATCHED[name]
        else:
            PATCHED[name] = saved


class GitCapture(adapter.GitCapture):
    """The moved class with its two composition ports wired (a subclass: the scenario builds it from the repository alone)."""

    def __init__(self, repository, *args, **kwargs):
        super().__init__(repository, *args, run_process=run_process, git_source=GitSource, **kwargs)


# the composition's own wiring is the production one; the forwarders above only add the labelled-fault seam over the same callables
assert research_program_adapters.git_capture(".").run_process is process_groups.run_process

API = SimpleNamespace(
    GitCapture=GitCapture, CaptureError=adapter.CaptureError, CAPTURE_AUTHOR=adapter.CAPTURE_AUTHOR,
    MAX_SNAPSHOT_BYTES=adapter.MAX_SNAPSHOT_BYTES, run_process=process_groups.run_process, GitSource=git_source.GitSource,
    CAPTURE_ROOT=CAPTURE_ROOT, ContractError=ContractError, patch=patch)

if __name__ == "__main__":
    driver.finish("target", "research.capture", s8_capture.run(API))
