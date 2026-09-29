"""INV-WORKER-PROFILE-001: the opt-in worker profile for the Claude Code CLI transport.

The profile layer is exercised against `tests/claude_protocol_child.py`, which plays Claude
Code's hook runner: it invokes each configured command hook through the platform shell with the
event JSON on stdin. That proves the adapter's delivery, quoting, environment and receipt
handling on this host; it proves nothing about a model, and the real canary is recorded
separately by the operation.

Ported SOURCE M7 suite `tests/test_worker_profile.py` run against the target (REBUILD-DESIGN-v2 §5.3 S2).

Import paths rewritten to the target modules; any other adaptation is named in place.

Not ported here (owning slice; carried forward, listed in the S2 coverage evidence):
- test_a_profiled_run_delivers_the_document_and_hooks_and_reads_back_real_receipts: S3 execution: a profiled run through the Claude CLI transport
- test_hooks_that_never_ran_are_recorded_as_not_observed: S3 execution: a profiled run through the Claude CLI transport
- test_concurrent_sessions_keep_separate_receipt_directories: S3 execution: a profiled run through the Claude CLI transport
- test_a_profiled_run_that_hits_its_deadline_keeps_the_existing_failure_and_receipts: S3 execution: a profiled run through the Claude CLI transport
- test_an_unknown_profile_name_is_refused_before_anything_is_probed: S3 execution: the Claude CLI transport
- test_the_profile_adds_hooks_and_bash_rules_and_changes_no_other_policy: S3 execution: the Claude CLI transport
- test_the_metadata_command_is_one_exact_allow_and_every_earlier_grant_is_preserved: S3 execution: the Claude CLI transport
- test_an_unconfigured_run_keeps_the_existing_transport_contract: S3 execution: the Claude CLI transport
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.context.adapters import worker_profile as module
from codex_harness.context.adapters.worker_profile import (
    WorkerProfileError,
    hook_command,
    hook_receipts,
    load_profile,
    profile_digest,
    profile_environment,
    quote_argument,
)
from codex_harness.kernel.errors import ContractError

CHILD = Path(__file__).resolve().parent / "claude_protocol_child.py"
HOOK = Path(module.__file__).resolve().parents[2] / "resources" / "worker_profile_hook.py"  # adapted: one package level deeper
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









# ---- unconfigured runs are untouched -----------------------------------------------------------

