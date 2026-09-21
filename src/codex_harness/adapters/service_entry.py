"""Where a service run ended, written down before the CLI's stderr disappears.

The registered Fleet task starts a hidden PowerShell launcher that sends the CLI's stdout and
stderr to `Out-Null`, so an exit 1 arrives with two reconciliation lines and nothing else: no
exception type, no place in the package, no way to tell one run from the next
(docs/zeus/operations/self-improvement-reference-001/RESIDUAL-DISPOSITION.md). That lost provenance
is the only thing this adapter adds. It is not a repair of the old exit 1, whose cause stays
unknown, and it is not a second process owner: `background_service.ProcessTree` remains the sole
owner of the service tree, and nothing here retries, releases, budgets or kills anything.

    python -m codex_harness.adapters.service_entry --journal PATH -- fleet run

The CLI arguments after `--` are passed to the existing `codex_harness.cli.main` unchanged, through
a scoped `sys.argv` replacement that is restored however the call ends. The CLI runs in this
process, so its own stdout and stderr keep going wherever the launcher sends them; this adapter
adds a durable journal beside them and prints nothing itself.

The journal is the rotating JSONL of `background_service` reused - its size cap, its backups, its
refusal to let `logging` swallow a lost line - under its own logger name and its own typed
allowlist, so the owner's journal keeps exactly the fields and the log it had. One journal belongs
to one service instance; concurrent owners of the same service remain prohibited by the existing
process ownership, not by this file.

The exit status is the CLI's, and the journal is the reason:

| answer | meaning                                                                       |
|--------|-------------------------------------------------------------------------------|
| child  | the CLI's own `SystemExit` code, preserved, including a `0` or a `None`        |
| 1      | an uncaught exception, or an exit whose code is not an integer                 |
| 125    | the diagnostics themselves failed; before the start, the CLI never ran at all  |
| 130    | KeyboardInterrupt                                                             |

What a failure entry may say is fixed in advance: a run id, a timestamp, a reason code from a
closed vocabulary, the name of a *built-in* exception type or `unknown`, and at most eight
frames - the deepest ones that belong to this installed `codex_harness` package - each a
package-relative module path and an integer line. A frame outside the package is omitted rather
than shortened, and a class defined outside `builtins` is `unknown` rather than named, because a
name from somewhere else is exactly the kind of text this journal is not allowed to carry. No
message, `repr`, argument, local, environment value, source line, absolute path or raw traceback
is read or written anywhere.

`cli.main` reports a refusal as `raise SystemExit(1) from exc`, so the chained cause is walked as
well, bounded to four links, `__suppress_context__` respected, and a cycle ends the walk instead of
following it. The absence of a cause is stated (`cause: none`) rather than left out.

This proves where an exception left the package. It is not a root cause, it says nothing about the
child processes the CLI itself started, and it cannot exist at all for a SIGKILL or for a failure
before the interpreter starts.
"""
from __future__ import annotations

import builtins
import re
import sys
import traceback
import uuid
from pathlib import Path

import codex_harness
from codex_harness.adapters.background_service import (
    EXIT_INTERRUPTED,
    EXIT_OWNER_ERROR,
    Journal,
    record,
    safe_scalar,
)

# INV-SERVICE-DIAGNOSTICS-001 is the contract for everything below.
EXIT_SUCCESS = 0
# One fixed answer for "it failed and the code is not a number", so no exit value is ever formatted.
EXIT_FAILURE = 1
# The owner's own 125 keeps its meaning here: this side failed, whatever the CLI said.
EXIT_DIAGNOSTICS_FAILED = EXIT_OWNER_ERROR

LOGGER_NAME = "zeus.service_entry"
# argv[0] for the CLI: a fixed name, never this host's interpreter or script path.
CLI_PROGRAM = "zeus"
USAGE = "usage: python -m codex_harness.adapters.service_entry --journal PATH -- CLI_ARGS"

MAX_FRAMES = 8
MAX_CAUSES = 4
UNKNOWN_EXCEPTION = "unknown"
CAUSE_KINDS = frozenset({"cause", "context"})
# The closed reason vocabulary. A reason is chosen from here or the field is dropped.
REASONS = frozenset({"ok", "cli_exit", "cli_exit_unknown", "uncaught_exception", "interrupted",
                     "diagnostics_failed"})
_PACKAGE = Path(codex_harness.__file__).resolve().parent
# A package-relative module path: `codex_harness/adapters/fleet_cli.py` and nothing else. The
# package prefix is part of the pattern, so a frame this module did not derive from the installed
# package cannot pass the allowlist on its way into the file.
MODULE_PATH = re.compile(re.escape(_PACKAGE.name) + r"/[A-Za-z0-9_./-]{1,110}")


