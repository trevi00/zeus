"""Ask one published port the same question from three places at the same moment.

Two failures have been recorded against a disposable stack and they are not the same failure:

* the port accepts a connection and PostgreSQL refuses the session - measured, and the readiness
  check now waits for a real answer instead of an open socket;
* on WSL, `127.0.0.1:<published port>` refuses a connection for the whole 30s bound - never
  reproduced in 24 recorded starts, and its cause is undetermined.

The second one has stayed undetermined for a reason: every observation of it was taken from one
side. A single "connection refused" cannot tell whether the database never came up, whether the
port was never published, or whether it was published somewhere this side cannot reach. On this
machine WSL runs in NAT mode, where the two localhosts are not the same thing and Docker Desktop
does its own forwarding, so "which side" is exactly the question.

So when readiness fails, the same port is asked from all three vantages at once:

    inside the container · from Windows · from WSL

and what comes back narrows it:

    container fails                     -> the service itself
    container answers, Windows does not -> publication and the forwarding path
    Windows answers, WSL does not       -> the path from WSL to that port

This diagnoses; it does not retry, and it never widens a deadline. A vantage that cannot be asked
from here says so, and that is recorded as not asked rather than as a failure.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time

VANTAGES = ("container", "windows", "wsl")
PROBE_SECONDS = 3.0
CAPTURE_SECONDS = 10.0

# What each verdict means, in the words of the thing it points at.
NARROWINGS = {
    "service": "the service in the container was not answering on the container's own port",
    "publication": "the container answered, and the published port did not; the forwarding path "
                   "between them is where this broke",
    "wsl_path": "Windows reached the published port and WSL did not; the route from WSL to that "
                "port is where this broke",
    "all_reachable": "every vantage reached the port at this moment, so whatever refused earlier "
                     "was not refusing when this was taken",
    "undetermined": "not enough vantages could be asked to narrow it",
}


def _run(argv, seconds):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=seconds)
        return done.returncode, (done.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return None, ""


def _tcp_here(port, seconds):
    started = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=seconds):
            return {"reachable": True, "how": "socket from this process",
                    "seconds": round(time.monotonic() - started, 3)}
    except OSError as exc:
        return {"reachable": False, "how": "socket from this process", "error": type(exc).__name__,
                "seconds": round(time.monotonic() - started, 3)}


def _tcp_from_windows(port, seconds):
    """From the Windows side, directly when this is Windows and over interop when it is not."""
    if os.name == "nt":
        return _tcp_here(port, seconds)
    command = (f"$c=New-Object Net.Sockets.TcpClient;"
               f"try{{if($c.ConnectAsync('127.0.0.1',{port}).Wait(2000)){{'open'}}else{{'shut'}}}}"
               f"catch{{'shut'}}finally{{$c.Dispose()}}")
    code, output = _run(["powershell.exe", "-NoProfile", "-Command", command], seconds)
    if code is None:
        return {"reachable": None, "how": "powershell.exe over interop", "asked": False,
                "note": "Windows could not be asked from here"}
    return {"reachable": output.strip().endswith("open"), "how": "powershell.exe over interop",
            "asked": True}


def _tcp_from_wsl(port, seconds):
    """From the WSL side, directly when this is Linux and through wsl.exe when it is not."""
    if os.name != "nt":
        return _tcp_here(port, seconds)
    probe = f"timeout 2 bash -c '</dev/tcp/127.0.0.1/{port}' && echo open || echo shut"
    code, output = _run(["wsl.exe", "-e", "bash", "-lc", probe], seconds)
    if code is None:
        return {"reachable": None, "how": "wsl.exe", "asked": False,
                "note": "WSL could not be asked from here"}
    return {"reachable": output.strip().endswith("open"), "how": "wsl.exe", "asked": True}


def _tcp_in_container(container, service, seconds):
    """Inside the container, over its own loopback, using the service's own client."""
    if not container:
        return {"reachable": None, "how": "docker exec", "asked": False,
                "note": "the container id was not known"}
    inside = "5432" if service == "postgres" else "6379"
    if service == "postgres":
        argv = ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-p", inside]
    else:
        argv = ["docker", "exec", container, "redis-cli", "-h", "127.0.0.1", "-p", inside, "ping"]
    code, output = _run(argv, seconds)
    # This vantage asks about the service's own port inside the container, not the published one -
    # the published number does not exist in there. It answers "is the service up", and the other
    # two answer "can this side reach it".
    asked_port = {"asked_port": inside, "of": "the container's own loopback"}
    if code is None:
        return {"reachable": None, "how": "docker exec", "asked": False, **asked_port,
                "note": "the container could not be asked"}
    return {"reachable": code == 0, "how": "docker exec", "asked": True, **asked_port,
            "answer": output.splitlines()[-1][:80] if output else ""}


def context():
    """Where this is being asked from. None of it is a secret and none of it is a measurement."""
    kernel = ""
    try:
        with open("/proc/sys/kernel/osrelease", encoding="utf-8") as stream:
            kernel = stream.read().strip()
    except OSError:
        kernel = ""
    code, docker_context = _run(["docker", "context", "show"], 5.0)
    return {"platform": sys.platform, "kernel": kernel,
            "docker_context": docker_context if code == 0 else None,
            "docker_host": bool(os.environ.get("DOCKER_HOST")),
            "note": "on this machine WSL is in NAT mode, where the two loopbacks are different "
                    "networks and Docker Desktop forwards between them"}


def narrow(observations):
    """Name the segment the three answers point at, or say they do not point anywhere."""
    container = observations.get("container", {}).get("reachable")
    windows = observations.get("windows", {}).get("reachable")
    wsl = observations.get("wsl", {}).get("reachable")
    if container is False:
        return "service"
    if container is True and windows is False:
        return "publication"
    if windows is True and wsl is False:
        return "wsl_path"
    if container is True and windows is True and wsl is True:
        return "all_reachable"
    return "undetermined"


def observe(port, *, service, container=None, seconds=CAPTURE_SECONDS):
    """Ask all three at once, so the answers describe one moment rather than three.

    They run together on purpose. Asked in turn, a port that opens midway through would answer
    differently to the first and the last, and the difference would look like a place rather than a
    time.
    """
    started = time.monotonic()
    observations, threads = {}, []

    def ask(name, probe):
        def run():
            try:
                observations[name] = probe()
            except Exception as exc:   # a vantage that breaks is a vantage that was not asked
                observations[name] = {"reachable": None, "asked": False,
                                      "error": type(exc).__name__}
        worker = threading.Thread(target=run, daemon=True, name=f"port-diagnosis-{name}")
        worker.start()
        threads.append(worker)

    ask("container", lambda: _tcp_in_container(container, service, PROBE_SECONDS))
    ask("windows", lambda: _tcp_from_windows(port, PROBE_SECONDS))
    ask("wsl", lambda: _tcp_from_wsl(port, PROBE_SECONDS))
    deadline = started + seconds
    for worker in threads:
        worker.join(max(0.0, deadline - time.monotonic()))
    for name in VANTAGES:
        observations.setdefault(name, {"reachable": None, "asked": False,
                                       "note": "this vantage did not answer inside the capture bound"})
    verdict = narrow(observations)
    return {"port": port, "service": service, "observations": observations, "verdict": verdict,
            "means": NARROWINGS[verdict], "seconds": round(time.monotonic() - started, 2),
            "context": context(),
            "note": "one moment, three vantages; this narrows where a refusal happened and "
                    "diagnoses nothing on its own"}
