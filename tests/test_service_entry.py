"""docs/zeus/operations/self-improvement-reference-001/SPEC.md: safe Fleet lifecycle provenance.

The gap is the launcher's `Out-Null`: an exit 1 with no type, no place and no way to tell one run
from the next. What is checked here is exactly that much and no more - the exit status the CLI
asked for, the bounded facts written beside it, and the long list of things that must never reach
the file.

Three kinds of evidence, kept apart:

* real runs in this process: a callable standing in for `cli.main`, its exit codes, its exceptions
  and the resulting journal;
* labelled injection for what an OS will not produce on demand - a journal that opens and then
  refuses a line, a rotation that fails, and frames that report an in-package file without any
  test code being installed into the package;
* a real subprocess that runs `python -m codex_harness.adapters.service_entry` against the actual
  `codex_harness.cli`, with `--help` and with an unknown option. Neither needs a model, PostgreSQL,
  Redis or a service.

No test here starts a service, owns a process tree or touches production configuration; the owner
of the tree is still `background_service`, whose own tests are unchanged.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

import codex_harness
from codex_harness.adapters import background_service, service_entry
from codex_harness.adapters.commands import python_channel_environment
from codex_harness.adapters.service_entry import main, run

CANARY = "canary-3f9e1d47-not-for-the-journal"
PACKAGE_ROOT = Path(codex_harness.__file__).resolve().parents[1]
# A path inside the installed package that does not exist: enough for a frame to be ours, and
# nothing is ever written there.
IN_PACKAGE_FILE = str(Path(codex_harness.__file__).resolve().parent / "adapters" / "_probe.py")


@pytest.fixture
def journal(tmp_path):
    return tmp_path / "service.jsonl"


def entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def events(path: Path) -> list[str]:
    return [entry["event"] for entry in entries(path)]


def last(path: Path, event: str) -> dict:
    found = [entry for entry in entries(path) if entry["event"] == event]
    assert found, f"no {event} entry in {events(path)}"
    return found[-1]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def calling(monkeypatch, behaviour):
    """Stand in for `cli.main`; record the argv the CLI would have seen."""
    seen: list[list[str]] = []

    def entry():
        seen.append(list(sys.argv))
        behaviour()

    monkeypatch.setattr(service_entry, "_cli_main", entry)
    return seen


# ---- real runs: the exit status the CLI asked for ----------------------------------------------


def test_a_successful_call_is_zero_and_three_ordered_entries(journal, monkeypatch):
    seen = calling(monkeypatch, lambda: None)
    assert run(str(journal), ["fleet", "run"]) == 0
    assert seen == [["zeus", "fleet", "run"]], "the CLI arguments are passed through unchanged"
    assert events(journal) == ["start", "finish", "exit"]
    assert last(journal, "finish")["reason"] == "ok"
    assert last(journal, "exit") | {"timestamp": None} == {
        "timestamp": None, "event": "exit", "reason": "ok", "final_exit_code": 0,
        "run_id": last(journal, "start")["run_id"]}


def test_a_zero_system_exit_is_success_and_a_none_exit_is_too(journal, monkeypatch):
    calling(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(0)))
    assert run(str(journal), []) == 0
    assert last(journal, "finish")["reason"] == "ok"
    calling(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(None)))
    assert run(str(journal), []) == 0
    assert last(journal, "finish") | {"timestamp": None} == {
        "timestamp": None, "event": "finish", "reason": "ok", "exit_code": 0,
        "run_id": last(journal, "start")["run_id"]}


@pytest.mark.parametrize("code", [1, 2, 7])
def test_a_nonzero_cli_exit_is_preserved_with_its_type_and_place(journal, monkeypatch, code):
    """The Fleet case: `cli.main` raises SystemExit, and the number survives with a reason."""
    def refuse():
        raise SystemExit(code)

    calling(monkeypatch, refuse)
    assert run(str(journal), ["fleet", "run"]) == code
    finish = last(journal, "finish")
    assert finish["reason"] == "cli_exit" and finish["exit_code"] == code
    assert finish["exception"] == "SystemExit" and finish["cause"] == "none"
    assert last(journal, "exit")["final_exit_code"] == code


def test_a_cli_style_system_exit_carries_the_cause_it_was_raised_from(journal, monkeypatch):
    """`cli.main` reports a refusal as `raise SystemExit(1) from exc`; the cause is the fact."""
    def refuse():
        try:
            raise ValueError(CANARY)
        except ValueError as failure:
            raise SystemExit(1) from failure

    calling(monkeypatch, refuse)
    assert run(str(journal), []) == 1
    finish = last(journal, "finish")
    assert finish["exception"] == "SystemExit" and finish["cause"] == "present"
    assert [link["kind"] for link in finish["causes"]] == ["cause"]
    assert finish["causes"][0]["exception"] == "ValueError"
    assert finish["cause_truncated"] is False and finish["cause_cycle"] is False
    assert CANARY not in text(journal)


def test_an_uncaught_exception_is_one_and_names_only_a_builtin_type(journal, monkeypatch):
    def fail():
        raise RuntimeError(CANARY)

    calling(monkeypatch, fail)
    assert run(str(journal), []) == 1
    finish = last(journal, "finish")
    assert finish["reason"] == "uncaught_exception" and finish["exception"] == "RuntimeError"
    assert CANARY not in text(journal)


def test_an_exception_defined_outside_builtins_is_unknown_not_its_name(journal, monkeypatch):
    class SecretLookingError(RuntimeError):
        pass

    def fail():
        raise SecretLookingError("x")

    calling(monkeypatch, fail)
    assert run(str(journal), []) == 1
    assert last(journal, "finish")["exception"] == "unknown"
    assert "SecretLooking" not in text(journal)


def test_a_look_alike_named_after_a_builtin_is_also_unknown(journal, monkeypatch):
    """The allowlist is the type itself, not the spelling of its name."""
    ValueError_ = type("ValueError", (RuntimeError,), {})

    calling(monkeypatch, lambda: (_ for _ in ()).throw(ValueError_("x")))
    assert run(str(journal), []) == 1
    assert last(journal, "finish")["exception"] == "unknown"


@pytest.mark.parametrize("code", [CANARY, ("a", CANARY), object(), 1.5])
def test_a_non_integer_exit_is_a_fixed_one_and_its_value_is_never_written(journal, monkeypatch,
                                                                         code):
    calling(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(code)))
    assert run(str(journal), []) == 1
    finish = last(journal, "finish")
    assert finish["reason"] == "cli_exit_unknown" and "exit_code" not in finish
    assert CANARY not in text(journal)


@pytest.mark.parametrize(("code", "expected"), [(False, 0), (True, 1)])
def test_a_boolean_exit_is_read_as_the_integer_it_is(journal, monkeypatch, code, expected):
    calling(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(code)))
    assert run(str(journal), []) == expected
    finish = last(journal, "finish")
    assert finish["exit_code"] == expected and type(finish["exit_code"]) is int
    assert finish["reason"] == ("ok" if expected == 0 else "cli_exit")


def test_a_keyboard_interrupt_is_one_hundred_and_thirty(journal, monkeypatch):
    calling(monkeypatch, lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert run(str(journal), []) == 130
    finish = last(journal, "finish")
    assert finish["reason"] == "interrupted" and finish["exception"] == "KeyboardInterrupt"
    assert last(journal, "exit")["final_exit_code"] == 130


# ---- the chain, bounded ------------------------------------------------------------------------


def test_a_long_cause_chain_stops_at_four_links_and_says_it_was_truncated(journal, monkeypatch):
    def fail():
        failure: BaseException = ValueError("0")
        for index in range(6):
            nxt = RuntimeError(str(index))
            nxt.__cause__ = failure
            failure = nxt
        raise failure

    calling(monkeypatch, fail)
    assert run(str(journal), []) == 1
    finish = last(journal, "finish")
    assert len(finish["causes"]) == 4 and finish["cause_truncated"] is True
    assert finish["cause_cycle"] is False


def test_a_cycle_in_the_chain_ends_the_walk_instead_of_following_it(journal, monkeypatch):
    def fail():
        first, second = RuntimeError("a"), ValueError("b")
        first.__cause__, second.__cause__ = second, first
        raise first

    calling(monkeypatch, fail)
    assert run(str(journal), []) == 1
    finish = last(journal, "finish")
    assert finish["cause_cycle"] is True and len(finish["causes"]) == 1
    assert finish["causes"][0]["exception"] == "ValueError"


def test_a_suppressed_context_is_not_reported_as_a_cause(journal, monkeypatch):
    def fail():
        try:
            raise ValueError("first")
        except ValueError:
            raise RuntimeError("second") from None

    calling(monkeypatch, fail)
    assert run(str(journal), []) == 1
    finish = last(journal, "finish")
    assert finish["cause"] == "none" and finish["causes"] == []


def test_an_unsuppressed_context_is_reported_as_a_context_link(journal, monkeypatch):
    def fail():
        try:
            raise ValueError("first")
        except ValueError:
            raise RuntimeError("second")

    calling(monkeypatch, fail)
    assert run(str(journal), []) == 1
    assert [link["kind"] for link in last(journal, "finish")["causes"]] == ["context"]


# ---- frames: ours only, deepest eight, no absolute paths ---------------------------------------


def test_only_in_package_frames_are_kept_and_never_the_callers_file(journal, monkeypatch):
    def fail():
        raise RuntimeError("x")

    calling(monkeypatch, fail)
    assert run(str(journal), []) == 1
    frames = last(journal, "finish")["frames"]
    assert frames, "the place the exception left the package is the point of this journal"
    assert all(frame["module"].startswith("codex_harness/") for frame in frames)
    assert all(frame["line"] > 0 for frame in frames)
    assert "test_service_entry" not in text(journal)
    assert str(Path(__file__).resolve()) not in text(journal)
    assert str(PACKAGE_ROOT) not in text(journal), "no absolute path, only a relative module path"


def in_package_frames(depth: int):
    """Injection: a recursion whose frames report an in-package file.

    `compile` sets the file name a traceback reports, so a deep in-package stack is available
    without installing any test code into the package and without writing that file.
    """
    scope: dict = {}
    source = "def deep(n):\n    if n:\n        return deep(n - 1)\n    raise RuntimeError('x')\n"
    exec(compile(source, IN_PACKAGE_FILE, "exec"), scope)  # noqa: S102 - labelled injection
    return lambda: scope["deep"](depth)


def test_at_most_eight_of_our_deepest_frames_are_written(journal, monkeypatch):
    calling(monkeypatch, in_package_frames(12))
    assert run(str(journal), []) == 1
    frames = last(journal, "finish")["frames"]
    assert len(frames) == 8
    assert {frame["module"] for frame in frames} == {"codex_harness/adapters/_probe.py"}
    assert not Path(IN_PACKAGE_FILE).exists(), "the injection writes no file into the package"


def test_a_frame_outside_the_package_is_omitted_rather_than_shortened():
    assert service_entry._location("<string>", 3) is None
    assert service_entry._location(str(Path(__file__).resolve()), 3) is None
    assert service_entry._location(IN_PACKAGE_FILE, 0) is None
    assert service_entry._location(IN_PACKAGE_FILE, None) is None
    assert service_entry._location(IN_PACKAGE_FILE, 4) == {
        "module": "codex_harness/adapters/_probe.py", "line": 4}


# ---- what may be in the file at all ------------------------------------------------------------


def test_the_journal_carries_only_allowlisted_fields_and_no_canary(journal, monkeypatch, tmp_path):
    """Visibility/privacy: argv, the message, a local and the source line all carry the canary."""
    def fail():
        secret_local = CANARY + "-local"  # noqa: F841 - the point is that it is never read
        raise ValueError(CANARY + "-message")

    calling(monkeypatch, fail)
    assert run(str(journal), ["fleet", "run", "--token", CANARY + "-argv"]) == 1
    written = text(journal)
    assert CANARY not in written
    assert str(tmp_path) not in written and sys.executable not in written
    allowed = {"timestamp", "event", "run_id", "reason", "exception", "exit_code",
               "final_exit_code", "frames", "cause", "causes", "cause_truncated", "cause_cycle"}
    for entry in entries(journal):
        assert set(entry) <= allowed, entry


def test_a_field_outside_the_allowlist_or_of_the_wrong_shape_is_dropped(journal):
    """An unknown name, a frame that is not ours and a reason outside the vocabulary all go."""
    book = service_entry.Journal(str(journal), logger_name=service_entry.LOGGER_NAME,
                                 fields=service_entry.ENTRY_FIELDS)
    try:
        book.write("start", run_id="abc", command_line=CANARY, reason=CANARY,
                   exception=CANARY, frames=[{"module": CANARY, "line": 1}],
                   causes=[{"kind": "cause", "exception": CANARY, "frames": []}])
    finally:
        book.close()
    assert CANARY not in text(journal)
    assert set(entries(journal)[0]) == {"timestamp", "event", "run_id"}


def test_the_adapter_binds_nothing_that_could_own_a_process():
    """The owner of the service tree is unchanged: this module spawns, signals and kills nothing."""
    assert {"subprocess", "signal", "os", "ProcessTree", "run_owned"}.isdisjoint(
        vars(service_entry))


def test_the_adapter_prints_nothing_of_its_own_on_a_failure(journal, monkeypatch, capsys):
    calling(monkeypatch, lambda: (_ for _ in ()).throw(RuntimeError(CANARY)))
    assert run(str(journal), []) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


# ---- argv, and one run against the next --------------------------------------------------------


@pytest.mark.parametrize("behaviour", [lambda: None,
                                       lambda: (_ for _ in ()).throw(RuntimeError("x")),
                                       lambda: (_ for _ in ()).throw(SystemExit(3)),
                                       lambda: (_ for _ in ()).throw(KeyboardInterrupt())])
def test_the_original_argv_is_restored_however_the_call_ends(journal, monkeypatch, behaviour):
    original = list(sys.argv)
    calling(monkeypatch, behaviour)
    run(str(journal), ["fleet", "run"])
    assert sys.argv == original


def test_sequential_invocations_share_the_file_and_stay_identifiable(journal, monkeypatch):
    calling(monkeypatch, lambda: None)
    assert run(str(journal), ["fleet", "run"]) == 0
    calling(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(4)))
    assert run(str(journal), ["fleet", "run"]) == 4
    starts = [entry["run_id"] for entry in entries(journal) if entry["event"] == "start"]
    assert len(starts) == 2 and starts[0] != starts[1]
    assert events(journal) == ["start", "finish", "exit"] * 2
    per_run = {entry["run_id"] for entry in entries(journal)}
    assert per_run == set(starts), "every entry names the run it belongs to"


# ---- the journal itself failing ----------------------------------------------------------------


class _Refuses:
    """A stream that accepts nothing, the way a full disk does."""

    def write(self, text):
        raise OSError("injected: the journal stream refuses writes")

    def flush(self):
        pass

    def close(self):
        pass

    def seek(self, *args):
        return 0

    def tell(self):
        return 0


def refusing_from(event: str):
    """Injection: from the named event on, journal writes fail and are not swallowed."""

    class _RefusingHandler(RotatingFileHandler):
        def emit(self, record):
            if ('"event": "' + event + '"') in record.getMessage():
                self.stream = _Refuses()
            super().emit(record)

    return _RefusingHandler


def refusing_only(event: str):
    """Injection: exactly one event's line is lost; the journal works before and after it."""

    class _RefusingHandler(RotatingFileHandler):
        def emit(self, record):
            if ('"event": "' + event + '"') not in record.getMessage():
                super().emit(record)
                return
            real, self.stream = self.stream, _Refuses()
            try:
                super().emit(record)
            finally:
                self.stream = real

    return _RefusingHandler


