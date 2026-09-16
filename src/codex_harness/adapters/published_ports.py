"""Choose the host port a disposable stack publishes, instead of letting the daemon pick it.

Symptom A, from the ledger: inside WSL, `127.0.0.1:<published port>` refuses a connection for the
whole 30s readiness bound while the container is up and Windows reaches it. Seven occurrences were
recorded, all on WSL, all in the disposable-docker step. It is now reproduced on demand and the
mechanism is measured (`docs/zeus/implementation/wsl-port-001/README.md`):

* Docker Desktop's WSL integration serves a published port inside an integrated distro by binding
  `127.0.0.1:<port>` **there**, once, when the container starts.
* If anything in the distro already holds that port number at that moment, the bind does not happen
  and is never retried. Nothing listens, so the distro gets ECONNREFUSED - for the container's whole
  life, not for a moment. Restarting the container is what makes the relay try again.
* The occupant in the recorded failures could only have been the distro's own ephemeral allocator.
  The daemon draws the published port from the Windows dynamic range (49152-65535); the distro draws
  outbound local ports from `ip_local_port_range`, 32768-60999 by default. Ports 49152-60999 are
  therefore drawn from by both, and all seven recorded occurrences landed in that overlap.

So the port is chosen here, from a window no ephemeral allocator on this host draws from. This does
not make a collision impossible - a program can still bind any port explicitly - and it is not a
claim that every unreachable-port story is this one. It takes the case that actually happened off
the table, and the case that actually happened is the one that was costing runs.
"""
from __future__ import annotations

import random
import socket

# The window to choose from: high enough to be out of the well-known and service ranges, and below
# the lowest ephemeral start this code knows about (Linux defaults to 32768, Windows to 49152).
FLOOR = 20000
LINUX_DEFAULT_EPHEMERAL_START = 32768
TRIES = 60


def ephemeral_start():
    """Where this host starts handing out outbound local ports, as far as it can be read.

    Only Linux answers this cheaply and honestly, through /proc - and Linux is the side that matters,
    because the distro is where the failing bind happens. Elsewhere the Linux default is assumed,
    which is the lower of the two starts and so the safer assumption.
    """
    try:
        with open("/proc/sys/net/ipv4/ip_local_port_range", encoding="utf-8") as stream:
            first = stream.read().split()
        return min(LINUX_DEFAULT_EPHEMERAL_START, int(first[0]))
    except (OSError, ValueError, IndexError):
        return LINUX_DEFAULT_EPHEMERAL_START


def window():
    """The range to choose from, or None when this host leaves no room below its ephemeral start."""
    high = ephemeral_start() - 1
    if high < FLOOR:
        return None
    return FLOOR, high


def choose(count, *, rng=None):
    """`count` distinct ports in that window that are free right now, or None to let the daemon pick.

    Each candidate is bound to prove it is free, and every one is held until the whole set is found,
    so this cannot hand back the same port twice or race itself. They are released together, just
    before the stack is written, which leaves a gap between proving a port free and the daemon taking
    it. That gap is real; what closes it in practice is that no ephemeral allocator draws from this
    window, so the only thing that could take the port in between is a program binding it on purpose.

    Returning None is not a failure. It means this host has no such window, and the caller falls back
    to the daemon's own choice - which is what every run did before this existed.
    """
    span = window()
    if span is None or count <= 0:
        return None
    low, high = span
    picker = rng or random.Random()
    picked, held = [], []
    try:
        for _ in range(TRIES):
            if len(picked) == count:
                break
            candidate = picker.randint(low, high)
            if candidate in picked:
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
    return picked if len(picked) == count else None


def publication(chosen, inside):
    """How to write one published port in a compose spec, for a chosen port or for the daemon's."""
    return f"127.0.0.1:{chosen}:{inside}" if chosen else f"127.0.0.1::{inside}"
