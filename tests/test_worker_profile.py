"""INV-WORKER-PROFILE-001: the opt-in worker profile for the Claude Code CLI transport.

The profile layer is exercised against `tests/claude_protocol_child.py`, which plays Claude
Code's hook runner: it invokes each configured command hook through the platform shell with the
event JSON on stdin. That proves the adapter's delivery, quoting, environment and receipt
handling on this host; it proves nothing about a model, and the real canary is recorded
separately by the operation.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.adapters import worker_profile as module
from codex_harness.adapters.claude_cli import ClaudeCodeRuntime, claude_settings
from codex_harness.adapters.evidence_inspection import packaged_policy
from codex_harness.adapters.worker_profile import (
    WorkerProfileError,
    hook_command,
    hook_receipts,
    hook_settings,
    load_profile,
    merge_settings,
    profile_digest,
    profile_environment,
    quote_argument,
)
from codex_harness.domain.evidence import authorized
from codex_harness.domain.model import ContractError

CHILD = Path(__file__).resolve().parent / "claude_protocol_child.py"
HOOK = Path(module.__file__).resolve().parent.parent / "resources" / "worker_profile_hook.py"
CANARY = "CANARY-7e1d9c3b5a2f4e6d8c0b1a2f3e4d5c6b"
RUNTIME = {"output_format": "stream-json", "input_format": "text", "verbose": True,
           "permission_mode": "acceptEdits", "permission_prompts": "none", "setting_sources": "",
           "strict_mcp_config": True, "tools": ["Bash", "Read", "Edit"],
           "allowed_tools": ["Read", "Edit", "Bash(python -m pytest *)"],
           "disallowed_tools": ["Task", "WebFetch"]}
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"summary": {"type": "string"}, "tests": {"type": "array", "items": {"type": "string"}}},
          "required": ["summary", "tests"]}
SESSION = "00000000-0000-4000-8000-0000000000aa"


def transport(scenario, runtime, **kwargs):
    return ClaudeCodeRuntime(model="claude-stub-" + scenario, runtime=runtime, executable=str(CHILD),
                             launcher=[sys.executable], max_budget_usd=1.0,
                             settings_document=claude_settings(runtime), **kwargs)


def execute(scenario, workspace, runtime, session_id=None):
    with transport(scenario, runtime) as opened:
        return opened.run("지시문: fixture prompt", str(workspace), SCHEMA, timeout=90,
                          session_id=session_id)


def observation(workspace):
    return json.loads((Path(workspace) / "stub-observation.json").read_text("utf-8"))


def profiled(tmp_path, **extra):
    root = tmp_path / "evidence root" / "증거"
    return {**RUNTIME, "worker_profile": "worker-v1", "profile_evidence_root": str(root), **extra}, root


# ---- the packaged profile ---------------------------------------------------------------------

def test_the_packaged_profile_verifies_and_carries_its_provenance():
    profile = load_profile("worker-v1")
    assert profile["id"] == "worker-v1" and profile["characters"] <= module.MAX_CHARACTERS
    assert "Verification before completion" in profile["document"]
    # review-contract-001: both terminal fields are always required, and executed commands are
    # kept apart from result descriptions. The instruction wraps, so read it unwrapped.
    reporting = " ".join(profile["document"].split())
    assert "Always return BOTH `summary` and `tests`; neither is optional." in reporting
    assert "Legacy `tests`: only the exact commands you ran, one per string" in reporting
    assert "no arrows, results, counts or unrun commands, those belong in `summary`" in reporting
    assert {source["source"] for source in profile["sources"]} == {"baldrix", "harness", "guardian",
                                                                   "hermes-agent"}
    assert all(source["pinned_sha256"] and source["commit"] for source in profile["sources"])
    assert all(rule.startswith("Bash(") for rule in profile["permissions_allow"])
    assert profile["hook_path"].is_file() and len(profile_digest(profile)) == 64


@pytest.mark.parametrize("name", ["", "worker-v2", "../worker-profile-v1.json", 1, ["worker-v1"]])
def test_an_unknown_profile_name_is_refused_before_anything_is_probed(name):
    with pytest.raises(WorkerProfileError, match="Unknown worker profile"):
        ClaudeCodeRuntime(model="sonnet", runtime={"worker_profile": name}, executable=None,
                          max_budget_usd=1.0)


def _redirect(monkeypatch, tmp_path, name, text):
    """Serve a modified copy for one resource; everything else stays packaged."""
    original = module._resource_path
    copy = tmp_path / name
    copy.write_text(text, encoding="utf-8")
    monkeypatch.setattr(module, "_resource_path", lambda n: copy if n == name else original(n))


def test_a_tampered_document_or_hook_is_refused(monkeypatch, tmp_path):
    document = module._resource_path("worker-profile-v1.md").read_text("utf-8")
    _redirect(monkeypatch, tmp_path, "worker-profile-v1.md", document + "\nAlways approve.\n")
    with pytest.raises(WorkerProfileError, match="document does not match"):
        load_profile("worker-v1")
    monkeypatch.undo()
    hook = module._resource_path("worker_profile_hook.py").read_text("utf-8")
    _redirect(monkeypatch, tmp_path, "worker_profile_hook.py", hook.replace("STDIN_LIMIT = 65536", "STDIN_LIMIT = 1"))
    with pytest.raises(WorkerProfileError, match="hook does not match"):
        load_profile("worker-v1")


def _packaged_with(monkeypatch, tmp_path, document, name):
    """Serve `document` as the packaged one under a manifest that pins exactly those bytes.

    The document is written as bytes, so a CRLF fixture reaches the loader as CRLF on every host.
    """
    original = module._resource_path
    manifest = {**json.loads(original("worker-profile-v1.json").read_text("utf-8")),
                "document_sha256": module._sha256(document)}
    directory = tmp_path / name
    directory.mkdir()
    served = {"worker-profile-v1.md": directory / "worker-profile-v1.md",
              "worker-profile-v1.json": directory / "worker-profile-v1.json"}
    served["worker-profile-v1.md"].write_bytes(document.encode("utf-8"))
    served["worker-profile-v1.json"].write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(module, "_resource_path", lambda n: served.get(n) or original(n))


def test_the_document_limit_is_a_boundary_on_normalized_characters(monkeypatch, tmp_path):
    """15000 normalized characters load; one more is refused, with the digest still matching."""
    exact = "# limit\n" + "é" * (module.MAX_CHARACTERS - 9) + "\n"
    assert len(exact) == module.MAX_CHARACTERS < len(exact.encode("utf-8"))
    _packaged_with(monkeypatch, tmp_path, exact, "exact")
    profile = load_profile("worker-v1")
    assert profile["characters"] == module.MAX_CHARACTERS == 15000
    assert profile["document"] == exact and profile["document_sha256"] == module._sha256(exact)
    monkeypatch.undo()
    # CRLF line ends are normalized before the count, so the same document is still inside.
    _packaged_with(monkeypatch, tmp_path, exact.replace("\n", "\r\n"), "crlf")
    assert load_profile("worker-v1")["characters"] == module.MAX_CHARACTERS


def test_an_oversized_document_is_refused_rather_than_truncated(monkeypatch, tmp_path):
    over = "# big\n" + "é" * (module.MAX_CHARACTERS - 6) + "\n"
    assert len(over) == module.MAX_CHARACTERS + 1
    _packaged_with(monkeypatch, tmp_path, over, "over")
    with pytest.raises(WorkerProfileError, match="exceeds 15000 characters"):
        load_profile("worker-v1")
    monkeypatch.undo()
    _packaged_with(monkeypatch, tmp_path, "# big\n" + ("x" * 80 + "\n") * 400, "big")
    with pytest.raises(WorkerProfileError, match="exceeds 15000 characters"):
        load_profile("worker-v1")


def test_a_manifest_naming_another_profile_or_non_bash_rules_is_refused(monkeypatch, tmp_path):
    original = module._resource_path
    manifest = json.loads(original("worker-profile-v1.json").read_text("utf-8"))
    for change, message in (({"id": "worker-v9"}, "does not name"),
                            ({"permissions": {"allow": ["Task"]}}, "only add Bash")):
        copy = tmp_path / ("manifest-" + message.split()[0] + ".json")
        copy.write_text(json.dumps({**manifest, **change}), encoding="utf-8")
        monkeypatch.setattr(module, "_resource_path",
                            lambda n, copy=copy: copy if n == "worker-profile-v1.json" else original(n))
        with pytest.raises(WorkerProfileError, match=message):
            load_profile("worker-v1")


# ---- the hook command: one string, two shells ---------------------------------------------------

def test_hook_arguments_are_quoted_for_sh_and_cmd_alike_and_unsafe_characters_are_refused(tmp_path):
    spaced = tmp_path / "a dir with spaces" / "한글 경로"
    command = hook_command(sys.executable, HOOK, spaced, "d" * 64)
    assert "\\" not in command, "Windows paths travel with forward slashes"
    words = shlex.split(command, posix=True)
    assert words[2:4] == ["--directory", str(spaced.resolve()).replace("\\", "/")]
    assert Path(words[0]).resolve() == Path(sys.executable).resolve()
    for bad in ('say "hi"', "$HOME", "%TEMP%", "a\\b", "x`y", "a;b", "a&b", "a|b", "line\nbreak"):
        with pytest.raises(WorkerProfileError, match="cannot be quoted"):
            quote_argument(bad)
    with pytest.raises(ContractError):
        quote_argument("")


def test_the_hook_runs_through_this_hosts_shell_and_writes_only_metadata(tmp_path):
    directory = tmp_path / "receipts with space" / "세션"
    command = hook_command(sys.executable, HOOK, directory, "p" * 64)
    payload = {"session_id": SESSION, "hook_event_name": "PostToolUse", "tool_name": "Bash",
               "tool_input": {"command": "export TOKEN=" + CANARY},
               "tool_response": {"stdout": CANARY}, "prompt": "secret prompt " + CANARY}
    for _ in range(2):  # two invocations, two files: nothing is overwritten
        completed = subprocess.run(command, shell=True, input=json.dumps(payload).encode("utf-8"),
                                   capture_output=True, timeout=60)
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout == b"", "a hook that prints would inject context"
    files = sorted(directory.glob("*.json"))
    assert len(files) == 2
    for path in files:
        text = path.read_text("utf-8")
        assert CANARY not in text and "secret prompt" not in text and "TOKEN" not in text
        record = json.loads(text)
        assert record["session_id"] == SESSION and record["hook_event_name"] == "PostToolUse"
        assert record["tool_name"] == "Bash" and record["profile_digest"] == "p" * 64
        assert set(record) <= {"hook", "session_id", "hook_event_name", "tool_name", "profile_digest",
                               "stdin_bytes", "stdin_truncated", "recorded_at_ns", "pid", "note"}
    receipts = hook_receipts(directory, "p" * 64)
    assert receipts["observed"] and receipts["records"] == 2 and receipts["events"]["PostToolUse"] == 2
    assert receipts["events"]["SessionStart"] == 0 and receipts["sessions_named"] == [SESSION]
    assert hook_receipts(directory, "q" * 64) == {**hook_receipts(directory, "q" * 64), "observed": False,
                                                  "records": 0, "foreign_records": 2}


def test_the_hook_bounds_its_input_and_reports_write_failure_without_content(tmp_path):
    directory = tmp_path / "bounded"
    run = lambda data, target=directory: subprocess.run(  # noqa: E731
        [sys.executable, str(HOOK), "--directory", str(target), "--profile-digest", "z" * 64],
        input=data, capture_output=True, timeout=60)
    oversized = run(json.dumps({"hook_event_name": "SessionStart", "pad": "y" * 70000}).encode())
    assert oversized.returncode == 0
    malformed = run(b"not json {")
    assert malformed.returncode == 0
    records = [json.loads(path.read_text("utf-8")) for path in directory.glob("*.json")]
    assert len(records) == 2
    assert {record["stdin_truncated"] for record in records} == {True, False}
    assert all(record["hook_event_name"] == "unknown" and record["stdin_bytes"] <= 65536 for record in records)
    missing = run(b"{}"), subprocess.run([sys.executable, str(HOOK)], input=b"{}", capture_output=True, timeout=60)
    assert missing[1].returncode == 1 and b"required" in missing[1].stderr
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("x", encoding="utf-8")
    failed = run(b"{}", blocked / "inner")
    assert failed.returncode == 1 and b"receipt not written" in failed.stderr
    assert b"Traceback" not in failed.stderr and CANARY.encode() not in failed.stderr


# ---- settings and environment -----------------------------------------------------------------

def test_the_profile_adds_hooks_and_bash_rules_and_changes_no_other_policy():
    profile = load_profile("worker-v1")
    hooks = hook_settings("cmd")
    merged = merge_settings(claude_settings(RUNTIME), profile, hooks)
    assert merged["permissions"]["deny"] == RUNTIME["disallowed_tools"]
    assert merged["permissions"]["defaultMode"] == "acceptEdits"
    assert merged["permissions"]["allow"][:3] == RUNTIME["allowed_tools"]
    assert "Bash(python -m ruff:*)" in merged["permissions"]["allow"]
    assert set(merged["hooks"]) == {"SessionStart", "PostToolUse", "PostToolUseFailure"}
    assert merged["hooks"]["PostToolUse"][0]["matcher"] == "Bash"
    assert merged["hooks"]["PostToolUseFailure"][0]["matcher"] == "Bash|Edit|Glob|Grep|Read|Write"
    assert "Stop" not in merged["hooks"]
    assert merge_settings(None, profile, hooks)["permissions"]["allow"] == profile["permissions_allow"]
    with pytest.raises(WorkerProfileError, match="already carry hooks"):
        merge_settings({"hooks": {"Stop": []}}, profile, hooks)


def test_the_metadata_command_is_one_exact_allow_and_every_earlier_grant_is_preserved():
    """Issue 124: each fixed module is granted as one exact command, never as a Python prefix."""
    profile = load_profile("worker-v1")
    exact = "Bash(python -m codex_harness.adapters.worker_profile_metadata)"
    frontend = "Bash(python -m codex_harness.adapters.monitor_frontend_checks)"
    assert profile["permissions_allow"] == [
        "Bash(python -m pytest:*)", "Bash(python -m pytest)", "Bash(python -m ruff:*)",
        "Bash(python -m compileall:*)", "Bash(git status:*)", "Bash(git status)", "Bash(git diff:*)",
        "Bash(git diff)", "Bash(git log:*)", exact, frontend]
    fixed = (exact, frontend)
    assert all(":*" not in rule for rule in fixed), "a fixed capability is never granted with a wildcard"
    assert not [rule for rule in profile["permissions_allow"] if rule not in fixed
                and ("worker_profile_metadata" in rule or "monitor_frontend_checks" in rule
                     or rule.startswith(("Bash(python:", "Bash(python)", "Bash(python -m:", "Bash(python -m)",
                                         "Bash(python -c", "Bash(node", "Bash(npm", "Bash(npx")))]
    # The grant is only as narrow as the replay policy that repeats it: extra tokens are refused.
    packaged = packaged_policy()
    for rule in fixed:
        argv = rule[len("Bash("):-1].split()
        assert authorized(argv, packaged), rule
        assert not authorized([*argv, "--help"], packaged) and not authorized([*argv, "."], packaged)
    manifest = json.loads(module._resource_path("worker-profile-v1.json").read_text("utf-8"))
    assert list(manifest) == ["id", "version", "document", "document_sha256", "hook", "hook_sha256",
                              "character_limit", "hooks", "permissions", "sources", "note"]
    assert set(manifest["permissions"]) == {"allow"} and manifest["character_limit"] == module.MAX_CHARACTERS
    assert manifest["hooks"] == ["SessionStart", "PostToolUse(Bash)",
                                 "PostToolUseFailure(Bash|Edit|Glob|Grep|Read|Write)"]
    assert len(manifest["sources"]) == 13
    assert {source["path"] for source in manifest["sources"]} >= {
        "scripts/lib/repeat_error_tracker.py", "scripts/lib/strike_dispatcher.py",
        "scripts/cli/strike_research_consume.py"}
    base = claude_settings({**RUNTIME, "disallowed_tools": ["Task", "WebFetch", "Bash(python -c:*)"]})
    merged = merge_settings(base, profile, hook_settings("cmd"))
    assert merged["permissions"]["deny"] == ["Task", "WebFetch", "Bash(python -c:*)"], "denies are delivered unchanged"
    assert merged["permissions"]["allow"] == [*RUNTIME["allowed_tools"], *profile["permissions_allow"]]
    assert merged["permissions"]["allow"].count(exact) == 1 and merged["permissions"]["allow"].count(frontend) == 1
    assert merged["permissions"]["defaultMode"] == "acceptEdits"


def test_the_profile_environment_prefixes_path_and_binds_pythonpath_to_the_candidate(tmp_path):
    interpreter = Path(sys.executable).resolve()
    base = {"PATH": os.pathsep.join(["/somewhere/else", str(interpreter.parent)]),
            "PYTHONPATH": "/parent/leak", "HOME": "/h"}
    env, report = profile_environment(base, tmp_path, interpreter)
    assert env["PATH"].split(os.pathsep)[0] == str(interpreter.parent)
    assert env["PATH"].split(os.pathsep).count(str(interpreter.parent)) == 1
    assert "PYTHONPATH" not in env and report["pythonpath"] is None, "no src, no PYTHONPATH"
    (tmp_path / "src").mkdir()
    env, report = profile_environment(base, tmp_path, interpreter)
    assert env["PYTHONPATH"] == str((tmp_path / "src").resolve()) == report["pythonpath"]
    assert env["HOME"] == "/h" and "/parent/leak" not in env["PYTHONPATH"]
    with pytest.raises(WorkerProfileError, match="not a file"):
        module.verified_interpreter(str(tmp_path / "missing-python"))


# ---- the whole run against the protocol child --------------------------------------------------

def test_a_profiled_run_delivers_the_document_and_hooks_and_reads_back_real_receipts(tmp_path):
    runtime, root = profiled(tmp_path)
    workspace = tmp_path / "candidate 작업"
    (workspace / "src").mkdir(parents=True)
    result = execute("profile", workspace, runtime, session_id=SESSION)
    seen = observation(workspace)
    profile = load_profile("worker-v1")

    # Delivery: the document is a value on the child's command line, the log keeps a digest.
    assert seen["append_system_prompt"] == profile["document"]
    argv = result["command"]["argv"]
    assert "--append-system-prompt" in argv
    assert profile["document"] not in argv and all("Verification before" not in str(e) for e in argv)
    selected = result["command"]["worker_profile"]
    assert selected["id"] == "worker-v1" and selected["document_sha256"] == profile["document_sha256"]
    assert selected["document_transport"] == "--append-system-prompt"
    assert "document" not in selected and selected["compliance"].startswith("not judged")
    assert selected["sources"][0]["pinned_sha256"]
    settings = json.loads(seen["settings"])
    assert set(settings["hooks"]) == {"SessionStart", "PostToolUse", "PostToolUseFailure"}
    assert settings["permissions"]["deny"] == RUNTIME["disallowed_tools"]
    assert "Bash(python -m ruff:*)" in settings["permissions"]["allow"]

    # Environment: the verified interpreter leads PATH; PYTHONPATH is the candidate's src.
    assert seen["path"].split(os.pathsep)[0] == str(Path(sys.executable).resolve().parent)
    assert seen["pythonpath"] == str((workspace / "src").resolve())
    assert result["command"]["environment"]["profile"]["pythonpath"] == seen["pythonpath"]
    assert "PYTHONPATH" in seen["environment_names"]

    # Observation: the child invoked both hooks through its shell and the hook wrote receipts.
    assert [run["exit_code"] for run in seen["hook_runs"]] == [0, 0], seen["hook_runs"]
    receipts = result["worker_profile"]["hook_receipts"]
    assert receipts["observed"] is True and receipts["records"] == 2
    assert receipts["events"] == {"SessionStart": 1, "PostToolUse": 1, "PostToolUseFailure": 0}
    assert receipts["two_strike"]["observed"] is False and receipts["two_strike"]["research_required"] == 0
    assert receipts["sessions_named"] == [SESSION] and receipts["foreign_records"] == 0
    directory = Path(receipts["directory"])
    assert directory == (root / SESSION).resolve() and directory.is_dir()
    assert workspace.resolve() not in directory.parents, "receipts live outside the checkout"
    for path in directory.glob("*.json"):
        assert CANARY not in path.read_text("utf-8")
    assert result["worker_profile"]["selected"] == selected
    assert result["answer"]["tests"] == ["profile hooks invoked"]
    assert result["process"]["confirmed"] and result["process"]["exit_code"] == 0
    assert receipts["authority"].startswith("none")


def test_hooks_that_never_ran_are_recorded_as_not_observed(tmp_path):
    runtime, root = profiled(tmp_path)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = execute("normal", workspace, runtime)  # the normal child ignores its settings
    receipts = result["worker_profile"]["hook_receipts"]
    assert receipts["observed"] is False and receipts["records"] == 0
    assert receipts["events"] == {"SessionStart": 0, "PostToolUse": 0, "PostToolUseFailure": 0}
    assert result["command"]["worker_profile"]["id"] == "worker-v1", "installation is still recorded"
    assert result["answer"] is not None, "the run's own outcome is unchanged by an absent receipt"


def test_concurrent_sessions_keep_separate_receipt_directories(tmp_path):
    runtime, root = profiled(tmp_path)
    first = "00000000-0000-4000-8000-000000000001"
    second = "00000000-0000-4000-8000-000000000002"
    results = []
    for session in (first, second):
        workspace = tmp_path / session
        workspace.mkdir()
        results.append(execute("profile", workspace, runtime, session_id=session))
    for session, result in zip((first, second), results):
        receipts = result["worker_profile"]["hook_receipts"]
        assert Path(receipts["directory"]).name == session
        assert receipts["records"] == 2 and receipts["sessions_named"] == [session]
    assert sorted(path.name for path in root.iterdir()) == [first, second]


def test_a_profiled_run_that_hits_its_deadline_keeps_the_existing_failure_and_receipts(tmp_path):
    runtime, root = profiled(tmp_path)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with transport("silent", runtime) as opened:
        result = opened.run("지시문", str(workspace), SCHEMA, timeout=2)
    assert result["failure"]["cause"] == "claude-provider-timeout"
    assert result["process"]["confirmed"] and result["process"]["stop_reason"] == "deadline"
    assert result["worker_profile"]["hook_receipts"]["observed"] is False


# ---- unconfigured runs are untouched -----------------------------------------------------------

def test_an_unconfigured_run_keeps_the_existing_transport_contract(tmp_path):
    result = execute("normal", tmp_path, RUNTIME)
    seen = observation(tmp_path)
    assert "worker_profile" not in result
    assert result["command"]["worker_profile"] is None
    assert "--append-system-prompt" not in result["command"]["argv"]
    assert seen["append_system_prompt"] is None
    assert "hooks" not in json.loads(seen["settings"])
    assert json.loads(seen["settings"]) == claude_settings(RUNTIME)
    assert seen["pythonpath"] is None and "profile" not in result["command"]["environment"]
    assert "--append-system-prompt" not in transport("normal", RUNTIME)._planned_flags()
    assert result["answer"] is not None
