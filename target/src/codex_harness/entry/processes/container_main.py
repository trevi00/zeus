"""Entry of the role container: the codex home setup, then the operator CLI (M7 `container_main`).

Layer: entry
Owns: the `--agent` home, auth copy and config.toml setup (M7's statements, verbatim), then `entry.cli.main`
Entry points: main
Contracts: none

Moved from M7 container_main.py:9-25 (SOURCE e38aa722); the one change is `codex_harness.cli` -> `codex_harness.entry.cli`.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main():
    if "--agent" in sys.argv:
        agent = sys.argv[sys.argv.index("--agent") + 1]
        home = Path("/runtime/agents") / agent.replace(":", "-")
        home.mkdir(parents=True, exist_ok=True)
        os.environ["CODEX_HOME"] = str(home)
        source, target = Path("/run/secrets/codex-auth"), home / "auth.json"
        if source.exists() and (not target.exists() or source.stat().st_mtime > target.stat().st_mtime):
            shutil.copyfile(source, target)
            target.chmod(0o600)
        config = home / "config.toml"
        if not config.exists():
            config.write_text('approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
                              'model = "gpt-6-astra"\nmodel_reasoning_effort = "medium"\n', encoding="utf-8")
    from codex_harness.entry.cli import main as cli_main

    cli_main()
