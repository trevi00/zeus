"""One reproducible validation entry point; --integration opts into local Docker fixtures."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = dict(os.environ)
if "--integration" in sys.argv:
    env["HARNESS_INTEGRATION"] = "1"
for command in (["uv", "run", "ruff", "check", "."], ["uv", "run", "pytest", "-q"]):
    completed = subprocess.run(command, cwd=root, env=env)
    if completed.returncode:
        raise SystemExit(completed.returncode)
