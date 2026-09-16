"""Which host port a disposable stack publishes, and how far that choice was actually checked.

Symptom A - `127.0.0.1:<published port>` refusing a connection from inside WSL for the whole 30s
readiness bound while the container is up - is reproduced and its mechanism read off the socket
tables in `docs/zeus/implementation/wsl-port-001/README.md`.

What these checks hold is the scope of the claim, not a promise about every port on the machine:

* the window is below where the sides this code can see hand out ephemeral ports, and the window
  carries the **source** of that number - read from /proc, or assumed;
* a port is only reported free for a side that was asked, and how it was asked is recorded;
* when nothing is chosen, the record says which of the reasons it was.

The cross-host half of this - a port the distro holds while Windows thinks it is free - lives in
`test_published_ports_cross_host.py`, because it needs a real process on the other side.
"""
from __future__ import annotations

import random
import socket

import pytest

from codex_harness.adapters import published_ports


def local_ephemeral_range():
    """What this host actually hands out, read rather than assumed. None where it cannot be read."""
    try:
        with open("/proc/sys/net/ipv4/ip_local_port_range", encoding="utf-8") as stream:
            low, high = stream.read().split()[:2]
        return int(low), int(high)
    except OSError:
        return None


def test_the_window_sits_below_where_this_side_hands_out_ephemeral_ports():
    span = published_ports.window()
    assert span is not None, "this host should leave room below its ephemeral start"
    low, high, source = span
    assert low < high
    assert high < published_ports.ephemeral_start()[0]
    assert source.startswith(("measured:", "assumed:"))

    measured = local_ephemeral_range()
    if measured is not None:                    # Linux and WSL can be asked directly
        assert high < measured[0], f"the window must end before {measured[0]}"
        assert source.startswith("measured:")


def test_a_chosen_port_is_never_one_this_side_could_hand_out_as_ephemeral():
    """Every recorded symptom A port sat inside that range; a chosen one never can."""
    recorded = [49784, 59720, 51034, 50682, 56988, 56054, 49294]
    low, high, _ = published_ports.window()

    chosen = published_ports.choose(2)
    if chosen["ports"] is None:
        pytest.skip(f"no ports offered here: {chosen['fallback']}")
    assert len(set(chosen["ports"])) == 2

    for port in chosen["ports"]:
        assert low <= port <= high
        assert port < published_ports.ephemeral_start()[0]
        measured = local_ephemeral_range()
        if measured is not None:
            assert not measured[0] <= port <= measured[1]

    # And the ports that actually failed could not come out of this window.
    assert all(not low <= port <= high for port in recorded)


def test_every_chosen_port_was_proved_free_here_and_they_are_distinct():
    chosen = published_ports.choose(3)
    if chosen["ports"] is None:
        pytest.skip(f"no ports offered here: {chosen['fallback']}")
    assert len(set(chosen["ports"])) == 3
    for port in chosen["ports"]:
        held = socket.socket()
        try:
            held.bind(("127.0.0.1", port))      # still free, so the proof was about this host
        finally:
            held.close()


def test_a_busy_port_is_not_handed_back():
    """A port something else holds must be skipped, not returned because the number looked right."""
    low, high, _ = published_ports.window()
    blocked = socket.socket()
    blocked.bind(("127.0.0.1", 0))
    taken = blocked.getsockname()[1]
    sequence = iter([taken, taken, low + 7, low + 8, low + 9])

    class Scripted:
        def randint(self, _low, _high):
            return next(sequence)

    try:
        chosen = published_ports.choose(1, rng=Scripted())
    finally:
        blocked.close()
    assert chosen["ports"] == [low + 7], "the busy number is skipped and the next free one is used"


def test_a_host_with_no_room_below_its_ephemeral_start_falls_back_to_the_daemon(monkeypatch):
    """Returning nothing is the old behaviour on purpose, and it says which reason it was."""
    monkeypatch.setattr(published_ports, "ephemeral_start",
                        lambda: (published_ports.FLOOR, "assumed:test"))

    assert published_ports.window() is None
    chosen = published_ports.choose(2)
    assert chosen["ports"] is None and chosen["fallback"] == "no_window"
    assert chosen["verified_on"] == []
    assert published_ports.publication(None, "5432") == "127.0.0.1::5432"


def test_running_out_of_candidates_is_a_different_reason_from_having_no_window(monkeypatch):
    only = published_ports.window()[0]
    monkeypatch.setattr(published_ports, "window", lambda: (only, only, "assumed:test"))
    monkeypatch.setattr(published_ports, "TRIES", 4)

    chosen = published_ports.choose(2, rng=random.Random(0))
    assert chosen["ports"] is None
    assert chosen["fallback"] == "candidates_exhausted", "not the same story as an absent window"


def test_the_published_form_names_the_chosen_port():
    assert published_ports.publication(20123, "5432") == "127.0.0.1:20123:5432"
    assert published_ports.publication(20124, "6379") == "127.0.0.1:20124:6379"


def test_this_side_is_named_rather_than_guessed():
    assert published_ports.here() in {"windows", "wsl", "linux", "posix"}
    measured = local_ephemeral_range()
    if measured is None:
        assert published_ports.ephemeral_start()[1].startswith("assumed:")
    else:
        assert published_ports.ephemeral_start()[1].startswith("measured:")
        assert published_ports.ephemeral_start()[0] <= measured[0]