def failing_rotation():
    """Injection: the file rotates on every line and the rotation itself fails."""

    class _RollingHandler(RotatingFileHandler):
        def shouldRollover(self, record):
            return True

        def doRollover(self):
            raise OSError("injected: rotation failed")

    return _RollingHandler


def test_a_journal_that_cannot_be_opened_runs_nothing(tmp_path, monkeypatch):
    seen = calling(monkeypatch, lambda: None)
    unwritable = tmp_path / "no-such-directory" / "service.jsonl"
    assert run(str(unwritable), ["fleet", "run"]) == 125
    assert seen == [], "a run nobody can account for never begins"
    assert not unwritable.exists()


def test_a_journal_that_refuses_its_first_line_never_calls_the_cli(journal, monkeypatch):
    seen = calling(monkeypatch, lambda: None)
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("start"))
    assert run(str(journal), ["fleet", "run"]) == 125
    assert seen == [] and entries(journal) == []


def test_a_rotation_failure_before_the_start_also_calls_nothing(journal, monkeypatch):
    seen = calling(monkeypatch, lambda: None)
    monkeypatch.setattr(background_service, "RotatingFileHandler", failing_rotation())
    assert run(str(journal), ["fleet", "run"]) == 125
    assert seen == []


def test_a_journal_that_fails_after_the_start_never_reports_success(journal, monkeypatch):
    """The CLI succeeded; the run that cannot be described is still an owner-side 125."""
    calling(monkeypatch, lambda: None)
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("finish"))
    assert run(str(journal), ["fleet", "run"]) == 125
    assert events(journal) == ["start"]


