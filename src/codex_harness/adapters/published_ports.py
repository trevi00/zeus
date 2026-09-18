"""Choose the host port a disposable stack publishes, and say which sides were actually checked.

Symptom A - `127.0.0.1:<published port>` refusing a connection from inside WSL while the container is
up and Windows reaches it - was reproduced, and the reproduction's mechanism was read off the socket
tables on both sides (`docs/zeus/implementation/wsl-port-001/README.md`): Docker Desktop's WSL
integration binds a published port inside an integrated distro once, at container start. In that
experiment the bind did not happen while the distro held the port, and no retry was observed for the
30s the port was watched, nor after the occupant let go; a container restart is what produced a
`LISTEN` socket there.

**Two sides, and they are not symmetric.** Measured, not assumed
(`docs/zeus/evidence/wsl-port-001/*-daemon-bind-directions.json`):

* a port held on the **Windows** side makes the daemon refuse to publish - exit 125, naming the port.
  Loud, and nothing here has to predict it.
* a port held inside the **distro** lets the publish succeed and leaves the port unreachable from
  inside the distro. Silent. This is the one worth checking before choosing.

The first version of this module checked neither of those. It bound the candidate on whichever host
happened to be running, and called that "free" - so a choice made on Windows said nothing about the
distro, which is exactly where the failing bind happens. Codex's counterexample held 24000 inside
Ubuntu and got 24000 back from Windows.

So every answer here carries its own scope. A side that was asked is recorded with how it was asked;
a side that could not be asked is recorded as not asked, and is never counted as free. `verified_on`
names the sides the choice actually stands on, and nothing here claims a port is free everywhere.
"""
from __future__ import annotations

import os
import random
import socket
import subprocess

from codex_harness.adapters.commands import no_console_kwargs

# The window to choose from: above the well-known and registered service ranges, and below the lowest
# ephemeral start this code can establish for the sides it can see.
FLOOR = 20000
LINUX_DEFAULT_EPHEMERAL_START = 32768
TRIES = 60
PEER_SECONDS = 20.0


def _run(argv, seconds):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=seconds, **no_console_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    return done


def here():
    """Which side of this machine this process is on, named rather than guessed at."""
    if os.name == "nt":
        return "windows"
    try:
        with open("/proc/sys/kernel/osrelease", encoding="utf-8") as stream:
            release = stream.read().lower()
    except OSError:
        return "posix"
    return "wsl" if "microsoft" in release else "linux"


def ephemeral_start():
    """Where outbound local ports start here, and whether that was read or assumed.

    Only a Linux kernel answers this through /proc. On Windows the Linux default is assumed, and it
    is the lower of the two starts (Windows begins at 49152), so assuming it keeps the window below
    both. The source travels with the number so a receipt never shows an assumption as a reading.
    """
    try:
        with open("/proc/sys/net/ipv4/ip_local_port_range", encoding="utf-8") as stream:
            first = int(stream.read().split()[0])
        return min(LINUX_DEFAULT_EPHEMERAL_START, first), "measured:/proc/sys/net/ipv4/ip_local_port_range"
    except (OSError, ValueError, IndexError):
        return LINUX_DEFAULT_EPHEMERAL_START, "assumed:linux-default-32768"


def window():
    """(low, high, source), or None when there is no room below the ephemeral start."""
    start, source = ephemeral_start()
    high = start - 1
    if high < FLOOR:
        return None
    return FLOOR, high, source


def daemon_is_local():
    """Whether the daemon publishes on this machine, as far as this can be established.

    `DOCKER_HOST` pointing elsewhere means a port being free here says nothing about the host the
    daemon binds on. That topology is out of scope and is reported as such rather than mitigated.
    """
    host = os.environ.get("DOCKER_HOST", "").strip()
    if not host:
        return True
    return host.startswith("unix://") or host.startswith("npipe://")


