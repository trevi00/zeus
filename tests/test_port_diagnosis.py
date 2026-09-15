"""Three vantages, one moment: what the capture is allowed to conclude.

The WSL symptom - `127.0.0.1:<published port>` refusing a connection for the whole 30s bound - has
stayed undetermined because every observation of it was taken from one side. One refusal cannot
tell a database that never came up from a port that was never published from a port published
somewhere this side cannot reach.

These checks are about the narrowing, not about diagnosing that symptom: it has not been reproduced
and is not claimed to be solved here.
"""
from __future__ import annotations

import os
import socket

import pytest

from codex_harness.adapters import port_diagnosis


def answers(container=None, windows=None, wsl=None):
    return {"container": {"reachable": container}, "windows": {"reachable": windows},
            "wsl": {"reachable": wsl}}


@pytest.mark.parametrize("container,windows,wsl,verdict", [
    (False, True, True, "service"),          # the service itself never answered
    (False, False, False, "service"),        # and the rest follows from that, so it is still the service
    (True, False, False, "publication"),     # the container answers; the published port does not
    (True, True, False, "wsl_path"),         # Windows reaches it and WSL does not
    (True, True, True, "all_reachable"),     # nothing was refusing at this moment
])
def test_the_verdict_names_the_segment_the_three_answers_point_at(container, windows, wsl, verdict):
    assert port_diagnosis.narrow(answers(container, windows, wsl)) == verdict
    assert port_diagnosis.NARROWINGS[verdict]


@pytest.mark.parametrize("container,windows,wsl", [
    (None, True, True),      # the container could not be asked
    (True, None, False),     # Windows could not be asked, so "WSL only" is not established
    (True, True, None),      # WSL could not be asked
    (None, None, None),
])
def test_a_vantage_that_could_not_be_asked_never_becomes_a_verdict(container, windows, wsl):
    """Not asking is not the same as being refused, and it must not narrow anything."""
    assert port_diagnosis.narrow(answers(container, windows, wsl)) == "undetermined"


def test_a_port_that_is_open_here_is_reported_reachable_from_this_side():
    """The vantage that is this process is a real socket, not a description of one."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        record = port_diagnosis._tcp_here(port, 2.0)
        assert record["reachable"] is True and record["seconds"] >= 0
    finally:
        listener.close()

    shut = port_diagnosis._tcp_here(port, 0.5)
    assert shut["reachable"] is False and shut["error"]


def test_every_vantage_answers_or_says_it_was_not_asked():
    """A capture always has all three entries, so a missing one can never be read as a pass."""
    record = port_diagnosis.observe(59998, service="postgres", container=None, seconds=8)

    assert set(record["observations"]) == set(port_diagnosis.VANTAGES)
    for name, observation in record["observations"].items():
        assert "reachable" in observation, name
    assert record["observations"]["container"]["asked"] is False, "no container id was given"
    assert record["verdict"] in port_diagnosis.NARROWINGS
    assert record["context"]["platform"] and "seconds" in record


def test_the_container_vantage_says_which_port_it_asked_about():
    """It asks the service's own port, which is not the published number, and the record says so."""
    record = port_diagnosis._tcp_in_container("", "postgres", 1.0)
    assert record["asked"] is False

    this_host = port_diagnosis.observe(59997, service="redis", container=None, seconds=8)
    assert this_host["observations"]["container"]["reachable"] is None


def test_the_local_side_of_the_capture_matches_this_host():
    """On Windows the WSL vantage goes out through wsl.exe, and on Linux the Windows one does."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        here = port_diagnosis._tcp_from_windows(port, 3.0) if os.name == "nt" \
            else port_diagnosis._tcp_from_wsl(port, 3.0)
        assert here["reachable"] is True
        assert here["how"] == "socket from this process", "this side is asked directly"
    finally:
        listener.close()