def test_a_lost_finish_line_is_stated_in_the_exit_entry(journal, monkeypatch):
    """Explicit, not silent: the entry that did reach the file names the diagnostics failure."""
    calling(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(7)))
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_only("finish"))
    assert run(str(journal), ["fleet", "run"]) == 125
    assert events(journal) == ["start", "exit"]
    exit_entry = last(journal, "exit")
    assert exit_entry["reason"] == "diagnostics_failed" and exit_entry["final_exit_code"] == 125


def test_a_lost_exit_line_is_a_diagnostics_failure_whatever_the_cli_said(journal, monkeypatch):
    calling(monkeypatch, lambda: (_ for _ in ()).throw(SystemExit(7)))
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("exit"))
    assert run(str(journal), ["fleet", "run"]) == 125
    assert events(journal) == ["start", "finish"]
    assert last(journal, "finish")["exit_code"] == 7, "the CLI's own fact is preserved"


# ---- reuse: the owner's rotating journal, and the owner's log left alone ------------------------


def test_the_lifecycle_journal_reuses_the_owners_size_cap_and_backups(journal):
    book = service_entry.Journal(str(journal), logger_name=service_entry.LOGGER_NAME,
                                 fields=service_entry.ENTRY_FIELDS)
    try:
        assert book.handler.maxBytes == background_service.LOG_BYTES
        assert book.handler.backupCount == background_service.LOG_BACKUPS
    finally:
        book.close()


