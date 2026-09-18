from __future__ import annotations

import os
import signal
import subprocess

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


def run_process(argv: list[str], cwd: str | None = None, timeout: int = 120,
                input_text: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Terminate our own process tree on timeout, including cmd -> node on Windows."""
    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env,
                               **no_console_kwargs(process_group=True))
    try:
        stdout, stderr = process.communicate(input_text, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=20, **no_console_kwargs())
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
