"""Standalone Claude Code hook for the Zeus worker profile: a metadata receipt writer.

Run by Claude Code as a SessionStart or PostToolUse command hook. It depends on the standard
library only and never imports the harness. It reads the hook's JSON from stdin under a byte
limit, keeps four facts (session id, event name, tool name, the profile digest it was started
with) and writes them as one new file in the directory given on its command line. The prompt,
the tool's command, its output and any credential never leave this process: the fields that
carry them are not read out of the JSON at all.

The receipt is an observation that the hook ran, nothing more. It is not an approval, not a
completion signal, and a missing receipt means "not observed", never "did not happen".
"""
import json
import os
import re
import sys
import time
import uuid

STDIN_LIMIT = 65536
SAFE = re.compile(r"[^A-Za-z0-9_.-]")
FIELD_LIMIT = 64


def _argument(argv, name):
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return None


def _safe(value, limit=FIELD_LIMIT):
    return SAFE.sub("_", str(value))[:limit] if isinstance(value, str) and value else None


def main(argv):
    directory = _argument(argv, "--directory")
    profile_digest = _argument(argv, "--profile-digest")
    if not directory or not profile_digest:
        sys.stderr.write("worker_profile_hook: --directory and --profile-digest are required\n")
        return 1
    data = sys.stdin.buffer.read(STDIN_LIMIT + 1)
    truncated = len(data) > STDIN_LIMIT
    body = {}
    if not truncated:
        try:
            parsed = json.loads(data.decode("utf-8", "replace") or "{}")
            body = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            body = {}
    event = _safe(body.get("hook_event_name")) or "unknown"
    tool = _safe(body.get("tool_name"))
    record = {
        "hook": "worker_profile_hook",
        "session_id": _safe(body.get("session_id")),
        "hook_event_name": event,
        "tool_name": tool,
        "profile_digest": _safe(profile_digest, 128),
        "stdin_bytes": min(len(data), STDIN_LIMIT),
        "stdin_truncated": truncated,
        "recorded_at_ns": time.time_ns(),
        "pid": os.getpid(),
        "note": "metadata only; no prompt, command, output or credential is recorded",
    }
    name = f"{event}-{tool or 'none'}-{record['recorded_at_ns']}-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
    try:
        os.makedirs(directory, exist_ok=True)
        descriptor = os.open(os.path.join(directory, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
    except OSError as exc:
        sys.stderr.write("worker_profile_hook: receipt not written (" + type(exc).__name__ + ")\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
