"""Reference driver: an unpatched M7 provider transport cannot reach a provider (R-P control, F3).

Scenario family `guards.unpatched_transport`. In a reference driver process (audit hook installed by
`compare/guard/sitecustomize.py`), M7's Codex `AppServer` and `ClaudeCodeRuntime` are entered with
no patch, once resolving the executable from PATH (the fail-loud fake comes first) and once with an
absolute path to a marker-writing fixture named like the provider. Each attempt must be refused
before exec: the recorded outcome is the exception type, and the markers must stay absent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

import tempfile  # noqa: E402

from codex_harness.adapters.app_server import AppServer  # noqa: E402
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime  # noqa: E402


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
    with tempfile.TemporaryDirectory(prefix="zeus-s0-transport-") as raw:
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
            "codex_app_server_from_path": attempt(lambda: enter(AppServer())),
            "codex_app_server_absolute": attempt(lambda: enter(AppServer(executable=str(work / "bin/codex")))),
            "claude_runtime_from_path": attempt(lambda: enter(ClaudeCodeRuntime(model="fixture-model"))),
            "claude_runtime_absolute": attempt(lambda: enter(ClaudeCodeRuntime(
                model="fixture-model", executable=str(work / "bin/claude")))),
            "markers_written": sorted(n for n, m in markers.items() if m.exists()),
        }
    driver.finish("reference", "guards.unpatched_transport", result)


if __name__ == "__main__":
    main()
