"""Ask one published port the same question from three places, inside one deadline.

Two failures have been recorded against a disposable stack and they are not the same failure:

* the port accepts a connection and PostgreSQL refuses the session - measured, and readiness now
  waits for a real answer instead of an open socket;
* on WSL, `127.0.0.1:<published port>` refuses a connection for the whole 30s bound - never
  reproduced in 24 recorded starts, and its cause is undetermined.

The second one stayed undetermined because every observation of it was taken from one side. A
single "connection refused" cannot tell whether the service never came up, whether the port was
never published, or whether it was published somewhere that side cannot reach. So when readiness
fails, the same port is asked from inside the container, from Windows and from WSL.

Two things this module is careful about, both of which it got wrong before:

**Asking is not answering.** A probe that could not run has observed nothing. `docker exec` failing
because a container is gone, a shell that is not installed, output in a shape this code does not
recognise - none of that is a service refusing a connection, and none of it may narrow anything.
Each vantage therefore reports two separate facts: whether the probe ran and produced a reply in a
form this code accepts, and, only then, what that reply said.

**A deadline that returns is not a deadline that stopped.** One budget covers the container lookup,
the three probes, the context and the finalising. What is returned is a snapshot taken once, so an
answer that arrives late cannot edit a record that has already been handed out or stored - it is
recorded as still running instead.
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

# Why a vantage observed nothing. None of these is a connection result.
NOT_OBSERVED = ("command_failed", "unrecognised_reply", "not_available", "no_container",
                "did_not_finish", "no_budget")

NARROWINGS = {
    "service": "the service in the container was not answering on the container's own port",
    "publication": "the container answered, and the published port did not; the forwarding path "
                   "between them is where this broke",
    "wsl_path": "Windows reached the published port and WSL did not; the route from WSL to that "
                "port is where this broke",
    "all_reachable": "every vantage reached the port during its observation, so whatever refused "
                     "earlier was not refusing while this was taken",
    "undetermined": "at least one vantage observed nothing, so this narrows nothing",
}

# Not measured by this capture. Carried as a reference with its source, kept apart from anything
# this code observed, because it is about the machine it was written on and not about this run.
WSL_REFERENCE = {
    "claim": "WSL2 in NAT mode gives Windows and the distribution different loopbacks, and Docker "
             "Desktop forwards between them, so which side is asked matters",
    "source": "operator observation of this machine, plus Microsoft and Docker networking docs",
    "observed_at": "2026-09-15",
    "note": "reference only; this capture does not measure the networking mode",
}


def _run(argv, seconds):
    """Run a probe command. Says whether it ran at all, separately from what it printed."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=seconds)
    except (OSError, subprocess.SubprocessError):
        return {"ran": False, "why": "command_failed"}
    return {"ran": True, "code": done.returncode, "out": (done.stdout or "").strip()}


def _unobserved(how, why, **detail):
    return {"reachable": None, "observed": False, "how": how, "why": why, **detail}


def _why_not(result):
    """Name why a reply was not an answer, from the exit status and nothing the command printed.

    A command that exited non-zero without a reply this code knows is the command itself failing -
    `docker exec` on a container that is gone, `wsl.exe` that is not installed. A clean exit with an
    unknown reply is something else answering. Neither is a connection result, and the two are named
    apart so a record can never read as "the service refused".
    """
    return "command_failed" if result["code"] != 0 else "unrecognised_reply"


def _tcp_here(port, seconds):
    """This process's own socket. The one vantage whose result needs no interpretation."""
    started = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=seconds):
            return {"reachable": True, "observed": True, "how": "socket from this process",
                    "seconds": round(time.monotonic() - started, 3)}
    except OSError as exc:
        return {"reachable": False, "observed": True, "how": "socket from this process",
                "error": type(exc).__name__, "seconds": round(time.monotonic() - started, 3)}


def _decide(result, how):
    """Only the two words this probe was told to print count as an answer."""
    if not result["ran"]:
        return _unobserved(how, result["why"])
    reply = result["out"].splitlines()[-1].strip() if result["out"] else ""
    if reply == "open":
        return {"reachable": True, "observed": True, "how": how}
    if reply == "shut":
        return {"reachable": False, "observed": True, "how": how}
    return _unobserved(how, _why_not(result), exit_code=result["code"])


def _tcp_from_windows(port, seconds):
    if os.name == "nt":
        return _tcp_here(port, seconds)
    how = "powershell.exe over interop"
    command = (f"$c=New-Object Net.Sockets.TcpClient;"
               f"try{{if($c.ConnectAsync('127.0.0.1',{port}).Wait(2000)){{'open'}}else{{'shut'}}}}"
               f"catch{{'shut'}}finally{{$c.Dispose()}}")
    return _decide(_run(["powershell.exe", "-NoProfile", "-Command", command], seconds), how)


def _tcp_from_wsl(port, seconds):
    if os.name != "nt":
        return _tcp_here(port, seconds)
    how = "wsl.exe"
    probe = f"timeout 2 bash -c '</dev/tcp/127.0.0.1/{port}' && echo open || echo shut"
    return _decide(_run(["wsl.exe", "-e", "bash", "-lc", probe], seconds), how)


