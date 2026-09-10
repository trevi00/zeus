"""INV-ENCODING-001: actual Python children, not environment-string inspection."""
import os
import sys

from codex_harness.adapters.commands import python_channel_environment, run_process

TEXT = "검증 — 완료"  # U+2014 has no cp949 form.
# -X utf8=0 pins locale mode so the check is the same on hosts and interpreters that default to UTF-8.
ROUNDTRIP = [sys.executable, "-X", "utf8=0", "-c",
             "import sys;print(sys.stdout.encoding,flush=True);print(sys.stdin.read(),flush=True)"]
LITERAL = [sys.executable, "-X", "utf8=0", "-c",
           "import sys;print(sys.stdout.encoding,flush=True);print(%r,flush=True)" % TEXT]
LOCALE_PARENT = {**os.environ, "PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"}


def test_python_child_channel_matches_parent_decoder_in_both_directions():
    env = python_channel_environment(LOCALE_PARENT)
    assert env["PYTHONIOENCODING"] == "utf-8" and env["PATH"] == os.environ["PATH"]
    assert LOCALE_PARENT["PYTHONIOENCODING"] == "cp949", "input mapping is not mutated"
    for argv in (ROUNDTRIP, LITERAL):
        result = run_process(argv, input_text=TEXT, env=env, timeout=60)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "utf-8\n" + TEXT + "\n"


def test_unbound_locale_channel_is_the_failure_control():
    # Failure control (FA-009): the same children without the contract must not pass.
    roundtrip = run_process(ROUNDTRIP, input_text=TEXT, env=LOCALE_PARENT, timeout=60)
    literal = run_process(LITERAL, input_text=TEXT, env=LOCALE_PARENT, timeout=60)
    assert roundtrip.stdout.startswith("cp949\n") and literal.stdout.startswith("cp949\n")
    assert roundtrip.returncode != 0 and "UnicodeDecodeError" in roundtrip.stderr
    assert literal.returncode != 0 and "UnicodeEncodeError" in literal.stderr


def test_default_base_is_a_copy_of_the_current_environment(monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp949")
    monkeypatch.setenv("PYTHONUTF8", "0")
    env = python_channel_environment()
    assert env["PYTHONIOENCODING"] == "utf-8" and env["PYTHONUTF8"] == "0"
    assert os.environ["PYTHONIOENCODING"] == "cp949", "os.environ is not mutated"