def test_the_owners_journal_keeps_its_own_logger_fields_and_lines(tmp_path):
    """A second journal must not take the owner's handler, its allowlist or its file."""
    owner_path, entry_path = tmp_path / "owner.jsonl", tmp_path / "service.jsonl"
    owner = background_service.Journal(owner_path)
    entry = service_entry.Journal(str(entry_path), logger_name=service_entry.LOGGER_NAME,
                                  fields=service_entry.ENTRY_FIELDS)
    try:
        owner.write("starting")
        entry.write("start", run_id="0123456789abcdef")
        owner.write("shutdown", final_exit_code=0, pid=1234, run_id=CANARY)
    finally:
        entry.close()
        owner.close()
    assert events(owner_path) == ["starting", "shutdown"]
    assert events(entry_path) == ["start"]
    assert last(owner_path, "shutdown") | {"timestamp": None} == {
        "timestamp": None, "event": "shutdown", "final_exit_code": 0, "pid": 1234}
    assert CANARY not in text(owner_path) and CANARY not in text(entry_path)


# ---- the argument boundary ---------------------------------------------------------------------


def test_the_cli_arguments_after_the_separator_are_not_read_by_this_side(journal, monkeypatch):
    seen = calling(monkeypatch, lambda: None)
    assert main(["--journal", str(journal), "--", "fleet", "--journal", "x", "--", "run"]) == 0
    assert seen == [["zeus", "fleet", "--journal", "x", "--", "run"]]


