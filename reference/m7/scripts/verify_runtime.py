"""Live App Server file-task, native-hook and fresh-thread canary (uses account quota)."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from codex_harness.adapters.app_server import AppServer


def main():
    with tempfile.TemporaryDirectory(prefix="harness-runtime-") as directory:
        root = Path(directory)
        hook = root / "observe.py"
        hook.write_text("import json, pathlib, sys\n"
                        "event=json.load(sys.stdin)\n"
                        "pathlib.Path(event['cwd'],'hook-observed.txt').write_text(event['hook_event_name'])\n"
                        "print('{}')\n", encoding="utf-8")
        command = ([sys.executable, str(hook)])
        command = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
        hooks = {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}]}
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {"value": {"type": "string"}}, "required": ["value"]}
        with AppServer(hooks=hooks) as runtime:
            result = runtime.run("Use the shell to write HARNESS_RUNTIME_OK to output.txt. Return value done.",
                                 directory, schema, 120)
        with AppServer() as runtime:
            fresh = runtime.run("Read output.txt. Return its contents, stripped of whitespace, in value.",
                                directory, schema, 120, read_only=True)
        with AppServer(context_window=20000) as runtime:
            threshold = runtime.run("Inspect output.txt with a shell tool, then inspect it again in a separate "
                                    "tool call, then return value checked.", directory, schema, 120)
        checks = {"file_task": (root / "output.txt").read_text("utf-8").strip() == "HARNESS_RUNTIME_OK",
                  "native_hook": (root / "hook-observed.txt").exists(),
                  "fresh_thread": fresh["thread_id"] != result["thread_id"],
                  "handoff_read": fresh["answer"]["value"] == "HARNESS_RUNTIME_OK",
                  "usage_observed": result["usage"] is not None,
                  "controlled_window_rotation": threshold["rotate"]}
        print(json.dumps({"checks": checks, "hook_events": [e for e in result["events"]
                                                             if "hook" in e.get("method", "").lower()]}))
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
