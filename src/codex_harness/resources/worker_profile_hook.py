"""Standalone Claude Code hook for the Zeus worker profile: a metadata receipt writer that also
counts repeated tool failures for this session (two-strike-001).

Run by Claude Code as a SessionStart, PostToolUse or PostToolUseFailure command hook. It depends on
the standard library only and never imports the harness. It reads the hook's JSON from stdin under a
byte limit, keeps four facts (session id, event name, tool name, the profile digest it was started
with) and writes them as one new file in the directory given on its command line. The prompt, the
tool's command, its output and any credential never leave this process: the fields that carry them
are not read out of the JSON at all.

On an explicit failure of a supported tool the hook also derives a normalized symptom fingerprint in
memory (tool plus error text with paths, hex ids and numbers replaced) and counts it in a SQLite
file inside the same session directory. Only hashes, counters and fixed words are stored: the error
text itself is never written to the database, the receipt or stdout. One failed tool invocation
counts once, because the deduplication key is the hash of its `tool_use_id`; a second distinct
failure with the same fingerprint emits one research-required context for that fingerprint, once per
session, and later replays do not emit another. A missing session id, tool_use_id or error text, an
interruption, an unsupported tool and oversized or malformed input are recorded as unknown and are
not counted. Busy, failed or corrupt state is reported as unavailable; counts are never reset.

The receipt is an observation that the hook ran, nothing more. It is not an approval, not a
completion signal, and a missing receipt means "not observed", never "did not happen". A fingerprint
that reached the threshold is a research candidate, never a confirmed cause, and the hook observes
only what the platform delivers to it: a rejected tool call or a reviewer's rejection is not seen.
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid

STDIN_LIMIT = 65536
SAFE = re.compile(r"[^A-Za-z0-9_.-]")
FIELD_LIMIT = 64
# Two-strike counting (two-strike-001). The threshold is the count of distinct failed tool
# invocations that share one fingerprint inside one session; it is not the confirmed-cause
# threshold of the PostgreSQL incident recurrence rule, which stays independent of this hook.
FAILURE_EVENT = "PostToolUseFailure"
TOOL_USE_EVENT = "PostToolUse"
SUPPORTED_TOOLS = ("Bash", "Edit", "Glob", "Grep", "Read", "Write")
STRIKE_THRESHOLD = 2
DATABASE_NAME = "two-strike.sqlite3"
BUSY_TIMEOUT_MS = 4000
ERROR_LIMIT = 4096
SYMPTOM_LIMIT = 512
PATH_LIKE = re.compile(r"[^\s'\"]*[\\/][^\s'\"]*")
HEX_LIKE = re.compile(r"[0-9a-f]{6,}")
NUMBER = re.compile(r"[0-9]+")
RESEARCH_CONTEXT = (
    "Two-strike rule: {count} distinct {tool} failures in this session share one normalized symptom "
    "(fingerprint {fingerprint}). Stop repeating this approach; the shared symptom is a research "
    "candidate, not a confirmed cause. Read the failure evidence and the authoritative definition, "
    "producer, consumer and tests for the affected path; search the local references and primary "
    "documentation you are authorized to use. Record the source revision or date next to the claim "
    "it supports and keep observation, hypothesis and unknown apart. Run one bounded investigation "
    "with one discriminating check, then make one coherent fix inside the allowed paths and verify "
    "it with the affected tests. If the authority or the search is unavailable, report "
    "research_required with this evidence and hand off to the lead: do not claim success, do not "
    "explore unrelated code and do not start another investigation.")


def _argument(argv, name):
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return None


def _safe(value, limit=FIELD_LIMIT):
    return SAFE.sub("_", str(value))[:limit] if isinstance(value, str) and value else None


def _hash(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _failure(body, event):
    """What this event says about a failure: `(kind, value)`, or None when it reports none.

    `("error", "")` means "a tool failed, but the error text is missing": unknown, not a strike. A
    successful result whose output merely mentions failure is never read here; only a real nonzero
    `exit_code` integer makes a PostToolUse event count, and that event carries no error text, so
    the code itself is the whole symptom and different codes stay apart.
    """
    if event == FAILURE_EVENT:
        error = body.get("error")
        return ("error", error[:ERROR_LIMIT] if isinstance(error, str) and error.strip() else "")
    if event == TOOL_USE_EVENT:
        response = body.get("tool_response")
        code = response.get("exit_code") if isinstance(response, dict) else None
        if type(code) is int and code != 0:
            return ("exit", str(code))
    return None


def _symptom(tool, kind, value):
    """A bounded, path- and number-free shape of the failure. It stays in memory; only its hash
    is stored, so two failures differing in a path, a line number or an id fingerprint alike."""
    if kind == "exit":
        return tool + "|exit status " + value
    text = PATH_LIKE.sub("<path>", " ".join(value.lower().split()))
    return tool + "|" + NUMBER.sub("<n>", HEX_LIKE.sub("<id>", text))[:SYMPTOM_LIMIT]


def _unknown(reason):
    return {"status": "unknown", "reason": reason, "fingerprint": None, "distinct_failures": None,
            "research_required": False, "context_emitted": False, "threshold": STRIKE_THRESHOLD}


def _count(directory, scope, fingerprint, tool_use):
    """Count this failed invocation once and decide whether the context is owed, atomically.

    The write is one immediate transaction, so two hook processes that fail at the same time
    commit two distinct failures and exactly one of them owns the emission. Busy, failed or
    corrupt state returns unavailable: nothing is dropped, reset or reported as success.
    """
    connection = None
    try:
        connection = sqlite3.connect(os.path.join(directory, DATABASE_NAME),
                                     timeout=BUSY_TIMEOUT_MS / 1000.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = " + str(BUSY_TIMEOUT_MS))
        connection.execute("CREATE TABLE IF NOT EXISTS failures (scope TEXT NOT NULL, "
                           "fingerprint TEXT NOT NULL, tool_use TEXT NOT NULL, "
                           "recorded_at_ns INTEGER NOT NULL, "
                           "PRIMARY KEY (scope, fingerprint, tool_use))")
        connection.execute("CREATE TABLE IF NOT EXISTS strikes (scope TEXT NOT NULL, "
                           "fingerprint TEXT NOT NULL, emitted_at_ns INTEGER NOT NULL, "
                           "PRIMARY KEY (scope, fingerprint))")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT OR IGNORE INTO failures VALUES (?, ?, ?, ?)",
                           (scope, fingerprint, tool_use, time.time_ns()))
        count = connection.execute("SELECT COUNT(*) FROM failures WHERE scope = ? AND "
                                   "fingerprint = ?", (scope, fingerprint)).fetchone()[0]
        already = connection.execute("SELECT COUNT(*) FROM strikes WHERE scope = ? AND "
                                     "fingerprint = ?", (scope, fingerprint)).fetchone()[0]
        required = count >= STRIKE_THRESHOLD
        emit = required and not already
        if emit:
            connection.execute("INSERT INTO strikes VALUES (?, ?, ?)",
                               (scope, fingerprint, time.time_ns()))
        connection.execute("COMMIT")
    except (sqlite3.Error, OSError, ValueError):
        if connection is not None:
            try:
                connection.execute("ROLLBACK")
            except (sqlite3.Error, OSError):
                pass
        return {"status": "unavailable", "reason": "state_unavailable", "fingerprint": fingerprint,
                "distinct_failures": None, "research_required": False, "context_emitted": False,
                "threshold": STRIKE_THRESHOLD}
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
    return {"status": "counted", "reason": None, "fingerprint": fingerprint,
            "distinct_failures": count, "research_required": required, "context_emitted": emit,
            "threshold": STRIKE_THRESHOLD}


def two_strike(body, directory, profile_digest, failure):
    """Observe one explicit failure. Every missing fact is unknown, never an invented strike."""
    kind, value = failure
    if body.get("is_interrupt"):
        return _unknown("interrupted")
    tool = body.get("tool_name")
    if not (isinstance(tool, str) and tool in SUPPORTED_TOOLS):
        return _unknown("unsupported_tool")
    if not value:
        return _unknown("missing_error")
    session = body.get("session_id")
    if not (isinstance(session, str) and session):
        return _unknown("missing_session")
    tool_use = body.get("tool_use_id")
    if not (isinstance(tool_use, str) and tool_use):
        return _unknown("missing_tool_use_id")
    scope = _hash(session + "\x00" + profile_digest)
    fingerprint = _hash(scope + "\x00" + _symptom(tool, kind, value))
    return _count(directory, scope, fingerprint, _hash(tool_use))


def _emit_context(event, tool, strike):
    """One research-required context for this fingerprint, written once per session."""
    context = RESEARCH_CONTEXT.format(count=strike["distinct_failures"], tool=tool,
                                      fingerprint=strike["fingerprint"][:12])
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                                        "additionalContext": context}},
                                ensure_ascii=False) + "\n")
    sys.stdout.flush()


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
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        sys.stderr.write("worker_profile_hook: receipt not written (" + type(exc).__name__ + ")\n")
        return 1
    # Only an event that states a tool failed is counted; a success carries no two_strike fact.
    failure = None if truncated else _failure(body, event)
    if failure is not None:
        record["two_strike"] = two_strike(body, directory, profile_digest, failure)
        if record["two_strike"]["context_emitted"]:
            _emit_context(event, tool, record["two_strike"])
    name = f"{event}-{tool or 'none'}-{record['recorded_at_ns']}-{os.getpid()}-{uuid.uuid4().hex[:8]}.json"
    try:
        descriptor = os.open(os.path.join(directory, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
    except OSError as exc:
        sys.stderr.write("worker_profile_hook: receipt not written (" + type(exc).__name__ + ")\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