@pytest.mark.parametrize("argv", [[], ["fleet", "run"], ["--journal"], ["--journal", ""],
                                  ["--journal", "j", "fleet"], ["--other", "j", "--"],
                                  ["--other", CANARY, "--", "fleet"]])
def test_a_usage_error_is_a_fixed_line_and_no_run(argv, monkeypatch, capsys):
    """The answer is the fixed usage line: nothing that was passed in is echoed back."""
    seen = calling(monkeypatch, lambda: None)
    assert main(argv) == 125
    assert seen == []
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip() == service_entry.USAGE
    assert CANARY not in captured.err


def test_the_attached_journal_form_is_accepted_too(journal, monkeypatch):
    seen = calling(monkeypatch, lambda: None)
    assert main([f"--journal={journal}", "--", "fleet", "run"]) == 0
    assert seen == [["zeus", "fleet", "run"]] and events(journal) == ["start", "finish", "exit"]


def test_an_empty_cli_argument_list_is_allowed(journal, monkeypatch):
    seen = calling(monkeypatch, lambda: None)
    assert main(["--journal", str(journal), "--"]) == 0
    assert seen == [["zeus"]]


# ---- a real subprocess against the real CLI ----------------------------------------------------


def module_environment() -> dict:
    env = python_channel_environment()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(PACKAGE_ROOT) + ((os.pathsep + existing) if existing else "")
    return env