def _safe_reason(value) -> bool:
    return isinstance(value, str) and value in REASONS


def _safe_exception(value) -> bool:
    """A built-in exception type's name, or the fixed unknown. Never a name from other code."""
    if not isinstance(value, str) or not safe_scalar(value):
        return False
    if value == UNKNOWN_EXCEPTION:
        return True
    found = getattr(builtins, value, None)
    return isinstance(found, type) and issubclass(found, BaseException)


def _safe_frame(value) -> bool:
    return (isinstance(value, dict) and set(value) == {"module", "line"}
            and isinstance(value["module"], str)
            and MODULE_PATH.fullmatch(value["module"]) is not None
            and type(value["line"]) is int and value["line"] > 0)


def _safe_frames(value) -> bool:
    return (isinstance(value, list) and len(value) <= MAX_FRAMES
            and all(_safe_frame(item) for item in value))


def _safe_causes(value) -> bool:
    return (isinstance(value, list) and len(value) <= MAX_CAUSES
            and all(isinstance(item, dict) and set(item) == {"kind", "exception", "frames"}
                    and isinstance(item["kind"], str) and item["kind"] in CAUSE_KINDS
                    and _safe_exception(item["exception"])
                    and _safe_frames(item["frames"]) for item in value))


# The complete allowlist for this journal, each field with the shape it is allowed to have.
# Anything else, or anything of the wrong shape, is dropped by `Journal.write` rather than repaired.
ENTRY_FIELDS = {
    "run_id": safe_scalar,
    "reason": _safe_reason,
    "exception": _safe_exception,
    "exit_code": safe_scalar,
    "final_exit_code": safe_scalar,
    "frames": _safe_frames,
    "cause": safe_scalar,
    "causes": _safe_causes,
    "cause_truncated": safe_scalar,
    "cause_cycle": safe_scalar,
}


def _location(filename, line) -> dict | None:
    """One frame as a package-relative module path and a line, or `None` if it is not ours.

    `<string>`, a frozen import, a test's own file and every third-party frame land outside the
    installed package directory and are dropped here; nothing is truncated into shape.
    """
    if type(line) is not int or line <= 0 or not isinstance(filename, str):
        return None
    try:
        relative = Path(filename).resolve().relative_to(_PACKAGE)
    except (ValueError, OSError, RuntimeError):
        return None
    module = f"{_PACKAGE.name}/{relative.as_posix()}"
    if MODULE_PATH.fullmatch(module) is None:
        return None  # an unexpected name in the path is omitted rather than sanitized
    return {"module": module, "line": line}


def _frames(failure: BaseException) -> list[dict]:
    """The deepest `MAX_FRAMES` in-package frames of one exception, outermost first."""
    try:
        extracted = traceback.extract_tb(failure.__traceback__)
    except BaseException:
        return []  # reading a traceback is not worth losing the entry over
    ours = [location for frame in extracted
            if (location := _location(frame.filename, frame.lineno)) is not None]
    return ours[-MAX_FRAMES:]


def _next_link(failure: BaseException) -> tuple[BaseException | None, str]:
    cause = failure.__cause__
    if cause is not None:
        return cause, "cause"
    context = failure.__context__
    if context is not None and not failure.__suppress_context__:
        return context, "context"
    return None, ""


def _chain(failure: BaseException) -> dict:
    """Bounded `__cause__`/`__context__` walk: types and places only, never a message.

    Identity is the only thing compared, so a chain that points back at itself ends the walk
    instead of being followed, and a chain longer than `MAX_CAUSES` is reported as truncated
    rather than silently cut.
    """
    seen = {id(failure)}
    links: list[dict] = []
    current, cycle, truncated = failure, False, False
    while True:
        nxt, kind = _next_link(current)
        if nxt is None:
            break
        if id(nxt) in seen:
            cycle = True
            break
        if len(links) >= MAX_CAUSES:
            truncated = True
            break
        seen.add(id(nxt))
        links.append({"kind": kind, "exception": _exception_name(nxt), "frames": _frames(nxt)})
        current = nxt
    return {"cause": "present" if links else "none", "causes": links,
            "cause_truncated": truncated, "cause_cycle": cycle}


def _exception_name(failure: BaseException) -> str:
    """The exact built-in type's name, or `unknown` - including for a look-alike defined elsewhere."""
    kind = type(failure)
    found = getattr(builtins, kind.__name__, None)
    return kind.__name__ if found is kind else UNKNOWN_EXCEPTION


