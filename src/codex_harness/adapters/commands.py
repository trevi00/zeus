from __future__ import annotations

import os
import signal
import subprocess


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


def run_process(argv: list[str], cwd: str | None = None, timeout: int = 120,
                input_text: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Terminate our own process tree on timeout, including cmd -> node on Windows."""
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env, **kwargs)
    try:
        stdout, stderr = process.communicate(input_text, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=20)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
