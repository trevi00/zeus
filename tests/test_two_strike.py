"""two-strike-001: the packaged worker hook counts repeated tool failures for one session.

Every case here starts the real packaged hook as a subprocess, the way Claude Code starts a command
hook, and reads back what it wrote: its stdout, its receipt files and its SQLite state. That is
evidence about this hook on this host. It says nothing about a model: a delivered research context
is a prompt to research, never proof that any research happened.
"""
import json
import subprocess
import sys
from pathlib import Path

from codex_harness.adapters import worker_profile as module
from codex_harness.adapters.worker_profile import (
    FAILURE_TOOL_MATCHER,
    delivery_receipt,
    hook_command,
    hook_receipts,
    hook_settings,
    load_profile,
)

HOOK = Path(module.__file__).resolve().parent.parent / "resources" / "worker_profile_hook.py"
DATABASE = "two-strike.sqlite3"
DIGEST = "d" * 64
SESSION = "00000000-0000-4000-8000-0000000000aa"
CANARY = "CANARY-2f8a4c6e0b1d3f5a7c9e"


def payload(**fields):
    body = {"session_id": SESSION, "hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
            "cwd": "/candidate", **fields}
    return {key: value for key, value in body.items() if value is not None}


def argv(directory):
    return [sys.executable, str(HOOK), "--directory", str(directory), "--profile-digest", DIGEST]