def _peer_ports():
    """Every port the other side is holding, when there is another side and it can be asked.

    From Windows the other side is the WSL distro, and `ss` there lists sockets in every state -
    including the bound-but-not-listening kind an outbound socket leaves, which is the shape the
    failing occupant has. From inside WSL the other side is Windows, which needs no prediction: an
    occupant there makes the daemon refuse to publish outright.
    """
    side = here()
    if side == "windows":
        done = _run(["wsl.exe", "-e", "sh", "-c",
                     'printf "%s\\n" "${WSL_DISTRO_NAME:-unknown}"; ss -Htan'], PEER_SECONDS)
        if done is None or done.returncode != 0:
            return {"kind": "wsl:unknown", "checked": False, "busy": None,
                    "why_not": "command_failed"}
        lines = (done.stdout or "").splitlines()
        if not lines:
            return {"kind": "wsl:unknown", "checked": False, "busy": None,
                    "why_not": "unrecognised_reply"}
        distro, rows = lines[0].strip() or "unknown", lines[1:]
        busy = set()
        for row in rows:
            fields = row.split()
            if len(fields) < 4:
                continue
            local = fields[3].rsplit(":", 1)
            if len(local) == 2 and local[1].isdigit():
                busy.add(int(local[1]))
        return {"kind": f"wsl:{distro}", "checked": True, "busy": busy,
                "how": "socket table over wsl.exe (ss -Htan, every state)"}
    if side == "wsl":
        # Measured: an occupant on the Windows side makes `docker run` exit 125 and name the port,
        # so this direction is answered by the publish itself rather than by a guess made here.
        return {"kind": "windows", "checked": False, "busy": None,
                "why_not": "answered_by_the_daemon_refusing_to_publish"}
    return {"kind": "none", "checked": False, "busy": None, "why_not": "no_second_side"}


def choose(count, *, rng=None):
    """Pick `count` distinct ports, and report exactly which sides that rests on.

    Candidates are bound here to prove them free here, and held until the whole set is found so this
    cannot hand back the same port twice. Where the other side can be asked, a candidate it is
    holding is skipped as well. They are released together just before the stack is written, which
    leaves a gap between proving a port free and the daemon taking it; that gap is not closed here,
    and a failure in it is what the readiness diagnosis is for.

    `ports` is None when nothing was chosen, and `fallback` says which reason it was. That is not a
    failure: the caller falls back to the daemon's own choice, which is what every run did before.
    """
    span = window()
    if not daemon_is_local():
        return {"ports": None, "window": None, "window_source": None,
                "sides": {"local": {"kind": here(), "checked": False,
                                    "why_not": "daemon_publishes_elsewhere"},
                          "peer": {"kind": "unknown", "checked": False,
                                   "why_not": "daemon_publishes_elsewhere"}},
                "verified_on": [], "daemon_is_local": False, "guarantee": "none",
                "fallback": "daemon_not_local"}
    if span is None or count <= 0:
        return {"ports": None, "window": None,
                "window_source": ephemeral_start()[1],
                "sides": {"local": {"kind": here(), "checked": False, "why_not": "no_window"},
                          "peer": {"kind": "unknown", "checked": False, "why_not": "no_window"}},
                "verified_on": [], "daemon_is_local": True, "guarantee": "none",
                "fallback": "no_window"}

    low, high, source = span
    peer = _peer_ports()
    peer_busy = peer["busy"] if peer["checked"] else set()
    picker = rng or random.Random()
    picked, held = [], []
    try:
        for _ in range(TRIES):
            if len(picked) == count:
                break
            candidate = picker.randint(low, high)
            if candidate in picked or candidate in peer_busy:
                continue
            probe = socket.socket()
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                probe.close()
                continue
            held.append(probe)
            picked.append(candidate)
    finally:
        for probe in held:
            probe.close()

    verified = ["local"] + (["peer"] if peer["checked"] else [])
    return {"ports": picked if len(picked) == count else None,
            "window": [low, high], "window_source": source,
            "sides": {"local": {"kind": here(), "checked": True, "how": "bind"},
                      "peer": {key: value for key, value in peer.items() if key != "busy"}},
            "verified_on": verified,
            "daemon_is_local": True,
            "guarantee": "checked_before_choosing_on: " + ", ".join(verified),
            "fallback": None if len(picked) == count else "candidates_exhausted"}


def publication(chosen, inside):
    """How to write one published port in a compose spec, for a chosen port or for the daemon's."""
    return f"127.0.0.1:{chosen}:{inside}" if chosen else f"127.0.0.1::{inside}"