def _tcp_in_container(container, service, seconds):
    """Inside the container, over its own loopback, read from the client's own documented replies.

    `docker exec` returning non-zero is not the same as the service refusing. A missing container, a
    daemon that is not answering and a client that is not installed all fail here, and none of them
    is evidence about the database. Only the shapes these clients are documented to print are read
    as answers; anything else is recorded as nothing observed, with a reason and never with the
    command's own error text.
    """
    how = "docker exec"
    inside = "5432" if service == "postgres" else "6379"
    asked = {"asked_port": inside, "of": "the container's own loopback"}
    if not container:
        return _unobserved(how, "no_container", **asked)
    if service == "postgres":
        argv = ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-p", inside]
    else:
        argv = ["docker", "exec", container, "redis-cli", "-h", "127.0.0.1", "-p", inside, "ping"]
    result = _run(argv, seconds)
    if not result["ran"]:
        return _unobserved(how, result["why"], **asked)
    reply = result["out"].splitlines()[-1].strip() if result["out"] else ""
    if service == "postgres":
        # pg_isready prints one of these; anything else came from somewhere that is not pg_isready.
        if reply.endswith("accepting connections"):
            return {"reachable": True, "observed": True, "how": how, **asked}
        for refusal in ("rejecting connections", "no response", "no attempt"):
            if reply.endswith(refusal):
                # The matched form, not the line: even a validated reply is not copied verbatim.
                return {"reachable": False, "observed": True, "how": how, "said": refusal, **asked}
        return _unobserved(how, _why_not(result), exit_code=result["code"], **asked)
    if reply == "PONG":
        return {"reachable": True, "observed": True, "how": how, **asked}
    if reply.endswith("Connection refused"):
        # redis-cli's own wording for a port that would not take it. Nothing looser counts.
        return {"reachable": False, "observed": True, "how": how, "said": "Connection refused",
                **asked}
    return _unobserved(how, _why_not(result), exit_code=result["code"], **asked)


def context(seconds):
    """Where this is being asked from. Nothing here is a measurement of the networking mode."""
    kernel = ""
    try:
        with open("/proc/sys/kernel/osrelease", encoding="utf-8") as stream:
            kernel = stream.read().strip()
    except OSError:
        kernel = ""
    docker_context = None
    if seconds > 0:
        result = _run(["docker", "context", "show"], seconds)
        docker_context = result["out"] if result["ran"] and result["code"] == 0 else None
    return {"platform": sys.platform, "kernel": kernel, "docker_context": docker_context,
            "docker_host_set": bool(os.environ.get("DOCKER_HOST")),
            "wsl_networking_mode": "not measured by this capture",
            "reference": dict(WSL_REFERENCE)}


def narrow(observations):
    """Name the segment the answers point at - and only when every vantage actually answered."""
    answers = {name: observations.get(name, {}).get("reachable") for name in VANTAGES}
    if any(answer is None for answer in answers.values()):
        return "undetermined"
    if answers["container"] is False:
        return "service"
    if answers["windows"] is False:
        return "publication"
    if answers["wsl"] is False:
        return "wsl_path"
    return "all_reachable"


def observe(port, *, service, container=None, container_lookup=None, seconds=CAPTURE_SECONDS,
            failed_at=None):
    """Ask all three inside one budget, and hand back a snapshot that cannot change afterwards.

    The three are started together so their observation windows overlap. That is not the same as
    one atomic instant, and this does not claim to be: every vantage records when its own look
    started and ended, and the verdict is about those windows rather than about a single moment.
    """
    started = time.monotonic()
    deadline = started + seconds
    lookup = {"seconds": 0.0, "found": bool(container)}
    if container is None and container_lookup is not None:
        # Inside the budget, because a lookup that hangs is time the caller spends too.
        at = time.monotonic()
        try:
            container = container_lookup(max(0.0, deadline - at))
        except Exception:
            container = None
        lookup = {"seconds": round(time.monotonic() - at, 3), "found": bool(container)}

    live = {}
    guard = threading.Lock()
    workers = []

    def ask(name, probe):
        def run():
            began = round(time.monotonic() - started, 3)
            try:
                record = probe()
            except Exception as exc:
                record = _unobserved("probe", "command_failed", error=type(exc).__name__)
            record["looked_from"] = began
            record["looked_until"] = round(time.monotonic() - started, 3)
            with guard:
                live[name] = record
        worker = threading.Thread(target=run, daemon=True, name=f"port-diagnosis-{name}-{port}")
        worker.start()
        workers.append((name, worker))

    probe_bound = min(PROBE_SECONDS, max(0.0, deadline - time.monotonic()))
    if probe_bound > 0:
        ask("container", lambda: _tcp_in_container(container, service, probe_bound))
        ask("windows", lambda: _tcp_from_windows(port, probe_bound))
        ask("wsl", lambda: _tcp_from_wsl(port, probe_bound))
        for _, worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))
    else:
        # The budget was gone before a single probe could start. Asking with no time at all would
        # make a socket refuse instantly and a command fail instantly, and either would be written
        # down as an answer. Nothing was observed here, and that is what is recorded.
        with guard:
            for name in VANTAGES:
                live[name] = _unobserved("probe", "no_budget")

    where = context(max(0.0, deadline - time.monotonic()))

    # One snapshot, taken once. A worker that answers after this writes into `live`, which is not
    # what was returned, so a record already handed out or stored cannot be edited underneath it.
    with guard:
        observations = {name: dict(record) for name, record in live.items()}
    unfinished = [name for name, worker in workers if worker.is_alive()]
    for name in VANTAGES:
        observations.setdefault(name, _unobserved("probe", "did_not_finish"))
    verdict = narrow(observations)
    return {"port": port, "service": service, "observations": observations, "verdict": verdict,
            "means": NARROWINGS[verdict], "context": where,
            "container_lookup": lookup,
            "deadline_seconds": seconds,
            "seconds": round(time.monotonic() - started, 3),
            "still_running": unfinished,
            "delay_from_failure_seconds": (round(started - failed_at, 3)
                                           if failed_at is not None else None),
            "note": "three overlapping observation windows, not one instant; a vantage that "
                    "observed nothing never narrows anything, and probes still running at the "
                    "deadline cannot change this record"}
