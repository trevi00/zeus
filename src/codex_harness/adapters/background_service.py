"""The owner of a background service tree: what it starts, it also ends.

The scheduled-task entry used to start its service with `subprocess.run`, which owns a process and
nothing that process starts. Killing that Python owner left the hidden PowerShell and everything
under it running: six such descendants survived prior restarts and kept holding the collector lock
that the next start needs (docs/zeus/operations/service-ownership-001/SPEC.md).

`run_owned` is the missing owner, and it is the existing `ProcessTree` used unchanged rather than a
second ownership mechanism. On Windows the tree is a job object with KILL_ON_JOB_CLOSE and this
process holds the only handle to it, so even an owner that is terminated outright ends the tree:
the OS closes the last handle. On POSIX the boundary is the session's process group, which is
weaker and is documented as such - after SIGKILL of this owner nothing is left running to signal
the group, and a descendant that calls `setsid` has already left it. Neither limit is claimed away.

The exit status is the report:

| answer | meaning                                                                      |
|--------|------------------------------------------------------------------------------|
| child  | the child's own code, only after the tree was confirmed gone                  |
| 124    | cleanup could not be confirmed; takes precedence over every other answer      |
| 125    | an owner-side failure: start, wait or journal                                 |
| 130    | KeyboardInterrupt reached the owner                                           |
| 143    | POSIX SIGTERM reached the owner                                               |

The journal is a rotating JSONL file of facts an operator may read in the open: an event name, a
timestamp, the child's pid, exit codes, whether cleanup was confirmed and the class name of a
failure. Never the command line, the environment, exception text or a raw termination receipt. A
journal that cannot be opened starts nothing, and neither does one that opens but refuses its
first line: opening a file is not writing to it, so the `starting` receipt is written before the
spawn and a run nobody can account for never begins. A journal that stops accepting writes later
cannot skip the cleanup and cannot report success.

A POSIX SIGTERM is recorded, not raised. A handler that unwinds can arrive in the middle of
acquiring the ownership object - between the process existing and this owner holding the tree that
represents it - and that answer is a 143 beside a live child, which is the orphan this module
exists to prevent. So the handler only sets a flag, the wait polls in finite steps so a sleeping
service is still stopped promptly, and the acquired tree is always reclaimed before 143 is
returned. SIGKILL and a descendant that calls `setsid` remain outside the promise.

The last line the owner writes is `shutdown`. Its absence is not evidence that cleanup failed: an
owner killed outright never reaches it, and on Windows what ends the tree then is the OS closing
the job handle, which nothing on this side is alive to observe. `cleanup` and `shutdown` are this
owner's own observations; they are not the operating system's.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from codex_harness.adapters.process_tree import ProcessTree, TreeOwnershipLeak

# Exit contract (SPEC "Fixed acceptance matrix"): 124 outranks the rest, because an unproven tree
# is the one thing that must never be reported as any kind of finished run.
EXIT_CLEANUP_UNCONFIRMED = 124
EXIT_OWNER_ERROR = 125
EXIT_INTERRUPTED = 130
EXIT_SIGTERM = 143

# ProcessTree's own finite waits, kept finite here: terminate then settle, nothing unbounded.
TERMINATE_TIMEOUT, SETTLE_TIMEOUT = 5.0, 5.0
# How long one step of the child wait blocks, so a recorded stop is acted on without an unwind.
WAIT_POLL = 0.2

LOG_BYTES, LOG_BACKUPS = 1024 * 1024, 2
LOGGER_NAME = "zeus.background_service"
# The complete allowlist of facts. Anything else a caller passes is dropped rather than sanitized,
# so a new field cannot leak a command line or a secret by being added somewhere else.
LOG_FIELDS = frozenset({"pid", "child_exit_code", "final_exit_code", "cleanup_confirmed",
                        "error_type"})
LOG_VALUE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class JournalWriteError(RuntimeError):
    """A journal line did not reach the file. Carries the failing class name only, never its text."""


class _Pending:
    """A stop that was recorded, not raised.

    The signal handler writes one attribute and returns; nothing unwinds out of a signal, so no
    stop can arrive in the middle of a spawn, a handoff, a cleanup or the final journal entries.
    """

    def __init__(self):
        self.stop_code: int | None = None

    def observed(self) -> int | None:
        return self.stop_code


def _write_failed(record):
    """Logging's default is to print a warning and carry on; a dropped receipt is not acceptable."""
    failure = sys.exc_info()[1]
    if isinstance(failure, JournalWriteError):
        raise failure  # the rotating handler asks twice for one failure; keep the original name
    raise JournalWriteError(type(failure).__name__ if failure is not None else "Unknown")