def deliver(directory, **fields):
    """One hook invocation, as the platform would run it: one process, one event on stdin."""
    completed = subprocess.run(argv(directory), input=json.dumps(payload(**fields)).encode("utf-8"),
                               capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert b"Traceback" not in completed.stderr
    return completed


def failure(directory, tool_use_id, error, **fields):
    return deliver(directory, tool_use_id=tool_use_id, error=error, **fields)


def context(completed):
    return json.loads(completed.stdout.decode("utf-8"))["hookSpecificOutput"]


def receipts(directory):
    bodies = [json.loads(path.read_text("utf-8")) for path in directory.glob("*.json")]
    return sorted(bodies, key=lambda body: body["recorded_at_ns"])


def strikes(directory):
    """The two_strike fact of each receipt in the order the hook wrote them; None when absent."""
    return [body.get("two_strike") for body in receipts(directory)]


# ---- counting, similarity and the single research context ---------------------------------------

def test_the_second_similar_failure_asks_for_research_once_and_later_ones_do_not(tmp_path):
    directory = tmp_path / "evidence 증거" / SESSION
    first = failure(directory, "toolu_1", "FileNotFoundError: /workspace/src/a.py, line 12")
    assert first.stdout == b"", "one failure is not a strike"
    second = failure(directory, "toolu_2", "FileNotFoundError: /workspace/tests/b.py, line 4098")
    emitted = context(second)
    assert emitted["hookEventName"] == "PostToolUseFailure"
    assert "stop repeating this approach" in emitted["additionalContext"].lower()
    assert "research candidate, not a confirmed cause" in emitted["additionalContext"]
    assert "research_required" in emitted["additionalContext"] and "hand off" in emitted["additionalContext"]
    third = failure(directory, "toolu_3", "FileNotFoundError: /workspace/src/c.py, line 7")
    assert third.stdout == b"", "the context is emitted once per fingerprint, not on every repeat"

    facts = strikes(directory)
    assert [fact["distinct_failures"] for fact in facts] == [1, 2, 3]
    assert [fact["research_required"] for fact in facts] == [False, True, True]
    assert [fact["context_emitted"] for fact in facts] == [False, True, False]
    assert len({fact["fingerprint"] for fact in facts}) == 1, "paths and numbers do not separate them"
    assert {fact["status"] for fact in facts} == {"counted"} and facts[0]["threshold"] == 2
    # Three separate hook processes shared one state file, which lives in this session directory.
    assert (directory / DATABASE).is_file()
    assert sorted(path.name for path in directory.iterdir() if path.suffix != ".json") == [DATABASE]


def test_materially_different_failures_and_tools_are_counted_apart(tmp_path):
    directory = tmp_path / SESSION
    runs = [failure(directory, "toolu_1", "FileNotFoundError: /workspace/a.py, line 3"),
            failure(directory, "toolu_2", "PermissionError: cannot write /workspace/b.py"),
            failure(directory, "toolu_3", "FileNotFoundError: /workspace/c.py, line 5",
                    tool_name="Read")]
    assert [run.stdout for run in runs] == [b"", b"", b""], "no threshold is reached"
    facts = strikes(directory)
    assert [fact["distinct_failures"] for fact in facts] == [1, 1, 1]
    assert len({fact["fingerprint"] for fact in facts}) == 3


def test_a_redelivered_failure_counts_once(tmp_path):
    directory = tmp_path / SESSION
    for _ in range(2):  # the same tool_use_id delivered twice: one failed invocation, one count
        completed = failure(directory, "toolu_same", "TimeoutError after 30s")
        assert completed.stdout == b""
    facts = strikes(directory)
    assert [fact["distinct_failures"] for fact in facts] == [1, 1]
    assert [fact["context_emitted"] for fact in facts] == [False, False]


def test_a_restarted_hook_process_continues_the_existing_count(tmp_path):
    directory = tmp_path / SESSION
    failure(directory, "toolu_1", "ImportError while loading /workspace/tests/a.py")
    state = (directory / DATABASE).read_bytes()
    assert state.startswith(b"SQLite format 3")
    second = failure(directory, "toolu_2", "ImportError while loading /workspace/tests/b.py")
    assert context(second)["hookEventName"] == "PostToolUseFailure"
    assert strikes(directory)[-1]["distinct_failures"] == 2, "state survived between processes"


# ---- what must never become a strike -------------------------------------------------------------

def test_success_interruption_and_missing_facts_are_unknown_never_a_strike(tmp_path):
    directory = tmp_path / SESSION
    mentions_failure = deliver(directory, hook_event_name="PostToolUse", tool_use_id="toolu_ok",
                               tool_response={"exit_code": 0, "stdout": "2 checks failed earlier"})
    assert mentions_failure.stdout == b""
    assert strikes(directory) == [None], "a successful result carries no two_strike fact at all"

    runs = [deliver(directory, tool_use_id="toolu_i", error="boom", is_interrupt=True),
            deliver(directory, tool_use_id="toolu_e"),
            deliver(directory, error="boom"),
            deliver(directory, tool_use_id="toolu_t", error="boom", tool_name="Task"),
            deliver(directory, tool_use_id="toolu_s", error="boom", session_id=None)]
    assert [run.stdout for run in runs] == [b""] * 5
    facts = [fact for fact in strikes(directory) if fact]
    assert {fact["status"] for fact in facts} == {"unknown"} and len(facts) == 5
    assert {fact["reason"] for fact in facts} == {"interrupted", "missing_error",
                                                  "missing_tool_use_id", "unsupported_tool",
                                                  "missing_session"}
    assert all(fact["distinct_failures"] is None and not fact["research_required"] for fact in facts)
    assert not (directory / DATABASE).exists(), "unknown events write no state"


def test_only_a_real_nonzero_exit_code_makes_a_post_tool_use_event_count(tmp_path):
    directory = tmp_path / SESSION
    first = deliver(directory, hook_event_name="PostToolUse", tool_use_id="toolu_1",
                    tool_response={"exit_code": 2, "stderr": "pytest failed in /workspace/a.py"})
    assert first.stdout == b"" and strikes(directory)[-1]["distinct_failures"] == 1
    second = deliver(directory, hook_event_name="PostToolUse", tool_use_id="toolu_2",
                     tool_response={"exit_code": 2, "stderr": "pytest failed in /workspace/b.py"})
    assert context(second)["hookEventName"] == "PostToolUse"
    boolean = deliver(directory, hook_event_name="PostToolUse", tool_use_id="toolu_3",
                      tool_response={"exit_code": True})
    assert boolean.stdout == b"" and strikes(directory)[-1] is None, "a boolean is not an exit code"
    other = deliver(directory, hook_event_name="PostToolUse", tool_use_id="toolu_4",
                    tool_response={"exit_code": 127, "stderr": "command not found"})
    assert other.stdout == b"" and strikes(directory)[-1]["distinct_failures"] == 1, "another code, another symptom"
    oversized = subprocess.run(argv(directory), capture_output=True, timeout=60,
                               input=json.dumps(payload(tool_use_id="toolu_5", error="boom",
                                                        pad="y" * 70000)).encode("utf-8"))
    assert oversized.returncode == 0 and oversized.stdout == b""
    assert strikes(directory)[-1] is None, "input past the byte limit is not read, so it cannot count"


# ---- concurrency, unavailable state and privacy ---------------------------------------------------

def test_two_concurrent_hook_processes_commit_two_failures_and_one_context(tmp_path):
    directory = tmp_path / SESSION
    directory.mkdir(parents=True)
    bodies = [payload(tool_use_id="toolu_a", error="ConnectionError on /tmp/a.sock after 30s"),
              payload(tool_use_id="toolu_b", error="ConnectionError on /tmp/b.sock after 45s")]
    processes = [subprocess.Popen(argv(directory), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) for _ in bodies]
    for process, body in zip(processes, bodies):  # both are already running when either is fed
        process.stdin.write(json.dumps(body).encode("utf-8"))
        process.stdin.close()
    outputs = []
    for process in processes:
        outputs.append(process.stdout.read())
        process.stderr.read()
        assert process.wait(timeout=60) == 0
    facts = strikes(directory)
    assert sorted(fact["distinct_failures"] for fact in facts) == [1, 2], "both commits survived"
    assert len({fact["fingerprint"] for fact in facts}) == 1
    assert sum(bool(output.strip()) for output in outputs) == 1, "exactly one process owns the context"
    assert hook_receipts(directory, DIGEST)["two_strike"]["contexts_emitted"] == 1


def test_unusable_state_is_reported_unavailable_and_is_never_reset(tmp_path):
    directory = tmp_path / SESSION
    failure(directory, "toolu_1", "ValueError while parsing /workspace/a.json")
    corrupt = b"this is not a database" + bytes(64)
    (directory / DATABASE).write_bytes(corrupt)
    completed = failure(directory, "toolu_2", "ValueError while parsing /workspace/b.json")
    assert completed.stdout == b"", "a state the hook cannot read never claims a strike"
    fact = strikes(directory)[-1]
    assert fact["status"] == "unavailable" and fact["reason"] == "state_unavailable"
    assert fact["distinct_failures"] is None and fact["research_required"] is False
    assert (directory / DATABASE).read_bytes() == corrupt, "the hook does not reset what it cannot read"
    projection = hook_receipts(directory, DIGEST)["two_strike"]
    assert projection["unavailable_observations"] == 1 and projection["research_required"] == 0


def test_no_command_output_or_credential_reaches_stdout_receipts_or_state(tmp_path):
    directory = tmp_path / SESSION
    completed = None
    for index in range(2):
        completed = failure(directory, "toolu_" + str(index),
                            "AuthError: token=" + CANARY + " rejected at /workspace/x.py:" + str(index),
                            tool_input={"command": "export TOKEN=" + CANARY},
                            tool_response={"stdout": "output with " + CANARY},
                            prompt="secret prompt " + CANARY)
    emitted = context(completed)
    assert CANARY not in json.dumps(emitted) and "token=" not in emitted["additionalContext"]
    for body in receipts(directory):
        text = json.dumps(body)
        assert CANARY not in text and "TOKEN" not in text and "AuthError" not in text
    assert CANARY.encode() not in (directory / DATABASE).read_bytes()
    assert len(strikes(directory)[-1]["fingerprint"]) == 64, "only the hash of the symptom is kept"


# ---- what the packaged profile ships and reports --------------------------------------------------

def test_the_packaged_profile_ships_this_hook_with_its_failure_event(tmp_path):
    profile = load_profile("worker-v1")
    assert profile["hook_path"] == HOOK, "the tests above exercised the packaged hook"
    settings = hook_settings(hook_command(sys.executable, HOOK, tmp_path, DIGEST))
    assert settings["hooks"]["PostToolUseFailure"][0]["matcher"] == FAILURE_TOOL_MATCHER
    assert set(settings["hooks"]) == {"SessionStart", "PostToolUse", "PostToolUseFailure"}
    assert delivery_receipt(profile, tmp_path)["hooks"] == [
        "SessionStart", "PostToolUse(Bash)", "PostToolUseFailure(Bash|Edit|Glob|Grep|Read|Write)"]
    document = " ".join(profile["document"].split())  # the rule must survive rewrapping
    assert "## Repeated failure and investigation" in document
    assert "stop retrying it; a shared symptom is a research candidate, not a cause" in document
    assert "research_required evidence-and-gap report: not success, not promoted knowledge" in document
    assert "covers repeated reviewer rejection" in document
    assert "hooks observe none, and a hook context prompts research but is not research" in document


def test_the_receipt_projection_reports_counts_fingerprints_and_unknowns_only(tmp_path):
    directory = tmp_path / SESSION
    failure(directory, "toolu_1", "AssertionError in /workspace/a.py:10")
    failure(directory, "toolu_2", "AssertionError in /workspace/b.py:20")
    deliver(directory, tool_use_id="toolu_3")
    facts = hook_receipts(directory, DIGEST)
    assert facts["events"]["PostToolUseFailure"] == 3
    strike = facts["two_strike"]
    assert strike["observed"] and strike["failure_observations"] == 3
    assert strike["counted_failures"] == 2 and strike["distinct_fingerprints"] == 1
    assert strike["research_required"] == 1 and strike["contexts_emitted"] == 1
    assert [len(value) for value in strike["research_required_fingerprints"]] == [64]
    assert strike["unknown_observations"] == 1 and strike["unknown_reasons"] == ["missing_error"]
    assert strike["unavailable_observations"] == 0 and strike["threshold"] == 2
    assert strike["authority"].startswith("none"), "a repeated symptom is not a confirmed cause"
    assert hook_receipts(directory, "q" * 64)["two_strike"]["observed"] is False
