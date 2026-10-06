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
    from codex_harness.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