class _Journal:
    """Rotating JSONL (1 MiB, two backups), one owner run per process."""

    def __init__(self, path):
        handler = RotatingFileHandler(str(path), maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.handleError = _write_failed
        self.logger = logging.getLogger(LOGGER_NAME)
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        for old in list(self.logger.handlers):
            self.logger.removeHandler(old)
            old.close()
        self.logger.addHandler(handler)
        self.handler = handler

    def write(self, event: str, **fields) -> None:
        safe = {key: value for key, value in fields.items() if key in LOG_FIELDS and (
            value is None or isinstance(value, bool) or type(value) is int
            or (isinstance(value, str) and LOG_VALUE.fullmatch(value)))}
        self.logger.info(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                                     "event": event, **safe}, sort_keys=True))

    def close(self) -> None:
        self.logger.removeHandler(self.handler)
        try:
            self.handler.close()
        except OSError:
            pass


def _record(book: _Journal, event: str, **fields) -> str | None:
    """Write a shutdown-path entry; answer with the failure's class name instead of raising.

    Nothing on the way out may be skipped because the journal broke, and nothing on the way out may
    pretend the journal worked either, so the failure is carried back to the exit status.
    """
    try:
        book.write(event, **fields)
    except BaseException as failure:  # including a second interrupt during the final entries
        return type(failure).__name__
    return None


@contextmanager
def _posix_sigterm():
    """Record SIGTERM in a flag; POSIX main thread only, previous handler restored on the way out.

    Yields the flag to watch, or `None` where nothing is installed: on Windows, off the main thread
    (`signal.signal` is main-thread only), and where the platform refuses the handler. In those
    cases the run proceeds unchanged and the POSIX stop is simply not promised.
    """
    if os.name == "nt" or threading.current_thread() is not threading.main_thread():
        yield None
        return
    pending = _Pending()

    def handle(signum, frame):
        pending.stop_code = EXIT_SIGTERM  # recorded here, acted on by the owner's own code

    try:
        previous = signal.signal(signal.SIGTERM, handle)
    except (ValueError, OSError):
        yield None
        return
    try:
        yield pending
    finally:
        try:
            signal.signal(signal.SIGTERM, previous)
        except (ValueError, OSError):
            pass


def _release(tree: ProcessTree) -> tuple[bool, str | None]:
    """End the tree within finite waits and close the owned handle whatever terminate did.

    On Windows the close is the kill-on-close boundary itself, so it is attempted even after a
    terminate that failed or was itself interrupted. The confirmation reported here is the one
    `terminate` gave: closing the handle afterwards ends members, but leaves nothing to observe.
    """
    confirmed, error = False, None
    try:
        receipt = tree.terminate("the owner is ending the background service tree",
                                 timeout=TERMINATE_TIMEOUT, settle=SETTLE_TIMEOUT)
        confirmed = bool(receipt.get("confirmed"))
    except BaseException as failure:
        error = type(failure).__name__
    finally:
        try:
            tree.close()
        except BaseException as failure:
            error = error or type(failure).__name__
    return confirmed, error


def _await_child(process, pending: _Pending | None) -> int | None:
    """The child's exit code, or `None` when a recorded stop is to be answered instead.

    With nothing to watch this is one blocking wait and no wakeups. With a flag to watch it is the
    same wait in finite steps, so a service that is asleep for ten minutes is still stopped within
    one step of the signal rather than at the end of its sleep.
    """
    if pending is None:
        return process.wait()
    while pending.observed() is None:
        try:
            return process.wait(timeout=WAIT_POLL)
        except subprocess.TimeoutExpired:
            continue
    return None


