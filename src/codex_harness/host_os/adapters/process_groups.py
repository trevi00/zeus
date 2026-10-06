"""Owned child processes: the one spawn chokepoint, process-group kill, logged children, spawn observers.

Layer: adapters
Context: host_os
Owns: every child-process creation of the target tree (`popen`, `run`); the POSIX process-group
kill and reap; the spawn-observer registry
Does not own: which process should run (callers), the Windows console/kill primitives
(host_os.adapters.windows.no_console), owned-tree receipts (host_os.adapters.process_tree)
Entry points: popen, run, run_process, run_logged_process, observe_spawns, no_console_kwargs,
python_channel_environment, ProcessCancelled (defined in host_os.ports, S8 V19; imported here), ChokepointProcesses (the host_os.ports.ChildProcesses port)
Contracts: INV-ENCODING-001, INV-HOST-DELIVERY-VERIFY-001

The spawn chokepoint (design §5.3 S1): `popen`/`run` are the only calls in the target tree that
create a process (target/tests/test_spawn_chokepoint.py proves it statically), so a spawn policy -
the R-P provider guard in tests, production isolation later - has exactly one site to hold. They
pass their arguments to `subprocess` unchanged; ownership (process group, kill on failure, observer
announcement) stays with the callers below, exactly as at M7 (`adapters/commands.py`).
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager

from codex_harness.host_os.adapters.windows import no_console
from codex_harness.host_os.ports import ProcessCancelled

# How long a killed logged child may take to be reaped before cleanup reports it as unreaped.
REAP_SECONDS = 10


def python_channel_environment(base: dict | None = None) -> dict:
    """INV-ENCODING-001: a Python child encodes stdin/stdout/stderr exactly as run_process decodes.

    Windows Python otherwise follows the console code page (cp949 here), so a parent-side UTF-8
    decoder alone leaves non-representable text as a child crash or silent corruption. Only the
    stdio channel is bound; PYTHONUTF8 is left alone because it would also change how the child
    decodes other programs' output and file names, which this contract does not own.
    """
    env = dict(os.environ if base is None else base)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def no_console_kwargs(*, process_group: bool = False, creationflags: int = 0,
                      platform: str | None = None) -> dict:
    """Popen keyword arguments for a piped, non-interactive child that must open no console window.

    A console child started from a process without a console (the hidden PowerShell launchers)
    gets a fresh console window unless it is created with CREATE_NO_WINDOW; a captured pipe is not
    a visibility policy. On Windows the returned `creationflags` carries CREATE_NO_WINDOW, the
    caller's extra flags (CREATE_SUSPENDED for the job-object boundary) and, when the caller owns
    the child's group for its own kill path, CREATE_NEW_PROCESS_GROUP. CREATE_NEW_CONSOLE and
    DETACHED_PROCESS are never added: Windows ignores CREATE_NO_WINDOW next to either of them. On
    POSIX no Windows keyword appears at all: `{}` or `{"start_new_session": True}`, unchanged.

    Only for children whose stdio is redirected; a child that inherits the parent's console
    handles would be left with nothing to write to.
    """
    name = os.name if platform is None else platform
    if name == "nt":
        return no_console.creation_kwargs(process_group=process_group, creationflags=creationflags)
    return {"start_new_session": True} if process_group else {}


def popen(argv, **kwargs) -> subprocess.Popen:
    """Create one child process: the target tree's single `subprocess.Popen` call site."""
    return subprocess.Popen(argv, **kwargs)


