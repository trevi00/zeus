"""The side this process is not on also has to be free — and only a check can say that it is.

Codex's counterexample (review 5217822946, R1): a real Ubuntu process held a port in 24000-24099,
and `choose` running on Windows handed that very port back. The check bound the candidate on the
**calling** host's loopback and called it free, which says nothing about the distro where Docker
Desktop's relay has to bind it.

The two directions are not symmetric, and that is measured rather than assumed
(`docs/zeus/evidence/wsl-port-001/*-daemon-bind-directions.json`):

* an occupant on the **Windows** side makes the daemon refuse to publish - loudly, exit 125, naming
  the port. Nothing silent happens and nothing needs to guess.
* an occupant in the **distro** lets the publish succeed and leaves the port unreachable from inside
  the distro for the container's life. Silent. This is the one a check has to catch beforehand.

So what these hold is: a port is only reported free for a side that was actually asked, and a side
that could not be asked is recorded as not asked.
"""
from __future__ import annotations

import os
import random
import socket
import subprocess

import pytest

from codex_harness.adapters import published_ports

BAND = (24000, 24099)


def wsl_available():
    if os.name != "nt":
        return False
    try:
        done = subprocess.run(["wsl.exe", "-e", "sh", "-c", "echo ok"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and "ok" in (done.stdout or "")


class Pinned:
    """Offer only these numbers as candidates, the way the counterexample pinned its RNG.

    A random pick inside the band is not the case worth holding: it almost never lands on the port
    the peer is holding, so it passes against an implementation that never asks the peer at all.
    """

    def __init__(self, *ports):
        self.ports = list(ports)
        self.rng = random.Random(0)

    def randint(self, _low, _high):
        return self.rng.choice(self.ports)


def hold_in_distro(port):
    """Hold a port inside the distro from a real process there, and hand back a stopper."""
    script = (f"import socket,sys,time\n"
              f"s=socket.socket()\n"
              f"s.bind(('127.0.0.1',{port}))\n"
              f"s.listen(1)\n"
              f"print('held',flush=True)\n"
              f"sys.stdin.readline()\n")
    child = subprocess.Popen(["wsl.exe", "-e", "python3", "-c", script],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    first = child.stdout.readline()
    if "held" not in first:
        child.kill()
        pytest.skip("could not hold a port inside the distro")
    return child


def release(child):
    try:
        child.stdin.write("\n")
        child.stdin.flush()
        child.wait(timeout=15)
    except Exception:
        child.kill()


def offered(result):
    """The ports out of a choice, whichever shape the choice comes back in.

    This one check has to be about behaviour and not about the record's shape: an earlier version
    returned a bare list, and a test that only broke on the new keys would fail against it for the
    wrong reason and prove nothing.
    """
    if result is None:
        return None
    return result["ports"] if isinstance(result, dict) else list(result)


@pytest.mark.skipif(not wsl_available(), reason="needs a WSL distro reachable over interop")
def test_a_port_the_distro_already_holds_is_never_handed_back():
    """The counterexample: Windows said 24000 was free while Ubuntu was holding it."""
    port = BAND[0]
    holder = hold_in_distro(port)
    try:
        ports = offered(published_ports.choose(1, rng=Pinned(port)))
        assert ports is None or port not in ports, (
            f"{port} is held inside the distro; it must not come back as free")
    finally:
        release(holder)


@pytest.mark.skipif(not wsl_available(), reason="needs a WSL distro reachable over interop")
def test_giving_up_on_a_band_the_distro_owns_says_why():
    """When the only candidates are all held over there, the record says so instead of guessing."""
    holders = [hold_in_distro(port) for port in range(BAND[0], BAND[0] + 3)]

    try:
        chosen = published_ports.choose(1, rng=Pinned(*range(BAND[0], BAND[0] + 3)))
        assert chosen["ports"] is None
        assert chosen["fallback"] == "candidates_exhausted"
        assert chosen["sides"]["peer"]["checked"] is True
    finally:
        for holder in holders:
            release(holder)


@pytest.mark.skipif(not wsl_available(), reason="needs a WSL distro reachable over interop")
def test_the_record_names_which_sides_were_asked_and_how():
    chosen = published_ports.choose(2)
    sides = chosen["sides"]

    assert set(sides) >= {"local", "peer"}
    for name, side in sides.items():
        assert side["kind"], name
        assert isinstance(side["checked"], bool), name
        if side["checked"]:
            assert side["how"], f"{name} says it was checked, so it must say how"
        else:
            assert side["why_not"], f"{name} was not checked, so it must say why"

    assert sides["local"]["checked"] is True and sides["local"]["how"] == "bind"
    assert sides["peer"]["kind"].startswith("wsl:"), "the distro is named, not just 'the other side'"


def test_an_unaskable_peer_is_recorded_as_unasked_rather_than_free(monkeypatch):
    """Not being able to ask is not an answer - the same rule the diagnosis module follows."""
    monkeypatch.setattr(published_ports, "_peer_ports",
                        lambda: {"kind": "wsl:Ubuntu", "checked": False,
                                 "why_not": "command_failed", "busy": None})

    chosen = published_ports.choose(1)

    assert chosen["ports"], "an unaskable peer does not stop the choice"
    assert chosen["sides"]["peer"]["checked"] is False
    assert chosen["sides"]["peer"]["why_not"] == "command_failed"
    assert chosen["verified_on"] == ["local"], "only the side that answered is claimed"


def test_the_window_source_separates_what_was_read_from_what_was_assumed():
    span = published_ports.window()
    assert span is not None
    low, high, source = span
    assert low < high
    assert source.startswith("measured:") or source.startswith("assumed:")
    if os.name == "nt":
        assert source.startswith("assumed:"), "Windows cannot read the distro's /proc range"
    else:
        assert source.startswith("measured:")


def test_giving_up_says_which_of_the_two_reasons_it_was(monkeypatch):
    monkeypatch.setattr(published_ports, "ephemeral_start",
                        lambda: (published_ports.FLOOR, "assumed:test"))
    assert published_ports.window() is None
    assert published_ports.choose(2)["fallback"] == "no_window"

    monkeypatch.undo()
    only = published_ports.window()[0]
    monkeypatch.setattr(published_ports, "window", lambda: (only, only, "assumed:test"))
    monkeypatch.setattr(published_ports, "TRIES", 4)
    assert published_ports.choose(2)["fallback"] == "candidates_exhausted"


def test_a_daemon_this_code_cannot_place_reports_no_guarantee(monkeypatch):
    """A remote or otherwise unplaceable daemon: say there is no mitigation, do not imply one."""
    monkeypatch.setenv("DOCKER_HOST", "tcp://10.0.0.5:2375")

    chosen = published_ports.choose(2)

    assert chosen["daemon_is_local"] is False
    assert chosen["guarantee"] == "none", "a port free here says nothing about a remote daemon's host"
    assert chosen["ports"] is None, "and nothing is chosen on that promise"


def test_a_port_free_on_both_sides_is_still_a_real_local_socket():
    chosen = published_ports.choose(2)
    if chosen["ports"] is None:
        pytest.skip(f"no ports offered: {chosen['fallback']}")
    for port in chosen["ports"]:
        held = socket.socket()
        try:
            held.bind(("127.0.0.1", port))
        finally:
            held.close()