def run_module(journal: Path, cli_args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "codex_harness.adapters.service_entry",
                           "--journal", str(journal), "--", *cli_args],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          env=module_environment(), timeout=180)


def test_the_module_runs_the_real_cli_help_and_answers_zero(journal):
    """A real process, the real `cli.main`, no model, database or service."""
    done = run_module(journal, ["--help"])
    assert done.returncode == 0, done.stderr
    assert "usage" in done.stdout.lower(), "the CLI's own output is untouched"
    assert events(journal) == ["start", "finish", "exit"]
    assert last(journal, "finish")["reason"] == "ok"
    assert last(journal, "exit")["final_exit_code"] == 0
    assert "usage" not in text(journal).lower(), "the CLI's output is not in the journal"


def test_the_module_preserves_the_real_clis_refusal_of_an_unknown_option(journal):
    done = run_module(journal, ["--not-a-real-option-3f9e"])
    assert done.returncode == 2, done.stdout + done.stderr
    finish = last(journal, "finish")
    assert finish["reason"] == "cli_exit" and finish["exit_code"] == 2
    assert finish["exception"] == "SystemExit"
    modules = {frame["module"] for frame in finish["frames"]}
    assert "codex_harness/cli.py" in modules, modules
    assert all(module.startswith("codex_harness/") for module in modules)
    assert "not-a-real-option" not in text(journal), "the rejected argument is never journalled"
    assert last(journal, "exit")["final_exit_code"] == 2