def _final_code(*, confirmed: bool, stop_code: int | None, error_type: str | None,
                child_exit_code: int | None) -> int:
    if not confirmed:
        return EXIT_CLEANUP_UNCONFIRMED
    if stop_code is not None:
        return stop_code
    if error_type is not None or child_exit_code is None:
        return EXIT_OWNER_ERROR
    return child_exit_code


def run_owned(argv: list[str], *, cwd: str | None = None, env: dict | None = None,
              journal: str | os.PathLike) -> int:
    """Start `argv` as an owned tree, wait for it, and end everything it started before returning.

    `journal` is the path of the rotating JSONL receipt described in the module docstring. The
    child's stdin, stdout and stderr go to DEVNULL: the service launchers own their output logs,
    and a pipe nobody reads is a place for a background service to stop.
    """
    try:
        book = _Journal(journal)
    except (OSError, ValueError, TypeError):
        return EXIT_OWNER_ERROR  # nothing has been started, and nothing will be
    try:
        # A journal that opened is not yet a journal that writes. This line is the proof, and it is
        # taken before anything exists to account for: a failure here is 125 with zero spawns.
        try:
            book.write("starting")
        except KeyboardInterrupt:
            return EXIT_INTERRUPTED
        except BaseException:
            return EXIT_OWNER_ERROR
        with _posix_sigterm() as pending:
            return _own(argv, cwd=cwd, env=env, book=book, pending=pending)
    finally:
        book.close()


def _own(argv, *, cwd, env, book: _Journal, pending: _Pending | None) -> int:
    try:
        tree = ProcessTree.spawn(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except KeyboardInterrupt:
        _record(book, "start_interrupted", error_type="KeyboardInterrupt")
        return EXIT_INTERRUPTED
    except TreeOwnershipLeak as leak:
        # spawn's own cleanup could not prove the process it created is gone. A second start would
        # add a second one to whatever the first one is, so there is no retry here, ever.
        _record(book, "start_leaked", cleanup_confirmed=False, error_type=type(leak).__name__)
        return EXIT_CLEANUP_UNCONFIRMED
    except BaseException as failure:
        _record(book, "start_failed", error_type=type(failure).__name__)
        return EXIT_OWNER_ERROR

    released: dict = {}
    stop_code: int | None = None
    error_type: str | None = None
    child_exit_code: int | None = None
    try:
        book.write("startup", pid=tree.process.pid)
        # A signal that arrived while the tree was being acquired is answered here, with the tree
        # in hand, and never as a 143 returned beside a child nobody owns.
        child_exit_code = None if (pending and pending.observed()) else _await_child(tree.process,
                                                                                    pending)
        if child_exit_code is None:
            stop_code, error_type = EXIT_SIGTERM, "SIGTERM"
        else:
            book.write("child_exited", child_exit_code=child_exit_code)
    except KeyboardInterrupt:
        stop_code, error_type = EXIT_INTERRUPTED, "KeyboardInterrupt"
    except BaseException as failure:  # a wait or a journal write that failed still owns a tree
        error_type = type(failure).__name__
    finally:
        released["confirmed"], released["error"] = _release(tree)

    confirmed, cleanup_error = released["confirmed"], released["error"]
    journal_error = _record(book, "cleanup", cleanup_confirmed=confirmed, error_type=cleanup_error)
    error_type = error_type or cleanup_error or journal_error
    final = _final_code(confirmed=confirmed, stop_code=stop_code, error_type=error_type,
                        child_exit_code=child_exit_code)
    shutdown_error = _record(book, "shutdown", child_exit_code=child_exit_code,
                             final_exit_code=final, cleanup_confirmed=confirmed,
                             error_type=error_type)
    if shutdown_error:
        # The final entry never reached the file, so this run is an owner-side failure whatever the
        # child said: a 7 with no receipt is not a reported 7. The same precedence still decides,
        # so an unproven tree stays 124 and a deliberate stop stays 130/143.
        final = _final_code(confirmed=confirmed, stop_code=stop_code,
                            error_type=error_type or shutdown_error,
                            child_exit_code=child_exit_code)
    return final