def run(argv, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` through the chokepoint: the same arguments and the same result."""
    return subprocess.run(argv, **kwargs)


class ChokepointProcesses:
    """The `host_os.ports.ChildProcesses` implementation: `run`/`popen` above with `no_console_kwargs`
    applied, for contexts that may not import this module (S3 container staging and transports)."""

    def run(self, argv, *, process_group: bool = False, **kwargs) -> subprocess.CompletedProcess:
        return run(argv, **no_console_kwargs(process_group=process_group), **kwargs)

    def popen(self, argv, *, process_group: bool = False, **kwargs) -> subprocess.Popen:
        return popen(argv, **no_console_kwargs(process_group=process_group), **kwargs)


_SPAWN_OBSERVERS: list = []
_SPAWN_LOCK = threading.Lock()


@contextmanager
def observe_spawns(callback):
    """Report the pid of every owned child `run_process`/`run_logged_process` creates while active.

    INV-HOST-DELIVERY-VERIFY-001: an owner that must reclaim its children after its OWN death
    records each one durably, exactly when it is created. A callback that raises (its record could
    not be written) gets the child killed before the error propagates, so no unrecorded child runs.
    """
    with _SPAWN_LOCK:
        _SPAWN_OBSERVERS.append(callback)
    try:
        yield
    finally:
        with _SPAWN_LOCK:
            _SPAWN_OBSERVERS.remove(callback)


def _announce(process: subprocess.Popen) -> None:
    """Called inside each caller's kill-on-failure block: a raise here ends the child there."""
    with _SPAWN_LOCK:
        observers = list(_SPAWN_OBSERVERS)
    for callback in observers:
        callback(process.pid)


def _kill_tree(process: subprocess.Popen) -> dict:
    """Kill the child's whole tree: its process group on POSIX, `taskkill /T` on Windows."""
    if os.name == "nt":
        killed = run(no_console.taskkill_argv(process.pid), capture_output=True, timeout=20,
                     **no_console_kwargs())
        return {"method": "taskkill", "exit_code": killed.returncode}
    os.killpg(process.pid, signal.SIGKILL)
    return {"method": "killpg", "exit_code": None}


def run_process(argv: list[str], cwd: str | None = None, timeout: int = 120,
                input_text: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Terminate our own process tree on timeout, including cmd -> node on Windows."""
    process = popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env,
                    **no_console_kwargs(process_group=True))
    try:
        _announce(process)
        stdout, stderr = process.communicate(input_text, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        _kill_tree(process)
        process.communicate()
        raise
    except BaseException:
        # An owner that could not record this child never leaves it running.
        _kill_tree(process)
        process.communicate()
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def _group_gone(pgid: int, seconds: float = 5.0) -> bool:
    """POSIX: True once no process is left in the child's group; False if one outlives `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # a member exists that we may not signal: not gone
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _cleanup(process: subprocess.Popen) -> dict:
    """Kill the tree, reap the child and say whether the descendants are provably gone.

    `descendants_gone` is True only when the POSIX process group is observed empty; Windows
    `taskkill /T` does not enumerate what it killed, so there the answer is None (unknown). When
    the tree kill fails the direct child is killed on its own, and reaping is bounded by
    REAP_SECONDS: a child that survives is reported `reaped: False` instead of hanging the owner
    before its timeout or cancel evidence is written.
    """
    try:
        cleanup = _kill_tree(process)
    except ProcessLookupError:
        cleanup = {"method": "killpg", "exit_code": None}
    except (OSError, subprocess.SubprocessError) as exc:
        cleanup = {"method": "taskkill" if os.name == "nt" else "killpg", "error": type(exc).__name__}
        try:
            process.kill()
            cleanup["fallback"] = "kill"
        except OSError as kill_error:
            cleanup["fallback"] = "kill failed: " + type(kill_error).__name__
    try:
        process.wait(timeout=REAP_SECONDS)
    except subprocess.TimeoutExpired:
        return {**cleanup, "reaped": False, "descendants_gone": None,
                "reason": f"child not reaped within {REAP_SECONDS}s of the kill; descendants unknown"}
    cleanup["reaped"] = True
    if os.name == "nt":
        return {**cleanup, "descendants_gone": None,
                "reason": "taskkill /T does not enumerate descendants; not independently observed"}
    gone = _group_gone(process.pid)
    return {**cleanup, "descendants_gone": True if gone else None,
            "reason": "process group observed empty" if gone else "process group still populated"}


def run_logged_process(argv: list[str], *, stdout_path, stderr_path, cwd: str | None = None,
                       timeout: int = 120, env: dict | None = None) -> dict:
    """Run a child whose stdout/stderr stream straight into owner files, so a deadline keeps them.

    `run_process` holds output in pipes and loses it when the deadline kills the tree. Here the
    child writes the files itself; a timeout kills the tree, reaps the child and returns
    `timed_out` with the cleanup observation instead of raising, and a KeyboardInterrupt does the
    same cleanup before re-raising as ProcessCancelled. On POSIX a group left populated after a
    normal exit is killed too and reported as `stray_descendants`.
    """
    with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
        process = popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout,
                        stderr=stderr, env=env, **no_console_kwargs(process_group=True))
        try:
            _announce(process)
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "timed_out": True, "timeout_seconds": timeout,
                    "cleanup": _cleanup(process)}
        except KeyboardInterrupt:
            raise ProcessCancelled({"exit_code": None, "timed_out": False, "cancelled": True,
                                    "cleanup": _cleanup(process)}) from None
        except BaseException:
            _cleanup(process)
            raise
    observation = {"exit_code": returncode, "timed_out": False}
    if os.name != "nt" and not _group_gone(process.pid, seconds=0):
        observation["stray_descendants"] = True
        observation["cleanup"] = _cleanup(process)
    return observation
