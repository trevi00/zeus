from __future__ import annotations

import os
import signal
import subprocess
import time

# Win32 creation flags by value: `subprocess` exposes them only on Windows, and the helper below
# has to be able to describe the Windows policy from a Linux test.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


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
        flags = CREATE_NO_WINDOW | creationflags
        if process_group:
            flags |= CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags}
    return {"start_new_session": True} if process_group else {}


def _kill_tree(process: subprocess.Popen) -> dict:
    """Kill the child's whole tree: its process group on POSIX, `taskkill /T` on Windows."""
    if os.name == "nt":
        killed = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True, timeout=20, **no_console_kwargs())
        return {"method": "taskkill", "exit_code": killed.returncode}
    os.killpg(process.pid, signal.SIGKILL)
    return {"method": "killpg", "exit_code": None}


def run_process(argv: list[str], cwd: str | None = None, timeout: int = 120,
                input_text: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Terminate our own process tree on timeout, including cmd -> node on Windows."""
    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env,
                               **no_console_kwargs(process_group=True))
    try:
        stdout, stderr = process.communicate(input_text, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        _kill_tree(process)
        process.communicate()
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


class ProcessCancelled(KeyboardInterrupt):
    """A logged child interrupted by the owner; `observation` says what cleanup could prove."""

    def __init__(self, observation: dict):
        super().__init__("process cancelled")
        self.observation = observation


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
    `taskkill /T` does not enumerate what it killed, so there the answer is None (unknown).
    """
    try:
        cleanup = _kill_tree(process)
    except ProcessLookupError:
        cleanup = {"method": "killpg", "exit_code": None}
    except (OSError, subprocess.SubprocessError) as exc:
        cleanup = {"method": "taskkill" if os.name == "nt" else "killpg", "error": type(exc).__name__}
    process.wait()
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
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout,
                                   stderr=stderr, env=env, **no_console_kwargs(process_group=True))
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "timed_out": True, "timeout_seconds": timeout,
                    "cleanup": _cleanup(process)}
        except KeyboardInterrupt:
            raise ProcessCancelled({"exit_code": None, "timed_out": False, "cancelled": True,
                                    "cleanup": _cleanup(process)}) from None
    observation = {"exit_code": returncode, "timed_out": False}
    if os.name != "nt" and not _group_gone(process.pid, seconds=0):
        observation["stray_descendants"] = True
        observation["cleanup"] = _cleanup(process)
    return observation