def _failure_facts(reason: str, failure: BaseException) -> dict:
    return {"reason": reason, "exception": _exception_name(failure), "frames": _frames(failure),
            **_chain(failure)}


def _exit_facts(request: SystemExit) -> tuple[int, dict]:
    """A `SystemExit` read without reading its value: only an exact `int` is a code at all."""
    code = request.code
    if code is None:
        return EXIT_SUCCESS, {"reason": "ok", "exit_code": EXIT_SUCCESS}
    if type(code) is bool:
        code = int(code)  # a bool is an integer value in Python, so it is a code, not an unknown
    if type(code) is int:
        if code == EXIT_SUCCESS:
            return EXIT_SUCCESS, {"reason": "ok", "exit_code": EXIT_SUCCESS}
        return code, {"exit_code": code, **_failure_facts("cli_exit", request)}
    # Anything else - a string, an object, a tuple - is one fixed failure, and its value is not
    # formatted, compared or journalled. `cli_exit_unknown` says the code was not a number.
    return EXIT_FAILURE, _failure_facts("cli_exit_unknown", request)


def _cli_main() -> None:
    """The existing CLI, imported at call time so an import failure is a recorded run failure."""
    from codex_harness.cli import main
    main()


def _invoke(cli_args: list[str]) -> tuple[int, dict]:
    """Run the CLI under a scoped argv and answer with its exit code and the facts about it.

    The CLI's arguments reach it exactly as given. `sys.argv` is restored however this ends,
    including for `KeyboardInterrupt` and for anything raised on the way in.
    """
    original = sys.argv
    sys.argv = [CLI_PROGRAM, *cli_args]
    try:
        _cli_main()
    except KeyboardInterrupt as interrupt:
        return EXIT_INTERRUPTED, _failure_facts("interrupted", interrupt)
    except SystemExit as request:
        return _exit_facts(request)
    except BaseException as failure:
        return EXIT_FAILURE, _failure_facts("uncaught_exception", failure)
    else:
        return EXIT_SUCCESS, {"reason": "ok", "exit_code": EXIT_SUCCESS}
    finally:
        sys.argv = original


def _parse(argv: list[str]) -> tuple[str, list[str]] | None:
    """`--journal PATH -- CLI_ARGS`, read by hand so no CLI argument is ever claimed by this side."""
    if len(argv) >= 2 and argv[0] == "--journal":
        journal, rest = argv[1], argv[2:]
    elif argv and argv[0].startswith("--journal="):
        journal, rest = argv[0].partition("=")[2], argv[1:]
    else:
        return None
    if not journal or (rest and rest[0] != "--"):
        return None
    return journal, rest[1:]


def run(journal: str, cli_args: list[str]) -> int:
    """Journal the lifecycle of one CLI run and answer with the exit status described above."""
    run_id = uuid.uuid4().hex
    try:
        book = Journal(journal, logger_name=LOGGER_NAME, fields=ENTRY_FIELDS)
    except (OSError, ValueError, TypeError):
        return EXIT_DIAGNOSTICS_FAILED  # nothing has run, and nothing will
    try:
        # Opening a file is not writing to it. The CLI is started only after the journal has
        # proved it accepts a line, so a run that could not be accounted for never begins.
        try:
            book.write("start", run_id=run_id)
        except KeyboardInterrupt:
            return EXIT_INTERRUPTED
        except BaseException:
            return EXIT_DIAGNOSTICS_FAILED
        return _journalled(book, run_id, cli_args)
    finally:
        book.close()


def _journalled(book: Journal, run_id: str, cli_args: list[str]) -> int:
    code, facts = _invoke(cli_args)
    # A journal that stopped accepting lines cannot report the run it stopped describing: the exit
    # status becomes the owner-side 125, even where the CLI itself said 0 or 7. This differs from
    # `background_service`, which owns a tree and puts 124/130 first; this adapter owns nothing.
    failed = record(book, "finish", run_id=run_id, **facts)
    final = code if failed is None else EXIT_DIAGNOSTICS_FAILED
    reason = facts.get("reason") if failed is None else "diagnostics_failed"
    if record(book, "exit", run_id=run_id, final_exit_code=final, reason=reason) is not None:
        final = EXIT_DIAGNOSTICS_FAILED
    return final


def main(argv: list[str] | None = None) -> int:
    parsed = _parse(list(sys.argv[1:] if argv is None else argv))
    if parsed is None:
        # A fixed line, with no part of the given arguments in it.
        sys.stderr.write(USAGE + "\n")
        return EXIT_DIAGNOSTICS_FAILED
    journal, cli_args = parsed
    return run(journal, cli_args)


if __name__ == "__main__":
    sys.exit(main())
