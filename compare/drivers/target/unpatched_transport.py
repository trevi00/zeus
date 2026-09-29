"""Target driver: an unpatched target provider transport cannot reach a provider (R-P control, F3).

Scenario family `guards.unpatched_transport` on the target tree. The target's Codex `AppServer` and
`ClaudeCodeRuntime` are entered with the REAL host facilities composition would inject (the host_os
chokepoint processes and run_process, the host_os ProcessTree, the context worker-profile adapter), once
resolving the executable from PATH (the fail-loud fake comes first) and once with an absolute path to a
marker-writing fixture named like the provider. Each attempt must be refused before exec by the guard.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("target")

import tempfile  # noqa: E402

from codex_harness.context.adapters import worker_profile  # noqa: E402
from codex_harness.execution.adapters.providers.claude_cli import (  # noqa: E402
    ClaudeCodeRuntime,
    ClaudeHost,
)
from codex_harness.execution.adapters.providers.codex_app_server import AppServer  # noqa: E402
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.host_os.adapters.process_tree import ProcessTree, TreeOwnershipLeak  # noqa: E402

PROCESSES = process_groups.ChokepointProcesses()
HOST = ClaudeHost(runner=process_groups.run_process, trees=ProcessTree, tree_leak=TreeOwnershipLeak,
                  worker_profiles=worker_profile, redact=lambda text: (text, 0))


def attempt(action) -> str:
    try:
        action()
    except BaseException as exc:  # noqa: BLE001 - the outcome type is the recorded result
        chain, current = [], exc
        while current is not None and len(chain) < 4:
            chain.append(type(current).__name__)
            current = current.__cause__ or current.__context__
        return " <- ".join(chain)
    return "NO REFUSAL"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zeus-s4-transport-") as raw:
        work = Path(raw)
        markers = {}
        for name in ("codex", "claude"):
            marker = work / (name + ".ran")
            path = work / "bin" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
            path.chmod(0o755)
            markers[name] = marker

        def enter(runtime):
            with runtime:
                pass

        result = {
            "codex_app_server_from_path": attempt(lambda: enter(AppServer(processes=PROCESSES))),
            "codex_app_server_absolute": attempt(lambda: enter(AppServer(executable=str(work / "bin/codex"),
                                                                         processes=PROCESSES))),
            "claude_runtime_from_path": attempt(lambda: enter(ClaudeCodeRuntime(model="fixture-model", host=HOST))),
            "claude_runtime_absolute": attempt(lambda: enter(ClaudeCodeRuntime(
                model="fixture-model", executable=str(work / "bin/claude"), host=HOST))),
            "markers_written": sorted(n for n, m in markers.items() if m.exists()),
        }
    driver.finish("target", "guards.unpatched_transport", result)


if __name__ == "__main__":
    main()
