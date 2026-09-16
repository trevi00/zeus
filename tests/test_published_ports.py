"""Which host port a disposable stack publishes, and why it is not the daemon's choice any more.

Symptom A - `127.0.0.1:<published port>` refusing a connection from inside WSL for the whole 30s
readiness bound while the container is up - is reproduced and its mechanism measured in
`docs/zeus/implementation/wsl-port-001/README.md`. Docker Desktop's WSL integration binds the
published port inside the distro once, at container start, and never retries; a port the distro's
own ephemeral allocator was holding at that instant stays refused for the container's whole life.

The invariant these checks hold is the one that takes that case away: **a chosen port is never a
port this host's ephemeral allocator can hand out.** Under the daemon's choice there was no such
invariant, and all seven recorded occurrences landed inside the allocator's range.
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


def test_the_window_sits_below_where_this_host_hands_out_ephemeral_ports():
    span = published_ports.window()
    assert span is not None, "this host should leave room below its ephemeral start"
    low, high = span
    assert low < high
    assert high < published_ports.ephemeral_start()

    measured = local_ephemeral_range()
    if measured is not None:                    # Linux and WSL can be asked directly
        assert high < measured[0], f"the window must end before {measured[0]}"


def test_a_chosen_port_is_never_one_the_ephemeral_allocator_could_hand_out():
    """The counterexample this exists for: every recorded symptom A port was inside that range."""
    recorded = [49784, 59720, 51034, 50682, 56988, 56054, 49294]
    low, high = published_ports.window()

    chosen = published_ports.choose(2)
    assert chosen is not None and len(set(chosen)) == 2

    for port in chosen:
        assert low <= port <= high
        assert port < published_ports.ephemeral_start()
        measured = local_ephemeral_range()
        if measured is not None:
            assert not measured[0] <= port <= measured[1]

    # And the ports that actually failed could not come out of this choice.
    assert all(not low <= port <= high for port in recorded)


def test_every_chosen_port_was_proved_free_and_they_are_distinct():
    chosen = published_ports.choose(3)
    assert chosen is not None and len(set(chosen)) == 3
    for port in chosen:
        held = socket.socket()
        try:
            held.bind(("127.0.0.1", port))      # still free, so the proof was about this host
        finally:
            held.close()


def test_a_busy_port_is_not_handed_back(monkeypatch):
    """A port something else holds must be skipped, not returned because the number looked right."""
    low, high = published_ports.window()
    blocked = socket.socket()
    blocked.bind(("127.0.0.1", 0))
    # Force the picker at a port that is certainly taken first, then a fresh one.
    taken = blocked.getsockname()[1]
    sequence = iter([taken, taken, low + 7, low + 8, low + 9])

    class Scripted:
        def randint(self, _low, _high):
            return next(sequence)

    try:
        chosen = published_ports.choose(1, rng=Scripted())
    finally:
        blocked.close()
    assert chosen == [low + 7], "the busy number is skipped and the next free one is used"


def test_a_host_with_no_room_below_its_ephemeral_start_falls_back_to_the_daemon(monkeypatch):
    """Returning None is the old behaviour on purpose, not a failure."""
    monkeypatch.setattr(published_ports, "ephemeral_start", lambda: published_ports.FLOOR)

    assert published_ports.window() is None
    assert published_ports.choose(2) is None
    assert published_ports.publication(None, "5432") == "127.0.0.1::5432"


def test_the_published_form_names_the_chosen_port():
    assert published_ports.publication(20123, "5432") == "127.0.0.1:20123:5432"
    assert published_ports.publication(20124, "6379") == "127.0.0.1:20124:6379"


def test_the_range_is_read_from_this_host_rather_than_assumed():
    measured = local_ephemeral_range()
    if measured is None:
        pytest.skip("this host does not publish ip_local_port_range")
    assert published_ports.ephemeral_start() <= measured[0]


def test_choosing_more_ports_than_the_window_holds_gives_up_rather_than_repeating(monkeypatch):
    """It would rather hand back nothing than hand back the same port twice."""
    monkeypatch.setattr(published_ports, "TRIES", 5)
    only = published_ports.window()[0]
    monkeypatch.setattr(published_ports, "window", lambda: (only, only))

    chosen = published_ports.choose(2, rng=random.Random(0))
    assert chosen is None
